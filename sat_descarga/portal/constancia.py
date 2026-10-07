"""
Descarga de la Constancia de Situación Fiscal (CSF) vía el portal del SAT, con
autenticación CIEC (RFC + contraseña). Reutiliza el login genérico de `ciec.py`.

Flujo (confirmado mayo 2026):
  1. Entrada por la URL NIDP SSO cuyo `target` lleva a la pantalla "Reimprime tus
     acuses del RFC" (operación 43824). El usuario resuelve el captcha en el
     browser visible; tras el login se aterriza en
     wwwmat.sat.gob.mx/operacion/43824/reimprime-tus-acuses-del-rfc.
  2. Click en el botón "Generar constancia".
  3. El SAT abre una VENTANA NUEVA (popup) con el PDF de la constancia; se captura
     su URL y se descarga el PDF con la sesión autenticada (fallback: descarga
     directa si el click dispara un download).

Requiere playwright (+ chromium). El browser es headful porque hay captcha.
"""

import datetime
import logging
from pathlib import Path
from typing import Optional

from .login import iniciar_sesion_ciec, iniciar_sesion_fiel
from .. import demo

logger = logging.getLogger(__name__)

# URL de entrada: el "lanzador" estable del trámite (lo que dispara el enlace
# «servicio» en sat.gob.mx/portal/public/tramites/constancia-de-situacion-fiscal).
# Inicia el SSO login fresco (tipoLogeo=c = CIEC) con target a la op. 43824.
# Estable: sin parámetros de sesión, a diferencia de las URLs NIDP ya logueadas.
CSF_URL_ENTRADA = (
    "https://wwwmat.sat.gob.mx/app/seg/faces/pages/lanzador.jsf"
    "?url=/operacion/43824/reimprime-tus-acuses-del-rfc"
    "&tipoLogeo=c&target=principal&hostServer=https://wwwmat.sat.gob.mx"
)
# e.firma entra por el MISMO lanzador (tipoLogeo=c → "Acceso por contraseña"); de
# ahí el login FIEL hace clic en #buttonFiel para cambiar a e.firma. (tipoLogeo=e da
# pantalla en blanco.)
CSF_URL_ENTRADA_FIEL = CSF_URL_ENTRADA
# Tras el login se aterriza en esta pantalla (predicado de éxito).
CSF_LANDING = "wwwmat.sat.gob.mx/operacion/43824"
# Botón JSF/PrimeFaces "Generar Constancia" (id dinámico → matchear por texto).
# Suele estar dentro de un iframe, así que se busca en todos los frames.
# Su onclick hace AJAX + window.open('/PTSC/IdcSiat/IdcGeneraConstancia.jsf') → PDF.
CSF_BTN = 'button:has-text("Generar Constancia")'


