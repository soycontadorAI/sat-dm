"""Tests de la lógica pura de la descarga de declaraciones presentadas y acuses.

Predicado de aterrizaje, rango de periodos, nombres de archivo y API pública, sin
tocar red/browser.
"""

import pytest

from sat_descarga.portal import declaraciones as D


def test_entrada_y_landing():
    assert D.DECLARACIONES_URL_ENTRADA == "https://pstcdypisr.clouda.sat.gob.mx/"
    assert D.DECLARACIONES_URL_ENTRADA_FIEL == D.DECLARACIONES_URL_ENTRADA
    assert D.DECLARACIONES_LANDING == "pstcdypisr.clouda.sat.gob.mx"
    assert D.TIPOS_DOCUMENTO == {"declaracion": "1", "acuse": "3"}


def test_predicado_landing_no_dispara_en_login_ni_en_nidp():
    # El login vive en loginda (widget NIDP), con `target=` que codifica la URL de
    # vuelta: un substring dispararía en el propio login.
    assert not D._es_landing_declaraciones(
        "https://loginda.siat.sat.gob.mx/nidp/wsfed/ep?id=ciec&sid=0&option=credential"
        "&target=https%3A%2F%2Fpstcdypisr.clouda.sat.gob.mx%2F"
    )
    assert not D._es_landing_declaraciones("https://pstcdypisr.clouda.sat.gob.mx/nidp/app")
    assert not D._es_landing_declaraciones("")
    # Sí dispara en el portal (raíz, Home o Consulta).
    assert D._es_landing_declaraciones("https://pstcdypisr.clouda.sat.gob.mx/")
    assert D._es_landing_declaraciones("https://pstcdypisr.clouda.sat.gob.mx/Home/")
    assert D._es_landing_declaraciones(
        "https://pstcdypisr.clouda.sat.gob.mx/Consulta/Consulta?tipoDocumento=1"
    )


def test_periodos_entre():
    assert D.periodos_entre("2026-01", "2026-06") == [(2026, m) for m in range(1, 7)]
    assert D.periodos_entre("2025-11", "2026-02") == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]
    assert D.periodos_entre("2026-3") == [(2026, 3)]          # hasta opcional
    with pytest.raises(ValueError):
        D.periodos_entre("2026-06", "2026-01")               # invertido
    with pytest.raises(ValueError):
        D.periodos_entre("2026-13")
    with pytest.raises(ValueError):
        D.periodos_entre("enero 2026")


def test_nombre_archivo_respeta_el_sugerido_y_desambigua():
    # Una sola fila: el nombre que entrega el SAT, tal cual.
    assert D.nombre_archivo("GUPF620405TD8.38.2025.pdf", "declaracion", "251070077482",
                            "GUPF620405TD8", 2025, varias_filas=False) == "GUPF620405TD8.38.2025.pdf"
    # Varias filas (normal + complementaria): se agrega el número de operación.
    assert D.nombre_archivo("Acuse.GUPF620405TD8.38.2025.pdf", "acuse", "251070077482",
                            "GUPF620405TD8", 2025, varias_filas=True) == "Acuse.GUPF620405TD8.38.2025.251070077482.pdf"
    # El portal sugiere el MISMO nombre para declaración y acuse: el acuse se prefija.
    assert D.nombre_archivo("GUPF620405TD8.38.2026.pdf", "acuse", "265270003579",
                            "GUPF620405TD8", 2026, varias_filas=False) == "Acuse.GUPF620405TD8.38.2026.pdf"
    # Sin nombre sugerido: nombre estable con prefijo Acuse. para el acuse.
    assert D.nombre_archivo(None, "acuse", "1", "GUPF620405TD8", 2026, False) == "Acuse.GUPF620405TD8.2026.pdf"
    assert D.nombre_archivo("", "declaracion", "1", "GUPF620405TD8", 2026, False) == "GUPF620405TD8.2026.pdf"


def test_normalizar_tipos():
    assert D._normalizar_tipos(None) == ["declaracion", "acuse"]
    assert D._normalizar_tipos("ambos") == ["declaracion", "acuse"]
    assert D._normalizar_tipos("acuse") == ["acuse"]
    assert D._normalizar_tipos(["acuse", "declaracion", "acuse"]) == ["acuse", "declaracion"]
    with pytest.raises(ValueError):
        D._normalizar_tipos("pagadas")


def test_indice_funde_por_clave_y_elige_vigente(tmp_path):
    import json
    idx = tmp_path / "declaraciones.json"
    normal = {"periodo": "2026-01", "tipo": "declaracion", "numero_operacion": "265270003579",
              "tipo_declaracion": "Normal", "fecha_presentacion": "17/02/2026", "archivo": "a.pdf"}
    compl = {"periodo": "2026-01", "tipo": "declaracion", "numero_operacion": "261870059439",
             "tipo_declaracion": "Complementaria", "fecha_presentacion": "17/03/2026", "archivo": "b.pdf"}
    acuse = {"periodo": "2026-01", "tipo": "acuse", "numero_operacion": "265270003579",
             "fecha_presentacion": "17/02/2026", "archivo": "c.pdf"}
    D.actualizar_indice(idx, [compl, normal, acuse])
    # Reejecutar con un registro actualizado no duplica: misma clave → reemplaza.
    normal2 = dict(normal, archivo="a2.pdf")
    salida = D.actualizar_indice(idx, [normal2])
    assert len(salida) == 3
    assert [r["archivo"] for r in salida if r["tipo"] == "declaracion"] == ["a2.pdf", "b.pdf"]  # por fecha
    assert json.loads(idx.read_text(encoding="utf-8")) == salida
    # La vigente del periodo es la complementaria (más reciente), no la normal.
    assert D.declaracion_vigente(salida, "2026-01")["numero_operacion"] == "261870059439"
    assert D.declaracion_vigente(salida, "2026-02") is None


def test_api_publica_declaraciones():
    import sat_descarga
    assert callable(D.descargar_declaraciones_ciec)
    assert callable(D.descargar_declaraciones_fiel)
    assert sat_descarga.descargar_declaraciones_fiel is D.descargar_declaraciones_fiel
