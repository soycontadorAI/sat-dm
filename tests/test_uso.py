"""Uso por acción (api/uso.py): taxonomía y regla de no-PII, cola persistida con
tope, vaciado en lotes, sin red, errores del servicio y cierre de sesión.

La red nunca se toca: `requests.post` se simula. La cola vive en tmp (fixture
autouse del conftest) y aquí se enciende con SAT_DM_USO=1.
"""

import json
import re
from datetime import datetime, timedelta, timezone

import pytest
import requests

from sat_descarga.api import license_client as lc
from sat_descarga.api import uso

# Huella de la taxonomía v1. La MISMA constante vive en todoconta-apps
# (apps/web/src/lib/uso/__tests__/taxonomia.test.ts): si cambias un evento,
# una propiedad o un valor permitido, cambia los dos repos y las dos huellas.
HUELLA_V1 = "14346c4daaf7"


@pytest.fixture
def encendido(monkeypatch):
    monkeypatch.delenv("SAT_DM_SIN_USO", raising=False)
    monkeypatch.setenv("SAT_DM_USO", "1")
    monkeypatch.setenv("SENTRY_RELEASE", "2.4.0")
    monkeypatch.delenv("SAT_DM_MODO", raising=False)


@pytest.fixture
def sesion(monkeypatch):
    s = lc.Session(access_token="token-1", refresh_token="refresh-1", user_id="u-1", email=None)
    monkeypatch.setattr(lc, "load_session", lambda: s)
    return s


class _Resp:
    def __init__(self, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {}


class ServidorFalso:
    """Registra cada POST y responde lo programado (status, (status, headers) o excepción)."""

    def __init__(self, *respuestas):
        self.llamadas = []
        self.respuestas = list(respuestas)

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.llamadas.append({"url": url, "json": json, "headers": headers})
        r = self.respuestas.pop(0) if self.respuestas else 200
        if isinstance(r, Exception):
            raise r
        if isinstance(r, tuple):
            return _Resp(*r)
        return _Resp(r)


def _cola():
    ruta = uso._ruta()
    if not ruta.exists():
        return []
    return [json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines() if linea]


# ---------------------------------------------------------------------------
# Taxonomía y regla de no-PII
# ---------------------------------------------------------------------------


def test_huella_fija_el_contrato_con_el_servidor():
    assert uso.huella() == HUELLA_V1
    assert len(uso.TAXONOMIA) == 25


def test_la_taxonomia_solo_admite_categorias_y_booleanos():
    """Ninguna propiedad acepta texto libre ni números: solo valores de una lista
    corta en snake_case (o booleano). Así un RFC, un nombre, un UUID de CFDI, un
    monto o un nombre de archivo no caben por construcción."""
    nombre = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
    valor = re.compile(r"^[a-z0-9][a-z0-9_]{0,30}$")
    for evento, props in uso.TAXONOMIA.items():
        assert nombre.match(evento), evento
        for prop, regla in props.items():
            assert nombre.match(prop), (evento, prop)
            if regla == uso.BOOLEANO:
                continue
            assert isinstance(regla, tuple) and regla, (evento, prop)
            for v in regla:
                assert valor.match(v), (evento, prop, v)


@pytest.mark.parametrize(
    "evento, props",
    [
        ("empresa_agregada", {"rfc": "XAXX010101000"}),
        ("empresa_agregada", {"nombre": "Contadores del Norte SC"}),
        ("descarga_completada", {"uuid": "6F2A3B4C-1D2E-4F50-8A9B-0C1D2E3F4A5B"}),
        ("estatus_validado", {"monto": 15000.5}),
        ("excel_exportado", {"archivo": "cfdis_XAXX010101000.xlsx"}),
        ("tarea_creada", {"titulo": "Presentar la DIOT de junio"}),
        ("sesion_iniciada", {"email": "alguien@despacho.mx"}),
    ],
)
def test_rechaza_propiedades_fuera_de_la_lista(encendido, evento, props):
    with pytest.raises(ValueError):
        uso.validar(evento, props)
    uso.track(evento, **props)
    assert _cola() == []


@pytest.mark.parametrize(
    "evento, props",
    [
        ("calculadora_usada", {"calculadora": "XAXX010101000"}),
        ("descarga_completada", {"tamano": "1234"}),
        ("descarga_completada", {"tamano": 1234}),
        ("empresa_agregada", {"nueva": "si"}),
        ("empresa_agregada", {"nueva": 1}),
        ("listas_negras_consultada", {"modo": "XAXX010101000,XEXX010101000"}),
    ],
)
def test_rechaza_valores_fuera_de_la_lista(encendido, evento, props):
    with pytest.raises(ValueError):
        uso.validar(evento, props)
    uso.track(evento, **props)
    assert _cola() == []


def test_rechaza_eventos_desconocidos(encendido):
    with pytest.raises(ValueError):
        uso.validar("pantalla_vista", {})
    uso.track("pantalla_vista")
    assert _cola() == []


def test_el_error_nombra_la_propiedad_pero_nunca_el_valor():
    with pytest.raises(ValueError) as e:
        uso.validar("calculadora_usada", {"calculadora": "XAXX010101000"})
    assert "XAXX010101000" not in str(e.value)
    assert "calculadora" in str(e.value)


def test_propiedades_en_none_se_omiten():
    assert uso.validar("descarga_solicitada", {"canal": "rapida", "tipo": None}) == {"canal": "rapida"}


def test_el_evento_solo_lleva_id_evento_props_y_fecha(encendido):
    uso.track("descarga_completada", canal="web_service", tipo="emitidos",
              tamano="11_100", segundo_plano=True)
    (ev,) = _cola()
    assert set(ev) == {"id", "evento", "props", "ocurrido_en"}
    assert ev["evento"] == "descarga_completada"
    assert ev["props"] == {"canal": "web_service", "tipo": "emitidos",
                           "tamano": "11_100", "segundo_plano": True}
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ev["ocurrido_en"])