class ConstanciaClient:
    """Cliente para descargar la Constancia de Situación Fiscal (portal CIEC)."""

    def __init__(self, rfc: str = "", ciec: str = "", headless: bool = True):
        self.rfc = (rfc or "").strip().upper()
        self.ciec = ciec
        self.headless = headless

    def descargar(
        self,
        directorio_salida: str = "./constancia/",
        url_entrada: str = CSF_URL_ENTRADA,
        login=None,
        rfc_nombre: Optional[str] = None,
        pedir_captcha=None,
    ) -> Optional[Path]:
        """
        Genera y descarga la Constancia de Situación Fiscal.

        Args:
            url_entrada: URL por donde inicia el login (configurable: las URLs SSO
                del SAT pueden traer parámetros de sesión).
            login: callable(page) que autentica y aterriza en la pantalla de la
                constancia. Por defecto usa CIEC (RFC + contraseña). Para e.firma se
                inyecta un login FIEL. La navegación/descarga es agnóstica al método.
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
        rfc_nombre = (rfc_nombre or self.rfc or "constancia").strip().upper()
        dest = out_dir / f"constancia_{rfc_nombre}_{fecha}.pdf"

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
                        exito=lambda url: CSF_LANDING in url,
                        pedir_captcha=pedir_captcha,
                    )
                else:
                    login(page)
                try:
                    page.wait_for_load_state("networkidle", timeout=20_000)
                except PWTimeout:
                    pass

                logger.info("[CSF] En la pantalla de acuses. Buscando «Generar Constancia»...")
                btn = self._esperar_boton(page, timeout_ms=30_000)
                if btn is None:
                    logger.error(
                        "[CSF] No apareció el botón «Generar Constancia». "
                        "URL: %s | frames: %s", page.url, [f.url for f in page.frames]
                    )
                    return None

                ok = self._capturar_pdf(context, page, btn, dest)
                if ok:
                    logger.info("[CSF] ✓ Constancia guardada: %s (%d bytes)",
                                dest, dest.stat().st_size)
                    return dest
                logger.error("[CSF] No se pudo capturar el PDF de la constancia.")
                return None
            finally:
                browser.close()

    def _esperar_boton(self, page, timeout_ms: int = 30_000):
        """
        Busca el botón «Generar Constancia» en TODOS los frames (la app PTSC suele
        cargarse dentro de un iframe) con polling, porque el JSF puede renderizar
        después del aterrizaje. Devuelve un Locator o None.
        """
        import time

        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            for frame in page.frames:
                try:
                    loc = frame.locator(CSF_BTN)
                    if loc.count() > 0:
                        loc.first.wait_for(state="visible", timeout=2_000)
                        logger.info("[CSF] Botón encontrado en frame: %s",
                                    frame.url or "(principal)")
                        return loc.first
                except Exception:
                    continue
            page.wait_for_timeout(500)
        return None

    def _capturar_pdf(self, context, page, btn, dest: Path) -> bool:
        """
        Click en «Generar Constancia» → el popup abre IdcGeneraConstancia.jsf con el
        PDF. NO se puede re-pedir con APIRequestContext (el TLS del SAT usa una clave
        DH muy pequeña que Node rechaza), así que se captura la respuesta DESDE EL
        NAVEGADOR (Chromium tolera ese TLS): un listener de `response` en el popup
        guarda los bytes del PDF. Fallback: descarga directa.
        """
        from playwright.sync_api import TimeoutError as PWTimeout

        capturado: dict = {}
        descarga: dict = {}

        def _on_popup(pg):
            def _on_resp(resp):
                if "body" in capturado:
                    return
                ct = (resp.headers.get("content-type") or "").lower()
                if "pdf" in ct or resp.url.lower().endswith(".pdf") \
                        or "idcgeneraconstancia" in resp.url.lower():
                    try:
                        b = resp.body()
                        if b[:5] == b"%PDF-":
                            capturado["body"] = b
                            logger.info("[CSF] PDF capturado del navegador: %s (%d bytes)",
                                        resp.url, len(b))
                    except Exception:
                        pass
            pg.on("response", _on_resp)

        context.on("page", _on_popup)
        context.on("download", lambda d: descarga.setdefault("d", d))

        popup = None
        try:
            with context.expect_page(timeout=20_000) as pop_info:
                btn.click()
            popup = pop_info.value
        except PWTimeout:
            pass  # quizá disparó descarga directa (fallback abajo)

        if popup is not None:
            logger.info("[CSF] Ventana del PDF: %s", popup.url)
            # Dar tiempo a que el listener capture el body del PDF.
            for _ in range(30):
                if "body" in capturado:
                    break
                page.wait_for_timeout(500)

        if "body" in capturado:
            dest.write_bytes(capturado["body"])
            return dest.stat().st_size > 0

        # Fallback 1: descarga directa disparada por el click.
        if "d" in descarga:
            try:
                descarga["d"].save_as(str(dest))
                return dest.exists() and dest.stat().st_size > 0
            except Exception as e:
                logger.warning("[CSF] no se pudo guardar la descarga: %s", e)

        # Fallback 2: re-navegar el popup con el navegador (TLS tolerante).
        if popup is not None and popup.url.startswith("http"):
            try:
                resp = popup.goto(popup.url, wait_until="commit", timeout=15_000)
                if resp:
                    body = resp.body()
                    if body[:5] == b"%PDF-":
                        dest.write_bytes(body)
                        return dest.stat().st_size > 0
            except Exception as e:
                logger.info("[CSF] re-navegación del popup no entregó PDF: %s", e)

        return False


# ---------------------------------------------------------------------------
# Función pública de conveniencia
# ---------------------------------------------------------------------------

def descargar_constancia_ciec(
    rfc: str,
    ciec: str,
    directorio_salida: str = "./constancia/",
    headless: bool = True,
    url_entrada: str = CSF_URL_ENTRADA,
    pedir_captcha=None,
) -> Optional[Path]:
    """
    Descarga la Constancia de Situación Fiscal del portal del SAT (autenticación CIEC).

    El browser corre HEADLESS: solo aparece una mini-ventana con la imagen del captcha
    para teclearlo (hasta 3 intentos). El resto (navegación + «Generar constancia» +
    captura del PDF) es automático. `headless=False` solo para depurar.
    `pedir_captcha` permite inyectar otra UI de captcha (p. ej. el bridge del agente).
    `url_entrada` permite ajustar la URL de inicio del login si el SAT la cambia.
    """
    if demo.aplica(rfc):  # modo de grabación: empresa de demo, sin SAT
        from ..demo import sat as sat_demo
        return sat_demo.constancia(rfc, directorio_salida, pedir_captcha=pedir_captcha)
    client = ConstanciaClient(rfc=rfc, ciec=ciec, headless=headless)
    return client.descargar(
        directorio_salida=directorio_salida, url_entrada=url_entrada,
        pedir_captcha=pedir_captcha,
    )


def descargar_constancia_fiel(
    cer_path: str,
    key_path: str,
    password: str,
    directorio_salida: str = "./constancia/",
    headless: bool = True,
) -> Optional[Path]:
    """
    Descarga la Constancia de Situación Fiscal usando e.firma (FIEL) en vez de CIEC.

    El browser corre HEADLESS por default (espejo del flujo CIEC). El login con
    e.firma es 100% automático (no hay captcha). `headless=False` SOLO para depurar
    si el autollenado de .cer/.key/contraseña falla y necesitas completarlo a mano.
    """
    rfc_demo = demo.aplica_archivos_fiel(cer_path, key_path, password)
    if rfc_demo:  # modo de grabación: empresa de demo, sin SAT
        from ..demo import sat as sat_demo
        return sat_demo.constancia(rfc_demo, directorio_salida, con_captcha=False)

    # El RFC para nombrar el PDF se extrae del certificado.
    rfc = ""
    try:
        from ..core.fiel import FIEL
        rfc = FIEL(cer_path, key_path, password).rfc
    except Exception as e:
        logger.warning("[FIEL] no se pudo leer el RFC del .cer: %s", e)

    client = ConstanciaClient(rfc=rfc, headless=headless)
    login = lambda page: iniciar_sesion_fiel(
        page, cer_path, key_path, password,
        url_entrada=CSF_URL_ENTRADA_FIEL,
        exito=lambda url: CSF_LANDING in url,
    )
    return client.descargar(
        directorio_salida=directorio_salida, login=login, rfc_nombre=rfc,
    )
