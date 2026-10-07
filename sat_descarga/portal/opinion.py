"""
Descarga del Reporte de Opinión de Cumplimiento (32-D) vía el portal del SAT, con
autenticación CIEC (RFC + contraseña) o e.firma (FIEL). Reutiliza el login genérico
de `portal/login.py`, igual que la constancia.

Flujo (confirmado contra el portal real, mayo 2026):
  1. Entrada por el enlace «Ingresa» del trámite "Opinión del cumplimiento":
     `https://ptsc32d.clouda.sat.gob.mx/?/reporteOpinion32DContribuyente`. El SPA
     dispara un login OAuth2/OIDC con PKCE y redirige a
     `loginda.siat.sat.gob.mx/nidp/app/login?id=ciec...` (los params PKCE/state/nonce
     son EFÍMEROS → NO se hardcodean: se entra por el SPA y él genera el flujo fresco).
  2. El form de login es el MISMO widget NIDP del SAT (selectores confirmados, ya
     compartidos por la constancia): `input#rfc` / `input#password` / captcha
     `img[src^="data:image"]` + `input#userCaptcha` / enviar `input#submit` / e.firma
     `#buttonFiel`. CIEC pide captcha (browser visible); e.firma es automático.
  3. Tras enviar: `loginda.../nidp/oauth/nam/authz?...` → callback →
     `ptsc32d.clouda.sat.gob.mx/#/reporteOpinion32DContribuyente`. OJO: entrada y
     landing comparten host; se distinguen por `?/` (entrada) vs `#/` (landing).
  4. NO hay botón "Generar": el SPA pide y RINDE el PDF en un visor del navegador. Se
     captura la respuesta del PDF DESDE EL NAVEGADOR (listener `response` a nivel de
     contexto), igual que con la constancia (no re-pedir con APIRequestContext).

Requiere playwright (+ chromium). El browser es headful porque CIEC tiene captcha.
"""

import datetime
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .login import iniciar_sesion_ciec, iniciar_sesion_fiel
from .. import demo

logger = logging.getLogger(__name__)

# URL de entrada: el enlace «Ingresa» del trámite. Al cargar, el SPA inicia el
# OAuth2/PKCE fresco y redirige al login NIDP (loginda). NO hardcodear la URL NIDP:
# sus params PKCE/state/nonce son efímeros (pantalla en blanco si se reusan).
OPINION_URL_ENTRADA = "https://ptsc32d.clouda.sat.gob.mx/?/reporteOpinion32DContribuyente"
# e.firma entra por la misma URL; el login FIEL cambia a e.firma con #buttonFiel.
OPINION_URL_ENTRADA_FIEL = OPINION_URL_ENTRADA
# Host del SPA del trámite (para el predicado de aterrizaje).
OPINION_LANDING = "ptsc32d.clouda.sat.gob.mx"


def _es_landing_opinion(url: str) -> bool:
    """
    True cuando ya estamos en el SPA autenticado del reporte 32-D.

    Entrada y landing comparten host (`ptsc32d.clouda.sat.gob.mx`), así que un
    predicado de solo-host dispararía en la navegación de ENTRADA (antes del login).
    Se distinguen:
      - entrada:  `.../?/reporteOpinion32DContribuyente`  (query `/...`)
      - callback: `.../oauth2/callback`                   (transitorio)
      - landing:  `.../#/reporteOpinion32DContribuyente`  (hash route)
    OJO: se compara el HOST parseado, no un substring de la URL completa: la página
    de login de loginda lleva un `target=` codificado que contiene el hostname de
    ptsc32d literal (y `/oauth` como `%2Foauth`), así que un substring dispara un
    falso "login exitoso" EN el propio login (visto en corrida real, jul 2026:
    Sentry TODOCONTA-DESKTOP-Z).
    """
    try:
        p = urlparse((url or "").lower())
    except ValueError:
        return False
    return (
        p.hostname == "ptsc32d.clouda.sat.gob.mx"
        and not p.query.startswith("/")
        and "/oauth" not in p.path
    )


