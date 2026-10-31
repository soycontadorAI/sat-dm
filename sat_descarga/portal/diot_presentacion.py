"""
Presentación de la DIOT (carga masiva) en el portal pstcdi.clouda.sat.gob.mx.

Automatiza el flujo completo documentado en campo (julio 2026): login con
e.firma (sin captcha) → obligación DIOT → ejercicio/periodo/tipo → app de la
declaración → método "carga masiva" → subir el .txt → verificar la sección
Totales contra el propio .txt → responder estímulos fiscales → (opcional)
firmar y enviar → capturar el acuse PDF.

LIMITANTE DOCUMENTADA: solo soporta declaraciones donde "¿Aplicaste estímulos
fiscales?" se responde "No" (el flujo con estímulos no está mapeado en el
roadmap). Si la empresa aplica estímulos, la declaración debe presentarse a
mano.

Seguridad: presentar una declaración es IRREVERSIBLE. Por default el cliente
solo VALIDA (sube el archivo, coteja totales y se detiene sin enviar); el envío
requiere `enviar=True` y pasa por el callback `confirmar` (inyectable), que
recibe el resumen de totales y debe devolver True.

Requiere playwright (+ chromium). Reutiliza el login FIEL genérico de login.py.
"""

import datetime
import logging
from pathlib import Path
from typing import Callable, Optional

from ..core.errores import ErrorEsperado
from .login import iniciar_sesion_fiel

logger = logging.getLogger(__name__)

# --- Portal -----------------------------------------------------------------
DIOT_URL_ENTRADA = "https://pstcdi.clouda.sat.gob.mx/"
DIOT_HOST = "pstcdi.clouda.sat.gob.mx"

# --- Selectores (confirmados contra el portal, julio 2026) ------------------
SEL_MENU_PRESENTAR = 'a[href="/Declaracion/Temporales"]'
SEL_OBLIGACION_DIOT = 'label[for="9006"]'          # checkbox 9006 va oculto (d-none)
# pantalla "Formulario no concluido" (aparece si quedó una declaración temporal)
SEL_NUEVA_DECLARACION = "#newForm"
SEL_ELIMINAR_TEMPORAL = ".btnEliminarDeclaracion"
SEL_EJERCICIO = "#ejercicio"
SEL_PERIODICIDAD = "#periodicidad"
SEL_PERIODOS = "#periodos"
SEL_TIPO_DECLARACION = "#tipodeclaracion"
SEL_TIPO_COMPLEMENTARIA = "#tipocomplementaria"
SEL_BTN_SIGUIENTE = "#btnSiguiente"
SEL_MODAL_CERRAR = '.modal-footer button[data-dismiss="modal"]'
SEL_OPERACIONES_TERCEROS = '[id="562select5"]'     # "La presenta con datos" = 1
SEL_METODO_CARGA = '[id="562select6"]'             # "La presenta con carga masiva" = 1
SEL_PANEL_FORMULARIO = 'a[idpanel="A562maincontainer2"]'
SEL_PANEL_TOTALES_ACTIVO = 'a[idpanel="A562maincontainer4"].current'
SEL_INPUT_TXT = 'input[id^="archivos-"][accept=".txt"]'
SEL_TOTAL_OPERACIONES = '[id="562textbox451"]'
SEL_TOTAL_IVA_ACREDITABLE = '[id="562textbox625"]'
SEL_TAB_DATOS_ADICIONALES = 'a[href="#tab_562tab566"]'
SEL_IVA_RETENIDO = '[id="562textbox863"]'
SEL_ESTIMULOS = '[id="562select872"]'              # "02" = No (único flujo soportado)
# --- Formulario de períodos 2024-y-anteriores (pantalla única, sin tabs) ----
# La DIOT clásica reporta BASES: el portal calcula y muestra el IVA trasladado.
SEL_V24_IVA_TRASLADADO = '[id="562textbox516"]'    # "Total de IVA trasladado al contribuyente"
SEL_V24_IVA_DEVOLUCIONES = '[id="562textbox561"]'  # "Menos: IVA por devoluciones, descuentos…"
SEL_V24_IVA_RETENIDO = '[id="562textbox555"]'      # "IVA retenido por el contribuyente"
SEL_BTN_ENVIAR = "#btnEnviaDec"
SEL_MODAL_PROTESTA_SI = "button.bootbox-accept"
SEL_FIRMA_CER = "#fileInputCer"
SEL_FIRMA_KEY = "#fileInput"
SEL_FIRMA_BTN_CER = "#btnCert"
SEL_FIRMA_BTN_KEY = "#btnPrivateKey"
SEL_FIRMA_PASSWORD = "#pwdLlavePriv"
SEL_FIRMA_ENVIAR = "#btnEnviarForm"
SEL_LINK_ACUSE = 'a[href*="GeneraArchivoAcuse"]'
# pantalla "Impresión de acuse" (/Consulta/Consulta/3)
SEL_ACUSE_MENU = 'a[href="/Consulta/Consulta/3"]'
SEL_AC_TIPO_DECLARACION = "#TipoDeclaracion"
SEL_AC_EJERCICIO = "#Ejercicio"
SEL_AC_PERIODICIDAD = "#Periodicidad"
SEL_AC_PERIODO = "#Periodo"
SEL_AC_CONCEPTO = "#TipoConcepto"
CONCEPTO_DIOT = "9006"
SEL_AC_BUSCAR = "#btnBuscar"
SEL_AC_TABLA = "#tableResult"

VALOR_CON_DATOS = "1"
VALOR_CARGA_MASIVA = "1"
VALOR_ESTIMULOS_NO = "02"
TIPO_NORMAL = "001"
TIPO_COMPLEMENTARIA_MODIFICACION = "003"

