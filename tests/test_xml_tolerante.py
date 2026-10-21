"""Lectura tolerante de CFDIs mal formados (p. ej. xmlns:schemaLocation inválido)."""

import pytest

from sat_descarga.cli import config_store
from sat_descarga.core.xml_seguro import AVISO_RECODIFICADO, leer_tolerante
from sat_descarga.procesador import db as db_mod
from sat_descarga.procesador import indexar as indexar_mod
from sat_descarga.procesador.cfdi_parser import CfdiParseError, parse_cfdi
from sat_descarga.procesador.nodos import valores, xml_a_nodos
from sat_descarga.procesador.validaciones import validar_y_anotar
from sat_descarga.utils.xml_reader import leer_cfdi

MI_RFC = "BBB020202BBB"
UUID = "AAAAAAAA-1111-2222-3333-444444444444"

REGISTRO_FISCAL = (
    '<registrofiscal:CFDIRegistroFiscal '
    'xmlns:registrofiscal="http://www.sat.gob.mx/registrofiscal" '
    'xmlns:schemaLocation="http://www.sat.gob.mx/registrofiscal '
    'http://www.sat.gob.mx/sitio_internet/cfd/cfdiregistrofiscal/cfdiregistrofiscal.xsd" '
    'Version="1.0" Folio="123"/>'
)


def _xml(complemento_extra="", descripcion="Servicio 1", uuid=UUID):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0" Serie="A" Folio="100" Fecha="2026-05-15T10:00:00" Sello="..."
    NoCertificado="000" Certificado="..." SubTotal="500" Moneda="MXN" Total="500"
    TipoDeComprobante="I" Exportacion="01" MetodoPago="PUE" FormaPago="03"
    LugarExpedicion="64000">
  <cfdi:Emisor Rfc="AAA010101AAA" Nombre="EMISORA SA DE CV" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="{MI_RFC}" Nombre="RECEPTORA" DomicilioFiscalReceptor="64000"
                 RegimenFiscalReceptor="612" UsoCFDI="G03"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="01010101" Cantidad="1" ClaveUnidad="ACT"
                   Descripcion="{descripcion}" ValorUnitario="500" Importe="500"
                   ObjetoImp="01"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>{complemento_extra}
    <tfd:TimbreFiscalDigital Version="1.1" UUID="{uuid}"
        FechaTimbrado="2026-05-15T10:00:00" RfcProvCertif="SAT970701NN3" SelloCFD="..."
        NoCertificadoSAT="000" SelloSAT="..."/>
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


def test_xml_valido_sin_avisos():
    xml = _xml()
    lectura = leer_tolerante(xml)
    assert lectura.avisos == ()
    assert lectura.sin_perdida is True  # nada que perder: el XML era válido
    assert lectura.recodificado is False
    assert parse_cfdi(xml).avisos_lectura == []


def test_schemalocation_se_lee_sin_perder_datos():
    xml = _xml(REGISTRO_FISCAL)
    lectura = leer_tolerante(xml)
    assert lectura.avisos and lectura.sin_perdida

    cfdi = parse_cfdi(xml)
    assert cfdi.uuid == UUID
    assert cfdi.emisor_rfc == "AAA010101AAA"
    assert cfdi.receptor_rfc == MI_RFC
    assert cfdi.total == 500
    assert len(cfdi.conceptos) == 1
    assert len(cfdi.avisos_lectura) == 1
    assert "sin perder datos" in cfdi.avisos_lectura[0]
    assert "xmlns:schemaLocation" in cfdi.avisos_lectura[0]

    validar_y_anotar(cfdi)
    assert cfdi.warnings[0] == cfdi.avisos_lectura[0]


def test_error_que_no_es_de_namespace_se_lee_con_aviso_de_posible_perdida():
    xml = _xml(descripcion="Cables & conexiones")
    assert not leer_tolerante(xml).sin_perdida
    cfdi = parse_cfdi(xml)
    assert cfdi.uuid == UUID
    assert "puede faltar información" in cfdi.avisos_lectura[0]
    assert "sin perder datos" not in cfdi.avisos_lectura[0]


