"""
Fixtures compartidos para todos los tests.

pytest carga este archivo automáticamente. Los fixtures definidos aquí
están disponibles en cualquier test sin necesidad de importarlos.
"""

import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def keyring_en_memoria():
    """
    Backend de keyring en memoria para TODOS los tests: las credenciales nunca
    tocan el keychain real del SO. Se aísla por test (cada uno arranca vacío).
    """
    keyring = pytest.importorskip("keyring")
    from keyring.backend import KeyringBackend

    class _MemKeyring(KeyringBackend):
        priority = 1

        def __init__(self):
            self._store: dict = {}

        def set_password(self, service, username, password):
            self._store[(service, username)] = password

        def get_password(self, service, username):
            return self._store.get((service, username))

        def delete_password(self, service, username):
            self._store.pop((service, username), None)

    anterior = keyring.get_keyring()
    keyring.set_keyring(_MemKeyring())
    try:
        yield
    finally:
        keyring.set_keyring(anterior)


@pytest.fixture(autouse=True)
def licencia_en_tmp(tmp_path, monkeypatch):
    """
    El cache de licencia (`~/.sat-descarga/license-cache.json`) nunca es el
    real: con el tope de empresas (F1) la licencia del equipo de quien corre
    las pruebas podría bloquear altas en los tests del catálogo.
    """
    from sat_descarga.api import cupo_descargas, license_client

    monkeypatch.setattr(
        license_client, "LICENSE_CACHE_PATH", tmp_path / "license-cache-aislado.json"
    )
    # Igual con el contador de descargas del mes: nunca el del equipo real.
    monkeypatch.setattr(cupo_descargas, "_ruta", lambda: tmp_path / "descargas-mes-aislado.json")


@pytest.fixture(autouse=True)
def uso_apagado_y_aislado(tmp_path, monkeypatch):
    """
    Uso por acción (api/uso.py) APAGADO en todas las pruebas (`SAT_DM_SIN_USO=1`)
    y con la cola en tmp: ni las pruebas en modo hosted escriben la cola real ni
    se manda nada. Las pruebas de uso lo encienden a mano.
    """
    from sat_descarga.api import uso

    monkeypatch.setenv("SAT_DM_SIN_USO", "1")
    monkeypatch.setattr(uso, "_ruta", lambda: tmp_path / "uso-pendiente-aislado.jsonl")
    monkeypatch.setattr(uso, "_conteo", None)
    monkeypatch.setattr(uso, "_ultimos", {})
    monkeypatch.setattr(uso, "_pausa_hasta", 0.0)


@pytest.fixture(autouse=True)
def sin_instalacion_de_navegador(monkeypatch):
    """
    Los tests nunca deben descargar Chromium: se desactiva el warm-up del
    lifespan y se marca el navegador como ya verificado. Los tests de
    portal/setup.py (test_portal_setup.py) revierten el flag localmente.
    """
    monkeypatch.setenv("SAT_AGENT_SKIP_BROWSER_WARMUP", "1")
    from sat_descarga.portal import setup

    monkeypatch.setattr(setup, "_install_checked", True)


@pytest.fixture
def fixtures_dir():
    """Ruta al directorio de fixtures."""
    return FIXTURES_DIR


@pytest.fixture
def test_cer():
    """Ruta al certificado de prueba (.cer)."""
    return str(FIXTURES_DIR / "test_fiel.cer")


@pytest.fixture
def test_key():
    """Ruta a la llave privada de prueba (.key)."""
    return str(FIXTURES_DIR / "test_fiel.key")


@pytest.fixture
def test_password():
    """Contraseña de la llave de prueba."""
    return "12345678"


@pytest.fixture
def test_rfc():
    """RFC del certificado de prueba."""
    return "XAXX010101000"


@pytest.fixture(autouse=True)
def sesion_unica_aislada(tmp_path, monkeypatch):
    """
    Sesión única (F1.1): el id de instalación nunca se escribe en el
    `~/.sat-descarga` real, el estado arranca limpio en cada test y el hilo de
    latidos no corre (los lifespans de TestClient lo arrancarían).
    """
    from sat_descarga.api import sesion_unica

    monkeypatch.setenv("SAT_DM_SIN_SESION_UNICA", "1")
    monkeypatch.setattr(
        sesion_unica, "_ruta_instalacion", lambda: tmp_path / "instalacion-aislada.json"
    )
    monkeypatch.setattr(sesion_unica, "_instalacion_cache", None)
    monkeypatch.setattr(sesion_unica, "_ultima_interaccion", None)
    sesion_unica.reiniciar()
    yield
    sesion_unica.reiniciar()