TOLERANCIA_PESOS = 3            # el portal redondea; el usuario documentó ±2-3
APP_TIMEOUT_MS = 180_000        # carga de la SPA tras «Siguiente»
CARGA_TXT_TIMEOUT_MS = 180_000  # procesamiento del .txt hasta caer en Totales
ACUSE_TIMEOUT_MS = 600_000      # "aquí llega a demorar más que el resto"

# Campos (base 1) del layout de 54 posiciones del TXT de carga masiva 2025+.
_CAMPOS_IVA_ACREDITABLE = tuple(range(18, 28))   # sección 3.3 completa
_CAMPO_IVA_RETENIDO = 48
_N_CAMPOS = 54
# layout de ejercicios 2024-y-anteriores (sección 4 del instructivo V2)
_N_CAMPOS_V24 = 23
_CAMPO_V24_VALOR_16 = 8          # valor de actos 16% (BASE; el portal saca el IVA)
_CAMPO_V24_IVA_RETENIDO = 22
_CAMPO_V24_IVA_DEVOLUCIONES = 23


# ---------------------------------------------------------------------------
# Lógica pura (testeable sin browser)
# ---------------------------------------------------------------------------

def clave_periodo(periodo) -> str:
    """Normaliza el mes a la clave del combo #periodos ('001'..'012').

    Acepta 4, "4", "04", "004". Lanza ValueError fuera de 1-12.
    """
    try:
        mes = int(str(periodo).strip())
    except (TypeError, ValueError):
        raise ValueError(f"Periodo inválido: {periodo!r} (se espera el mes 1-12)")
    if not 1 <= mes <= 12:
        raise ValueError(f"Periodo fuera de rango: {mes} (se espera 1-12)")
    return f"{mes:03d}"


def numero_de_texto(texto: str) -> int:
    """Convierte lo que muestra el portal ('$1,209,655.00') a entero en pesos."""
    limpio = (texto or "").replace("$", "").replace(",", "").strip()
    if not limpio:
        return 0
    return round(float(limpio))


def totales_de_txt(path) -> dict:
    """Totales esperados a partir del propio .txt de carga masiva.

    Detecta el layout por el número de campos de la primera línea:
    - 54 campos (ejercicios 2025+): devuelve {"operaciones", "iva_acreditable",
      "iva_retenido", "layout": "2025"}. El IVA acreditable suma la sección 3.3
      completa (campos 18-27); el retenido es el campo 48.
    - 23 campos (ejercicios 2024 y anteriores, sección 4 del instructivo): el
      TXT reporta BASES, no IVA — devuelve {"operaciones", "iva_trasladado"
      (Σ round(16% × valor)), "iva_devoluciones" (campo 23), "iva_retenido"
      (campo 22), "iva_acreditable" (trasladado − devoluciones),
      "layout": "v24"}.

    Lanza ValueError si alguna línea no cuadra con el layout detectado.
    """
    data = Path(path).read_text(encoding="utf-8-sig")
    lineas = [l for l in data.splitlines() if l.strip()]
    if not lineas:
        raise ValueError("El TXT no trae renglones")
    n_campos = len(lineas[0].split("|"))
    if n_campos not in (_N_CAMPOS, _N_CAMPOS_V24):
        raise ValueError(
            f"Layout desconocido: {n_campos} campos (se esperan "
            f"{_N_CAMPOS} para 2025+ o {_N_CAMPOS_V24} para 2024-y-anteriores)"
        )
    operaciones = 0
    iva_acred = 0
    iva_ret = 0
    iva_tras = 0
    iva_dev = 0
    for n, linea in enumerate(lineas, start=1):
        campos = linea.split("|")
        if len(campos) != n_campos:
            raise ValueError(
                f"Línea {n} del TXT trae {len(campos)} campos (se esperan {n_campos})"
            )
        operaciones += 1
        if n_campos == _N_CAMPOS:
            iva_acred += sum(int(campos[i - 1] or 0) for i in _CAMPOS_IVA_ACREDITABLE)
            iva_ret += int(campos[_CAMPO_IVA_RETENIDO - 1] or 0)
        else:
            valor = int(campos[_CAMPO_V24_VALOR_16 - 1] or 0)
            iva_tras += round(valor * 0.16)
            iva_dev += int(campos[_CAMPO_V24_IVA_DEVOLUCIONES - 1] or 0)
            iva_ret += int(campos[_CAMPO_V24_IVA_RETENIDO - 1] or 0)
    if n_campos == _N_CAMPOS:
        return {
            "operaciones": operaciones,
            "iva_acreditable": iva_acred,
            "iva_retenido": iva_ret,
            "layout": "2025",
        }
    return {
        "operaciones": operaciones,
        "iva_trasladado": iva_tras,
        "iva_devoluciones": iva_dev,
        "iva_retenido": iva_ret,
        "iva_acreditable": iva_tras - iva_dev,
        "layout": "v24",
    }


def comparar_totales(esperado: dict, portal: dict,
                     tolerancia: int = TOLERANCIA_PESOS) -> list:
    """Discrepancias entre lo calculado del TXT y lo que muestra el portal.

    Las operaciones deben coincidir exacto; los montos admiten ±tolerancia
    (redondeos del portal). Devuelve lista de mensajes (vacía = todo cuadra).
    """
    discrepancias = []
    if esperado["operaciones"] != portal["operaciones"]:
        discrepancias.append(
            f"Operaciones: TXT={esperado['operaciones']} vs "
            f"portal={portal['operaciones']}"
        )
    for campo, etiqueta in (("iva_acreditable", "IVA acreditable"),
                            ("iva_trasladado", "IVA trasladado"),
                            ("iva_devoluciones", "IVA devoluciones"),
                            ("iva_retenido", "IVA retenido")):
        if campo not in esperado or campo not in portal:
            continue
        dif = abs(esperado[campo] - portal[campo])
        if dif > tolerancia:
            discrepancias.append(
                f"{etiqueta}: TXT={esperado[campo]:,} vs portal={portal[campo]:,} "
                f"(dif {dif:,} > tolerancia {tolerancia})"
            )
    return discrepancias


