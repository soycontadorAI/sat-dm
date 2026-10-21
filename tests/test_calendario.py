"""Cuadro de control local: migración 011, sincronización, API y alimentación."""

import io
import sqlite3
import zipfile
from datetime import date

import pytest

from sat_descarga.cli import config_store
from sat_descarga.procesador import calendario, parse_cfdi
from sat_descarga.procesador import db as db_mod

MI_RFC = "BBB020202BBB"
OTRO = "AAA010101AAA"
HOY = date(2026, 10, 13)


def _xml(uuid, fecha="2026-03-04T10:00:00", emisor=OTRO, receptor=MI_RFC, total=116):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0" Serie="A" Folio="10" Fecha="{fecha}" Sello="..." NoCertificado="000"
    Certificado="..." SubTotal="100" Moneda="MXN" Total="{total}"
    TipoDeComprobante="I" Exportacion="01" MetodoPago="PUE" FormaPago="03"
    LugarExpedicion="64000">
  <cfdi:Emisor Rfc="{emisor}" Nombre="EMISORA SA DE CV" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="{receptor}" Nombre="RECEPTORA" DomicilioFiscalReceptor="64000"
                 RegimenFiscalReceptor="612" UsoCFDI="G03"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="01010101" Cantidad="1" ClaveUnidad="ACT"
                   Descripcion="Servicio" ValorUnitario="100" Importe="100" ObjetoImp="01"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="{uuid}"
        FechaTimbrado="{fecha}" RfcProvCertif="SAT970701NN3" SelloCFD="..."
        NoCertificadoSAT="000" SelloSAT="..."/>
  </cfdi:Complemento>
