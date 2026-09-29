"""Registro desde la web en el provisioner (deploy/provisioner/main.py).

GoTrue, el endpoint de licencia y docker van simulados: se prueba el contrato
del provisioner (qué le pide a GoTrue, cuándo crea contenedores y qué contesta),
no los servicios externos.
"""

import base64
import importlib.util
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
import requests  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PROVISIONER = Path(__file__).parent.parent / "deploy" / "provisioner" / "main.py"


# `import docker` dentro del provisioner: en el repo hay una carpeta docker/ que
# le gana al SDK en sys.path, así que se inyecta un módulo mínimo con la única
# pieza que usa el código (errors.NotFound).
class _NoExiste(Exception):
    pass


docker = types.ModuleType("docker")
docker.errors = types.SimpleNamespace(NotFound=_NoExiste)
GOTRUE = "https://gotrue.test"
LICENCIA = "https://licencia.test/api/desktop/license"


# ---------------------------------------------------------------------------
# Carga del módulo con envs de prueba
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def prov(tmp_path_factory):
    envs = {
        "SAT_DM_MASTER_KEY": base64.b64encode(b"k" * 32).decode(),
        "REGISTRO_PATH": str(tmp_path_factory.mktemp("registro") / "registry.json"),
        "MAX_AGENTES": "2",
        "EXIGIR_LICENCIA": "1",
        "LICENCIA_URL": LICENCIA,
        "TODOCONTA_SUPABASE_URL": GOTRUE,
    }
    mp = pytest.MonkeyPatch()
    for k, v in envs.items():
        mp.setenv(k, v)
    for k in ("ALERTA_WEBHOOK_URL", "DOMINIOS_DESECHABLES", "CONFIAR_X_FORWARDED_FOR"):
        mp.delenv(k, raising=False)
    spec = importlib.util.spec_from_file_location("provisioner_main_test", PROVISIONER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["provisioner_main_test"] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("provisioner_main_test", None)
    mp.undo()


# ---------------------------------------------------------------------------
# Dobles: requests (GoTrue + licencia + health) y docker
# ---------------------------------------------------------------------------


class Resp:
    def __init__(self, status: int, data=None):
        self.status_code = status
        self._data = data if data is not None else {}

    def json(self):
        return self._data


class FakeHttp:
    """Responde como GoTrue, la licencia y el /health del agente; registra llamadas."""

    def __init__(self):
        self.llamadas = []  # (metodo, ruta, json, params)
        self.respuestas = {}  # ruta de GoTrue -> Resp (sobrescribe el default)
        self.plan = "trial"

    def post(self, url, json=None, params=None, headers=None, timeout=None):
        ruta = url.replace(f"{GOTRUE}/auth/v1", "")
        self.llamadas.append(("POST", ruta, json, params))
        if ruta in self.respuestas:
            return self.respuestas[ruta]
        if ruta in ("/verify", "/token"):
            correo = (json or {}).get("email", "x@x.mx")
            return Resp(
                200,
                {
                    "access_token": f"tok-{correo}",
                    "refresh_token": "ref",
                    "user": {"id": f"user-{correo}", "email": correo},
                },
            )
        if ruta == "/signup":
            # Confirmación de correo activada (default): sin sesión.
            return Resp(200, {"id": "nuevo", "email": (json or {}).get("email")})
        return Resp(200, {})

    def get(self, url, headers=None, timeout=None):
        self.llamadas.append(("GET", url, None, None))
        if url == LICENCIA:
            return Resp(200, {"plan": self.plan})
        if url.startswith("http://agente-") and "/health" in url:
            return Resp(200, {"status": "ok"})
        return Resp(404)

    def gotrue(self, ruta):
        return [c for c in self.llamadas if c[0] == "POST" and c[1] == ruta]


class FakeContenedor:
    def __init__(self, nombre, status="running", labels=None):
        self.name = nombre
        self.status = status
        self.labels = {"todoconta.agente": "1"} if labels is None else labels
        self.arrancado = False

    def start(self):
        self.status = "running"
        self.arrancado = True


class FakeContenedores:
    def __init__(self):
        self.items = {}
        self.creados = []

    def get(self, nombre):
        if nombre not in self.items:
            raise docker.errors.NotFound(f"no existe {nombre}")
        return self.items[nombre]

    def list(self, filters=None):
        filters = filters or {}
        res = list(self.items.values())
        if filters.get("status"):
            res = [c for c in res if c.status == filters["status"]]
        if filters.get("label"):
            clave, _, valor = filters["label"].partition("=")
            res = [c for c in res if c.labels.get(clave) == valor]
        return res

    def run(self, imagen, name=None, labels=None, **kwargs):
        c = FakeContenedor(name, "running", labels or {})
        self.items[name] = c
        self.creados.append(name)
        return c


class FakeColeccion:
    def __init__(self):
        self.items = set()

    def get(self, nombre):
        if nombre not in self.items:
            raise docker.errors.NotFound(f"no existe {nombre}")
        return nombre

    def create(self, nombre, **kwargs):
        self.items.add(nombre)
        return nombre


class FakeDocker:
    def __init__(self):
        self.containers = FakeContenedores()
        self.networks = FakeColeccion()
        self.volumes = FakeColeccion()


@pytest.fixture
def http(prov, monkeypatch):
    fake = FakeHttp()
    monkeypatch.setattr(
        prov,
        "requests",
        types.SimpleNamespace(
            post=fake.post,
            get=fake.get,
            RequestException=requests.RequestException,
            Response=requests.Response,
        ),
    )
    return fake


@pytest.fixture
def dk(prov, monkeypatch):
    fake = FakeDocker()
    monkeypatch.setitem(sys.modules, "docker", docker)
    monkeypatch.setattr(prov, "_docker", lambda: fake)
    return fake


@pytest.fixture
def alertas(prov, monkeypatch):
    enviadas = []
    monkeypatch.setattr(prov, "_alertar", lambda texto: enviadas.append(texto))
    return enviadas


@pytest.fixture
def client(prov, http, dk, alertas):
    prov._intentos.clear()
    with TestClient(prov.app) as c:
        yield c


def _ip(n):
    return {"X-Forwarded-For": f"10.0.0.{n}"}


def _nombre_contenedor(prov, correo):
    return f"agente-{prov._derivar(f'user-{correo}')['slug']}"


# ---------------------------------------------------------------------------
# Registro por código
# ---------------------------------------------------------------------------


def test_registro_por_codigo_crea_la_cuenta_y_su_espacio(client, http, dk, prov):
    r = client.post(
        "/provision/otp-send",
        json={"email": "ana@despacho.mx", "crear_cuenta": True, "nombre": "Ana López"},
        headers=_ip(1),
    )
    assert r.status_code == 200
    (envio,) = http.gotrue("/otp")
    assert envio[2] == {
        "email": "ana@despacho.mx",
        "create_user": True,
        "data": {"full_name": "Ana López"},
    }

    r = client.post(
        "/provision/otp-verify",
        json={"email": "ana@despacho.mx", "token": "123456"},
        headers=_ip(1),
    )
    assert r.status_code == 200
    cuerpo = r.json()
    assert "/u/" in cuerpo["base_url"]
    assert cuerpo["session"]["email"] == "ana@despacho.mx"
    (verif,) = http.gotrue("/verify")
    assert verif[2]["type"] == "email"
    # La licencia se consultó (ahí arranca la prueba) y se creó su contenedor.
    assert any(c[0] == "GET" and c[1] == LICENCIA for c in http.llamadas)
    assert dk.containers.creados == [_nombre_contenedor(prov, "ana@despacho.mx")]


def test_login_por_codigo_sigue_sin_crear_cuentas(client, http):
    r = client.post("/provision/otp-send", json={"email": "beto@despacho.mx"}, headers=_ip(2))
    assert r.status_code == 200
    (envio,) = http.gotrue("/otp")
    assert envio[2] == {"email": "beto@despacho.mx", "create_user": False}


# ---------------------------------------------------------------------------
# Registro con contraseña
# ---------------------------------------------------------------------------


def test_registro_con_contrasena_confirma_con_codigo(client, http, dk):
    r = client.post(
        "/provision/signup",
        json={"email": "carla@despacho.mx", "password": "secreta123", "nombre": "Carla"},
        headers=_ip(3),
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "requiere_confirmacion": True}
    (alta,) = http.gotrue("/signup")
    assert alta[2] == {
        "email": "carla@despacho.mx",
        "password": "secreta123",
        "data": {"full_name": "Carla"},
    }
    # Todavía no hay espacio: se crea al confirmar el correo.
    assert dk.containers.creados == []

    r = client.post(
        "/provision/otp-verify",
        json={"email": "carla@despacho.mx", "token": "654321", "tipo": "signup"},
        headers=_ip(3),
    )
    assert r.status_code == 200
    (verif,) = http.gotrue("/verify")
    assert verif[2]["type"] == "signup"
    assert len(dk.containers.creados) == 1


def test_registro_sin_confirmacion_abre_el_espacio_de_una_vez(client, http, dk):
    http.respuestas["/signup"] = Resp(
        200,
        {
            "access_token": "tok-dani",
            "refresh_token": "ref",
            "user": {"id": "user-dani@despacho.mx", "email": "dani@despacho.mx"},
        },
    )
    r = client.post(
        "/provision/signup",
        json={"email": "dani@despacho.mx", "password": "secreta123"},
        headers=_ip(4),
    )
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["requiere_confirmacion"] is False
    assert "/u/" in cuerpo["base_url"]
    assert len(dk.containers.creados) == 1


def test_registro_contrasena_corta_no_llega_a_gotrue(client, http):
    r = client.post(
        "/provision/signup",
        json={"email": "eva@despacho.mx", "password": "corta"},
        headers=_ip(5),
    )
    assert r.status_code == 400
    assert http.gotrue("/signup") == []


def test_registro_de_correo_existente_no_lo_revela(client, http):
    http.respuestas["/signup"] = Resp(
        422, {"error_code": "user_already_exists", "msg": "User already registered"}
    )
    r = client.post(
        "/provision/signup",
        json={"email": "fer@despacho.mx", "password": "secreta123"},
        headers=_ip(6),
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "requiere_confirmacion": True}


def test_reenviar_confirmacion_no_revela_si_hay_registro(client, http):
    http.respuestas["/resend"] = Resp(400, {"error_code": "user_not_found"})
    r = client.post(
        "/provision/otp-send",
        json={"email": "gabo@despacho.mx", "tipo": "signup"},
        headers=_ip(7),
    )
    assert r.status_code == 200
    (reenvio,) = http.gotrue("/resend")
    assert reenvio[2] == {"type": "signup", "email": "gabo@despacho.mx"}


def test_reenviar_confirmacion_si_informa_el_limite(client, http):
    http.respuestas["/resend"] = Resp(429, {"error_code": "over_email_send_rate_limit"})
    r = client.post(
        "/provision/otp-send",
        json={"email": "gabo@despacho.mx", "tipo": "signup"},
        headers=_ip(8),
    )
    assert r.status_code == 429


def test_tipo_de_verificacion_invalido(client, http):
    r = client.post(
        "/provision/otp-verify",
        json={"email": "hugo@despacho.mx", "token": "123456", "tipo": "magiclink"},
        headers=_ip(9),
    )
    assert r.status_code == 400
    assert http.gotrue("/verify") == []


# ---------------------------------------------------------------------------
# Antiabuso
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("correo", ["x@mailinator.com", "y@alias.yopmail.com"])
def test_correo_desechable_no_puede_registrarse(client, http, correo):
    r = client.post(
        "/provision/signup",
        json={"email": correo, "password": "secreta123"},
        headers=_ip(10),
    )
    assert r.status_code == 400
    assert "temporales" in r.json()["detail"]
    r = client.post(
        "/provision/otp-send",
        json={"email": correo, "crear_cuenta": True},
        headers=_ip(11),
    )
    assert r.status_code == 400
    assert http.gotrue("/signup") == [] and http.gotrue("/otp") == []


def test_correo_desechable_si_puede_pedir_codigo_de_login(client, http):
    # El bloqueo es solo para registrar: el login no cambia.
    r = client.post(
        "/provision/otp-send", json={"email": "viejo@mailinator.com"}, headers=_ip(12)
    )
    assert r.status_code == 200


def test_limite_por_correo_aunque_cambie_de_ip(client, prov):
    correo = "ines@despacho.mx"
    for i in range(prov._RATE_MAX_CORREO):
        r = client.post(
            "/provision/otp-send",
            json={"email": correo, "crear_cuenta": True},
            headers=_ip(100 + i),
        )
        assert r.status_code == 200
    r = client.post(
        "/provision/otp-send",
        json={"email": correo.upper(), "crear_cuenta": True},
        headers=_ip(200),
    )
    assert r.status_code == 429
    # Otro correo no se ve afectado.
    r = client.post(
        "/provision/otp-send",
        json={"email": "otra@despacho.mx", "crear_cuenta": True},
        headers=_ip(201),
    )
    assert r.status_code == 200


def test_limite_por_ip_usa_la_ip_real_detras_de_traefik(client, prov):
    for i in range(prov._RATE_MAX):
        r = client.post(
            "/provision/otp-send", json={"email": f"u{i}@despacho.mx"}, headers=_ip(50)
        )
        assert r.status_code == 200
    r = client.post("/provision/otp-send", json={"email": "u99@despacho.mx"}, headers=_ip(50))
    assert r.status_code == 429
    # Otro cliente (otra IP en X-Forwarded-For) sigue entrando.
    r = client.post("/provision/otp-send", json={"email": "u98@despacho.mx"}, headers=_ip(51))
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Guarda de capacidad
# ---------------------------------------------------------------------------


def test_capacidad_llena_frena_espacios_nuevos(client, dk, alertas):
    for n in ("agente-aaa", "agente-bbb"):
        dk.containers.items[n] = FakeContenedor(n)
    r = client.post(
        "/provision/otp-verify",
        json={"email": "juan@despacho.mx", "token": "123456"},
        headers=_ip(60),
    )
    assert r.status_code == 503
    assert r.json()["motivo"] == "capacidad"
    assert "más espacio" in r.json()["detail"]
    assert dk.containers.creados == []
    # No deja volumen huérfano y avisa.
    assert dk.volumes.items == set()
    assert len(alertas) == 1


def test_capacidad_llena_no_frena_a_quien_ya_tiene_espacio(client, dk, prov, alertas):
    for n in ("agente-aaa", "agente-bbb"):
        dk.containers.items[n] = FakeContenedor(n)
    propio = _nombre_contenedor(prov, "karla@despacho.mx")
    dk.containers.items[propio] = FakeContenedor(propio, status="exited")
    r = client.post(
        "/provision/login-password",
        json={"email": "karla@despacho.mx", "password": "secreta123"},
        headers=_ip(61),
    )
    assert r.status_code == 200
    assert dk.containers.items[propio].arrancado is True
    assert dk.containers.creados == []
    assert alertas == []


def test_los_contenedores_sin_marca_no_cuentan(client, dk):
    # Solo cuentan los agentes creados por el provisioner (label todoconta.agente).
    dk.containers.items["traefik"] = FakeContenedor("traefik", labels={})
    dk.containers.items["agente-aaa"] = FakeContenedor("agente-aaa")
    r = client.post(
        "/provision/otp-verify",
        json={"email": "leo@despacho.mx", "token": "123456"},
        headers=_ip(62),
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Lo que no cambia
# ---------------------------------------------------------------------------


def test_login_con_contrasena_sigue_igual(client, http, dk):
    r = client.post(
        "/provision/login-password",
        json={"email": "mar@despacho.mx", "password": "secreta123"},
        headers=_ip(70),
    )
    assert r.status_code == 200
    (token,) = http.gotrue("/token")
    assert token[3] == {"grant_type": "password"}
    assert len(dk.containers.creados) == 1


def test_sin_plan_sigue_en_403(client, http, dk):
    http.plan = "free"
    r = client.post(
        "/provision/otp-verify",
        json={"email": "nora@despacho.mx", "token": "123456"},
        headers=_ip(71),
    )
    assert r.status_code == 403
    assert dk.containers.creados == []