def test_el_origen_es_categorico_y_viaja_con_el_evento(encendido):
    assert uso.origen_de_cabecera("mcp") == "mcp"
    assert uso.origen_de_cabecera(" API ") == "api"
    assert uso.origen_de_cabecera("abacus") == "abacus"
    assert uso.origen_de_cabecera(None) == "app"
    assert uso.origen_de_cabecera("XAXX010101000") == "app"

    marca = uso.fijar_origen("mcp")
    try:
        uso.track("diot_generada")
    finally:
        uso.restaurar_origen(marca)
    marca = uso.fijar_origen("cualquier-cosa")  # fuera de la lista: sin origen
    try:
        uso.track("diot_txt_exportado")
    finally:
        uso.restaurar_origen(marca)
    uso.track("empresa_archivada")  # fuera de una petición (p. ej. el poller)
    assert [e.get("origen") for e in _cola()] == ["mcp", None, None]


# ---------------------------------------------------------------------------
# Encendido
# ---------------------------------------------------------------------------


def test_apagado_por_defecto_en_desarrollo_y_pruebas(monkeypatch):
    monkeypatch.delenv("SAT_DM_SIN_USO", raising=False)
    monkeypatch.delenv("SAT_DM_USO", raising=False)
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("SAT_DM_MODO", raising=False)
    assert uso.activo() is False
    uso.track("diot_generada")
    assert _cola() == []


def test_encendido_en_desktop_empaquetada_y_en_hosted(monkeypatch):
    monkeypatch.delenv("SAT_DM_SIN_USO", raising=False)
    monkeypatch.delenv("SAT_DM_USO", raising=False)
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "production")
    assert uso.activo() is True
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "development")
    assert uso.activo() is False
    monkeypatch.setenv("SAT_DM_MODO", "hosted")
    assert uso.activo() is True


def test_kill_switch_gana(monkeypatch):
    monkeypatch.setenv("SAT_DM_USO", "1")
    monkeypatch.setenv("SAT_DM_MODO", "hosted")
    monkeypatch.setenv("SAT_DM_SIN_USO", "1")
    assert uso.activo() is False


# ---------------------------------------------------------------------------
# Cola local
# ---------------------------------------------------------------------------


def test_ventana_cuenta_una_vez_por_intencion(encendido, monkeypatch):
    reloj = [1000.0]
    monkeypatch.setattr(uso.time, "monotonic", lambda: reloj[0])
    for _ in range(5):  # la calculadora recalcula con cada tecla
        uso.track("calculadora_usada", calculadora="isr")
    uso.track("calculadora_usada", calculadora="sbc")  # otra calculadora sí cuenta
    assert [e["props"]["calculadora"] for e in _cola()] == ["isr", "sbc"]
    reloj[0] += 31 * 60  # pasada la ventana vuelve a contar
    uso.track("calculadora_usada", calculadora="isr")
    assert len(_cola()) == 3


def test_eventos_sin_ventana_cuentan_siempre(encendido):
    for _ in range(3):
        uso.track("excel_exportado", tipo="cfdi", formato="xlsx")
    assert len(_cola()) == 3


