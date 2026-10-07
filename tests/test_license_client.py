"""Tests de `sat_descarga/api/license_client.py`: licencia con payloads viejos
(antes de F0) y nuevos (planes v3: limites, capacidades, uso...).

El backend se mockea siempre (requests.get); el cache vive en tmp_path.
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest
import requests

from sat_descarga.api import license_client as lc
from sat_descarga.api.license_client import Session


# Payload tal como lo devolvía /api/desktop/license antes de F0.
PAYLOAD_VIEJO = {
    "authenticated": True,
    "user_id": "user-1",
    "email": "cuenta@ejemplo.test",
    "plan": "premium",
    "days_remaining": 200,
    "expires_at": "2027-04-23T00:00:00.000Z",
    "subscription_cancel_at_period_end": False,
    "promo_active": False,
    "promo_ends_at": None,
    "promo_price_mxn": 1495,
    "regular_price_mxn": 2990,
    "promo_days": 7,
    "is_founder": False,
    "founder_acquired_at": None,
    "founder_window_open": False,
    "founder_window_closes_at": "2026-06-18T05:59:59.000Z",
    "founder_price_mxn": 1499,
    "premium_features_unlocked": True,
    "ai_credits_balance": 0,
    "ai_features_unlocked": False,
    "ia_price_mxn": 4990,
    "ia_founder_price_mxn": 2490,
}

# Mismo usuario con los campos aditivos de F0 (legado anual 'desktop', que
# conserva la MCP: decidido por Israel 2026-10-05).
PAYLOAD_NUEVO = {
    **PAYLOAD_VIEJO,
    "plan_codigo": "desktop",
    "plan_nombre": "Anual",
    "limites": {"empresas": None, "usuarios": 1},
    "capacidades": {
        "web": True,
        "exportar": True,
        "mcp": True,
        "abacus": False,
        "api": False,
        "piloto": True,
        "vigilancia": {"app_correo": True, "whatsapp": False},
        "reporte_cliente": False,
    },
    "uso": {"empresas_activas": 56},
    "legado": True,
    "precio_asegurado_mxn": 2990,
}

PAYLOAD_ESENCIAL = {
    **PAYLOAD_VIEJO,
    "plan_codigo": "esencial",
    "plan_nombre": "Esencial",
    "limites": {"empresas": 10, "usuarios": 1},
    "capacidades": {
        "web": True,
        "exportar": True,
        "mcp": False,
        "abacus": False,
        "api": False,
        "piloto": False,
        "vigilancia": {"app_correo": False, "whatsapp": False},
        "reporte_cliente": False,
    },
    "uso": {"empresas_activas": 8},
    "legado": False,
    "precio_asegurado_mxn": None,
}


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Sesión guardada + cache de licencia en tmp_path."""
    monkeypatch.setattr(lc, "LICENSE_CACHE_PATH", tmp_path / "license-cache.json")
    lc.save_session(
        Session(
            access_token="fake-bearer",
            refresh_token=None,
            user_id="user-1",
            email="cuenta@ejemplo.test",
        )
    )
    yield tmp_path
    lc.clear_session()


