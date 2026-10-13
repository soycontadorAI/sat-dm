"""Solicitud manual que sirve de la base lo consolidado (fase 6 del doc)."""

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from sat_descarga.cli import config_store
from sat_descarga.procesador import calendario, parse_cfdi, servir_base
from sat_descarga.procesador import db as db_mod


MI_RFC = "BBB020202BBB"
OTRO = "AAA010101AAA"
HOY = date(2026, 10, 13)


def _xml(uuid, fecha="2026-03-04T10:00:00", emisor=OTRO, receptor=MI_RFC):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0" Serie="A" Folio="10" Fecha="{fecha}" Sello="..." NoCertificado="000"
    Certificado="..." SubTotal="100" Moneda="MXN" Total="116"
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


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "DEFAULT_DB_PATH", tmp_path / "procesador.db")
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "EFIRMA_DIR", tmp_path / "efirma")
    monkeypatch.setattr(config_store, "descargas_dir_default", lambda: str(tmp_path / "TodoConta"))
    monkeypatch.setattr(calendario, "hoy", lambda: HOY)
    db_mod.resetear_singleton_para_tests()
    inst = db_mod.abrir_db()
    yield inst
    inst.close()
    db_mod.resetear_singleton_para_tests()


def _uuid(n):
    return f"BBBBBBBB-0000-0000-0000-{n:012d}"


def _agregar(db, n, dia, *, emisor=OTRO, receptor=MI_RFC, con_xml=True):
    xml = _xml(_uuid(n), fecha=f"{dia}T10:00:00", emisor=emisor, receptor=receptor)
    cfdi = parse_cfdi(xml)
    db.agregar([cfdi], mi_rfc=MI_RFC, xmls={cfdi.uuid: xml} if con_xml else None)
    return cfdi.uuid


def _estado(dias, direccion, estado):
    """Fija el estado de varios días (iso) como lo haría el cierre mensual."""
    if estado in ("consolidado", "diferencia"):
        calendario.cerrar_dias(MI_RFC, {(d, direccion): (estado, 0, None) for d in dias})
    else:
        for d in dias:
            f = date.fromisoformat(d)
            calendario.marcar(MI_RFC, f, f, direccion, estado)


def _d(n):
    return date(2026, 3, n)


def _iso(*ns):
    return [_d(n).isoformat() for n in ns]


# ---------------------------------------------------------------------------
# 1. plan
# ---------------------------------------------------------------------------


def _plan(*args):
    """`plan` sin los UUID (se prueban aparte)."""
    p = servir_base.plan(*args)
    p.pop("uuids")
    return p


def test_plan_sin_consolidados_es_un_hueco_con_todo(db):
    p = _plan(MI_RFC, _d(1), _d(10), "R")
    assert p == {"consolidados": [], "huecos": [(_d(1), _d(10))]}


def test_plan_todo_consolidado_no_deja_huecos(db):
    _estado(_iso(1, 2, 3), "R", "consolidado")
    p = _plan(MI_RFC, _d(1), _d(3), "R")
    assert p == {"consolidados": [_d(1), _d(2), _d(3)], "huecos": []}


def test_plan_mezcla_deja_huecos_minimos_y_respeta_la_direccion(db):
    _estado(_iso(3, 4, 8), "R", "consolidado")
    _estado(_iso(1, 2), "E", "consolidado")  # la otra dirección no cuenta
    p = _plan(MI_RFC, _d(1), _d(10), "R")
    assert p["consolidados"] == [_d(3), _d(4), _d(8)]
    assert p["huecos"] == [(_d(1), _d(2)), (_d(5), _d(7)), (_d(9), _d(10))]


def test_plan_junta_los_huecos_si_son_mas_del_maximo(db):
    _estado(_iso(2, 4, 6, 8, 10, 12, 14), "R", "consolidado")
    # Huecos sueltos: 1, 3, 5, 7, 9, 11, 13 (siete) -> se juntan a MAX_RANGOS.
    p = _plan(MI_RFC, _d(1), _d(14), "R")
    assert len(p["huecos"]) == servir_base.MAX_RANGOS
    cubiertos = {_d(n) for n in (1, 3, 5, 7, 9, 11, 13)}
    for dia in cubiertos:
        assert any(a <= dia <= b for a, b in p["huecos"])


def test_plan_recorta_los_dias_futuros(db):
    p = _plan(MI_RFC, date(2026, 10, 10), date(2026, 10, 30), "E")
    assert p["huecos"] == [(date(2026, 10, 10), HOY)]
    assert _plan(MI_RFC, date(2026, 10, 20), date(2026, 10, 30), "E") == {
        "consolidados": [], "huecos": [],
    }


