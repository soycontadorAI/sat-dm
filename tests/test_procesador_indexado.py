"""Índice permanente del procesador: nodos, documentos (XML + nodos) e indexado."""

import shutil

import pytest

from sat_descarga.cli import config_store
from sat_descarga.procesador import parse_cfdi
from sat_descarga.procesador import db as db_mod
from sat_descarga.procesador import indexar as indexar_mod
from sat_descarga.procesador.nodos import NODOS_VERSION, valores, xml_a_nodos

MI_RFC = "BBB020202BBB"
OTRO_RFC = "CCC030303CCC"


def _xml(uuid="AAAAAAAA-1111-2222-3333-444444444444", fecha="2026-05-15T10:00:00",
         emisor="AAA010101AAA", receptor=MI_RFC, conceptos=1, extra_complemento=""):
    concepto = """
    <cfdi:Concepto ClaveProdServ="01010101" Cantidad="1" ClaveUnidad="ACT"
                   Descripcion="Servicio {n}" ValorUnitario="500" Importe="500"
                   ObjetoImp="01"/>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0" Serie="A" Folio="100" Fecha="{fecha}" Sello="..." NoCertificado="000"
    Certificado="..." SubTotal="{500 * conceptos}" Moneda="MXN" Total="{500 * conceptos}"
    TipoDeComprobante="I" Exportacion="01" MetodoPago="PUE" FormaPago="03"
    LugarExpedicion="64000">
  <cfdi:Emisor Rfc="{emisor}" Nombre="EMISORA SA DE CV" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="{receptor}" Nombre="RECEPTORA" DomicilioFiscalReceptor="64000"
                 RegimenFiscalReceptor="612" UsoCFDI="G03"/>
  <cfdi:Conceptos>{"".join(concepto.format(n=i) for i in range(conceptos))}
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="{uuid}"
        FechaTimbrado="{fecha}" RfcProvCertif="SAT970701NN3" SelloCFD="..."
        NoCertificadoSAT="000" SelloSAT="..."/>{extra_complemento}
  </cfdi:Complemento>
</cfdi:Comprobante>""".encode()


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "DEFAULT_DB_PATH", tmp_path / "procesador.db")
    db_mod.resetear_singleton_para_tests()
    inst = db_mod.abrir_db()
    yield inst
    inst.close()
    db_mod.resetear_singleton_para_tests()


# ---------------------------------------------------------------------------
# nodos
# ---------------------------------------------------------------------------


def test_nodos_guarda_todo_sin_prefijos():
    carta_porte = """
    <cartaporte31:CartaPorte xmlns:cartaporte31="http://www.sat.gob.mx/CartaPorte31"
        Version="3.1" TranspInternac="No" TotalDistRec="120">
      <cartaporte31:Mercancias PesoBrutoTotal="1500.5" UnidadPeso="KGM"/>
    </cartaporte31:CartaPorte>"""
    n = xml_a_nodos(_xml(extra_complemento=carta_porte))

    c = n["Comprobante"]
    assert c["Folio"] == "100"
    assert c["Emisor"]["Nombre"] == "EMISORA SA DE CV"
    assert c["Complemento"]["TimbreFiscalDigital"]["UUID"].startswith("AAAAAAAA")
    # Un complemento que el parser no entiende queda completo en nodos.
    assert c["Complemento"]["CartaPorte"]["Mercancias"]["PesoBrutoTotal"] == "1500.5"


def test_nodos_hijo_unico_es_dict_y_repetido_es_lista():
    uno = xml_a_nodos(_xml(conceptos=1))["Comprobante"]["Conceptos"]["Concepto"]
    tres = xml_a_nodos(_xml(conceptos=3))["Comprobante"]["Conceptos"]["Concepto"]
    assert isinstance(uno, dict)
    assert [c["Descripcion"] for c in tres] == ["Servicio 0", "Servicio 1", "Servicio 2"]


def test_nodos_atributo_que_choca_con_hijo_y_texto():
    n = xml_a_nodos(b'<Raiz Dato="attr"><Dato>texto</Dato></Raiz>')
    assert n == {"Raiz": {"@Dato": "attr", "Dato": {"#text": "texto"}}}