# ---------------------------------------------------------------------------
# Cliente Playwright
# ---------------------------------------------------------------------------

class PresentadorDiot:
    """Presenta (o solo valida) la DIOT por carga masiva con e.firma.

    `confirmar(resumen) -> bool` se consulta justo antes de firmar/enviar
    (inyectable: prompt del CLI, bridge de la app, etc.). Si devuelve False la
    corrida termina en estado "validado" sin enviar. `progreso(msg)` es opcional
    para reportar avance (SSE/UI).
    """

    def __init__(self, headless: bool = True,
                 confirmar: Optional[Callable[[dict], bool]] = None,
                 progreso: Optional[Callable[[str], None]] = None,
                 on_progreso: Optional[Callable[[str, dict], None]] = None):
        self.headless = headless
        self.confirmar = confirmar
        self.progreso = progreso or (lambda msg: None)
        # contrato UI (patrón csd.py): fases con nombre ESTABLE para la
        # checklist del renderer; `progreso` sigue siendo el mensaje libre
        # del CLI — se emiten ambos
        self._on_progreso = on_progreso

    @staticmethod
    def _qs(page, selector):
        """query_selector tolerante: si la página navega a media consulta
        (contexto destruido), devuelve None en vez de tronar."""
        try:
            return page.query_selector(selector)
        except Exception:  # noqa: BLE001
            return None

    def _paso(self, msg: str):
        logger.info("[DIOT] %s", msg)
        self.progreso(msg)

    def _emitir(self, fase: str, **data):
        if self._on_progreso is None:
            return
        try:
            self._on_progreso(fase, data)
        except Exception as e:  # noqa: BLE001 — el progreso es cosmético
            logger.warning("[DIOT] callback de progreso falló en %s: %s", fase, e)

    # -- flujo principal ----------------------------------------------------

    def presentar(self, cer_path: str, key_path: str, password: str,
                  txt_path: str, ejercicio: int, periodo,
                  tipo_declaracion: str = TIPO_NORMAL,
                  directorio_salida: str = "./diot_presentacion/",
                  enviar: bool = False, rfc: str = "") -> dict:
        """Corre el flujo. Devuelve dict con estado/totales/acuse/evidencia.

        estado: "validado" (no se envió) o "presentado" (firmado y enviado).
        Con discrepancias de totales NUNCA se envía, aunque `enviar=True`.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError(
                "playwright no está instalado. Ejecuta:\n"
                "  pip install playwright\n  playwright install chromium"
            )
        from .setup import asegurar_chromium, lanzar_chromium
        asegurar_chromium()

        periodo_clave = clave_periodo(periodo)
        esperado = totales_de_txt(txt_path)
        out_dir = Path(directorio_salida)
        out_dir.mkdir(parents=True, exist_ok=True)
        etiqueta = f"{(rfc or 'diot').upper()}_{ejercicio}_{periodo_clave}"
        evidencia = []

        resultado = {
            "estado": "validado",
            "totales_txt": esperado,
            "totales_portal": None,
            "discrepancias": None,
            "acuse": None,
            "evidencia": evidencia,
        }

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
                return self._flujo(page, context, cer_path, key_path, password,
                                   txt_path, ejercicio, periodo_clave, esperado,
                                   tipo_declaracion, out_dir, etiqueta,
                                   evidencia, resultado, enviar, rfc)
            except Exception:
                # evidencia del punto de falla: oro para ajustar selectores
                try:
                    shot = out_dir / f"error_{etiqueta}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    (out_dir / f"error_{etiqueta}.html").write_text(
                        page.content(), encoding="utf-8")
                    evidencia.append(str(shot))
                    logger.error("[DIOT] Falla en %s — evidencia: %s(.html)",
                                 page.url, shot)
                except Exception:  # noqa: BLE001 — no tapar el error original
                    pass
                raise
            finally:
                browser.close()

    LOGIN_INTENTOS = 3

    def _login_diot(self, page, cer_path, key_path, password):
        """Login e.firma al portal DIOT con reintentos.

        El NIDP del SAT se atora de vez en cuando a media redirección (medido
        2026-08-29 en el portal de contabilidad electrónica: 2 fallas sueltas
        en 15 entradas, sin patrón de rate-limit — es el mismo login). Se
        reintenta; agotar los intentos es fallo de entorno (`ErrorEsperado`),
        no bug.
        """
        # comparar el HOST parseado: la URL del OAuth intermedio trae
        # "pstcdi..." embebido en el redirect_uri y un substring simple
        # daría falso positivo (visto en la corrida del 2026-07-31)
        from urllib.parse import urlparse
        for intento in range(1, self.LOGIN_INTENTOS + 1):
            self._paso(f"Login con e.firma en el portal DIOT "
                       f"(intento {intento}/{self.LOGIN_INTENTOS})...")
            try:
                iniciar_sesion_fiel(
                    page, cer_path, key_path, password,
                    url_entrada=DIOT_URL_ENTRADA,
                    exito=lambda url: urlparse(url).netloc.lower() == DIOT_HOST,
                )
                return
            except RuntimeError as e:
                if intento == self.LOGIN_INTENTOS:
                    raise ErrorEsperado(
                        f"El SAT no respondió al login del portal DIOT tras "
                        f"{self.LOGIN_INTENTOS} intentos ({str(e)[:120]}). "
                        "Suele ser lentitud o mantenimiento sin aviso; "
                        "reintenta más tarde.") from e
                logger.warning("[DIOT] El login no completó (%s); reintento.",
                               str(e)[:160])

    def _flujo(self, page, context, cer_path, key_path, password, txt_path,
               ejercicio, periodo_clave, esperado, tipo_declaracion, out_dir,
               etiqueta, evidencia, resultado, enviar, rfc) -> dict:
        self._emitir("login")
        self._login_diot(page, cer_path, key_path, password)
        page.wait_for_selector(SEL_MENU_PRESENTAR, timeout=60_000)

        self._paso("Seleccionando obligación DIOT y periodo...")
        self._emitir("seleccionando_declaracion", ejercicio=ejercicio,
                     periodo=periodo_clave)
        self._seleccionar_declaracion(page, ejercicio, periodo_clave,
                                      tipo_declaracion)

        self._paso("Configurando método de carga masiva...")
        self._configurar_carga_masiva(page)

        self._paso("Subiendo el archivo TXT...")
        self._emitir("subiendo_txt")
        self._cargar_txt(page, txt_path)

        self._paso("Leyendo la sección Totales...")
        self._emitir("totales_leyendo")
        portal = self._leer_totales(page, esperado.get("layout", "2025"))
        resultado["totales_portal"] = portal

        # Único flujo soportado: SIN estímulos fiscales (responde "No").
        self._paso("Respondiendo estímulos fiscales: No...")
        self._emitir("estimulos", respuesta="No")
        self._responder_estimulos(page, esperado.get("layout", "2025"))

        discrepancias = comparar_totales(esperado, portal)
        resultado["discrepancias"] = discrepancias

        shot = out_dir / f"totales_{etiqueta}.png"
        try:
            page.screenshot(path=str(shot), full_page=True)
            evidencia.append(str(shot))
        except Exception:  # noqa: BLE001 — la evidencia es best-effort
            pass

        if discrepancias:
            logger.error("[DIOT] Totales NO cuadran; no se envía:\n  %s",
                         "\n  ".join(discrepancias))
            return resultado
        self._paso(
            f"Totales OK: {portal['operaciones']} operaciones, "
            f"IVA acreditable {portal['iva_acreditable']:,}, "
            f"retenido {portal['iva_retenido']:,}."
        )

        if not enviar:
            self._paso("Modo validación: NO se envía la declaración.")
            self._emitir("fin", estado="validado")
            return resultado

        self._emitir("confirmando", **{k: portal.get(k) for k in
                     ("operaciones", "iva_acreditable", "iva_retenido")})
        if self.confirmar is not None and not self.confirmar({
            "rfc": rfc, "ejercicio": ejercicio, "periodo": periodo_clave,
            **portal,
        }):
            self._paso("Envío cancelado por el usuario.")
            self._emitir("fin", estado="cancelado")
            return resultado

        self._emitir("firmando")
        self._paso("Enviando declaración (firma con e.firma)...")
        acuse = self._enviar_y_firmar(
            page, context, cer_path, key_path, password,
            out_dir / f"acuse_diot_{etiqueta}_"
            f"{datetime.date.today():%Y%m%d}.pdf",
        )
        if acuse is None:
            # Sin acuse NO se afirma nada: la prueba de presentación es
            # que la declaración temporal fue consumida por el envío.
            quedo = self._quedo_temporal(page, ejercicio, periodo_clave)
            if quedo is True:
                resultado["estado"] = "no_presentada"
                logger.error(
                    "[DIOT] El envío NO se concretó: la declaración "
                    "sigue como temporal en el portal. Reintenta."
                )
            else:
                # Que la temporal desaparezca NO prueba la presentación
                # (comprobado 2026-07-31: una firma fallida consumió la
                # temporal sin presentar). Sin acuse, el estado queda en
                # duda SIEMPRE.
                resultado["estado"] = "desconocido"
                logger.error(
                    "[DIOT] Sin acuse no hay confirmación. Verifica en "
                    "el portal antes de re-presentar (intenta "
                    "`sat-dm diot acuse` en unos minutos)."
                )
            return resultado
        resultado["estado"] = "presentado"
        self._emitir("acuse", path=str(resultado.get("acuse") or ""))
        resultado["acuse"] = str(acuse)
        self._paso(f"Acuse guardado: {acuse}")
        return resultado

    # -- pasos --------------------------------------------------------------

    def _cerrar_modal_si_aparece(self, page, timeout_ms: int = 10_000):
        """Cierra el modal informativo (p. ej. ajuste de fracciones de peso)."""
        from playwright.sync_api import TimeoutError as PWTimeout
        try:
            page.click(f"{SEL_MODAL_CERRAR}:visible", timeout=timeout_ms)
            logger.info("[DIOT] Modal informativo cerrado.")
        except PWTimeout:
            pass

    def _despachar_dialogos(self, page, max_rondas: int = 6):
        """Cierra los diálogos visibles (bootbox confirm/alert y modales).

        Preferencia: botón de aceptar de un confirm; si el modal tiene un solo
        botón (alertas tipo «Se eliminó correctamente», «Cerrar»), ese; si hay
        varios sin bootbox-accept, el de texto afirmativo. Los clicks van por
        JS: los overlays de bootbox interceptan los clicks visuales.
        """
        for _ in range(max_rondas):
            # si la página navega a media inspección, el contexto se destruye
            # bajo los pies (mismo patrón que _texto_error_login): los diálogos
            # murieron con la navegación → no hay nada que despachar
            try:
                if self._qs(page, f".bootbox.show {SEL_MODAL_PROTESTA_SI}"):
                    page.eval_on_selector(
                        f".bootbox.show {SEL_MODAL_PROTESTA_SI}",
                        "el => el.click()")
                    logger.info("[DIOT] Confirmación bootbox aceptada.")
                    page.wait_for_timeout(600)
                    continue
                botones = page.query_selector_all(
                    ".bootbox.show .modal-footer button, "
                    ".modal.show .modal-footer button")
                visibles = [b for b in botones if b.is_visible()]
                if not visibles:
                    return
                objetivo = visibles[0]
                if len(visibles) > 1:
                    for b in visibles:
                        texto = (b.text_content() or "").strip().upper()
                        if texto in ("SÍ", "SI", "ACEPTAR", "OK", "CERRAR",
                                     "ELIMINAR", "CONTINUAR"):
                            objetivo = b
                            break
                texto = (objetivo.text_content() or "").strip()
                objetivo.evaluate("el => el.click()")
                logger.info("[DIOT] Diálogo cerrado (botón «%s»).", texto)
                page.wait_for_timeout(600)
            except Exception as e:  # noqa: BLE001 — navegación en vuelo
                logger.info("[DIOT] Despacho de diálogos interrumpido por "
                            "navegación (%s); continúo.", type(e).__name__)
                return

    def _resolver_pantalla_temporales(self, page, ejercicio, periodo_clave):
        """Deja la malla de obligaciones lista, venga limpia o con temporales.

        Si el portal muestra "Formulario no concluido" (quedó una declaración
        temporal, p. ej. de una corrida de validación previa), ELIMINA la
        temporal del mismo ejercicio/periodo —para partir de cero, que es el
        flujo mapeado— y arranca una nueva declaración con #newForm.
        """
        # tras el login la página puede seguir redirigiendo (OAuth → Home):
        # si el contexto se destruye a media inspección, reintentar una vez
        for intento in (1, 2):
            try:
                page.wait_for_selector(
                    f"{SEL_OBLIGACION_DIOT}, {SEL_NUEVA_DECLARACION}",
                    timeout=60_000,
                )
                if self._qs(page, SEL_OBLIGACION_DIOT):
                    return
                break
            except Exception as e:  # noqa: BLE001 — navegación en vuelo
                if intento == 2:
                    raise
                logger.info("[DIOT] Pantalla de temporales navegando (%s); "
                            "reintento...", type(e).__name__)
                page.wait_for_timeout(3_000)
                try:
                    page.click(SEL_MENU_PRESENTAR, timeout=10_000)
                except Exception:  # noqa: BLE001 — quizá ya está ahí
                    pass
        sel_trash = (f'{SEL_ELIMINAR_TEMPORAL}[data-ejercicio="{ejercicio}"]'
                     f'[data-periodo="{periodo_clave}"]')
        if self._qs(page, sel_trash):
            logger.info("[DIOT] Eliminando declaración temporal %s-%s previa...",
                        ejercicio, periodo_clave)
            # el span mide 0x0 (el ícono flota adentro) → click por JS, no visual
            page.eval_on_selector(sel_trash, "el => el.click()")
            page.wait_for_timeout(800)
            self._despachar_dialogos(page)   # confirm de borrado + alerta de éxito
            page.wait_for_timeout(1_000)
            self._despachar_dialogos(page)
        page.eval_on_selector(SEL_NUEVA_DECLARACION, "el => el.click()")
        page.wait_for_selector(SEL_OBLIGACION_DIOT, timeout=60_000)

    def _quedo_temporal(self, page, ejercicio, periodo_clave):
        """¿Sigue la declaración como temporal? True/False, o None si no se
        pudo verificar (la página no cargó, sesión perdida, etc.)."""
        try:
            page.goto(DIOT_URL_ENTRADA + "Declaracion/Temporales",
                      wait_until="domcontentloaded")
            page.wait_for_selector(
                f"{SEL_OBLIGACION_DIOT}, {SEL_NUEVA_DECLARACION}",
                timeout=30_000,
            )
            sel = (f'{SEL_ELIMINAR_TEMPORAL}[data-ejercicio="{ejercicio}"]'
                   f'[data-periodo="{periodo_clave}"]')
            return self._qs(page, sel) is not None
        except Exception as e:  # noqa: BLE001 — sin evidencia no se afirma nada
            logger.warning("[DIOT] No se pudo verificar temporales: %s", e)
            return None

    def _seleccionar_declaracion(self, page, ejercicio, periodo_clave, tipo):
        page.click(SEL_MENU_PRESENTAR)
        self._resolver_pantalla_temporales(page, ejercicio, periodo_clave)
        page.click(SEL_OBLIGACION_DIOT)
        page.wait_for_selector(f"{SEL_EJERCICIO}:visible", timeout=30_000)
        page.select_option(SEL_EJERCICIO, str(ejercicio))
        page.select_option(SEL_PERIODICIDAD, "M")
        # el combo de periodos se puebla por AJAX tras elegir periodicidad
        page.wait_for_selector(
            f'{SEL_PERIODOS} option[value="{periodo_clave}"]',
            state="attached", timeout=30_000,
        )
        page.select_option(SEL_PERIODOS, periodo_clave)
        page.wait_for_selector(f"{SEL_TIPO_DECLARACION}:visible", timeout=30_000)
        page.select_option(SEL_TIPO_DECLARACION, tipo)
        if tipo != TIPO_NORMAL:
            # complementarias: el portal (v2, 30-sep-2026) pide el «Tipo de
            # complementaria»; lo que se reemplaza con un TXT nuevo es la
            # «Modificación de Declaración» (003)
            page.wait_for_selector(f"{SEL_TIPO_COMPLEMENTARIA}:visible", timeout=30_000)
            page.select_option(SEL_TIPO_COMPLEMENTARIA, TIPO_COMPLEMENTARIA_MODIFICACION)
        page.wait_for_selector(f"{SEL_BTN_SIGUIENTE}:visible", timeout=30_000)
        page.click(SEL_BTN_SIGUIENTE)
        # la SPA tarda en cargar y en el camino pueden aparecer diálogos
        # (ajuste de redondeo, confirmaciones): despacharlos mientras se espera
        import time
        deadline = time.time() + APP_TIMEOUT_MS / 1000
        while time.time() < deadline:
            if self._qs(page, SEL_OPERACIONES_TERCEROS):
                break
            self._despachar_dialogos(page, max_rondas=1)
            page.wait_for_timeout(500)
        else:
            raise RuntimeError(
                f"La aplicación de la declaración no cargó en "
                f"{APP_TIMEOUT_MS // 1000}s (URL: {page.url})."
            )
        self._cerrar_modal_si_aparece(page)

    def _configurar_carga_masiva(self, page):
        page.select_option(SEL_OPERACIONES_TERCEROS, VALOR_CON_DATOS)
        # si había una declaración temporal previa, el portal pide confirmar
        self._despachar_dialogos(page)
        page.wait_for_selector(f"{SEL_METODO_CARGA}:visible", timeout=30_000)
        page.select_option(SEL_METODO_CARGA, VALOR_CARGA_MASIVA)
        self._despachar_dialogos(page)

    def _cargar_txt(self, page, txt_path):
        page.click(SEL_PANEL_FORMULARIO)
        page.wait_for_selector(SEL_INPUT_TXT, state="attached", timeout=30_000)
        page.set_input_files(SEL_INPUT_TXT, str(txt_path))
        # una carga exitosa redirige sola a la sección Totales
        page.wait_for_selector(SEL_PANEL_TOTALES_ACTIVO,
                               timeout=CARGA_TXT_TIMEOUT_MS)

    def _leer_totales(self, page, layout: str = "2025") -> dict:
        page.wait_for_selector(SEL_TOTAL_OPERACIONES, state="attached",
                               timeout=30_000)
        operaciones = numero_de_texto(page.input_value(SEL_TOTAL_OPERACIONES))
        if layout == "v24":
            # períodos 2024-y-anteriores: pantalla única, SIN tab de
            # «Datos adicionales»; el portal calcula el IVA desde las bases
            page.wait_for_selector(SEL_V24_IVA_RETENIDO, state="attached",
                                   timeout=30_000)
            iva_tras = numero_de_texto(page.input_value(SEL_V24_IVA_TRASLADADO))
            iva_dev = numero_de_texto(page.input_value(SEL_V24_IVA_DEVOLUCIONES))
            iva_ret = numero_de_texto(page.input_value(SEL_V24_IVA_RETENIDO))
            return {
                "operaciones": operaciones,
                "iva_trasladado": iva_tras,
                "iva_devoluciones": iva_dev,
                "iva_retenido": iva_ret,
                "iva_acreditable": iva_tras - iva_dev,
            }
        iva_acred = numero_de_texto(page.input_value(SEL_TOTAL_IVA_ACREDITABLE))
        page.click(SEL_TAB_DATOS_ADICIONALES)
        page.wait_for_selector(SEL_IVA_RETENIDO, state="attached", timeout=30_000)
        iva_ret = numero_de_texto(page.input_value(SEL_IVA_RETENIDO))
        return {
            "operaciones": operaciones,
            "iva_acreditable": iva_acred,
            "iva_retenido": iva_ret,
        }

    def _responder_estimulos(self, page, layout: str = "2025"):
        if layout == "v24":
            # El formulario clásico (2024-y-anteriores) NO pregunta estímulos:
            # el select queda en el DOM de la SPA pero oculto (comprobado con
            # SAJ feb-2021). Solo se responde si el portal lo muestra.
            sel = self._qs(page, SEL_ESTIMULOS)
            if sel is None or not sel.is_visible():
                self._paso("El formulario clásico no pregunta estímulos; se omite.")
                return
        page.wait_for_selector(SEL_ESTIMULOS, state="attached", timeout=30_000)
        page.select_option(SEL_ESTIMULOS, VALOR_ESTIMULOS_NO)

    def _click_link_acuse(self, context) -> bool:
        """Busca el link «Descargar» del acuse en TODAS las páginas y frames."""
        for pg in context.pages:
            for frame in pg.frames:
                try:
                    if frame.query_selector(SEL_LINK_ACUSE):
                        frame.eval_on_selector(SEL_LINK_ACUSE, "el => el.click()")
                        logger.info("[DIOT] Click en link del acuse (%s).",
                                    frame.url or "frame")
                        return True
                except Exception:  # noqa: BLE001 — frames navegando
                    continue
        return False

    def descargar_acuse(self, cer_path: str, key_path: str, password: str,
                        ejercicio: int, periodo,
                        tipo_declaracion: str = TIPO_NORMAL,
                        directorio_salida: str = "./diot_presentacion/",
                        rfc: str = "") -> Optional[Path]:
        """Reimprime y descarga el acuse de una DIOT ya presentada.

        Entra a «Impresión de acuse», busca por ejercicio/periodo/tipo
        (concepto DIOT) y captura el PDF del primer resultado.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError(
                "playwright no está instalado. Ejecuta:\n"
                "  pip install playwright\n  playwright install chromium"
            )
        from .setup import asegurar_chromium, lanzar_chromium
        asegurar_chromium()

        periodo_clave = clave_periodo(periodo)
        out_dir = Path(directorio_salida)
        out_dir.mkdir(parents=True, exist_ok=True)
        etiqueta = f"{(rfc or 'diot').upper()}_{ejercicio}_{periodo_clave}"
        dest = out_dir / (f"acuse_diot_{etiqueta}_"
                          f"{datetime.date.today():%Y%m%d}.pdf")

        with sync_playwright() as p:
            browser = lanzar_chromium(p, headless=self.headless, slow_mo=80)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            try:
                self._login_diot(page, cer_path, key_path, password)
                page.wait_for_selector(SEL_ACUSE_MENU, timeout=60_000)
                page.click(SEL_ACUSE_MENU)
                self._paso("Buscando la declaración presentada...")
                page.wait_for_selector(f"{SEL_AC_TIPO_DECLARACION}:visible",
                                       timeout=60_000)
                page.select_option(SEL_AC_TIPO_DECLARACION, tipo_declaracion)
                page.select_option(SEL_AC_EJERCICIO, str(ejercicio))
                page.select_option(SEL_AC_PERIODICIDAD, "M")
                page.wait_for_selector(
                    f'{SEL_AC_PERIODO} option[value="{periodo_clave}"]',
                    state="attached", timeout=30_000,
                )
                page.select_option(SEL_AC_PERIODO, periodo_clave)
                page.select_option(SEL_AC_CONCEPTO, CONCEPTO_DIOT)
                page.click(SEL_AC_BUSCAR)
                page.wait_for_selector(f"{SEL_AC_TABLA}:visible", timeout=60_000)

                acuse = self._capturar_acuse(page, context, dest)
                if acuse:
                    self._paso(f"Acuse guardado: {acuse}")
                return acuse
            except Exception:
                try:
                    shot = out_dir / f"error_acuse_{etiqueta}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    (out_dir / f"error_acuse_{etiqueta}.html").write_text(
                        page.content(), encoding="utf-8")
                    logger.error("[DIOT] Falla en %s — evidencia: %s(.html)",
                                 page.url, shot)
                except Exception:  # noqa: BLE001
                    pass
                raise
            finally:
                browser.close()

    def _capturar_acuse(self, page, context, dest: Path,
                        timeout_ms: int = 120_000) -> Optional[Path]:
        """Dispara la descarga desde la fila de resultados y captura el PDF."""
        capturado: dict = {}
        descarga: dict = {}

        def _on_resp(resp):
            if "body" in capturado:
                return
            ct = (resp.headers.get("content-type") or "").lower()
            if "pdf" in ct or "generaarchivoacuse" in resp.url.lower():
                try:
                    b = resp.body()
                    if b[:5] == b"%PDF-":
                        capturado["body"] = b
                        logger.info("[DIOT] Acuse capturado: %s (%d bytes)",
                                    resp.url, len(b))
                except Exception:  # noqa: BLE001
                    pass

        for pg in context.pages:
            pg.on("response", _on_resp)
        context.on("page", lambda pg: pg.on("response", _on_resp))
        context.on("download", lambda d: descarga.setdefault("d", d))

        # candidatos al control de descarga dentro de los resultados
        candidatos = (
            f"#tableBody {SEL_LINK_ACUSE}",
            SEL_LINK_ACUSE,
            "#tableBody a",
            "#accordionResult a[href*='GeneraArchivoAcuse']",
        )
        clickeado = False
        for sel in candidatos:
            if self._qs(page, sel):
                page.eval_on_selector(sel, "el => el.click()")
                logger.info("[DIOT] Click de descarga con selector: %s", sel)
                clickeado = True
                break
        if not clickeado:
            logger.warning("[DIOT] No encontré control de descarga en resultados.")

        import time
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            if "body" in capturado:
                dest.write_bytes(capturado["body"])
                return dest if dest.stat().st_size > 0 else None
            if "d" in descarga:
                try:
                    descarga["d"].save_as(str(dest))
                    if dest.exists() and dest.stat().st_size > 0:
                        return dest
                except Exception as e:  # noqa: BLE001
                    logger.warning("[DIOT] descarga del acuse falló: %s", e)
                    descarga.pop("d", None)
            if not clickeado:
                clickeado = self._click_link_acuse(context)
            page.wait_for_timeout(500)
        return None

    def _enviar_y_firmar(self, page, context, cer_path, key_path, password,
                         dest: Path) -> Optional[Path]:
        from playwright.sync_api import TimeoutError as PWTimeout

        # listener del acuse ANTES de disparar el envío (mismo patrón que la
        # opinión 32-D: el TLS del SAT no se puede re-pedir desde Node)
        capturado: dict = {}
        descarga: dict = {}

        def _on_resp(resp):
            if "body" in capturado:
                return
            ct = (resp.headers.get("content-type") or "").lower()
            if "pdf" in ct or "generaarchivoacuse" in resp.url.lower():
                try:
                    b = resp.body()
                    if b[:5] == b"%PDF-":
                        capturado["body"] = b
                        logger.info("[DIOT] Acuse capturado: %s (%d bytes)",
                                    resp.url, len(b))
                except Exception:  # noqa: BLE001
                    pass

        for pg in context.pages:
            pg.on("response", _on_resp)
        context.on("page", lambda pg: pg.on("response", _on_resp))
        context.on("download", lambda d: descarga.setdefault("d", d))

        page.wait_for_selector(f"{SEL_BTN_ENVIAR}:not(.disabled)", timeout=30_000)
        page.click(SEL_BTN_ENVIAR)
        page.wait_for_selector(f"{SEL_MODAL_PROTESTA_SI}:visible", timeout=30_000)
        page.click(SEL_MODAL_PROTESTA_SI)

        # formulario de firma (los file inputs van ocultos → state=attached)
        page.wait_for_selector(SEL_FIRMA_PASSWORD, state="attached",
                               timeout=60_000)
        page.wait_for_selector(SEL_FIRMA_CER, state="attached", timeout=30_000)

        def _cargar_firma():
            # Camino manual real: «Buscar» reemplaza el input por un clon y abre
            # el file chooser; así el handler que extrae el RFC del .cer corre
            # igual que cuando el usuario lo hace a mano. (Inyectar directo al
            # input oculto llena el nombre pero no siempre dispara ese parseo.)
            try:
                with page.expect_file_chooser(timeout=8_000) as fc:
                    page.click(SEL_FIRMA_BTN_CER)
                fc.value.set_files(cer_path)
                with page.expect_file_chooser(timeout=8_000) as fc:
                    page.click(SEL_FIRMA_BTN_KEY)
                fc.value.set_files(key_path)
            except Exception as e:  # noqa: BLE001 — fallback al input oculto
                logger.info("[DIOT] File chooser no disponible (%s); "
                            "inyectando directo.", type(e).__name__)
                page.set_input_files(SEL_FIRMA_CER, cer_path)
                page.set_input_files(SEL_FIRMA_KEY, key_path)
            page.fill(SEL_FIRMA_PASSWORD, password)

        # El JS de la página parsea el .cer y llena el RFC de solo lectura
        # (#txtRFC); si se envía antes de eso, el portal truena con "El RFC del
        # usuario de la sesión no coincide con el del certificado" (comparación
        # contra vacío, visto 2026-07-31). Si el parse no llega, se re-cargan
        # los archivos: el handler del input pudo no estar enlazado aún.
        _cargar_firma()
        rfc_listo = False
        for intento in range(1, 4):
            try:
                page.wait_for_function(
                    "() => { const el = document.querySelector('#txtRFC');"
                    "        return el && el.value && el.value.length >= 12; }",
                    timeout=15_000,
                )
                rfc_listo = True
                break
            except PWTimeout:
                self._despachar_dialogos(page)  # cierra "Error al validar"
                logger.info("[DIOT] #txtRFC vacío; re-cargando la e.firma "
                            "(intento %d/3)...", intento)
                _cargar_firma()
        if not rfc_listo:
            logger.warning("[DIOT] #txtRFC nunca se llenó; intento enviar igual.")

        # el handler de #btnEnviarForm (onclick vacío en el HTML) se enlaza
        # dinámicamente → reintentar hasta que el form avance. Click por JS y
        # despachando alertas: los overlays de bootbox interceptan el puntero.
        avanzo = False
        for intento in range(1, 7):
            self._despachar_dialogos(page, max_rondas=2)
            page.eval_on_selector(SEL_FIRMA_ENVIAR, "el => el.click()")
            try:
                page.wait_for_function(
                    "() => { const el = document.querySelector('#pwdLlavePriv');"
                    "        return !el || el.offsetParent === null; }",
                    timeout=10_000,
                )
                avanzo = True
                break
            except PWTimeout:
                logger.info("[DIOT] La firma no avanzó tras el click "
                            "(intento %d/6); reintentando...", intento)
        if not avanzo:
            raise RuntimeError(
                "El formulario de firma no avanzó tras 6 intentos de Enviar; "
                "la declaración NO se presentó (queda como temporal)."
            )
        self._paso("Declaración firmada; esperando el acuse (puede tardar)...")

        # espera del acuse: por captura de response, por download o por el link
        import time
        deadline = time.time() + ACUSE_TIMEOUT_MS / 1000
        link_clickeado = False
        while time.time() < deadline:
            if "body" in capturado:
                dest.write_bytes(capturado["body"])
                return dest if dest.stat().st_size > 0 else None
            if "d" in descarga:
                try:
                    descarga["d"].save_as(str(dest))
                    if dest.exists() and dest.stat().st_size > 0:
                        return dest
                except Exception as e:  # noqa: BLE001
                    logger.warning("[DIOT] descarga del acuse falló: %s", e)
                    descarga.pop("d", None)
            if not link_clickeado:
                link_clickeado = self._click_link_acuse(context)
            page.wait_for_timeout(500)
        return None