def _respuesta(payload: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.text = json.dumps(payload)
    return resp


def _backend(monkeypatch, payload: dict | None = None, *, sin_red: bool = False):
    def fake_get(url, **kwargs):
        assert url.endswith("/api/desktop/license")
        if sin_red:
            raise requests.ConnectionError("sin internet")
        return _respuesta(payload or {})

    monkeypatch.setattr(lc.requests, "get", fake_get)


# ---------------------------------------------------------------------------
# get_license_status: guarda y expone los campos nuevos
# ---------------------------------------------------------------------------


def test_payload_nuevo_se_guarda_en_cache_y_se_expone(entorno, monkeypatch):
    _backend(monkeypatch, PAYLOAD_NUEVO)
    lic = lc.get_license_status(force_refresh=True)
    assert lic == PAYLOAD_NUEVO

    guardado = json.loads(lc.LICENSE_CACHE_PATH.read_text())
    assert guardado["payload"]["limites"] == {"empresas": None, "usuarios": 1}
    assert guardado["payload"]["capacidades"]["vigilancia"]["app_correo"] is True
    assert guardado["payload"]["uso"] == {"empresas_activas": 56}

    # Lectura siguiente sin red: sale del cache fresco con los campos nuevos.
    _backend(monkeypatch, sin_red=True)
    desde_cache = lc.get_license_status()
    assert desde_cache["from_cache"] is True
    assert desde_cache["plan_codigo"] == "desktop"
    assert desde_cache["precio_asegurado_mxn"] == 2990
    assert desde_cache["legado"] is True


def test_payload_viejo_sigue_funcionando(entorno, monkeypatch):
    _backend(monkeypatch, PAYLOAD_VIEJO)
    lic = lc.get_license_status(force_refresh=True)
    assert lic == PAYLOAD_VIEJO
    assert "limites" not in lic and "capacidades" not in lic
    # Helpers con licencia vieja: sin tope y capacidades derivadas de lo de antes.
    assert lc.limites_de(lic) == {"empresas": None, "usuarios": None}
    assert lc.capacidad(lic, "exportar") is True
    assert lc.capacidad(lic, "web") is True
    assert lc.capacidad(lic, "mcp") is True  # premium de antes: el gateway ya le da MCP
    assert lc.capacidad(lic, "abacus") is False


def test_cache_viejo_en_gracia_offline_se_respeta(entorno, monkeypatch):
    """Cache de antes de F0, vencido (>24h) pero dentro de los 30 días, sin red."""
    hace_2_dias = int(time.time()) - 2 * 24 * 60 * 60
    lc.LICENSE_CACHE_PATH.write_text(
        json.dumps({"cached_at": hace_2_dias, "payload": PAYLOAD_VIEJO})
    )
    _backend(monkeypatch, sin_red=True)
    lic = lc.get_license_status()
    assert lic["stale"] is True and lic["offline"] is True
    assert lic["premium_features_unlocked"] is True
    assert lc.limites_de(lic) == {"empresas": None, "usuarios": None}


def test_cache_nuevo_en_gracia_offline_conserva_limites(entorno, monkeypatch):
    hace_2_dias = int(time.time()) - 2 * 24 * 60 * 60
    lc.LICENSE_CACHE_PATH.write_text(
        json.dumps({"cached_at": hace_2_dias, "payload": PAYLOAD_ESENCIAL})
    )
    _backend(monkeypatch, sin_red=True)
    lic = lc.get_license_status()
    assert lic["offline"] is True
    assert lc.limites_de(lic) == {"empresas": 10, "usuarios": 1}
    assert lc.capacidad(lic, "piloto") is False


def test_fallback_sin_cache_no_bloquea(entorno, monkeypatch):
    """Sin red y sin cache: mismo mínimo de hoy y NINGÚN tope."""
    _backend(monkeypatch, sin_red=True)
    lic = lc.get_license_status()
    assert lic == {
        "authenticated": True,
        "is_founder": False,
        "premium_features_unlocked": False,
        "stale": True,
        "offline": True,
    }
    assert lc.limites_de(lic) == {"empresas": None, "usuarios": None}


def test_cache_fuera_de_gracia_cae_al_fallback_sin_tope(entorno, monkeypatch):
    hace_40_dias = int(time.time()) - 40 * 24 * 60 * 60
    lc.LICENSE_CACHE_PATH.write_text(
        json.dumps({"cached_at": hace_40_dias, "payload": PAYLOAD_ESENCIAL})
    )
    _backend(monkeypatch, sin_red=True)
    lic = lc.get_license_status()
    assert "limites" not in lic
    assert lc.limites_de(lic) == {"empresas": None, "usuarios": None}


def test_sin_sesion_no_autenticado(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "LICENSE_CACHE_PATH", tmp_path / "license-cache.json")
    assert lc.get_license_status() == {"authenticated": False}
    assert lc.limites_de({"authenticated": False}) == {"empresas": None, "usuarios": None}


# ---------------------------------------------------------------------------
# Helpers: limites_de / capacidad
# ---------------------------------------------------------------------------


def test_limites_de_payload_nuevo():
    assert lc.limites_de(PAYLOAD_ESENCIAL) == {"empresas": 10, "usuarios": 1}
    assert lc.limites_de(PAYLOAD_NUEVO) == {"empresas": None, "usuarios": 1}


@pytest.mark.parametrize(
    "limites",
    [None, "10", [], {"empresas": "10"}, {"empresas": 0}, {"empresas": -5}, {"empresas": True}],
)
def test_limites_raros_no_bloquean(limites):
    lic = {**PAYLOAD_VIEJO, "limites": limites}
    assert lc.limites_de(lic)["empresas"] is None


def test_capacidad_payload_nuevo():
    assert lc.capacidad(PAYLOAD_NUEVO, "exportar") is True
    assert lc.capacidad(PAYLOAD_NUEVO, "piloto") is True
    assert lc.capacidad(PAYLOAD_NUEVO, "vigilancia.app_correo") is True
    assert lc.capacidad(PAYLOAD_NUEVO, "vigilancia.whatsapp") is False
    assert lc.capacidad(PAYLOAD_NUEVO, "mcp") is True
    assert lc.capacidad(PAYLOAD_NUEVO, "abacus") is False
    assert lc.capacidad(PAYLOAD_ESENCIAL, "piloto") is False


def test_capacidades_mandan_sobre_los_campos_de_antes():
    """Con `capacidades` presentes no se mira premium/ai_features_unlocked."""
    lic = {**PAYLOAD_ESENCIAL, "ai_features_unlocked": True}
    assert lc.capacidad(lic, "mcp") is False


@pytest.mark.parametrize(
    "plan, premium, ia, esperado",
    [
        # (plan, premium_features_unlocked, ai_features_unlocked) → exportar, mcp, web
        # MCP como el gateway de hoy: trial, premium o founder (legado con MCP).
        ("trial", False, False, (False, True, True)),
        ("free", False, False, (False, False, False)),
        ("premium", True, False, (True, True, True)),
        ("premium", True, True, (True, True, True)),
        ("founder", True, False, (True, True, True)),
    ],
)
def test_capacidad_derivada_de_payload_viejo(plan, premium, ia, esperado):
    lic = {
        **PAYLOAD_VIEJO,
        "plan": plan,
        "is_founder": plan == "founder",
        "premium_features_unlocked": premium,
        "ai_features_unlocked": ia,
    }
    assert (
        lc.capacidad(lic, "exportar"),
        lc.capacidad(lic, "mcp"),
        lc.capacidad(lic, "web"),
    ) == esperado


def test_capacidad_desconocida_es_error():
    with pytest.raises(ValueError):
        lc.capacidad(PAYLOAD_NUEVO, "exportarr")


def test_auth_license_expone_campos_nuevos(entorno, monkeypatch):
    """El router /auth/license devuelve el payload sin recortar los campos nuevos."""
    pytest.importorskip("fastapi")
    from sat_descarga.api.routers import system

    _backend(monkeypatch, {**PAYLOAD_ESENCIAL, "email": None})
    lic = system.auth_license(refresh=True)
    assert lic["limites"] == {"empresas": 10, "usuarios": 1}
    assert lic["uso"] == {"empresas_activas": 8}
    assert lic["email"] == "cuenta@ejemplo.test"  # completado desde la sesión local


# ---------------------------------------------------------------------------
# F1: interruptor del Día C y payloads de checkout de los planes v3
# ---------------------------------------------------------------------------


def test_planes_v3_activos_solo_con_true_explicito():
    assert lc.planes_v3_activos({**PAYLOAD_ESENCIAL, "planes_v3_activo": True}) is True
    assert lc.planes_v3_activos(PAYLOAD_ESENCIAL) is False
    assert lc.planes_v3_activos({"planes_v3_activo": "true"}) is False
    assert lc.planes_v3_activos(None) is False


def _captura_post(monkeypatch, respuesta: dict):
    enviados = []

    def fake_post(url, **kwargs):
        enviados.append((url, kwargs.get("json")))
        return _respuesta(respuesta)

    monkeypatch.setattr(lc.requests, "post", fake_post)
    return enviados


@pytest.mark.parametrize(
    "plan, intervalo, esperado",
    [
        ("anual", None, {"plan": "anual"}),
        ("anual_ia", None, {"plan": "anual_ia"}),
        ("cualquier-cosa", None, {"plan": "anual"}),
        ("pro", "mensual", {"plan": "pro", "intervalo": "mensual"}),
        ("esencial", None, {"plan": "esencial", "intervalo": "anual"}),
        ("completo", "semanal", {"plan": "completo", "intervalo": "anual"}),
    ],
)
def test_subscribe_payloads(monkeypatch, plan, intervalo, esperado):
    enviados = _captura_post(monkeypatch, {"url": "https://checkout"})
    sesion = Session(access_token="t", refresh_token=None, user_id="u", email=None)
    lc.init_subscribe_checkout(sesion, plan, intervalo)
    assert enviados[0][0].endswith("/api/desktop/subscribe")
    assert enviados[0][1] == esperado


@pytest.mark.parametrize(
    "plan, esperado", [(None, None), ("pro", {"plan": "pro"}), ("anual", None)]
)
def test_transfer_intent_payloads(monkeypatch, plan, esperado):
    enviados = _captura_post(monkeypatch, {"ok": True, "amount_mxn": 6990})
    sesion = Session(access_token="t", refresh_token=None, user_id="u", email=None)
    lc.create_transfer_intent(sesion, plan)
    assert enviados[0][0].endswith("/api/desktop/transfer-intent")
    assert enviados[0][1] == esperado


def test_router_subscribe_y_transfer_pasan_el_plan_v3(entorno, monkeypatch):
    pytest.importorskip("fastapi")
    from sat_descarga.api.routers import system

    enviados = _captura_post(monkeypatch, {"url": "https://checkout", "ok": True})
    system.auth_subscribe({"plan": "pro", "intervalo": "mensual"})
    system.auth_subscribe({"plan": "anual_ia"})
    system.auth_subscribe(None)
    system.auth_transfer_intent({"plan": "completo"})
    system.auth_transfer_intent(None)
    assert [b for _, b in enviados] == [
        {"plan": "pro", "intervalo": "mensual"},
        {"plan": "anual_ia"},
        {"plan": "anual"},
        {"plan": "completo"},
        None,
    ]


# ---------------------------------------------------------------------------
# Usuarios adicionales (2026-10-06): Pro y Completo, $990 al año o $129 al mes
# ---------------------------------------------------------------------------


def test_subscribe_con_usuarios_adicionales(monkeypatch):
    enviados = _captura_post(monkeypatch, {"url": "https://checkout"})
    sesion = Session(access_token="t", refresh_token=None, user_id="u", email=None)
    lc.init_subscribe_checkout(sesion, "pro", "mensual", 2)
    lc.init_subscribe_checkout(sesion, "completo", None, 0, previsualizar=True)
    lc.init_subscribe_checkout(sesion, "anual", None, 3)  # oferta de antes: no viaja
    lc.init_subscribe_checkout(sesion, "pro", "anual", True)  # un bool no es cantidad
    assert [b for _, b in enviados] == [
        {"plan": "pro", "intervalo": "mensual", "usuarios_adicionales": 2},
        {"plan": "completo", "intervalo": "anual", "usuarios_adicionales": 0, "previsualizar": True},
        {"plan": "anual"},
        {"plan": "pro", "intervalo": "anual"},
    ]


def test_transfer_intent_con_usuarios_adicionales(monkeypatch):
    enviados = _captura_post(monkeypatch, {"ok": True, "amount_mxn": 8970})
    sesion = Session(access_token="t", refresh_token=None, user_id="u", email=None)
    lc.create_transfer_intent(sesion, "pro", 2)
    lc.create_transfer_intent(sesion, "pro", 0)
    lc.create_transfer_intent(sesion, None, 2)  # plan de antes: cuerpo vacío
    assert [b for _, b in enviados] == [
        {"plan": "pro", "usuarios_adicionales": 2},
        {"plan": "pro"},
        None,
    ]


def test_router_pasa_usuarios_adicionales_y_rechaza_los_invalidos(entorno, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import HTTPException

    from sat_descarga.api.routers import system

    enviados = _captura_post(monkeypatch, {"url": "https://checkout", "ok": True})
    system.auth_subscribe({"plan": "pro", "intervalo": "anual", "usuarios_adicionales": 2})
    system.auth_subscribe({"plan": "pro", "usuarios_adicionales": 1, "previsualizar": True})
    system.auth_transfer_intent({"plan": "completo", "usuarios_adicionales": 3})
    assert [b for _, b in enviados] == [
        {"plan": "pro", "intervalo": "anual", "usuarios_adicionales": 2},
        {"plan": "pro", "intervalo": "anual", "usuarios_adicionales": 1, "previsualizar": True},
        {"plan": "completo", "usuarios_adicionales": 3},
    ]
    for malo in ("2", -1, 1.5):
        with pytest.raises(HTTPException) as e:
            system.auth_subscribe({"plan": "pro", "usuarios_adicionales": malo})
        assert e.value.status_code == 400
    assert len(enviados) == 3


def test_cuenta_usuarios_adicionales_proxya_y_espeja_el_status(entorno, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import HTTPException

    from sat_descarga.api.routers import system

    llamadas = []
    respuesta = {"valor": (200, {"ok": True, "usuarios_adicionales": 3, "max_usuarios": 6})}

    def fake_proxy(method, path, *, json_body=None, params=None):
        llamadas.append((method, path, json_body))
        return respuesta["valor"]

    monkeypatch.setattr(lc, "proxy_desktop", fake_proxy)
    r = system.cuenta_usuarios_adicionales(system.UsuariosAdicionalesRequest(usuarios_adicionales=3))
    assert r == {"ok": True, "usuarios_adicionales": 3, "max_usuarios": 6}
    assert llamadas == [
        ("POST", "/api/desktop/usuarios-adicionales", {"usuarios_adicionales": 3, "previsualizar": False})
    ]

    # Un 409 del servicio (el equipo no cabe) sigue siendo 409, con su mensaje.
    respuesta["valor"] = (409, {"codigo": "excede_usuarios", "error": "Tu equipo tiene 5 usuarios..."})
    with pytest.raises(HTTPException) as e:
        system.cuenta_usuarios_adicionales(
            system.UsuariosAdicionalesRequest(usuarios_adicionales=1, previsualizar=True)
        )
    assert e.value.status_code == 409
    assert e.value.detail == "Tu equipo tiene 5 usuarios..."
