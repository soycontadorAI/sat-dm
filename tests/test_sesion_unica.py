"""Tests de la sesión única (F1.1): `api/sesion_unica.py`, su router y su efecto
en el poller y la licencia.

Regla: gana la sesión más reciente; sin vencimiento. El servicio
(`/api/desktop/sesion/*`) se mockea siempre vía `license_client.proxy_desktop`.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from sat_descarga.api import license_client as lc  # noqa: E402
from sat_descarga.api import poller  # noqa: E402
from sat_descarga.api import sesion_unica as su  # noqa: E402
from sat_descarga.api.license_client import Session  # noqa: E402

OTRA = {"etiqueta": "Windows · OFICINA-2", "tipo": "desktop", "desde": "2026-10-06T17:53:00.000Z"}


def _resp(activa: bool, modo: str = "exigir", otra: dict | None = None, hb: int = 60) -> dict:
    return {
        "activa": activa,
        "modo": modo,
        "instalacion_id": "x",
        "heartbeat_segundos": hb,
        "otra": otra,
    }


@pytest.fixture
def servicio(monkeypatch):
    """Mock de proxy_desktop: guarda las llamadas y responde lo programado."""
    estado = {"respuesta": (200, _resp(True)), "llamadas": []}

    def fake(method, path, *, json_body=None, params=None):
        estado["llamadas"].append((method, path, json_body))
        r = estado["respuesta"]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(lc, "proxy_desktop", fake)
    return estado


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("SAT_DM_MODO", "hosted")


# ---------------------------------------------------------------------------
# Identidad de la instalación
# ---------------------------------------------------------------------------


def test_instalacion_id_estable_y_guardada(tmp_path, monkeypatch):
    primero = su.instalacion_id()
    assert su.es_valida(primero)
    assert su.instalacion_id() == primero
    # Se relee del archivo aunque se pierda el cache en memoria (reinicio).
    monkeypatch.setattr(su, "_instalacion_cache", None)
    assert su.instalacion_id() == primero
    data = json.loads((tmp_path / "instalacion-aislada.json").read_text())
    assert data["id"] == primero and "creada_en" in data


def test_instalacion_id_se_regenera_si_el_archivo_esta_danado(tmp_path, monkeypatch):
    (tmp_path / "instalacion-aislada.json").write_text("{no es json")
    nuevo = su.instalacion_id()
    assert su.es_valida(nuevo)
    assert json.loads((tmp_path / "instalacion-aislada.json").read_text())["id"] == nuevo


def test_etiqueta_local(monkeypatch):
    monkeypatch.setattr(su.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(su.socket, "gethostname", lambda: "MacBook-de-Ana.local")
    assert su.etiqueta_local() == "macOS · MacBook-de-Ana"
    monkeypatch.setattr(su.platform, "system", lambda: "Windows")
    monkeypatch.setattr(su.socket, "gethostname", lambda: "")
    assert su.etiqueta_local() == "Windows"


# ---------------------------------------------------------------------------
# Escritorio: reclamar, latir, cerrarse
# ---------------------------------------------------------------------------


def test_reclamar_manda_la_instalacion_propia(servicio):
    r = su.reclamar("id-que-manda-la-ui", "lo que sea", interaccion_hace_s=0)
    metodo, ruta, body = servicio["llamadas"][0]
    assert (metodo, ruta) == ("POST", su.RUTA_RECLAMAR)
    assert body["instalacion_id"] == su.instalacion_id()  # ignora lo de la UI
    assert body["tipo"] == "desktop"
    assert body["etiqueta"] == su.etiqueta_local()
    assert body["interaccion_hace_s"] == 0
    assert r["cerrada"] is False and r["instalacion_id"] == su.instalacion_id()


def test_latido_de_instalacion_desplazada_la_cierra_y_dice_cual(servicio):
    servicio["respuesta"] = (200, _resp(False, otra=OTRA))
    r = su.latido()
    assert r["cerrada"] is True
    assert r["otra"] == OTRA
    assert r["modo"] == "exigir"
    assert su.cerrada() is True
    assert su.estado()["cerrada"] is True


def test_continuar_aqui_reclama_y_abre(servicio):
    servicio["respuesta"] = (200, _resp(False, otra=OTRA))
    su.latido()
    assert su.cerrada()
    servicio["respuesta"] = (200, _resp(True))
    r = su.reclamar()
    assert r["cerrada"] is False and r["otra"] is None
    assert su.cerrada() is False


def test_modo_observar_nunca_cierra(servicio):
    servicio["respuesta"] = (200, _resp(True, modo="observar", otra=OTRA))
    r = su.latido()
    assert r["cerrada"] is False
    assert r["otra"] == OTRA  # informativo
    assert su.cerrada() is False


@pytest.mark.parametrize(
    "respuesta",
    [
        lc.ServicioNoDisponible("sin internet"),
        (404, None),  # servicio viejo sin el endpoint
        (500, {"error": "x"}),
        (503, {"error": "base", **_resp(True)}),
        (200, {"raro": True}),
    ],
)
def test_sin_respuesta_valida_nunca_cierra(servicio, respuesta):
    servicio["respuesta"] = respuesta
    r = su.latido()
    assert r["cerrada"] is False
    assert su.cerrada() is False
    assert r["sin_conexion"] is isinstance(respuesta, lc.ServicioNoDisponible)


def test_offline_no_abre_un_cierre_confirmado_pero_continuar_aqui_si(servicio):
    servicio["respuesta"] = (200, _resp(False, otra=OTRA))
    su.latido()
    servicio["respuesta"] = lc.ServicioNoDisponible("sin internet")
    assert su.latido()["cerrada"] is True  # el latido sin red no cambia nada
    r = su.reclamar()  # "Continuar aquí" sin internet: nunca se queda cerrada
    assert r["cerrada"] is False and r["sin_conexion"] is True


def test_401_sin_sesion_no_cierra(servicio):
    servicio["respuesta"] = (200, _resp(False, otra=OTRA))
    su.latido()
    servicio["respuesta"] = (401, {"error": "No autenticado"})
    assert su.latido()["cerrada"] is False


def test_intervalo_del_servidor_con_topes(servicio):
    servicio["respuesta"] = (200, _resp(True, hb=5))
    assert su.latido()["heartbeat_segundos"] == su.LATIDO_MIN_S
    servicio["respuesta"] = (200, _resp(True, hb=99999))
    assert su.latido()["heartbeat_segundos"] == su.LATIDO_MAX_S
    servicio["respuesta"] = (200, _resp(True, hb=90))
    assert su.latido()["heartbeat_segundos"] == 90


def test_interaccion_reportada_por_la_ui_viaja_en_el_latido(servicio):
    su.estado(interaccion_hace_s=12)
    su.latido()
    body = servicio["llamadas"][-1][2]
    assert 12 <= body["interaccion_hace_s"] <= 14


def test_hilo_no_late_si_esta_cerrada(servicio):
    servicio["respuesta"] = (200, _resp(False, otra=OTRA))
    su.latido()
    n = len(servicio["llamadas"])
    su._un_latido()
    assert len(servicio["llamadas"]) == n  # cerrada: espera a "Continuar aquí"


def test_hilo_late_si_esta_abierta(servicio):
    su._un_latido()
    assert servicio["llamadas"][-1][1] == su.RUTA_LATIDO


def test_reiniciar_olvida_el_cierre(servicio):
    servicio["respuesta"] = (200, _resp(False, otra=OTRA))
    su.latido()
    su.reiniciar()
    assert su.cerrada() is False


def test_iniciar_latidos_respeta_kill_switch_y_web(monkeypatch):
    arrancados = []
    monkeypatch.setattr(su.threading, "Thread", lambda **kw: arrancados.append(kw) or MagicMock())
    monkeypatch.setattr(su, "_thread", None)
    su.iniciar_latidos()  # SAT_DM_SIN_SESION_UNICA=1 (conftest)
    monkeypatch.delenv("SAT_DM_SIN_SESION_UNICA")
    monkeypatch.setenv("SAT_DM_MODO", "hosted")
    su.iniciar_latidos()
    assert arrancados == []
    monkeypatch.delenv("SAT_DM_MODO")
    su.iniciar_latidos()
    assert len(arrancados) == 1 and arrancados[0]["name"] == "sesion-latidos"


# ---------------------------------------------------------------------------
# Licencia: header de instalación y campo `sesion`
# ---------------------------------------------------------------------------


@pytest.fixture
def con_sesion(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "LICENSE_CACHE_PATH", tmp_path / "license-cache.json")
    lc.save_session(Session(access_token="fake", refresh_token=None, user_id="u", email=None))
    yield
    lc.clear_session()


def _licencia(monkeypatch, payload: dict, vistos: list):
    def fake_get(url, **kwargs):
        vistos.append(kwargs.get("headers", {}))
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        return resp

    monkeypatch.setattr(lc.requests, "get", fake_get)


def test_licencia_manda_la_instalacion_y_aplica_el_cierre(con_sesion, monkeypatch):
    vistos: list = []
    payload = {"authenticated": True, "plan": "premium", "sesion": {**_resp(False, otra=OTRA), "instalacion_id": su.instalacion_id()}}
    _licencia(monkeypatch, payload, vistos)
    lic = lc.get_license_status(force_refresh=True)
    assert vistos[0][su.HEADER_INSTALACION] == su.instalacion_id()
    assert su.cerrada() is True
    # El estado de la sesión no se cachea ni viaja a la UI con la licencia.
    assert "sesion" not in lic
    assert "sesion" not in json.loads(lc.LICENSE_CACHE_PATH.read_text())["payload"]
    assert "sesion" in payload  # no muta la respuesta original


def test_licencia_sin_campo_sesion_no_cambia_nada(con_sesion, monkeypatch):
    _licencia(monkeypatch, {"authenticated": True, "plan": "premium"}, [])
    lc.get_license_status(force_refresh=True)
    assert su.cerrada() is False


def test_licencia_de_otra_instalacion_se_ignora():
    su.desde_licencia({"sesion": {**_resp(False, otra=OTRA), "instalacion_id": "otra-instalacion-xyz"}})
    assert su.cerrada() is False


# ---------------------------------------------------------------------------
# Web (modo hosted): la instalación es el navegador
# ---------------------------------------------------------------------------


def test_web_usa_la_instalacion_del_navegador_y_no_guarda_estado(hosted, servicio):
    servicio["respuesta"] = (200, _resp(False, otra=OTRA))
    r = su.latido("navegador-abc12345", "Chrome en Windows", interaccion_hace_s=3)
    body = servicio["llamadas"][0][2]
    assert body == {
        "instalacion_id": "navegador-abc12345",
        "tipo": "web",
        "etiqueta": "Chrome en Windows",
        "interaccion_hace_s": 3,
    }
    assert r["cerrada"] is True  # la respuesta es para ESE navegador
    # El contenedor es de todos los navegadores de la cuenta: nada se pausa.
    assert su.cerrada() is False
    assert su.header_instalacion() == {}


def test_web_sin_instalacion_valida_es_error(hosted, servicio):
    with pytest.raises(ValueError):
        su.reclamar(None)
    with pytest.raises(ValueError):
        su.latido("x y")
    assert servicio["llamadas"] == []


# ---------------------------------------------------------------------------
# Poller: pausa lo nuevo, termina lo ya solicitado al Web Service
# ---------------------------------------------------------------------------


def test_poller_pausa_reenvios_pero_termina_solicitudes_ws(servicio, monkeypatch):
    from sat_descarga.cli import config_store

    monkeypatch.setattr(config_store, "list_empresas", lambda: [{"rfc": "AAA010101AAA"}])
    hechos = []
    monkeypatch.setattr(poller, "_procesar_empresa", lambda rfc, emp: hechos.append(("ws", rfc)))
    monkeypatch.setattr(poller, "_reanudar_envios_ce", lambda rfc, emp: hechos.append(("ce", rfc)))

    poller._una_pasada()
    assert hechos == [("ws", "AAA010101AAA"), ("ce", "AAA010101AAA")]

    servicio["respuesta"] = (200, _resp(False, otra=OTRA))
    su.latido()
    hechos.clear()
    poller._una_pasada()
    assert hechos == [("ws", "AAA010101AAA")]  # CE pausado; WS sigue

    servicio["respuesta"] = (200, _resp(True))
    su.reclamar()  # "Continuar aquí"
    hechos.clear()
    poller._una_pasada()
    assert ("ce", "AAA010101AAA") in hechos


def test_poller_tolera_falla_de_la_sesion_unica(monkeypatch):
    def explota():
        raise RuntimeError("x")

    monkeypatch.setattr(su, "cerrada", explota)
    assert poller._sesion_cerrada() is False


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from sat_descarga.api.server import app

    with TestClient(app) as c:
        yield c


def test_router_estado_reclamar_y_latido(client, servicio):
    r = client.get("/auth/sesion", params={"interaccion_hace_s": 4})
    assert r.status_code == 200
    assert r.json()["cerrada"] is False
    assert r.json()["instalacion_id"] == su.instalacion_id()

    servicio["respuesta"] = (200, _resp(False, otra=OTRA))
    r = client.post("/auth/sesion/latido", json={})
    assert r.status_code == 200 and r.json()["cerrada"] is True
    assert client.get("/auth/sesion").json()["cerrada"] is True

    servicio["respuesta"] = (200, _resp(True))
    r = client.post("/auth/sesion/reclamar")  # sin body también vale
    assert r.status_code == 200 and r.json()["cerrada"] is False


def test_router_web_sin_instalacion_400(hosted, client, servicio):
    r = client.post("/auth/sesion/reclamar", json={})
    assert r.status_code == 400
    r = client.post(
        "/auth/sesion/reclamar",
        json={"instalacion_id": "navegador-abc12345", "etiqueta": "Safari en macOS"},
    )
    assert r.status_code == 200
    assert servicio["llamadas"][-1][2]["interaccion_hace_s"] == 0  # reclamar = acción del usuario


def test_logout_olvida_el_cierre(client, servicio):
    servicio["respuesta"] = (200, _resp(False, otra=OTRA))
    client.post("/auth/sesion/latido", json={})
    assert su.cerrada() is True
    assert client.post("/auth/logout").status_code == 200
    assert su.cerrada() is False