def test_tope_tira_los_mas_viejos(encendido, monkeypatch):
    monkeypatch.setattr(uso, "TOPE_COLA", 10)
    for i in range(25):
        uso.track("tarea_creada", desde_sugerencia=(i % 2 == 0))
    cola = _cola()
    assert len(cola) <= 11  # tope + 10% de holgura
    ids = [e["id"] for e in cola]
    assert len(set(ids)) == len(ids)
    # Los que quedan son los últimos en llegar: el último evento sigue ahí.
    ultimo = cola[-1]
    assert ultimo["props"] == {"desde_sugerencia": True}  # i = 24


def test_la_cola_sobrevive_un_reinicio(encendido, monkeypatch):
    uso.track("diot_generada")
    uso.track("diot_txt_exportado")
    monkeypatch.setattr(uso, "_conteo", None)  # proceso nuevo
    uso.track("empresa_archivada")
    assert [e["evento"] for e in _cola()] == ["diot_generada", "diot_txt_exportado", "empresa_archivada"]
    assert uso.pendientes() == 3


def test_lineas_rotas_se_saltan_y_se_limpian(encendido, sesion, monkeypatch):
    ruta = uso._ruta()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    bueno = {"id": "11111111-1111-4111-8111-111111111111", "evento": "diot_generada",
             "props": {}, "ocurrido_en": uso._ahora_iso()}
    ruta.write_text("\x00\x00\x00\n{no es json\n" + json.dumps(bueno) + "\n[1,2]\n", encoding="utf-8")
    assert uso.pendientes() == 1
    servidor = ServidorFalso(200)
    monkeypatch.setattr(uso.requests, "post", servidor)
    assert uso.vaciar() is True
    assert servidor.llamadas[0]["json"]["eventos"] == [bueno]
    assert ruta.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# Envío
# ---------------------------------------------------------------------------


def test_vaciar_manda_lotes_con_el_bearer_y_vacia_la_cola(encendido, sesion, monkeypatch):
    for _ in range(450):
        uso.track("excel_exportado", tipo="nomina", formato="xlsx")
    servidor = ServidorFalso()
    monkeypatch.setattr(uso.requests, "post", servidor)

    assert uso.vaciar() is True
    assert [len(c["json"]["eventos"]) for c in servidor.llamadas] == [200, 200, 50]
    llamada = servidor.llamadas[0]
    assert llamada["url"].endswith("/api/desktop/eventos")
    assert llamada["headers"] == {"Authorization": "Bearer token-1"}
    cuerpo = llamada["json"]
    assert set(cuerpo) == {"lote", "plataforma", "version_app", "eventos"}
    assert cuerpo["plataforma"] == "desktop" and cuerpo["version_app"] == "2.4.0"
    assert re.match(r"^[0-9a-f-]{36}$", cuerpo["lote"])
    assert uso.pendientes() == 0


def test_plataforma_web_en_modo_hosted(encendido, sesion, monkeypatch):
    monkeypatch.setenv("SAT_DM_MODO", "hosted")
    uso.track("diot_generada")
    servidor = ServidorFalso()
    monkeypatch.setattr(uso.requests, "post", servidor)
    uso.vaciar()
    assert servidor.llamadas[0]["json"]["plataforma"] == "web"


def test_sin_red_conserva_la_cola(encendido, sesion, monkeypatch):
    uso.track("diot_generada")
    uso.track("diot_txt_exportado")
    servidor = ServidorFalso(requests.ConnectionError("sin internet"))
    monkeypatch.setattr(uso.requests, "post", servidor)
    assert uso.vaciar() is False
    assert [e["evento"] for e in _cola()] == ["diot_generada", "diot_txt_exportado"]
    # Al volver la red, sale todo y en el mismo orden.
    servidor.respuestas = [200]
    assert uso.vaciar() is True
    assert [e["evento"] for e in servidor.llamadas[-1]["json"]["eventos"]] == [
        "diot_generada", "diot_txt_exportado",
    ]


@pytest.mark.parametrize("status", [404, 500, 502, 503])
def test_errores_del_servicio_conservan_la_cola(encendido, sesion, monkeypatch, status):
    uso.track("diot_generada")
    monkeypatch.setattr(uso.requests, "post", ServidorFalso(status))
    assert uso.vaciar() is False
    assert uso.pendientes() == 1


def test_un_400_descarta_el_lote_para_no_atorar_la_cola(encendido, sesion, monkeypatch):
    uso.track("diot_generada")
    monkeypatch.setattr(uso.requests, "post", ServidorFalso(400))
    assert uso.vaciar() is True
    assert uso.pendientes() == 0


