"""Soporte en modo BORRADOR: clasifica el correo de soporte@ y redacta
respuestas que Israel aprueba — este agente NO responde solo a nadie (regla v1).

Realidad del buzón (Workspace de Israel): soporte@todoconta.com es un ALIAS
que entrega en su cuenta real (dominio @sicastro.com) — no existe un buzón
separado. Por eso el agente:

  - Hace login IMAP con la CUENTA REAL (SOPORTE_EMAIL + su app password) pero
    SOLO procesa correos dirigidos al alias (SOPORTE_ALIAS) — jamás lee el
    resto del buzón.
  - NUNCA toca banderas de leído/no-leído ni modifica nada del buzón (INBOX se
    abre readonly): la deduplicación va exclusivamente por Message-ID en /data.
  - Busca en una ventana corta (SOPORTE_VENTANA_DIAS, default 2) para no
    barrer correo viejo ya atendido al encenderse.

Cada corrida:
  1. Busca correos al alias en la ventana (Gmail X-GM-RAW; fallback IMAP
     estándar), descartando auto-respuestas/boletines, correo propio y lo ya
     procesado.
  2. Lee en local (sin LLM, lib/adjuntos.py) los PDF adjuntos —la Constancia de
     Situación Fiscal incluida— y clasifica con Claude (categoría, urgencia,
     resumen) redactando un borrador con contexto real del producto. Al modelo
     solo le llega QUÉ se leyó; los datos fiscales van únicamente en el aviso a
     Israel.
  3. Deja el borrador EN LA CARPETA BORRADORES (hilado a la conversación, con
     remitente soporte@todoconta.com — Gmail lo respeta como send-as del
     alias) y avisa a Israel por correo con el original + la clasificación.

Uso:
    python agents/soporte.py            # corre (si está encendido)
    python agents/soporte.py --dry-run  # imprime clasificación/borradores, no toca nada

Kill switch: OPS_SOPORTE_ENABLED != "1" → no hace nada (default APAGADO).
Requiere: SOPORTE_EMAIL (cuenta real) + SOPORTE_APP_PASSWORD (app password de
esa cuenta, con verificación en 2 pasos activa).
"""

from __future__ import annotations

import email
import email.utils
import html as html_mod
import imaplib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.mime.text import MIMEText
from pathlib import Path

from lib import adjuntos, correo, llm

ESTADO = Path("/data/soporte_estado.json")
MAX_PROCESADOS_GUARDADOS = 500

REMITENTES_AUTO = re.compile(
    r"no-?reply|mailer-daemon|postmaster|bounce|notificacion|donotreply", re.I
)

SISTEMA = (
    "Eres el agente de soporte de TodoConta (todoconta.com): app de escritorio "
    "(Windows/macOS) para contadores en México que descarga CFDI y documentos "
    "del SAT de forma masiva, con versión web en app.todoconta.com. Contexto "
    "real del producto: prueba gratis de 15 días al registrarse; plan Anual "
    "$2,990 MXN y Anual con IA $4,990 MXN (incluye Abacus, asistente fiscal por "
    "WhatsApp); métodos de acceso al SAT: e.firma (sin captcha), Contraseña del "
    "SAT (antes CIEC, con captcha) y Web Service para volumen; la e.firma y las "
    "contraseñas se guardan cifradas en el equipo del usuario (\"tú decides "
    "dónde viven tus datos\"); descargas: CFDI emitidos/recibidos, Constancia de "
    "Situación Fiscal, Opinión de cumplimiento 32-D, DIOT 2025; procesadores "
    "XML→Excel y calculadoras fiscales; soporte humano: Israel Castro. Redacta "
    "en español de México, cálido y directo, máximo 180 palabras, firmando "
    "\"Israel — TodoConta\". Si el problema requiere datos que no tienes (logs, "
    "capturas, versión), pídelos. NUNCA prometas fechas de features ni "
    "reembolsos: eso lo decide Israel (déjalo como [ISRAEL DECIDE] si aplica). "
    "Nunca digas \"CIEC\" a secas ni \"espejo\" (di \"versión web\"). Si el correo "
    "trae un bloque ADJUNTOS, ahí dice qué archivos leyó el sistema: lo que ya "
    "se leyó NO se vuelve a pedir (si la Constancia de Situación Fiscal ya fue "
    "leída, confirma que la recibimos y no pidas razón social, RFC, domicilio "
    "ni régimen; ante una solicitud de factura pide solo lo que falte, como el "
    "uso de CFDI si el cliente no lo dijo). No menciones el cifrado ni dónde se "
    "guardan los datos salvo que el cliente pregunte por privacidad o seguridad."
)


