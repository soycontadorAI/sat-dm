"""Endpoints /ce/* y la presentación DIOT del agente local (TestClient).

Sin browser (convención del repo): se prueban las vallas de entrada — la
confirmación obligatoria, la limitante de estímulos como contrato, la revisión
previa de ZIPs, el 409 de job activo — y la lectura de la cola de pendientes.
"""

import zipfile

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from sat_descarga.api import jobs, server  # noqa: E402
from sat_descarga.cli import config_store  # noqa: E402

RFC = "SSA980330HU1"

XML_BALANZA = (
    '<?xml version="1.0"?>\n'
    '<BCE:Balanza Version="1.3" RFC="{rfc}" Mes="{mes}" Anio="{anio}" '
    'TipoEnvio="N" xmlns:BCE="http://www.sat.gob.mx/esquemas/ContabilidadE/'
    '1_3/BalanzaComprobacion"><BCE:Ctas NumCta="100-01" SaldoIni="1.0" '
    'Debe="0.0" Haber="0.0" SaldoFin="1.0"/></BCE:Balanza>'
)


@pytest.fixture(autouse=True)
def aislar(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "get_config_dir",
                        lambda: tmp_path / ".sat-descarga")
    yield


@pytest.fixture
def client():
    return TestClient(server.app)


def _zip_valido(tmp_path, rfc=RFC, anio="2026", mes="01"):
    path = tmp_path / f"{rfc}{anio}{mes}BN.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(path.stem + ".xml",
                    XML_BALANZA.format(rfc=rfc, anio=anio, mes=mes))
    return path


# --- /ce/enviar: vallas ------------------------------------------------------

def test_enviar_sin_confirmar_es_400(client, tmp_path):
    r = client.post("/ce/enviar", json={
        "rfc": RFC, "archivos": [str(_zip_valido(tmp_path))]})
    assert r.status_code == 400
    assert "confirmar" in r.json()["detail"]


def test_enviar_archivo_inexistente_es_400(client):
    r = client.post("/ce/enviar", json={
        "rfc": RFC, "archivos": ["/no/existe.zip"], "solo_validar": True})
    assert r.status_code == 400
    assert "No existe" in r.json()["detail"]


def test_enviar_zip_que_no_pasa_revision_es_400(client, tmp_path):
    # nombre dice 2026-01 pero el XML trae otro RFC: no debe llegar al portal
    path = tmp_path / f"{RFC}202601BN.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(path.stem + ".xml", XML_BALANZA.format(
            rfc="SAJ0205248A9", anio="2026", mes="01"))
    r = client.post("/ce/enviar", json={
        "rfc": RFC, "archivos": [str(path)], "solo_validar": True})
    assert r.status_code == 400
    assert "revisión previa" in r.json()["detail"]["mensaje"]


def test_enviar_sin_efirma_en_catalogo_falla_limpio(client, tmp_path):
    # empresa no registrada → 404 (contrato de _empresa_con_fiel en certifica)
    r = client.post("/ce/enviar", json={
        "rfc": "XAXX010101000", "archivos": [str(_zip_valido(
            tmp_path, rfc="XAXX010101000"))], "solo_validar": True})
    assert r.status_code == 404


def test_enviar_con_job_activo_es_409(client, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs.registry, "hay_activo", lambda: True)
    monkeypatch.setattr(
        "sat_descarga.api.routers.ce._credenciales_keychain",
        lambda rfc: {"cer_path": "x", "key_path": "y", "password": "z"})
    r = client.post("/ce/enviar", json={
        "rfc": RFC, "archivos": [str(_zip_valido(tmp_path))],
        "solo_validar": True})
    assert r.status_code == 409


# --- /ce/acuses --------------------------------------------------------------

def test_acuses_rango_invalido_es_400(client):
    r = client.post("/ce/acuses", json={
        "rfc": RFC, "anio": 2026, "mes_ini": 5, "mes_fin": 2})
    assert r.status_code == 400


# --- /ce/pendientes y /ce/reanudar ------------------------------------------

def test_pendientes_refleja_el_store(client):
    assert client.get("/ce/pendientes").json() == {"pendientes": []}
    config_store.save_envio_pendiente(RFC, "ce", ["/a/x.zip"], error="timeout")
    body = client.get("/ce/pendientes", params={"rfc": RFC}).json()
    assert len(body["pendientes"]) == 1
    assert body["pendientes"][0]["rfc"] == RFC


def test_reanudar_sin_pendientes_es_404(client):
    r = client.post("/ce/reanudar", json={"rfc": RFC})
    assert r.status_code == 404


# --- /ce/inventario, /ce/subir -----------------------------------------------

def test_inventario_devuelve_fichas_sin_portal(client, tmp_path):
    r = client.post("/ce/inventario", json={"archivos": [str(tmp_path)]})
    assert r.status_code == 400          # carpeta sin .zip
    _zip_valido(tmp_path)
    r = client.post("/ce/inventario", json={"archivos": [str(tmp_path)]})
    assert r.status_code == 200
    ficha = r.json()["archivos"][0]
    assert ficha["tipo"] == "BN" and ficha["problemas"] == []