def test_plan_diferencia_y_provisional_son_hueco(db):
    _estado(_iso(1), "R", "consolidado")
    _estado(_iso(2), "R", "diferencia")
    _estado(_iso(3), "R", "provisional")
    p = _plan(MI_RFC, _d(1), _d(3), "R")
    assert p == {"consolidados": [_d(1)], "huecos": [(_d(2), _d(3))]}


def test_plan_dia_consolidado_con_un_cfdi_sin_xml_es_hueco(db):
    _agregar(db, 1, "2026-03-03")
    _agregar(db, 2, "2026-03-04")
    _agregar(db, 3, "2026-03-04", con_xml=False)
    _agregar(db, 4, "2026-03-05")
    _estado(_iso(3, 4, 5), "R", "consolidado")
    p = _plan(MI_RFC, _d(3), _d(5), "R")
    assert p == {"consolidados": [_d(3), _d(5)], "huecos": [(_d(4), _d(4))]}


def test_plan_dia_consolidado_sin_cfdis_se_sirve(db):
    _estado(_iso(3), "R", "consolidado")
    p = _plan(MI_RFC, _d(3), _d(3), "R")
    assert p == {"consolidados": [_d(3)], "huecos": []}


def test_plan_los_consolidados_dentro_de_un_hueco_juntado_no_se_sirven(db):
    _estado(_iso(2, 4, 6, 8, 10, 12, 14), "R", "consolidado")
    p = _plan(MI_RFC, _d(1), _d(14), "R")
    assert len(p["huecos"]) == servir_base.MAX_RANGOS
    for dia in p["consolidados"]:
        assert not any(a <= dia <= b for a, b in p["huecos"])
    # Se juntaron dos huecos y el consolidado de en medio se pide al SAT.
    assert len(p["consolidados"]) == 6


# ---------------------------------------------------------------------------
# 2. materializar
# ---------------------------------------------------------------------------


def test_materializar_escribe_los_xml_y_registra_sin_reindexar(db, tmp_path, monkeypatch):
    from sat_descarga.procesador import indexar

    def _no(*a, **k):
        raise AssertionError("no debe reindexar lo que ya está en la base")

    monkeypatch.setattr(indexar, "indexar_descarga", _no)

    recibido = _agregar(db, 1, "2026-03-04")
    emitido = _agregar(db, 2, "2026-03-04", emisor=MI_RFC, receptor=OTRO)
    auto = _agregar(db, 3, "2026-03-05", emisor=MI_RFC, receptor=MI_RFC)
    cancelado = _agregar(db, 4, "2026-03-05")
    db.actualizar_estado_sat(cancelado, "Cancelado")
    sin_xml = _agregar(db, 5, "2026-03-05", con_xml=False)
    fuera = _agregar(db, 6, "2026-03-06")  # día no consolidado

    dias = [_d(4), _d(5)]
    r = servir_base.materializar(MI_RFC, dias, "R", desde=_d(1), hasta=_d(10))
    carpeta = tmp_path / "TodoConta" / "cfdi" / MI_RFC / "recibidos" / "2026-03-01_a_2026-03-10"
    assert r == {"ruta": str(carpeta), "cfdis": 2, "sin_xml": 1}
    assert {p.name for p in carpeta.iterdir()} == {f"{recibido}.xml", f"{auto}.xml"}
    assert fuera not in {p.stem for p in carpeta.iterdir()} and cancelado not in {
        p.stem for p in carpeta.iterdir()}
    assert (carpeta / f"{recibido}.xml").read_bytes().startswith(b"<?xml")

    # La autofactura sale también en emitidos; el emitido normal solo ahí.
    r_e = servir_base.materializar(MI_RFC, dias, "E", desde=_d(1), hasta=_d(10))
    carpeta_e = tmp_path / "TodoConta" / "cfdi" / MI_RFC / "emitidos" / "2026-03-01_a_2026-03-10"
    assert r_e["cfdis"] == 2
    assert {p.stem for p in carpeta_e.iterdir()} == {emitido, auto}
    assert sin_xml not in {p.stem for p in carpeta_e.iterdir()}

    historial = config_store.list_descargas(MI_RFC)[0]  # la de emitidos, la última
    assert historial["canal"] == "base" and historial["tipo"] == "cfdi"
    assert historial["total"] == 2 and historial["ruta"] == str(carpeta_e)
    assert historial["descripcion"] == "Desde la base · 2026-03-01 a 2026-03-10 (2 CFDI consolidados)"


