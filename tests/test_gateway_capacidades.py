"""Capacidades del plan en el gateway (F1): el scope `mcp` exige
`capacidades.mcp`, los scopes REST exigen `capacidades.api` (o Abacus) y el
vínculo de Abacus exige `capacidades.abacus`. El legado conserva la MCP.

La licencia del dueño se simula (la API de servicios nunca se toca).
"""

import base64
import importlib
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("mcp")
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

GATEWAY_DIR = Path(__file__).parent.parent / "deploy" / "gateway"
MODULOS = ("main", "oauth", "capacidades")


def _caps(mcp=False, abacus=False, api=False):
    return {
        "web": True, "exportar": True, "mcp": mcp, "abacus": abacus, "api": api,
        "piloto": mcp, "vigilancia": {"app_correo": mcp, "whatsapp": abacus},
        "reporte_cliente": abacus,
    }


# Licencia calculada por plan, como la devuelve /api/admin/license.
LICENCIAS = {
    "u-legado": {"plan_codigo": "desktop", "legado": True, "capacidades": _caps(mcp=True)},
    "u-fundador": {"plan_codigo": "fundador", "legado": True, "capacidades": _caps(mcp=True)},
    "u-web-viejo": {"plan_codigo": "empresarial", "legado": True, "capacidades": _caps(mcp=True)},
    "u-legado-ia": {"plan_codigo": "desktop_ia", "legado": True,
                    "capacidades": _caps(mcp=True, abacus=True, api=True)},
    "u-trial": {"plan_codigo": "trial", "legado": False, "capacidades": _caps(mcp=True)},
    "u-gratis": {"plan_codigo": "gratis", "legado": False, "capacidades": _caps()},
    "u-esencial": {"plan_codigo": "esencial", "legado": False, "capacidades": _caps()},
    "u-pro": {"plan_codigo": "pro", "legado": False, "capacidades": _caps(mcp=True)},
    "u-completo": {"plan_codigo": "completo", "legado": False,
                   "capacidades": _caps(mcp=True, abacus=True, api=True)},
    # Override raro: Abacus sin API. La key del vínculo sigue usando la REST.
    "u-solo-abacus": {"plan_codigo": "medida", "legado": False,
                      "capacidades": _caps(mcp=True, abacus=True, api=False)},
    # Backend de antes de F0: sin capacidades → nunca candado.
    "u-viejo": {"plan": "premium"},
}

TODOS_LOS_SCOPES = ["documentos:leer", "cfdi:solicitar", "listas-negras:consultar", "mcp"]


@pytest.fixture(scope="module")
def gw(tmp_path_factory):
    previos = {k: os.environ.get(k) for k in ("OAUTH_DB_PATH", "EXIGIR_LICENCIA", "SAT_DM_MASTER_KEY")}
    os.environ["OAUTH_DB_PATH"] = str(tmp_path_factory.mktemp("oauth") / "oauth.db")
    os.environ["EXIGIR_LICENCIA"] = "0"
    os.environ["SAT_DM_MASTER_KEY"] = base64.b64encode(b"0" * 32).decode()
    sys.path.insert(0, str(GATEWAY_DIR))
    for mod in MODULOS:
        sys.modules.pop(mod, None)
    main_mod = importlib.import_module("main")
    yield main_mod, sys.modules["oauth"], sys.modules["capacidades"]
    sys.path.remove(str(GATEWAY_DIR))
    for mod in MODULOS:
        sys.modules.pop(mod, None)
    for k, v in previos.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(scope="module")
def client(gw):
    main_mod, _, _ = gw
    with TestClient(main_mod.app, base_url="http://localhost") as c:
        yield c


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def servicio(gw, monkeypatch):
    """Simula GET /api/admin/license y cuenta las llamadas."""
    _, _, caps = gw
    caps.limpiar_cache()
    monkeypatch.setattr(caps, "LICENCIA_GATEWAY_SECRET", "secreto-de-prueba")
    llamadas = []

    def fake_get(url, params=None, headers=None, timeout=None):
        assert headers["Authorization"] == "Bearer secreto-de-prueba"
        uid = (params or {}).get("user_id")
        llamadas.append(uid)
        if uid == "u-caido":
            return _Resp(500, {"error": "boom"})
        if uid not in LICENCIAS:
            return _Resp(404, {"error": "Usuario no encontrado"})
        return _Resp(200, {"perfil": {"id": uid}, "license": LICENCIAS[uid], "notas": []})

    monkeypatch.setattr(caps.requests, "get", fake_get)
    yield llamadas
    caps.limpiar_cache()


def _modo(gw, monkeypatch, modo):
    monkeypatch.setattr(gw[2], "MODO", modo)


def _usuario(uid, scopes=None):
    return {"user_id": uid, "scopes": list(TODOS_LOS_SCOPES if scopes is None else scopes)}


def _rechazo(fn) -> int | None:
    try:
        fn()
    except HTTPException as e:
        return e.status_code
    return None