class OpinionClient:
    """Cliente para descargar el Reporte de Opinión de Cumplimiento 32-D (portal)."""

    def __init__(self, rfc: str = "", ciec: str = "", headless: bool = True):
        self.rfc = (rfc or "").strip().upper()
        self.ciec = ciec
        self.headless = headless

    def descargar(
        self,
        directorio_salida: str = "./opinion/",
        url_entrada: str = OPINION_URL_ENTRADA,
        login=None,
        rfc_nombre: Optional[str] = None,
        pedir_captcha=None,
    ) -> Optional[Path]:
        """
        Descarga el Reporte de Opinión de Cumplimiento 32-D (PDF).

        Args:
            url_entrada: URL por donde inicia el login (configurable: el SAT puede
                cambiar la entrada del SSO).
            login: callable(page) que autentica y aterriza en la pantalla del reporte.
                Por defecto usa CIEC (RFC + contraseña). Para e.firma se inyecta un
                login FIEL. La navegación/captura es agnóstica al método.
            rfc_nombre: RFC para nombrar el PDF (útil en FIEL, donde se extrae del .cer).

        Returns:
            Path al PDF descargado, o None si no se pudo capturar.
        """
        try:
            from playwright.sync_api import sync_playwright
            from playwright.sync_api import TimeoutError as PWTimeout
        except ImportError:
            raise ImportError(
                "playwright no está instalado. Ejecuta:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )

        from .setup import asegurar_chromium, lanzar_chromium
        asegurar_chromium()

        out_dir = Path(directorio_salida)
        out_dir.mkdir(parents=True, exist_ok=True)
        fecha = datetime.date.today().strftime("%Y%m%d")
        rfc_nombre = (rfc_nombre or self.rfc or "opinion").strip().upper()
        dest = out_dir / f"opinion32d_{rfc_nombre}_{fecha}.pdf"

        with sync_playwright() as p:
            browser = lanzar_chromium(p, headless=self.headless, slow_mo=80)
            context = browser.new_context(
                accept_downloads=True,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )

            # El PDF se rinde al aterrizar (sin click), así que el listener debe estar
            # activo ANTES de que el SPA lo pida. Se engancha a nivel de contexto para
            # capturarlo en cualquier página/frame.
            capturado: dict = {}
            self._instalar_captura(context, capturado)

            page = context.new_page()
            try:
                if login is None:
                    iniciar_sesion_ciec(
                        page, self.rfc, self.ciec,
                        url_entrada=url_entrada,
                        exito=_es_landing_opinion,
                        pedir_captcha=pedir_captcha,
                    )
                else:
                    login(page)
                try:
                    page.wait_for_load_state("networkidle", timeout=20_000)
                except PWTimeout:
                    pass

                logger.info("[32D] En la pantalla del reporte. Esperando el PDF...")
                ok = self._esperar_pdf(page, capturado, dest, timeout_ms=40_000)
                if ok:
                    logger.info("[32D] ✓ Opinión 32-D guardada: %s (%d bytes)",
                                dest, dest.stat().st_size)
                    return dest

                logger.error("%s", self._diagnostico(page, capturado))
                return None
            finally:
                browser.close()

    def _instalar_captura(self, context, capturado: dict) -> None:
        """
        Engancha un listener `response` a nivel de contexto que guarda los bytes del
        primer PDF que vea (por content-type, extensión o magic `%PDF-`). Se captura
        DESDE EL NAVEGADOR (Chromium tolera el TLS del SAT); NO se re-pide con
        APIRequestContext. Lleva además un registro de respuestas candidatas para
        diagnosticar si el visor sirve el PDF de forma inesperada (p. ej. base64/JSON).
        """
        candidatos = capturado.setdefault("_candidatos", [])

        def _on_resp(resp):
            if "body" in capturado:
                return
            ct = (resp.headers.get("content-type") or "").lower()
            url = resp.url.lower()
            # Registrar candidatos para diagnóstico: además del PDF/reporte, la danza
            # OAuth (authz/callback/login) para reconstruir el flujo si el visor no
            # rinde el PDF (la corrida real de jul 2026 se atoró rebotando en authz).
            if ("pdf" in ct or url.endswith(".pdf") or "reporte" in url
                    or "opinion" in url or "/oauth" in url or "/authz" in url
                    or "/nidp/" in url):
                if len(candidatos) < 40:
                    candidatos.append(f"{resp.status} {ct or '?'} {resp.url}")
            if not ("pdf" in ct or url.endswith(".pdf")):
                return
            try:
                b = resp.body()
                if b[:5] == b"%PDF-":
                    capturado["body"] = b
                    logger.info("[32D] PDF capturado del navegador: %s (%d bytes)",
                                resp.url, len(b))
            except Exception:
                pass

        context.on("response", _on_resp)
        context.on("download", lambda d: capturado.setdefault("download", d))

    def _esperar_pdf(self, page, capturado: dict, dest: Path, timeout_ms: int) -> bool:
        """Espera (polling) a que el listener capture el PDF; fallbacks de descarga/visor."""
        import time

        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            if "body" in capturado:
                dest.write_bytes(capturado["body"])
                return dest.stat().st_size > 0
            if "download" in capturado:
                try:
                    capturado["download"].save_as(str(dest))
                    if dest.exists() and dest.stat().st_size > 0:
                        return True
                except Exception as e:
                    logger.warning("[32D] no se pudo guardar la descarga: %s", e)
            page.wait_for_timeout(500)

        # Fallback: el visor puede ser un <embed>/<iframe>/<object> apuntando al PDF.
        # Si su src es http(s), re-navegamos un page nuevo ahí (browser-side, TLS OK).
        src = self._buscar_src_pdf(page)
        if src and src.startswith("http"):
            try:
                pg = page.context.new_page()
                resp = pg.goto(src, wait_until="commit", timeout=15_000)
                if resp:
                    body = resp.body()
                    if body[:5] == b"%PDF-":
                        dest.write_bytes(body)
                        pg.close()
                        return dest.stat().st_size > 0
                pg.close()
            except Exception as e:
                logger.info("[32D] el src del visor no entregó PDF: %s", e)
        return False

    def _buscar_src_pdf(self, page) -> Optional[str]:
        """Busca en todos los frames un embed/iframe/object cuyo src apunte al PDF."""
        sels = ('embed[src]', 'iframe[src]', 'object[data]')
        for frame in page.frames:
            for sel in sels:
                try:
                    for el in frame.query_selector_all(sel):
                        src = el.get_attribute("src") or el.get_attribute("data") or ""
                        if src and (".pdf" in src.lower() or "pdf" in src.lower()):
                            return src
                except Exception:
                    continue
        return None

    def _diagnostico(self, page, capturado: dict) -> str:
        """Arma el reporte de pistas para afinar la captura si la corrida real falla.

        Devuelve UN solo string multilínea (un solo logger.error ⇒ un solo issue en
        Sentry; loggear línea por línea creaba 3-4 issues por fallo)."""
        lineas = [f"[32D] No se capturó el PDF del reporte. URL: {page.url}"]
        lineas.append(f"frames: {[f.url for f in page.frames]}")
        cands = capturado.get("_candidatos") or []
        if cands:
            lineas.append("respuestas candidatas (status content-type url):")
            lineas.extend(f"  - {c}" for c in cands)
        src = self._buscar_src_pdf(page)
        if src:
            lineas.append(f"src del visor detectado (no http o sin %PDF-): {src}")
        return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Funciones públicas de conveniencia
# ---------------------------------------------------------------------------

def descargar_opinion_ciec(
    rfc: str,
    ciec: str,
    directorio_salida: str = "./opinion/",
    headless: bool = True,
    url_entrada: str = OPINION_URL_ENTRADA,
    pedir_captcha=None,
) -> Optional[Path]:
    """
    Descarga el Reporte de Opinión de Cumplimiento 32-D del portal del SAT (CIEC).

    El browser corre HEADLESS: solo aparece una mini-ventana con la imagen del captcha
    para teclearlo (hasta 3 intentos). El resto (navegación + captura del PDF) es
    automático. `headless=False` solo para depurar. `pedir_captcha` permite inyectar otra
    UI de captcha (p. ej. el bridge del agente). `url_entrada` permite ajustar la URL de
    inicio del login si el SAT la cambia.
    """
    if demo.aplica(rfc):  # modo de grabación: empresa de demo, sin SAT
        from ..demo import sat as sat_demo
        return sat_demo.opinion(rfc, directorio_salida, pedir_captcha=pedir_captcha)
    client = OpinionClient(rfc=rfc, ciec=ciec, headless=headless)
    return client.descargar(
        directorio_salida=directorio_salida, url_entrada=url_entrada,
        pedir_captcha=pedir_captcha,
    )


def descargar_opinion_fiel(
    cer_path: str,
    key_path: str,
    password: str,
    directorio_salida: str = "./opinion/",
    headless: bool = True,
) -> Optional[Path]:
    """
    Descarga el Reporte de Opinión de Cumplimiento 32-D usando e.firma (FIEL).

    El browser corre HEADLESS por default (espejo del flujo CIEC). El login con
    e.firma es 100% automático (no hay captcha). `headless=False` SOLO para depurar
    si el autollenado de .cer/.key/contraseña falla y necesitas completarlo a mano.
    """
    rfc_demo = demo.aplica_archivos_fiel(cer_path, key_path, password)
    if rfc_demo:  # modo de grabación: empresa de demo, sin SAT
        from ..demo import sat as sat_demo
        return sat_demo.opinion(rfc_demo, directorio_salida, con_captcha=False)

    # El RFC para nombrar el PDF se extrae del certificado.
    rfc = ""
    try:
        from ..core.fiel import FIEL
        rfc = FIEL(cer_path, key_path, password).rfc
    except Exception as e:
        logger.warning("[FIEL] no se pudo leer el RFC del .cer: %s", e)

    client = OpinionClient(rfc=rfc, headless=headless)
    login = lambda page: iniciar_sesion_fiel(
        page, cer_path, key_path, password,
        url_entrada=OPINION_URL_ENTRADA_FIEL,
        exito=_es_landing_opinion,
    )
    return client.descargar(
        directorio_salida=directorio_salida, login=login, rfc_nombre=rfc,
    )
