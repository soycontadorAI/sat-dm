"""
Consulta y descarga de DIOT ya presentadas en el portal pstcdi.clouda.sat.gob.mx:
PDF de la declaración, su Excel (detalle de operaciones) y el acuse de recibo, por
periodo mensual, con CIEC (captcha) o e.firma (automático). Gemelo de
`portal/declaraciones.py` (portal de pagos provisionales); la presentación de la
DIOT vive en `portal/diot_presentacion.py`.

Flujo (recorrido documentado contra el portal real, sep 2026):
  1. Entrada `https://pstcdi.clouda.sat.gob.mx/` → widget NIDP de loginda (mismo
     login compartido: CIEC + captcha o e.firma con #buttonFiel).
  2. Menú: «Consultar declaración» (`/Consulta/Consulta/1`) e «Impresión de acuse»
     (`/Consulta/Consulta/3`); el form es el mismo: #IdDeclaracion (001 Declaraciones
     Informativas), #Ejercicio, #Periodicidad (M → habilita #Periodo 001..012),
     #TipoConcepto (9006 = DIOT) y #btnBuscar.
  3. Resultado en `#tableResult tbody#tableBody`, una fila por declaración (normal y
     complementarias): link PDF `a#linkDescargaPDF` con
     `onclick="abrirArchivoPDF('/Consulta/RecuperarArchivo?...tipoArchivo=0...')"`
     (descarga directa) y, sólo en «Consultar declaración», link Excel
     `a#linkDescargaExcel` con `onclick="buscarArchivoExcel(crear, recuperar, estado)"`
     (el portal genera el archivo, muestra un modal 3-4 s y descarga solo).
     Columnas: No. de Operación, Estatus, Tipo de Declaración, Tipo de
     Complementaria, Fecha de Presentación, Periodicidad, Período.
  4. Los acuses son sólo PDF.

Requiere playwright (+ chromium).
"""

import datetime
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .login import iniciar_sesion_ciec, iniciar_sesion_fiel
from .declaraciones import periodos_entre, actualizar_indice, declaracion_vigente  # noqa: F401 (API)

logger = logging.getLogger(__name__)

DIOT_BASE = "https://pstcdi.clouda.sat.gob.mx"
DIOT_CONSULTA_URL_ENTRADA = DIOT_BASE + "/"
DIOT_CONSULTA_URL_ENTRADA_FIEL = DIOT_CONSULTA_URL_ENTRADA
DIOT_CONSULTA_LANDING = "pstcdi.clouda.sat.gob.mx"

# Ruta de la consulta por tipo de documento: 1 = la declaración (PDF + Excel),
# 3 = impresión de acuse (sólo PDF).
RUTAS_CONSULTA = {"declaracion": "/Consulta/Consulta/1", "acuse": "/Consulta/Consulta/3"}
TIPOS_DEFAULT = ("declaracion", "acuse")
ID_DECLARACION_INFORMATIVAS = "001"
PERIODICIDAD_MENSUAL = "M"
CONCEPTO_DIOT = "9006"
INDICE_NOMBRE = "diot.json"

# Encabezados de #tableResult → clave del registro (los dos primeros th van vacíos:
# link PDF y link Excel).
_ENCABEZADOS = {
    "no. de operación": "numero_operacion", "estatus": "estado",
    "tipo de declaración": "tipo_declaracion", "tipo de complementaria": "tipo_complementaria",
    "fecha de presentación": "fecha_presentacion", "periodicidad": "periodicidad", "período": "periodo_texto",
    "periodo": "periodo_texto",
}
_RE_PDF = re.compile(r"abrirArchivoPDF\(\s*'([^']+)'")
_RE_EXCEL = re.compile(r"buscarArchivoExcel\(\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'")


def _es_landing_diot(url: str) -> bool:
    """True cuando ya estamos en el portal DIOT autenticado (host parseado, sin /nidp)."""
    try:
        p = urlparse((url or "").lower())
    except ValueError:
        return False
    return p.hostname == DIOT_CONSULTA_LANDING and "/nidp" not in p.path