def test_materializar_encuentra_el_xml_con_uuid_en_minusculas(db, tmp_path):
    """El índice guarda el UUID como viene en el XML; algunos PAC lo timbran en
    minúsculas y la regla del conteo lo da en mayúsculas."""
    xml = _xml("bbbbbbbb-0000-0000-0000-00000000000a", fecha="2026-03-04T10:00:00")
    cfdi = parse_cfdi(xml)
    db.agregar([cfdi], mi_rfc=MI_RFC, xmls={cfdi.uuid: xml})
    r = servir_base.materializar(MI_RFC, [_d(4)], "R", desde=_d(4), hasta=_d(4))
    assert (r["cfdis"], r["sin_xml"]) == (1, 0)
    assert (Path(r["ruta"]) / "BBBBBBBB-0000-0000-0000-00000000000A.xml").read_bytes() == xml


def test_plan_sirve_un_cfdi_con_uuid_en_mayusculas_y_minusculas_mezcladas(db, tmp_path):
    """El UUID se busca tal como se guardó: el día consolidado se sirve (no es
    hueco) y el archivo sale en mayúsculas."""
    uuid = "bBbBbBbB-0000-0000-0000-00000000000a"
    xml = _xml(uuid, fecha="2026-03-04T10:00:00")
    cfdi = parse_cfdi(xml)
    db.agregar([cfdi], mi_rfc=MI_RFC, xmls={cfdi.uuid: xml})
    _estado(["2026-03-04"], "R", "consolidado")

    p = servir_base.plan(MI_RFC, _d(4), _d(4), "R")
    assert p["consolidados"] == [_d(4)] and p["huecos"] == []
    r = servir_base.materializar(MI_RFC, p["consolidados"], "R", desde=_d(4), hasta=_d(4),
                                 uuids_por_dia=p["uuids"])
    assert (r["cfdis"], r["sin_xml"]) == (1, 0)
    assert [f.name for f in Path(r["ruta"]).iterdir()] == [uuid.upper() + ".xml"]


def test_materializar_sin_dias_no_escribe_nada(db, tmp_path):
    r = servir_base.materializar(MI_RFC, [], "R", desde=_d(1), hasta=_d(5))
    assert r == {"ruta": None, "cfdis": 0, "sin_xml": 0}
    assert not (tmp_path / "TodoConta").exists()
    assert config_store.list_descargas(MI_RFC) == []


# ---------------------------------------------------------------------------
# 3. Endpoint
# ---------------------------------------------------------------------------


