"""Endpoints /diot/* del agente local (TestClient)."""

import inspect
import json
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from sat_descarga.api import jobs, server  # noqa: E402
from sat_descarga.cli import config_store  # noqa: E402
from sat_descarga.diot import exportar_txt, fila_vacia  # noqa: E402
from sat_descarga.portal import diot_presentacion  # noqa: E402
from sat_descarga.procesador import parse_cfdi  # noqa: E402
from sat_descarga.procesador import db as db_mod  # noqa: E402

from .test_diot import MI_RFC, PROV_A, PROV_B, _xml  # noqa: E402

PERIODO = "2026-05"


@pytest.fixture(autouse=True)
def aislar(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    # Siembra el singleton del procesador con una DB temporal.
    db_mod.resetear_singleton_para_tests()
    db = db_mod.abrir_db(tmp_path / "procesador.db")
    db.agregar([parse_cfdi(_xml("API-1"))], mi_rfc=MI_RFC)
    yield
    db_mod.resetear_singleton_para_tests()


@pytest.fixture
def client():
    return TestClient(server.app)


def test_estado_vacio(client):
    r = client.get("/diot/estado", params={"rfc": MI_RFC, "periodo": PERIODO})
    assert r.status_code == 200
    body = r.json()
    assert body["filas"] == [] and body["errores"] == []


def test_flujo_prellenar_editar_exportar(client):
    # Prellenar desde el buffer del procesador.
    r = client.post("/diot/prellenar", json={"rfc": MI_RFC, "periodo": PERIODO})
    assert r.status_code == 200
    body = r.json()
    assert body["resumen"]["proveedores"] == 1
    (fila,) = body["filas"]
    assert fila["rfc"] == PROV_A and fila["valor_16"] == 1000

    # Editar: el usuario ajusta un monto y agrega un renglón manual.
    fila["valor_16"] = 1200
    manual = fila_vacia()
    manual.update(rfc="CCC030303CC9", valor_16=500, acred_excl_16=80, origen="manual")
    r = client.put(
        "/diot/estado",
        json={"rfc": MI_RFC, "periodo": PERIODO, "filas": [fila, manual]},
    )
    assert r.status_code == 200
    assert len(r.json()["filas"]) == 2

    # El estado editado persiste.
    r = client.get("/diot/estado", params={"rfc": MI_RFC, "periodo": PERIODO})
    assert r.json()["filas"][0]["valor_16"] == 1200

    # Re-prellenar pisa la fila CFDI (vuelve a 1000) pero conserva la manual.
    r = client.post("/diot/prellenar", json={"rfc": MI_RFC, "periodo": PERIODO})
    filas = r.json()["filas"]
    assert {f["rfc"] for f in filas} == {PROV_A, "CCC030303CC9"}
    assert next(f for f in filas if f["rfc"] == PROV_A)["valor_16"] == 1000

    # Exportar el TXT.
    r = client.get("/diot/exportar", params={"rfc": MI_RFC, "periodo": PERIODO})
    assert r.status_code == 200
    assert r.headers["content-disposition"] == (
        f'attachment; filename="{MI_RFC}_diot_{PERIODO}.txt"'
    )
    assert r.content.startswith(b"\xef\xbb\xbf")
    assert r.content.count(b"\r\n") == 2


def test_exportar_sin_filas_400(client):
    r = client.get("/diot/exportar", params={"rfc": MI_RFC, "periodo": "2026-01"})
    assert r.status_code == 400


def test_exportar_con_errores_400(client):
    fila = fila_vacia()
    fila.update(rfc="", valor_16=100)  # nacional sin RFC → error duro
    client.put("/diot/estado", json={"rfc": MI_RFC, "periodo": PERIODO, "filas": [fila]})
    r = client.get("/diot/exportar", params={"rfc": MI_RFC, "periodo": PERIODO})
    assert r.status_code == 400
    assert r.json()["detail"]["errores"]


def test_rfc_y_periodo_invalidos_400(client):
    assert client.get("/diot/estado", params={"rfc": "MALO", "periodo": PERIODO}).status_code == 400
    assert client.get("/diot/estado", params={"rfc": MI_RFC, "periodo": "2026-13"}).status_code == 400


def test_catalogos(client):
    r = client.get("/diot/catalogos")
    assert r.status_code == 200
    body = r.json()
    assert body["tipo_tercero"]["04"] == "Proveedor Nacional"
    assert body["operaciones_por_tercero"]["15"] == ["87"]
    assert body["paises"]["ZZZ"] == "Otro"
    assert len(body["campos"]) == 54


# ---------------------------------------------------------------------------
# POST /diot/presentar y /diot/acuse: el job completo con un portal falso
# ---------------------------------------------------------------------------

RFC_FIEL = "XAXX010101000"  # RFC del certificado de pruebas (tests/fixtures)


def _argumentos(metodo, yo, *args, **kwargs) -> dict:
    """Liga la llamada a la firma REAL del método: un argumento de más, de menos
    o mal nombrado truena aquí con el mismo TypeError que en producción."""
    ligada = inspect.signature(metodo).bind(yo, *args, **kwargs)
    ligada.apply_defaults()
    return {k: v for k, v in ligada.arguments.items() if k != "self"}


@pytest.fixture
def portal(tmp_path, monkeypatch, test_cer, test_key, test_password):
    """Empresa con e.firma en el catálogo y un `PresentadorDiot` falso que nunca
    abre el navegador ni toca al SAT. Devuelve lo que el router le pidió."""
    monkeypatch.setattr(jobs, "registry", jobs.JobRegistry())
    monkeypatch.setattr(config_store, "EFIRMA_DIR", tmp_path / "efirma")
    monkeypatch.setattr(config_store, "descargas_dir_default",
                        lambda: str(tmp_path / "TodoConta"))
    eventos_uso = []
    monkeypatch.setattr("sat_descarga.api.routers.diot.track",
                        lambda evento, **props: eventos_uso.append((evento, props)))

    real = diot_presentacion.PresentadorDiot
    pedido = {"presentar": [], "acuse": [], "uso": eventos_uso}

    class PresentadorFalso:
        def __init__(self, *args, **kwargs):
            self.opciones = _argumentos(real.__init__, self, *args, **kwargs)

        def presentar(self, *args, **kwargs):
            llamada = _argumentos(real.presentar, self, *args, **kwargs)
            # el mismo parser con el que el portal real coteja los Totales
            totales = diot_presentacion.totales_de_txt(llamada["txt_path"])
            llamada["contenido"] = Path(llamada["txt_path"]).read_bytes()
            pedido["presentar"].append(llamada)
            self.opciones["on_progreso"]("subiendo_txt", {})
            return {
                "estado": "presentado" if llamada["enviar"] else "validado",
                "totales_txt": totales, "totales_portal": totales,
                "discrepancias": [], "acuse": None, "evidencia": [],
            }

        def descargar_acuse(self, *args, **kwargs):
            llamada = _argumentos(real.descargar_acuse, self, *args, **kwargs)
            pedido["acuse"].append(llamada)
            pdf = Path(llamada["directorio_salida"]) / "acuse_diot.pdf"
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(b"%PDF-1.4 acuse de prueba")
            return pdf

    monkeypatch.setattr(diot_presentacion, "PresentadorDiot", PresentadorFalso)
    assert config_store.add_empresa("Mi Empresa", test_cer, test_key,
                                    test_password) == RFC_FIEL
    return pedido


def _filas_validas():
    a = fila_vacia()
    a.update(rfc=PROV_A, valor_16=1000, acred_excl_16=160, origen="cfdi")
    b = fila_vacia()
    b.update(rfc=PROV_B, valor_16=500, acred_excl_16=80, origen="manual")
    return [a, b]


def _terminar_job(client, job_id, timeout_s=8.0):
    """Espera a que el job termine y drena su SSE, que se cierra después de
    `al_completar`. Devuelve (estado final, eventos del stream)."""
    limite = time.monotonic() + timeout_s
    while True:
        estado = client.get(f"/jobs/{job_id}").json()
        if estado["estado"] in ("done", "error", "cancelled"):
            break
        if time.monotonic() > limite:
            pytest.fail(f"El job {job_id} no terminó en {timeout_s}s: {estado}")
        time.sleep(0.02)
    eventos = []
    with client.stream("GET", f"/events/{job_id}") as r:
        for linea in r.iter_lines():
            if linea.startswith("data: "):
                eventos.append(json.loads(linea[len("data: "):]))
    return estado, eventos


def _carpeta_presentacion(tmp_path, ejercicio=2026, mes=7):
    return (tmp_path / "TodoConta" / "diot" / "presentaciones" / RFC_FIEL
            / str(ejercicio) / f"{mes:02d}-{ejercicio}")


def test_presentar_con_el_txt_que_genera_la_app(client, portal, tmp_path):
    r = client.put("/diot/estado", json={
        "rfc": RFC_FIEL, "periodo": "2026-07", "filas": _filas_validas()})
    assert r.status_code == 200
    exportado = client.get("/diot/exportar",
                           params={"rfc": RFC_FIEL, "periodo": "2026-07"}).content

    r = client.post("/diot/presentar", json={
        "rfc": RFC_FIEL, "ejercicio": 2026, "periodo": 7, "usar_generado": True,
        "sin_estimulos": True, "solo_validar": True})
    assert r.status_code == 200, r.text
    estado, eventos = _terminar_job(client, r.json()["job_id"])

    assert estado["estado"] == "done", estado["error"]
    assert estado["resultado"]["estado"] == "validado"
    assert estado["resultado"]["totales_txt"]["operaciones"] == 2
    (llamada,) = portal["presentar"]
    # el mismo TXT que baja GET /diot/exportar, escrito junto a la evidencia
    carpeta = _carpeta_presentacion(tmp_path)
    assert llamada["txt_path"] == str(carpeta / f"{RFC_FIEL}_diot_2026-07.txt")
    assert llamada["contenido"] == exportado
    assert llamada["directorio_salida"] == str(carpeta)
    assert (llamada["ejercicio"], llamada["periodo"], llamada["rfc"]) == (2026, 7, RFC_FIEL)
    assert llamada["enviar"] is False
    assert llamada["password"] == "12345678"
    assert any(e.get("fase") == "subiendo_txt" for e in eventos)
    # el export de arriba cuenta lo suyo; presentar no suma otro export
    assert portal["uso"] == [
        ("diot_txt_exportado", {}),
        ("diot_presentada", {"modo": "validacion"}),
    ]


def test_presentar_con_el_txt_del_usuario(client, portal, tmp_path):
    # el TXT que sale del software contable del usuario: se sube tal cual
    txt = tmp_path / "mi_contabilidad" / "diot_julio.txt"
    txt.parent.mkdir()
    txt.write_bytes(exportar_txt(_filas_validas()[:1]))

    r = client.post("/diot/presentar", json={
        "rfc": RFC_FIEL, "ejercicio": 2026, "periodo": 7, "txt_path": str(txt),
        "sin_estimulos": True, "confirmar": True})
    assert r.status_code == 200, r.text
    estado, _ = _terminar_job(client, r.json()["job_id"])

    assert estado["estado"] == "done", estado["error"]
    assert estado["resultado"]["estado"] == "presentado"
    (llamada,) = portal["presentar"]
    assert llamada["txt_path"] == str(txt)
    assert llamada["contenido"] == txt.read_bytes()
    assert llamada["enviar"] is True
    # no se generó ni se escribió otro TXT
    assert not list(_carpeta_presentacion(tmp_path).glob("*.txt"))
    assert portal["uso"] == [("diot_presentada", {"modo": "envio"})]


def test_presentar_generado_sin_renglones_es_400(client, portal):
    r = client.post("/diot/presentar", json={
        "rfc": RFC_FIEL, "ejercicio": 2026, "periodo": 7, "usar_generado": True,
        "sin_estimulos": True, "solo_validar": True})
    assert r.status_code == 400
    assert "renglones" in r.json()["detail"]
    assert portal["presentar"] == []


def test_presentar_generado_con_errores_es_400(client, portal):
    fila = fila_vacia()
    fila.update(rfc="", valor_16=100)  # nacional sin RFC → error duro
    client.put("/diot/estado", json={"rfc": RFC_FIEL, "periodo": "2026-07", "filas": [fila]})
    r = client.post("/diot/presentar", json={
        "rfc": RFC_FIEL, "ejercicio": 2026, "periodo": 7, "usar_generado": True,
        "sin_estimulos": True, "solo_validar": True})
    assert r.status_code == 400
    assert r.json()["detail"]["errores"]
    assert portal["presentar"] == []


def test_presentar_generado_con_ejercicio_invalido_es_400(client, portal):
    r = client.post("/diot/presentar", json={
        "rfc": RFC_FIEL, "ejercicio": 26, "periodo": 7, "usar_generado": True,
        "sin_estimulos": True, "solo_validar": True})
    assert r.status_code == 400
    assert portal["presentar"] == []


def test_acuse_con_el_portal_falso(client, portal, tmp_path):
    r = client.post("/diot/acuse", json={"rfc": RFC_FIEL, "ejercicio": 2026, "periodo": 7})
    assert r.status_code == 200, r.text
    estado, _ = _terminar_job(client, r.json()["job_id"])

    assert estado["estado"] == "done", estado["error"]
    carpeta = _carpeta_presentacion(tmp_path)
    assert estado["resultado"] == {"acuse": str(carpeta / "acuse_diot.pdf")}
    (llamada,) = portal["acuse"]
    assert (llamada["ejercicio"], llamada["periodo"], llamada["rfc"]) == (2026, 7, RFC_FIEL)
