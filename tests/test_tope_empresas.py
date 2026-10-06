"""Tope de empresas activas por plan (F1): alta con e.firma, alta con
Contraseña y desarchivar contra `limites.empresas` de la licencia en cache.

El catálogo y el cache de licencia viven en tmp_path; el keychain es en memoria
(conftest). La red nunca se toca: el refresco de la licencia se simula.
"""

from __future__ import annotations

import time

import pytest
import requests

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from sat_descarga.api import license_client as lc  # noqa: E402
from sat_descarga.api import server  # noqa: E402
from sat_descarga.api import tope_empresas as te  # noqa: E402
from sat_descarga.api.routers import empresas as empresas_router  # noqa: E402
from sat_descarga.cli import config_store  # noqa: E402


def _caps(mcp=False, abacus=False, api=False):
    return {
        "web": True,
        "exportar": True,
        "mcp": mcp,
        "abacus": abacus,
        "api": api,
        "piloto": mcp,
        "vigilancia": {"app_correo": mcp, "whatsapp": abacus},
        "reporte_cliente": abacus,
    }


BASE = {"authenticated": True, "user_id": "user-1", "plan": "premium", "is_founder": False}

ESENCIAL = {**BASE, "plan_codigo": "esencial", "plan_nombre": "Esencial",
            "limites": {"empresas": 10, "usuarios": 1}, "capacidades": _caps(),
            "legado": False, "precio_asegurado_mxn": None}
PRO = {**ESENCIAL, "plan_codigo": "pro", "plan_nombre": "Pro",
       "limites": {"empresas": 50, "usuarios": 3}, "capacidades": _caps(mcp=True)}
COMPLETO = {**ESENCIAL, "plan_codigo": "completo", "plan_nombre": "Completo",
            "limites": {"empresas": 100, "usuarios": 5},
            "capacidades": _caps(mcp=True, abacus=True, api=True)}
MEDIDA = {**COMPLETO, "plan_codigo": "medida", "plan_nombre": "A la medida",
          "limites": {"empresas": 3, "usuarios": 10}}
TRIAL = {**BASE, "plan": "trial", "plan_codigo": "trial", "plan_nombre": "Prueba",
         "limites": {"empresas": 50, "usuarios": 1}, "capacidades": _caps(mcp=True),
         "legado": False, "precio_asegurado_mxn": None}
GRATIS = {**BASE, "plan": "free", "plan_codigo": "gratis", "plan_nombre": "Gratis",
          "limites": {"empresas": 5, "usuarios": 1}, "capacidades": _caps(),
          "legado": False, "precio_asegurado_mxn": None}
LEGADO_ANUAL = {**BASE, "plan_codigo": "desktop", "plan_nombre": "Anual",
                "limites": {"empresas": None, "usuarios": 1},
                "capacidades": _caps(mcp=True), "legado": True,
                "precio_asegurado_mxn": 2990}
LEGADO_IA = {**LEGADO_ANUAL, "plan_codigo": "desktop_ia", "plan_nombre": "Anual con IA",
             "capacidades": _caps(mcp=True, abacus=True, api=True),
             "precio_asegurado_mxn": 4990}
FUNDADOR = {**BASE, "plan": "founder", "is_founder": True, "plan_codigo": "fundador",
            "plan_nombre": "Fundador", "limites": {"empresas": None, "usuarios": 1},
            "capacidades": _caps(mcp=True), "legado": True, "precio_asegurado_mxn": None}
# /api/desktop/license antes de F0: sin limites ni capacidades.
VIEJO = {**BASE, "premium_features_unlocked": True, "ai_features_unlocked": False}


@pytest.fixture(autouse=True)
def aislar(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "EFIRMA_DIR", tmp_path / "efirma")
    monkeypatch.setattr(config_store, "descargas_dir_default", lambda: str(tmp_path / "TodoConta"))
    monkeypatch.setattr(empresas_router, "sincronizar_async", lambda motivo="": None)
    yield
    server._limpiar_session()


@pytest.fixture
def client():
    return TestClient(server.app)


def _licencia(payload: dict | None, *, edad_s: int = 3600) -> None:
    """Deja `payload` en el cache local con la edad indicada (default 1 h)."""
    if payload is None:
        lc.clear_license_cache()
        return
    lc._cache_write({"cached_at": int(time.time()) - edad_s, "payload": payload})


def _rfc(n: int) -> str:
    return f"EMP{n:06d}AB1"