@pytest.fixture()
def cliente(db, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from sat_descarga.api import cupo_descargas, server
    from sat_descarga.api.routers import webservice

    config_store.add_empresa_ciec(MI_RFC, "Empresa", "ciec123")
    server._limpiar_session()
    server._session["fiel"] = SimpleNamespace(rfc=MI_RFC)

    ctx = SimpleNamespace(pedidas=[], exigidas=[], registradas=[], falla_en=None)

    def _solicitar(**kw):
        if ctx.falla_en is not None and len(ctx.pedidas) + 1 == ctx.falla_en:
            raise RuntimeError("El SAT rechazó la solicitud")
        ctx.pedidas.append(kw)
        return f"SOL-{len(ctx.pedidas)}"

    monkeypatch.setattr(webservice, "_renovar_token", lambda: "token")
    monkeypatch.setattr(webservice, "solicitar_descarga", _solicitar)
    ctx.exigir_real = cupo_descargas.exigir

    def _exigir(rfc=None):
        ctx.exigidas.append(rfc)

    monkeypatch.setattr(cupo_descargas, "exigir", _exigir)
    monkeypatch.setattr(
        cupo_descargas, "registrar", lambda tipo, rfc=None: ctx.registradas.append((tipo, rfc)))
    ctx.http = TestClient(server.app)
    yield ctx
    server._limpiar_session()


def _cuerpo(desde="2026-03-01", hasta="2026-03-10", **extra):
    return {"fecha_inicio": desde, "fecha_fin": hasta, "tipo_comprobante": "R", **extra}


def test_endpoint_todo_consolidado_no_toca_al_sat_ni_al_cupo(cliente, db, monkeypatch):
    from sat_descarga.api.routers import webservice

    def _truena(**kw):
        raise AssertionError("tocó al SAT")

    monkeypatch.setattr(webservice, "solicitar_descarga", _truena)
    _agregar(db, 1, "2026-03-04")
    _estado(_iso(3, 4, 5), "R", "consolidado")

    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-03", "2026-03-05"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and j["id_solicitud"] is None and j["solicitudes"] == []
    assert j["servidos"]["dias"] == 3 and j["servidos"]["cfdis"] == 1
    assert j["servidos"]["ruta"].endswith("recibidos/2026-03-03_a_2026-03-05")
    assert "errores" not in j
    assert cliente.exigidas == [] and cliente.registradas == []


def test_endpoint_con_huecos_pide_solo_los_huecos(cliente, db):
    _agregar(db, 1, "2026-03-04")
    _estado(_iso(3, 4, 5), "R", "consolidado")

    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["id_solicitud"] == "SOL-1"
    assert j["solicitudes"] == [
        {"id_solicitud": "SOL-1", "fecha_inicio": "2026-03-01", "fecha_fin": "2026-03-02"},
        {"id_solicitud": "SOL-2", "fecha_inicio": "2026-03-06", "fecha_fin": "2026-03-08"},
    ]
    assert j["servidos"]["dias"] == 3 and j["servidos"]["cfdis"] == 1
    assert [(p["fecha_inicio"], p["fecha_fin"], p["tipo_comprobante"], p["tipo_solicitud"])
            for p in cliente.pedidas] == [
        (_d(1), _d(2), "R", "CFDI"), (_d(6), _d(8), "R", "CFDI")]
    # Cupo: se exige una vez y se registra una por solicitud.
    assert cliente.exigidas == [MI_RFC]
    assert cliente.registradas == [("cfdi", MI_RFC), ("cfdi", MI_RFC)]
    # Los días pedidos quedan en proceso; los consolidados no cambian.
    filas = calendario.filas(MI_RFC, _d(1), _d(8))
    assert {f: v["estado"] for (f, _), v in filas.items()} == {
        **{d: "en_proceso" for d in _iso(1, 2, 6, 7, 8)},
        **{d: "consolidado" for d in _iso(3, 4, 5)},
    }
    assert filas[(_d(1).isoformat(), "R")]["ultima_solicitud_id"] == "SOL-1"
    assert filas[(_d(7).isoformat(), "R")]["ultima_solicitud_id"] == "SOL-2"
    # Quedan en el catálogo como cualquier solicitud y lo que bajen va a la carpeta
    # del rango pedido, junto con lo servido de la base.
    assert {s["id_solicitud"] for s in config_store.list_solicitudes(MI_RFC)} == {"SOL-1", "SOL-2"}
    from sat_descarga.api import state

    assert state._salida_descarga_ws(MI_RFC, "SOL-1") == j["servidos"]["ruta"]
    assert state._salida_descarga_ws(MI_RFC, "SOL-2") == j["servidos"]["ruta"]
    assert j["servidos"]["ruta"].endswith("recibidos/2026-03-01_a_2026-03-08")


def test_endpoint_sin_consolidados_usa_su_propia_carpeta(cliente, db):
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.json()["solicitudes"] == [
        {"id_solicitud": "SOL-1", "fecha_inicio": "2026-03-01", "fecha_fin": "2026-03-08"}]
    assert "carpeta_rango" not in config_store.get_solicitud(MI_RFC, "SOL-1")


def test_endpoint_periodo_futuro_es_400(cliente, db):
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-10-20", "2026-10-30"))
    assert r.status_code == 400 and "después de hoy" in r.json()["detail"]
    assert cliente.pedidas == [] and cliente.exigidas == []


def test_endpoint_un_error_posterior_no_tira_lo_ya_pedido(cliente, db):
    _estado(_iso(3, 4, 5), "R", "consolidado")
    cliente.falla_en = 2
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert [s["id_solicitud"] for s in j["solicitudes"]] == ["SOL-1"]
    assert j["errores"] == [{"tipo": "sat", "rango": ["2026-03-06", "2026-03-08"],
                             "mensaje": "El SAT rechazó la solicitud"}]
    assert j["servidos"]["dias"] == 3


def test_endpoint_error_del_primer_rango_es_400(cliente, db):
    cliente.falla_en = 1
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo())
    assert r.status_code == 400 and "rechazó" in r.json()["detail"]


def test_endpoint_metadata_es_400(cliente, db):
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo(tipo_solicitud="Metadata"))
    assert r.status_code == 400 and r.json()["detail"] == "Solo para CFDI"
    assert cliente.pedidas == []


def test_endpoint_sin_efirma_es_401(cliente, db):
    from sat_descarga.api import server

    server._limpiar_session()
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo())
    assert r.status_code == 401


def test_solicitar_sigue_igual(cliente, db):
    _estado(_iso(3, 4, 5), "R", "consolidado")
    r = cliente.http.post("/solicitar", json=_cuerpo("2026-03-01", "2026-03-10"))
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "id_solicitud": "SOL-1"}
    assert len(cliente.pedidas) == 1
    assert (cliente.pedidas[0]["fecha_inicio"], cliente.pedidas[0]["fecha_fin"]) == (_d(1), _d(10))
    assert cliente.exigidas == [MI_RFC] and cliente.registradas == [("cfdi", MI_RFC)]


# ---------------------------------------------------------------------------
# 4. Correcciones de la revisión
# ---------------------------------------------------------------------------


