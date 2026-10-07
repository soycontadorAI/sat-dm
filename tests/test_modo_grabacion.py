"""Modo de grabación (sat_descarga/demo): datos de ejemplo sin SAT.

Cubre:
- el escenario de los guiones (cifras exactas de septiembre de El Roble,
  pagos, nómina, listas negras, 32-D negativa con motivos);
- cada operación con el modo prendido y RFC de demo: no sale a la red;
- RFC reales con el modo prendido: siguen al SAT;
- modo apagado: nada cambia (los RFC de demo también van al SAT);
- la siembra de la cuenta de grabación y su limpieza.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from sat_descarga import demo
from sat_descarga.demo import catalogo, cfdi, documentos, efirma
from sat_descarga.demo import sat as sat_demo
from sat_descarga.demo.escenario import (
    CIEC_DEMO, EL_ROBLE, EMPRESAS, MOLINA, NORMA, PANADERIA, RFCS_DEMO,
)

AHORA = datetime(2026, 10, 19, 9, 30)
RFC_REAL = "XAXX010101000"


class _TocoAlSat(Exception):
    pass


@pytest.fixture(autouse=True)
def reloj(monkeypatch):
    """Corte fijo: el escenario es de septiembre de 2026 y se graba en octubre."""
    monkeypatch.setattr(cfdi, "_ahora", lambda: AHORA)
    monkeypatch.setattr(sat_demo, "_hoy", lambda: AHORA.date())
    monkeypatch.delenv("SAT_DM_MODO_GRABACION", raising=False)
    monkeypatch.setenv("SAT_DM_GRABACION_RITMO", "0")
    monkeypatch.setenv("SAT_DM_GRABACION_ESPERA", "0")


@pytest.fixture
def modo(monkeypatch):
    monkeypatch.setenv("SAT_DM_MODO_GRABACION", "1")


@pytest.fixture
def perfil(tmp_path, monkeypatch):
    from sat_descarga.cli import config_store
    from sat_descarga.procesador import db as db_mod

    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "EFIRMA_DIR", tmp_path / ".sat-descarga" / "efirma")
    monkeypatch.setattr(config_store, "descargas_dir_default", lambda: str(tmp_path / "TodoConta"))
    db_mod.resetear_singleton_para_tests()
    db_mod.abrir_db(tmp_path / "procesador.db")
    yield tmp_path
    db_mod.resetear_singleton_para_tests()


@pytest.fixture
def sin_red(monkeypatch):
    """Cualquier llamada al SAT (SOAP) truena: prueba que el modo no sale a la red."""
    from sat_descarga.utils import validacion
    from sat_descarga.webservice import auth, descarga, solicitud, verificacion

    def _no(*a, **k):
        raise _TocoAlSat(k.get("operation") or "SAT")

    for mod in (auth, solicitud, verificacion, descarga, validacion):
        monkeypatch.setattr(mod, "make_request", _no)


def _fiel_demo(rfc, tmp_path):
    from sat_descarga.core.fiel import FIEL

    cer, key, pwd = efirma.generar(rfc, tmp_path / "efirma-demo", AHORA.date())
    return FIEL(str(cer), str(key), pwd), (str(cer), str(key), pwd)


def _recibidos_sep():
    return [c for c in cfdi.comprobantes(EL_ROBLE, 2026, 9) if c.direccion == "R"]


# ---------------------------------------------------------------------------
# Interruptor
# ---------------------------------------------------------------------------

def test_apagado_por_default():
    assert not demo.activo()
    assert demo.es_demo(EL_ROBLE)
    assert not demo.aplica(EL_ROBLE)


def test_prendido_solo_para_rfc_de_demo(modo):
    assert demo.activo()
    assert demo.aplica(EL_ROBLE) and demo.aplica(EL_ROBLE.lower())
    assert not demo.aplica(RFC_REAL)
    assert not demo.aplica(None)


def test_espera_configurable(monkeypatch):
    monkeypatch.setenv("SAT_DM_GRABACION_ESPERA", "45")
    assert demo.espera_ws() == 45
    monkeypatch.setenv("SAT_DM_GRABACION_ESPERA", "no-es-numero")
    assert demo.espera_ws() == demo.ESPERA_WS_DEFAULT


def test_anuncio_en_el_log(modo, caplog):
    with caplog.at_level("WARNING", logger="sat_descarga.demo"):
        demo.anunciar()
    assert "modo-grabacion" in caplog.text and "ACTIVO" in caplog.text


# ---------------------------------------------------------------------------
# Escenario: las cifras de los guiones
# ---------------------------------------------------------------------------

def test_septiembre_de_el_roble_como_en_los_guiones():
    rec = _recibidos_sep()
    assert len(rec) == 1163
    assert len({c.emisor_rfc for c in rec}) == 87
    por_tipo = {}
    for c in rec:
        por_tipo[(c.tipo, c.metodo_pago)] = por_tipo.get((c.tipo, c.metodo_pago), 0) + 1
    assert por_tipo[("I", "PPD")] == 58
    assert por_tipo[("P", "")] == 42
    assert por_tipo[("E", "PUE")] == 18
    cancelados = cfdi.cancelados_despues(EL_ROBLE, 2026, 9)
    assert len(cancelados) == 3
    canc = [c for c in rec if c.uuid in cancelados]
    assert len({c.emisor_rfc for c in canc}) == 3  # de proveedores distintos
    assert all(c.tipo == "I" and c.metodo_pago == "PUE" for c in canc)
    # Proveedores en listas negras presentes en el mes.
    emisores = {c.emisor_rfc for c in rec}
    assert {"SAG990231KX4", "FMC120431RB7", "COR140230FN2"} <= emisores


def test_generador_determinista():
    antes = [(c.uuid, c.total, c.fecha) for c in _recibidos_sep()]
    xml_antes = cfdi.xml(_recibidos_sep()[100])
    cfdi._mes.cache_clear()
    despues = [(c.uuid, c.total, c.fecha) for c in _recibidos_sep()]
    assert antes == despues
    assert cfdi.xml(_recibidos_sep()[100]) == xml_antes


def test_solo_existe_lo_que_ya_paso(monkeypatch):
    monkeypatch.setattr(cfdi, "_ahora", lambda: datetime(2026, 9, 10, 0, 0))
    assert all(c.fecha <= datetime(2026, 9, 10) for c in cfdi.comprobantes(EL_ROBLE, 2026, 9))
    assert cfdi.comprobantes(EL_ROBLE, 2026, 11) == []
    assert cfdi.comprobantes(RFC_REAL, 2026, 9) == []


def test_xml_cfdi40_lo_lee_el_procesador_sin_avisos():
    from sat_descarga.procesador.cfdi_parser import parse_cfdi
    from sat_descarga.procesador.validaciones import validar

    for c in cfdi.comprobantes(EL_ROBLE, 2026, 9) + cfdi.comprobantes(PANADERIA, 2026, 9):
        d = parse_cfdi(cfdi.xml(c))
        assert d.uuid == c.uuid
        assert d.version == "4.0"
        assert d.tipo_comprobante == c.tipo
        assert validar(d) == [], (c.tipo, c.uuid)
        if c.tipo == "P":
            assert d.datos_pago is not None and d.datos_pago.documentos_relacionados
        if c.tipo == "N":
            assert d.datos_nomina is not None and d.datos_nomina.periodicidad_pago == "04"


def _cargar(db, rfc, meses, tipo):
    from sat_descarga.procesador.cfdi_parser import parse_cfdi

    parseados = [parse_cfdi(cfdi.xml(c)) for a, m in meses
                 for c in cfdi.comprobantes(rfc, a, m) if c.direccion == tipo]
    db.agregar(parseados, mi_rfc=rfc, direccion_fija=tipo)


@pytest.mark.parametrize("meses, huerfanos", [
    ([(2026, 9)], 3),                       # los 2 extemporáneos pagan facturas de julio
    ([(2026, 7), (2026, 8), (2026, 9)], 1),  # con julio cargado queda el huérfano real
])
def test_pagos_ppd_complementos_y_problemas(tmp_path, meses, huerfanos):
    from sat_descarga.procesador.db import ProcesadorDB
    from sat_descarga.procesador.reportes_pagos import stats_pagos

    db = ProcesadorDB(tmp_path / "p.db")
    _cargar(db, EL_ROBLE, meses, "R")
    st = stats_pagos(db, {"mi_rfc": EL_ROBLE, "desde": "2026-09-01", "hasta": "2026-09-30"})
    assert st["total_ingresos_ppd"] == 58
    assert (st["pagos_completos"], st["pagos_parciales"], st["sin_complemento"]) == (30, 12, 16)
    assert st["complementos_extemporaneos"] == 2
    assert st["incidencias_pue"] == 1
    assert st["pagos_huerfanos"] == huerfanos
    db.close()


def test_nomina_quincenal_de_panaderia(tmp_path):
    from sat_descarga.procesador.db import ProcesadorDB
    from sat_descarga.procesador.reportes_nomina import reporte_deducibilidad, stats_nomina

    db = ProcesadorDB(tmp_path / "p.db")
    _cargar(db, PANADERIA, [(2026, 9)], "E")
    st = stats_nomina(db, {"mi_rfc": PANADERIA})
    assert (st["total_recibos"], st["total_empleados"]) == (28, 14)
    ded = reporte_deducibilidad(db, {"mi_rfc": PANADERIA})
    diferencias = {e["nombre"]: round(e["diferencia"], 2)
                   for e in ded["desglose_por_empleado"] if abs(e["diferencia"]) > 1}
    # Una sola retención corta a propósito (el reporte "ISR teórico contra retenido").
    assert list(diferencias) == ["LUIS FERNANDO AGUILAR RIOS"]
    db.close()


def test_rfc_de_contrapartes_ficticios_con_fecha_imposible():
    import re

    patron = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")
    rfcs = catalogo.rfcs_del_escenario() - RFCS_DEMO
    assert rfcs
    for rfc in rfcs:
        assert patron.match(rfc), rfc
        assert sat_demo._fecha_imposible(rfc), rfc
    nombres = {}
    for perfil in catalogo.PERFILES.values():
        for c in (*perfil.proveedores, *perfil.clientes):
            assert nombres.setdefault(c.rfc, c.nombre) == c.nombre  # sin choques
    for emp in catalogo.EMPLEADOS[PANADERIA]:
        assert len(emp.curp) == 18 and len(emp.nss) == 11


# ---------------------------------------------------------------------------
# Documentos y e.firma de ejemplo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rfc", sorted(RFCS_DEMO))
def test_constancia_y_opinion_las_leen_los_parsers(tmp_path, rfc):
    from sat_descarga.utils.csf_parser import parsear_csf
    from sat_descarga.utils.opinion_parser import parsear_opinion

    emp = EMPRESAS[rfc]
    csf = parsear_csf(documentos.constancia_pdf(rfc, tmp_path / "csf.pdf", AHORA.date()))
    assert (csf.rfc, csf.nombre, csf.tipo_persona) == (rfc, emp.nombre, emp.tipo)
    assert [r.clave for r in csf.regimenes] == [c for c, _, _ in emp.regimenes]
    assert csf.actividades and csf.actividades[0].principal

    op = parsear_opinion(documentos.opinion_pdf(rfc, tmp_path / "op.pdf", AHORA.date()))
    assert (op.rfc, op.sentido) == (rfc, emp.opinion)
    if rfc == NORMA:
        assert [m.titulo for m in op.motivos] == ["Cumplimiento de obligaciones", "Créditos fiscales"]
        assert len(op.motivos[0].detalles) == 3
    else:
        assert op.motivos == []


def test_pdf_lleva_la_marca_de_ejemplo(tmp_path):
    import pdfplumber

    ruta = documentos.opinion_pdf(NORMA, tmp_path / "op.pdf", AHORA.date())
    with pdfplumber.open(ruta) as pdf:
        assert "DOCUMENTO DE EJEMPLO" in pdf.pages[0].extract_text()


def test_captcha_es_png():
    texto, png = documentos.captcha_png(semilla=3)
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and len(texto) == 6


def test_efirma_de_ejemplo_la_abre_la_app(tmp_path):
    fiel, _ = _fiel_demo(NORMA, tmp_path)
    assert fiel.rfc == NORMA
    assert fiel.legal_name == "Norma Reyes Aguilar"
    assert (fiel.not_valid_after.date() - AHORA.date()).days == 4
    assert efirma.es_certificado_de_ejemplo(fiel)
    pm, _ = _fiel_demo(EL_ROBLE, tmp_path)
    assert pm.rfc == EL_ROBLE


def test_alta_de_efirma_de_ejemplo_solo_con_el_modo(perfil, monkeypatch):
    from sat_descarga.cli import config_store

    cer, key, pwd = efirma.generar(PANADERIA, perfil / "e", AHORA.date())
    with pytest.raises(ValueError, match="ejemplo"):
        config_store.add_empresa("", str(cer), str(key), pwd)
    monkeypatch.setenv("SAT_DM_MODO_GRABACION", "1")
    assert config_store.add_empresa("", str(cer), str(key), pwd) == PANADERIA


# ---------------------------------------------------------------------------
# Web Service
# ---------------------------------------------------------------------------

def test_web_service_de_demo_sin_red(modo, perfil, sin_red, monkeypatch):
    from sat_descarga.webservice.auth import obtener_token
    from sat_descarga.webservice.descarga import descargar_todos
    from sat_descarga.webservice.solicitud import solicitar_descarga
    from sat_descarga.webservice.verificacion import consultar_solicitud

    fiel, _ = _fiel_demo(EL_ROBLE, perfil)
    token = obtener_token(fiel)
    monkeypatch.setenv("SAT_DM_GRABACION_ESPERA", "3600")
    id_sol = solicitar_descarga(fiel, token, EL_ROBLE, date(2026, 9, 1), date(2026, 9, 30),
                                tipo_comprobante="R", estado_comprobante="Vigente")
    en_proceso = consultar_solicitud(token, EL_ROBLE, id_sol, fiel)
    assert en_proceso.cod_estado in ("1", "2") and not en_proceso.terminada

    monkeypatch.setenv("SAT_DM_GRABACION_ESPERA", "0")
    lista = consultar_solicitud(token, EL_ROBLE, id_sol, fiel)
    assert (lista.cod_estado, lista.numero_cfdis, lista.terminada) == ("3", 1163, True)
    assert lista.package_ids == [f"{id_sol.upper()}_01"]

    salida = perfil / "salida"
    zips = descargar_todos(token, EL_ROBLE, lista.package_ids, str(salida), fiel)
    assert len(zips) == 1 and zips[0].exists()
    assert len(list(salida.rglob("*.xml"))) == 1163


def test_web_service_otra_empresa_no_ve_la_solicitud(modo, perfil, sin_red):
    from sat_descarga.webservice.verificacion import consultar_solicitud

    id_sol = sat_demo.solicitar(EL_ROBLE, date(2026, 9, 1), date(2026, 9, 30), "CFDI", "R")
    estado = consultar_solicitud("t", PANADERIA, id_sol)
    assert estado.cod_estado == "" and estado.cod_estatus == "5004"


def test_web_service_periodo_sin_cfdis_es_rechazo_como_el_sat(modo, perfil, sin_red):
    id_sol = sat_demo.solicitar(EL_ROBLE, date(2021, 1, 1), date(2021, 1, 31), "CFDI", "R")
    estado = sat_demo.verificar(EL_ROBLE, id_sol)
    assert (estado.cod_estado, estado.mensaje) == ("5", "No se encontró la información")


def test_metadata_de_demo(modo, perfil, sin_red):
    from sat_descarga.webservice.client import descargar_metadata

    _, (cer, key, pwd) = _fiel_demo(EL_ROBLE, perfil)
    registros = descargar_metadata(cer, key, pwd, date(2026, 9, 1), date(2026, 9, 30),
                                   directorio_salida=str(perfil / "meta"), tipo_comprobante="R")
    assert len(registros) == 1163
    assert {r.rfc_receptor for r in registros} == {EL_ROBLE}


def test_web_service_rfc_real_sigue_al_sat(modo, sin_red, test_cer, test_key, test_password):
    from sat_descarga.core.fiel import FIEL
    from sat_descarga.webservice.auth import obtener_token
    from sat_descarga.webservice.solicitud import solicitar_descarga

    fiel = FIEL(test_cer, test_key, test_password)
    assert fiel.rfc == RFC_REAL
    with pytest.raises(_TocoAlSat):
        obtener_token(fiel)
    with pytest.raises(_TocoAlSat):
        solicitar_descarga(fiel, "t", RFC_REAL, date(2026, 9, 1), date(2026, 9, 30))


def test_modo_apagado_la_empresa_de_demo_va_al_sat(sin_red, tmp_path):
    from sat_descarga.webservice.auth import obtener_token
    from sat_descarga.webservice.solicitud import solicitar_descarga

    fiel, _ = _fiel_demo(EL_ROBLE, tmp_path)
    with pytest.raises(_TocoAlSat):
        obtener_token(fiel)
    with pytest.raises(_TocoAlSat):
        solicitar_descarga(fiel, "t", EL_ROBLE, date(2026, 9, 1), date(2026, 9, 30))


# ---------------------------------------------------------------------------
# Portal: Descarga rápida, constancia, opinión
# ---------------------------------------------------------------------------

def test_descarga_rapida_con_contrasena_pide_captcha(modo, perfil):
    from sat_descarga.portal.cfdi import descargar_cfdi_ciec

    vistos = []

    def pedir(img, intento, maximo):
        vistos.append((img[:8], intento, maximo))
        return "K7PQ2X"

    archivos = descargar_cfdi_ciec(MOLINA, CIEC_DEMO, date(2026, 9, 1), date(2026, 9, 30),
                                   tipo_comprobante="R", directorio_salida=str(perfil / "c"),
                                   max_registros=500, pedir_captcha=pedir)
    esperados = [c for c in cfdi.comprobantes(MOLINA, 2026, 9) if c.direccion == "R"]
    assert len(archivos) == len(esperados) > 100
    assert vistos == [(b"\x89PNG\r\n\x1a\n", 1, 3)]
    assert all("recibidos/2026-09-01_a_2026-09-30" in str(a) for a in archivos)


def test_descarga_rapida_respeta_el_tope(modo, perfil):
    from sat_descarga.portal.cfdi import descargar_cfdi_ciec

    archivos = descargar_cfdi_ciec(MOLINA, CIEC_DEMO, date(2026, 9, 1), date(2026, 9, 30),
                                   tipo_comprobante="R", directorio_salida=str(perfil / "c"),
                                   max_registros=20, pedir_captcha=lambda *a: "X")
    assert len(archivos) == 20


def test_captcha_cancelado(modo, perfil):
    from sat_descarga.portal.cfdi import descargar_cfdi_ciec

    with pytest.raises(RuntimeError, match="cancelado"):
        descargar_cfdi_ciec(MOLINA, CIEC_DEMO, date(2026, 9, 1), date(2026, 9, 30),
                            directorio_salida=str(perfil / "c"), pedir_captcha=lambda *a: None)


def test_constancia_y_opinion_por_portal(modo, perfil):
    from sat_descarga.portal.constancia import descargar_constancia_ciec
    from sat_descarga.portal.opinion import descargar_opinion_fiel
    from sat_descarga.utils.opinion_parser import parsear_opinion

    pdf = descargar_constancia_ciec(MOLINA, CIEC_DEMO, directorio_salida=str(perfil / "csf"),
                                    pedir_captcha=lambda *a: "X")
    assert pdf.name == f"constancia_{MOLINA}_20261019.pdf" and pdf.exists()

    _, (cer, key, pwd) = _fiel_demo(NORMA, perfil)
    op = descargar_opinion_fiel(cer, key, pwd, directorio_salida=str(perfil / "op"))
    assert op.name == f"opinion32d_{NORMA}_20261019.pdf"
    assert parsear_opinion(op).sentido == "negativa"


def test_tramite_no_simulado_no_abre_el_portal(modo):
    from sat_descarga.portal.login import OperacionNoSimulada, iniciar_sesion_ciec

    with pytest.raises(OperacionNoSimulada):
        iniciar_sesion_ciec(None, NORMA, "x", "https://portal", lambda url: True)


# ---------------------------------------------------------------------------
# Estatus y listas negras
# ---------------------------------------------------------------------------

def test_estatus_de_demo_tres_cancelados(modo, sin_red):
    from sat_descarga.utils.validacion import validar_masivo

    rec = _recibidos_sep()
    res = validar_masivo([{"uuid": c.uuid, "emisor_rfc": c.emisor_rfc,
                           "receptor_rfc": c.receptor_rfc, "total": c.total} for c in rec])
    cancelados = {r.uuid for r in res if r.estado == "Cancelado"}
    assert cancelados == cfdi.cancelados_despues(EL_ROBLE, 2026, 9)
    assert sum(r.estado == "Vigente" for r in res) == 1160


def test_estatus_mezclado_real_va_al_sat(modo, sin_red):
    from sat_descarga.utils.validacion import validar_cfdi

    real = validar_cfdi("11111111-1111-4111-8111-111111111111", RFC_REAL, "AAA010101AAA", 10.0)
    assert real.estado == "Error"  # intentó salir a la red (y la prueba lo cortó)
    cancelados = cfdi.cancelados_despues(EL_ROBLE, 2026, 9)
    vigente = next(c for c in _recibidos_sep() if c.uuid not in cancelados)
    demo_res = validar_cfdi(vigente.uuid, vigente.emisor_rfc, EL_ROBLE, vigente.total)
    assert demo_res.estado == "Vigente"
    cancelado = validar_cfdi(sorted(cancelados)[0], "AAA010101AAA", EL_ROBLE, 1.0)
    assert cancelado.estado == "Cancelado"


def test_estatus_modo_apagado_va_al_sat(sin_red):
    from sat_descarga.utils.validacion import validar_cfdi

    assert validar_cfdi(_recibidos_sep()[0].uuid, "AAA010101AAA", EL_ROBLE, 1.0).estado == "Error"


def test_listas_negras_demo_sin_red_y_reales_a_la_api(modo, monkeypatch):
    from sat_descarga.utils import listas_negras as ln

    llamadas = []

    def red(rfcs):
        llamadas.append(list(rfcs))
        return ([ln.MatchListaNegra(r, False, None, None, False) for r in rfcs],
                ln.ListasMetadata("2026-10-05T06:00:00+00:00", "2026-10-05T06:00:00+00:00"))

    monkeypatch.setattr(ln, "_consultar_rfcs_red", red)
    matches, meta = ln.consultar_rfcs(["SAG990231KX4", "fmc120431rb7", "AAA010101AAA"])
    assert llamadas == [["AAA010101AAA"]]
    por = {m.rfc: m for m in matches}
    assert por["SAG990231KX4"].es_efos and por["SAG990231KX4"].situacion_69b == "Definitivo"
    assert ln.clasificar(por["FMC120431RB7"]) == "69"
    assert ln.clasificar(por["AAA010101AAA"]) == "Limpio"

    llamadas.clear()
    solo_demo, meta = ln.consultar_rfcs(["COR140230FN2"])
    assert llamadas == [] and solo_demo[0].supuestos_69 == ["No localizados"]
    assert meta.lista_69b_updated_at  # sin sesión: el corte de ejemplo


def test_listas_negras_modo_apagado_van_a_la_api(monkeypatch):
    from sat_descarga.utils import listas_negras as ln

    llamadas = []
    monkeypatch.setattr(ln, "_consultar_rfcs_red",
                        lambda rfcs: (llamadas.append(list(rfcs)) or ([], ln.ListasMetadata(None, None))))
    ln.consultar_rfcs(["SAG990231KX4"])
    assert llamadas == [["SAG990231KX4"]]
    with pytest.raises(RuntimeError):
        ln.consultar_metadata()  # sin sesión y sin modo: el error de siempre


# ---------------------------------------------------------------------------
# Cupo de descargas del plan
# ---------------------------------------------------------------------------

def test_lo_de_demo_no_gasta_descargas_del_mes(modo):
    from sat_descarga.api import cupo_descargas

    antes = cupo_descargas.usadas_del_mes()
    cupo_descargas.registrar("cfdi", rfc=EL_ROBLE)
    assert cupo_descargas.usadas_del_mes() == antes
    cupo_descargas.registrar("cfdi", rfc=RFC_REAL)
    assert cupo_descargas.usadas_del_mes() == antes + 1


# ---------------------------------------------------------------------------
# Siembra
# ---------------------------------------------------------------------------

def test_siembra_requiere_el_modo(perfil):
    from sat_descarga.demo.siembra import ModoApagado, sembrar

    with pytest.raises(ModoApagado):
        sembrar(ahora=AHORA, avisar=lambda *_: None)


def test_siembra_de_la_cuenta_de_grabacion(modo, perfil):
    from sat_descarga.cli import config_store
    from sat_descarga.demo.siembra import sembrar
    from sat_descarga.procesador import abrir_db

    assert sorted(sembrar(ahora=AHORA, avisar=lambda *_: None)) == sorted(RFCS_DEMO)
    emp = {e["rfc"]: e for e in config_store.list_empresas()}
    assert set(emp) == set(RFCS_DEMO)
    assert emp[MOLINA]["metodos"] == ["ciec"]
    assert config_store.get_empresa(MOLINA)["ciec"] == CIEC_DEMO
    assert emp[EL_ROBLE]["default"]
    # Semáforos de la pieza 2.
    assert emp[NORMA]["opinion_status"] == "negativa" and len(emp[NORMA]["opinion_motivos"]) == 2
    assert emp["COV110714AB2"]["opinion_status"] == "positiva"
    assert emp[MOLINA]["opinion_status"] == "positiva"
    assert emp[PANADERIA]["opinion_path"] and emp[PANADERIA]["opinion_status"] is None
    assert not emp[EL_ROBLE]["opinion_path"] and not emp["GACL850312H40"]["opinion_path"]
    assert not emp[PANADERIA]["csf_path"] and not emp[MOLINA]["csf_path"]
    assert emp[EL_ROBLE]["csf_path"] and emp[EL_ROBLE]["regimenes_fiscales"][0]["clave"] == "601"
    assert emp[NORMA]["vencimiento"] == "2026-10-23"  # 4 días después de sembrar
    # Historial: meses anteriores ya descargados, nada de septiembre de El Roble.
    sols = config_store.list_solicitudes(EL_ROBLE)
    assert {(s["fecha_inicio"], s["estado"]) for s in sols} >= {
        ("2026-07-01", "descargada"), ("2026-08-01", "descargada")}
    assert all(s["fecha_inicio"] != "2026-09-01" for s in sols)
    historial = config_store.list_todas_descargas()
    assert len(historial) >= 15
    assert all(h["timestamp"] <= AHORA.isoformat() for h in historial)
    # Nómina de septiembre de Panadería ya en el procesador (pieza 4).
    with abrir_db().cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM cfdis WHERE mi_rfc = ? AND tipo = 'N'", (PANADERIA,))
        assert cur.fetchone()[0] == 28

    # Idempotente.
    n_hist, n_sol = len(historial), len(sols)
    sembrar(ahora=AHORA, avisar=lambda *_: None)
    assert len(config_store.list_todas_descargas()) == n_hist
    assert len(config_store.list_solicitudes(EL_ROBLE)) == n_sol


def test_siembra_respeta_empresa_dada_de_alta_a_mano(modo, perfil):
    """Pieza 1: El Roble se da de alta en cuadro (⌘N) y luego se siembra el resto."""
    from sat_descarga.cli import config_store
    from sat_descarga.demo.siembra import sembrar

    cer, key, pwd = efirma.generar(EL_ROBLE, perfil / "e", AHORA.date())
    config_store.add_empresa("", str(cer), str(key), pwd)
    cer_antes = config_store.get_empresa(EL_ROBLE)["cer_path"]
    sembrar(ahora=AHORA, excluir=[PANADERIA], historial_cfdi=False, avisar=lambda *_: None)
    emp = {e["rfc"]: e for e in config_store.list_empresas()}
    assert PANADERIA not in emp and EL_ROBLE in emp
    assert config_store.get_empresa(EL_ROBLE)["cer_path"] == cer_antes
    assert emp[EL_ROBLE]["csf_path"]  # sus documentos sí se siembran
    assert config_store.list_solicitudes(EL_ROBLE) == []


def test_siembra_con_septiembre(modo, perfil):
    from sat_descarga.cli import config_store
    from sat_descarga.demo.siembra import sembrar

    sembrar(ahora=AHORA, con_septiembre=True, historial_cfdi=False, avisar=lambda *_: None)
    sep = [s for s in config_store.list_solicitudes(EL_ROBLE) if s["fecha_inicio"] == "2026-09-01"]
    assert len(sep) == 1 and sep[0]["numero_cfdis"] == 1163


def test_limpiar_solo_quita_lo_de_demo(modo, perfil):
    from sat_descarga.cli import config_store
    from sat_descarga.demo.siembra import limpiar, sembrar

    config_store.add_empresa_ciec(RFC_REAL, "Empresa real", "secreta")
    sembrar(ahora=AHORA, con_septiembre=True, historial_cfdi=False, avisar=lambda *_: None)
    base = Path(config_store.get_descargas_dir())
    assert (base / "cfdi" / EL_ROBLE).exists()
    limpiar(avisar=lambda *_: None)
    assert [e["rfc"] for e in config_store.list_empresas()] == [RFC_REAL]
    assert not (base / "cfdi" / EL_ROBLE).exists()
    assert config_store.get_empresa(RFC_REAL)["ciec"] == "secreta"


def test_carpeta_xml_con_duplicados(tmp_path):
    from sat_descarga.demo.siembra import carpeta_xml

    n = carpeta_xml(tmp_path, desde=(2025, 1), hasta=(2025, 3), duplicados=5)
    archivos = list(tmp_path.glob("*.xml"))
    assert len(archivos) == n
    assert sum(1 for a in archivos if "(1)" in a.name or a.name.startswith("Copia de")) == 5


def test_config_dir_por_variable(tmp_path):
    env = {**os.environ, "SAT_DM_CONFIG_DIR": str(tmp_path / "perfil")}
    out = subprocess.run(
        [sys.executable, "-c",
         "from sat_descarga.cli import config_store as c; print(c.CONFIG_DIR)"],
        env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out == str(tmp_path / "perfil")


def test_cli_perfil_imprime_las_variables(tmp_path):
    out = subprocess.run(
        [sys.executable, "-m", "sat_descarga.demo", "perfil", "--dir", str(tmp_path / "p")],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "export SAT_DM_MODO_GRABACION=1" in out
    assert "SAT_DM_CONFIG_DIR=" in out and "SAT_DM_SECRETS_KEY=" in out
    # La clave es estable entre corridas (si no, el perfil perdería sus secretos).
    otra = subprocess.run(
        [sys.executable, "-m", "sat_descarga.demo", "perfil", "--dir", str(tmp_path / "p")],
        capture_output=True, text=True, check=True,
    ).stdout
    assert out == otra


def test_contrasena_de_ejemplo_no_va_al_portal_con_el_modo_apagado():
    from sat_descarga.portal.login import CredencialCIECInvalida, iniciar_sesion_ciec

    with pytest.raises(CredencialCIECInvalida, match="ejemplo"):
        iniciar_sesion_ciec(None, MOLINA, CIEC_DEMO, "https://portal", lambda url: True)