def _empresas(n: int, *, desde: int = 0) -> list[str]:
    rfcs = [_rfc(desde + i) for i in range(n)]
    for rfc in rfcs:
        config_store.add_empresa_ciec(rfc, f"Empresa {rfc}", "ciec")
    return rfcs


def _alta_ciec(client, rfc: str):
    return client.post("/empresas/ciec", json={"rfc": rfc, "nombre": "", "ciec": "x"})


def _sin_refresco(monkeypatch):
    """El refresco de la licencia nunca debe ocurrir en este test."""
    def explota(**_):
        raise AssertionError("no debía pedir la licencia al servicio")

    monkeypatch.setattr(lc, "get_license_status", explota)


def _refresco_devuelve(monkeypatch, payload):
    llamadas = []

    def fake(force_refresh=False):
        llamadas.append(force_refresh)
        return payload

    monkeypatch.setattr(lc, "get_license_status", fake)
    return llamadas


# ---------------------------------------------------------------------------
# Por tipo de licencia
# ---------------------------------------------------------------------------


def test_esencial_bloquea_la_empresa_11_con_402(client, monkeypatch):
    _licencia(ESENCIAL)
    _refresco_devuelve(monkeypatch, ESENCIAL)
    _empresas(9)
    assert _alta_ciec(client, _rfc(100)).status_code == 200  # la 10 sí entra

    r = _alta_ciec(client, _rfc(101))
    assert r.status_code == 402
    body = r.json()
    assert body["codigo"] == "tope_empresas"
    assert body["detail"] == (
        "Tu plan Esencial incluye 10 empresas. "
        "Archiva una que ya no trabajes o cambia a Pro (50 empresas)."
    )
    assert body["tope_empresas"] == {
        "plan_codigo": "esencial",
        "plan_nombre": "Esencial",
        "tope": 10,
        "activas": 10,
        "sobran": 0,
        "siguiente_plan": {"codigo": "pro", "nombre": "Pro", "empresas": 50},
    }
    # No se registró nada.
    assert _rfc(101) not in {e["rfc"] for e in config_store.list_empresas()}


@pytest.mark.parametrize(
    "payload, tope, siguiente, salida",
    [
        (PRO, 50, {"codigo": "completo", "nombre": "Completo", "empresas": 100},
         "cambia a Completo (100 empresas)"),
        (COMPLETO, 100, {"codigo": "medida", "nombre": "A la medida", "empresas": None},
         "escríbenos para un plan a la medida"),
        (MEDIDA, 3, None, "escríbenos para ampliarlo"),
    ],
)
def test_planes_v3_aplican_su_tope_aunque_no_llegue_el_interruptor(
    client, monkeypatch, payload, tope, siguiente, salida
):
    _licencia(payload)
    _refresco_devuelve(monkeypatch, payload)
    _empresas(tope)
    r = _alta_ciec(client, _rfc(900))
    assert r.status_code == 402
    datos = r.json()["tope_empresas"]
    assert datos["tope"] == tope and datos["activas"] == tope
    assert datos["siguiente_plan"] == siguiente
    assert r.json()["detail"].endswith(f"Archiva una que ya no trabajes o {salida}.")


@pytest.mark.parametrize("payload", [TRIAL, GRATIS])
def test_prueba_y_gratis_no_se_aplican_antes_del_dia_c(client, monkeypatch, payload):
    _licencia(payload)
    _sin_refresco(monkeypatch)
    _empresas(payload["limites"]["empresas"])
    assert _alta_ciec(client, _rfc(900)).status_code == 200


def test_prueba_con_planes_v3_activos_tope_50(client, monkeypatch):
    lic = {**TRIAL, "planes_v3_activo": True}
    _licencia(lic)
    _refresco_devuelve(monkeypatch, lic)
    _empresas(50)
    r = _alta_ciec(client, _rfc(900))
    assert r.status_code == 402
    assert r.json()["detail"] == (
        "Tu prueba incluye 50 empresas. "
        "Archiva una que ya no trabajes o cambia a Completo (100 empresas)."
    )


def test_gratis_con_planes_v3_activos_tope_5(client, monkeypatch):
    lic = {**GRATIS, "planes_v3_activo": True}
    _licencia(lic)
    _refresco_devuelve(monkeypatch, lic)
    _empresas(5)
    r = _alta_ciec(client, _rfc(900))
    assert r.status_code == 402
    assert r.json()["tope_empresas"]["siguiente_plan"]["codigo"] == "esencial"
    assert r.json()["detail"].startswith("Tu plan Gratis incluye 5 empresas.")