def _con_tope(monkeypatch, cliente, *, tope=5, usadas=3):
    from sat_descarga.api import cupo_descargas

    monkeypatch.setattr(cupo_descargas, "exigir", cliente.exigir_real)
    monkeypatch.setattr(cupo_descargas, "estado", lambda licencia=None, **k: cupo_descargas.CupoDescargas(
        tope=tope, usadas=usadas, mes="2026-10", plan_codigo="gratis", plan_nombre="Gratis"))
    monkeypatch.setattr(cupo_descargas, "licencia_fresca", lambda: None)


def _tres_huecos():
    # Consolidados 3 y 6 (sin CFDI): huecos 1-2, 4-5, 7-8.
    _estado(_iso(3, 6), "R", "consolidado")


def test_endpoint_con_tope_pide_un_solo_rango_del_primer_hueco_al_ultimo(cliente, db, monkeypatch):
    _con_tope(monkeypatch, cliente)  # quedan 2
    _tres_huecos()
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert [(p["fecha_inicio"], p["fecha_fin"]) for p in cliente.pedidas] == [(_d(1), _d(8))]
    assert len(j["solicitudes"]) == 1
    # Los consolidados 3 y 6 caen dentro del rango pedido: se piden, no se sirven.
    assert j["servidos"] == {"dias": 0, "cfdis": 0, "ruta": None, "sin_xml": 0}
    assert cliente.registradas == [("cfdi", MI_RFC)]
    assert "errores" not in j


def test_endpoint_con_tope_y_un_solo_hueco_no_cambia(cliente, db, monkeypatch):
    _con_tope(monkeypatch, cliente)
    _estado(_iso(3, 4, 5), "R", "consolidado")
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-03", "2026-03-10"))
    assert r.status_code == 200, r.text
    assert [(p["fecha_inicio"], p["fecha_fin"]) for p in cliente.pedidas] == [(_d(6), _d(10))]


def test_endpoint_sin_tope_pide_los_huecos_por_separado(cliente, db, monkeypatch):
    from sat_descarga.api import cupo_descargas

    monkeypatch.setattr(cupo_descargas, "estado", lambda licencia=None, **k: cupo_descargas.CupoDescargas(
        tope=None, usadas=40, mes="2026-10", plan_codigo="pro", plan_nombre="Pro"))
    _tres_huecos()
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    assert [(p["fecha_inicio"], p["fecha_fin"]) for p in cliente.pedidas] == [
        (_d(1), _d(2)), (_d(4), _d(5)), (_d(7), _d(8))]
    assert cliente.exigidas == [MI_RFC]


def test_endpoint_cupo_agotado_conserva_el_mensaje_de_siempre(cliente, db, monkeypatch):
    _con_tope(monkeypatch, cliente, tope=5, usadas=5)
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 402
    assert "ya usaste las 5" in r.json()["detail"]


def test_endpoint_dia_consolidado_sin_xml_se_pide_al_sat(cliente, db):
    _agregar(db, 1, "2026-03-04", con_xml=False)
    _estado(_iso(4), "R", "consolidado")
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-04", "2026-03-04"))
    j = r.json()
    assert [(s["fecha_inicio"], s["fecha_fin"]) for s in j["solicitudes"]] == [
        ("2026-03-04", "2026-03-04")]
    assert j["servidos"]["dias"] == 0


def test_endpoint_consolidados_dentro_de_un_hueco_juntado_no_se_sirven(cliente, db):
    dias = [2, 4, 6, 8, 10, 12, 14]
    uuids = {n: _agregar(db, n, f"2026-03-{n:02d}") for n in dias}
    _estado(_iso(*dias), "R", "consolidado")
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-14"))
    assert r.status_code == 200, r.text
    j = r.json()
    pedidos = [(s["fecha_inicio"], s["fecha_fin"]) for s in j["solicitudes"]]
    assert len(pedidos) == servir_base.MAX_RANGOS
    dentro = {n for n in dias if any(a <= f"2026-03-{n:02d}" <= b for a, b in pedidos)}
    assert len(dentro) == 1
    assert j["servidos"]["dias"] == 6 and j["servidos"]["cfdis"] == 6
    escritos = {p.stem for p in Path(j["servidos"]["ruta"]).iterdir()}
    assert escritos == {uuids[n] for n in dias if n not in dentro}


