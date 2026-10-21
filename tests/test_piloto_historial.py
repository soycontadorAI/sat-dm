"""Llenado del historial de la descarga automática (fase 5, api/piloto.py).

Mismo entorno que tests/test_piloto.py: SAT simulado del modo de grabación, reloj
fijo en la Ciudad de México (2026-10-13 09:00) y una empresa de demo con pocos CFDI.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from sat_descarga.cli import config_store  # noqa: E402
from sat_descarga.procesador import calendario  # noqa: E402
from tests.test_piloto import (  # noqa: E402,F401
    AHORA, RFC, _del_piloto, _fila, _indexar_mes, _procesar, cliente, entorno,
)


def _historial(entorno, desde, activo=True):
    from sat_descarga.api import piloto

    piloto.configurar(activo=activo, historial_desde=desde)


def _correr(vueltas=6):
    """Evaluaciones del piloto, cada una seguida de una pasada del poller."""
    from sat_descarga.api import piloto

    for _ in range(vueltas):
        piloto.evaluar()
        _procesar()


def _cierre(mes, rfc=RFC):
    from sat_descarga.api import piloto

    return piloto._fila(rfc, "cierre", mes)


def _del_historial():
    """Filas de cierre del historial, por periodo."""
    from sat_descarga.api import piloto

    return {p: f for (r, p), f in piloto._cierres().items()
            if r == RFC and f["detalle"].get("origen") == "historial"}


# ---------------------------------------------------------------------------
# 1. Orden y límites
# ---------------------------------------------------------------------------


def test_meses_de_historial_del_mas_reciente_al_mas_antiguo(entorno):
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 5, 1))
    # Septiembre es del cierre normal; el historial arranca en agosto.
    assert piloto.meses_de_historial(RFC) == ["2026-08", "2026-07", "2026-06", "2026-05"]
    assert piloto.meses_por_cerrar(RFC) == ["2026-09"]
    assert piloto.historial_maximo() == date(2026, 8, 1)
    assert piloto.historial_minimo() == date(2021, 11, 1)
    # Un mes ya completo sale de la lista.
    piloto._reservar(RFC, "cierre", "2026-07")
    piloto._guardar(RFC, "cierre", "2026-07", estado="completa")
    assert piloto.meses_de_historial(RFC) == ["2026-08", "2026-06", "2026-05"]


def test_sin_historial_desde_no_hay_meses(entorno):
    from sat_descarga.api import piloto

    piloto.configurar(activo=True)
    assert piloto.meses_de_historial(RFC) == []


# ---------------------------------------------------------------------------
# 2. Validación por la API
# ---------------------------------------------------------------------------


def test_api_valida_y_normaliza_historial_desde(cliente, monkeypatch):
    from sat_descarga.api import piloto

    est = cliente.get("/piloto/estado").json()
    assert est["historial"] == {"desde": None, "minimo": "2021-11-01", "maximo": "2026-08-01",
                                "meses": 0, "empresas": 1, "empezados": 0,
                                "meses_total": 0, "meses_completos": 0,
                                "meses_con_diferencia": 0, "meses_con_error": 0, "siguiente": None}
    assert est["empresas"][0]["historial_total"] == 0

    # Se normaliza al día 1.
    r = cliente.put("/piloto/config", json={"activo": True, "historial_desde": "2025-03-17"})
    assert r.status_code == 200
    assert r.json()["historial"]["desde"] == "2025-03-01"
    assert config_store.get_piloto_config()["historial_desde"] == "2025-03-01"

    msg = "El historial se puede llenar desde noviembre de 2021 hasta agosto de 2026."
    for fecha in ("2021-10-01", "2026-09-01", "2026-10-13"):
        r = cliente.put("/piloto/config", json={"historial_desde": fecha})
        assert r.status_code == 400 and r.json()["detail"] == msg, fecha
    # Los extremos son válidos.
    assert cliente.put("/piloto/config", json={"historial_desde": "2021-11-30"}).status_code == 200
    assert cliente.put("/piloto/config", json={"historial_desde": "2026-08-01"}).status_code == 200

    # Sin la clave no cambia; null detiene (sin pedir la capacidad); fijarlo la exige.
    assert cliente.put("/piloto/config", json={"dia_cierre": 7}).json()["historial"]["desde"] \
        == "2026-08-01"
    monkeypatch.setattr(piloto, "disponible", lambda: False)
    r = cliente.put("/piloto/config", json={"historial_desde": "2025-01-01"})
    assert r.status_code == 402 and r.json()["codigo"] == "piloto"
    r = cliente.put("/piloto/config", json={"historial_desde": None})
    assert r.status_code == 200 and r.json()["historial"]["desde"] is None


def test_el_limite_de_cinco_anos_se_mueve_con_el_dia(entorno):
    from sat_descarga.api import piloto

    # Con un margen de 7 días: no se empieza un mes que en esos días quede fuera.
    assert piloto.historial_minimo(date(2026, 12, 31)) == date(2022, 2, 1)
    assert piloto.historial_minimo(date(2026, 12, 24)) == date(2022, 1, 1)
    assert piloto.historial_minimo(date(2026, 1, 1)) == date(2021, 2, 1)
    with pytest.raises(ValueError, match="El historial se puede llenar desde"):
        piloto.configurar(historial_desde=date(2021, 10, 1))


def test_el_maximo_al_reanudar_se_calcula_como_si_se_activara_hoy(cliente):
    from sat_descarga.api import piloto

    # Activado en junio y en pausa: al reanudar, `activado_en` pasa a hoy (octubre).
    config_store.set_piloto_config({"activo": False, "activado_en": "2026-06-10T09:00:00"})
    assert cliente.get("/piloto/estado").json()["historial"]["maximo"] == "2026-08-01"
    assert piloto.historial_maximo() == date(2026, 8, 1)
    r = cliente.put("/piloto/config", json={"activo": True, "historial_desde": "2026-07-01"})
    assert r.status_code == 200 and r.json()["historial"]["desde"] == "2026-07-01"
    # Ya activo, cuenta su `activado_en`.
    config_store.set_piloto_config({"activado_en": "2026-06-10T09:00:00"})
    assert piloto.historial_maximo() == date(2026, 4, 1)


# ---------------------------------------------------------------------------
# 3. Flujo completo de un mes
# ---------------------------------------------------------------------------


def test_un_mes_del_historial_pide_solo_ese_mes_y_consolida(entorno, monkeypatch):
    from sat_descarga.api import piloto
    from sat_descarga.demo import cfdi as demo_cfdi

    # Sin metadata reusable del cierre normal (esa se prueba aparte): pide la suya.
    monkeypatch.setattr(piloto, "_metadata_reusable", lambda rfc, periodo: None)
    _historial(entorno, date(2026, 8, 1))
    _correr()
    ej = _cierre("2026-08")
    assert ej["estado"] == "completa", ej
    assert ej["detalle"]["origen"] == "historial" and ej["detalle"]["iniciado"] == "2026-10-13"
    meta = [s for s in _del_piloto("cierre_metadata") if s["periodo"] == "2026-08"]
    assert sorted(s["tipo_comprobante"] for s in meta) == ["E", "R"]
    assert all(s["tipo_solicitud"] == "Metadata" and s["fecha_inicio"] == "2026-08-01"
               and s["fecha_fin"] == "2026-08-31" for s in meta)
    # La base estaba vacía: lo que faltaba se pidió por días y todo quedó consolidado.
    assert [s for s in _del_piloto("cierre_faltantes") if s["periodo"] == "2026-08"]
    ago = calendario.filas(RFC, date(2026, 8, 1), date(2026, 8, 31))
    assert len(ago) == 62 and {f["estado"] for f in ago.values()} == {"consolidado"}
    dia = demo_cfdi.en_rango(RFC, date(2026, 8, 15), date(2026, 8, 15), "R")
    assert _fila("2026-08-15", "R")["total_sat"] == _fila("2026-08-15", "R")["total_bd"] == len(dia)
    # El mes del historial no entra al resumen mensual; el de septiembre sí.
    assert not any("agosto de 2026 completo" in a["mensaje"] for a in piloto.avisos())
    assert any("septiembre de 2026 completo" in a["mensaje"] for a in piloto.avisos())


def test_la_metadata_del_cierre_normal_sigue_pidiendo_12_meses(entorno):
    _historial(entorno, date(2026, 8, 1))
    _correr()
    meta = [s for s in _del_piloto("cierre_metadata") if s["periodo"] == "2026-09"]
    assert meta and all(s["fecha_inicio"] == "2025-10-01" for s in meta)
    assert "origen" not in _cierre("2026-09")["detalle"]


def test_un_mes_que_se_retoma_conserva_su_origen(entorno, monkeypatch):
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 8, 1))
    _correr(3)
    assert _cierre("2026-08")["detalle"]["origen"] == "historial"
    # Metadata ilegible: se vuelve a pedir, pero sigue siendo del historial.
    monkeypatch.setattr(piloto, "_leer_metadata", lambda rfc, ids: None)
    piloto.evaluar()
    ej = _cierre("2026-08")
    assert ej["detalle"]["origen"] == "historial" and ej["detalle"]["iniciado"] == "2026-10-13"


# ---------------------------------------------------------------------------
# 4. Ritmo
# ---------------------------------------------------------------------------


def test_un_mes_nuevo_por_empresa_y_dia(entorno):
    _historial(entorno, date(2026, 5, 1))
    _correr(10)
    assert sorted(_del_historial()) == ["2026-08"]
    assert _cierre("2026-08")["estado"] == "completa"
    # Al día siguiente, el siguiente mes.
    entorno.reloj["ahora"] = AHORA + timedelta(days=1)
    _correr(10)
    assert sorted(_del_historial()) == ["2026-07", "2026-08"]
    assert _del_historial()["2026-07"]["detalle"]["iniciado"] == "2026-10-14"
    assert _cierre("2026-07")["estado"] == "completa"


def test_el_historial_espera_la_hora_de_la_pasada(entorno):
    _historial(entorno, date(2026, 5, 1))
    entorno.reloj["ahora"] = AHORA.replace(hour=0, minute=30)
    _correr(3)
    assert _del_historial() == {}
    entorno.reloj["ahora"] = AHORA.replace(hour=1, minute=5)
    _correr(3)
    assert "2026-08" in _del_historial()


def test_no_toca_al_sat_si_un_cierre_normal_lo_hizo(entorno):
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 5, 1))
    piloto.evaluar()  # septiembre pide su metadata: es la acción de la vuelta
    assert _cierre("2026-09") is not None and _del_historial() == {}


def test_tope_por_cuenta_con_varias_empresas(entorno, monkeypatch):
    from sat_descarga.api import piloto, poller
    from sat_descarga.demo import efirma
    from sat_descarga.demo.escenario import NORMA

    cer, key, pwd = efirma.generar(NORMA, entorno.tmp / "e2", AHORA.date())
    config_store.add_empresa("", str(cer), str(key), pwd)
    monkeypatch.setattr(piloto, "HISTORIAL_MESES_POR_DIA_CUENTA", 1)
    _historial(entorno, date(2026, 5, 1))
    for _ in range(4):
        piloto.evaluar()
        poller._proxima_verificacion.clear()
        for e in config_store.list_empresas():
            poller._procesar_empresa(e["rfc"], e)
    iniciados = [(r, p) for (r, p), f in piloto._cierres().items()
                 if f["detalle"].get("origen") == "historial"]
    assert len(iniciados) == 1  # una sola empresa arrancó mes hoy
    # Al día siguiente la otra (y la primera ya no tiene su mes del día).
    monkeypatch.setattr(piloto, "HISTORIAL_MESES_POR_DIA_CUENTA", 8)
    entorno.reloj["ahora"] = AHORA + timedelta(days=1)
    piloto.evaluar()
    iniciados = [(r, p) for (r, p), f in piloto._cierres().items()
                 if f["detalle"].get("origen") == "historial"]
    assert len({r for r, _p in iniciados}) == 2


# ---------------------------------------------------------------------------
# 5. Cancelaciones
# ---------------------------------------------------------------------------


def test_cancelaciones_del_historial_se_marcan_sin_aviso(entorno, monkeypatch):
    from sat_descarga.api import piloto
    from sat_descarga.demo import cfdi as demo_cfdi
    from sat_descarga.procesador.db import abrir_db

    agosto = _indexar_mes(2026, 8)
    cancelado = agosto[0]
    original = demo_cfdi.cancelados_despues
    monkeypatch.setattr(demo_cfdi, "cancelados_despues",
                        lambda rfc, a, m: frozenset({cancelado.uuid}) if (a, m) == (2026, 8)
                        else original(rfc, a, m))
    # Septiembre ya cerrado: su metadata de 12 meses sí avisaría la cancelación de agosto.
    piloto._reservar(RFC, "cierre", "2026-09")
    piloto._guardar(RFC, "cierre", "2026-09", estado="completa")
    _historial(entorno, date(2026, 8, 1))
    _correr()
    assert _cierre("2026-08")["estado"] == "completa"
    with abrir_db().cursor() as cur:
        estado, fecha_canc = cur.execute(
            "SELECT estado_sat, fecha_cancelacion FROM cfdis WHERE uuid = ?", (cancelado.uuid,)
        ).fetchone()
    assert estado == "Cancelado" and fecha_canc
    assert [a for a in piloto.avisos() if a["tipo"] == "cancelacion"] == []

    # Con la misma regla de un cierre normal (CFDI de un mes anterior) sí avisaría;
    # el historial lo aplica en silencio.
    registro = SimpleNamespace(uuid=agosto[1].uuid, estatus="0", fecha_cancelacion="2026-10-01T10:00:00")
    assert piloto._cancelaciones(RFC, "2026-09", [registro], avisar=False) == 1
    assert [a for a in piloto.avisos() if a["tipo"] == "cancelacion"] == []
    registro = SimpleNamespace(uuid=agosto[2].uuid, estatus="0", fecha_cancelacion="2026-10-01T10:00:00")
    assert piloto._cancelaciones(RFC, "2026-09", [registro]) == 1
    assert len([a for a in piloto.avisos() if a["tipo"] == "cancelacion"]) == 1


# ---------------------------------------------------------------------------
# 6. Aviso único al terminar
# ---------------------------------------------------------------------------


def test_un_solo_aviso_al_terminar_todo_el_historial(entorno):
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 7, 1))
    _correr(10)
    resumenes = lambda: [a for a in piloto.avisos() if "historial" in a["mensaje"].lower()]  # noqa: E731
    assert resumenes() == []  # solo va agosto
    entorno.reloj["ahora"] = AHORA + timedelta(days=1)
    _correr(10)
    assert _cierre("2026-07")["estado"] == "completa"
    aviso = resumenes()
    assert len(aviso) == 1 and aviso[0]["tipo"] == "resumen"
    assert aviso[0]["mensaje"] == ("El historial desde julio de 2026 ya está en la base: "
                                   "2 meses, 0 con diferencias.")
    _correr(4)
    entorno.reloj["ahora"] = AHORA + timedelta(days=2)
    _correr(4)
    assert len(resumenes()) == 1


def test_el_aviso_final_es_por_rango_y_no_por_mes_con_error(entorno):
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 7, 1))
    for mes, estado in (("2026-08", "completa"), ("2026-07", "error")):
        piloto._reservar(RFC, "cierre", mes, {"origen": "historial", "iniciado": "2026-10-10"})
        piloto._guardar(RFC, "cierre", mes, estado=estado, error_mensaje="Rechazada")
    piloto._resumen_historial()
    with piloto.abrir_db().cursor() as cur:
        claves = [r[0] for r in cur.execute(
            "SELECT clave FROM piloto_avisos WHERE clave LIKE 'historial:%'").fetchall()]
    fijado = config_store.get_piloto_config()["historial_fijado_en"]
    assert claves == [f"historial:2026-07-01:{fijado}:0"]
    # Al reanudar antes, el rango se recorre (lo que se sume tendrá su propio aviso).
    config_store.set_piloto_config({"activado_en": "2026-09-20T09:00:00"})
    assert piloto._meses_rango(date(2026, 10, 13))[0] == "2026-07"
    # Un mes del historial que queda en error no emite el aviso `error` del mes.
    piloto._falla_cierre(RFC, "2026-06", None, "rechazo", "", "Rechazada",
                         detalle={"origen": "historial"})
    assert [a for a in piloto.avisos() if a["tipo"] == "error"] == []
    piloto._falla_cierre(RFC, "2026-05", None, "rechazo", "", "Rechazada")
    assert len([a for a in piloto.avisos() if a["tipo"] == "error"]) == 1


def test_el_aviso_final_no_se_pierde_si_se_archiva_la_empresa_pendiente(entorno):
    from sat_descarga.api import piloto
    from sat_descarga.demo import efirma
    from sat_descarga.demo.escenario import NORMA

    cer, key, pwd = efirma.generar(NORMA, entorno.tmp / "e2", AHORA.date())
    config_store.add_empresa("", str(cer), str(key), pwd)
    otra = next(e["rfc"] for e in config_store.list_empresas() if e["rfc"] != RFC)
    _historial(entorno, date(2026, 8, 1))
    # La otra ya terminó agosto; la primera lo trae empezado.
    piloto._reservar(otra, "cierre", "2026-08", {"origen": "historial", "iniciado": "2026-10-12"})
    piloto._guardar(otra, "cierre", "2026-08", estado="completa")
    piloto._reservar(RFC, "cierre", "2026-08", {"origen": "historial", "iniciado": "2026-10-12"})
    piloto._resumen_historial()
    assert [a for a in piloto.avisos() if "historial" in a["mensaje"].lower()] == []
    config_store.archive_empresa(RFC)
    piloto.evaluar()
    aviso = [a["mensaje"] for a in piloto.avisos() if "historial" in a["mensaje"].lower()]
    assert aviso == ["El historial desde agosto de 2026 ya está en la base: "
                     "1 mes, 0 con diferencias."]


def test_estado_cuenta_el_progreso_del_historial(entorno):
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 6, 1))
    est = piloto.estado()
    assert est["historial"] == {"desde": "2026-06-01", "minimo": "2021-11-01",
                                "maximo": "2026-08-01", "meses": 3, "empresas": 1,
                                "empezados": 0, "meses_total": 3, "meses_completos": 0,
                                "meses_con_diferencia": 0, "meses_con_error": 0,
                                "siguiente": "2026-08"}
    assert est["empresas"][0]["historial_total"] == 3
    assert est["empresas"][0]["historial_completos"] == 0
    _correr(10)
    est = piloto.estado()
    assert est["historial"]["meses_completos"] == 1
    assert est["empresas"][0]["historial_completos"] == 1
    assert est["historial"]["siguiente"] == "2026-07"
    assert est["historial"]["empezados"] == 0


# ---------------------------------------------------------------------------
# 7. Detener
# ---------------------------------------------------------------------------


def test_historial_desde_none_no_empieza_meses_nuevos_pero_termina_los_empezados(entorno):
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 5, 1))
    _correr(3)
    assert _cierre("2026-08")["estado"] == "en_curso"
    assert piloto.estado()["historial"]["empezados"] == 1
    piloto.configurar(historial_desde=None)
    # Aunque `desde` sea null, el mes empezado se sigue contando hasta que termine.
    assert piloto.estado()["historial"]["desde"] is None
    assert piloto.estado()["historial"]["empezados"] == 1
    assert config_store.get_piloto_config()["historial_desde"] is None
    _correr(10)
    assert _cierre("2026-08")["estado"] == "completa"  # el empezado terminó
    assert piloto.estado()["historial"]["empezados"] == 0
    entorno.reloj["ahora"] = AHORA + timedelta(days=1)
    _correr(10)
    assert sorted(_del_historial()) == ["2026-08"]  # ninguno nuevo
    # Sin pasarlo, la configuración no se toca.
    _historial(entorno, date(2026, 6, 1))
    piloto.configurar(dia_cierre=9)
    assert config_store.get_piloto_config()["historial_desde"] == "2026-06-01"


# ---------------------------------------------------------------------------
# 8. Sin piloto activo no corre
# ---------------------------------------------------------------------------


def test_sin_piloto_activo_o_sin_capacidad_no_corre(entorno, monkeypatch):
    from sat_descarga.api import piloto

    config_store.set_piloto_config({"historial_desde": "2026-05-01"})
    assert piloto.evaluar() == {"corrio": False, "motivo": "inactivo"}
    assert _del_piloto() == [] and _del_historial() == {}
    piloto.configurar(activo=True)
    monkeypatch.setattr(piloto, "disponible", lambda: False)
    assert piloto.evaluar() == {"corrio": False, "motivo": "licencia"}
    assert _del_piloto() == []


def test_un_mes_que_fallo_no_deja_el_avance_atorado(entorno):
    """Un mes en error sin reintento ya no tiene trabajo: el avance no se queda
    "yendo" en él y el resumen lo cuenta como no cerrado."""
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 7, 1))
    piloto._reservar(RFC, "cierre", "2026-08", {"paso": "inicio", "origen": "historial",
                                                "iniciado": "2026-10-12"})
    piloto._guardar(RFC, "cierre", "2026-08", estado="error", error_mensaje="Rechazada")
    piloto._reservar(RFC, "cierre", "2026-07", {"origen": "historial", "iniciado": "2026-10-11"})
    piloto._guardar(RFC, "cierre", "2026-07", estado="completa")
    h = piloto.estado()["historial"]
    assert (h["siguiente"], h["meses_completos"], h["meses_con_error"]) == (None, 1, 1)
    piloto._resumen_historial()
    aviso = [a["mensaje"] for a in piloto.avisos() if "historial" in a["mensaje"].lower()]
    assert aviso == ["El historial desde julio de 2026 ya está en la base: 1 mes, "
                     "0 con diferencias. 1 no se pudo cerrar."]
    # Uno que espera a la e.firma sí sigue pendiente.
    piloto._guardar(RFC, "cierre", "2026-08", detalle={"origen": "historial", "reintentable": True})
    assert piloto.estado()["historial"]["siguiente"] == "2026-08"


def test_un_mes_del_historial_empezado_no_entra_a_los_cierres_normales(entorno):
    """Los cierres empezados se terminan aunque su mes quede antes del primero,
    pero los del historial los lleva el historial (con su ritmo y su hora)."""
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 7, 1))
    piloto._reservar(RFC, "cierre", "2026-08", {"paso": "inicio", "origen": "historial",
                                                "iniciado": "2026-10-13"})
    piloto._reservar(RFC, "cierre", "2026-06", {"paso": "inicio"})
    assert piloto.meses_por_cerrar(RFC) == ["2026-09", "2026-06"]


# ---------------------------------------------------------------------------
# 9. Segunda revisión
# ---------------------------------------------------------------------------


def _terminar(mes, estado="completa", rfc=RFC):
    from sat_descarga.api import piloto

    piloto._reservar(rfc, "cierre", mes, {"origen": "historial", "iniciado": "2026-10-10"})
    piloto._guardar(rfc, "cierre", mes, estado=estado)


def _avisos_historial():
    from sat_descarga.api import piloto

    return [a["mensaje"] for a in piloto.avisos(solo_sin_leer=False)
            if "historial" in a["mensaje"].lower()]


def test_el_aviso_final_habla_del_rango_efectivo(entorno, monkeypatch):
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 6, 1))
    # El mínimo se movió: el mes más antiguo del rango es julio, no el junio guardado.
    monkeypatch.setattr(piloto, "historial_minimo", lambda hoy=None: date(2026, 7, 1))
    for mes in ("2026-08", "2026-07"):
        _terminar(mes)
    piloto._resumen_historial()
    assert _avisos_historial() == ["El historial desde julio de 2026 ya está en la base: "
                                   "2 meses, 0 con diferencias."]
    with piloto.abrir_db().cursor() as cur:
        claves = [r[0] for r in cur.execute(
            "SELECT clave FROM piloto_avisos WHERE clave LIKE 'historial:%'").fetchall()]
    fijado = config_store.get_piloto_config()["historial_fijado_en"]
    assert claves == [f"historial:2026-06-01:{fijado}:0"]  # lo que eligió el usuario, no el rango


def test_cambiar_de_mes_a_un_rango_completo_no_avisa_otra_vez(entorno):
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 7, 1))
    for mes in ("2026-08", "2026-07"):
        _terminar(mes)
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=5)  # terminaron después de fijarlo
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 1
    # Se cambia de mes a un rango que ya estaba completo: no vuelve a avisar.
    entorno.reloj["ahora"] = AHORA + timedelta(days=1)
    piloto.configurar(historial_desde=date(2026, 8, 1))
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 1
    # Y volver al rango más largo (ya completo, nada terminó después) tampoco.
    piloto.configurar(historial_desde=date(2026, 7, 1))
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 1
    # Un rango nuevo cuyos meses terminan DESPUÉS de fijarlo sí avisa.
    piloto.configurar(historial_desde=date(2026, 6, 1))
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 1  # junio sigue pendiente
    entorno.reloj["ahora"] = AHORA + timedelta(days=2)
    _terminar("2026-06")
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 2
    assert _avisos_historial()[0].startswith("El historial desde junio de 2026")


def test_el_aviso_final_no_escanea_si_ya_existe(entorno, monkeypatch):
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 8, 1))
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=5)
    _terminar("2026-08")
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 1
    monkeypatch.setattr(piloto, "_cierres", lambda *a, **k: pytest.fail("escaneó los cierres"))
    piloto._resumen_historial()


def test_cierres_filtra_por_empresa_en_sql(entorno):
    from sat_descarga.api import piloto

    _terminar("2026-08")
    _terminar("2026-08", rfc="OTRO010101AAA")
    assert set(piloto._cierres()) == {(RFC, "2026-08"), ("OTRO010101AAA", "2026-08")}
    assert set(piloto._cierres(RFC)) == {(RFC, "2026-08")}
    assert piloto._cierres(RFC)[(RFC, "2026-08")]["actualizado_en"]
    assert piloto._iniciados_hoy(date(2026, 10, 10)) == [RFC, "OTRO010101AAA"]
    assert piloto._iniciados_hoy(date(2026, 10, 13)) == []


def test_un_mes_del_historial_reusa_la_metadata_del_cierre_normal(entorno):
    from sat_descarga.api import piloto

    piloto.configurar(activo=True)
    _correr()
    sep = _cierre("2026-09")
    assert sep["estado"] == "completa" and sep["detalle"]["ventana"][0] == "2025-10-01"
    pedidas = len(_del_piloto("cierre_metadata"))
    _historial(entorno, date(2026, 8, 1))
    _correr()
    ago = _cierre("2026-08")
    assert ago["estado"] == "completa" and ago["detalle"]["origen"] == "historial"
    assert ago["detalle"]["metadata"] == sep["detalle"]["metadata"]
    assert len(_del_piloto("cierre_metadata")) == pedidas  # ninguna Metadata nueva
    ago_dias = calendario.filas(RFC, date(2026, 8, 1), date(2026, 8, 31))
    assert {f["estado"] for f in ago_dias.values()} == {"consolidado"}


def test_no_reusa_la_metadata_ilegible_o_de_otra_ventana(entorno):
    from sat_descarga.api import piloto

    piloto.configurar(activo=True)
    _correr()
    ids = _cierre("2026-09")["detalle"]["metadata"]
    assert piloto._metadata_reusable(RFC, "2026-08")[0] == ids
    assert piloto._metadata_reusable(RFC, "2024-01") is None  # fuera de la ventana
    config_store.marcar_solicitud(RFC, ids["E"], ilegible=True)
    assert piloto._metadata_reusable(RFC, "2026-08") is None


def test_reusa_la_metadata_aunque_una_direccion_venga_vacia(entorno):
    from sat_descarga.api import piloto

    piloto.configurar(activo=True)
    _correr()
    ids = _cierre("2026-09")["detalle"]["metadata"]
    # R sin información en el periodo (5004): la solicitud no se descargó, pero está lista.
    config_store.update_solicitud(RFC, ids["R"], "5")
    config_store.marcar_solicitud(RFC, ids["R"], codigo_estado_solicitud="5004")
    assert piloto._estado_solicitud(RFC, ids["R"]) == "lista"
    pedidas = len(_del_piloto("cierre_metadata"))
    assert piloto._metadata_reusable(RFC, "2026-08")[0] == ids
    _historial(entorno, date(2026, 8, 1))
    _correr()
    assert _cierre("2026-08")["detalle"]["origen"] == "historial"
    assert len(_del_piloto("cierre_metadata")) == pedidas  # ninguna Metadata nueva


def test_el_aviso_no_se_repite_cuando_el_minimo_se_mueve_de_mes(entorno, monkeypatch):
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 7, 1))
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=5)
    for mes in ("2026-08", "2026-07"):
        _terminar(mes)
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 1
    # Pasa un mes: el mínimo avanza y el rango efectivo cambia, pero el aviso ya se dio.
    monkeypatch.setattr(piloto, "historial_minimo", lambda hoy=None: date(2026, 8, 1))
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 1


def test_el_aviso_final_de_varias_empresas_cuenta_cierres(entorno):
    from sat_descarga.api import piloto
    from sat_descarga.demo import efirma
    from sat_descarga.demo.escenario import NORMA

    cer, key, pwd = efirma.generar(NORMA, entorno.tmp / "e3", AHORA.date())
    config_store.add_empresa("", str(cer), str(key), pwd)
    otra = next(e["rfc"] for e in config_store.list_empresas() if e["rfc"] != RFC)
    _historial(entorno, date(2026, 8, 1))
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=5)
    _terminar("2026-08")
    _terminar("2026-08", rfc=otra)
    piloto._resumen_historial()
    assert _avisos_historial() == ["El historial desde agosto de 2026 ya está en la base para "
                                   "2 empresas: 2 cierres (un mes por empresa), 0 con diferencias."]



def test_al_reanudar_los_meses_nuevos_tienen_su_aviso(entorno):
    """Los meses que se suman al reanudar y llena el historial tienen su aviso, que habla
    solo de ellos (no repite lo ya anunciado)."""
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 7, 1))
    for mes in ("2026-08", "2026-07"):
        _terminar(mes)
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=5)
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 1
    # Se reanuda dos meses después: el rango crece por el lado reciente.
    piloto.configurar(activo=False)
    entorno.reloj["ahora"] = AHORA + timedelta(days=61)
    piloto.configurar(activo=True)
    nuevos = [m for m in piloto._meses_rango(entorno.reloj["ahora"].date()) if m > "2026-08"]
    assert nuevos
    for mes in nuevos:
        _terminar(mes)
    entorno.reloj["ahora"] = AHORA + timedelta(days=61, minutes=5)
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 2
    assert _avisos_historial()[0] == ("Ya está en la base lo que se sumó al historial "
                                      "(septiembre de 2026 a octubre de 2026): 2 meses, "
                                      "0 con diferencias.")
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 2


def test_reanudar_con_meses_que_ya_cerro_el_cierre_normal_no_avisa_otra_vez(entorno):
    """Tras una pausa corta, el mes que se suma al rango ya lo cerró el cierre normal: el
    historial no llenó nada nuevo y el aviso no se repite."""
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 7, 1))
    for mes in ("2026-08", "2026-07"):
        _terminar(mes)
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=5)
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 1
    piloto._reservar(RFC, "cierre", "2026-09", {"paso": "inicio"})  # el primer cierre normal
    piloto._guardar(RFC, "cierre", "2026-09", estado="completa")
    piloto.configurar(activo=False)
    entorno.reloj["ahora"] = AHORA + timedelta(days=30)
    piloto.configurar(activo=True)
    assert piloto._meses_rango(entorno.reloj["ahora"].date())[0] == "2026-09"
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 1
    assert config_store.get_piloto_config()["historial_revisado"]["hasta"] == {RFC: "2026-09"}


def test_una_empresa_que_vuelve_a_incluirse_tiene_su_aviso(entorno):
    """Lo revisado sin aviso no tapa a una empresa que no estaba incluida: al volver, lo
    que su historial llenó después de fijarlo sí se anuncia."""
    from sat_descarga.api import piloto
    from sat_descarga.demo import efirma
    from sat_descarga.demo.escenario import NORMA

    cer, key, pwd = efirma.generar(NORMA, entorno.tmp / "e4", AHORA.date())
    config_store.add_empresa("", str(cer), str(key), pwd)
    otra = next(e["rfc"] for e in config_store.list_empresas() if e["rfc"] != RFC)
    entorno.reloj["ahora"] = AHORA - timedelta(days=1)
    _terminar("2026-08")  # la primera ya lo tenía antes de fijar el historial
    entorno.reloj["ahora"] = AHORA
    _historial(entorno, date(2026, 8, 1))
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=5)
    _terminar("2026-08", rfc=otra)
    config_store.set_piloto_incluida(otra, False)
    piloto._resumen_historial()
    assert _avisos_historial() == []  # solo la primera, completa desde antes
    config_store.set_piloto_incluida(otra, True)
    piloto._resumen_historial()
    nombre = next(e.get("nombre") or otra for e in config_store.list_empresas() if e["rfc"] == otra)
    assert _avisos_historial() == [f"Ya está en la base lo que se sumó al historial de {nombre} "
                                   "(agosto de 2026): 1 mes, 0 con diferencias."]
    assert [a["rfc"] for a in piloto.avisos() if "historial" in a["mensaje"]] == [otra]


def test_lo_ya_revisado_con_otra_eleccion_no_se_vuelve_a_contar(entorno):
    """Se elige julio (aviso), luego agosto (ya completo: sin aviso) y al reanudar el
    historial llena septiembre y octubre: el aviso habla solo de esos dos."""
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 7, 1))
    for mes in ("2026-08", "2026-07"):
        _terminar(mes)
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=5)
    piloto._resumen_historial()
    entorno.reloj["ahora"] = AHORA + timedelta(days=1)
    piloto.configurar(historial_desde=date(2026, 8, 1))
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 1
    piloto.configurar(activo=False)
    entorno.reloj["ahora"] = AHORA + timedelta(days=61)
    piloto.configurar(activo=True)
    for mes in ("2026-10", "2026-09"):
        _terminar(mes)
    piloto._resumen_historial()
    assert _avisos_historial()[0] == ("Ya está en la base lo que se sumó al historial "
                                      "(septiembre de 2026 a octubre de 2026): 2 meses, "
                                      "0 con diferencias.")


def test_lo_que_cerro_el_cierre_normal_no_cuenta_como_sumado(entorno):
    """Tras una pausa larga, septiembre ya lo cerró el cierre normal y el historial llena
    octubre y noviembre: el aviso cuenta solo esos dos."""
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 7, 1))
    for mes in ("2026-08", "2026-07"):
        _terminar(mes)
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=5)
    piloto._resumen_historial()
    piloto._reservar(RFC, "cierre", "2026-09", {"paso": "inicio"})  # el primer cierre normal
    piloto._guardar(RFC, "cierre", "2026-09", estado="completa")
    piloto.configurar(activo=False)
    entorno.reloj["ahora"] = AHORA + timedelta(days=80)
    piloto.configurar(activo=True)
    assert piloto._meses_rango(entorno.reloj["ahora"].date())[0] == "2026-11"
    for mes in ("2026-11", "2026-10"):
        _terminar(mes)
    piloto._resumen_historial()
    assert _avisos_historial()[0] == ("Ya está en la base lo que se sumó al historial "
                                      "(octubre de 2026 a noviembre de 2026): 2 meses, "
                                      "0 con diferencias.")


def test_meses_en_palabras_no_junta_meses_salteados():
    from sat_descarga.api import piloto

    assert piloto._meses_en_palabras(["2026-09"]) == "septiembre de 2026"
    assert piloto._meses_en_palabras(["2026-10", "2026-09"]) == "septiembre de 2026 a octubre de 2026"
    assert piloto._meses_en_palabras(["2026-07", "2026-10", "2026-09"]) == (
        "julio de 2026 y septiembre de 2026 a octubre de 2026")
    assert piloto._meses_en_palabras(["2025-01", "2025-02", "2025-04", "2025-06", "2025-07"]) == (
        "enero de 2025 a febrero de 2025, abril de 2025 y junio de 2025 a julio de 2025")
    assert piloto._meses_en_palabras(["2026-12", "2027-01"]) == "diciembre de 2026 a enero de 2027"


def test_un_rango_ya_revisado_no_se_vuelve_a_escanear(entorno, monkeypatch):
    from sat_descarga.api import piloto

    _historial(entorno, date(2026, 7, 1))
    for mes in ("2026-08", "2026-07"):
        _terminar(mes)
    entorno.reloj["ahora"] = AHORA + timedelta(minutes=5)
    piloto._resumen_historial()
    entorno.reloj["ahora"] = AHORA + timedelta(days=1)
    piloto.configurar(historial_desde=date(2026, 8, 1))  # rango ya completo: sin aviso
    piloto._resumen_historial()
    assert len(_avisos_historial()) == 1
    assert config_store.get_piloto_config()["historial_revisado"]["hasta"] == {RFC: "2026-08"}
    original = piloto._cierres
    monkeypatch.setattr(piloto, "_cierres", lambda *a, **k: pytest.fail("volvió a escanear"))
    piloto._resumen_historial()  # nada nuevo: no lee los cierres
    # Si el rango crece (al reanudar), sí se revisa otra vez.
    llamadas = []
    monkeypatch.setattr(piloto, "_cierres", lambda *a, **k: llamadas.append(1) or original(*a, **k))
    monkeypatch.setattr(piloto, "historial_maximo", lambda: date(2026, 9, 1))
    piloto._resumen_historial()
    assert llamadas


def test_metadata_reusable_exige_un_5004_explicito(entorno):
    from sat_descarga.api import piloto

    assert piloto._metadata_lista({"estado": "descargada"})
    assert piloto._metadata_lista({"estado": "5", "codigo_estado_solicitud": "5004"})
    assert not piloto._metadata_lista({"estado": "5"})  # puede ser un rechazo sin código
    # El 5004 de la verificación misma es "no se encontró la solicitud", no "sin datos".
    assert not piloto._metadata_lista({"estado": "5", "cod_estatus": "5004"})


def test_estado_solicitud_no_toma_el_5004_de_la_verificacion(entorno):
    from sat_descarga.api import piloto
    from sat_descarga.api.routers import webservice

    req = webservice.SolicitudRequest(fecha_inicio=date(2026, 10, 1), fecha_fin=date(2026, 10, 10),
                                      tipo_solicitud="CFDI", tipo_comprobante="E")
    for id_sol, campos in (("SINCODIGO", {}), ("NOENCONTRADA", {"cod_estatus": "5004"}),
                           ("SININFO", {"cod_estatus": "5000", "codigo_estado_solicitud": "5004"}),
                           ("RECHAZO", {"cod_estatus": "5000"})):
        webservice._guardar_solicitud_ws(RFC, id_sol, req)
        config_store.update_solicitud(RFC, id_sol, "5", **campos)
    assert piloto._estado_solicitud(RFC, "SINCODIGO") == "lista"  # guardada sin ningún código
    assert piloto._estado_solicitud(RFC, "SININFO") == "lista"
    assert piloto._estado_solicitud(RFC, "NOENCONTRADA") == "fallida"
    assert piloto._estado_solicitud(RFC, "RECHAZO") == "fallida"
    assert not piloto._metadata_lista({"estado": "descargada", "ilegible": True})


def test_cierres_con_una_sola_cota(entorno):
    from sat_descarga.api import piloto

    for mes in ("2026-05", "2026-07", "2026-08"):
        piloto._reservar(RFC, "cierre", mes)
    assert {p for (_r, p) in piloto._cierres(desde="2026-07")} == {"2026-07", "2026-08"}
    assert {p for (_r, p) in piloto._cierres(hasta="2026-07")} == {"2026-05", "2026-07"}
