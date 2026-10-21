"""
Contexto del cliente para la API de conversiones de Meta (api/contexto_cliente.py):
qué recuerda el agente del renderer y qué reenvía a api.todoconta.com.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sat_descarga.api import contexto_cliente as cc
from sat_descarga.api import license_client as lc
from sat_descarga.api.license_client import Session

UA_CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36"
UA_ELECTRON = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 TodoConta/2.5.0 Electron/33.0"


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.delenv("SAT_DM_MODO", raising=False)
    cc._reiniciar_para_pruebas()
    yield
    cc._reiniciar_para_pruebas()


def test_desktop_reenvia_el_ua_de_electron_y_nunca_la_ip(monkeypatch):
    cc.registrar(UA_ELECTRON, "201.141.10.20", None)
    assert cc.headers() == {cc.HEADER_MODO: "desktop", cc.HEADER_UA: UA_ELECTRON}


def test_web_reenvia_ua_e_ip_del_primer_salto(monkeypatch):
    monkeypatch.setenv("SAT_DM_MODO", "hosted")
    cc.registrar(UA_CHROME, "201.141.10.20, 172.18.0.2", None)
    assert cc.headers() == {
        cc.HEADER_MODO: "web",
        cc.HEADER_UA: UA_CHROME,
        cc.HEADER_IP: "201.141.10.20",
    }


def test_web_sin_confiar_en_x_forwarded_for_no_manda_ip(monkeypatch):
    monkeypatch.setenv("SAT_DM_MODO", "hosted")
    monkeypatch.setattr(cc, "CONFIAR_X_FORWARDED_FOR", False)
    cc.registrar(UA_CHROME, "201.141.10.20", None)
    assert cc.HEADER_IP not in cc.headers()


def test_el_gateway_y_los_clientes_que_no_son_navegador_no_cuentan(monkeypatch):
    monkeypatch.setenv("SAT_DM_MODO", "hosted")
    cc.registrar(UA_CHROME, "201.141.10.20", None)
    # Una llamada del gateway MCP (marcada) o un cliente HTTP no pisan a la persona.
    cc.registrar("python-httpx/0.27", "187.77.152.160", None)
    cc.registrar(UA_CHROME, "187.77.152.160", "mcp")
    assert cc.headers()[cc.HEADER_IP] == "201.141.10.20"
    assert cc.headers()[cc.HEADER_UA] == UA_CHROME


def test_ip_invalida_se_descarta(monkeypatch):
    monkeypatch.setenv("SAT_DM_MODO", "hosted")
    cc.registrar(UA_CHROME, "no-es-ip", None)
    assert cc.HEADER_IP not in cc.headers()
    assert cc.user_agent_valido("Mozilla/" + "x" * 600) is None


def test_sin_nada_registrado_solo_va_el_modo():
    assert cc.headers() == {cc.HEADER_MODO: "desktop"}


def test_la_licencia_lleva_el_contexto(monkeypatch):
    cc.registrar(UA_ELECTRON, None, None)
    capturado = {}

    def fake_get(url, headers=None, timeout=None):
        capturado.update(headers or {})
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"authenticated": True}
        return r

    monkeypatch.setattr(lc.requests, "get", fake_get)
    lc.fetch_license_remote(Session(access_token="tok", refresh_token=None, user_id="u1", email=None))
    assert capturado["Authorization"] == "Bearer tok"
    assert capturado[cc.HEADER_UA] == UA_ELECTRON
    assert capturado[cc.HEADER_MODO] == "desktop"


def test_el_checkout_lleva_el_contexto(monkeypatch):
    monkeypatch.setenv("SAT_DM_MODO", "hosted")
    cc.registrar(UA_CHROME, "201.141.10.20", None)
    capturado = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        capturado.update(headers or {})
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"url": "https://checkout.stripe.com/x"}
        return r

    monkeypatch.setattr(lc.requests, "post", fake_post)
    lc.init_subscribe_checkout(Session(access_token="tok", refresh_token=None, user_id="u1", email=None))
    assert capturado[cc.HEADER_IP] == "201.141.10.20"
    assert capturado[cc.HEADER_MODO] == "web"
