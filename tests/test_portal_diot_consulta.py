"""Tests de la lógica pura de la consulta/descarga de DIOT presentadas (PDF, Excel, acuse)."""

import pytest

from sat_descarga.portal import diot_consulta as C

# Fila real del recorrido (sep 2026): onclick con las URLs del PDF y del Excel.
_ONCLICK_PDF = ("abrirArchivoPDF('/Consulta/RecuperarArchivo?enLinea=0&amp;tipoDocumento=1"
                "&amp;numeroOperacion=260330094501&amp;ejercicio=2026&amp;tipoArchivo=0&amp;periodo=001"
                "&amp;tipoConcepto=9006')")
_ONCLICK_XLS = ("buscarArchivoExcel('/Consulta/CrearArchivoExcelDiot?enLinea=0&amp;numeroOperacion=260330094501',"
                "'/Consulta/RecuperarArchivo?enLinea=0&amp;numeroOperacion=260330094501&amp;tipoArchivo=1',"
                "'/Consulta/ConsultarEstadoDiotExcelDiot?enLinea=0&amp;numeroOperacion=260330094501')")
_ENCABEZADOS = ["", "", "No. de Operación", "Estatus", "Tipo de Declaración", "Tipo de Complementaria",
                "Fecha de Presentación", "Periodicidad", "Período"]


def test_entrada_landing_y_rutas():
    assert C.DIOT_CONSULTA_URL_ENTRADA == "https://pstcdi.clouda.sat.gob.mx/"
    assert C.RUTAS_CONSULTA == {"declaracion": "/Consulta/Consulta/1", "acuse": "/Consulta/Consulta/3"}
    assert C.CONCEPTO_DIOT == "9006"
    assert not C._es_landing_diot("https://loginda.siat.sat.gob.mx/nidp/wsfed/ep?id=ciec"
                                  "&target=https%3A%2F%2Fpstcdi.clouda.sat.gob.mx%2F")
    assert not C._es_landing_diot("https://pstcdi.clouda.sat.gob.mx/nidp/app")
    assert C._es_landing_diot("https://pstcdi.clouda.sat.gob.mx/")
    assert C._es_landing_diot("https://pstcdi.clouda.sat.gob.mx/Consulta/Consulta/3")


def test_urls_de_onclick():
    assert C.urls_de_onclick(_ONCLICK_PDF) == {
        "pdf": "/Consulta/RecuperarArchivo?enLinea=0&tipoDocumento=1&numeroOperacion=260330094501"
               "&ejercicio=2026&tipoArchivo=0&periodo=001&tipoConcepto=9006"}
    x = C.urls_de_onclick(_ONCLICK_XLS)
    assert x["crear"].startswith("/Consulta/CrearArchivoExcelDiot?")
    assert "tipoArchivo=1" in x["recuperar"]
    assert x["estado"].startswith("/Consulta/ConsultarEstadoDiotExcelDiot?")
    # href normal (portal de pagos provisionales) y nada
    assert C.urls_de_onclick(None, "/Consulta/RecuperarArchivo?x=1") == {"pdf": "/Consulta/RecuperarArchivo?x=1"}
    assert C.urls_de_onclick("javascript:void(0)", "javascript:void(0)") == {}


def test_mapear_filas_por_encabezado():
    filas = [{"celdas": ["", "", "260330094501", "Vigente", "Normal", "", "20/02/2026", "1-Mensual", "Enero", ""],
              "pdf": {"onclick": _ONCLICK_PDF, "href": "javascript:void(0)"},
              "excel": {"onclick": _ONCLICK_XLS, "href": "#"}}]
    (r,) = C.mapear_filas(_ENCABEZADOS, filas)
    assert r["numero_operacion"] == "260330094501" and r["estado"] == "Vigente"
    assert r["tipo_declaracion"] == "Normal" and r["fecha_presentacion"] == "20/02/2026"
    assert r["_pdf"].endswith("tipoConcepto=9006") and r["_excel"]["recuperar"]
    # acuse: sin columna Excel (td oculto sin link) → _excel vacío
    (a,) = C.mapear_filas(_ENCABEZADOS, [{"celdas": filas[0]["celdas"], "pdf": filas[0]["pdf"], "excel": None}])
    assert a["_excel"] == {} and a["numero_operacion"] == "260330094501"


def test_nombre_archivo_sugerido_y_colision():
    usados = set()
    assert C.nombre_archivo("Decla_260330094501_0012026.pdf", "declaracion", "260330094501", "RFC", "2026-01",
                            "pdf", usados) == "Decla_260330094501_0012026.pdf"
    # el acuse con el mismo nombre sugerido no pisa a la declaración
    assert C.nombre_archivo("Decla_260330094501_0012026.pdf", "acuse", "260330094501", "RFC", "2026-01",
                            "pdf", usados) == "Acuse.Decla_260330094501_0012026.pdf"
    assert C.nombre_archivo(None, "declaracion", "1", "RFC", "2026-01", "xlsx", set()) == "DIOT_RFC_2026-01_1.xlsx"


def test_normalizar_tipos_y_api():
    assert C._normalizar_tipos("ambos") == ["declaracion", "acuse"]
    assert C._normalizar_tipos("acuse") == ["acuse"]
    with pytest.raises(ValueError):
        C._normalizar_tipos("excel")
    import sat_descarga
    assert sat_descarga.descargar_diot_fiel is C.descargar_diot_fiel
    assert callable(sat_descarga.descargar_diot_ciec)
