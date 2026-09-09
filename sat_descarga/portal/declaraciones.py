"""
Descarga de declaraciones presentadas (Provisionales y Definitivas de Impuestos
Federales) y de sus acuses de recibo desde el portal de declaraciones del SAT, con
autenticación CIEC (captcha) o e.firma (automático). Reutiliza el login genérico de
`portal/login.py`, igual que la constancia y la opinión 32-D.

Flujo (recorrido documentado contra el portal real, sep 2026):
  1. Entrada: `https://pstcdypisr.clouda.sat.gob.mx/`. Redirige al widget NIDP de
     `loginda.siat.sat.gob.mx` (`form#IDPLogin`: #rfc/#password/#userCaptcha o e.firma
     con #buttonFiel → #fileCertificate/#filePrivateKey/#privateKeyPassword/#submit).
  2. Aterriza en el panel de declaraciones (mismo host `pstcdypisr`). El menú
     «Consultas» ofrece `/Consulta/Consulta?tipoDocumento=1` (De la declaración) y
     `?tipoDocumento=3` (Acuse de recibo de la declaración); el form es el mismo.
  3. Form de consulta: #IdDeclaracion (001 = Provisionales y Definitivas),
     #Ejercicio, #Periodicidad (M = mensual; al elegirla se habilita #Periodo con
     001..012) y #btnBuscar. Resultado en `#tableResult tbody#tableBody`, una fila por
     declaración (normal, complementarias, ...) con un link `#linkDescargaPDF` →
     `/Consulta/RecuperarArchivo?enLinea=0&tipoDocumento=N&numeroOperacion=X&ejercicio=AAAA`.
  4. El link descarga el PDF en automático (sin ventana extra). Se descargan TODAS las
     filas del periodo (normal y complementarias) para ambos tipos de documento.

Requiere playwright (+ chromium).
"""

import datetime
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .login import iniciar_sesion_ciec, iniciar_sesion_fiel

logger = logging.getLogger(__name__)

DECLARACIONES_BASE = "https://pstcdypisr.clouda.sat.gob.mx"
# Entrada: la raíz del portal dispara el login NIDP (loginda) fresco.
DECLARACIONES_URL_ENTRADA = DECLARACIONES_BASE + "/"
DECLARACIONES_URL_ENTRADA_FIEL = DECLARACIONES_URL_ENTRADA
DECLARACIONES_LANDING = "pstcdypisr.clouda.sat.gob.mx"

# tipoDocumento del portal: 1 = la declaración, 3 = acuse de recibo de la declaración
# (2 = declaraciones pagadas, 4 = por obligación: no se usan aquí).
TIPOS_DOCUMENTO = {"declaracion": "1", "acuse": "3"}
TIPOS_DEFAULT = ("declaracion", "acuse")
ID_DECLARACION_PROVISIONALES = "001"     # Provisionales y Definitivas de Impuestos Federales
PERIODICIDAD_MENSUAL = "M"

# Columnas de #tableResult (la primera es el link de descarga).
_COLS = ("_link", "numero_operacion", "tipo_declaracion", "tipo_complementaria",
         "linea_captura", "fecha_presentacion", "periodicidad", "periodo",
         "fecha_causacion", "estado")

_RE_PERIODO = re.compile(r"^(\d{4})-(\d{1,2})$")


def _es_landing_declaraciones(url: str) -> bool:
    """True cuando ya estamos en el portal de declaraciones autenticado.

    Entrada y landing comparten host; el login vive en `loginda.siat.sat.gob.mx`, así
    que basta con el host parseado (no substring: el login lleva `target=` con la
    URL de vuelta codificada). Se excluye cualquier ruta `/nidp/` por si el SAT
    moviera el widget al mismo host.
    """
    try:
        p = urlparse((url or "").lower())
    except ValueError:
        return False
    return p.hostname == DECLARACIONES_LANDING and "/nidp" not in p.path