def test_endpoint_si_materializar_truena_no_dice_que_sirvio_dias(cliente, db, monkeypatch):
    _estado(_iso(3, 4, 5), "R", "consolidado")

    def _truena(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(servir_base, "materializar", _truena)
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["servidos"]["dias"] == 0 and j["servidos"]["cfdis"] == 0
    assert "disco lleno" in j["errores"][0]["mensaje"]
    assert j["errores"][0]["tipo"] == "base"
    assert len(j["solicitudes"]) == 2


def test_endpoint_renueva_el_token_por_hueco_si_pasa_la_vigencia(cliente, db, monkeypatch):
    from sat_descarga.api.routers import webservice

    emitidos = []

    def _token():
        emitidos.append(f"t{len(emitidos)}")
        return emitidos[-1]

    monkeypatch.setattr(webservice, "_renovar_token", _token)
    monkeypatch.setattr(webservice, "TOKEN_VIGENCIA_S", 0)
    _tres_huecos()
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    assert [p["token"] for p in cliente.pedidas] == ["t0", "t1", "t2"]


def test_endpoint_reusa_el_token_dentro_de_la_vigencia(cliente, db, monkeypatch):
    from sat_descarga.api.routers import webservice

    llamadas = []
    monkeypatch.setattr(webservice, "_renovar_token", lambda: llamadas.append(1) or "token")
    _tres_huecos()
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    assert len(llamadas) == 1


def test_endpoint_cualquier_error_del_segundo_hueco_no_tira_lo_ya_pedido(cliente, db, monkeypatch):
    from sat_descarga.api.routers import webservice

    def _solicitar(**kw):
        if cliente.pedidas:
            raise ValueError("respuesta rara del SAT")
        cliente.pedidas.append(kw)
        return "SOL-1"

    monkeypatch.setattr(webservice, "solicitar_descarga", _solicitar)
    _estado(_iso(3, 4, 5), "R", "consolidado")
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert [s["id_solicitud"] for s in j["solicitudes"]] == ["SOL-1"]
    assert j["errores"] == [{"tipo": "sat", "rango": ["2026-03-06", "2026-03-08"],
                             "mensaje": "respuesta rara del SAT"}]


def test_endpoint_fechas_invertidas_es_400(cliente, db):
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-10", "2026-03-01"))
    assert r.status_code == 400
    assert r.json()["detail"] == "La fecha inicial es posterior a la final."
    assert cliente.pedidas == []


# ---------------------------------------------------------------------------
# 5. Segunda revisión
# ---------------------------------------------------------------------------


def test_endpoint_falla_el_token_despues_del_primer_hueco_va_a_errores(cliente, db, monkeypatch):
    from sat_descarga.api.routers import webservice

    emitidos = []

    def _token():
        emitidos.append(1)
        if len(emitidos) > 1:
            raise RuntimeError("no se pudo renovar el token")
        return "token"

    monkeypatch.setattr(webservice, "_renovar_token", _token)
    monkeypatch.setattr(webservice, "TOKEN_VIGENCIA_S", 0)
    _tres_huecos()
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert [s["id_solicitud"] for s in j["solicitudes"]] == ["SOL-1"]
    assert [(e["tipo"], e["rango"]) for e in j["errores"]] == [
        ("sat", ["2026-03-04", "2026-03-05"]), ("sat", ["2026-03-07", "2026-03-08"])]
    assert "token" in j["errores"][0]["mensaje"]


def test_endpoint_si_el_indice_falla_sigue_como_solicitar(cliente, db, monkeypatch):
    def _truena(*a, **k):
        raise RuntimeError("base bloqueada")

    monkeypatch.setattr(servir_base, "plan", _truena)
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert [(p["fecha_inicio"], p["fecha_fin"]) for p in cliente.pedidas] == [(_d(1), _d(8))]
    assert j["servidos"] == {"dias": 0, "cfdis": 0, "ruta": None, "sin_xml": 0}
    assert "errores" not in j


def test_endpoint_si_el_indice_falla_recorta_a_hoy(cliente, db, monkeypatch):
    monkeypatch.setattr(servir_base, "plan", lambda *a, **k: 1 / 0)
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-10-10", "2026-10-30"))
    assert r.status_code == 200, r.text
    assert [(p["fecha_inicio"], p["fecha_fin"]) for p in cliente.pedidas] == [
        (date(2026, 10, 10), HOY)]


@pytest.mark.parametrize("filtro", ["rfc_emisor", "rfc_receptor"])
def test_endpoint_con_filtros_no_sirve_nada_de_la_base(cliente, db, filtro):
    _agregar(db, 1, "2026-03-04")
    _estado(_iso(3, 4, 5), "R", "consolidado")
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo(
        "2026-03-01", "2026-03-08", **{filtro: OTRO}))
    assert r.status_code == 200, r.text
    j = r.json()
    assert [(p["fecha_inicio"], p["fecha_fin"]) for p in cliente.pedidas] == [(_d(1), _d(8))]
    assert cliente.pedidas[0][filtro] == OTRO
    assert j["servidos"] == {"dias": 0, "cfdis": 0, "ruta": None, "sin_xml": 0}