def test_valores_recorre_listas_y_tolera_rutas_inexistentes():
    n = xml_a_nodos(_xml(conceptos=2))
    assert valores(n, "Comprobante.Conceptos.Concepto.Importe") == ["500", "500"]
    assert valores(xml_a_nodos(_xml()), "Comprobante.Conceptos.Concepto.Importe") == ["500"]
    assert valores(n, "Comprobante.Addenda.Lo.Que.Sea") == []


# ---------------------------------------------------------------------------
# Documentos en la DB
# ---------------------------------------------------------------------------


def test_agregar_guarda_xml_original_y_nodos(db):
    xml = _xml()
    cfdi = parse_cfdi(xml)
    db.agregar([cfdi], mi_rfc=MI_RFC, xmls={cfdi.uuid: xml}, origen="manual")

    doc = db.documento(cfdi.uuid, MI_RFC)
    assert doc["xml"] == xml
    assert doc["nodos"]["Comprobante"]["Folio"] == "100"
    assert doc["nodos_version"] == NODOS_VERSION
    with db.cursor() as cur:
        origen = cur.execute("SELECT origen FROM cfdis WHERE uuid = ?", (cfdi.uuid,)).fetchone()[0]
    assert origen == "manual"


def test_duplicado_sin_documento_lo_recibe(db):
    xml = _xml()
    cfdi = parse_cfdi(xml)
    db.agregar([cfdi], mi_rfc=MI_RFC)  # cargado antes de la migración 010
    assert db.documento(cfdi.uuid, MI_RFC) is None

    r = db.agregar([parse_cfdi(xml)], mi_rfc=MI_RFC, xmls={cfdi.uuid: xml})
    assert r == {"agregados": 0, "duplicados": 1}
    assert db.documento(cfdi.uuid, MI_RFC)["xml"] == xml


def test_borrar_empresa_borra_sus_documentos(db):
    xml = _xml()
    cfdi = parse_cfdi(xml)
    db.agregar([cfdi], mi_rfc=MI_RFC, xmls={cfdi.uuid: xml})
    db.borrar(MI_RFC)
    assert db.documento(cfdi.uuid, MI_RFC) is None


def test_migracion_009_a_010_preserva_filas_y_completa_documento(tmp_path):
    """Upgrade real: una DB en v009 poblada sube a v010; la fila vieja queda sin
    origen ni documento, y al volver a indexar su XML recibe el documento."""
    ocultas = [
        (mig, tmp_path / f"{mig.name}.bak")
        for mig in sorted(db_mod.MIGRATIONS_DIR.glob("*.sql"))
        if int(mig.name[:3]) > 9
    ]
    db_path = tmp_path / "procesador.db"
    xml = _xml()

    db_mod.resetear_singleton_para_tests()
    try:
        for mig, fuera in ocultas:
            shutil.move(str(mig), str(fuera))
        vieja = db_mod.ProcesadorDB(db_path)
        try:
            with vieja.cursor() as c:
                c.execute("SELECT value FROM _meta WHERE key='schema_version'")
                assert c.fetchone()[0] == "9"
                c.execute(
                    "INSERT INTO cfdis (uuid, mi_rfc, tipo, fecha, emisor_rfc, receptor_rfc)"
                    " VALUES ('AAAAAAAA-1111-2222-3333-444444444444', ?, 'I',"
                    " '2026-05-15T10:00:00', 'AAA010101AAA', ?)",
                    (MI_RFC, MI_RFC),
                )
                c.connection.commit()
        finally:
            vieja.close()
    finally:
        # Restaurar las migraciones pase lo que pase (crítico para la suite).
        for mig, fuera in ocultas:
            if fuera.exists():
                shutil.move(str(fuera), str(mig))
        db_mod.resetear_singleton_para_tests()

    nueva = db_mod.ProcesadorDB(db_path)
    try:
        uuid = "AAAAAAAA-1111-2222-3333-444444444444"
        with nueva.cursor() as c:
            c.execute("SELECT value FROM _meta WHERE key='schema_version'")
            assert c.fetchone()[0] == str(db_mod.schema_version_actual())
            assert c.execute("SELECT origen FROM cfdis").fetchone()[0] is None
        assert nueva.documento(uuid, MI_RFC) is None

        r = nueva.agregar([parse_cfdi(xml)], mi_rfc=MI_RFC, xmls={uuid: xml})
        assert r == {"agregados": 0, "duplicados": 1}
        assert nueva.documento(uuid, MI_RFC)["xml"] == xml
    finally:
        nueva.close()