def test_subir_guarda_y_revisa(client, tmp_path):
    z = _zip_valido(tmp_path)
    with open(z, "rb") as fh:
        r = client.post("/ce/subir", files=[("archivos", (z.name, fh, "application/zip"))])
    assert r.status_code == 200
    ficha = r.json()["archivos"][0]
    assert ficha["problemas"] == [] and ficha["rfc"] == RFC
    # quedó en la carpeta de paso del agente, no en la ruta original
    assert "ce_subidos" in ficha["path"]


def test_subir_rechaza_lo_que_no_es_zip(client):
    r = client.post("/ce/subir", files=[("archivos", ("x.txt", b"hola", "text/plain"))])
    assert r.status_code == 400


def test_subir_no_escapa_de_la_carpeta(client, tmp_path):
    z = _zip_valido(tmp_path)
    r = client.post("/ce/subir", files=[
        ("archivos", ("../../" + z.name, z.read_bytes(), "application/zip"))])
    assert r.status_code == 200
    assert ".." not in r.json()["archivos"][0]["path"]


# --- /ce/acuse y /ce/acuses (lectura) ----------------------------------------

@pytest.fixture
def empresa_ce(tmp_path, monkeypatch):
    real = config_store.get_empresa
    monkeypatch.setattr(
        config_store, "get_empresa",
        lambda rfc: {"rfc": RFC} if rfc == RFC else real(rfc))
    monkeypatch.setattr("sat_descarga.api.routers.ce._descargas_base",
                        lambda: tmp_path / "descargas")
    return tmp_path / "descargas" / "ce" / RFC / "2026"


def test_acuse_sirve_el_pdf_derivado_del_folio(client, empresa_ce):
    empresa_ce.mkdir(parents=True)
    (empresa_ce / "AR_000220260101.pdf").write_bytes(b"%PDF-1.4 x")
    r = client.get("/ce/acuse", params={"rfc": RFC, "anio": 2026,
                                        "folio": "000220260101", "tipo": "AR"})
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    r = client.get("/ce/acuse", params={"rfc": RFC, "anio": 2026,
                                        "folio": "000220260101", "tipo": "AP"})
    assert r.status_code == 404


@pytest.mark.parametrize("folio", ["../../etc/passwd", "12", "abc123456"])
def test_acuse_folio_invalido_es_400(client, empresa_ce, folio):
    r = client.get("/ce/acuse", params={"rfc": RFC, "anio": 2026, "folio": folio})
    assert r.status_code == 400


def test_acuse_empresa_inexistente_es_404(client):
    r = client.get("/ce/acuse", params={"rfc": "XAXX010101000", "anio": 2026,
                                        "folio": "000220260101"})
    assert r.status_code == 404


def test_acuses_guardados_marca_que_pdf_existen(client, empresa_ce):
    from sat_descarga.api.routers.ce import _guardar_consulta
    empresa_ce.mkdir(parents=True)
    (empresa_ce / "AR_000220260101.pdf").write_bytes(b"%PDF-")
    _guardar_consulta(RFC, 2026, [{
        "folio": "000220260101", "estatus": "Recibido", "periodo": "Enero",
        "acuse_recepcion": "/ruta/del/agente.pdf"}])
    body = client.get("/ce/acuses", params={"rfc": RFC, "anio": 2026}).json()
    fila = body["filas"][0]
    assert body["consultado_en"] and fila["tiene_ar"] and not fila["tiene_ap"]
    assert "acuse_recepcion" not in fila     # rutas del agente no salen al cliente


def test_acuses_guardados_sin_consulta_previa(client, empresa_ce):
    body = client.get("/ce/acuses", params={"rfc": RFC, "anio": 2026}).json()
    assert body == {"consultado_en": None, "filas": []}


# --- /diot/presentar: vallas -------------------------------------------------

def test_presentar_sin_estimulos_es_contrato(client, tmp_path):
    """La limitante de estímulos NO es una nota: sin sin_estimulos=true → 400,
    para que la UI esté obligada a preguntárselo al usuario."""
    txt = tmp_path / "diot.txt"
    txt.write_text("x")
    r = client.post("/diot/presentar", json={
        "rfc": RFC, "ejercicio": 2026, "periodo": 7,
        "txt_path": str(txt), "solo_validar": True})
    assert r.status_code == 400
    assert "estímulos" in r.json()["detail"]


def test_presentar_sin_confirmar_es_400(client, tmp_path):
    txt = tmp_path / "diot.txt"
    txt.write_text("x")
    r = client.post("/diot/presentar", json={
        "rfc": RFC, "ejercicio": 2026, "periodo": 7,
        "txt_path": str(txt), "sin_estimulos": True})
    assert r.status_code == 400
    assert "confirmar" in r.json()["detail"]


def test_presentar_periodo_invalido_es_400(client, tmp_path):
    txt = tmp_path / "diot.txt"
    txt.write_text("x")
    r = client.post("/diot/presentar", json={
        "rfc": RFC, "ejercicio": 2026, "periodo": 13,
        "txt_path": str(txt), "sin_estimulos": True, "solo_validar": True})
    assert r.status_code == 400


def test_presentar_sin_txt_es_400(client):
    r = client.post("/diot/presentar", json={
        "rfc": RFC, "ejercicio": 2026, "periodo": 7,
        "sin_estimulos": True, "solo_validar": True})
    assert r.status_code == 400
    assert "txt_path" in r.json()["detail"]