PAGO_SIN_PREFIJO = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0" Fecha="2026-05-15T10:00:00" SubTotal="0" Moneda="XXX" Total="0"
    TipoDeComprobante="P" Exportacion="01" LugarExpedicion="64000">
  <cfdi:Emisor Rfc="AAA010101AAA" Nombre="EMISORA" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="BBB020202BBB" Nombre="RECEPTORA" UsoCFDI="CP01"/>
  <cfdi:Conceptos><cfdi:Concepto ClaveProdServ="84111506" Cantidad="1" ClaveUnidad="ACT"
      Descripcion="Pago" ValorUnitario="0" Importe="0" ObjetoImp="01"/></cfdi:Conceptos>
  <cfdi:Complemento>
    <pago20:Pagos Version="2.0" xsi:schemaLocation="http://www.sat.gob.mx/Pagos20 x.xsd">
      <pago20:Totales MontoTotalPagos="1160.00"/>
      <pago20:Pago FechaPago="2026-05-15T12:00:00" FormaDePagoP="03" MonedaP="MXN" Monto="1160.00">
        <pago20:DoctoRelacionado IdDocumento="BBBBBBBB-0000-0000-0000-000000000001"
            MonedaDR="MXN" NumParcialidad="1" ImpSaldoAnt="1160.00" ImpPagado="1160.00"
            ImpSaldoInsoluto="0.00"/>
      </pago20:Pago>
    </pago20:Pagos>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="AAAAAAAA-1111-2222-3333-444444444444"
        FechaTimbrado="2026-05-15T12:05:00" RfcProvCertif="SAT970701NN3" SelloCFD="..."
        NoCertificadoSAT="000" SelloSAT="..."/>
  </cfdi:Complemento>
