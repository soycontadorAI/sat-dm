"""
Parser lxml endurecido para XML de origen EXTERNO (respuestas del SAT, CFDIs
del usuario). Desactiva la resolución de entidades, DTDs y el acceso a red
(anti-XXE / billion-laughs). Úsalo en todo `fromstring`/`parse` cuyo input no
generamos nosotros; los templates SOAP propios pueden seguir con el parser
default de lxml.
"""

import re
from dataclasses import dataclass
from typing import Optional

from lxml import etree

_MAX_AVISOS = 5

# Defectos de los que el modo `recover` sale con el documento completo:
# - una declaración de namespace con URI inválido (`xmlns:schemaLocation="a b"`)
#   solo vive en `nsmap`; elementos y atributos quedan intactos;
# - un prefijo sin declarar (`pago20:Pagos` sin `xmlns:pago20`, o
#   `xsi:schemaLocation` sin `xmlns:xsi`): el nodo queda con el nombre literal y
#   quien lea por nombre local con `nombre_local` / `LOCAL` lo encuentra igual.
# Todo lo demás (`&` o `<` sueltos, comillas rotas, XML truncado) puede perder
# datos: el atributo o el resto del documento se caen.
_TIPOS_SIN_PERDIDA = frozenset({"WAR_NS_URI", "WAR_NS_URI_RELATIVE", "NS_ERR_UNDEFINED_NAMESPACE"})

# Predicado XPath por nombre local con la variable `$n`, que también encuentra
# los nodos con prefijo sin declarar (su local-name() es "pago20:Pagos").
LOCAL = "[local-name()=$n or substring-after(local-name(), ':')=$n]"

_ENCODING_DECLARADO = re.compile(rb"""^\s*<\?xml[^>]*?encoding\s*=\s*["']([A-Za-z0-9._-]+)["']""")


def parser_seguro(huge_tree: bool = False, recover: bool = False) -> etree.XMLParser:
    """
    Parser sin entidades, sin DTD y sin red.

    `huge_tree=True` solo para respuestas grandes del SAT (los paquetes de
    descarga exceden los límites default de lxml); en cualquier otro caso
    dejar el default, que además acota profundidad/tamaño.

    `recover=True` lee XML mal formado en lo que se pueda (ver `leer_tolerante`);
    las protecciones anti-XXE son las mismas en ambos modos.
    """
    return etree.XMLParser(
        huge_tree=huge_tree,
        resolve_entities=False,
        no_network=True,
        dtd_validation=False,
        load_dtd=False,
        recover=recover,
    )


def fromstring_seguro(data: bytes, huge_tree: bool = False):
    """`etree.fromstring` con `parser_seguro()`."""
    return etree.fromstring(data, parser=parser_seguro(huge_tree=huge_tree))


def nombre_local(nodo) -> str:
    """Nombre sin namespace ni prefijo de un elemento (o del nombre de un
    atributo). Tolera el prefijo sin declarar que deja la lectura tolerante
    (`pago20:Pagos` literal), donde `etree.QName` lanza ValueError. Comentarios
    e instrucciones de proceso dan ""."""
    nombre = nodo if isinstance(nodo, str) else getattr(nodo, "tag", None)
    if not isinstance(nombre, str):
        return ""
    if nombre.startswith("{"):
        return nombre.rpartition("}")[2]
    return nombre.rpartition(":")[2]


@dataclass(frozen=True)
class LecturaTolerante:
    """Resultado de `leer_tolerante`."""
    raiz: etree._Element
    avisos: tuple[str, ...]   # vacío si el XML era válido; si `recodificado`, el
                              # primero es `AVISO_RECODIFICADO` y luego los del parser
    sin_perdida: bool         # lo leído está completo (siempre True si el XML era válido)
    recodificado: bool        # traía bytes fuera de UTF-8 y se leyeron como Windows-1252


AVISO_RECODIFICADO = "Bytes fuera de UTF-8; se leyeron como Windows-1252"

# Bytes que no eran UTF-8 válido, tras decodificar con `surrogateescape`.
_SUSTITUTOS = re.compile("[\udc80-\udcff]+")