def periodos_entre(desde: str, hasta: Optional[str] = None) -> list[tuple[int, int]]:
    """``"2026-01", "2026-06"`` → ``[(2026, 1), ..., (2026, 6)]`` (inclusivo)."""
    m1 = _RE_PERIODO.match((desde or "").strip())
    m2 = _RE_PERIODO.match((hasta or desde or "").strip())
    if not m1 or not m2:
        raise ValueError("Los periodos van como YYYY-MM (p. ej. 2026-01).")
    a1, mes1 = int(m1.group(1)), int(m1.group(2))
    a2, mes2 = int(m2.group(1)), int(m2.group(2))
    if not (1 <= mes1 <= 12 and 1 <= mes2 <= 12):
        raise ValueError("El mes del periodo debe ir de 01 a 12.")
    if (a1, mes1) > (a2, mes2):
        raise ValueError("El periodo inicial es posterior al final.")
    out, a, m = [], a1, mes1
    while (a, m) <= (a2, mes2):
        out.append((a, m))
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return out


def nombre_archivo(sugerido: Optional[str], tipo: str, numero_operacion: str,
                   rfc: str, ejercicio: int, varias_filas: bool) -> str:
    """Nombre del PDF en disco.

    Se respeta el nombre que sugiere el portal (p. ej. ``RFC.38.2025.pdf``). OJO: el
    portal sugiere el MISMO nombre para la declaración y para su acuse (corrida real,
    sep 2026), así que el acuse lleva el prefijo ``Acuse.`` (``Acuse.RFC.38.2025.pdf``)
    para no pisar la declaración. Si el periodo trae más de una fila (normal +
    complementarias) se agrega el número de operación. Sin nombre sugerido se arma
    uno estable.
    """
    base = Path(sugerido).stem if sugerido and sugerido.lower().endswith(".pdf") else ""
    if not base:
        base = f"{rfc}.{ejercicio}"
    if tipo == "acuse" and not base.lower().startswith("acuse."):
        base = f"Acuse.{base}"
    if varias_filas and numero_operacion and numero_operacion not in base:
        base = f"{base}.{numero_operacion}"
    return base + ".pdf"


INDICE_NOMBRE = "declaraciones.json"