@pytest.mark.parametrize("payload", [LEGADO_ANUAL, LEGADO_IA, FUNDADOR, VIEJO])
def test_legado_fundador_y_payload_viejo_sin_tope(client, monkeypatch, payload):
    _licencia({**payload, "planes_v3_activo": True})
    _sin_refresco(monkeypatch)
    _empresas(12)
    assert _alta_ciec(client, _rfc(900)).status_code == 200


def test_legado_con_tope_raro_sigue_sin_tope():
    """Cinturón: aunque un error del backend le mande un número al legado, la
    regla de producto es "legado y fundadores: sin tope"."""
    lic = {**LEGADO_ANUAL, "limites": {"empresas": 1, "usuarios": 1}, "planes_v3_activo": True}
    assert te.tope_de(lic) is None


# ---------------------------------------------------------------------------
# Archivar libera cupo; desarchivar lo ocupa
# ---------------------------------------------------------------------------


def test_archivadas_no_cuentan_y_archivar_libera_lugar(client, monkeypatch):
    _licencia(ESENCIAL)
    _refresco_devuelve(monkeypatch, ESENCIAL)
    rfcs = _empresas(10)
    assert _alta_ciec(client, _rfc(900)).status_code == 402

    assert client.post(f"/empresas/{rfcs[0]}/archive").status_code == 200
    assert _alta_ciec(client, _rfc(900)).status_code == 200


def test_desarchivar_sin_lugar_402_y_con_lugar_ok(client, monkeypatch):
    _licencia(ESENCIAL)
    _refresco_devuelve(monkeypatch, ESENCIAL)
    rfcs = _empresas(10)
    client.post(f"/empresas/{rfcs[0]}/archive")
    _alta_ciec(client, _rfc(900))  # vuelve a quedar en 10

    r = client.post(f"/empresas/{rfcs[0]}/unarchive")
    assert r.status_code == 402
    assert r.json()["tope_empresas"]["activas"] == 10
    assert config_store.get_empresa(rfcs[0]).get("archived_at")  # sigue archivada

    client.post(f"/empresas/{rfcs[1]}/archive")
    assert client.post(f"/empresas/{rfcs[0]}/unarchive").status_code == 200


def test_desarchivar_una_activa_o_inexistente_no_cuenta(client, monkeypatch):
    _licencia(ESENCIAL)
    _sin_refresco(monkeypatch)
    rfcs = _empresas(10)
    assert client.post(f"/empresas/{rfcs[0]}/unarchive").status_code == 200
    assert client.post("/empresas/NOEXISTE00000/unarchive").status_code == 404


def test_credenciales_a_una_empresa_existente_no_son_alta(client, monkeypatch):
    _licencia(ESENCIAL)
    _sin_refresco(monkeypatch)
    rfcs = _empresas(10)
    # Cambiar la Contraseña de una activa con el plan lleno.
    assert _alta_ciec(client, rfcs[3]).status_code == 200
    # Agregar Contraseña a una archivada: sigue archivada y no ocupa lugar.
    client.post(f"/empresas/{rfcs[4]}/archive")
    _alta_ciec(client, _rfc(900))
    assert _alta_ciec(client, rfcs[4]).status_code == 200
    assert config_store.get_empresa(rfcs[4]).get("archived_at")


def test_excedido_por_sincronizacion_dice_cuantas_sobran(client, monkeypatch):
    _licencia(ESENCIAL)
    _refresco_devuelve(monkeypatch, ESENCIAL)
    _empresas(12)  # p. ej. altas en dos equipos sin internet
    r = _alta_ciec(client, _rfc(900))
    assert r.status_code == 402
    assert r.json()["tope_empresas"]["sobran"] == 2
    assert r.json()["detail"] == (
        "Tienes 12 empresas activas y tu plan Esencial incluye 10: te sobran 2. "
        "Archiva las que ya no trabajes o cambia a Pro (50 empresas)."
    )


# ---------------------------------------------------------------------------
# e.firma
# ---------------------------------------------------------------------------


def _alta_fiel(client, test_cer, test_key, password, **extra):
    with open(test_cer, "rb") as c, open(test_key, "rb") as k:
        return client.post(
            "/empresas/fiel",
            files={"cer_file": ("f.cer", c), "key_file": ("f.key", k)},
            data={"password": password, **extra},
        )