def test_endpoint_5005_en_el_primer_hueco_sirve_lo_consolidado(cliente, db, monkeypatch):
    from sat_descarga.api.routers import webservice

    def _duplicada(**kw):
        raise RuntimeError(
            "Ya tienes una solicitud activa (SAT rechazó la solicitud. CodEstatus=5005, Mensaje=x)")

    monkeypatch.setattr(webservice, "solicitar_descarga", _duplicada)
    _agregar(db, 1, "2026-03-04")
    _estado(_iso(3, 4, 5), "R", "consolidado")
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["id_solicitud"] is None and j["solicitudes"] == []
    assert [e["tipo"] for e in j["errores"]] == ["sat", "sat"]
    assert "CodEstatus=5005" in j["errores"][0]["mensaje"]
    assert j["servidos"]["dias"] == 3 and j["servidos"]["cfdis"] == 1


def test_endpoint_otro_error_del_primer_hueco_sigue_siendo_400(cliente, db, monkeypatch):
    from sat_descarga.api.routers import webservice

    def _otro(**kw):
        raise RuntimeError("SAT rechazó la solicitud. CodEstatus=5002, Mensaje=x")

    monkeypatch.setattr(webservice, "solicitar_descarga", _otro)
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo())
    assert r.status_code == 400 and "5002" in r.json()["detail"]


def test_plan_devuelve_los_uuid_de_los_dias_que_sirve(db):
    u1 = _agregar(db, 1, "2026-03-03")
    u2 = _agregar(db, 2, "2026-03-05")
    _agregar(db, 3, "2026-03-04", con_xml=False)
    _estado(_iso(3, 4, 5), "R", "consolidado")
    p = servir_base.plan(MI_RFC, _d(3), _d(5), "R")
    assert p["consolidados"] == [_d(3), _d(5)]
    assert p["uuids"] == {_d(3): {u1.upper()}, _d(5): {u2.upper()}}


def test_materializar_usa_los_uuid_del_plan_sin_recalcularlos(db, monkeypatch):
    uuid = _agregar(db, 1, "2026-03-04")
    _estado(_iso(4), "R", "consolidado")
    p = servir_base.plan(MI_RFC, _d(4), _d(4), "R")

    def _no(*a, **k):
        raise AssertionError("no debe recalcular uuids_por_dia")

    monkeypatch.setattr(calendario, "uuids_por_dia", _no)
    r = servir_base.materializar(
        MI_RFC, p["consolidados"], "R", desde=_d(4), hasta=_d(4), uuids_por_dia=p["uuids"])
    assert r["cfdis"] == 1
    assert (Path(r["ruta"]) / f"{uuid}.xml").exists()


# ---------------------------------------------------------------------------
# 6. Tercera revisión
# ---------------------------------------------------------------------------


def test_endpoint_con_tope_lo_consolidado_dentro_del_rango_no_se_escribe(cliente, db, monkeypatch):
    _con_tope(monkeypatch, cliente)
    _agregar(db, 1, "2026-03-03")
    _agregar(db, 2, "2026-03-06")
    _estado(_iso(3, 6), "R", "consolidado")
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert [(p["fecha_inicio"], p["fecha_fin"]) for p in cliente.pedidas] == [(_d(1), _d(8))]
    assert j["servidos"]["dias"] == 0 and j["servidos"]["ruta"] is None


def test_endpoint_con_tope_sirve_lo_consolidado_fuera_del_rango_juntado(cliente, db, monkeypatch):
    _con_tope(monkeypatch, cliente)
    _agregar(db, 1, "2026-03-01")
    _agregar(db, 2, "2026-03-04")
    _estado(_iso(1, 4), "R", "consolidado")
    # Huecos 2-3 y 5-6 -> rango 2-6; el día 1 queda fuera y se sirve, el 4 se pide.
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-06"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert [(p["fecha_inicio"], p["fecha_fin"]) for p in cliente.pedidas] == [(_d(2), _d(6))]
    assert j["servidos"]["dias"] == 1 and j["servidos"]["cfdis"] == 1
    assert {p.stem for p in Path(j["servidos"]["ruta"]).iterdir()} == {_uuid(1)}


def test_endpoint_cupo_agotado_con_algo_servido_no_tira_la_peticion(cliente, db, monkeypatch):
    _con_tope(monkeypatch, cliente, tope=5, usadas=5)
    _agregar(db, 1, "2026-03-02")
    _estado(_iso(1, 2, 3), "R", "consolidado")
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["id_solicitud"] is None and j["solicitudes"] == []
    assert cliente.pedidas == [] and cliente.registradas == []
    assert j["servidos"]["dias"] == 3 and j["servidos"]["cfdis"] == 1
    assert [e["tipo"] for e in j["errores"]] == ["cupo"]
    assert "ya usaste las 5" in j["errores"][0]["mensaje"]
    assert j["errores"][0]["datos"]["tope"] == 5 and j["errores"][0]["datos"]["usadas"] == 5
    assert j["errores"][0]["rango"] == ["2026-03-04", "2026-03-08"]