# ---------------------------------------------------------------------------
# Tabla de verdad en modo exigir
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "uid, mcp_ok, rest_ok",
    [
        ("u-legado", True, False),
        ("u-fundador", True, False),
        ("u-web-viejo", True, False),
        ("u-legado-ia", True, True),
        ("u-trial", True, False),
        ("u-gratis", False, False),
        ("u-esencial", False, False),
        ("u-pro", True, False),
        ("u-completo", True, True),
        ("u-solo-abacus", True, True),
        ("u-viejo", True, True),
    ],
)
def test_scopes_por_plan_en_modo_exigir(gw, monkeypatch, servicio, uid, mcp_ok, rest_ok):
    main_mod, _, caps = gw
    _modo(gw, monkeypatch, "exigir")
    user = _usuario(uid)
    assert _rechazo(lambda: main_mod._exigir_scope(user, "mcp")) == (None if mcp_ok else 403)
    for scope in ("documentos:leer", "cfdi:solicitar", "listas-negras:consultar"):
        assert _rechazo(lambda: main_mod._exigir_scope(user, scope)) == (None if rest_ok else 403)


def test_mensaje_del_rechazo_lleva_a_planes(gw, monkeypatch, servicio):
    main_mod, _, _ = gw
    _modo(gw, monkeypatch, "exigir")
    with pytest.raises(HTTPException) as e:
        main_mod._exigir_scope(_usuario("u-esencial"), "mcp")
    assert "Pro y Completo" in e.value.detail and "todoconta.com/planes" in e.value.detail
    with pytest.raises(HTTPException) as e:
        main_mod._exigir_scope(_usuario("u-pro"), "documentos:leer")
    assert "API" in e.value.detail and "Completo" in e.value.detail


def test_key_sin_el_scope_se_rechaza_aunque_el_plan_lo_tenga(gw, monkeypatch, servicio):
    main_mod, _, _ = gw
    _modo(gw, monkeypatch, "exigir")
    user = _usuario("u-completo", scopes=["documentos:leer"])
    with pytest.raises(HTTPException) as e:
        main_mod._exigir_scope(user, "mcp")
    assert e.value.status_code == 403 and "permiso `mcp`" in e.value.detail
    assert servicio == []  # ni siquiera consultó el plan


# ---------------------------------------------------------------------------
# Modos y fallas: nadie pierde acceso por desplegar
# ---------------------------------------------------------------------------


def test_modo_observar_deja_pasar_y_registra(gw, monkeypatch, servicio, caplog):
    main_mod, _, _ = gw
    _modo(gw, monkeypatch, "observar")
    caplog.set_level("WARNING", logger="gateway")
    main_mod._exigir_scope(_usuario("u-esencial"), "mcp")  # no lanza
    main_mod._exigir_scope(_usuario("u-esencial"), "mcp")
    avisos = [r for r in caplog.records if "capacidad faltante" in r.getMessage()]
    assert len(avisos) == 1  # uno por usuario y capacidad por hora
    assert "cap=mcp" in avisos[0].getMessage() and "plan=esencial" in avisos[0].getMessage()


def test_modo_apagado_ni_consulta(gw, monkeypatch, servicio):
    main_mod, _, _ = gw
    _modo(gw, monkeypatch, "apagado")
    main_mod._exigir_scope(_usuario("u-esencial"), "mcp")
    assert servicio == []


def test_sin_token_no_consulta_ni_bloquea(gw, monkeypatch, servicio):
    main_mod, _, caps = gw
    _modo(gw, monkeypatch, "exigir")
    monkeypatch.setattr(caps, "LICENCIA_GATEWAY_SECRET", "")
    main_mod._exigir_scope(_usuario("u-esencial"), "mcp")
    assert servicio == []


@pytest.mark.parametrize("uid", ["u-caido", "u-desconocido"])
def test_servicio_que_falla_no_bloquea(gw, monkeypatch, servicio, uid):
    main_mod, _, _ = gw
    _modo(gw, monkeypatch, "exigir")
    main_mod._exigir_scope(_usuario(uid), "mcp")


def test_red_caida_no_bloquea(gw, monkeypatch, servicio):
    import requests

    main_mod, _, caps = gw
    _modo(gw, monkeypatch, "exigir")

    def sin_red(*a, **k):
        raise requests.ConnectionError("sin red")

    monkeypatch.setattr(caps.requests, "get", sin_red)
    main_mod._exigir_scope(_usuario("u-esencial"), "mcp")


def test_cache_por_usuario(gw, monkeypatch, servicio):
    main_mod, _, _ = gw
    _modo(gw, monkeypatch, "exigir")
    for _ in range(5):
        main_mod._exigir_scope(_usuario("u-pro"), "mcp")
    assert servicio == ["u-pro"]


# ---------------------------------------------------------------------------
# /mcp por HTTP: API key y token OAuth
# ---------------------------------------------------------------------------


