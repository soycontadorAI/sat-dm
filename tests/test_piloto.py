"""Descarga automática (api/piloto.py): pasada diaria, cierre mensual, errores y API.

Todo contra el SAT simulado del modo de grabación (sin red), con el reloj fijo
en la Ciudad de México y una empresa de demo con pocos CFDI.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from sat_descarga.cli import config_store  # noqa: E402
from sat_descarga.procesador import calendario  # noqa: E402
from sat_descarga.webservice import solicitud as solicitud_mod  # noqa: E402

ORIGINAL_SOLICITAR = solicitud_mod.solicitar_descarga

RFC = "GACL850312H40"  # Laura García Cervantes: pocos CFDI y con e.firma
AHORA = datetime(2026, 10, 13, 9, 0, tzinfo=calendario.ZONA_MX)


def _reaplicar_entorno(entorno, monkeypatch):
    """Perfil aislado, SAT simulado y reloj fijo."""
    from sat_descarga.api import piloto
    from sat_descarga.demo import cfdi as demo_cfdi
    from sat_descarga.demo import sat as sat_demo
    from sat_descarga.procesador import indexar as indexar_mod

    tmp_path, reloj = entorno.tmp, entorno.reloj
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "EFIRMA_DIR", tmp_path / ".sat-descarga" / "efirma")
    monkeypatch.setattr(config_store, "descargas_dir_default", lambda: str(tmp_path / "TodoConta"))
    monkeypatch.setenv("SAT_DM_MODO_GRABACION", "1")
    monkeypatch.setenv("SAT_DM_GRABACION_ESPERA", "0")
    monkeypatch.setenv("SAT_DM_GRABACION_RITMO", "0")
    monkeypatch.setenv("SAT_DM_SIN_USO", "1")
    monkeypatch.delenv("SAT_DM_SIN_INDEXADO", raising=False)
    monkeypatch.setattr(calendario, "ahora_mx", lambda: reloj["ahora"])
    monkeypatch.setattr(demo_cfdi, "_ahora", lambda: reloj["ahora"].replace(tzinfo=None))
    monkeypatch.setattr(sat_demo, "_hoy", lambda: reloj["ahora"].date())
    monkeypatch.setattr(piloto, "disponible", lambda: True)
    monkeypatch.setattr(piloto, "_escalonar", lambda: None)
    monkeypatch.setattr(piloto, "_desfase_min", lambda: 0)
    # El indexado de cada descarga, en el mismo hilo (sin esperar hilos de fondo).
    monkeypatch.setattr(indexar_mod, "_en_hilo", lambda nombre, fn, *a: fn(*a))


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    from sat_descarga.api import piloto, poller
    from sat_descarga.demo import efirma
    from sat_descarga.procesador import db as db_mod

    ent = SimpleNamespace(reloj={"ahora": AHORA}, tmp=tmp_path)
    _reaplicar_entorno(ent, monkeypatch)
    db_mod.resetear_singleton_para_tests()
    db_mod.abrir_db(tmp_path / "procesador.db")
    poller._fiel_cache.clear()
    poller._proxima_verificacion.clear()
    piloto._efirma_rechequeo.clear()

    cer, key, pwd = efirma.generar(RFC, tmp_path / "e", AHORA.date())
    config_store.add_empresa("", str(cer), str(key), pwd)
    yield ent
    poller._fiel_cache.clear()
    db_mod.resetear_singleton_para_tests()


def _activar(entorno, cuando=None):
    from sat_descarga.api import piloto

    if cuando is not None:
        entorno.reloj["ahora"] = cuando
    piloto.configurar(activo=True)


def _procesar():
    """Una pasada del poller sobre la empresa (verifica y baja lo que esté listo)."""
    from sat_descarga.api import poller

    poller._proxima_verificacion.clear()
    emp = next(e for e in config_store.list_empresas() if e["rfc"] == RFC)
    poller._procesar_empresa(RFC, emp)


def _del_piloto(proposito=None):
    return [s for s in config_store.list_solicitudes(RFC) if s.get("origen") == "piloto"
            and (proposito is None or s.get("proposito") == proposito)]


def _fila(fecha, d):
    f = date.fromisoformat(fecha)
    return calendario.filas(RFC, f, f).get((fecha, d))


def _indexar_mes(anio, mes, saltar=()):
    """Mete al índice el mes de la empresa como si ya se hubiera descargado."""
    from sat_descarga.demo import cfdi as demo_cfdi
    from sat_descarga.procesador import indexar as indexar_mod

    ini = date(anio, mes, 1)
    fin = (date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)) - timedelta(days=1)
    comps = [c for c in demo_cfdi.en_rango(RFC, ini, fin) if c.uuid not in set(saltar)]
    indexar_mod.indexar(RFC, [(f"{c.uuid}.xml", demo_cfdi.xml(c)) for c in comps], origen="sat_ws")
    return comps


def _falla_solicitud(monkeypatch, error):
    """Las solicitudes de CFDI de la pasada diaria fallan con `error` (la metadata
    del cierre sigue al SAT simulado). Devuelve las llamadas de CFDI."""
    from sat_descarga.webservice import solicitud

    llamadas = []
    original = solicitud.solicitar_descarga

    def _solicitar(**kw):
        if kw.get("tipo_solicitud") != "CFDI":
            return original(**kw)
        llamadas.append(kw)
        raise error

    monkeypatch.setattr(solicitud, "solicitar_descarga", _solicitar)
    return llamadas


# ---------------------------------------------------------------------------
# Cuándo corre
# ---------------------------------------------------------------------------


def test_inactivo_o_sin_capacidad_no_hace_nada(entorno, monkeypatch):
    from sat_descarga.api import piloto

    assert piloto.evaluar() == {"corrio": False, "motivo": "inactivo"}
    _activar(entorno)
    monkeypatch.setattr(piloto, "disponible", lambda: False)
    assert piloto.evaluar() == {"corrio": False, "motivo": "licencia"}
    assert _del_piloto() == []


def test_sesion_cerrada_pausa_el_piloto(entorno, monkeypatch):
    from sat_descarga.api import piloto

    _activar(entorno)
    monkeypatch.setattr(piloto, "_sesion_cerrada", lambda: True)
    assert piloto.evaluar()["motivo"] == "sesion"
    assert _del_piloto() == []


def test_antes_de_la_hora_no_pide_y_despues_si(entorno):
    from sat_descarga.api import piloto

    _activar(entorno, AHORA.replace(hour=0, minute=30))
    piloto.evaluar()
    assert _del_piloto("diaria") == []
    entorno.reloj["ahora"] = AHORA.replace(hour=1, minute=5)
    piloto.evaluar()
    assert len(_del_piloto("diaria")) == 2


# ---------------------------------------------------------------------------
# Pasada diaria
# ---------------------------------------------------------------------------


def test_pasada_diaria_pide_d3_a_d1_y_el_poller_la_baja(entorno):
    from sat_descarga.api import piloto
    from sat_descarga.demo import cfdi as demo_cfdi

    _activar(entorno)
    piloto.evaluar()
    sols = _del_piloto("diaria")
    assert sorted((s["tipo_comprobante"], s["fecha_inicio"], s["fecha_fin"]) for s in sols) == [
        ("E", "2026-10-10", "2026-10-12"), ("R", "2026-10-10", "2026-10-12")]
    assert all(s["tipo_solicitud"] == "CFDI" and s["periodo"] == "2026-10-13" for s in sols)
    assert _fila("2026-10-11", "R")["estado"] == "en_proceso"
    # Candado: otra evaluación el mismo día no vuelve a pedir.
    piloto.evaluar()
    assert len(_del_piloto("diaria")) == 2

    _procesar()
    calendario.sincronizar(RFC)
    esperados = len(demo_cfdi.en_rango(RFC, date(2026, 10, 11), date(2026, 10, 11), "R"))
    fila = _fila("2026-10-11", "R")
    assert fila["estado"] == "provisional" and fila["total_bd"] == esperados
    # No consume el cupo de descargas del mes.
    from sat_descarga.api import cupo_descargas

    assert cupo_descargas.estado().usadas == 0


def test_la_ventana_salta_dias_cerrados_y_con_solicitud_viva(entorno):
    from sat_descarga.api import piloto

    _activar(entorno)
    calendario.cerrar_dias(RFC, {("2026-10-11", "E"): ("consolidado", 1, None)})
    config_store.save_solicitud(RFC, "VIVA", "2026-10-12", "2026-10-12", "CFDI · recibidos",
                                tipo_comprobante="R")
    v = piloto.ventana_diaria(RFC, AHORA.date())
    assert v["E"] == [date(2026, 10, 10), date(2026, 10, 12)]
    assert v["R"] == [date(2026, 10, 10), date(2026, 10, 11)]


def test_al_abrir_la_app_se_pone_al_corriente(entorno):
    from sat_descarga.api import piloto

    _activar(entorno, AHORA.replace(day=1))
    piloto.evaluar()
    _procesar()
    # Diez días con la app cerrada: al volver, una solicitud por dirección cubre
    # lo que nadie pidió más el rezago de los últimos 3 días.
    entorno.reloj["ahora"] = AHORA
    piloto.evaluar()
    hoy = [s for s in _del_piloto("diaria") if s["periodo"] == "2026-10-13"]
    assert sorted((s["tipo_comprobante"], s["fecha_inicio"], s["fecha_fin"]) for s in hoy) == [
        ("E", "2026-10-01", "2026-10-12"), ("R", "2026-10-01", "2026-10-12")]


def test_rangos_se_juntan_si_son_demasiados():
    from sat_descarga.api import piloto

    dias = [date(2026, 10, d) for d in (1, 3, 5, 7, 9, 20)]
    rangos = piloto._rangos(dias)
    assert len(rangos) == piloto.MAX_RANGOS
    assert rangos[-1] == (date(2026, 10, 20), date(2026, 10, 20))
    assert piloto._rangos([date(2026, 10, 2), date(2026, 10, 3)]) == [
        (date(2026, 10, 2), date(2026, 10, 3))]


# ---------------------------------------------------------------------------
# Errores del SAT
# ---------------------------------------------------------------------------


def test_5002_es_error_sin_reintentos(entorno, monkeypatch):
    from sat_descarga.api import piloto

    llamadas = _falla_solicitud(monkeypatch, RuntimeError(
        "El SAT rechazó la solicitud: CodEstatus=5002, Se han agotado las solicitudes de por vida"))
    _activar(entorno)
    piloto.evaluar()
    assert len(llamadas) == 2  # una por dirección
    # Sin el truco de variar los segundos (gasta la cuota del SAT).
    assert all(k["reintentar_5002"] is False for k in llamadas)
    fila = _fila("2026-10-11", "E")
    assert fila["estado"] == "error" and fila["error_codigo"] == "5002"
    entorno.reloj["ahora"] = AHORA + timedelta(hours=5)
    piloto.evaluar()
    assert len(llamadas) == 2


def test_falla_transitoria_reintenta_con_espera_y_a_los_3_dias_es_error(entorno, monkeypatch):
    import requests

    from sat_descarga.api import piloto

    llamadas = _falla_solicitud(monkeypatch, requests.ConnectionError("SAT caído"))
    _activar(entorno)
    piloto.evaluar()
    assert len(llamadas) == 2 and _fila("2026-10-11", "R")["estado"] == "en_proceso"
    ej = piloto._fila(RFC, "diaria", "2026-10-13")
    assert ej["estado"] == "en_curso" and ej["intentos"] == 1
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=10)
    piloto.evaluar()
    assert len(llamadas) == 2  # todavía no toca
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=31)
    piloto.evaluar()
    assert len(llamadas) == 4
    # Al día siguiente la falla de ayer se sigue reintentando y la pasada nueva
    # no vuelve a pedir esos días.
    entorno.reloj["ahora"] = AHORA + timedelta(days=1, hours=2)
    piloto.evaluar()
    hoy = [k for k in llamadas[4:] if k["fecha_inicio"] == date(2026, 10, 13)]
    assert len(llamadas) == 8 and len(hoy) == 2  # 2 reintentos de ayer + 2 de la pasada nueva
    entorno.reloj["ahora"] = AHORA + timedelta(hours=73)
    piloto.evaluar()
    ej = piloto._fila(RFC, "diaria", "2026-10-13")
    assert ej["estado"] == "error"
    fila = _fila("2026-10-11", "R")
    assert fila["estado"] == "error" and "3 días" in fila["error_mensaje"]


def test_al_vencer_el_plazo_no_se_pisan_dias_cerrados_ni_con_datos(entorno, monkeypatch):
    import requests

    from sat_descarga.api import piloto
    from sat_descarga.demo import cfdi as demo_cfdi
    from sat_descarga.procesador import indexar as indexar_mod

    _falla_solicitud(monkeypatch, requests.ConnectionError("SAT caído"))
    _activar(entorno)
    piloto.evaluar()
    # Mientras se reintenta, el cierre consolida un día del rango y otro llega por
    # otro camino (una descarga del portal, una carpeta).
    calendario.cerrar_dias(RFC, {("2026-10-10", "R"): ("consolidado", 0, None)})
    comps = demo_cfdi.en_rango(RFC, date(2026, 10, 12), date(2026, 10, 12), "R")
    indexar_mod.indexar(RFC, [(f"{c.uuid}.xml", demo_cfdi.xml(c)) for c in comps], origen="sat_ws")
    calendario.sincronizar(RFC)
    entorno.reloj["ahora"] = AHORA + timedelta(hours=73)
    piloto.evaluar()
    assert piloto._fila(RFC, "diaria", "2026-10-13")["estado"] == "error"
    assert _fila("2026-10-10", "R")["estado"] == "consolidado"
    assert _fila("2026-10-12", "R")["estado"] == "provisional"
    assert _fila("2026-10-11", "E")["estado"] == "error"


def test_5005_no_burla_al_sat_y_deja_los_dias_en_proceso(entorno, monkeypatch):
    from sat_descarga.api import piloto

    llamadas = _falla_solicitud(monkeypatch, RuntimeError(
        "CodEstatus=5005, Ya se tiene una solicitud registrada"))
    _activar(entorno)
    piloto.evaluar()
    assert len(llamadas) == 2  # una por dirección: sin variar segundos ni reintentar
    assert _fila("2026-10-11", "E")["estado"] == "en_proceso"
    assert piloto._fila(RFC, "diaria", "2026-10-13")["estado"] == "completa"


def test_efirma_rechazada_es_error_inmediato_con_aviso(entorno, monkeypatch):
    from sat_descarga.api import piloto

    _falla_solicitud(monkeypatch, RuntimeError("CodEstatus=305, Certificado Inválido"))
    _activar(entorno)
    piloto.evaluar()
    fila = _fila("2026-10-11", "E")
    assert fila["estado"] == "error" and fila["error_codigo"] == "305"
    assert piloto._fila(RFC, "diaria", "2026-10-13")["estado"] == "error"
    assert any(a["tipo"] == "efirma" for a in piloto.avisos())


def test_efirma_que_no_abre_salta_la_empresa(entorno, monkeypatch):
    from sat_descarga.api import piloto, poller

    _activar(entorno)
    monkeypatch.setattr(poller, "_fiel_de", lambda rfc: None)
    piloto.evaluar()
    assert _del_piloto() == []
    assert any(a["tipo"] == "efirma" for a in piloto.avisos())


def test_empresa_excluida_o_vencida_no_entra(entorno):
    from sat_descarga.api import piloto

    _activar(entorno)
    config_store.set_piloto_incluida(RFC, False)
    piloto.evaluar()
    assert _del_piloto() == []
    est = {e["rfc"]: e for e in piloto.estado()["empresas"]}
    assert est[RFC]["incluida"] is False and est[RFC]["motivo"] == "No incluida"


def test_candado_dos_evaluaciones_a_la_vez_no_duplican(entorno):
    from sat_descarga.api import piloto

    _activar(entorno)
    assert piloto._reservar(RFC, "diaria", "2026-10-13") is True
    assert piloto._reservar(RFC, "diaria", "2026-10-13") is False
    with piloto._evaluando:
        assert piloto.evaluar() == {"corrio": False, "motivo": "ocupado"}


def test_dos_hilos_evaluando_piden_una_sola_vez(entorno):
    from sat_descarga.api import piloto

    _activar(entorno)
    hilos = [threading.Thread(target=piloto.evaluar) for _ in range(4)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=30)
    assert len(_del_piloto("diaria")) == 2


# ---------------------------------------------------------------------------
# Cierre mensual
# ---------------------------------------------------------------------------


def _cerrar_septiembre(entorno, vueltas=4):
    from sat_descarga.api import piloto

    for _ in range(vueltas):
        piloto.evaluar()
        _procesar()
    return piloto._fila(RFC, "cierre", "2026-09")


def test_cierre_pide_metadata_y_lo_que_falta_y_consolida(entorno):
    from sat_descarga.api import piloto
    from sat_descarga.demo import cfdi as demo_cfdi

    _activar(entorno)
    ej = _cerrar_septiembre(entorno)
    assert ej["estado"] == "completa", ej
    meta = _del_piloto("cierre_metadata")
    assert sorted(s["tipo_comprobante"] for s in meta) == ["E", "R"]
    assert all(s["tipo_solicitud"] == "Metadata" and s["fecha_inicio"] == "2025-10-01"
               and s["fecha_fin"] == "2026-09-30" for s in meta)
    # La base estaba vacía: lo que faltaba se pidió por días.
    assert _del_piloto("cierre_faltantes")
    sep = calendario.filas(RFC, date(2026, 9, 1), date(2026, 9, 30))
    assert len(sep) == 60 and {f["estado"] for f in sep.values()} == {"consolidado"}
    un_dia = demo_cfdi.en_rango(RFC, date(2026, 9, 15), date(2026, 9, 15), "R")
    fila = _fila("2026-09-15", "R")
    assert fila["total_sat"] == fila["total_bd"] == len(un_dia)
    assert any(a["tipo"] == "resumen" and "septiembre de 2026 completo" in a["mensaje"]
               for a in piloto.avisos())
    # La metadata quedó aparte de los XML y se registró como metadata.
    hist = config_store.list_descargas(RFC)
    assert any(h["tipo"] == "metadata" and "/metadata/" in h["ruta"] for h in hist)


def test_cierre_con_pocos_faltantes_los_pide_por_folio(entorno):
    from sat_descarga.api import piloto

    comps = _indexar_mes(2026, 9)
    faltan = [comps[0].uuid, comps[-1].uuid]
    from sat_descarga.procesador.db import abrir_db

    with abrir_db().transaccion() as conn:
        conn.executemany("DELETE FROM cfdis WHERE uuid = ? AND mi_rfc = ?",
                         [(u, RFC) for u in faltan])
    _activar(entorno)
    ej = _cerrar_septiembre(entorno)
    assert ej["estado"] == "completa"
    folios = _del_piloto("cierre_faltantes")
    assert len(folios) == 1 and sorted(folios[0]["uuids"]) == sorted(faltan)
    assert "/folios/" in config_store.list_descargas(RFC)[0]["ruta"] or any(
        "/folios/" in h["ruta"] for h in config_store.list_descargas(RFC))
    assert {f["estado"] for f in calendario.filas(RFC, date(2026, 9, 1), date(2026, 9, 30)).values()} \
        == {"consolidado"}


def test_lo_que_el_sat_no_entrega_queda_en_diferencia(entorno, monkeypatch):
    from sat_descarga.api import piloto
    from sat_descarga.demo import sat as sat_demo

    comps = _indexar_mes(2026, 9)
    perdido = comps[3]
    from sat_descarga.procesador.db import abrir_db

    with abrir_db().transaccion() as conn:
        conn.execute("DELETE FROM cfdis WHERE uuid = ? AND mi_rfc = ?", (perdido.uuid, RFC))
    original = sat_demo._comprobantes
    monkeypatch.setattr(sat_demo, "_comprobantes",
                        lambda sol: [] if sol.get("uuids") else original(sol))
    _activar(entorno)
    ej = _cerrar_septiembre(entorno)
    assert ej["estado"] == "completa"
    dia = perdido.fecha.date().isoformat()
    fila = _fila(dia, perdido.direccion)
    assert fila["estado"] == "diferencia"
    assert fila["total_sat"] == fila["total_bd"] + 1 and perdido.uuid in fila["error_mensaje"]
    assert ej["detalle"]["resumen"]["dias_con_diferencia"] == 1
    assert any(a["tipo"] == "resumen" and "con diferencias" in a["mensaje"] for a in piloto.avisos())


def test_cancelaciones_de_meses_ya_cerrados_avisan(entorno, monkeypatch):
    from sat_descarga.api import piloto
    from sat_descarga.demo import cfdi as demo_cfdi

    agosto = _indexar_mes(2026, 8)
    _indexar_mes(2026, 9)
    cancelado = agosto[0]
    original = demo_cfdi.cancelados_despues
    monkeypatch.setattr(demo_cfdi, "cancelados_despues",
                        lambda rfc, a, m: frozenset({cancelado.uuid}) if (a, m) == (2026, 8)
                        else original(rfc, a, m))
    _activar(entorno)
    _cerrar_septiembre(entorno)
    from sat_descarga.procesador.db import abrir_db

    with abrir_db().cursor() as cur:
        estado, fecha_canc = cur.execute(
            "SELECT estado_sat, fecha_cancelacion FROM cfdis WHERE uuid = ?", (cancelado.uuid,)
        ).fetchone()
    assert estado == "Cancelado" and fecha_canc
    avisos = [a for a in piloto.avisos() if a["tipo"] == "cancelacion"]
    assert len(avisos) == 1 and avisos[0]["periodo"] == "2026-08"
    assert cancelado.uuid in avisos[0]["mensaje"]


def test_el_cierre_espera_a_las_diarias_que_tocan_el_mes(entorno):
    from sat_descarga.api import piloto

    _activar(entorno)
    config_store.save_solicitud(RFC, "VIVA", "2026-09-29", "2026-10-01", "CFDI · emitidos",
                                tipo_comprobante="E")
    piloto.evaluar()
    assert _del_piloto("cierre_metadata") == []
    ej = piloto._fila(RFC, "cierre", "2026-09")
    assert ej is None or ej["detalle"].get("paso", "inicio") == "inicio"


def test_el_cierre_espera_los_reintentos_de_las_diarias_del_mes(entorno, monkeypatch):
    import requests

    from sat_descarga.api import piloto

    _falla_solicitud(monkeypatch, requests.ConnectionError("SAT caído"))
    _activar(entorno, datetime(2026, 10, 2, 9, 0, tzinfo=calendario.ZONA_MX))
    piloto.evaluar()  # la pasada del 2 pide del 29 sep al 1 oct y el SAT no responde
    entorno.reloj["ahora"] = datetime(2026, 10, 5, 8, 0, tzinfo=calendario.ZONA_MX)
    piloto.evaluar()
    # Ya es día de cierre, pero esos días siguen en reintento: no hay solicitud
    # viva que lo diga y aun así septiembre espera.
    assert _del_piloto("cierre_metadata") == []
    monkeypatch.setattr(solicitud_mod, "solicitar_descarga", ORIGINAL_SOLICITAR)
    entorno.reloj["ahora"] = datetime(2026, 10, 5, 11, 0, tzinfo=calendario.ZONA_MX)
    piloto.evaluar()  # el reintento sale
    assert piloto._fila(RFC, "diaria", "2026-10-02")["estado"] == "completa"
    _procesar()
    piloto.evaluar()
    assert len(_del_piloto("cierre_metadata")) == 2


def test_el_cierre_indexa_lo_que_bajo_antes_de_comparar(entorno, monkeypatch):
    """El poller indexa en segundo plano: si el cierre compara antes de que ese
    hilo termine, lo que ya bajó no debe quedar como diferencia."""
    from sat_descarga.procesador import indexar as indexar_mod

    monkeypatch.setattr(indexar_mod, "_en_hilo", lambda nombre, fn, *a: None)
    _activar(entorno)
    ej = _cerrar_septiembre(entorno)
    assert ej["estado"] == "completa" and ej["detalle"]["resumen"]["dias_con_diferencia"] == 0
    sep = calendario.filas(RFC, date(2026, 9, 1), date(2026, 9, 30))
    assert {f["estado"] for f in sep.values()} == {"consolidado"}


def test_metadata_lista_sin_paquetes_no_es_ilegible(entorno):
    from sat_descarga.api import piloto

    config_store.save_solicitud(RFC, "VACIA", "2025-10-01", "2026-09-30", "Metadata · emitidos",
                                tipo_comprobante="E", tipo_solicitud="Metadata")
    config_store.update_solicitud(RFC, "VACIA", "descargada", numero_cfdis=0)
    assert piloto._leer_metadata(RFC, {"E": "VACIA"}) == []
    # Con registros y sin carpeta (se borró): no se compara contra nada.
    config_store.save_solicitud(RFC, "BORRADA", "2025-10-01", "2026-09-30", "Metadata · recibidos",
                                tipo_comprobante="R", tipo_solicitud="Metadata")
    config_store.update_solicitud(RFC, "BORRADA", "descargada", numero_cfdis=12)
    assert piloto._leer_metadata(RFC, {"E": "VACIA", "R": "BORRADA"}) is None


def test_la_metadata_viva_de_antes_se_reusa(entorno):
    """Una solicitud de metadata guardada sin `tipo_solicitud` (las de antes) se
    reconoce por su tipo: se reusa en vez de provocar un 5005."""
    from sat_descarga.api import piloto

    config_store.save_solicitud(RFC, "META", "2025-10-01", "2026-09-30", "Metadata · emitidos",
                                tipo_comprobante="E")
    desde, hasta = date(2025, 10, 1), date(2026, 9, 30)
    assert piloto._igual(RFC, desde, hasta, "E", "Metadata", None) == "META"
    assert piloto._igual(RFC, desde, hasta, "E", "CFDI", None) is None
    assert ("2026-09-15", "E") not in piloto._cubiertos_por_vivas(RFC)


def test_meses_vencidos_con_la_app_cerrada_y_respiro_del_rezago(entorno):
    from sat_descarga.api import piloto

    _activar(entorno, AHORA.replace(month=8, day=10))
    entorno.reloj["ahora"] = AHORA
    assert piloto.meses_por_cerrar(RFC) == ["2026-09", "2026-08", "2026-07"]
    # Con día de cierre 1, el cierre igual espera el rezago (día 4).
    piloto.configurar(dia_cierre=1)
    assert piloto._fecha_cierre("2026-09", 1) == date(2026, 10, 4)
    # Un cierre que toca al SAT por vuelta.
    piloto.evaluar()
    assert len({s["periodo"] for s in _del_piloto("cierre_metadata")}) == 1


def test_metadata_ilegible_se_vuelve_a_pedir(entorno, monkeypatch):
    from sat_descarga.api import piloto

    _activar(entorno)
    piloto.evaluar()
    _procesar()  # baja la metadata
    monkeypatch.setattr(piloto, "_leer_metadata", lambda rfc, ids: None)
    piloto.evaluar()
    ej = piloto._fila(RFC, "cierre", "2026-09")
    assert ej["estado"] == "en_curso" and ej["detalle"]["paso"] == "inicio"
    assert not calendario.filas(RFC, date(2026, 9, 1), date(2026, 9, 30))  # nada se cerró
    # Con la espera y el plazo de cualquier falla del SAT (no en cada vuelta).
    assert ej["intentos"] == 1 and ej["proximo_intento"] > piloto._utc(AHORA)
    metadata = len(_del_piloto("cierre_metadata"))
    piloto.evaluar()
    assert len(_del_piloto("cierre_metadata")) == metadata
    for horas in (1, 4, 11, 24, 49, 74):
        entorno.reloj["ahora"] = AHORA + timedelta(hours=horas)
        piloto.evaluar()
        _procesar()
    ej = piloto._fila(RFC, "cierre", "2026-09")
    assert ej["estado"] == "error" and "no se pudo leer" in ej["error_mensaje"]
    assert any(a["tipo"] == "error" for a in piloto.avisos())


# ---------------------------------------------------------------------------
# Reintentar un día
# ---------------------------------------------------------------------------


def test_reintentar_un_dia_con_error(entorno):
    from sat_descarga.api import piloto

    _activar(entorno)
    calendario.marcar(RFC, date(2026, 9, 3), date(2026, 9, 3), "E", "error",
                      error_codigo="5002", error_mensaje="Agotadas")
    r = piloto.reintentar(RFC, date(2026, 9, 3), "E")
    assert r["ok"] and _fila("2026-09-03", "E")["estado"] == "en_proceso"
    sol = config_store.get_solicitud(RFC, r["id_solicitud"])
    assert sol["proposito"] == "reintento" and sol["fecha_inicio"] == "2026-09-03"
    with pytest.raises(ValueError):
        piloto.reintentar(RFC, date(2026, 9, 4), "E")  # no está en error


def test_reintentar_un_dia_de_un_mes_cerrado_lo_vuelve_a_comparar(entorno, monkeypatch):
    """La petición no toca el cierre (solo lo escribe el hilo del piloto); cuando
    la solicitud termina, el mes se compara otra vez con la metadata que tenía."""
    from sat_descarga.api import piloto
    from sat_descarga.demo import sat as sat_demo
    from sat_descarga.procesador.db import abrir_db

    comps = _indexar_mes(2026, 9)
    perdido = comps[3]
    with abrir_db().transaccion() as conn:
        conn.execute("DELETE FROM cfdis WHERE uuid = ? AND mi_rfc = ?", (perdido.uuid, RFC))
    original = sat_demo._comprobantes
    monkeypatch.setattr(sat_demo, "_comprobantes",
                        lambda sol: [] if sol.get("uuids") else original(sol))
    _activar(entorno)
    cierre = _cerrar_septiembre(entorno)
    dia, direccion = perdido.fecha.date(), perdido.direccion
    assert _fila(dia.isoformat(), direccion)["estado"] == "diferencia"
    metadata = len(_del_piloto("cierre_metadata"))

    r = piloto.reintentar(RFC, dia, direccion)
    assert _fila(dia.isoformat(), direccion)["estado"] == "en_proceso"
    assert piloto._fila(RFC, "cierre", "2026-09") == cierre
    piloto.evaluar()  # la solicitud sigue viva: nada que comparar todavía
    assert piloto._fila(RFC, "cierre", "2026-09")["estado"] == "completa"

    _procesar()  # el reintento por días sí trae el CFDI
    piloto.evaluar()
    cierre = piloto._fila(RFC, "cierre", "2026-09")
    assert cierre["estado"] == "completa"
    assert cierre["detalle"]["resumen"]["dias_con_diferencia"] == 0
    fila = _fila(dia.isoformat(), direccion)
    assert fila["estado"] == "consolidado" and fila["total_sat"] == fila["total_bd"]
    assert len(_del_piloto("cierre_metadata")) == metadata  # sin pedir otra metadata
    assert config_store.get_solicitud(RFC, r["id_solicitud"])["recomparada"] is True
    piloto.evaluar()
    assert piloto._fila(RFC, "cierre", "2026-09") == cierre  # no se reabre otra vez


# ---------------------------------------------------------------------------
# Poller y catálogo
# ---------------------------------------------------------------------------


def test_lista_sin_bajar_por_mas_de_72_horas_vence(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    config_store.save_solicitud(RFC, "S1", "2026-09-01", "2026-09-01", "CFDI · emitidos",
                                tipo_comprobante="E")
    config_store.update_solicitud(RFC, "S1", "3")
    assert config_store.get_solicitud(RFC, "S1")["lista_en"]
    assert config_store.marcar_solicitudes_vencidas(RFC) == []
    ruta = config_store._solicitudes_path(RFC)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["solicitudes"][0]["lista_en"] = "2026-01-01T00:00:00"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    vencidas = config_store.marcar_solicitudes_vencidas(RFC)
    assert [v["id_solicitud"] for v in vencidas] == ["S1"]
    assert "vencieron" in config_store.get_solicitud(RFC, "S1")["mensaje"]


def test_save_solicitud_guarda_los_campos_estructurados(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    config_store.save_solicitud(RFC, "S1", "", "", "CFDI · folios", tipo_comprobante="R",
                                tipo_solicitud="CFDI", uuids=["A"], origen="piloto",
                                proposito="cierre_faltantes", periodo="2026-09", nada=None)
    sol = config_store.get_solicitud(RFC, "S1")
    assert sol["uuids"] == ["A"] and sol["origen"] == "piloto" and "nada" not in sol


def test_salidas_de_metadata_y_folios(tmp_path, monkeypatch):
    from sat_descarga.api import state

    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "descargas_dir_default", lambda: str(tmp_path / "TodoConta"))
    config_store.save_solicitud(RFC, "M1", "2026-09-01", "2026-09-30", "Metadata · emitidos",
                                tipo_comprobante="E", tipo_solicitud="Metadata")
    config_store.save_solicitud(RFC, "F1", "", "", "CFDI · folios", tipo_comprobante="R",
                                uuids=["A"])
    assert state._salida_descarga_ws(RFC, "M1").endswith(
        f"metadata/{RFC}/emitidos/2026-09-01_a_2026-09-30")
    assert state._salida_descarga_ws(RFC, "F1").endswith(f"cfdi/{RFC}/folios/F1")


def test_poller_verifica_las_del_piloto_a_lo_mas_cada_10_minutos(entorno, monkeypatch):
    from sat_descarga.api import piloto, poller

    _activar(entorno)
    piloto.evaluar()
    consultas = []
    monkeypatch.setattr(poller, "consultar_solicitud",
                        lambda *a, **k: consultas.append(a) or SimpleNamespace(
                            cod_estado="", package_ids=[], mensaje="", numero_cfdis=0,
                            cod_estatus="", codigo_estado_solicitud=""))
    emp = next(e for e in config_store.list_empresas() if e["rfc"] == RFC)
    poller._proxima_verificacion.clear()
    poller._procesar_empresa(RFC, emp)
    n = len(consultas)
    poller._procesar_empresa(RFC, emp)
    assert n >= 2 and len(consultas) == n


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture
def cliente(entorno):
    from fastapi.testclient import TestClient

    from sat_descarga.api import server

    yield TestClient(server.app)
    server._limpiar_session()


def test_api_estado_y_configuracion(cliente, monkeypatch):
    from sat_descarga.api import piloto

    est = cliente.get("/piloto/estado").json()
    assert est["activo"] is False and est["disponible"] is True and est["dia_cierre"] == 5
    assert est["empresas"][0]["rfc"] == RFC and est["empresas"][0]["elegible"] is True
    assert set(est) >= {"proxima_pasada", "cierre", "ejecuciones", "avisos", "pausado_por"}

    monkeypatch.setattr(piloto, "disponible", lambda: False)
    r = cliente.put("/piloto/config", json={"activo": True})
    assert r.status_code == 402 and r.json()["codigo"] == "piloto"

    monkeypatch.setattr(piloto, "disponible", lambda: True)
    r = cliente.put("/piloto/config", json={"activo": True, "dia_cierre": 8})
    assert r.status_code == 200 and r.json()["activo"] is True and r.json()["dia_cierre"] == 8
    assert config_store.get_piloto_config()["activado_en"]
    assert cliente.put("/piloto/config", json={"dia_cierre": 31}).status_code == 422

    r = cliente.put(f"/empresas/{RFC}/piloto", json={"incluida": False})
    assert r.status_code == 200
    assert cliente.put("/empresas/CCC030303CCC/piloto", json={"incluida": True}).status_code == 404


def test_api_reintentar_y_avisos(cliente, monkeypatch):
    from sat_descarga.api import piloto

    r = cliente.post(f"/calendario/{RFC}/reintentar", json={"fecha": "2026-09-03", "direccion": "E"})
    assert r.status_code == 400  # el día no está en error
    piloto._avisar("resumen", "Hola", clave="x")
    avisos = cliente.get("/piloto/estado").json()["avisos"]
    assert avisos[0]["mensaje"] == "Hola"
    assert cliente.post("/piloto/avisos/leidos", json={}).json()["marcados"] == 1
    assert cliente.get("/piloto/estado").json()["avisos"] == []
    monkeypatch.setattr(piloto, "disponible", lambda: False)
    r = cliente.post(f"/calendario/{RFC}/reintentar", json={"fecha": "2026-09-03", "direccion": "E"})
    assert r.status_code == 402


def test_una_vuelta_sin_trabajo_no_abre_la_efirma(entorno, monkeypatch):
    from sat_descarga.api import piloto, poller

    _activar(entorno)
    _cerrar_septiembre(entorno)  # pasada del día y cierre listos
    abiertas = []
    original = poller._fiel_de
    monkeypatch.setattr(poller, "_fiel_de", lambda rfc: abiertas.append(rfc) or original(rfc))
    piloto.evaluar()
    assert abiertas == []  # leerla toca el llavero del sistema


def test_error_de_efirma_se_reintenta_a_las_6_horas(entorno, monkeypatch):
    from sat_descarga.api import piloto

    llamadas = _falla_solicitud(monkeypatch, RuntimeError("CodEstatus=305, Certificado Inválido"))
    _activar(entorno)
    piloto.evaluar()
    assert len(llamadas) == 1  # la primera dirección falla y la pasada se detiene
    ej = piloto._fila(RFC, "diaria", "2026-10-13")
    assert ej["estado"] == "error" and ej["detalle"]["reintentable"]
    entorno.reloj["ahora"] = AHORA + timedelta(hours=1)
    piloto.evaluar()
    assert len(llamadas) == 1
    # Se corrigió la e.firma: a las 6 h se vuelve a pedir y ahora sí sale.
    monkeypatch.setattr(solicitud_mod, "solicitar_descarga", ORIGINAL_SOLICITAR)
    entorno.reloj["ahora"] = AHORA + timedelta(hours=7)
    piloto.evaluar()
    ej = piloto._fila(RFC, "diaria", "2026-10-13")
    assert ej["estado"] == "completa"
    assert {s["tipo_comprobante"] for s in _del_piloto("diaria")} == {"E", "R"}


def test_la_pasada_con_efirma_en_error_se_retoma_al_dia_siguiente(entorno, monkeypatch):
    from sat_descarga.api import piloto

    _falla_solicitud(monkeypatch, RuntimeError("CodEstatus=305, Certificado Inválido"))
    _activar(entorno)
    piloto.evaluar()
    assert piloto._fila(RFC, "diaria", "2026-10-13")["estado"] == "error"
    # Se corrigió la e.firma y la vuelta siguiente ya es de otro día: la pasada
    # del 13 se retoma y la del 14 no vuelve a pedir esos días.
    monkeypatch.setattr(solicitud_mod, "solicitar_descarga", ORIGINAL_SOLICITAR)
    entorno.reloj["ahora"] = AHORA + timedelta(days=1)
    piloto.evaluar()
    assert piloto._fila(RFC, "diaria", "2026-10-13")["estado"] == "completa"
    pedidas = sorted((s["periodo"], s["tipo_comprobante"], s["fecha_inicio"], s["fecha_fin"])
                     for s in _del_piloto("diaria"))
    assert pedidas == [
        ("2026-10-13", "E", "2026-10-10", "2026-10-12"), ("2026-10-13", "R", "2026-10-10", "2026-10-12"),
        ("2026-10-14", "E", "2026-10-13", "2026-10-13"), ("2026-10-14", "R", "2026-10-13", "2026-10-13")]
    assert _fila("2026-10-11", "E")["estado"] == "en_proceso"


def test_un_token_por_empresa_en_cada_vuelta(entorno, monkeypatch):
    from sat_descarga.api import piloto
    from sat_descarga.webservice import auth

    tokens = []
    original = auth.obtener_token
    monkeypatch.setattr(auth, "obtener_token", lambda fiel: tokens.append(1) or original(fiel))
    _activar(entorno)
    piloto.evaluar()  # metadata del cierre (E y R) y pasada diaria (E y R)
    assert len(_del_piloto()) == 4 and len(tokens) == 1


def test_si_la_autenticacion_falla_no_se_repite_en_la_vuelta(entorno, monkeypatch):
    import requests

    from sat_descarga.api import piloto
    from sat_descarga.webservice import auth

    intentos = []

    def _falla(fiel):
        intentos.append(1)
        raise requests.ConnectionError("SAT caído")

    monkeypatch.setattr(auth, "obtener_token", _falla)
    _activar(entorno)
    piloto.evaluar()
    assert len(intentos) == 1 and _del_piloto() == []
    assert piloto._fila(RFC, "diaria", "2026-10-13")["estado"] == "en_curso"
    assert piloto._fila(RFC, "cierre", "2026-09")["estado"] == "en_curso"


def test_una_empresa_con_rfc_invalido_no_frena_a_las_demas(entorno, monkeypatch):
    from sat_descarga.api import piloto

    _activar(entorno)
    reales = config_store.list_empresas
    monkeypatch.setattr(config_store, "list_empresas", lambda *a, **k: [
        {"rfc": "NO-ES-RFC", "metodos": ["fiel"]}, *reales(*a, **k)])
    assert piloto.evaluar()["corrio"] is True
    assert len(_del_piloto("diaria")) == 2



# ---------------------------------------------------------------------------
# Segunda revisión: fallas a medias del SAT
# ---------------------------------------------------------------------------


def test_soap_fault_sin_codigo_se_reintenta(entorno, monkeypatch):
    """Un error sin CodEstatus (SOAP Fault, respuesta sin resultado) no es un
    rechazo de la solicitud: se reintenta como falla del SAT."""
    from sat_descarga.api import piloto

    llamadas = _falla_solicitud(monkeypatch, RuntimeError(
        "[SolicitaDescargaRecibidos] SOAP Fault s:Server: InternalServiceFault"))
    _activar(entorno)
    piloto.evaluar()
    ej = piloto._fila(RFC, "diaria", "2026-10-13")
    assert ej["estado"] == "en_curso" and ej["proximo_intento"]
    assert _fila("2026-10-11", "E")["estado"] == "en_proceso"
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=31)
    piloto.evaluar()
    assert len(llamadas) == 4


def _falla_metadata(monkeypatch, direccion, error):
    """La metadata de `direccion` falla con `error`; lo demás va al SAT simulado."""
    from sat_descarga.webservice import solicitud

    llamadas = []
    original = solicitud.solicitar_descarga

    def _solicitar(**kw):
        if kw.get("tipo_solicitud") == "Metadata":
            llamadas.append(kw["tipo_comprobante"])
            if kw["tipo_comprobante"] == direccion and error is not None:
                raise error
        return original(**kw)

    monkeypatch.setattr(solicitud, "solicitar_descarga", _solicitar)
    return llamadas


def test_la_metadata_que_ya_salio_no_se_vuelve_a_pedir(entorno, monkeypatch):
    import requests

    from sat_descarga.api import piloto

    llamadas = _falla_metadata(monkeypatch, "R", requests.ConnectionError("SAT caído"))
    _activar(entorno)
    piloto.evaluar()
    assert llamadas == ["E", "R"]
    ej = piloto._fila(RFC, "cierre", "2026-09")
    assert ej["estado"] == "en_curso" and set(ej["detalle"]["metadata_parcial"]) == {"E"}
    _procesar()  # la de emitidos baja mientras tanto
    monkeypatch.setattr(solicitud_mod, "solicitar_descarga", ORIGINAL_SOLICITAR)
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=31)
    piloto.evaluar()
    ej = piloto._fila(RFC, "cierre", "2026-09")
    assert ej["detalle"]["paso"] == "metadata"
    assert sorted(s["tipo_comprobante"] for s in _del_piloto("cierre_metadata")) == ["E", "R"]


def test_5005_de_la_metadata_usa_la_que_ya_existe(entorno, monkeypatch):
    from sat_descarga.api import piloto

    _activar(entorno)
    piloto.evaluar()
    _procesar()
    previas = {s["tipo_comprobante"]: s["id_solicitud"] for s in _del_piloto("cierre_metadata")}
    # La metadata ya bajada no se pudo leer: se vuelve a pedir y el SAT contesta 5005.
    piloto._guardar(RFC, "cierre", "2026-09", detalle={"paso": "inicio"})
    _falla_metadata(monkeypatch, "E", RuntimeError("CodEstatus=5005, Solicitud duplicada"))
    llamadas = _falla_metadata(monkeypatch, "R", RuntimeError("CodEstatus=5005, Solicitud duplicada"))
    piloto.evaluar()
    ej = piloto._fila(RFC, "cierre", "2026-09")
    assert llamadas == ["E", "R"]
    assert ej["detalle"]["paso"] == "metadata" and ej["detalle"]["metadata"] == previas


def test_5005_sin_una_propia_espera_como_falla_del_sat(entorno, monkeypatch):
    from sat_descarga.api import piloto

    _falla_metadata(monkeypatch, "E", RuntimeError("CodEstatus=5005, Solicitud duplicada"))
    _activar(entorno)
    piloto.evaluar()
    ej = piloto._fila(RFC, "cierre", "2026-09")
    assert ej["estado"] == "en_curso" and ej["proximo_intento"]
    assert "espera" in ej["error_mensaje"]
    assert not [a for a in piloto.avisos() if a["tipo"] == "error"]


def test_si_pedir_lo_que_falta_falla_no_se_cierra_en_diferencia(entorno, monkeypatch):
    import requests

    from sat_descarga.api import piloto

    _activar(entorno)
    piloto.evaluar()  # metadata del cierre y pasada diaria
    _procesar()
    _falla_solicitud(monkeypatch, requests.ConnectionError("SAT caído"))
    piloto.evaluar()  # compara, faltan los XML del mes y el SAT no responde
    ej = piloto._fila(RFC, "cierre", "2026-09")
    assert ej["estado"] == "en_curso" and not ej["detalle"].get("faltantes_pedidos")
    assert not calendario.filas(RFC, date(2026, 9, 1), date(2026, 9, 30))
    monkeypatch.setattr(solicitud_mod, "solicitar_descarga", ORIGINAL_SOLICITAR)
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=31)
    for _ in range(3):
        piloto.evaluar()
        _procesar()
    ej = piloto._fila(RFC, "cierre", "2026-09")
    assert ej["estado"] == "completa" and ej["detalle"]["resumen"]["dias_con_diferencia"] == 0


def test_el_plazo_de_3_dias_cuenta_desde_la_primera_falla(entorno, monkeypatch):
    """Cuatro días esperando a la e.firma no gastan el plazo de las fallas del SAT."""
    import requests

    from sat_descarga.api import piloto

    _falla_solicitud(monkeypatch, RuntimeError("CodEstatus=305, Certificado Inválido"))
    _activar(entorno)
    piloto.evaluar()
    assert piloto._fila(RFC, "diaria", "2026-10-13")["estado"] == "error"
    _falla_solicitud(monkeypatch, requests.ConnectionError("SAT caído"))
    entorno.reloj["ahora"] = AHORA + timedelta(days=4)
    piloto.evaluar()
    ej = piloto._fila(RFC, "diaria", "2026-10-13")
    assert ej["estado"] == "en_curso" and ej["detalle"]["fallando_desde"] == piloto._utc(
        AHORA + timedelta(days=4))
    assert _fila("2026-10-11", "E")["estado"] == "en_proceso"


def test_muchas_cancelaciones_de_meses_anteriores_son_un_solo_aviso(entorno, monkeypatch):
    from sat_descarga.api import piloto
    from sat_descarga.demo import cfdi as demo_cfdi

    julio, agosto = _indexar_mes(2026, 7), _indexar_mes(2026, 8)
    _indexar_mes(2026, 9)
    cancelados = {julio[0].uuid, agosto[0].uuid, agosto[1].uuid}
    original = demo_cfdi.cancelados_despues
    monkeypatch.setattr(demo_cfdi, "cancelados_despues",
                        lambda rfc, a, m: frozenset(cancelados) if (a, m) in ((2026, 7), (2026, 8))
                        else original(rfc, a, m))
    _activar(entorno)
    ej = _cerrar_septiembre(entorno)
    avisos = [a for a in piloto.avisos() if a["tipo"] == "cancelacion"]
    assert len(avisos) == 1 and avisos[0]["periodo"] == "2026-07"
    assert "Se cancelaron 3 CFDI" in avisos[0]["mensaje"]
    assert "1 de julio de 2026, 2 de agosto de 2026" in avisos[0]["mensaje"]
    assert ej["detalle"]["resumen"]["canceladas"] == 3


def test_las_cancelaciones_se_cuentan_aunque_pase_por_faltantes(entorno, monkeypatch):
    from sat_descarga.api import piloto
    from sat_descarga.demo import cfdi as demo_cfdi

    agosto = _indexar_mes(2026, 8)  # septiembre vacío: el cierre pasa por faltantes
    original = demo_cfdi.cancelados_despues
    monkeypatch.setattr(demo_cfdi, "cancelados_despues",
                        lambda rfc, a, m: frozenset({agosto[0].uuid}) if (a, m) == (2026, 8)
                        else original(rfc, a, m))
    _activar(entorno)
    ej = _cerrar_septiembre(entorno)
    assert _del_piloto("cierre_faltantes")
    assert ej["estado"] == "completa" and ej["detalle"]["resumen"]["canceladas"] == 1


def test_al_reanudar_no_se_cierran_los_meses_en_pausa(entorno):
    from sat_descarga.api import piloto

    _activar(entorno, AHORA.replace(month=6, day=10))
    piloto.configurar(activo=False)
    entorno.reloj["ahora"] = AHORA
    piloto.configurar(activo=True)
    assert config_store.get_piloto_config()["activado_en"].startswith("2026-10-13")
    assert piloto.meses_por_cerrar(RFC) == ["2026-09"]
    # Activar de nuevo sin haber pausado no mueve la fecha.
    piloto.configurar(activo=True, dia_cierre=7)
    assert config_store.get_piloto_config()["activado_en"].startswith("2026-10-13")


def test_un_cierre_empezado_antes_de_la_pausa_se_termina(entorno):
    from sat_descarga.api import piloto

    _activar(entorno, AHORA.replace(month=8, day=10))
    entorno.reloj["ahora"] = AHORA.replace(month=8, day=12)
    piloto.evaluar()  # cierre de julio a medias (metadata pedida)
    assert piloto._fila(RFC, "cierre", "2026-07")["estado"] == "en_curso"
    piloto.configurar(activo=False)
    entorno.reloj["ahora"] = AHORA
    piloto.configurar(activo=True)
    assert piloto.meses_por_cerrar(RFC) == ["2026-09", "2026-07"]
    _cerrar_septiembre(entorno, vueltas=6)
    assert piloto._fila(RFC, "cierre", "2026-07")["estado"] == "completa"
    assert piloto._fila(RFC, "cierre", "2026-08") is None  # el de la pausa no