def actualizar_indice(path: Path, registros: list[dict]) -> list[dict]:
    """Funde `registros` en el índice JSON `path` (lista de dicts).

    Clave: (periodo, tipo, numero_operacion). Un registro nuevo reemplaza al viejo con
    la misma clave; el resto se conserva. Se guarda ordenado por periodo, tipo y fecha
    de presentación. Devuelve la lista resultante. Pura salvo por el archivo."""
    import json

    actual: list[dict] = []
    if path.exists():
        try:
            actual = json.loads(path.read_text(encoding="utf-8")) or []
        except (OSError, ValueError):
            logger.warning("[DECL] índice ilegible, se reescribe: %s", path)
            actual = []
    por_clave = {(r.get("periodo"), r.get("tipo"), r.get("numero_operacion")): r for r in actual}
    for r in registros:
        por_clave[(r.get("periodo"), r.get("tipo"), r.get("numero_operacion"))] = r
    salida = sorted(por_clave.values(),
                    key=lambda r: (r.get("periodo") or "", r.get("tipo") or "",
                                   _fecha_iso(r.get("fecha_presentacion")), r.get("numero_operacion") or ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    return salida


def _fecha_iso(ddmmaaaa: Optional[str]) -> str:
    """'17/03/2026' → '2026-03-17' (para ordenar); cualquier otra cosa se devuelve tal cual."""
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", (ddmmaaaa or "").strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else (ddmmaaaa or "")


def declaracion_vigente(registros: list[dict], periodo: str) -> Optional[dict]:
    """La declaración (tipo 'declaracion') más reciente del `periodo`: normalmente la
    última complementaria, si la hay; si no, la normal."""
    cands = [r for r in registros if r.get("periodo") == periodo and r.get("tipo") == "declaracion"]
    if not cands:
        return None
    return max(cands, key=lambda r: (_fecha_iso(r.get("fecha_presentacion")), r.get("numero_operacion") or ""))


def _normalizar_tipos(tipos) -> list[str]:
    if not tipos:
        return list(TIPOS_DEFAULT)
    if isinstance(tipos, str):
        tipos = [tipos]
    out = []
    for t in tipos:
        t = (t or "").strip().lower()
        if t == "ambos":
            out.extend(TIPOS_DEFAULT)
        elif t in TIPOS_DOCUMENTO:
            out.append(t)
        else:
            raise ValueError(f"Tipo de documento inválido: {t!r} (declaracion | acuse | ambos)")
    return list(dict.fromkeys(out))


class DeclaracionesClient:
    """Cliente para descargar declaraciones presentadas y sus acuses (portal)."""

    def __init__(self, rfc: str = "", ciec: str = "", headless: bool = True):
        self.rfc = (rfc or "").strip().upper()
        self.ciec = ciec
        self.headless = headless

    # ------------------------------------------------------------------ público
    def descargar(
        self,
        periodos: list[tuple[int, int]],
        tipos=TIPOS_DEFAULT,
        directorio_salida: str = "./declaraciones/",
        url_entrada: str = DECLARACIONES_URL_ENTRADA,
        login=None,
        rfc_nombre: Optional[str] = None,
        pedir_captcha=None,
    ) -> list[dict]:
        """
        Descarga los PDFs de los `periodos` ((año, mes), mensuales) para los `tipos`
        pedidos ("declaracion" y/o "acuse").

        Args:
            login: callable(page) que autentica y aterriza en el portal. Por defecto
                CIEC; para e.firma se inyecta un login FIEL.
            rfc_nombre: RFC para las carpetas/nombres (en FIEL sale del .cer).

        Returns:
            Lista de dicts, uno por PDF descargado (o fila sin PDF, con `archivo=None`):
            periodo, tipo, numero_operacion, tipo_declaracion, tipo_complementaria,
            fecha_presentacion, estado, archivo.
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

        tipos = _normalizar_tipos(tipos)
        rfc = (rfc_nombre or self.rfc or "sin_rfc").strip().upper()
        out_dir = Path(directorio_salida)
        out_dir.mkdir(parents=True, exist_ok=True)
        resultados: list[dict] = []

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
            page = context.new_page()
            try:
                if login is None:
                    iniciar_sesion_ciec(
                        page, self.rfc, self.ciec,
                        url_entrada=url_entrada,
                        exito=_es_landing_declaraciones,
                        pedir_captcha=pedir_captcha,
                    )
                else:
                    login(page)
                try:
                    page.wait_for_load_state("networkidle", timeout=20_000)
                except PWTimeout:
                    pass

                for anio, mes in periodos:
                    dest_dir = out_dir / f"{anio}-{mes:02d}"
                    for tipo in tipos:
                        filas = self._consultar(page, tipo, anio, mes)
                        logger.info("[DECL] %04d-%02d %s: %d fila(s)", anio, mes, tipo, len(filas))
                        if not filas:
                            continue
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        for fila in filas:
                            archivo = self._descargar_fila(
                                page, fila, tipo, dest_dir, rfc, anio, len(filas) > 1,
                            )
                            resultados.append({
                                "rfc": rfc,
                                "periodo": f"{anio}-{mes:02d}",
                                "ejercicio": anio,
                                "mes": mes,
                                "tipo": tipo,
                                "numero_operacion": fila.get("numero_operacion", ""),
                                "tipo_declaracion": fila.get("tipo_declaracion", ""),
                                "tipo_complementaria": fila.get("tipo_complementaria", ""),
                                "linea_captura": fila.get("linea_captura", ""),
                                "fecha_presentacion": fila.get("fecha_presentacion", ""),
                                "estado": fila.get("estado", ""),
                                "archivo": archivo,
                                "descargado_en": datetime.datetime.now().isoformat(timespec="seconds"),
                            })
            finally:
                browser.close()
        # Índice persistente: tipo de declaración, número de operación y fecha de
        # presentación por periodo, para trámites posteriores (p. ej. la solicitud de
        # devolución pide el número de operación y la fecha de la declaración).
        actualizar_indice(out_dir / INDICE_NOMBRE, resultados)
        return resultados

    # ---------------------------------------------------------------- consulta
    def _consultar(self, page, tipo: str, anio: int, mes: int) -> list[dict]:
        """Llena el form de consulta del `tipo` para (anio, mes) y devuelve las filas."""
        from playwright.sync_api import TimeoutError as PWTimeout

        tipo_doc = TIPOS_DOCUMENTO[tipo]
        page.goto(f"{DECLARACIONES_BASE}/Consulta/Consulta?tipoDocumento={tipo_doc}",
                  wait_until="domcontentloaded")
        try:
            page.wait_for_selector("#Ejercicio", timeout=30_000)
        except PWTimeout:
            raise RuntimeError(
                f"No cargó el form de consulta de declaraciones (URL: {page.url}). "
                "¿La sesión del portal no quedó válida?"
            )
        try:
            page.wait_for_load_state("networkidle", timeout=8_000)
        except PWTimeout:
            pass

        page.select_option("#IdDeclaracion", ID_DECLARACION_PROVISIONALES)
        page.select_option("#Ejercicio", str(anio))
        page.select_option("#Periodicidad", PERIODICIDAD_MENSUAL)
        # Al elegir la periodicidad el portal llena y habilita #Periodo (001..012).
        page.wait_for_function(
            "() => { const s = document.querySelector('#Periodo');"
            " return !!s && !s.disabled && s.options.length > 1; }",
            timeout=20_000,
        )
        page.select_option("#Periodo", f"{mes:03d}")
        page.click("#btnBuscar", no_wait_after=True)

        # Resultado: filas en #tableBody o un aviso bootbox ("sin registros").
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('#tableBody tr').length > 0"
                " || !!document.querySelector('.bootbox .bootbox-body, .modal.show .modal-body')",
                timeout=40_000,
            )
        except PWTimeout:
            logger.warning("[DECL] %04d-%02d %s: la consulta no respondió a tiempo (URL %s).",
                           anio, mes, tipo, page.url)
            return []

        filas = page.evaluate(
            "() => Array.from(document.querySelectorAll('#tableBody tr')).map(tr => ({"
            " href: (tr.querySelector('a') || {}).getAttribute ? tr.querySelector('a').getAttribute('href') : null,"
            " celdas: Array.from(tr.querySelectorAll('td')).map(td => (td.textContent || '').trim())"
            "}))"
        )
        if not filas:
            aviso = page.evaluate(
                "() => { const m = document.querySelector('.bootbox .bootbox-body, .modal.show .modal-body');"
                " return m ? (m.textContent || '').trim() : ''; }"
            )
            logger.info("[DECL] %04d-%02d %s: sin declaraciones (%s)", anio, mes, tipo, aviso or "sin aviso")
            self._cerrar_modal(page)
            return []
        out = []
        for f in filas:
            celdas = f.get("celdas") or []
            fila = {k: (celdas[i] if i < len(celdas) else "") for i, k in enumerate(_COLS)}
            fila["_link"] = f.get("href") or ""
            out.append(fila)
        return out

    def _cerrar_modal(self, page) -> None:
        for sel in (".bootbox .bootbox-accept", ".bootbox button", ".modal.show button"):
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click(timeout=3_000)
                    return
            except Exception:  # noqa: BLE001 — el modal ya se fue o no es clicable
                continue

    # ---------------------------------------------------------------- descarga
    def _descargar_fila(self, page, fila: dict, tipo: str, dest_dir: Path, rfc: str,
                        ejercicio: int, varias: bool) -> Optional[str]:
        """Descarga el PDF de una fila (click en su link; fallback GET con las cookies)."""
        from playwright.sync_api import TimeoutError as PWTimeout

        href = fila.get("_link") or ""
        numop = fila.get("numero_operacion") or ""
        if not href:
            logger.warning("[DECL] fila sin link de descarga (op. %s)", numop)
            return None
        url = href if href.startswith("http") else DECLARACIONES_BASE + href

        sugerido, body = None, None
        try:
            with page.expect_download(timeout=30_000) as dl:
                page.click(f'#tableBody a[href="{href}"]', no_wait_after=True)
            d = dl.value
            sugerido = d.suggested_filename
            tmp = d.path()
            body = Path(tmp).read_bytes() if tmp else None
        except PWTimeout:
            logger.info("[DECL] el link no disparó descarga; se pide por GET (op. %s)", numop)
        except Exception as e:  # noqa: BLE001 — click fallido, etc.
            logger.info("[DECL] click de descarga falló (%s); se pide por GET (op. %s)", e, numop)

        if not body:
            try:
                resp = page.context.request.get(url, timeout=60_000)
                cd = resp.headers.get("content-disposition") or ""
                m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
                if m:
                    sugerido = m.group(1).strip()
                body = resp.body()
            except Exception as e:  # noqa: BLE001
                logger.error("[DECL] no se pudo descargar op. %s: %s", numop, e)
                return None

        if not body or body[:5] != b"%PDF-":
            logger.error("[DECL] la respuesta de op. %s no es un PDF (%d bytes)", numop, len(body or b""))
            return None

        # Idempotente: volver a correr el mismo periodo sobreescribe el PDF (misma
        # declaración → mismo contenido) en vez de acumular copias renombradas.
        nombre = nombre_archivo(sugerido, tipo, numop, rfc, ejercicio, varias)
        dest = dest_dir / nombre
        dest.write_bytes(body)
        logger.info("[DECL] ✓ %s (%d bytes)", dest, len(body))
        return str(dest)


# ---------------------------------------------------------------------------
# Funciones públicas de conveniencia
# ---------------------------------------------------------------------------

def descargar_declaraciones_ciec(
    rfc: str,
    ciec: str,
    desde: str,
    hasta: Optional[str] = None,
    tipos=TIPOS_DEFAULT,
    directorio_salida: str = "./declaraciones/",
    headless: bool = True,
    url_entrada: str = DECLARACIONES_URL_ENTRADA,
    pedir_captcha=None,
) -> list[dict]:
    """
    Declaraciones presentadas y/o acuses (PDF) por periodo mensual, vía CIEC.

    `desde`/`hasta` van como ``YYYY-MM`` (inclusivo; `hasta` opcional = solo `desde`).
    `tipos`: "declaracion", "acuse" o "ambos". El browser corre HEADLESS; solo aparece
    la mini-ventana del captcha. Los PDFs quedan en ``{directorio_salida}/{YYYY-MM}/``.
    """
    client = DeclaracionesClient(rfc=rfc, ciec=ciec, headless=headless)
    return client.descargar(
        periodos_entre(desde, hasta), tipos=tipos, directorio_salida=directorio_salida,
        url_entrada=url_entrada, pedir_captcha=pedir_captcha,
    )


def descargar_declaraciones_fiel(
    cer_path: str,
    key_path: str,
    password: str,
    desde: str,
    hasta: Optional[str] = None,
    tipos=TIPOS_DEFAULT,
    directorio_salida: str = "./declaraciones/",
    headless: bool = True,
) -> list[dict]:
    """
    Declaraciones presentadas y/o acuses (PDF) por periodo mensual, con e.firma.

    100% automático (sin captcha). Mismos parámetros que la variante CIEC.
    """
    rfc = ""
    try:
        from ..core.fiel import FIEL
        rfc = FIEL(cer_path, key_path, password).rfc
    except Exception as e:  # noqa: BLE001
        logger.warning("[FIEL] no se pudo leer el RFC del .cer: %s", e)

    client = DeclaracionesClient(rfc=rfc, headless=headless)
    login = lambda page: iniciar_sesion_fiel(  # noqa: E731
        page, cer_path, key_path, password,
        url_entrada=DECLARACIONES_URL_ENTRADA_FIEL,
        exito=_es_landing_declaraciones,
    )
    return client.descargar(
        periodos_entre(desde, hasta), tipos=tipos, directorio_salida=directorio_salida,
        login=login, rfc_nombre=rfc,
    )