def _recodificar_cp1252(data: bytes) -> Optional[tuple[bytes, bool]]:
    """XML que declara UTF-8 (o nada) pero trae bytes de Windows-1252/Latin-1 (un
    `PEÑA` guardado por un sistema viejo): cada secuencia inválida se lee como
    Windows-1252 y lo demás se respeta como UTF-8. Devuelve `(bytes en UTF-8,
    completo)`; `completo` es False si algún byte no existe en Windows-1252
    (0x81, 0x8D, 0x8F, 0x90, 0x9D) y quedó como «�». None si los bytes ya son
    UTF-8 válido, si es UTF-16/32 o si declara otra codificación (eso lo lee
    libxml2)."""
    if b"\x00" in data[:200]:
        return None
    m = _ENCODING_DECLARADO.match(data[:200])
    declarado = m.group(1).decode("ascii").lower().replace("_", "-") if m else "utf-8"
    if declarado not in ("utf-8", "utf8"):
        return None
    texto = data.decode("utf-8", errors="surrogateescape")
    if not _SUSTITUTOS.search(texto):
        return None
    completo = True

    def _como_cp1252(m: re.Match) -> str:
        nonlocal completo
        crudos = bytes(ord(c) - 0xDC00 for c in m.group())
        try:
            return crudos.decode("cp1252")
        except UnicodeDecodeError:
            completo = False
            return crudos.decode("cp1252", errors="replace")

    return _SUSTITUTOS.sub(_como_cp1252, texto).encode("utf-8"), completo


def _excede_limites(error: etree.XMLSyntaxError) -> bool:
    """¿Falló por los límites de libxml2 (texto de más de 10 MB, más de 256
    niveles) y no por estar mal formado?"""
    return any(e.type_name == "ERR_RESOURCE_LIMIT" for e in error.error_log)


def leer_tolerante(data: bytes, huge_tree: bool = False) -> LecturaTolerante:
    """
    Lee un XML en modo estricto y, si falla, lo intenta recuperar.

    Hay CFDIs reales con defectos que no tocan su contenido: un
    `xmlns:schemaLocation="..."` en el complemento de registro fiscal (libxml2
    lo rechaza como URI inválido) o bytes de Windows-1252 en un XML que declara
    UTF-8. Primero se corrige la codificación, si aplica; luego se lee en modo
    `recover`. `sin_perdida` dice si lo recuperado está completo; si no, el
    llamador debe avisar que puede faltar información (o rechazarlo). Los
    mensajes del parser quedan en `avisos`.

    Solo para documentos del usuario (CFDIs). Las respuestas SOAP del SAT
    siguen con `fromstring_seguro`, estrictas.

    Si ni en modo tolerante se puede leer, relanza el error ESTRICTO original.
    """
    try:
        return LecturaTolerante(fromstring_seguro(data, huge_tree=huge_tree), (), True, False)
    except etree.XMLSyntaxError as error:
        original = restante = error
    if not huge_tree and _excede_limites(original):
        # XML válido pero grande (una addenda con un PDF en base64): se relaja el
        # límite solo para él, no se lee como mal formado.
        huge_tree = True
        try:
            return LecturaTolerante(fromstring_seguro(data, huge_tree=True), (), True, False)
        except etree.XMLSyntaxError as error:
            original = restante = error

    avisos: list[str] = []
    sin_perdida = True
    recodificado = _recodificar_cp1252(data)
    if recodificado is not None:
        data, sin_perdida = recodificado
        avisos.append(AVISO_RECODIFICADO)
        try:
            raiz = fromstring_seguro(data, huge_tree=huge_tree)
            return LecturaTolerante(raiz, tuple(avisos), sin_perdida, True)
        except etree.XMLSyntaxError as error:
            restante = error  # además trae otro defecto: sigue el modo recover

    parser = parser_seguro(huge_tree=huge_tree, recover=True)
    try:
        raiz = etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError:
        raiz = None
    if raiz is None:
        raise original

    entradas = list(parser.error_log)
    del_parser: list[str] = []
    for entrada in entradas:
        mensaje = (entrada.message or "").strip()
        if mensaje and mensaje not in del_parser:
            del_parser.append(mensaje)
    avisos.extend(del_parser or [str(restante)])
    sin_perdida = sin_perdida and bool(entradas) and all(
        e.type_name in _TIPOS_SIN_PERDIDA for e in entradas
    )
    return LecturaTolerante(raiz, tuple(avisos[:_MAX_AVISOS]), sin_perdida,
                            recodificado is not None)
