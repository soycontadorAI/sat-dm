"""
XML de un CFDI → `nodos`: el comprobante COMPLETO como JSON, sin elegir campos.

El parser (`cfdi_parser.py`) extrae solo lo que los reportes de hoy entienden.
`nodos` guarda todo lo demás (complementos como Carta Porte o Comercio
Exterior, addendas, atributos que no mapeamos) para que un reporte
personalizado pueda pedir cualquier dato por su ruta sin volver a leer el XML.

Forma (contrato estable; si cambia, sube `NODOS_VERSION` y reprocesa):

- La raíz es `{"Comprobante": {...}}` (el nombre local del elemento raíz).
- Nombres SIN prefijo de namespace: `cfdi:Emisor` → `Emisor`,
  `tfd:TimbreFiscalDigital` → `TimbreFiscalDigital`.
- Atributos e hijos viven en el mismo dict. Si un atributo choca con el
  nombre de un hijo, el atributo se guarda como `@Nombre`.
- Un hijo que aparece una vez es un dict; si se repite, una lista de dicts
  (`Conceptos.Concepto` es dict con un concepto y lista con varios). Para
  leer sin importar cuál de las dos, usa `valores()`.
- El texto de un elemento (raro en CFDI, común en addendas) va en `#text`.
- Valores siempre como texto, tal cual vienen en el XML.

Ejemplo de rutas: `Comprobante.Folio`, `Comprobante.Emisor.Nombre`,
`Comprobante.Complemento.TimbreFiscalDigital.UUID`,
`Comprobante.Conceptos.Concepto.Importe` (una por concepto).
"""

from __future__ import annotations

from typing import Any, Union

from ..core.xml_seguro import leer_tolerante, nombre_local

NODOS_VERSION = 1


def xml_a_nodos(xml: Union[bytes, str]) -> dict:
    """Convierte el XML de un CFDI a `nodos`. Lee en modo tolerante; lanza
    `etree.XMLSyntaxError` solo si ni así se puede leer."""
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    raiz = leer_tolerante(xml, huge_tree=True).raiz
    return {nombre_local(raiz): _elemento(raiz)}


def _elemento(elem) -> dict:
    nodo: dict[str, Any] = {}
    for nombre, valor in elem.attrib.items():
        nodo[nombre_local(nombre)] = valor

    for hijo in elem:
        if not isinstance(hijo.tag, str):  # comentarios e instrucciones
            continue
        nombre = nombre_local(hijo)
        valor = _elemento(hijo)
        if nombre in nodo and not _es_hijo(nodo[nombre]):
            # Choque con un atributo del mismo nombre: el atributo se aparta.
            nodo["@" + nombre] = nodo.pop(nombre)
        previo = nodo.get(nombre)
        if previo is None:
            nodo[nombre] = valor
        elif isinstance(previo, list):
            previo.append(valor)
        else:
            nodo[nombre] = [previo, valor]

    texto = (elem.text or "").strip()
    if texto:
        nodo["#text"] = texto
    return nodo


def _es_hijo(valor: Any) -> bool:
    return isinstance(valor, (dict, list))


def valores(nodos: dict, ruta: str) -> list:
    """Todos los valores en `ruta` (separada por puntos), recorriendo las
    listas que encuentre. `valores(n, "Comprobante.Conceptos.Concepto.Importe")`
    da un importe por concepto; una ruta que no existe da `[]`."""
    actuales: list = [nodos]
    for parte in ruta.split("."):
        siguientes: list = []
        for actual in actuales:
            for item in actual if isinstance(actual, list) else [actual]:
                if isinstance(item, dict) and parte in item:
                    valor = item[parte]
                    siguientes.extend(valor if isinstance(valor, list) else [valor])
        actuales = siguientes
    return actuales
