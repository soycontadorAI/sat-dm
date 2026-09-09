"""Tests de la estructura del CLI tras la reorganización por canal.

Verifican que el grupo `descargar` tenga los subcomandos cfdi/ciec/constancia y que
todos los --help carguen (detecta imports rotos por la reorg). No ejecutan descargas.
"""

from click.testing import CliRunner

from sat_descarga.cli.main import cli


def test_comandos_top_level():
    out = CliRunner().invoke(cli, ["--help"]).output
    for c in ("descargar", "empresas", "validar", "metadata", "organizar", "retomar"):
        assert c in out


def test_descargar_es_grupo_con_subcomandos():
    out = CliRunner().invoke(cli, ["descargar", "--help"]).output
    for sub in ("cfdi", "ciec", "constancia", "opinion", "declaraciones", "diot"):
        assert sub in out


def test_help_de_cada_subcomando_carga():
    r = CliRunner()
    for args in (["descargar", "cfdi"], ["descargar", "ciec"],
                 ["descargar", "constancia"], ["descargar", "opinion"],
                 ["descargar", "declaraciones"], ["descargar", "diot"]):
        res = r.invoke(cli, args + ["--help"])
        assert res.exit_code == 0, f"{args} --help falló: {res.output}"


def test_reexports_raiz_disponibles():
    import sat_descarga
    for nombre in (
        "descargar_cfdi", "FIEL", "verificar_solicitud_existente",
        "descargar_cfdi_ciec", "descargar_constancia_ciec", "descargar_constancia_fiel",
        "descargar_opinion_ciec", "descargar_opinion_fiel",
        "descargar_declaraciones_ciec", "descargar_declaraciones_fiel",
        "descargar_diot_ciec", "descargar_diot_fiel",
    ):
        assert hasattr(sat_descarga, nombre), f"falta re-export: {nombre}"


def test_help_anuncia_layout_descargas():
    # Los --salida deben anunciar el nuevo layout unificado descargas/.
    r = CliRunner()
    assert "descargas" in r.invoke(cli, ["descargar", "cfdi", "--help"]).output
    assert "descargas/cfdi" in r.invoke(cli, ["descargar", "ciec", "--help"]).output
