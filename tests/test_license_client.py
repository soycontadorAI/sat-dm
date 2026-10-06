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

# Mismo usuario con los campos aditivos de F0 (legado anual 'desktop').
PAYLOAD_NUEVO = {
    **PAYLOAD_VIEJO,
    "plan_codigo": "desktop",
    "plan_nombre": "Anual",
    "limites": {"empresas": None, "usuarios": 1},
    "capacidades": {
        "web": True,
        "exportar": True,
        "mcp": False,
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
    assert lc.capacidad(lic, "mcp") is False


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
    assert lc.capacidad(PAYLOAD_NUEVO, "mcp") is False
    assert lc.capacidad(PAYLOAD_ESENCIAL, "piloto") is False


def test_capacidades_mandan_sobre_los_campos_de_antes():
    """Con `capacidades` presentes no se mira premium/ai_features_unlocked."""
    lic = {**PAYLOAD_ESENCIAL, "ai_features_unlocked": True}
    assert lc.capacidad(lic, "mcp") is False


@pytest.mark.parametrize(
    "plan, premium, ia, esperado",
    [
        # (plan, premium_features_unlocked, ai_features_unlocked) → exportar, mcp, web
        ("trial", False, False, (False, False, True)),
        ("free", False, False, (False, False, False)),
        ("premium", True, False, (True, False, True)),
        ("premium", True, True, (True, True, True)),
        ("founder", True, False, (True, False, True)),
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