def _normalizar(s: str) -> str:
    return " ".join((s or "").replace("\xa0", " ").split()).strip().lower()


def urls_de_onclick(onclick: Optional[str], href: Optional[str] = None) -> dict:
    """Extrae las URLs del `onclick` de los links de resultados.

    Devuelve {"pdf": url} para `abrirArchivoPDF('...')`, {"crear", "recuperar", "estado"}
    para `buscarArchivoExcel('...','...','...')`. Si el link fuera un href normal (como
    en el portal de pagos provisionales), devuelve {"pdf": href}.
    """
    onclick = (onclick or "").replace("&amp;", "&")
    m = _RE_PDF.search(onclick)
    if m:
        return {"pdf": m.group(1)}
    m = _RE_EXCEL.search(onclick)
    if m:
        return {"crear": m.group(1), "recuperar": m.group(2), "estado": m.group(3)}
    if href and href.startswith("/") and "RecuperarArchivo" in href:
        return {"pdf": href.replace("&amp;", "&")}
    return {}


def mapear_filas(encabezados: list[str], filas: list[dict]) -> list[dict]:
    """Convierte las filas crudas (celdas + links) en registros por nombre de columna.

    `filas`: [{"celdas": [...texto por td...], "pdf": {onclick, href}, "excel": {onclick, href}}].
    Pura (sin Playwright) → testeable con el HTML del recorrido.
    """
    idx = {}
    for i, h in enumerate(encabezados):
        clave = _ENCABEZADOS.get(_normalizar(h))
        if clave:
            idx[clave] = i
    out = []
    for f in filas:
        celdas = f.get("celdas") or []
        reg = {k: (celdas[i].strip() if i < len(celdas) and celdas[i] else "") for k, i in idx.items()}
        pdf = f.get("pdf") or {}
        excel = f.get("excel") or {}
        reg["_pdf"] = urls_de_onclick(pdf.get("onclick"), pdf.get("href")).get("pdf", "")
        reg["_excel"] = urls_de_onclick(excel.get("onclick"), excel.get("href"))
        out.append(reg)
    return out


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
        elif t in RUTAS_CONSULTA:
            out.append(t)
        else:
            raise ValueError(f"Tipo de documento inválido: {t!r} (declaracion | acuse | ambos)")
    return list(dict.fromkeys(out))


def nombre_archivo(sugerido: Optional[str], tipo: str, numero_operacion: str, rfc: str,
                   periodo: str, extension: str, usados: set) -> str:
    """Nombre en disco: el que sugiere el portal (p. ej. ``Decla_<op>_0MMAAAA.pdf``);
    sin sugerencia, ``DIOT_<RFC>_<periodo>_<op>.<ext>``. Si en la misma carpeta ya se
    escribió ese nombre en esta corrida (declaración y acuse con el mismo nombre), se
    prefija con el tipo."""
    ext = "." + extension.lstrip(".")
    base = Path(sugerido).stem if sugerido and sugerido.lower().endswith(ext) else ""
    if not base:
        base = f"DIOT_{rfc}_{periodo}_{numero_operacion or 'sin_op'}"
    nombre = base + ext
    if nombre.lower() in usados:
        nombre = f"{'Acuse' if tipo == 'acuse' else 'Declaracion'}.{base}{ext}"
    usados.add(nombre.lower())
    return nombre