def test_un_429_pausa_los_envios(encendido, sesion, monkeypatch):
    reloj = [5000.0]
    monkeypatch.setattr(uso.time, "monotonic", lambda: reloj[0])
    uso.track("diot_generada")
    servidor = ServidorFalso((429, {"Retry-After": "120"}))
    monkeypatch.setattr(uso.requests, "post", servidor)
    assert uso.vaciar() is False
    assert uso.vaciar() is False  # en pausa: ni lo intenta
    assert len(servidor.llamadas) == 1
    reloj[0] += 121
    assert uso.vaciar() is True
    assert len(servidor.llamadas) == 2


def test_401_renueva_la_sesion_y_reintenta(encendido, sesion, monkeypatch):
    uso.track("diot_generada")
    nueva = lc.Session(access_token="token-2", refresh_token="r-2", user_id="u-1", email=None)
    monkeypatch.setattr(lc, "try_refresh_session", lambda s: nueva)
    servidor = ServidorFalso(401, 200)
    monkeypatch.setattr(uso.requests, "post", servidor)
    assert uso.vaciar() is True
    assert [c["headers"]["Authorization"] for c in servidor.llamadas] == [
        "Bearer token-1", "Bearer token-2",
    ]


def test_sin_sesion_no_manda_nada(encendido, monkeypatch):
    monkeypatch.setattr(lc, "load_session", lambda: None)
    uso.track("diot_generada")
    servidor = ServidorFalso()
    monkeypatch.setattr(uso.requests, "post", servidor)
    assert uso.vaciar() is False
    assert servidor.llamadas == [] and uso.pendientes() == 1


def test_cola_vacia_no_toca_el_keychain(encendido, monkeypatch):
    def explota():
        raise AssertionError("no debía leer la sesión")

    monkeypatch.setattr(lc, "load_session", explota)
    assert uso.vaciar() is True


def test_eventos_de_hace_mas_de_30_dias_se_tiran(encendido, sesion, monkeypatch):
    ruta = uso._ruta()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    viejo = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ruta.write_text(json.dumps({"id": "a", "evento": "diot_generada", "props": {},
                                "ocurrido_en": viejo}) + "\n", encoding="utf-8")
    uso.track("diot_txt_exportado")
    servidor = ServidorFalso()
    monkeypatch.setattr(uso.requests, "post", servidor)
    assert uso.vaciar() is True
    assert [e["evento"] for e in servidor.llamadas[0]["json"]["eventos"]] == ["diot_txt_exportado"]


def test_cerrar_sesion_manda_lo_pendiente_y_vacia_la_cola(encendido, sesion, monkeypatch):
    uso.track("diot_generada")
    servidor = ServidorFalso()
    monkeypatch.setattr(uso.requests, "post", servidor)
    uso.al_cerrar_sesion()
    assert len(servidor.llamadas) == 1 and uso.pendientes() == 0


def test_cerrar_sesion_sin_red_igual_vacia_la_cola(encendido, sesion, monkeypatch):
    """Nada de esta cuenta debe atribuírsele a la siguiente que inicie sesión."""
    uso.track("diot_generada")
    monkeypatch.setattr(uso.requests, "post", ServidorFalso(requests.ConnectionError()))
    uso.al_cerrar_sesion()
    assert uso.pendientes() == 0


def test_detener_hace_un_ultimo_envio(encendido, sesion, monkeypatch):
    uso.track("diot_generada")
    servidor = ServidorFalso()
    monkeypatch.setattr(uso.requests, "post", servidor)
    uso.detener()
    assert len(servidor.llamadas) == 1 and uso.pendientes() == 0


# ---------------------------------------------------------------------------
# Ayudantes de propiedades
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n, esperado",
    [(0, "0"), (1, "1_10"), (10, "1_10"), (11, "11_100"), (100, "11_100"),
     (101, "101_1000"), (1000, "101_1000"), (1001, "1001_10000"),
     (10000, "1001_10000"), (10001, "mas_10000"), (None, None), ("12", None), (True, None)],
)
def test_rango(n, esperado):
    assert uso.rango(n) == esperado
    if esperado is not None:
        assert esperado in uso.TAMANOS


def test_tipos_de_descarga():
    assert uso.tipo_cfdi("E") == "emitidos"
    assert uso.tipo_cfdi("r") == "recibidos"
    assert uso.tipo_cfdi("R", "Metadata") == "metadata"
    assert uso.tipo_cfdi(None) is None
    assert uso.tipo_de_solicitud({"tipo": "CFDI · emitidos", "tipo_comprobante": "E"}) == "emitidos"
    assert uso.tipo_de_solicitud({"tipo": "Metadata · recibidos", "tipo_comprobante": "R"}) == "metadata"
    assert uso.tipo_de_solicitud(None) is None