# ---------------------------------------------------------------------------
# indexar()
# ---------------------------------------------------------------------------


def test_indexar_filtra_otra_empresa_errores_y_fechas(db, tmp_path, monkeypatch):
    monkeypatch.setattr(indexar_mod, "LOTE", 2)  # fuerza varios lotes
    carpeta = tmp_path / "cfdi"
    (carpeta / "sub").mkdir(parents=True)
    for i in range(3):
        (carpeta / f"{i}.xml").write_bytes(
            _xml(uuid=f"AAAAAAAA-1111-2222-3333-00000000000{i}"))
    (carpeta / "sub" / "MAYUS.XML").write_bytes(
        _xml(uuid="AAAAAAAA-1111-2222-3333-000000000009"))
    (carpeta / "ajeno.xml").write_bytes(
        _xml(uuid="BBBBBBBB-1111-2222-3333-000000000000", receptor=OTRO_RFC))
    (carpeta / "viejo.xml").write_bytes(
        _xml(uuid="CCCCCCCC-1111-2222-3333-000000000000", fecha="2025-01-01T00:00:00"))
    (carpeta / "roto.xml").write_bytes(b"<no es un cfdi")
    (carpeta / "metadata.txt").write_text("no se toca")

    r = indexar_mod.indexar_carpeta(MI_RFC, carpeta, origen="carpeta", desde="2026-01-01")

    assert r["archivos_encontrados"] == 7
    assert (r["agregados"], r["duplicados"], r["omitidos_rfc"]) == (4, 0, 1)
    assert [e["filename"] for e in r["errores"]] == ["roto.xml"]
    assert db.documento("AAAAAAAA-1111-2222-3333-000000000009", MI_RFC) is not None

    # Volver a indexar la misma carpeta no duplica.
    r2 = indexar_mod.indexar_carpeta(MI_RFC, carpeta, origen="carpeta", desde="2026-01-01")
    assert (r2["agregados"], r2["duplicados"]) == (0, 4)


def test_descarga_de_cfdi_se_indexa_sola(db, tmp_path, monkeypatch):
    pytest.importorskip("fastapi")  # api/state.py; el CI corre sin el extra server
    from sat_descarga.api import state

    monkeypatch.delenv("SAT_DM_SIN_INDEXADO")
    salida = tmp_path / "descarga"
    salida.mkdir()
    (salida / "a.xml").write_bytes(_xml())

    hilos = []
    original = indexar_mod.indexar_descarga
    monkeypatch.setattr(indexar_mod, "indexar_descarga",
                        lambda *a: hilos.append(original(*a)) or hilos[-1])
    monkeypatch.setattr(config_store, "registrar_descarga", lambda *a, **k: None)

    state._registrar_descarga(MI_RFC, "ws", "cfdi", ruta=str(salida))
    state._registrar_descarga(MI_RFC, "fiel", "constancia", ruta=str(salida))

    assert len(hilos) == 1  # solo la de CFDI
    hilos[0].join(timeout=10)
    with db.cursor() as cur:
        assert cur.execute("SELECT origen FROM cfdis").fetchall()[0][0] == "sat_ws"