class DiotConsultaClient:
    """Cliente para descargar DIOT presentadas (PDF, Excel) y sus acuses (portal)."""

    def __init__(self, rfc: str = "", ciec: str = "", headless: bool = True):
        self.rfc = (rfc or "").strip().upper()
        self.ciec = ciec
        self.headless = headless

    # ------------------------------------------------------------------ público
    def descargar(self, periodos: list[tuple[int, int]], tipos=TIPOS_DEFAULT, excel: bool = True,
                  directorio_salida: str = "./diot/", url_entrada: str = DIOT_CONSULTA_URL_ENTRADA,
                  login=None, rfc_nombre: Optional[str] = None, pedir_captcha=None) -> list[dict]:
        """Descarga, por (año, mes), la declaración DIOT (PDF y opcionalmente Excel) y/o
        el acuse. Devuelve un registro por fila con periodo, tipo, numero_operacion,
        estado, tipo_declaracion, tipo_complementaria, fecha_presentacion, archivo y,
        para la declaración, archivo_excel. Actualiza `diot.json` en la salida."""
        try:
            from playwright.sync_api import sync_playwright
            from playwright.sync_api import TimeoutError as PWTimeout
        except ImportError:
            raise ImportError("playwright no está instalado. Ejecuta:\n  pip install playwright\n"
                              "  playwright install chromium")
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
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
            )
            page = context.new_page()
            try:
                if login is None:
                    iniciar_sesion_ciec(page, self.rfc, self.ciec, url_entrada=url_entrada,
                                        exito=_es_landing_diot, pedir_captcha=pedir_captcha)
                else:
                    login(page)
                try:
                    page.wait_for_load_state("networkidle", timeout=20_000)
                except PWTimeout:
                    pass

                for anio, mes in periodos:
                    periodo = f"{anio}-{mes:02d}"
                    dest_dir = out_dir / periodo
                    usados: set = set()
                    for tipo in tipos:
                        filas = self._consultar(page, tipo, anio, mes)
                        logger.info("[DIOT] %s %s: %d fila(s)", periodo, tipo, len(filas))
                        if not filas:
                            continue
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        for fila in filas:
                            numop = fila.get("numero_operacion", "")
                            archivo = self._descargar_pdf(page, fila, tipo, dest_dir, rfc, periodo, usados)
                            archivo_excel = None
                            if tipo == "declaracion" and excel and fila.get("_excel"):
                                archivo_excel = self._descargar_excel(page, fila, dest_dir, rfc, periodo, usados)
                            reg = {
                                "rfc": rfc, "periodo": periodo, "ejercicio": anio, "mes": mes, "tipo": tipo,
                                "concepto": "DIOT", "numero_operacion": numop,
                                "estado": fila.get("estado", ""),
                                "tipo_declaracion": fila.get("tipo_declaracion", ""),
                                "tipo_complementaria": fila.get("tipo_complementaria", ""),
                                "fecha_presentacion": fila.get("fecha_presentacion", ""),
                                "archivo": archivo,
                                "descargado_en": datetime.datetime.now().isoformat(timespec="seconds"),
                            }
                            if tipo == "declaracion":
                                reg["archivo_excel"] = archivo_excel
                            resultados.append(reg)
            finally:
                browser.close()
        actualizar_indice(out_dir / INDICE_NOMBRE, resultados)
        return resultados

    # ---------------------------------------------------------------- consulta
    def _consultar(self, page, tipo: str, anio: int, mes: int) -> list[dict]:
        from playwright.sync_api import TimeoutError as PWTimeout

        page.goto(DIOT_BASE + RUTAS_CONSULTA[tipo], wait_until="domcontentloaded")
        try:
            page.wait_for_selector("#Ejercicio", timeout=30_000)
        except PWTimeout:
            raise RuntimeError(f"No cargó el form de consulta DIOT (URL: {page.url}). "
                               "¿La sesión del portal no quedó válida?")
        try:
            page.wait_for_load_state("networkidle", timeout=8_000)
        except PWTimeout:
            pass
        page.select_option("#IdDeclaracion", ID_DECLARACION_INFORMATIVAS)
        page.select_option("#Ejercicio", str(anio))
        page.select_option("#Periodicidad", PERIODICIDAD_MENSUAL)
        page.wait_for_function(
            "() => { const s = document.querySelector('#Periodo');"
            " return !!s && !s.disabled && s.options.length > 1; }", timeout=20_000)
        page.select_option("#Periodo", f"{mes:03d}")
        page.select_option("#TipoConcepto", CONCEPTO_DIOT)
        page.click("#btnBuscar", no_wait_after=True)
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('#tableBody tr').length > 0"
                " || !!document.querySelector('.bootbox .bootbox-body, .modal.show .modal-body')",
                timeout=40_000)
        except PWTimeout:
            logger.warning("[DIOT] %04d-%02d %s: la consulta no respondió a tiempo (URL %s).",
                           anio, mes, tipo, page.url)
            return []
        crudo = page.evaluate(
            "() => ({"
            " encabezados: Array.from(document.querySelectorAll('#tableResult thead th')).map(th => th.textContent || ''),"
            " filas: Array.from(document.querySelectorAll('#tableBody tr')).map(tr => {"
            "   const a = s => { const el = tr.querySelector(s); return el ? {onclick: el.getAttribute('onclick'), href: el.getAttribute('href')} : null; };"
            "   return { celdas: Array.from(tr.querySelectorAll('td')).map(td => (td.textContent || '').trim()),"
            "            pdf: a('a#linkDescargaPDF') || a('td:first-child a'),"
            "            excel: a('a#linkDescargaExcel') || a('td.descargaExcel a') };"
            " })})")
        if not crudo.get("filas"):
            aviso = page.evaluate(
                "() => { const m = document.querySelector('.bootbox .bootbox-body, .modal.show .modal-body');"
                " return m ? (m.textContent || '').trim() : ''; }")
            logger.info("[DIOT] %04d-%02d %s: sin declaraciones (%s)", anio, mes, tipo, aviso or "sin aviso")
            self._cerrar_modal(page)
            return []
        return mapear_filas(crudo.get("encabezados") or [], crudo["filas"])

    def _cerrar_modal(self, page) -> None:
        for sel in (".bootbox .bootbox-accept", ".bootbox button", ".modal.show button"):
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click(timeout=3_000)
                    return
            except Exception:  # noqa: BLE001
                continue

    # ---------------------------------------------------------------- descargas
    def _clic_y_capturar(self, page, selector: str, timeout_ms: int):
        """Hace clic en `selector` y devuelve (nombre_sugerido, bytes) de la descarga, o (None, None)."""
        from playwright.sync_api import TimeoutError as PWTimeout
        try:
            with page.expect_download(timeout=timeout_ms) as dl:
                page.eval_on_selector(selector, "el => el.click()")
            d = dl.value
            tmp = d.path()
            return d.suggested_filename, (Path(tmp).read_bytes() if tmp else None)
        except PWTimeout:
            return None, None
        except Exception as e:  # noqa: BLE001
            logger.info("[DIOT] click en %s falló: %s", selector, e)
            return None, None

    def _get(self, page, url: str):
        """GET con las cookies de la sesión; devuelve (nombre_sugerido, bytes)."""
        resp = page.context.request.get(url if url.startswith("http") else DIOT_BASE + url, timeout=90_000)
        cd = resp.headers.get("content-disposition") or ""
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
        return (m.group(1).strip() if m else None), resp.body()

    def _descargar_pdf(self, page, fila: dict, tipo: str, dest_dir: Path, rfc: str, periodo: str,
                       usados: set) -> Optional[str]:
        numop = fila.get("numero_operacion", "")
        url = fila.get("_pdf") or ""
        sel = f'#tableBody tr:has(td:text-is("{numop}")) a#linkDescargaPDF' if numop else "#tableBody a#linkDescargaPDF"
        sugerido, body = self._clic_y_capturar(page, sel, 30_000)
        if not body and url:
            logger.info("[DIOT] el link PDF no disparó descarga; se pide por GET (op. %s)", numop)
            try:
                sugerido, body = self._get(page, url)
            except Exception as e:  # noqa: BLE001
                logger.error("[DIOT] no se pudo descargar el PDF de op. %s: %s", numop, e)
                return None
        if not body or body[:5] != b"%PDF-":
            logger.error("[DIOT] la respuesta de op. %s no es un PDF (%d bytes)", numop, len(body or b""))
            return None
        dest = dest_dir / nombre_archivo(sugerido, tipo, numop, rfc, periodo, "pdf", usados)
        dest.write_bytes(body)
        logger.info("[DIOT] ✓ %s (%d bytes)", dest, len(body))
        return str(dest)

    def _descargar_excel(self, page, fila: dict, dest_dir: Path, rfc: str, periodo: str,
                         usados: set) -> Optional[str]:
        """El link Excel genera el archivo en el servidor (modal «Generando archivo»,
        3-4 s) y luego lo descarga solo; se espera hasta 120 s. Fallback: pedir la
        creación y recuperar por GET."""
        numop = fila.get("numero_operacion", "")
        urls = fila.get("_excel") or {}
        sel = f'#tableBody tr:has(td:text-is("{numop}")) a#linkDescargaExcel' if numop else "#tableBody a#linkDescargaExcel"
        sugerido, body = self._clic_y_capturar(page, sel, 120_000)
        if not body and urls.get("recuperar"):
            logger.info("[DIOT] el link Excel no disparó descarga; se pide por GET (op. %s)", numop)
            try:
                if urls.get("crear"):
                    self._get(page, urls["crear"])
                    page.wait_for_timeout(5_000)
                sugerido, body = self._get(page, urls["recuperar"])
            except Exception as e:  # noqa: BLE001
                logger.error("[DIOT] no se pudo descargar el Excel de op. %s: %s", numop, e)
                return None
        if not body or body[:2] != b"PK":
            logger.error("[DIOT] la respuesta Excel de op. %s no es un .xlsx (%d bytes)", numop, len(body or b""))
            return None
        ext = Path(sugerido).suffix.lstrip(".") if sugerido and Path(sugerido).suffix else "xlsx"
        dest = dest_dir / nombre_archivo(sugerido, "declaracion", numop, rfc, periodo, ext, usados)
        dest.write_bytes(body)
        logger.info("[DIOT] ✓ %s (%d bytes)", dest, len(body))
        return str(dest)


