"""Tests para core.xml_seguro — parser lxml endurecido (anti-XXE)."""

import pytest
from lxml import etree

from sat_descarga.core.xml_seguro import fromstring_seguro, parser_seguro


class TestParserSeguro:

    def test_no_expande_entidades_internas(self):
        # Con el parser default de lxml, &a; se expandiría a "secreto".
        xml = b'<!DOCTYPE r [<!ENTITY a "secreto">]><r>&a;</r>'
        root = fromstring_seguro(xml)
        assert root.text != "secreto"

    def test_no_resuelve_entidades_externas(self, tmp_path):
        # Un XXE clásico: entidad externa que apunta a un archivo local.
        objetivo = tmp_path / "datos.txt"
        objetivo.write_text("contenido-privado")
        xml = (
            f'<!DOCTYPE r [<!ENTITY xxe SYSTEM "file://{objetivo}">]>'
            f"<r>&xxe;</r>"
        ).encode()
        root = fromstring_seguro(xml)
        assert root.text is None or "contenido-privado" not in (root.text or "")

    def test_xml_normal_parsea_igual(self):
        xml = b'<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Version="4.0"/>'
        root = fromstring_seguro(xml)
        assert root.get("Version") == "4.0"

    def test_huge_tree_configurable(self):
        # Solo verifica que la opción se acepta (las respuestas del SAT la requieren).
        parser = parser_seguro(huge_tree=True)
        root = etree.fromstring(b"<r><hijo/></r>", parser=parser)
        assert len(root) == 1


class TestLeerTolerante:

    def test_modo_recover_tampoco_resuelve_entidades_externas(self, tmp_path):
        from sat_descarga.core.xml_seguro import leer_tolerante

        objetivo = tmp_path / "datos.txt"
        objetivo.write_text("contenido-privado")
        # `xmlns:x="a b"` fuerza la vía tolerante con el mismo XXE de arriba.
        xml = (
            f'<!DOCTYPE r [<!ENTITY xxe SYSTEM "file://{objetivo}">]>'
            f'<r xmlns:x="a b">&xxe;</r>'
        ).encode()
        lectura = leer_tolerante(xml)
        assert lectura.avisos
        assert "contenido-privado" not in (lectura.raiz.text or "")