def _decodificar(valor: str | None) -> str:
    if not valor:
        return ""
    partes = []
    for texto, charset in decode_header(valor):
        if isinstance(texto, bytes):
            partes.append(texto.decode(charset or "utf-8", errors="replace"))
        else:
            partes.append(texto)
    return "".join(partes)


def _cuerpo_texto(msg: email.message.Message) -> str:
    """Extrae texto plano (o HTML desetiquetado) del mensaje."""
    def _decodifica_parte(parte: email.message.Message) -> str:
        payload = parte.get_payload(decode=True) or b""
        charset = parte.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")

    if msg.is_multipart():
        html_fallback = ""
        for parte in msg.walk():
            tipo = parte.get_content_type()
            if "attachment" in str(parte.get("Content-Disposition", "")):
                continue
            if tipo == "text/plain":
                return _decodifica_parte(parte)
            if tipo == "text/html" and not html_fallback:
                html_fallback = _decodifica_parte(parte)
        texto = re.sub(r"<[^>]+>", " ", html_fallback)
        return html_mod.unescape(re.sub(r"\s+", " ", texto)).strip()
    if msg.get_content_type() == "text/html":
        texto = re.sub(r"<[^>]+>", " ", _decodifica_parte(msg))
        return html_mod.unescape(re.sub(r"\s+", " ", texto)).strip()
    return _decodifica_parte(msg)


def _es_automatico(msg: email.message.Message, de_email: str) -> bool:
    if REMITENTES_AUTO.search(de_email or ""):
        return True
    auto = str(msg.get("Auto-Submitted", "no")).lower()
    if auto and auto != "no":
        return True
    if str(msg.get("Precedence", "")).lower() in ("bulk", "junk", "list"):
        return True
    if msg.get("List-Unsubscribe"):
        return True
    return False


def _buscar_al_alias(imap: imaplib.IMAP4_SSL, alias: str, dias: int) -> list[bytes]:
    """UIDs de correos dirigidos al alias dentro de la ventana.

    Primero con búsqueda nativa de Gmail (X-GM-RAW: su `to:` cubre To/Cc y la
    entrega al alias); si el servidor no la soporta, IMAP estándar (TO/CC +
    SINCE). Nunca usa UNSEEN: las banderas son de Israel, no del agente.
    """
    try:
        ok, resultado = imap.uid(
            "SEARCH", "X-GM-RAW", f'"to:{alias} newer_than:{dias}d"'
        )
        if ok == "OK":
            return resultado[0].split() if resultado and resultado[0] else []
    except imaplib.IMAP4.error:
        pass
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%d-%b-%Y")
    ok, resultado = imap.uid(
        "SEARCH", None, f'(OR TO "{alias}" CC "{alias}") SINCE {desde}'
    )
    if ok != "OK":
        return []
    return resultado[0].split() if resultado and resultado[0] else []


def _carpeta_borradores(imap: imaplib.IMAP4_SSL) -> str | None:
    """Encuentra la carpeta con flag \\Drafts (Gmail la nombra según idioma)."""
    ok, carpetas = imap.list()
    if ok != "OK" or not carpetas:
        return None
    for linea in carpetas:
        texto = linea.decode("utf-8", errors="replace") if isinstance(linea, bytes) else str(linea)
        if "\\Drafts" in texto:
            m = re.search(r'"([^"]+)"\s*$', texto)
            if m:
                return m.group(1)
    return None