def test_efirma_nueva_con_plan_lleno_402_sin_rastro(
    client, monkeypatch, test_cer, test_key, test_password, test_rfc
):
    from sat_descarga.core import secretos

    _licencia(ESENCIAL)
    _refresco_devuelve(monkeypatch, ESENCIAL)
    _empresas(10)
    r = _alta_fiel(client, test_cer, test_key, test_password)
    assert r.status_code == 402
    assert r.json()["tope_empresas"]["tope"] == 10
    assert test_rfc not in {e["rfc"] for e in config_store.list_empresas()}
    assert not (config_store.EFIRMA_DIR / test_rfc / "fiel.cer").exists()
    assert secretos.obtener(test_rfc, secretos.FIEL) is None


def test_efirma_de_una_empresa_existente_entra_con_plan_lleno(
    client, monkeypatch, test_cer, test_key, test_password, test_rfc
):
    _licencia(ESENCIAL)
    _sin_refresco(monkeypatch)
    config_store.add_empresa_ciec(test_rfc, "Con Contraseña", "ciec")
    _empresas(9)
    r = _alta_fiel(client, test_cer, test_key, test_password, rfc_esperado=test_rfc)
    assert r.status_code == 200
    assert config_store.get_empresa(test_rfc)["metodos"] == ["ciec", "fiel"]


def test_efirma_contrasena_mala_sigue_siendo_400(client, test_cer, test_key):
    _licencia(ESENCIAL)
    assert _alta_fiel(client, test_cer, test_key, "mala").status_code == 400


# ---------------------------------------------------------------------------
# Licencia: cache, refresco y fallback offline
# ---------------------------------------------------------------------------


def test_sin_cache_no_hay_tope(client, monkeypatch):
    _licencia(None)
    _sin_refresco(monkeypatch)
    _empresas(120)
    assert _alta_ciec(client, _rfc(900)).status_code == 200


def test_cache_fuera_de_gracia_no_bloquea(client, monkeypatch):
    _licencia(ESENCIAL, edad_s=lc.CACHE_GRACE_SECONDS + 60)
    _sin_refresco(monkeypatch)
    _empresas(10)
    assert _alta_ciec(client, _rfc(900)).status_code == 200


def test_si_ya_cambio_de_plan_el_refresco_lo_deja_pasar(client, monkeypatch):
    _licencia(ESENCIAL)
    llamadas = _refresco_devuelve(monkeypatch, PRO)
    _empresas(10)
    assert _alta_ciec(client, _rfc(900)).status_code == 200
    assert llamadas == [True]


def test_cache_reciente_no_vuelve_a_preguntar(client, monkeypatch):
    _licencia(ESENCIAL, edad_s=5)
    _sin_refresco(monkeypatch)
    _empresas(10)
    assert _alta_ciec(client, _rfc(900)).status_code == 402


def test_refresco_que_falla_no_da_500(client, monkeypatch):
    _licencia(ESENCIAL)

    def explota(**_):
        raise RuntimeError("se cayó algo")

    monkeypatch.setattr(lc, "get_license_status", explota)
    _empresas(10)
    assert _alta_ciec(client, _rfc(900)).status_code == 402  # decide con el cache


def _sesion():
    lc.save_session(lc.Session(access_token="fake", refresh_token=None,
                               user_id="user-1", email=None))


def test_offline_con_cache_en_gracia_respeta_el_tope(client, monkeypatch):
    """Extremo a extremo con get_license_status real: sin red, la licencia del
    cache (dentro de los 30 días) sigue mandando."""
    _sesion()
    _licencia(ESENCIAL, edad_s=2 * 24 * 3600)

    def sin_red(url, **kwargs):
        raise requests.ConnectionError("sin internet")

    monkeypatch.setattr(lc.requests, "get", sin_red)
    _empresas(10)
    assert _alta_ciec(client, _rfc(900)).status_code == 402
    lc.clear_session()


def test_offline_sin_cache_nunca_bloquea(client, monkeypatch):
    """Fallback offline sin cache: `get_license_status` no trae `limites`."""
    _sesion()
    _licencia(None)

    def sin_red(url, **kwargs):
        raise requests.ConnectionError("sin internet")

    monkeypatch.setattr(lc.requests, "get", sin_red)
    _empresas(60)
    assert _alta_ciec(client, _rfc(900)).status_code == 200
    lc.clear_session()


def test_licencia_fresca_del_servicio_extremo_a_extremo(client, monkeypatch):
    """Cache viejo de Esencial lleno; el servicio ya dice Pro → entra."""
    _sesion()
    _licencia(ESENCIAL)

    class _Resp:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return PRO

    monkeypatch.setattr(lc.requests, "get", lambda url, **kw: _Resp())
    _empresas(10)
    assert _alta_ciec(client, _rfc(900)).status_code == 200
    assert lc._cache_read()["payload"]["plan_codigo"] == "pro"
    lc.clear_session()
