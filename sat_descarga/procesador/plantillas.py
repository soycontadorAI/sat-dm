"""
Plantillas de export del procesador de CFDI (reportes personalizables).

Una plantilla dice qué columnas lleva el Excel/CSV, en qué orden y con qué
encabezado. Tiene dos listas:

- `columnas`: las del CFDI (campos de nivel "cfdi").
- `detalle_concepto`: el bloque que se usa con "Una fila por concepto"
  (campos de nivel "concepto"). Ocupa el lugar de la columna "Conceptos";
  si la plantilla no la tiene, va al final.

El catálogo de campos vive aquí y es la única fuente: la UI lo pide en
`GET /procesador/cfdi/campos`. Cada campo se lee de las columnas planas del
índice o de `nodos` (procesador/nodos.py); los de `nodos` caen a lo plano
(o a `raw`) cuando el CFDI no tiene documento. Fuera del catálogo, un campo
puede ser una ruta de `nodos`: `ruta:Comprobante.Complemento.…` o, relativa
al concepto, `ruta_concepto:InformacionAduanera.NumeroPedimento`.

Opciones que se eligen al exportar (no viven en la plantilla):

- `por_concepto`: un renglón por concepto, repitiendo los datos del CFDI.
- `convertir_mxn`: importes en moneda extranjera × el tipo de cambio del
  CFDI (los del complemento de pago, × el de cada pago). Su encabezado lleva
  " MXN".

Las plantillas del sistema (`clasico`, la predeterminada, y `completo`) están
en código; las del usuario, en `plantillas_store.py`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Iterator, Optional

from ..utils.regimenes_fiscales import REGIMENES_FISCALES
from .catalogos import (
    FORMAS_PAGO,
    METODOS_PAGO,
    OBJETOS_IMPUESTO,
    TIPOS_COMPROBANTE,
    TIPOS_RELACION,
    USOS_CFDI,
)
from .db import CfdiFiltros, ProcesadorDB, _construir_where
from .nodos import valores

logger = logging.getLogger(__name__)

TIPOS = ("texto", "fecha", "importe", "numero", "tipo_cambio")
NIVELES = ("cfdi", "concepto")

PREFIJO_RUTA = "ruta:"
PREFIJO_RUTA_CONCEPTO = "ruta_concepto:"
_RUTA_RE = re.compile(r"^[A-Za-z_@#][\w@#-]*(\.[A-Za-z_@#][\w@#-]*)*$")
MAX_RUTA = 300

MAX_COLUMNAS = 120
MAX_ENCABEZADO = 100
MAX_NOMBRE = 80

# Límites de una hoja de Excel (sin contar el encabezado).
MAX_FILAS_EXCEL = 1_048_575
MAX_TEXTO_EXCEL = 32_767

_REGIMENES = {r["clave"]: r["descripcion"] for r in REGIMENES_FISCALES}
_ORIGENES = {
    "sat_ws": "Descarga SAT (Web Service)",
    "sat_portal": "Descarga SAT (portal)",
    "carpeta": "Carpeta de descargas",
    "manual": "Carga manual",
}
_LISTAS = {
    "EFOS": "EFOS (69-B)",
    "Aclarado": "69-B aclarado",
    "69": "Lista 69",
    "Limpio": "Limpio",
}


# ---------------------------------------------------------------------------
# Lo que un campo puede leer
# ---------------------------------------------------------------------------

_SIN_CARGAR = object()


class Fila:
    """Un renglón en construcción: el CFDI del índice (dict de `iter_all`),
    sus `nodos` (se cargan solo si algún campo los pide) y, en modo por
    concepto, el concepto del renglón (dict con los nombres del XML)."""

    def __init__(self, cfdi: dict, db: ProcesadorDB, convertir_mxn: bool = False):
        self.cfdi = cfdi
        self.db = db
        self.convertir_mxn = convertir_mxn
        self.concepto: dict = {}
        self.concepto_n = 0
        self.conceptos_total = 0
        self._nodos: Any = _SIN_CARGAR
        self._conceptos: Optional[list[dict]] = None

    @property
    def nodos(self) -> Optional[dict]:
        if self._nodos is _SIN_CARGAR:
            doc = self.db.documento(self.cfdi["uuid"], self.cfdi["mi_rfc"])
            self._nodos = doc["nodos"] if doc else None
        return self._nodos

    @property
    def comprobante(self) -> dict:
        c = (self.nodos or {}).get("Comprobante")
        return c if isinstance(c, dict) else {}

    def conceptos(self) -> list[dict]:
        """Conceptos con los nombres del XML: de `nodos` o, si el CFDI no tiene
        documento, de la tabla `conceptos` (sin impuestos ni No. identificación)."""
        if self._conceptos is None:
            if self.nodos:
                self._conceptos = [
                    c for c in valores(self.nodos, "Comprobante.Conceptos.Concepto")
                    if isinstance(c, dict)
                ]
            else:
                self._conceptos = [
                    _concepto_de_tabla(c)
                    for c in self.db.conceptos_de(self.cfdi["uuid"], self.cfdi["mi_rfc"])
                ]
        return self._conceptos

    def mxn(self, valor: Any) -> Optional[float]:
        """Importe del CFDI como número, convertido a MXN si se pidió."""
        n = _num(valor)
        if n is None or not self.convertir_mxn:
            return n
        return n * _factor(self.cfdi.get("moneda"), self.cfdi.get("tipo_cambio"))


def _concepto_de_tabla(c: dict) -> dict:
    return {
        "ClaveProdServ": c.get("clave_prod_serv"),
        "Descripcion": c.get("descripcion"),
        "Cantidad": c.get("cantidad"),
        "ClaveUnidad": c.get("clave_unidad"),
        "Unidad": c.get("unidad"),
        "ValorUnitario": c.get("valor_unitario"),
        "Importe": c.get("importe"),
        "Descuento": c.get("descuento"),
    }


# ---------------------------------------------------------------------------
# Helpers de lectura
# ---------------------------------------------------------------------------


def _num(v: Any) -> Optional[float]:
    if v is None or v == "" or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def _factor(moneda: Any, tipo_cambio: Any) -> float:
    """Pesos por unidad de `moneda` (1 si ya es MXN o falta el tipo de cambio)."""
    if not moneda or moneda in ("MXN", "XXX"):
        return 1.0
    tc = _num(tipo_cambio)
    return tc if tc and tc > 0 else 1.0


def _fecha(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v)[:19])
    except ValueError:
        return None


def _clave(clave: Any, catalogo: dict) -> str:
    if not clave:
        return ""
    desc = catalogo.get(str(clave))
    return f"{clave} - {desc}" if desc else str(clave)


def _unir(vals: Iterable[Any], sep: str = " | ") -> str:
    return sep.join(str(v) for v in vals if v not in (None, ""))


def _unicos(vals: Iterable[Any]) -> list:
    vistos: list = []
    for v in vals:
        if v not in (None, "") and v not in vistos:
            vistos.append(v)
    return vistos


def _lista(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _de(nodo: Any, ruta: str) -> list:
    """`valores()` relativo a un nodo (p. ej. a un concepto)."""
    return valores({"_": nodo}, "_." + ruta) if isinstance(nodo, dict) else []


def _impuestos(concepto: dict, impuesto: str, retenciones: bool = False) -> list[dict]:
    ruta = "Impuestos.Retenciones.Retencion" if retenciones else "Impuestos.Traslados.Traslado"
    return [
        t for t in _de(concepto, ruta)
        if isinstance(t, dict) and t.get("Impuesto") == impuesto
    ]


def _suma(items: list[dict], attr: str) -> Optional[float]:
    nums = [n for n in (_num(i.get(attr)) for i in items) if n is not None]
    return sum(nums) if nums else None


def _tasa(items: list[dict]) -> str:
    etiquetas = []
    for t in items:
        if t.get("TipoFactor") == "Exento":
            etiquetas.append("Exento")
            continue
        n = _num(t.get("TasaOCuota"))
        if n is None:
            continue
        etiquetas.append(f"Cuota {n:g}" if t.get("TipoFactor") == "Cuota" else f"{n * 100:g}%")
    return _unir(_unicos(etiquetas))


def _pagos(f: Fila) -> list[dict]:
    """Los `Pago` del complemento (todos). Sin documento cae al primer pago
    que guardó el parser en `raw` (sin su tipo de cambio)."""
    if f.cfdi.get("tipo") != "P":
        return []
    if f.nodos:
        return [
            p for p in valores(f.nodos, "Comprobante.Complemento.Pagos.Pago")
            if isinstance(p, dict)
        ]
    dp = (f.cfdi.get("raw") or {}).get("datos_pago")
    if not isinstance(dp, dict):
        return []
    return [{
        "FechaPago": dp.get("fecha_pago"),
        "Monto": dp.get("monto_pago"),
        "FormaDePagoP": dp.get("forma_de_pago"),
        "MonedaP": dp.get("moneda_pago"),
        "DoctoRelacionado": [
            {"IdDocumento": d.get("id_documento")}
            for d in dp.get("documentos_relacionados") or []
            if isinstance(d, dict)
        ],
    }]


# ---------------------------------------------------------------------------
# Lectores de los campos con lógica
# ---------------------------------------------------------------------------


def _tipo_cambio(f: Fila) -> Optional[float]:
    moneda = f.cfdi.get("moneda")
    if not moneda or moneda == "MXN":
        return 1.0
    tc = _num(f.cfdi.get("tipo_cambio"))
    return tc if tc and tc > 0 else 1.0


def _validacion_local(f: Fila) -> str:
    avisos = f.cfdi.get("warnings") or []
    if not avisos:
        return "Válido"
    return f"{len(avisos)} error(es): {'; '.join(str(a) for a in avisos)}"


def _estado_diot(f: Fila) -> str:
    if not f.cfdi.get("elegible_diot"):
        return "No aplica"
    return "Pasa a DIOT" if f.cfdi.get("incluir_diot") else "Excluido"


def _cfdi_relacionados(f: Fila) -> str:
    partes = []
    for rel in valores(f.nodos or {}, "Comprobante.CfdiRelacionados"):
        if not isinstance(rel, dict):
            continue
        uuids = _unir((r.get("UUID") for r in _lista(rel.get("CfdiRelacionado"))
                       if isinstance(r, dict)), sep=", ")
        tipo = _clave(rel.get("TipoRelacion"), TIPOS_RELACION)
        partes.append(f"{tipo}: {uuids}" if tipo else uuids)
    return _unir(partes)


def _imp_locales(f: Fila, attr: str) -> Optional[float]:
    total = _suma(
        [i for i in valores(f.nodos or {}, "Comprobante.Complemento.ImpuestosLocales")
         if isinstance(i, dict)],
        attr,
    )
    return f.mxn(total)


def _conceptos(f: Fila) -> str:
    """Las descripciones, con las repetidas agrupadas («Magna ×250»): una
    factura global trae cientos de conceptos iguales. En modo por concepto
    (sin bloque de detalle) es la descripción del renglón."""
    if f.concepto:
        return f.concepto.get("Descripcion") or ""
    cuenta: dict[str, int] = {}
    for c in f.conceptos():
        d = c.get("Descripcion")
        if d:
            cuenta[d] = cuenta.get(d, 0) + 1
    return _unir(d if n == 1 else f"{d} ×{n}" for d, n in cuenta.items())


def _pago_fecha(f: Fila) -> Any:
    fechas = [d for d in (_fecha(p.get("FechaPago")) for p in _pagos(f)) if d]
    if len(fechas) == 1:
        return fechas[0]
    return _unir(d.strftime("%d/%m/%Y") for d in fechas) or None


def _pago_monto(f: Fila) -> Optional[float]:
    total = None
    for p in _pagos(f):
        n = _num(p.get("Monto"))
        if n is None:
            continue
        if f.convertir_mxn:
            n *= _factor(p.get("MonedaP"), p.get("TipoCambioP"))
        total = (total or 0.0) + n
    return total


def _docs_relacionados(f: Fila) -> str:
    return _unir(
        d.get("IdDocumento")
        for p in _pagos(f)
        for d in _lista(p.get("DoctoRelacionado"))
        if isinstance(d, dict)
    )


def _c(attr: str) -> Callable[[Fila], Any]:
    return lambda f: f.concepto.get(attr) or ""


def _c_mxn(attr: str) -> Callable[[Fila], Any]:
    return lambda f: f.mxn(f.concepto.get(attr)) if f.concepto else None


def _c_impuesto(impuesto: str, attr: str, retenciones: bool = False) -> Callable[[Fila], Any]:
    return lambda f: f.mxn(_suma(_impuestos(f.concepto, impuesto, retenciones), attr))


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Campo:
    id: str
    etiqueta: str
    grupo: str
    leer: Callable[[Fila], Any] = field(repr=False, compare=False)
    tipo: str = "texto"
    nivel: str = "cfdi"
    # Importe en la moneda del CFDI: con convertir_mxn se convierte y su
    # encabezado lleva " MXN".
    convertible: bool = False
    descripcion: str = ""

    def a_dict(self) -> dict:
        return {
            "id": self.id,
            "etiqueta": self.etiqueta,
            "grupo": self.grupo,
            "tipo": self.tipo,
            "nivel": self.nivel,
            "convertible": self.convertible,
            "descripcion": self.descripcion,
        }


def _plano(col: str) -> Callable[[Fila], Any]:
    return lambda f: f.cfdi.get(col) or ""


def _importe(col: str) -> Callable[[Fila], Any]:
    return lambda f: f.mxn(f.cfdi.get(col))


_CATALOGO: list[Campo] = [
    # Comprobante
    Campo("fecha_emision", "Fecha Emisión", "Comprobante",
          lambda f: _fecha(f.cfdi.get("fecha")), tipo="fecha"),
    Campo("fecha_timbrado", "Fecha Timbrado", "Comprobante",
          lambda f: _fecha(f.cfdi.get("fecha_timbrado")), tipo="fecha"),
    Campo("serie", "Serie", "Comprobante", _plano("serie")),
    Campo("folio", "Folio", "Comprobante", _plano("folio")),
    Campo("uuid", "UUID", "Comprobante", _plano("uuid")),
    Campo("tipo_comprobante", "Tipo Comprobante", "Comprobante",
          lambda f: _clave(f.cfdi.get("tipo"), TIPOS_COMPROBANTE)),
    Campo("version", "Versión", "Comprobante", _plano("version")),
    Campo("lugar_expedicion", "Lugar Expedición", "Comprobante", _plano("lugar_expedicion")),
    Campo("condiciones_pago", "Condiciones de Pago", "Comprobante",
          lambda f: f.comprobante.get("CondicionesDePago") or ""),
    Campo("cfdi_relacionados", "CFDI Relacionados", "Comprobante", _cfdi_relacionados,
          descripcion="Tipo de relación y UUID de los CFDI relacionados."),
    Campo("direccion", "Emitido / Recibido", "Comprobante",
          lambda f: {"E": "Emitido", "R": "Recibido"}.get(f.cfdi.get("direccion") or "", "")),
    Campo("origen", "Origen", "Comprobante",
          lambda f: _ORIGENES.get(f.cfdi.get("origen") or "", "")),
    # Emisor y receptor
    Campo("emisor_rfc", "RFC Emisor", "Emisor y receptor", _plano("emisor_rfc")),
    Campo("emisor_nombre", "Nombre Emisor", "Emisor y receptor", _plano("emisor_nombre")),
    Campo("emisor_regimen", "Régimen Emisor", "Emisor y receptor",
          lambda f: _clave(f.cfdi.get("emisor_regimen_fiscal"), _REGIMENES)),
    Campo("receptor_rfc", "RFC Receptor", "Emisor y receptor", _plano("receptor_rfc")),
    Campo("receptor_nombre", "Nombre Receptor", "Emisor y receptor", _plano("receptor_nombre")),
    Campo("uso_cfdi", "Uso CFDI", "Emisor y receptor",
          lambda f: _clave(f.cfdi.get("receptor_uso_cfdi"), USOS_CFDI)),
    Campo("receptor_regimen", "Régimen Receptor", "Emisor y receptor",
          lambda f: _clave((f.comprobante.get("Receptor") or {}).get("RegimenFiscalReceptor"),
                           _REGIMENES)),
    Campo("receptor_cp", "CP Receptor", "Emisor y receptor",
          lambda f: (f.comprobante.get("Receptor") or {}).get("DomicilioFiscalReceptor") or ""),
    # Importes
    Campo("subtotal", "SubTotal", "Importes", _importe("sub_total"),
          tipo="importe", convertible=True),
    Campo("descuento", "Descuento", "Importes", _importe("descuento"),
          tipo="importe", convertible=True),
    Campo("total", "Total", "Importes", _importe("total"), tipo="importe", convertible=True),
    Campo("moneda", "Moneda", "Importes", _plano("moneda")),
    Campo("tipo_cambio", "Tipo de cambio", "Importes", _tipo_cambio, tipo="tipo_cambio"),
    # Impuestos
    Campo("iva_16", "IVA 16%", "Impuestos", _importe("iva_trasladado"),
          tipo="importe", convertible=True),
    Campo("iva_8", "IVA 8%", "Impuestos", _importe("iva_trasladado_8"),
          tipo="importe", convertible=True),
    Campo("base_iva_16", "Base IVA 16%", "Impuestos", _importe("base_iva_16"),
          tipo="importe", convertible=True),
    Campo("base_iva_8", "Base IVA 8%", "Impuestos", _importe("base_iva_8"),
          tipo="importe", convertible=True),
    Campo("base_iva_0", "Base IVA 0%", "Impuestos", _importe("base_iva_0"),
          tipo="importe", convertible=True),
    Campo("base_exento", "Base exenta", "Impuestos", _importe("base_exento"),
          tipo="importe", convertible=True),
    Campo("ieps", "IEPS", "Impuestos", _importe("ieps_trasladado"),
          tipo="importe", convertible=True),
    Campo("iva_retenido", "IVA Ret.", "Impuestos", _importe("iva_retenido"),
          tipo="importe", convertible=True),
    Campo("isr_retenido", "ISR Ret.", "Impuestos", _importe("isr_retenido"),
          tipo="importe", convertible=True),
    Campo("imp_locales_trasladados", "Imp. locales trasladados", "Impuestos",
          lambda f: _imp_locales(f, "TotaldeTraslados"), tipo="importe", convertible=True),
    Campo("imp_locales_retenidos", "Imp. locales retenidos", "Impuestos",
          lambda f: _imp_locales(f, "TotaldeRetenciones"), tipo="importe", convertible=True),
    # Forma y método de pago
    Campo("forma_pago", "Forma Pago", "Forma y método de pago",
          lambda f: _clave(f.cfdi.get("forma_pago"), FORMAS_PAGO)),
    Campo("metodo_pago", "Método Pago", "Forma y método de pago",
          lambda f: _clave(f.cfdi.get("metodo_pago"), METODOS_PAGO)),
    # Complemento de pago
    Campo("pago_fecha", "Fecha de pago", "Complemento de pago", _pago_fecha, tipo="fecha",
          descripcion="Fecha del pago (si el REP trae varios, todas)."),
    Campo("pago_monto", "Monto de pago", "Complemento de pago", _pago_monto,
          tipo="importe", convertible=True,
          descripcion="Suma de los pagos del REP."),
    Campo("pago_forma", "Forma de pago (REP)", "Complemento de pago",
          lambda f: _unir(_unicos(_clave(p.get("FormaDePagoP"), FORMAS_PAGO) for p in _pagos(f)))),
    Campo("pago_moneda", "Moneda del pago", "Complemento de pago",
          lambda f: _unir(_unicos(p.get("MonedaP") for p in _pagos(f)))),
    Campo("docs_relacionados", "Docs Relacionados", "Complemento de pago", _docs_relacionados,
          descripcion="UUID de las facturas que paga el REP."),
    # Conceptos (resumen en un renglón por CFDI)
    Campo("conceptos", "Conceptos", "Conceptos", _conceptos,
          descripcion="Descripciones de todos los conceptos. Con «Una fila por concepto» "
                      "aquí va el detalle de cada concepto."),
    Campo("num_conceptos", "Núm. conceptos", "Conceptos",
          lambda f: len(f.conceptos()), tipo="numero"),
    Campo("claves_prod_serv", "Claves SAT", "Conceptos",
          lambda f: _unir(_unicos(c.get("ClaveProdServ") for c in f.conceptos()))),
    # Validación
    Campo("estado_sat", "Estatus SAT", "Validación",
          lambda f: f.cfdi.get("estado_sat") or "Por verificar"),
    Campo("validacion_local", "Validación Local", "Validación", _validacion_local),
    Campo("lista_emisor", "Listas SAT emisor", "Validación",
          lambda f: _LISTAS.get(f.cfdi.get("emisor_en_lista_negra") or "", "Sin validar")),
    Campo("lista_receptor", "Listas SAT receptor", "Validación",
          lambda f: _LISTAS.get(f.cfdi.get("receptor_en_lista_negra") or "", "Sin validar")),
    # Clasificación
    Campo("deducible", "Deducible", "Clasificación",
          lambda f: f.cfdi.get("deducible") or "Sin analizar"),
    Campo("estado_diot", "DIOT", "Clasificación", _estado_diot),
    # Detalle por concepto (solo con «Una fila por concepto»)
    Campo("concepto_num", "Concepto #", "Detalle del concepto",
          lambda f: f"{f.concepto_n} de {f.conceptos_total}" if f.concepto_n else "",
          nivel="concepto", descripcion="«1 de 3»: filtra «1 de» para sumar importes del CFDI."),
    Campo("no_identificacion", "No. Identificación", "Detalle del concepto",
          _c("NoIdentificacion"), nivel="concepto",
          descripcion="Clave del producto del emisor (SKU)."),
    Campo("clave_prod_serv", "Clave SAT", "Detalle del concepto", _c("ClaveProdServ"),
          nivel="concepto"),
    Campo("descripcion", "Descripción", "Detalle del concepto", _c("Descripcion"),
          nivel="concepto"),
    Campo("cantidad", "Cantidad", "Detalle del concepto",
          lambda f: _num(f.concepto.get("Cantidad")), tipo="numero", nivel="concepto"),
    Campo("clave_unidad", "Clave Unidad", "Detalle del concepto", _c("ClaveUnidad"),
          nivel="concepto"),
    Campo("unidad", "Unidad", "Detalle del concepto", _c("Unidad"), nivel="concepto"),
    Campo("valor_unitario", "Valor Unitario", "Detalle del concepto", _c_mxn("ValorUnitario"),
          tipo="importe", nivel="concepto", convertible=True),
    Campo("importe_concepto", "Importe concepto", "Detalle del concepto", _c_mxn("Importe"),
          tipo="importe", nivel="concepto", convertible=True),
    Campo("descuento_concepto", "Descuento concepto", "Detalle del concepto",
          lambda f: (f.mxn(f.concepto.get("Descuento")) or 0.0) if f.concepto else None,
          tipo="importe", nivel="concepto", convertible=True),
    Campo("objeto_imp", "Objeto Imp.", "Detalle del concepto",
          lambda f: _clave(f.concepto.get("ObjetoImp"), OBJETOS_IMPUESTO), nivel="concepto"),
    Campo("base_iva_concepto", "Base IVA", "Detalle del concepto", _c_impuesto("002", "Base"),
          tipo="importe", nivel="concepto", convertible=True),
    Campo("tasa_iva", "Tasa IVA", "Detalle del concepto",
          lambda f: _tasa(_impuestos(f.concepto, "002")), nivel="concepto"),
    Campo("iva_concepto", "IVA concepto", "Detalle del concepto", _c_impuesto("002", "Importe"),
          tipo="importe", nivel="concepto", convertible=True),
    Campo("tasa_ieps", "Tasa IEPS", "Detalle del concepto",
          lambda f: _tasa(_impuestos(f.concepto, "003")), nivel="concepto"),
    Campo("ieps_concepto", "IEPS concepto", "Detalle del concepto",
          _c_impuesto("003", "Importe"), tipo="importe", nivel="concepto", convertible=True),
    Campo("iva_ret_concepto", "IVA Ret. concepto", "Detalle del concepto",
          _c_impuesto("002", "Importe", retenciones=True),
          tipo="importe", nivel="concepto", convertible=True),
    Campo("isr_ret_concepto", "ISR Ret. concepto", "Detalle del concepto",
          _c_impuesto("001", "Importe", retenciones=True),
          tipo="importe", nivel="concepto", convertible=True),
    Campo("pedimento", "Pedimento", "Detalle del concepto",
          lambda f: _unir(_de(f.concepto, "InformacionAduanera.NumeroPedimento")),
          nivel="concepto"),
    Campo("cuenta_predial", "Cuenta predial", "Detalle del concepto",
          lambda f: _unir(_de(f.concepto, "CuentaPredial.Numero")), nivel="concepto"),
]

CAMPOS: dict[str, Campo] = {c.id: c for c in _CATALOGO}
GRUPOS: list[str] = list(dict.fromkeys(c.grupo for c in _CATALOGO))


def campo(campo_id: str) -> Optional[Campo]:
    """El campo del catálogo, o uno de ruta (`ruta:…` / `ruta_concepto:…`)."""
    if campo_id in CAMPOS:
        return CAMPOS[campo_id]
    for prefijo, nivel in ((PREFIJO_RUTA, "cfdi"), (PREFIJO_RUTA_CONCEPTO, "concepto")):
        if not campo_id.startswith(prefijo):
            continue
        ruta = campo_id[len(prefijo):]
        if len(ruta) > MAX_RUTA or not _RUTA_RE.match(ruta):
            return None
        if nivel == "cfdi":
            def leer(f: Fila, r: str = ruta) -> str:
                return _unir(valores(f.nodos or {}, r))
        else:
            def leer(f: Fila, r: str = ruta) -> str:
                return _unir(_de(f.concepto, r))
        return Campo(campo_id, ruta.rsplit(".", 1)[-1], "Ruta", leer, nivel=nivel)
    return None


def catalogo() -> dict:
    return {"grupos": GRUPOS, "campos": [c.a_dict() for c in _CATALOGO]}


# ---------------------------------------------------------------------------
# Plantillas
# ---------------------------------------------------------------------------


@dataclass
class Plantilla:
    id: str
    nombre: str
    columnas: list[dict]
    detalle_concepto: list[dict]
    sistema: bool = False
    descripcion: str = ""

    def a_dict(self) -> dict:
        return {
            "id": self.id,
            "nombre": self.nombre,
            "descripcion": self.descripcion,
            "sistema": self.sistema,
            "columnas": [dict(c) for c in self.columnas],
            "detalle_concepto": [dict(c) for c in self.detalle_concepto],
        }


def _cols(*pares: tuple[str, str]) -> list[dict]:
    return [{"campo": c, "encabezado": e} for c, e in pares]


DETALLE_PREDETERMINADO = _cols(
    ("concepto_num", "Concepto #"),
    ("no_identificacion", "No. Identificación"),
    ("clave_prod_serv", "Clave SAT"),
    ("descripcion", "Descripción"),
    ("cantidad", "Cantidad"),
    ("clave_unidad", "Clave Unidad"),
    ("unidad", "Unidad"),
    ("valor_unitario", "Valor Unitario"),
    ("importe_concepto", "Importe concepto"),
    ("descuento_concepto", "Descuento concepto"),
    ("objeto_imp", "Objeto Imp."),
    ("base_iva_concepto", "Base IVA"),
    ("tasa_iva", "Tasa IVA"),
    ("iva_concepto", "IVA concepto"),
    ("ieps_concepto", "IEPS concepto"),
    ("iva_ret_concepto", "IVA Ret. concepto"),
    ("isr_ret_concepto", "ISR Ret. concepto"),
)

ID_PREDETERMINADA = "clasico"

# El formato que exportaba la app web vieja (todoconta-apps, csv-generator.ts:
# un renglón por CFDI con los pagos), que es el que piden los contadores.
CLASICO = Plantilla(
    id="clasico",
    nombre="Formato clásico",
    descripcion="Un renglón por CFDI con conceptos y complemento de pago en la misma hoja.",
    sistema=True,
    columnas=_cols(
        ("fecha_emision", "Fecha Emisión"),
        ("estado_sat", "Estatus SAT"),
        ("serie", "Serie"),
        ("folio", "Folio"),
        ("emisor_nombre", "Nombre Emisor"),
        ("emisor_rfc", "RFC Emisor"),
        ("receptor_nombre", "Nombre Receptor"),
        ("receptor_rfc", "RFC Receptor"),
        ("subtotal", "SubTotal"),
        ("descuento", "Descuento"),
        ("iva_16", "IVA 16%"),
        ("iva_retenido", "IVA Ret."),
        ("isr_retenido", "ISR Ret."),
        ("total", "Total"),
        ("forma_pago", "Forma Pago"),
        ("metodo_pago", "Método Pago"),
        ("moneda", "Moneda"),
        ("tipo_cambio", "Tipo de cambio"),
        ("tipo_comprobante", "Tipo Comprobante"),
        ("uuid", "UUID"),
        ("validacion_local", "Validación Local"),
        ("conceptos", "Conceptos"),
        ("pago_fecha", "Fecha de pago"),
        ("pago_monto", "Monto de pago"),
        ("docs_relacionados", "Docs Relacionados"),
    ),
    detalle_concepto=DETALLE_PREDETERMINADO,
)

# Las columnas del export anterior del escritorio (exportar.py), ahora en una
# hoja; "IVA Trasladado" era solo el 16% y el 8% no salía.
COMPLETO = Plantilla(
    id="completo",
    nombre="Completo",
    descripcion="Las columnas del export anterior, con IVA al 8%, uso de CFDI, deducible y DIOT.",
    sistema=True,
    columnas=_cols(
        ("uuid", "UUID"),
        ("tipo_comprobante", "Tipo"),
        ("fecha_emision", "Fecha"),
        ("serie", "Serie"),
        ("folio", "Folio"),
        ("emisor_rfc", "RFC Emisor"),
        ("emisor_nombre", "Nombre Emisor"),
        ("receptor_rfc", "RFC Receptor"),
        ("receptor_nombre", "Nombre Receptor"),
        ("subtotal", "Subtotal"),
        ("descuento", "Descuento"),
        ("iva_16", "IVA 16%"),
        ("iva_8", "IVA 8%"),
        ("ieps", "IEPS Trasladado"),
        ("iva_retenido", "IVA Retenido"),
        ("isr_retenido", "ISR Retenido"),
        ("total", "Total"),
        ("moneda", "Moneda"),
        ("tipo_cambio", "Tipo de Cambio"),
        ("forma_pago", "Forma de Pago"),
        ("metodo_pago", "Método de Pago"),
        ("uso_cfdi", "Uso CFDI"),
        ("lugar_expedicion", "Lugar Expedición"),
        ("estado_sat", "Estado SAT"),
        ("deducible", "Deducible"),
        ("estado_diot", "DIOT"),
    ),
    detalle_concepto=DETALLE_PREDETERMINADO,
)

SISTEMA: dict[str, Plantilla] = {p.id: p for p in (CLASICO, COMPLETO)}


def normalizar_columnas(columnas: Any, nivel: str) -> list[dict]:
    """Valida una lista de columnas `{campo, encabezado}` del `nivel` dado.
    Encabezado vacío = la etiqueta del campo. ValueError con el motivo."""
    if not isinstance(columnas, list):
        raise ValueError("Las columnas deben ser una lista.")
    if len(columnas) > MAX_COLUMNAS:
        raise ValueError(f"Una plantilla admite hasta {MAX_COLUMNAS} columnas.")
    salida = []
    for col in columnas:
        if not isinstance(col, dict):
            raise ValueError("Cada columna debe tener «campo» y «encabezado».")
        campo_id = str(col.get("campo") or "").strip()
        c = campo(campo_id)
        if c is None:
            raise ValueError(f"Campo desconocido: {campo_id!r}.")
        if c.nivel != nivel:
            donde = "el detalle por concepto" if nivel == "concepto" else "las columnas del CFDI"
            raise ValueError(f"El campo «{c.etiqueta}» no va en {donde}.")
        encabezado = str(col.get("encabezado") or "").strip() or c.etiqueta
        if len(encabezado) > MAX_ENCABEZADO:
            raise ValueError(f"Encabezado demasiado largo: {encabezado[:30]!r}…")
        salida.append({"campo": campo_id, "encabezado": encabezado})
    return salida


def normalizar_nombre(nombre: Any) -> str:
    limpio = str(nombre or "").strip()
    if not limpio:
        raise ValueError("La plantilla necesita un nombre.")
    if len(limpio) > MAX_NOMBRE:
        raise ValueError(f"El nombre admite hasta {MAX_NOMBRE} caracteres.")
    return limpio


# ---------------------------------------------------------------------------
# Motor: columnas finales y renglones
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Columna:
    campo: Campo
    encabezado: str


def columnas_de(plantilla: Plantilla, *, por_concepto: bool = False,
                convertir_mxn: bool = False) -> list[Columna]:
    """Columnas del archivo. Con `por_concepto`, el bloque de detalle ocupa el
    lugar de la columna «Conceptos» (o va al final si no está)."""

    def _resolver(lista: list[dict]) -> list[Columna]:
        salida = []
        for col in lista:
            c = campo(col.get("campo", ""))
            if c is None:  # campo retirado del catálogo: se omite
                continue
            encabezado = col.get("encabezado") or c.etiqueta
            if convertir_mxn and c.convertible:
                encabezado += " MXN"
            salida.append(Columna(c, encabezado))
        return salida

    principales = _resolver(plantilla.columnas)
    detalle = _resolver(plantilla.detalle_concepto) if por_concepto else []
    if not detalle:
        return principales
    i = next((n for n, col in enumerate(principales) if col.campo.id == "conceptos"), None)
    if i is None:
        return principales + detalle
    return principales[:i] + detalle + principales[i + 1:]


def renglones(
    db: ProcesadorDB,
    filtros: Optional[CfdiFiltros],
    columnas: list[Columna],
    *,
    por_concepto: bool = False,
    convertir_mxn: bool = False,
    ascendente: bool = True,
    limite: Optional[int] = None,
) -> Iterator[list[Any]]:
    """Valores de cada renglón (uno por CFDI, o uno por concepto)."""
    fallidos: set[str] = set()

    def _valores(fila: Fila) -> list[Any]:
        salida = []
        for col in columnas:
            try:
                salida.append(col.campo.leer(fila))
            except Exception:  # noqa: BLE001 — un campo roto no tumba el archivo
                if col.campo.id not in fallidos:
                    fallidos.add(col.campo.id)
                    logger.exception("[plantillas] falló el campo %s", col.campo.id)
                salida.append(None)
        return salida

    n = 0
    for cfdi in db.iter_all(filtros, ascendente=ascendente):
        fila = Fila(cfdi, db, convertir_mxn)
        if por_concepto:
            conceptos = fila.conceptos()
            fila.conceptos_total = len(conceptos)
            for i, concepto in enumerate(conceptos or [{}], 1):
                fila.concepto = concepto
                fila.concepto_n = i if concepto else 0
                yield _valores(fila)
                n += 1
                if limite is not None and n >= limite:
                    return
        else:
            yield _valores(fila)
            n += 1
            if limite is not None and n >= limite:
                return


def contar_renglones(db: ProcesadorDB, filtros: Optional[CfdiFiltros],
                     por_concepto: bool = False) -> int:
    """Cuántos renglones tendría el archivo (por concepto: los de la tabla
    `conceptos`, un CFDI sin conceptos cuenta uno). Sirve para rechazar un
    Excel que pase de `MAX_FILAS_EXCEL` antes de generarlo."""
    where, params = _construir_where(filtros)
    if not por_concepto:
        sql = f"SELECT COUNT(*) FROM cfdis {where}"
    else:
        sql = (
            "SELECT COALESCE(SUM(MAX(n, 1)), 0) FROM ("
            "SELECT (SELECT COUNT(*) FROM conceptos c WHERE c.cfdi_uuid = cfdis.uuid "
            f"AND c.mi_rfc = cfdis.mi_rfc) AS n FROM cfdis {where})"
        )
    with db.cursor() as cur:
        return int(cur.execute(sql, params).fetchone()[0])


# ---------------------------------------------------------------------------
# Texto (CSV y vista previa)
# ---------------------------------------------------------------------------

# Excel interpreta como fórmula una celda de CSV que empieza con estos
# caracteres; los textos vienen del XML (los escribe el emisor).
_INICIO_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def texto(valor: Any, tipo: str) -> str:
    """Valor como texto para CSV y vista previa."""
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        if tipo == "importe":
            return f"{valor:.2f}"
        if tipo == "tipo_cambio":
            return f"{valor:.4f}"
        return f"{valor:.6f}".rstrip("0").rstrip(".")
    s = str(valor)
    return "'" + s if s.startswith(_INICIO_FORMULA) else s