</cfdi:Comprobante>""".encode()


def test_prefijo_sin_declarar_se_lee_sin_perder_datos():
    # Sin `xmlns:pago20` ni `xmlns:xsi`: el modo recover deja los nombres literales
    # (`pago20:Pagos`) y la lectura por nombre local los encuentra igual.
    lectura = leer_tolerante(PAGO_SIN_PREFIJO)
    assert lectura.avisos and lectura.sin_perdida
    cfdi = parse_cfdi(PAGO_SIN_PREFIJO)
    assert cfdi.datos_pago is not None and cfdi.datos_pago.monto_pago == 1160.0
    assert cfdi.datos_pago.documentos_relacionados[0].imp_pagado == 1160.0
    aviso = cfdi.avisos_lectura[0]
    assert "prefijo sin declarar: pago20" in aviso and "prefijo sin declarar: xsi" in aviso
    assert "sin perder datos" in aviso
    nodos = xml_a_nodos(PAGO_SIN_PREFIJO)  # antes: ValueError("Invalid tag name …")
    assert valores(nodos, "Comprobante.Complemento.Pagos.Pago.Monto") == ["1160.00"]
    assert "pago20:Pagos" not in nodos["Comprobante"]["Complemento"]


def test_raiz_sin_namespace_declarado_es_cfdi_igual():
    xml = _xml().replace(b'xmlns:cfdi="http://www.sat.gob.mx/cfd/4"', b"")
    cfdi = parse_cfdi(xml)
    assert cfdi.uuid == UUID and cfdi.emisor_rfc == "AAA010101AAA"
    assert "prefijo sin declarar: cfdi" in cfdi.avisos_lectura[0]


def test_comentario_dentro_del_comprobante_no_rompe_la_lectura():
    xml = _xml().replace(b"<cfdi:Conceptos>", b"<cfdi:Conceptos><!-- generado por X -->")
    assert parse_cfdi(xml).conceptos[0].importe == 500


def test_latin1_declarado_como_utf8_se_recodifica_sin_perder_datos():
    xml = _xml().replace(b"EMISORA SA DE CV", "PEÑA Y ASOCIADOS".encode("latin-1"))
    lectura = leer_tolerante(xml)
    assert lectura.recodificado and lectura.sin_perdida
    cfdi = parse_cfdi(xml)
    assert cfdi.emisor_nombre == "PEÑA Y ASOCIADOS"
    assert "Windows-1252" in cfdi.avisos_lectura[0]
    assert "sin perder datos" in cfdi.avisos_lectura[0]


def test_mezcla_de_utf8_valido_y_latin1_respeta_los_dos():
    xml = (_xml(descripcion="Señal")  # «ñ» en UTF-8 válido
           .replace(b"EMISORA SA DE CV", "MUÑOZ".encode("latin-1")))
    cfdi = parse_cfdi(xml)
    assert cfdi.emisor_nombre == "MUÑOZ"
    assert cfdi.conceptos[0].descripcion == "Señal"


def test_latin1_y_schemalocation_juntos_suman_los_dos_avisos():
    xml = _xml(REGISTRO_FISCAL).replace(b"EMISORA SA DE CV", "PEÑA".encode("latin-1"))
    cfdi = parse_cfdi(xml)
    assert cfdi.emisor_nombre == "PEÑA"
    aviso = cfdi.avisos_lectura[0]
    assert "Windows-1252" in aviso and "xmlns:schemaLocation" in aviso
    assert "sin perder datos" in aviso


def test_xml_que_declara_otra_codificacion_no_se_recodifica():
    xml = _xml().replace(b'encoding="UTF-8"', b'encoding="ISO-8859-1"').replace(
        b"EMISORA SA DE CV", "PEÑA".encode("latin-1"))
    lectura = leer_tolerante(xml)
    assert lectura.avisos == () and not lectura.recodificado
    assert parse_cfdi(xml).emisor_nombre == "PEÑA"


def test_truncado_sin_timbre_o_basura_se_rechaza():
    xml = _xml(REGISTRO_FISCAL)
    truncado = xml[: xml.index(b"<tfd:TimbreFiscalDigital")]
    with pytest.raises(CfdiParseError):
        parse_cfdi(truncado)
    with pytest.raises(CfdiParseError):
        parse_cfdi(b"esto no es xml")


def test_nodos_del_xml_con_schemalocation():
    nodos = xml_a_nodos(_xml(REGISTRO_FISCAL))
    assert valores(nodos, "Comprobante.Complemento.CFDIRegistroFiscal.Folio") == ["123"]
    assert valores(nodos, "Comprobante.Complemento.TimbreFiscalDigital.UUID") == [UUID]


def test_indexar_conserva_el_aviso(db):
    xml = _xml(REGISTRO_FISCAL)
    r = indexar_mod.indexar(MI_RFC, [("a.xml", xml)], origen="carpeta")
    assert r["agregados"] == 1
    assert r["errores"] == []
    items = db.listar({"mi_rfc": MI_RFC})["items"]
    assert any("sin perder datos" in w for w in items[0]["warnings"])
    assert db.count({"mi_rfc": MI_RFC, "solo_con_errores": True}) == 1
    doc = db.documento(UUID, MI_RFC)
    assert doc["xml"] == xml
    assert valores(doc["nodos"], "Comprobante.Complemento.CFDIRegistroFiscal.Folio") == ["123"]


def test_duplicado_con_documento_no_recalcula_nodos(db, monkeypatch):
    xml = _xml(REGISTRO_FISCAL)
    indexar_mod.indexar(MI_RFC, [("a.xml", xml)], origen="carpeta")
    preparados = []
    original = db_mod._preparar_documentos
    monkeypatch.setattr(db_mod, "_preparar_documentos",
                        lambda cfdis, xmls: preparados.append(len(cfdis)) or original(cfdis, xmls))
    r = indexar_mod.indexar(MI_RFC, [("a.xml", xml)], origen="carpeta")
    assert r["duplicados"] == 1
    assert preparados == [0]


def test_leer_cfdi_de_archivo_mal_formado(tmp_path):
    ruta = tmp_path / "x.xml"
    ruta.write_bytes(_xml(REGISTRO_FISCAL, uuid=UUID.lower()))
    header = leer_cfdi(str(ruta))
    assert header.uuid == UUID
    assert header.emisor_rfc == "AAA010101AAA"


def test_reindexado_por_version(db, tmp_path, monkeypatch):
    monkeypatch.delenv("SAT_DM_SIN_INDEXADO")
    monkeypatch.setattr(config_store, "list_empresas", lambda: [{"rfc": MI_RFC}])
    carpeta = tmp_path / "cfdi" / MI_RFC / "recibidos" / "2026-05-01_a_2026-05-31" / "pkg"
    carpeta.mkdir(parents=True)
    (carpeta / "a.xml").write_bytes(_xml(REGISTRO_FISCAL))
    llave = f"indexado_carpeta:{MI_RFC}"

    db.meta_set(llave, "1")
    indexar_mod.indexar_descargas_existentes(tmp_path).join(timeout=10)
    assert db.count() == 1
    assert db.meta_get(llave) == "2"

    llamadas = []
    monkeypatch.setattr(indexar_mod, "indexar_carpeta", lambda *a, **k: llamadas.append(a))
    indexar_mod.indexar_descargas_existentes(tmp_path).join(timeout=10)
    assert llamadas == []



def test_byte_que_no_existe_en_windows_1252_no_se_da_por_completo():
    xml = _xml().replace(b"EMISORA SA DE CV", b"EMISORA \x81 SA")
    lectura = leer_tolerante(xml)
    assert lectura.recodificado and not lectura.sin_perdida
    cfdi = parse_cfdi(xml)
    assert "puede faltar información" in cfdi.avisos_lectura[0]


def test_la_nota_de_recodificacion_va_primero_aunque_el_namespace_falle_antes():
    # El parser estricto tropieza primero con el namespace (está antes que el «Ñ»).
    xml = _xml(REGISTRO_FISCAL).replace(b"RECEPTORA", "MUÑOZ".encode("latin-1"))
    lectura = leer_tolerante(xml)
    assert lectura.avisos[0] == AVISO_RECODIFICADO
    assert any("xmlns:schemaLocation" in a for a in lectura.avisos[1:])
    assert len(lectura.avisos) == len(set(lectura.avisos))


def test_recuperar_sin_el_rfc_de_la_empresa_se_rechaza_y_se_reporta(db):
    # Una comilla suelta en el Nombre hace que el modo recover tire el Rfc.
    xml = _xml().replace(b'Rfc="BBB020202BBB" Nombre="RECEPTORA"',
                         b'Nombre="RECEP"TORA" Rfc="BBB020202BBB"')
    with pytest.raises(CfdiParseError, match="RFC del receptor"):
        parse_cfdi(xml)
    r = indexar_mod.indexar(MI_RFC, [("a.xml", xml)], origen="carpeta")
    assert r["agregados"] == 0 and r["omitidos_rfc"] == 0
    assert r["errores"] and "RFC del receptor" in r["errores"][0]["mensaje"]


def test_addenda_grande_es_xml_valido_sin_avisos():
    addenda = "<cfdi:Addenda><Pdf>" + ("A" * 11_000_000) + "</Pdf></cfdi:Addenda>"
    xml = _xml().replace(b"</cfdi:Comprobante>", addenda.encode() + b"</cfdi:Comprobante>")
    cfdi = parse_cfdi(xml)
    assert cfdi.uuid == UUID and cfdi.avisos_lectura == []


def test_el_organizador_no_usa_lecturas_con_perdida(tmp_path):
    ruta = tmp_path / "x.xml"
    ruta.write_bytes(_xml(descripcion="Cables & conexiones"))
    with pytest.raises(ValueError, match="mal formado"):
        leer_cfdi(str(ruta))


def test_reindexado_desde_la_version_1_solo_lee_los_mal_formados(db, tmp_path, monkeypatch):
    monkeypatch.delenv("SAT_DM_SIN_INDEXADO")
    monkeypatch.setattr(config_store, "list_empresas", lambda: [{"rfc": MI_RFC}])
    carpeta = tmp_path / "cfdi" / MI_RFC / "recibidos" / "2026-05-01_a_2026-05-31"
    carpeta.mkdir(parents=True)
    (carpeta / "bueno.xml").write_bytes(_xml(uuid="AAAAAAAA-1111-2222-3333-000000000001"))
    (carpeta / "malo.xml").write_bytes(_xml(REGISTRO_FISCAL))
    db.meta_set(f"indexado_carpeta:{MI_RFC}", "1")

    leidos = []
    original = indexar_mod.parse_cfdi
    monkeypatch.setattr(indexar_mod, "parse_cfdi",
                        lambda xml, file_name="": leidos.append(file_name) or original(xml, file_name))
    indexar_mod.indexar_descargas_existentes(tmp_path).join(timeout=10)
    assert leidos == ["malo.xml"]  # el bueno ya lo había indexado la versión 1
    assert db.count({"mi_rfc": MI_RFC}) == 1


def test_documento_que_se_borro_entre_candados_se_vuelve_a_guardar(db, monkeypatch):
    xml = _xml()
    cfdi = parse_cfdi(xml)
    # Simula que al empezar `agregar` el documento existía y luego se borró.
    monkeypatch.setattr(db, "_uuids_con_documento", lambda mi_rfc, uuids: set(uuids))
    db.agregar([cfdi], mi_rfc=MI_RFC, xmls={UUID: xml})
    assert db.documento(UUID, MI_RFC)["xml"] == xml