</cfdi:Comprobante>""".encode()


def _uuid(n):
    return f"AAAAAAAA-0000-0000-0000-{n:012d}"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "DEFAULT_DB_PATH", tmp_path / "procesador.db")
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "EFIRMA_DIR", tmp_path / "efirma")
    monkeypatch.setattr(calendario, "hoy", lambda: HOY)
    db_mod.resetear_singleton_para_tests()
    inst = db_mod.abrir_db()
    yield inst
    inst.close()
    db_mod.resetear_singleton_para_tests()


def _agregar(db, n, con_xml=True, **kw):
    xml = _xml(_uuid(n), **kw)
    cfdi = parse_cfdi(xml)
    db.agregar([cfdi], mi_rfc=MI_RFC, xmls={cfdi.uuid: xml} if con_xml else None)
    return cfdi.uuid


def _sol(id_, desde, hasta, estado="solicitada", tipo="CFDI · emitidos", dir_="E",
         ts="2026-10-10T10:00:00", **extra):
    config_store.save_solicitud(MI_RFC, id_, desde, hasta, tipo, estado=estado,
                                tipo_comprobante=dir_)
    # Fija el timestamp para que el orden sea determinista.
    import json
    ruta = config_store._solicitudes_path(MI_RFC)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    for s in datos["solicitudes"]:
        if s["id_solicitud"] == id_:
            s["timestamp"] = ts
            s.update(extra)
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def _fila(f, d):
    return calendario.filas(MI_RFC, date.fromisoformat(f), date.fromisoformat(f)).get((f, d))


# ---------------------------------------------------------------------------
# 1. Migración
# ---------------------------------------------------------------------------


def test_db_nueva_queda_en_version_11_con_la_tabla(db):
    assert db_mod.schema_version_actual() >= 11
    assert db.meta_get("schema_version") == str(db_mod.schema_version_actual())
    with db.cursor() as cur:
        cols = {r[1] for r in cur.execute("PRAGMA table_info(descarga_dias)")}
    assert {"mi_rfc", "fecha", "direccion", "estado", "total_bd", "total_sat",
            "ultima_solicitud_id", "error_codigo", "error_mensaje", "intentos",
            "actualizado_en"} <= cols


def test_db_en_version_10_migra_a_11_sin_perder_cfdis(tmp_path):
    ruta = tmp_path / "vieja.db"
    # Una DB real en 10: se aplican las migraciones hasta la 010 a mano.
    conn = sqlite3.connect(str(ruta))
    conn.execute("CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT)")
    for version, path in db_mod._listar_migraciones():
        if version > 10:
            break
        conn.executescript(path.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO _meta VALUES ('schema_version', '10')")
    conn.execute(
        "INSERT INTO cfdis (uuid, mi_rfc, fecha, emisor_rfc, receptor_rfc) "
        "VALUES ('U1', ?, '2026-03-04T10:00:00', ?, ?)", (MI_RFC, OTRO, MI_RFC))
    conn.commit()
    conn.close()

    inst = db_mod.ProcesadorDB(ruta)
    try:
        assert inst.meta_get("schema_version") == str(db_mod.schema_version_actual())
        with inst.cursor() as cur:
            assert cur.execute("SELECT COUNT(*) FROM cfdis").fetchone()[0] == 1
            assert cur.execute("SELECT COUNT(*) FROM descarga_dias").fetchone()[0] == 0
    finally:
        inst.close()


# ---------------------------------------------------------------------------
# 2. Regla de transición
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("actual,nuevo,esperado", [
    (None, "en_proceso", "en_proceso"),
    (None, "provisional", "provisional"),
    (None, "pendiente", None),
    ("pendiente", "error", "error"),
    ("en_proceso", "provisional", "provisional"),
    ("en_proceso", "error", "error"),
    ("error", "en_proceso", "en_proceso"),
    ("error", "provisional", "provisional"),
    ("error", "pendiente", "error"),
    ("provisional", "en_proceso", "provisional"),
    ("provisional", "error", "provisional"),
    ("provisional", "pendiente", "provisional"),
    ("provisional", "consolidado", "consolidado"),
    ("provisional", "diferencia", "diferencia"),
    ("consolidado", "provisional", "consolidado"),
    ("consolidado", "diferencia", "consolidado"),
    ("diferencia", "consolidado", "diferencia"),
    ("diferencia", "error", "diferencia"),
])
def test_siguiente(actual, nuevo, esperado):
    assert calendario._siguiente(actual, nuevo) == esperado


# ---------------------------------------------------------------------------
# 3. sincronizar
# ---------------------------------------------------------------------------


def test_pendiente_pasa_a_en_proceso(db):
    _sol("S1", "2026-03-01", "2026-03-03")
    assert calendario.sincronizar(MI_RFC) == {"cambiadas": 3}
    f = _fila("2026-03-02", "E")
    assert f["estado"] == "en_proceso" and f["ultima_solicitud_id"] == "S1"
    assert _fila("2026-03-02", "R") is None


@pytest.mark.parametrize("estado", ["solicitada", "1", "2", "3"])
def test_estados_en_cola_son_en_proceso(db, estado):
    _sol("S1", "2026-03-01", "2026-03-01", estado=estado)
    calendario.sincronizar(MI_RFC)
    assert _fila("2026-03-01", "E")["estado"] == "en_proceso"


def test_descargada_es_provisional_con_total_del_indice(db):
    _agregar(db, 1, emisor=MI_RFC, receptor=OTRO)
    _agregar(db, 2, emisor=MI_RFC, receptor=OTRO)
    _sol("S1", "2026-03-04", "2026-03-04", estado="descargada")
    calendario.sincronizar(MI_RFC)
    f = _fila("2026-03-04", "E")
    assert f["estado"] == "provisional" and f["total_bd"] == 2


@pytest.mark.parametrize("estado,cod,esperado", [("4", None, "4"), ("5", "5002", "5002"),
                                                 ("vencida", None, "vencida")])
def test_estados_de_falla_son_error(db, estado, cod, esperado):
    extra = {"mensaje": "Falló", **({"cod_estatus": cod} if cod else {})}
    _sol("S1", "2026-03-01", "2026-03-01", estado=estado, **extra)
    calendario.sincronizar(MI_RFC)
    f = _fila("2026-03-01", "E")
    assert f["estado"] == "error"
    assert f["error_codigo"] == esperado and f["error_mensaje"] == "Falló"
    assert f["intentos"] == 1


def test_5004_es_provisional_en_cero(db):
    _sol("S1", "2026-03-01", "2026-03-02", estado="5", codigo_estado_solicitud="5004")
    _sol("S2", "2026-03-05", "2026-03-05", estado="5",
         mensaje="No se encontró la información")
    calendario.sincronizar(MI_RFC)
    for dia in ("2026-03-01", "2026-03-02", "2026-03-05"):
        f = _fila(dia, "E")
        assert f["estado"] == "provisional" and f["total_bd"] == 0


def test_el_5004_de_la_verificacion_no_es_sin_informacion(db):
    # CodEstatus 5004 es de la verificación misma: "no se encontró la solicitud".
    _sol("S1", "2026-03-01", "2026-03-01", estado="5", cod_estatus="5004",
         mensaje="No se encontró la solicitud")
    calendario.sincronizar(MI_RFC)
    f = _fila("2026-03-01", "E")
    assert f["estado"] == "error" and f["error_codigo"] == "5004"


def test_descargada_gana_a_error_en_el_mismo_dia(db):
    _sol("S1", "2026-03-01", "2026-03-01", estado="5", mensaje="Rechazada",
         ts="2026-10-09T10:00:00")
    _sol("S2", "2026-03-01", "2026-03-01", estado="descargada", ts="2026-10-10T10:00:00")
    calendario.sincronizar(MI_RFC)
    f = _fila("2026-03-01", "E")
    assert f["estado"] == "provisional" and f["error_codigo"] is None
    assert f["ultima_solicitud_id"] == "S2"


def test_error_mas_reciente_gana_entre_errores(db):
    _sol("S1", "2026-03-01", "2026-03-01", estado="4", mensaje="viejo", ts="2026-10-01T10:00:00")
    _sol("S2", "2026-03-01", "2026-03-01", estado="5", mensaje="nuevo", cod_estatus="5002",
         ts="2026-10-02T10:00:00")
    calendario.sincronizar(MI_RFC)
    f = _fila("2026-03-01", "E")
    assert (f["error_codigo"], f["error_mensaje"], f["intentos"]) == ("5002", "nuevo", 2)


def test_dia_solo_indice_es_provisional(db):
    _agregar(db, 1)  # recibido, sin solicitud alguna
    assert calendario.sincronizar(MI_RFC) == {"cambiadas": 1}
    f = _fila("2026-03-04", "R")
    assert f["estado"] == "provisional" and f["total_bd"] == 1


def test_error_con_datos_en_el_indice_es_provisional(db):
    _agregar(db, 1, emisor=MI_RFC, receptor=OTRO)
    _sol("S1", "2026-03-04", "2026-03-04", estado="4", mensaje="x")
    calendario.sincronizar(MI_RFC)
    assert _fila("2026-03-04", "E")["estado"] == "provisional"


def test_dias_futuros_se_recortan(db):
    _sol("S1", "2026-10-12", "2026-10-20")
    assert calendario.sincronizar(MI_RFC) == {"cambiadas": 2}
    assert _fila("2026-10-14", "E") is None


def test_metadata_se_ignora(db):
    _sol("S1", "2026-03-01", "2026-03-31", tipo="Metadata · emitidos")
    _sol("S2", "2026-03-01", "2026-03-31", tipo="metadata · recibidos", dir_="R")
    assert calendario.sincronizar(MI_RFC) == {"cambiadas": 0}


def test_registro_viejo_infiere_la_direccion_del_tipo(db):
    config_store.save_solicitud(MI_RFC, "S1", "2026-03-01", "2026-03-01", "CFDI · recibidos")
    config_store.save_solicitud(MI_RFC, "S2", "2026-03-01", "2026-03-01", "CFDI")
    calendario.sincronizar(MI_RFC)
    assert _fila("2026-03-01", "R")["estado"] == "en_proceso"
    assert _fila("2026-03-01", "E") is None  # S2 no tiene dirección: se omite


def test_consolidado_y_diferencia_no_se_degradan(db):
    calendario.marcar(MI_RFC, date(2026, 3, 1), date(2026, 3, 1), "E", "consolidado",
                      total_sat=0, forzar=True)
    calendario.marcar(MI_RFC, date(2026, 3, 2), date(2026, 3, 2), "E", "diferencia",
                      total_sat=5, forzar=True)
    _sol("S1", "2026-03-01", "2026-03-02", estado="4", mensaje="x")
    _sol("S2", "2026-03-01", "2026-03-02", estado="descargada")
    calendario.sincronizar(MI_RFC)
    assert _fila("2026-03-01", "E")["estado"] == "consolidado"
    assert _fila("2026-03-02", "E")["estado"] == "diferencia"
    assert _fila("2026-03-02", "E")["total_sat"] == 5


def test_sincronizar_es_idempotente(db):
    _agregar(db, 1)
    _sol("S1", "2026-03-01", "2026-03-05")
    assert calendario.sincronizar(MI_RFC)["cambiadas"] > 0
    assert calendario.sincronizar(MI_RFC) == {"cambiadas": 0}


def test_total_bd_se_refresca_cuando_entra_un_cfdi(db):
    _sol("S1", "2026-03-04", "2026-03-04", estado="descargada")
    calendario.sincronizar(MI_RFC)
    assert _fila("2026-03-04", "R") is None
    _agregar(db, 1)
    assert calendario.sincronizar(MI_RFC) == {"cambiadas": 1}
    assert _fila("2026-03-04", "R")["total_bd"] == 1


def test_marcar_valida_estado_y_direccion(db):
    with pytest.raises(ValueError):
        calendario.marcar(MI_RFC, HOY, HOY, "X", "provisional")
    with pytest.raises(ValueError):
        calendario.marcar(MI_RFC, HOY, HOY, "E", "raro")


# ---------------------------------------------------------------------------
# 4. Conteo
# ---------------------------------------------------------------------------


def test_autofactura_cuenta_en_emitidos_y_recibidos(db):
    _agregar(db, 1, emisor=MI_RFC, receptor=MI_RFC)
    c = calendario._conteos(MI_RFC)
    assert c[("2026-03-04", "E")] == 1 and c[("2026-03-04", "R")] == 1


def test_cancelados_no_cuentan(db):
    u = _agregar(db, 1)
    _agregar(db, 2)
    db.actualizar_estado_sat(u, "Cancelado")
    assert calendario._conteos(MI_RFC) == {("2026-03-04", "R"): 1}


def test_fechas_vacias_o_mal_formadas_se_ignoran(db):
    _agregar(db, 1)
    with db.transaccion() as conn:
        conn.execute("UPDATE cfdis SET fecha = 'basura' WHERE uuid = ?", (_uuid(1),))
    assert calendario._conteos(MI_RFC) == {}


# ---------------------------------------------------------------------------
# 5. anio() y dia()
# ---------------------------------------------------------------------------


def test_anio_tiene_la_forma_del_contrato(db):
    _agregar(db, 1, emisor=MI_RFC, receptor=OTRO)
    _sol("S1", "2026-03-04", "2026-03-04", estado="descargada")
    _sol("S2", "2026-03-04", "2026-03-04", estado="5", dir_="R", mensaje="Rechazada",
         tipo="CFDI · recibidos", cod_estatus="5002")
    _sol("S3", "2025-12-31", "2025-12-31", estado="descargada")
    calendario.sincronizar(MI_RFC)

    r = calendario.anio(MI_RFC, 2026)
    assert set(r) == {"rfc", "anio", "hoy", "anios", "dias", "resumen"}
    assert r["rfc"] == MI_RFC and r["anio"] == 2026 and r["hoy"] == "2026-10-13"
    assert r["anios"] == [2025, 2026]
    assert list(r["dias"]) == ["2026-03-04"]
    e = r["dias"]["2026-03-04"]["E"]
    assert e["estado"] == "provisional" and e["total_bd"] == 1
    assert set(e) == {"estado", "total_bd", "actualizado_en"}  # sin nulos ni intentos 0
    rr = r["dias"]["2026-03-04"]["R"]
    assert rr["estado"] == "error" and rr["error_codigo"] == "5002"
    assert rr["error_mensaje"] == "Rechazada" and rr["intentos"] == 1
    assert "total_sat" not in rr

    dias_hasta_hoy = (HOY - date(2026, 1, 1)).days + 1
    assert set(r["resumen"]) == {"E", "R"}
    assert set(r["resumen"]["E"]) == set(calendario.ESTADOS)
    assert r["resumen"]["E"]["provisional"] == 1
    assert r["resumen"]["E"]["pendiente"] == dias_hasta_hoy - 1
    assert r["resumen"]["R"]["error"] == 1
    assert sum(r["resumen"]["R"].values()) == dias_hasta_hoy


def test_anio_pasado_completo_y_futuro_vacio(db):
    assert sum(calendario.anio(MI_RFC, 2025)["resumen"]["E"].values()) == 365
    futuro = calendario.anio(MI_RFC, 2027)
    assert futuro["dias"] == {}
    assert sum(futuro["resumen"]["E"].values()) == 0
    assert futuro["anios"] == [2026]


def test_dia_tiene_la_forma_del_contrato(db):
    _agregar(db, 1, emisor=MI_RFC, receptor=OTRO)
    _agregar(db, 2, emisor=MI_RFC, receptor=MI_RFC, fecha="2026-03-04T09:00:00")
    _agregar(db, 3)
    _agregar(db, 4, fecha="2026-03-05T09:00:00")
    _sol("S1", "2026-03-01", "2026-03-31", estado="descargada", numero_cfdis=120)
    _sol("S2", "2026-04-01", "2026-04-30", estado="descargada")
    _sol("S3", "2026-03-01", "2026-03-31", tipo="Metadata · emitidos")
    calendario.sincronizar(MI_RFC)

    r = calendario.dia(MI_RFC, date(2026, 3, 4))
    assert set(r) == {"rfc", "fecha", "E", "R", "solicitudes", "cfdis", "cfdis_total"}
    assert r["E"]["estado"] == "provisional" and r["E"]["total_bd"] == 2
    assert "actualizado_en" in r["E"]
    assert r["R"]["total_bd"] == 2  # autofactura + el recibido
    assert [s["id_solicitud"] for s in r["solicitudes"]] == ["S1"]
    assert set(r["solicitudes"][0]) == {"id_solicitud", "tipo_comprobante", "fecha_inicio",
                                        "fecha_fin", "estado", "mensaje", "numero_cfdis",
                                        "timestamp"}
    # La autofactura sale en las dos listas, como en los conteos (E + R = 4).
    assert r["cfdis_total"] == 4
    assert [c["direccion"] for c in r["cfdis"]] == ["E", "E", "R", "R"]
    assert _uuid(2) in {c["uuid"] for c in r["cfdis"] if c["direccion"] == "R"}
    assert set(r["cfdis"][0]) == {"uuid", "direccion", "tipo", "serie", "folio", "fecha",
                                  "emisor_rfc", "emisor_nombre", "receptor_rfc",
                                  "receptor_nombre", "total", "moneda", "estado_sat"}


def test_dia_sin_fila_es_pendiente_y_sin_datos(db):
    r = calendario.dia(MI_RFC, date(2026, 3, 4))
    assert r["E"] == {"estado": "pendiente", "total_bd": 0}
    assert r["R"] == {"estado": "pendiente", "total_bd": 0}
    assert r["cfdis"] == [] and r["cfdis_total"] == 0 and r["solicitudes"] == []


def test_dia_limita_la_lista_a_200(db):
    n = calendario.LIMITE_CFDIS_DIA + 5
    cfdis = [parse_cfdi(_xml(_uuid(i))) for i in range(n)]
    db.agregar(cfdis, mi_rfc=MI_RFC)
    r = calendario.dia(MI_RFC, date(2026, 3, 4))
    assert len(r["cfdis"]) == calendario.LIMITE_CFDIS_DIA
    assert r["cfdis_total"] == n


def test_xml_del_mes(db):
    u1 = _agregar(db, 1)
    u2 = _agregar(db, 2, con_xml=False)
    _agregar(db, 3, emisor=MI_RFC, receptor=MI_RFC)
    _agregar(db, 4, fecha="2026-04-01T00:00:00")
    todos = dict(calendario.xml_del_mes(MI_RFC, 2026, 3))
    assert len(todos) == 3 and todos[u2] is None and todos[u1].startswith(b"<?xml")
    assert len(dict(calendario.xml_del_mes(MI_RFC, 2026, 3, "E"))) == 1
    assert len(dict(calendario.xml_del_mes(MI_RFC, 2026, 3, "R"))) == 3


# ---------------------------------------------------------------------------
# 6. API
# ---------------------------------------------------------------------------


@pytest.fixture()
def cliente(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from sat_descarga.api import server

    config_store.add_empresa_ciec(MI_RFC, "Empresa", "ciec123")
    yield TestClient(server.app)
    server._limpiar_session()


def test_api_anio(cliente, db):
    _agregar(db, 1)
    r = cliente.get(f"/calendario/{MI_RFC}", params={"anio": 2026})
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j) == {"rfc", "anio", "hoy", "anios", "dias", "resumen"}
    assert j["dias"]["2026-03-04"]["R"]["estado"] == "provisional"  # sincronizó el índice
    # Sin anio: el de hoy().
    assert cliente.get(f"/calendario/{MI_RFC}").json()["anio"] == 2026


def test_api_rfc_invalido_y_fuera_del_catalogo(cliente):
    assert cliente.get("/calendario/XX").status_code == 400
    r = cliente.get("/calendario/CCC030303CCC")
    assert r.status_code == 404
    assert r.json()["detail"] == "Esa empresa no está en el catálogo."
    assert cliente.get("/calendario/CCC030303CCC/dia", params={"fecha": "2026-03-04"}).status_code == 404
    assert cliente.get("/calendario/CCC030303CCC/zip", params={"anio": 2026, "mes": 3}).status_code == 404


def test_api_dia(cliente, db):
    _agregar(db, 1)
    r = cliente.get(f"/calendario/{MI_RFC}/dia", params={"fecha": "2026-03-04"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["fecha"] == "2026-03-04" and j["cfdis_total"] == 1
    assert j["R"]["total_bd"] == 1 and j["E"]["estado"] == "pendiente"


def test_api_zip(cliente, db):
    u1 = _agregar(db, 1)
    u2 = _agregar(db, 2, con_xml=False)
    _agregar(db, 3, emisor=MI_RFC, receptor=OTRO)
    r = cliente.get(f"/calendario/{MI_RFC}/zip", params={"anio": 2026, "mes": 3})
    assert r.status_code == 200, r.text
    assert f"cfdi_{MI_RFC}_2026-03.zip" in r.headers["content-disposition"]
    assert r.headers["x-total-xml"] == "2" and r.headers["x-sin-xml"] == "1"
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert sorted(zf.namelist()) == sorted([f"{u1}.xml", f"{_uuid(3)}.xml", "sin_xml.txt"])
        assert zf.read("sin_xml.txt").decode().split() == [u2]
        assert zf.read(f"{u1}.xml") == _xml(_uuid(1))

    emitidos = cliente.get(f"/calendario/{MI_RFC}/zip",
                           params={"anio": 2026, "mes": 3, "direccion": "E"})
    assert "_emitidos.zip" in emitidos.headers["content-disposition"]
    assert emitidos.headers["x-total-xml"] == "1" and emitidos.headers["x-sin-xml"] == "0"


def test_api_zip_mes_vacio_y_mes_invalido(cliente):
    r = cliente.get(f"/calendario/{MI_RFC}/zip", params={"anio": 2026, "mes": 5})
    assert r.status_code == 404
    assert r.json()["detail"] == "No hay CFDI de ese mes en la base."
    assert cliente.get(f"/calendario/{MI_RFC}/zip", params={"anio": 2026, "mes": 13}).status_code == 400


# ---------------------------------------------------------------------------
# 7. Alimentación
# ---------------------------------------------------------------------------


def test_update_solicitud_guarda_cod_estatus(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    config_store.save_solicitud(MI_RFC, "S1", "2026-03-01", "2026-03-01", "CFDI · emitidos")
    config_store.update_solicitud(MI_RFC, "S1", "5", mensaje="x", cod_estatus="5000",
                                  codigo_estado_solicitud="5004")
    sol = config_store.get_solicitud(MI_RFC, "S1")
    assert sol["cod_estatus"] == "5000" and sol["codigo_estado_solicitud"] == "5004"


def test_poller_sincroniza_el_calendario(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from sat_descarga.api import poller

    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.delenv("SAT_DM_SIN_INDEXADO")  # el calendario sigue al indexado automático
    config_store.save_solicitud(MI_RFC, "S1", "2026-03-01", "2026-03-01", "CFDI · emitidos",
                                tipo_comprobante="E")
    llamadas = []
    monkeypatch.setattr(calendario, "sincronizar", lambda rfc: llamadas.append(rfc))
    # Pendiente reciente, sin cambios en la pasada: no se recalcula el calendario.
    poller._procesar_empresa(MI_RFC, {"rfc": MI_RFC, "metodos": []})
    assert llamadas == []

    # Pasó de 72 h y el poller la vence: ese cambio sí llega al calendario, aunque
    # ya no quede nada pendiente (antes el `return` temprano se lo saltaba).
    import json
    ruta = config_store._solicitudes_path(MI_RFC)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["solicitudes"][0]["timestamp"] = "2026-01-01T00:00:00"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    poller._procesar_empresa(MI_RFC, {"rfc": MI_RFC, "metodos": []})
    assert config_store.get_solicitud(MI_RFC, "S1")["estado"] == "vencida"
    assert llamadas == [MI_RFC]

    # Sin nada pendiente no hay trabajo y no se sincroniza.
    llamadas.clear()
    poller._procesar_empresa(MI_RFC, {"rfc": MI_RFC, "metodos": []})
    assert llamadas == []


def test_poller_no_cae_si_el_calendario_falla(monkeypatch):
    pytest.importorskip("fastapi")
    from sat_descarga.api import poller

    def _falla(rfc):
        raise RuntimeError("boom")

    monkeypatch.setattr(calendario, "sincronizar", _falla)
    poller._sincronizar_calendario(MI_RFC)  # no lanza


def test_registrar_descarga_con_rango_marca_provisional(db, monkeypatch):
    pytest.importorskip("fastapi")
    from sat_descarga.api import state

    from sat_descarga.procesador import indexar as indexar_mod

    monkeypatch.setattr(config_store, "registrar_descarga", lambda *a, **k: None)
    monkeypatch.delenv("SAT_DM_SIN_INDEXADO")
    monkeypatch.setattr(indexar_mod, "indexar_descarga", lambda *a, **k: None)
    state._registrar_descarga(MI_RFC, "ciec", "cfdi", ruta="x",
                              rango=(date(2026, 3, 1), date(2026, 3, 3)),
                              direcciones=["E", "R"])
    for d in ("E", "R"):
        for dia in ("2026-03-01", "2026-03-03"):
            assert _fila(dia, d)["estado"] == "provisional"

    # Sin rango (descarga truncada) no se marca nada nuevo.
    state._registrar_descarga(MI_RFC, "ciec", "cfdi", ruta="x")
    assert len(calendario.filas(MI_RFC, date(2026, 1, 1), HOY)) == 6


def test_helpers_de_descarga_truncada_y_direcciones():
    pytest.importorskip("fastapi")
    from sat_descarga.api import state

    assert state.direcciones_de("E") == ["E"]
    assert state.direcciones_de("R") == ["R"]
    assert state.direcciones_de("RE") == ["E", "R"]
    # Misma regla que el portal: "RECIBIDOS" no cuenta como emitidos por traer una E.
    assert state.direcciones_de("RECIBIDOS") == ["R"]
    assert state.direcciones_de("emitidos") == ["E"]
    assert state.direcciones_de("AMBOS") == ["E", "R"]
    assert state.direcciones_de("") == ["E", "R"]


def test_hoy_es_la_fecha_de_la_ciudad_de_mexico(monkeypatch):
    # 03:00 UTC del 14 de octubre = 21:00 del 13 en la Ciudad de México.
    from datetime import datetime as _dt, timezone as _tz

    from sat_descarga.procesador import calendario as cal

    class _Reloj(_dt):
        @classmethod
        def now(cls, tz=None):
            base = _dt(2026, 10, 14, 3, 0, tzinfo=_tz.utc)
            return base.astimezone(tz) if tz else base.replace(tzinfo=None)

    monkeypatch.setattr(cal, "datetime", _Reloj)
    assert cal.hoy().isoformat() == "2026-10-13"



def test_5004_como_lo_manda_el_sat_real(db):
    # VerificaSolicitud: EstadoSolicitud=5, CodEstatus=5000 (la verificación salió
    # bien) y el 5004 en CodigoEstadoSolicitud, con Mensaje "Solicitud Aceptada".
    _sol("S1", "2026-03-01", "2026-03-02", estado="5", cod_estatus="5000",
         codigo_estado_solicitud="5004", mensaje="Solicitud Aceptada")
    calendario.sincronizar(MI_RFC)
    assert _fila("2026-03-01", "E")["estado"] == "provisional"
    assert _fila("2026-03-02", "E")["total_bd"] == 0


def test_el_codigo_de_error_es_el_de_la_solicitud(db):
    _sol("S1", "2026-03-01", "2026-03-01", estado="5", cod_estatus="5000",
         codigo_estado_solicitud="5003", mensaje="Tope máximo")
    calendario.sincronizar(MI_RFC)
    fila = _fila("2026-03-01", "E")
    assert fila["estado"] == "error" and fila["error_codigo"] == "5003"


def test_borrar_la_solicitud_regresa_el_dia_a_por_descargar(db):
    _sol("S1", "2026-03-01", "2026-03-02")
    calendario.sincronizar(MI_RFC)
    assert _fila("2026-03-01", "E")["estado"] == "en_proceso"
    config_store.delete_solicitud(MI_RFC, "S1")
    calendario.sincronizar(MI_RFC)
    assert _fila("2026-03-01", "E")["estado"] == "pendiente"
    assert "2026-03-01" not in calendario.anio(MI_RFC, 2026)["dias"]
    # Un error que puso el planificador sin solicitud (p. ej. 5002) no se toca.
    calendario.marcar(MI_RFC, date(2026, 3, 5), date(2026, 3, 5), "E", "error",
                      error_codigo="5002", error_mensaje="Agotadas")
    calendario.sincronizar(MI_RFC)
    assert _fila("2026-03-05", "E")["estado"] == "error"


def test_el_indexado_de_una_descarga_pone_al_dia_el_calendario(db, tmp_path, monkeypatch):
    from sat_descarga.procesador import indexar as indexar_mod

    carpeta = tmp_path / "descarga"
    carpeta.mkdir()
    (carpeta / "a.xml").write_bytes(_xml(_uuid(1)))
    indexar_mod._indexar_registrando(MI_RFC, str(carpeta), "sat_ws")
    fila = _fila("2026-03-04", "R")
    assert fila["estado"] == "provisional" and fila["total_bd"] == 1



def test_con_el_indexado_apagado_las_descargas_no_tocan_el_calendario(db, monkeypatch):
    pytest.importorskip("fastapi")
    from sat_descarga.api import poller, state

    monkeypatch.setenv("SAT_DM_SIN_INDEXADO", "1")
    monkeypatch.setattr(config_store, "registrar_descarga", lambda *a, **k: None)
    llamadas = []
    monkeypatch.setattr(calendario, "sincronizar", lambda rfc: llamadas.append(rfc))
    state._registrar_descarga(MI_RFC, "ciec", "cfdi", ruta="x",
                              rango=(date(2026, 3, 1), date(2026, 3, 3)), direcciones=["E"])
    poller._sincronizar_calendario(MI_RFC)
    assert calendario.filas(MI_RFC, date(2026, 1, 1), HOY) == {} and llamadas == []



# ---------------------------------------------------------------------------
# Segunda revisión: portal completo, 5004 heredado, intentos, carreras, rango
# ---------------------------------------------------------------------------


def _cliente_portal(monkeypatch, filas_por_dia, falla=()):
    """CIECClient con la página simulada: `filas_por_dia` = filas que regresa
    cada búsqueda; los UUID en `falla` no se pueden bajar."""
    from sat_descarga.portal import cfdi as portal_cfdi

    cliente = portal_cfdi.CIECClient(MI_RFC, "x")
    respuestas = iter(filas_por_dia)
    monkeypatch.setattr(cliente, "_buscar_emisor", lambda page, fi, ff: None)
    monkeypatch.setattr(cliente, "_buscar_receptor_dia", lambda page, dia: None)
    monkeypatch.setattr(cliente, "_extraer_filas", lambda page: next(respuestas, []))

    def _bajar(page, url, dest):
        if dest.stem in falla:
            return False
        dest.write_bytes(b"<x/>")
        return True

    monkeypatch.setattr(cliente, "_descargar_xml", _bajar)
    cliente._completa = True
    return cliente


def test_descarga_del_portal_completa_e_incompleta(monkeypatch, tmp_path):
    from sat_descarga.portal.cfdi import MAX_FILAS_CONSULTA, DescargaPortal

    fila = lambda u, url="u": {"uuid": u, "url": url}
    # Todo bajó: completa.
    c = _cliente_portal(monkeypatch, [[fila("A"), fila("B")]])
    assert len(c._descargar_tipo(None, "E", HOY, HOY, tmp_path, 100)) == 2 and c._completa
    # Una fila sin URL o un XML que falla: incompleta.
    c = _cliente_portal(monkeypatch, [[fila("C", url=""), fila("D")]])
    c._descargar_tipo(None, "E", HOY, HOY, tmp_path, 100)
    assert not c._completa
    c = _cliente_portal(monkeypatch, [[fila("E"), fila("F")]], falla={"F"})
    c._descargar_tipo(None, "E", HOY, HOY, tmp_path, 100)
    assert not c._completa
    # Una consulta que llegó al máximo de filas del portal: pudo quedarse con más afuera.
    c = _cliente_portal(monkeypatch, [[fila(f"G{i}") for i in range(MAX_FILAS_CONSULTA)]])
    c._descargar_tipo(None, "E", HOY, HOY, tmp_path, 10_000)
    assert not c._completa
    # La lista de siempre, con el dato.
    lista = DescargaPortal([tmp_path / "a.xml"], completa=False)
    assert isinstance(lista, list) and len(lista) == 1 and lista.completa is False


def test_5004_guardado_antes_del_codigo_es_provisional(db):
    # Solicitudes rechazadas de antes de guardar CodigoEstadoSolicitud: con el
    # mensaje genérico de la verificación, casi siempre son el 5004.
    _sol("S1", "2026-03-01", "2026-03-01", estado="5", mensaje="Solicitud Aceptada")
    _sol("S2", "2026-03-02", "2026-03-02", estado="5", mensaje="Algo distinto")
    calendario.sincronizar(MI_RFC)
    assert _fila("2026-03-01", "E")["estado"] == "provisional"
    assert _fila("2026-03-02", "E")["estado"] == "error"


def test_un_dia_que_sana_deja_los_intentos_en_cero(db):
    _sol("S1", "2026-03-01", "2026-03-01", estado="4", ts="2026-10-01T00:00:00")
    _sol("S2", "2026-03-01", "2026-03-01", estado="vencida", ts="2026-10-02T00:00:00")
    calendario.sincronizar(MI_RFC)
    assert _fila("2026-03-01", "E")["intentos"] == 2
    _sol("S3", "2026-03-01", "2026-03-01", estado="descargada", ts="2026-10-03T00:00:00")
    calendario.sincronizar(MI_RFC)
    fila = _fila("2026-03-01", "E")
    assert fila["estado"] == "provisional" and fila["intentos"] == 0


def test_sincronizar_no_regresa_un_dia_que_se_toco_despues_de_leer_el_catalogo(db, monkeypatch):
    _sol("S1", "2026-03-01", "2026-03-01")
    calendario.sincronizar(MI_RFC)
    config_store.delete_solicitud(MI_RFC, "S1")
    leer = config_store.list_solicitudes

    def _catalogo_y_luego_otro_escribe(rfc):
        catalogo = leer(rfc)  # foto del catálogo: S1 ya no está y S2 aún no
        # Justo después, el piloto pide S2 y marca el día (otro hilo).
        calendario.marcar(MI_RFC, date(2026, 3, 1), date(2026, 3, 1), "E", "en_proceso",
                          solicitud_id="S2", forzar=True)
        return catalogo

    monkeypatch.setattr(config_store, "list_solicitudes", _catalogo_y_luego_otro_escribe)
    calendario.sincronizar(MI_RFC)
    fila = _fila("2026-03-01", "E")
    assert fila["estado"] == "en_proceso" and fila["ultima_solicitud_id"] == "S2"


def test_sincronizar_con_rango_solo_toca_esos_dias(db):
    _sol("S1", "2025-12-30", "2026-01-02")
    calendario.sincronizar(MI_RFC, date(2026, 1, 1), date(2026, 12, 31))
    assert _fila("2026-01-01", "E")["estado"] == "en_proceso"
    assert _fila("2025-12-31", "E") is None
    calendario.sincronizar(MI_RFC)
    assert _fila("2025-12-31", "E")["estado"] == "en_proceso"


def test_anios_incluye_los_del_indice_y_los_de_las_solicitudes(db):
    _agregar(db, 1, fecha="2024-05-01T10:00:00")
    _sol("S1", "2023-12-01", "2023-12-31")
    assert calendario.anio(MI_RFC, 2026)["anios"] == [2023, 2024, 2026]


def test_api_solo_sincroniza_el_anio_que_se_ve(cliente, db):
    _sol("S1", "2025-06-01", "2025-06-01")
    _sol("S2", "2026-06-01", "2026-06-01")
    cliente.get(f"/calendario/{MI_RFC}", params={"anio": 2026})
    assert _fila("2026-06-01", "E")["estado"] == "en_proceso"
    assert _fila("2025-06-01", "E") is None


def test_poller_no_sincroniza_si_la_descarga_no_cambio_nada(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from sat_descarga.api import poller

    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.delenv("SAT_DM_SIN_INDEXADO")
    config_store.save_solicitud(MI_RFC, "S1", "2026-03-01", "2026-03-01", "CFDI · emitidos",
                                estado="3", tipo_comprobante="E")
    llamadas = []
    monkeypatch.setattr(calendario, "sincronizar", lambda rfc: llamadas.append(rfc))
    monkeypatch.setattr(poller, "_fiel_de", lambda rfc: object())
    monkeypatch.setattr(poller, "obtener_token", lambda fiel: "t")
    monkeypatch.setattr(poller, "_descargar_lista", lambda rfc, fiel, sol: False)
    poller._procesar_empresa(MI_RFC, {"rfc": MI_RFC, "metodos": ["fiel"]})
    assert llamadas == []
    monkeypatch.setattr(poller, "_descargar_lista", lambda rfc, fiel, sol: True)
    poller._procesar_empresa(MI_RFC, {"rfc": MI_RFC, "metodos": ["fiel"]})
    assert llamadas == [MI_RFC]


def test_si_falla_el_token_igual_se_sincroniza_lo_vencido(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    import json

    import requests

    from sat_descarga.api import poller

    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.delenv("SAT_DM_SIN_INDEXADO")
    config_store.save_solicitud(MI_RFC, "S1", "2026-03-01", "2026-03-01", "CFDI · emitidos",
                                tipo_comprobante="E")
    config_store.save_solicitud(MI_RFC, "S2", "2026-03-02", "2026-03-02", "CFDI · emitidos",
                                tipo_comprobante="E")
    ruta = config_store._solicitudes_path(MI_RFC)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["solicitudes"][0]["timestamp"] = "2026-01-01T00:00:00"  # S1 vence; S2 sigue viva
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    llamadas = []
    monkeypatch.setattr(calendario, "sincronizar", lambda rfc: llamadas.append(rfc))
    monkeypatch.setattr(poller, "_fiel_de", lambda rfc: object())

    def _sin_token(fiel):
        raise requests.ConnectionError("SAT caído")

    monkeypatch.setattr(poller, "obtener_token", _sin_token)
    with pytest.raises(requests.ConnectionError):
        poller._procesar_empresa(MI_RFC, {"rfc": MI_RFC, "metodos": ["fiel"]})
    assert llamadas == [MI_RFC]
