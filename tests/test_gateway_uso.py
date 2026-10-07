"""Uso por acción en el gateway (deploy/gateway/uso.py y su cableado en main.py):
cuenta tools MCP, llamadas REST y mensajes de Abacus por cuenta, con la misma
lista blanca que el agente y sin argumentos, RFC ni contenido.

La parte del módulo corre sin FastAPI ni MCP; la del cableado se salta si el
SDK de MCP no está instalado (igual que las demás pruebas del gateway).
"""

import asyncio
import base64
import importlib
import importlib.util
import os
import sys
from collections import deque
from pathlib import Path

import pytest
import requests

from sat_descarga.api import uso as uso_agente

GATEWAY_DIR = Path(__file__).parent.parent / "deploy" / "gateway"
USER = "0b1f3c9e-5d2a-4e8b-9c7d-112233445566"


def _cargar_modulo():
    spec = importlib.util.spec_from_file_location("gateway_uso_aislado", GATEWAY_DIR / "uso.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def gw_uso(monkeypatch):
    mod = _cargar_modulo()
    monkeypatch.setattr(mod, "_asegurar_hilo", lambda: None)  # sin hilo en pruebas
    yield mod
    mod._cola.clear()  # el atexit del módulo no tiene nada que mandar


class _Resp:
    def __init__(self, status=200):
        self.status_code = status


class ServidorFalso:
    def __init__(self, *respuestas):
        self.llamadas = []
        self.respuestas = list(respuestas)

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.llamadas.append({"url": url, "json": json, "headers": headers})
        r = self.respuestas.pop(0) if self.respuestas else 200
        if isinstance(r, Exception):
            raise r
        return _Resp(r)


# ---------------------------------------------------------------------------
# Módulo
# ---------------------------------------------------------------------------


def test_los_eventos_del_gateway_son_los_de_la_taxonomia(gw_uso):
    for evento in uso_agente.EVENTOS_DEL_GATEWAY:
        esperado = {k: tuple(v) for k, v in uso_agente.TAXONOMIA[evento].items()}
        assert {k: tuple(v) for k, v in gw_uso.EVENTOS[evento].items()} == esperado
    assert set(gw_uso.EVENTOS) == set(uso_agente.EVENTOS_DEL_GATEWAY)


@pytest.mark.parametrize(
    "path, esperado",
    [
        ("/v1/empresas", "empresas"),
        ("/v1/csf", "csf"),
        ("/v1/opinion", "opinion"),
        ("/v1/cfdi/solicitudes", "cfdi_solicitar"),
        ("/v1/cfdi/solicitudes/CAMY89051862A/8b2e-sol", "cfdi_estado"),
        ("/v1/cfdi/solicitudes/CAMY89051862A/8b2e-sol/zip", "cfdi_zip"),
        ("/v1/cfdi/procesar", "cfdi_procesar"),
        ("/v1/cfdi/resumen", "cfdi_resumen"),
        ("/v1/cfdi/reporte/top-contrapartes", "cfdi_reporte"),
        ("/v1/cfdi/excel", "cfdi_excel"),
        ("/v1/calculadoras/finiquito", "calculadora"),
        ("/v1/listas-negras", "listas_negras"),
        ("/v1/algo-nuevo/CAMY89051862A", "otro"),
    ],
)
def test_endpoint_de_nunca_deja_pasar_el_dato(gw_uso, path, esperado):
    assert gw_uso.endpoint_de(path) == esperado
    assert esperado in gw_uso.ENDPOINTS_API


def test_tool_nueva_cuenta_como_otra(gw_uso):
    assert gw_uso.herramienta_de("descargar_csf") == "descargar_csf"
    assert gw_uso.herramienta_de("tool_que_aun_no_existe") == "otra"


def test_registrar_valida_cuenta_y_propiedades(gw_uso):
    gw_uso.registrar(None, "abacus_mensaje")
    gw_uso.registrar("user-1", "abacus_mensaje")  # no es un user_id real
    gw_uso.registrar(USER, "mcp_herramienta", herramienta="descargar_csf", rfc="CAMY89051862A")
    gw_uso.registrar(USER, "api_llamada", endpoint="/v1/csf")  # la ruta cruda no pasa
    gw_uso.registrar(USER, "evento_inventado")
    assert gw_uso.pendientes() == 0

    gw_uso.registrar(USER, "mcp_herramienta", herramienta="descargar_csf", conexion="oauth")
    (ev,) = list(gw_uso._cola)
    assert set(ev) == {"id", "user_id", "evento", "props", "ocurrido_en", "origen"}
    assert ev["user_id"] == USER and ev["props"] == {"herramienta": "descargar_csf", "conexion": "oauth"}
    assert ev["origen"] == "mcp"


def test_origen_de_los_eventos_del_gateway(gw_uso):
    gw_uso.registrar(USER, "api_llamada", endpoint="csf", origen="integracion")
    gw_uso.registrar(USER, "api_llamada", endpoint="csf", origen="abacus")
    gw_uso.registrar(USER, "abacus_mensaje")
    assert [e["origen"] for e in gw_uso._cola] == ["api", "abacus", "abacus"]
    assert all(e["origen"] in uso_agente.ORIGENES for e in gw_uso._cola)


def test_kill_switch(gw_uso, monkeypatch):
    monkeypatch.setattr(gw_uso, "ACTIVO", False)
    gw_uso.registrar(USER, "abacus_mensaje")
    assert gw_uso.pendientes() == 0


def test_sin_secreto_no_manda_y_conserva(gw_uso, monkeypatch):
    monkeypatch.setattr(gw_uso, "EVENTOS_GATEWAY_SECRET", "")
    servidor = ServidorFalso()
    monkeypatch.setattr(gw_uso.requests, "post", servidor)
    gw_uso.registrar(USER, "abacus_mensaje")
    assert gw_uso.vaciar() is False
    assert servidor.llamadas == [] and gw_uso.pendientes() == 1


def test_vaciar_manda_lotes_con_el_secreto(gw_uso, monkeypatch):
    monkeypatch.setattr(gw_uso, "EVENTOS_GATEWAY_SECRET", "secreto-gw")
    servidor = ServidorFalso()
    monkeypatch.setattr(gw_uso.requests, "post", servidor)
    for _ in range(250):
        gw_uso.registrar(USER, "api_llamada", endpoint="csf", origen="integracion")
    assert gw_uso.vaciar() is True
    assert [len(c["json"]["eventos"]) for c in servidor.llamadas] == [200, 50]
    llamada = servidor.llamadas[0]
    assert llamada["headers"] == {"Authorization": "Bearer secreto-gw"}
    assert llamada["json"]["plataforma"] == "gateway"
    assert gw_uso.pendientes() == 0


@pytest.mark.parametrize("falla", [requests.ConnectionError("caída"), 500, 503, 404])
def test_si_el_servicio_falla_la_cola_queda_intacta(gw_uso, monkeypatch, falla):
    monkeypatch.setattr(gw_uso, "EVENTOS_GATEWAY_SECRET", "secreto-gw")
    monkeypatch.setattr(gw_uso.requests, "post", ServidorFalso(falla))
    gw_uso.registrar(USER, "abacus_mensaje")
    gw_uso.registrar(USER, "api_llamada", endpoint="csf", origen="abacus")
    antes = list(gw_uso._cola)
    assert gw_uso.vaciar() is False
    assert list(gw_uso._cola) == antes


def test_un_400_descarta_el_lote(gw_uso, monkeypatch):
    monkeypatch.setattr(gw_uso, "EVENTOS_GATEWAY_SECRET", "secreto-gw")
    monkeypatch.setattr(gw_uso.requests, "post", ServidorFalso(400))
    gw_uso.registrar(USER, "abacus_mensaje")
    assert gw_uso.vaciar() is True and gw_uso.pendientes() == 0


def test_el_tope_tira_los_mas_viejos(gw_uso, monkeypatch):
    monkeypatch.setattr(gw_uso, "_cola", deque(maxlen=3))
    for endpoint in ("csf", "opinion", "empresas", "cfdi_excel", "listas_negras"):
        gw_uso.registrar(USER, "api_llamada", endpoint=endpoint, origen="integracion")
    assert [e["props"]["endpoint"] for e in gw_uso._cola] == ["empresas", "cfdi_excel", "listas_negras"]


# ---------------------------------------------------------------------------
# Cableado en main.py (MCP, REST y Abacus)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gw():
    pytest.importorskip("fastapi")
    pytest.importorskip("mcp")
    previos = {k: os.environ.get(k) for k in ("OAUTH_DB_PATH", "EXIGIR_LICENCIA", "SAT_DM_MASTER_KEY")}
    import tempfile

    os.environ["OAUTH_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "oauth.db")
    os.environ["EXIGIR_LICENCIA"] = "0"
    os.environ["SAT_DM_MASTER_KEY"] = base64.b64encode(b"0" * 32).decode()
    sys.path.insert(0, str(GATEWAY_DIR))
    for mod in ("main", "oauth", "capacidades", "uso"):
        sys.modules.pop(mod, None)
    main_mod = importlib.import_module("main")
    yield main_mod
    sys.path.remove(str(GATEWAY_DIR))
    for mod in ("main", "oauth", "capacidades", "uso"):
        sys.modules.pop(mod, None)
    for k, v in previos.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(scope="module")
def client(gw):
    from fastapi.testclient import TestClient

    # Un solo lifespan por módulo: el session manager de MCP corre una vez.
    with TestClient(gw.app, base_url="http://localhost") as c:
        yield c


@pytest.fixture
def cola(gw, monkeypatch):
    monkeypatch.setattr(gw.uso_srv, "_cola", deque(maxlen=100))
    monkeypatch.setattr(gw.uso_srv, "_asegurar_hilo", lambda: None)
    return gw.uso_srv._cola


class _RespJson:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def test_tool_mcp_cuenta_nombre_y_conexion(gw, cola, monkeypatch):
    monkeypatch.setattr(gw, "_agente_de", lambda user: ("http://agente-fake:8787", {}))
    monkeypatch.setattr(gw.requests, "get", lambda *a, **k: _RespJson(200, {"empresas": []}))
    token = gw.ctx_user.set({"user_id": USER, "scopes": ["mcp"], "conexion": "oauth"})
    try:
        asyncio.run(gw.mcp_srv.call_tool("listar_empresas", {}))
    finally:
        gw.ctx_user.reset(token)
    (ev,) = list(cola)
    assert ev["evento"] == "mcp_herramienta"
    assert ev["props"] == {"herramienta": "listar_empresas", "conexion": "oauth"}
    assert ev["user_id"] == USER


def test_la_tool_conserva_su_firma_para_el_cliente_mcp(gw):
    """El contador no debe cambiar el esquema que ve el LLM."""
    tools = {t.name: t for t in asyncio.run(gw.mcp_srv.list_tools())}
    assert set(tools) == set(uso_agente.HERRAMIENTAS_MCP) - {"otra"}
    assert set(tools["solicitar_cfdis"].inputSchema["properties"]) == {
        "rfc", "fecha_inicio", "fecha_fin", "tipo",
    }


def test_llamada_rest_cuenta_endpoint_y_origen(gw, client, cola, monkeypatch):
    monkeypatch.setattr(gw, "_validar_key", lambda key: {"user_id": USER, "scopes": ["listas-negras:consultar"]})
    monkeypatch.setattr(gw.caps_srv, "exigir", lambda *a, **k: None)
    monkeypatch.setattr(gw.requests, "post", lambda *a, **k: _RespJson(200, {}))
    r = client.post("/v1/listas-negras", json={"rfcs": ["CAMY89051862A"]},
                    headers={"X-Api-Key": "tc_live_x"})
    assert r.status_code == 200
    r = client.post("/v1/listas-negras", json={"rfcs": ["CAMY89051862A"]},
                    headers={"X-Api-Key": "tc_live_x", "X-Forwarded-For": "201.1.2.3"})
    assert r.status_code == 200
    # Sin key válida no hay a quién contarle nada.
    monkeypatch.setattr(gw, "_validar_key", lambda key: (_ for _ in ()).throw(
        gw.HTTPException(status_code=401, detail="no")))
    assert client.post("/v1/listas-negras", json={"rfcs": ["X"]}).status_code == 401
    eventos = list(cola)
    assert [e["props"] for e in eventos] == [
        {"endpoint": "listas_negras", "origen": "abacus"},
        {"endpoint": "listas_negras", "origen": "integracion"},
    ]
    assert all(e["evento"] == "api_llamada" and e["user_id"] == USER for e in eventos)
    assert "CAMY89051862A" not in repr(eventos)


def test_el_agente_recibe_el_origen_de_la_peticion(gw, client, cola, monkeypatch):
    vistos = []

    def agente_falso(user_id):
        return "http://agente-fake:8787", gw._headers_agente("token-del-agente")

    def get_falso(url, headers=None, **kw):
        vistos.append(headers)
        return _RespJson(200, {"empresas": []})

    monkeypatch.setattr(gw, "_asegurar_agente", agente_falso)
    monkeypatch.setattr(gw, "_validar_key", lambda key: {"user_id": USER, "scopes": ["documentos:leer"]})
    monkeypatch.setattr(gw.caps_srv, "exigir", lambda *a, **k: None)
    monkeypatch.setattr(gw.requests, "get", get_falso)
    client.get("/v1/empresas", headers={"X-Api-Key": "tc_live_x"})
    client.get("/v1/empresas", headers={"X-Api-Key": "tc_live_x", "X-Forwarded-For": "201.1.2.3"})
    assert [h["X-Todoconta-Origen"] for h in vistos] == ["abacus", "api"]
    assert all(h["X-Agent-Token"] == "token-del-agente" for h in vistos)
    # Fuera de una petición del gateway no se inventa un origen.
    assert "X-Todoconta-Origen" not in gw._headers_agente("t")


def test_mensaje_de_abacus_se_cuenta_sin_contenido(gw, client, cola, monkeypatch):
    monkeypatch.setattr(gw, "VINCULOS_INTERNAL_TOKEN", "interno")
    monkeypatch.setattr(gw.caps_srv, "exigir", lambda *a, **k: None)
    monkeypatch.setattr(
        gw.requests, "get",
        lambda *a, **k: _RespJson(200, [{"user_id": USER, "api_key_cifrada": "cifrada"}]),
    )
    r = client.get("/internal/vinculos/+5215512345678", headers={"X-Interno-Token": "interno"})
    assert r.status_code == 200
    (ev,) = list(cola)
    assert ev["evento"] == "abacus_mensaje" and ev["props"] == {} and ev["user_id"] == USER
    assert "5512345678" not in repr(ev)