def test_descarga_con_subcarpetas_indexa_solo_lo_que_bajo(db, tmp_path, monkeypatch):
    """Dos huecos que bajan a la misma carpeta del rango: el segundo solo indexa
    sus paquetes, no lo del primero ni los XML servidos de la base."""
    pytest.importorskip("fastapi")
    from sat_descarga.api import state

    monkeypatch.delenv("SAT_DM_SIN_INDEXADO")
    salida = tmp_path / "rango"
    for pid in ("p1", "p2"):
        (salida / pid).mkdir(parents=True)
    (salida / "servido.xml").write_bytes(_xml())

    trabajos = []
    monkeypatch.setattr(indexar_mod, "indexar_descarga",
                        lambda rfc, ruta, canal, carpetas=None: trabajos.append(carpetas))
    registradas = []
    monkeypatch.setattr(config_store, "registrar_descarga",
                        lambda *a, **k: registradas.append(k["ruta"]))

    state._registrar_descarga(MI_RFC, "ws", "cfdi", ruta=str(salida), paquetes=["p1"])
    state._registrar_descarga(MI_RFC, "ws", "cfdi", ruta=str(salida), paquetes=["p2", "no_existe"])
    # Un solo trabajo por descarga, solo con las carpetas de sus paquetes.
    assert trabajos == [[str(salida / "p1")], [str(salida / "p2")]]
    assert registradas == [str(salida), str(salida)]

    trabajos.clear()
    state._registrar_descarga(MI_RFC, "ws", "cfdi", ruta=str(salida), paquetes=["no_existe"])
    assert trabajos == [[]]  # nada extraído: un trabajo sin carpetas (no lee la del rango)
    state._registrar_descarga(MI_RFC, "ws", "cfdi", ruta=str(salida))
    assert trabajos == [[], None]  # otros canales: la carpeta completa


def test_un_trabajo_sin_carpetas_no_lee_nada_pero_pone_al_dia_el_calendario(db, tmp_path, monkeypatch):
    salida = tmp_path / "rango"
    salida.mkdir()
    (salida / "servido.xml").write_bytes(_xml())
    sincronizadas = []
    monkeypatch.setattr(indexar_mod, "_sincronizar_calendario", lambda rfc: sincronizadas.append(rfc))
    indexar_mod._indexar_registrando(MI_RFC, str(salida), "sat_ws", carpetas=[])
    assert sincronizadas == [MI_RFC]
    with db.cursor() as cur:
        assert cur.execute("SELECT COUNT(*) FROM cfdis").fetchone()[0] == 0


def test_kill_switch_apaga_el_indexado_automatico(db, tmp_path):
    # conftest deja SAT_DM_SIN_INDEXADO=1
    assert indexar_mod.indexar_descarga(MI_RFC, str(tmp_path), "ws") is None
    assert indexar_mod.indexar_descargas_existentes(tmp_path) is None


def test_carpeta_existente_se_indexa_una_vez_por_empresa(db, tmp_path, monkeypatch):
    monkeypatch.delenv("SAT_DM_SIN_INDEXADO")
    monkeypatch.setattr(config_store, "list_empresas", lambda: [
        {"rfc": MI_RFC}, {"rfc": OTRO_RFC, "archived_at": "2026-01-01"},
    ])
    carpeta = tmp_path / "cfdi" / MI_RFC / "recibidos" / "2026-05-01_a_2026-05-31" / "pkg"
    carpeta.mkdir(parents=True)
    (carpeta / "a.xml").write_bytes(_xml())

    indexar_mod.indexar_descargas_existentes(tmp_path).join(timeout=10)
    assert db.count() == 1
    assert db.meta_get(f"indexado_carpeta:{MI_RFC}") == "1"
    assert db.meta_get(f"indexado_carpeta:{OTRO_RFC}") is None  # archivada

    # La segunda vez no vuelve a recorrer la carpeta.
    llamadas = []
    monkeypatch.setattr(indexar_mod, "indexar_carpeta", lambda *a, **k: llamadas.append(a))
    indexar_mod.indexar_descargas_existentes(tmp_path).join(timeout=10)
    assert llamadas == []


# ---------------------------------------------------------------------------
# Endpoint de carga manual
# ---------------------------------------------------------------------------


def test_endpoint_cargar_guarda_documento_con_origen_manual(db, tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from sat_descarga.api import server

    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "EFIRMA_DIR", tmp_path / "efirma")
    config_store.add_empresa_ciec(MI_RFC, "Empresa", "ciec123")
    client = TestClient(server.app)
    xml = _xml()

    r = client.post("/procesador/cfdi/cargar", data={"rfc": MI_RFC},
                    files=[("files", ("a.xml", xml, "text/xml"))])

    assert r.status_code == 200, r.text
    assert r.json()["agregados"] == 1
    assert db.documento("AAAAAAAA-1111-2222-3333-444444444444", MI_RFC)["xml"] == xml
    server._limpiar_session()