def _cargar_estado() -> dict:
    if ESTADO.exists():
        try:
            return json.loads(ESTADO.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {"procesados": []}


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    if os.environ.get("OPS_SOPORTE_ENABLED", "0") != "1" and not dry_run:
        print("[soporte] apagado por OPS_SOPORTE_ENABLED — no se hace nada")
        return 0

    cuenta = os.environ.get("SOPORTE_EMAIL")
    password = os.environ.get("SOPORTE_APP_PASSWORD")
    if not cuenta or not password:
        print("[soporte] faltan SOPORTE_EMAIL/SOPORTE_APP_PASSWORD")
        return 1
    alias = os.environ.get("SOPORTE_ALIAS", "soporte@todoconta.com")
    ventana = int(os.environ.get("SOPORTE_VENTANA_DIAS", "2"))
    max_corrida = int(os.environ.get("OPS_SOPORTE_MAX", "10"))
    estado = _cargar_estado()
    procesados: list[str] = estado.get("procesados", [])

    imap = imaplib.IMAP4_SSL(os.environ.get("SOPORTE_IMAP_HOST", "imap.gmail.com"))
    try:
        imap.login(cuenta, password)
        # readonly: este buzón es el personal de Israel — el agente jamás lo
        # modifica (ni banderas ni borrados). El APPEND del borrador va a la
        # carpeta Borradores, que no requiere escribir en INBOX.
        imap.select("INBOX", readonly=True)
        uids = _buscar_al_alias(imap, alias, ventana)
        if not uids:
            print(f"[soporte] sin correos nuevos para {alias}")
            return 0

        borradores = None if dry_run else _carpeta_borradores(imap)
        atendidos = 0
        for uid in uids:
            if atendidos >= max_corrida:
                break
            ok, datos = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            if ok != "OK" or not datos or not isinstance(datos[0], tuple):
                continue
            msg = email.message_from_bytes(datos[0][1])
            # Llave de dedupe: Message-ID (o el UID como último recurso).
            clave = str(msg.get("Message-ID", "")).strip() or f"uid:{uid.decode()}"
            if clave in procesados:
                continue

            de_nombre, de_email = email.utils.parseaddr(_decodificar(msg.get("From")))
            asunto = _decodificar(msg.get("Subject")) or "(sin asunto)"
            # Correo propio (Israel respondiendo con copia al alias): ignorar.
            if de_email.lower() in (cuenta.lower(), alias.lower()):
                if not dry_run:
                    procesados.append(clave)
                continue
            if _es_automatico(msg, de_email):
                if not dry_run:
                    procesados.append(clave)
                print(f"[soporte] auto/boletín descartado: {de_email} — {asunto[:60]}")
                continue

            cuerpo = _cuerpo_texto(msg)[:6000]
            analisis = adjuntos.analizar(msg)
            resumen_adjuntos = adjuntos.para_israel(analisis)
            resultado_llm = llm.generar_json(
                "Clasifica este correo de soporte y redacta el borrador de "
                'respuesta. Responde JSON: {"categoria": "tecnico|facturacion|'
                'ventas|cuenta|otro|no_requiere_respuesta", "urgencia": "alta|'
                'media|baja", "resumen": "1-2 oraciones", "borrador": "texto '
                'plano con saltos \\n (vacío si no requiere respuesta)"}\n\n'
                f"DE: {de_nombre} <{de_email}>\nASUNTO: {asunto}\n\nCUERPO:\n{cuerpo}"
                f"{adjuntos.para_llm(analisis)}",
                sistema=SISTEMA,
                max_tokens=1200,
            ) or {
                "categoria": "sin_clasificar",
                "urgencia": "media",
                "resumen": "(sin ANTHROPIC_API_KEY: clasificación no disponible)",
                "borrador": "",
            }
            categoria = str(resultado_llm.get("categoria") or "otro")
            urgencia = str(resultado_llm.get("urgencia") or "media")
            resumen = str(resultado_llm.get("resumen") or "")
            borrador = str(resultado_llm.get("borrador") or "").strip()

            if dry_run:
                print(
                    f"\n───── {de_email} — {asunto} ─────\n"
                    f"[{categoria}/{urgencia}] {resumen}\n\n"
                    + (f"{resumen_adjuntos}\n\n" if resumen_adjuntos else "")
                    + f"BORRADOR:\n{borrador or '(sin respuesta)'}\n"
                )
                atendidos += 1
                continue

            if categoria == "no_requiere_respuesta":
                procesados.append(clave)
                print(f"[soporte] sin respuesta necesaria: {de_email} — {asunto[:60]}")
                continue

            # 1) Borrador hilado en la carpeta Borradores, saliendo como el alias.
            deja_borrador = False
            if borrador and borradores:
                try:
                    respuesta = MIMEText(borrador, "plain", "utf-8")
                    respuesta["From"] = f"TodoConta Soporte <{alias}>"
                    respuesta["To"] = email.utils.formataddr((de_nombre, de_email))
                    respuesta["Subject"] = (
                        asunto if asunto.lower().startswith("re:") else f"Re: {asunto}"
                    )
                    message_id = str(msg.get("Message-ID", "")).strip()
                    if message_id:
                        respuesta["In-Reply-To"] = message_id
                        respuesta["References"] = message_id
                    imap.append(
                        f'"{borradores}"',
                        r"(\Draft)",
                        imaplib.Time2Internaldate(datetime.now(timezone.utc).timestamp()),
                        respuesta.as_bytes(),
                    )
                    deja_borrador = True
                except Exception as e:  # noqa: BLE001
                    print(f"[soporte] no pude dejar el borrador en Gmail: {e}")

            # 2) Aviso a Israel con todo el contexto.
            nota_borrador = (
                "El borrador ya está en tu carpeta Borradores (hilado; sale como "
                f"{alias}): ajústalo y envía."
                if deja_borrador
                else "No se pudo dejar el borrador en Gmail — cópialo de aquí."
            )
            texto_aviso = (
                f"De: {de_nombre} <{de_email}>\nAsunto: {asunto}\n"
                f"Clasificación: {categoria} / urgencia {urgencia}\n\n"
                f"Resumen: {resumen}\n\n{nota_borrador}\n\n"
                + (f"{resumen_adjuntos}\n\n" if resumen_adjuntos else "")
                + f"── BORRADOR PROPUESTO ──\n{borrador or '(sin borrador)'}\n\n"
                f"── MENSAJE ORIGINAL ──\n{cuerpo[:3000]}"
            )
            html_aviso = (
                '<div style="font-family:system-ui,sans-serif;font-size:14px;max-width:640px;color:#111">'
                f"<p><b>De:</b> {html_mod.escape(de_nombre)} &lt;{html_mod.escape(de_email)}&gt;<br>"
                f"<b>Asunto:</b> {html_mod.escape(asunto)}<br>"
                f"<b>Clasificación:</b> {html_mod.escape(categoria)} · urgencia {html_mod.escape(urgencia)}</p>"
                f"<p>{html_mod.escape(resumen)}</p><p><i>{html_mod.escape(nota_borrador)}</i></p>"
                + (
                    '<div style="white-space:pre-wrap;background:#eef4ee;border-radius:8px;'
                    f'padding:12px;margin-bottom:12px">{html_mod.escape(resumen_adjuntos)}</div>'
                    if resumen_adjuntos
                    else ""
                )
                + f'<h4 style="margin-bottom:4px">Borrador propuesto</h4>'
                f'<div style="white-space:pre-wrap;background:#f6f6f3;border-radius:8px;padding:12px">{html_mod.escape(borrador or "(sin borrador)")}</div>'
                f'<h4 style="margin-bottom:4px">Mensaje original</h4>'
                f'<div style="white-space:pre-wrap;color:#52514e">{html_mod.escape(cuerpo[:3000])}</div></div>'
            )
            try:
                correo.enviar(
                    f"[{alias}] {urgencia} · {categoria} — {asunto[:70]}",
                    html_aviso,
                    texto_aviso,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[soporte] aviso a Israel falló: {e} — NO registro para reintentar")
                continue

            procesados.append(clave)
            atendidos += 1
            print(f"[soporte] atendido: {de_email} — {asunto[:60]} [{categoria}/{urgencia}]")

        if not dry_run:
            estado["procesados"] = procesados[-MAX_PROCESADOS_GUARDADOS:]
            try:
                ESTADO.write_text(json.dumps(estado))
            except Exception as e:  # noqa: BLE001
                print(f"[soporte] estado no guardado: {e}")
        print(f"[soporte] corrida terminada — {atendidos} mensaje(s) atendidos")
        return 0
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