def test_endpoint_lo_de_la_base_se_sirve_antes_de_pedir_cupo(cliente, db, monkeypatch):
    orden = []
    real = servir_base.materializar

    def _materializar(*a, **k):
        orden.append("base")
        return real(*a, **k)

    monkeypatch.setattr(servir_base, "materializar", _materializar)
    from sat_descarga.api import cupo_descargas

    monkeypatch.setattr(cupo_descargas, "exigir", lambda rfc=None: orden.append("cupo"))
    _estado(_iso(3, 4, 5), "R", "consolidado")
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    assert orden == ["base", "cupo"]


def test_endpoint_cupo_agotado_sin_nada_servido_sigue_siendo_402(cliente, db, monkeypatch):
    _con_tope(monkeypatch, cliente, tope=5, usadas=5)
    _agregar(db, 1, "2026-03-04", con_xml=False)
    _estado(_iso(4), "R", "consolidado")  # sin XML: se pide, no se sirve
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 402


def test_endpoint_error_del_primer_hueco_con_algo_servido_va_a_errores(cliente, db):
    _agregar(db, 1, "2026-03-04")
    _estado(_iso(3, 4, 5), "R", "consolidado")
    cliente.falla_en = 1
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["id_solicitud"] is None
    assert [(e["tipo"], e["rango"]) for e in j["errores"]] == [
        ("sat", ["2026-03-01", "2026-03-02"]), ("sat", ["2026-03-06", "2026-03-08"])]
    assert "rechazó" in j["errores"][0]["mensaje"]
    assert j["servidos"]["dias"] == 3 and j["servidos"]["cfdis"] == 1
    assert j["solicitudes"] == []


def test_endpoint_falla_el_token_del_primer_hueco_con_algo_servido_va_a_errores(cliente, db, monkeypatch):
    from sat_descarga.api.routers import webservice

    def _token():
        raise RuntimeError("no se pudo renovar el token")

    monkeypatch.setattr(webservice, "_renovar_token", _token)
    _estado(_iso(3, 4, 5), "R", "consolidado")
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["solicitudes"] == [] and j["servidos"]["dias"] == 3
    assert [e["tipo"] for e in j["errores"]] == ["sat", "sat"]


def _duplicada(monkeypatch):
    from sat_descarga.api.routers import webservice

    def _solicitar(**kw):
        raise RuntimeError(
            "Ya tienes una solicitud activa (SAT rechazó la solicitud. CodEstatus=5005, Mensaje=x)")

    monkeypatch.setattr(webservice, "solicitar_descarga", _solicitar)


def test_endpoint_5005_con_solicitud_viva_igual_la_sigue(cliente, db, monkeypatch):
    primera = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert primera.json()["id_solicitud"] == "SOL-1"
    registradas = list(cliente.registradas)
    _duplicada(monkeypatch)
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["solicitudes"] == [
        {"id_solicitud": "SOL-1", "fecha_inicio": "2026-03-01", "fecha_fin": "2026-03-08"}]
    assert j["id_solicitud"] == "SOL-1" and "errores" not in j
    assert cliente.registradas == registradas  # no cuenta otra descarga


def test_endpoint_5005_con_filtros_no_sigue_la_solicitud_de_otro_criterio(cliente, db, monkeypatch):
    cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    _duplicada(monkeypatch)
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo(
        "2026-03-01", "2026-03-08", rfc_emisor=OTRO))
    assert r.status_code == 200, r.text
    assert r.json()["solicitudes"] == []
    assert "CodEstatus=5005" in r.json()["errores"][0]["mensaje"]


def test_endpoint_5005_con_solicitud_viva_de_otro_rango_es_error(cliente, db, monkeypatch):
    cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-07"))
    _duplicada(monkeypatch)
    r = cliente.http.post("/solicitar/desde-base", json=_cuerpo("2026-03-01", "2026-03-08"))
    assert r.status_code == 200, r.text
    assert r.json()["solicitudes"] == [] and r.json()["errores"][0]["tipo"] == "sat"


def test_exigir_ya_no_recibe_cuantas():
    import inspect

    from sat_descarga.api import cupo_descargas

    assert list(inspect.signature(cupo_descargas.exigir).parameters) == ["rfc"]
    assert list(inspect.signature(cupo_descargas.error_de_tope).parameters) == ["cupo"]