# ---------------------------------------------------------------------------
# Funciones públicas de conveniencia
# ---------------------------------------------------------------------------

def descargar_diot_ciec(rfc: str, ciec: str, desde: str, hasta: Optional[str] = None, tipos=TIPOS_DEFAULT,
                        excel: bool = True, directorio_salida: str = "./diot/", headless: bool = True,
                        url_entrada: str = DIOT_CONSULTA_URL_ENTRADA, pedir_captcha=None) -> list[dict]:
    """DIOT presentadas (PDF + Excel) y/o acuses por periodo mensual (``YYYY-MM``), vía CIEC."""
    client = DiotConsultaClient(rfc=rfc, ciec=ciec, headless=headless)
    return client.descargar(periodos_entre(desde, hasta), tipos=tipos, excel=excel,
                            directorio_salida=directorio_salida, url_entrada=url_entrada,
                            pedir_captcha=pedir_captcha)


def descargar_diot_fiel(cer_path: str, key_path: str, password: str, desde: str, hasta: Optional[str] = None,
                        tipos=TIPOS_DEFAULT, excel: bool = True, directorio_salida: str = "./diot/",
                        headless: bool = True) -> list[dict]:
    """DIOT presentadas (PDF + Excel) y/o acuses por periodo mensual, con e.firma (sin captcha)."""
    rfc = ""
    try:
        from ..core.fiel import FIEL
        rfc = FIEL(cer_path, key_path, password).rfc
    except Exception as e:  # noqa: BLE001
        logger.warning("[FIEL] no se pudo leer el RFC del .cer: %s", e)
    client = DiotConsultaClient(rfc=rfc, headless=headless)
    login = lambda page: iniciar_sesion_fiel(  # noqa: E731
        page, cer_path, key_path, password, url_entrada=DIOT_CONSULTA_URL_ENTRADA_FIEL, exito=_es_landing_diot)
    return client.descargar(periodos_entre(desde, hasta), tipos=tipos, excel=excel,
                            directorio_salida=directorio_salida, login=login, rfc_nombre=rfc)