def test_mcp_con_api_key_de_esencial_403(gw, client, monkeypatch, servicio):
    main_mod, _, _ = gw
    _modo(gw, monkeypatch, "exigir")
    monkeypatch.setattr(main_mod, "_validar_key", lambda key: _usuario("u-esencial"))
    r = client.post("/mcp", headers={"x-api-key": "tc_live_prueba"}, json={})
    assert r.status_code == 403
    assert "MCP" in r.json()["detail"]


@pytest.mark.parametrize("uid", ["u-pro", "u-legado", "u-trial"])
def test_mcp_con_api_key_de_planes_con_mcp_pasa(gw, client, monkeypatch, servicio, uid):
    main_mod, _, _ = gw
    _modo(gw, monkeypatch, "exigir")
    monkeypatch.setattr(main_mod, "_validar_key", lambda key: _usuario(uid))
    r = client.post("/mcp", headers={"x-api-key": "tc_live_prueba"}, json={})
    assert r.status_code not in (401, 403)


def test_mcp_con_token_oauth_revisa_el_plan(gw, client, monkeypatch, servicio):
    main_mod, oauth_mod, _ = gw
    _modo(gw, monkeypatch, "exigir")
    monkeypatch.setattr(
        oauth_mod, "validar_access_token",
        lambda token: {"user_id": "u-gratis", "scopes": ["mcp"], "email": None},
    )
    r = client.post("/mcp", headers={"authorization": "Bearer mcp_at_x"}, json={})
    assert r.status_code == 403

    monkeypatch.setattr(
        oauth_mod, "validar_access_token",
        lambda token: {"user_id": "u-legado", "scopes": ["mcp"], "email": None},
    )
    r = client.post("/mcp", headers={"authorization": "Bearer mcp_at_x"}, json={})
    assert r.status_code not in (401, 403)


# ---------------------------------------------------------------------------
# OAuth: autorizar exige la MCP del plan (con la licencia del propio usuario)
# ---------------------------------------------------------------------------


def _licencia_oauth(monkeypatch, oauth_mod, payload):
    monkeypatch.setattr(oauth_mod, "EXIGIR_LICENCIA", True)
    monkeypatch.setattr(oauth_mod.requests, "get", lambda *a, **k: _Resp(200, payload))


def test_authorize_esencial_rechazado_en_modo_exigir(gw, monkeypatch):
    _, oauth_mod, _ = gw
    _modo(gw, monkeypatch, "exigir")
    _licencia_oauth(monkeypatch, oauth_mod, {
        "plan": "premium", "premium_features_unlocked": True, **LICENCIAS["u-esencial"],
    })
    with pytest.raises(HTTPException) as e:
        oauth_mod._validar_licencia("jwt", "alguien@ejemplo.test")
    assert e.value.status_code == 403


@pytest.mark.parametrize("uid", ["u-legado", "u-fundador", "u-trial", "u-pro", "u-viejo"])
def test_authorize_planes_con_mcp_pasan(gw, monkeypatch, uid):
    _, oauth_mod, _ = gw
    _modo(gw, monkeypatch, "exigir")
    plan = "founder" if uid == "u-fundador" else ("trial" if uid == "u-trial" else "premium")
    _licencia_oauth(monkeypatch, oauth_mod, {"plan": plan, **LICENCIAS[uid]})
    oauth_mod._validar_licencia("jwt", "alguien@ejemplo.test")


def test_authorize_esencial_pasa_en_modo_observar(gw, monkeypatch):
    _, oauth_mod, _ = gw
    _modo(gw, monkeypatch, "observar")
    _licencia_oauth(monkeypatch, oauth_mod, {"plan": "premium", **LICENCIAS["u-esencial"]})
    oauth_mod._validar_licencia("jwt", "alguien@ejemplo.test")


# ---------------------------------------------------------------------------
# Vínculo de Abacus
# ---------------------------------------------------------------------------


def _vinculo(monkeypatch, main_mod, uid):
    """Supabase responde el vínculo; la licencia sigue saliendo de `servicio`
    (main y capacidades comparten el mismo módulo `requests`)."""
    monkeypatch.setattr(main_mod, "VINCULOS_INTERNAL_TOKEN", "interno")
    previo = main_mod.requests.get

    def fake(url, *a, **k):
        if "asistente_vinculos" in url:
            return _Resp(200, [{"user_id": uid, "api_key_cifrada": "cifrada"}])
        return previo(url, *a, **k)

    monkeypatch.setattr(main_mod.requests, "get", fake)


@pytest.mark.parametrize(
    "uid, esperado",
    [("u-completo", 200), ("u-legado-ia", 200), ("u-legado", 403), ("u-pro", 403),
     ("u-trial", 403), ("u-viejo", 200)],
)
def test_vinculo_abacus_por_plan(gw, client, monkeypatch, servicio, uid, esperado):
    main_mod, _, _ = gw
    _modo(gw, monkeypatch, "exigir")
    _vinculo(monkeypatch, main_mod, uid)
    r = client.get("/internal/vinculos/+5215512345678", headers={"x-interno-token": "interno"})
    assert r.status_code == esperado
    if esperado == 403:
        assert "Abacus" in r.json()["detail"]