# ---------------------------------------------------------------------------
# Función pública de conveniencia
# ---------------------------------------------------------------------------

def presentar_diot_fiel(cer_path: str, key_path: str, password: str,
                        txt_path: str, ejercicio: int, periodo,
                        directorio_salida: str = "./diot_presentacion/",
                        tipo_declaracion: str = TIPO_NORMAL,
                        enviar: bool = False, headless: bool = True,
                        confirmar=None, progreso=None) -> dict:
    """Presenta (o valida) la DIOT por carga masiva usando e.firma.

    ADVERTENCIA: solo aplica a contribuyentes que responden "No" en
    "¿Aplicaste estímulos fiscales?" — el flujo con estímulos no está soportado.

    Sin `enviar=True` el flujo se detiene tras validar la sección Totales
    contra el TXT (nada se presenta). El RFC para nombrar la evidencia se lee
    del certificado.
    """
    rfc = ""
    try:
        from ..core.fiel import FIEL
        rfc = FIEL(cer_path, key_path, password).rfc
    except Exception as e:  # noqa: BLE001 — solo afecta el nombre del archivo
        logger.warning("[DIOT] no se pudo leer el RFC del .cer: %s", e)

    cliente = PresentadorDiot(headless=headless, confirmar=confirmar,
                              progreso=progreso)
    return cliente.presentar(
        cer_path, key_path, password, txt_path, ejercicio, periodo,
        tipo_declaracion=tipo_declaracion, directorio_salida=directorio_salida,
        enviar=enviar, rfc=rfc,
    )


def descargar_acuse_diot_fiel(cer_path: str, key_path: str, password: str,
                              ejercicio: int, periodo,
                              tipo_declaracion: str = TIPO_NORMAL,
                              directorio_salida: str = "./diot_presentacion/",
                              headless: bool = True,
                              progreso=None) -> Optional[Path]:
    """Descarga (reimprime) el acuse de una DIOT ya presentada, con e.firma."""
    rfc = ""
    try:
        from ..core.fiel import FIEL
        rfc = FIEL(cer_path, key_path, password).rfc
    except Exception as e:  # noqa: BLE001 — solo afecta el nombre del archivo
        logger.warning("[DIOT] no se pudo leer el RFC del .cer: %s", e)

    cliente = PresentadorDiot(headless=headless, progreso=progreso)
    return cliente.descargar_acuse(
        cer_path, key_path, password, ejercicio, periodo,
        tipo_declaracion=tipo_declaracion, directorio_salida=directorio_salida,
        rfc=rfc,
    )
