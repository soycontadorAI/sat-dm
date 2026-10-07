"""
Generador determinista de CFDI 4.0 para el modo de grabación.

`comprobantes(rfc, anio, mes)` arma el universo de comprobantes de una empresa
de demo en un mes (emitidos y recibidos): misma entrada → mismos UUID, montos y
fechas, en cualquier equipo. De ahí salen los paquetes del Web Service, la
Descarga rápida, la metadata, el estatus de "Validar contra SAT" y la siembra.

Septiembre de 2026 de Distribuidora El Roble sigue el plan exacto de los
guiones (docs/negocio/guiones-ventana-2026-11.md):
  - 1,163 recibidos de 87 emisores;
  - 58 facturas PPD: 30 pagadas completas, 12 parciales, 16 sin complemento;
  - complementos con 2 extemporáneos (pagos de julio), 1 huérfano y 1 que
    paga una factura PUE;
  - 3 facturas que se cancelan después de descargarlas (las ve "Validar
    contra SAT", no el Web Service, que solo entrega vigentes);
  - emisores en listas negras: Suministros Álamo Gris (69-B definitivo) y
    dos en la lista 69.

Los XML llevan la estructura completa (Emisor, Receptor, Conceptos con
impuestos, Impuestos, Complemento con TimbreFiscalDigital, Pagos 2.0 y Nómina
1.2), con sellos y certificados de relleno: no pasan una validación de sello,
pero sí el parser y los procesadores de la app.
"""

from __future__ import annotations

import calendar
import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Optional
from xml.sax.saxutils import escape, quoteattr

from . import catalogo
from .catalogo import Contraparte, GIROS, PERFILES
from .escenario import EL_ROBLE, EMPRESAS

ANIO_MIN = 2022  # antes de esto no hay comprobantes de demo

RFC_PUBLICO = "XAXX010101000"

_GIROS_MERCANCIA = {"abarrotes", "harinas", "lacteos", "limpieza", "desechables",
                    "empaque", "agua", "cemento", "acero", "block", "concreto"}


def _ahora() -> datetime:
    """Corte de "lo que ya existe" (las pruebas lo fijan)."""
    return datetime.now()


def _semilla(*partes) -> int:
    texto = "|".join(str(p) for p in partes)
    return int(hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16], 16)


def _uuid(*partes) -> str:
    h = hashlib.sha256(("uuid|" + "|".join(str(p) for p in partes)).encode()).hexdigest()
    # Formato de UUID v4 (como los del SAT), en mayúsculas.
    h = h[:12] + "4" + h[13:16] + "89ab"[int(h[16], 16) % 4] + h[17:32]
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}".upper()


def _r2(x: float) -> float:
    return round(x + 1e-9, 2)


def _fmt(x: float) -> str:
    return f"{_r2(x):.2f}"


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------

@dataclass
class Concepto:
    clave: str
    descripcion: str
    clave_unidad: str
    unidad: str
    cantidad: float
    valor_unitario: float
    importe: float
    tasa: str               # "16" | "0" | "exento" | "" (no objeto)
    iva: float = 0.0
    ret_iva: float = 0.0
    ret_isr: float = 0.0
    tasa_ret_iva: str = ""
    tasa_ret_isr: str = ""


@dataclass
class Docto:
    uuid: str
    serie: str
    folio: str
    parcialidad: int
    saldo_ant: float
    pagado: float
    tasa: str               # tasa de IVA de la factura pagada


@dataclass
class Pago:
    fecha_pago: datetime
    forma: str
    doctos: list

    @property
    def monto(self) -> float:
        return _r2(sum(d.pagado for d in self.doctos))


@dataclass
class ReciboNomina:
    empleado: object        # catalogo.Empleado
    patron: dict
    fecha_pago: date
    inicio: date
    fin: date
    dias: float
    percepciones: list      # (tipo, clave, concepto, gravado, exento)
    deducciones: list       # (tipo, clave, concepto, importe)
    sbc: float

    @property
    def total_percepciones(self) -> float:
        return _r2(sum(g + e for _, _, _, g, e in self.percepciones))

    @property
    def total_deducciones(self) -> float:
        return _r2(sum(i for *_, i in self.deducciones))


@dataclass
class Comprobante:
    uuid: str
    tipo: str               # I | E | P | N
    fecha: datetime
    emisor_rfc: str
    emisor_nombre: str
    emisor_regimen: str
    receptor_rfc: str
    receptor_nombre: str
    receptor_regimen: str
    receptor_cp: str
    uso_cfdi: str
    lugar: str
    serie: str
    folio: str
    direccion: str          # E (emitido) | R (recibido), respecto de la empresa dueña
    metodo_pago: str = ""
    forma_pago: str = ""
    conceptos: list = field(default_factory=list)
    relacionados: list = field(default_factory=list)  # UUID (notas de crédito)
    pago: Optional[Pago] = None
    nomina: Optional[ReciboNomina] = None
    global_semana: Optional[tuple] = None  # (periodicidad, mes, año) factura global
    pac: str = ""

    # Totales -------------------------------------------------------------
    @property
    def subtotal(self) -> float:
        if self.tipo == "P":
            return 0.0
        if self.tipo == "N":
            return self.nomina.total_percepciones
        return _r2(sum(c.importe for c in self.conceptos))

    @property
    def descuento(self) -> float:
        return self.nomina.total_deducciones if self.tipo == "N" else 0.0

    @property
    def iva(self) -> float:
        return _r2(sum(c.iva for c in self.conceptos)) if self.tipo in ("I", "E") else 0.0

    @property
    def ret_iva(self) -> float:
        return _r2(sum(c.ret_iva for c in self.conceptos)) if self.tipo in ("I", "E") else 0.0

    @property
    def ret_isr(self) -> float:
        return _r2(sum(c.ret_isr for c in self.conceptos)) if self.tipo in ("I", "E") else 0.0

    @property
    def total(self) -> float:
        if self.tipo == "P":
            return 0.0
        if self.tipo == "N":
            return _r2(self.subtotal - self.descuento)
        return _r2(self.subtotal + self.iva - self.ret_iva - self.ret_isr)

    @property
    def monto_metadata(self) -> float:
        return self.pago.monto if self.tipo == "P" and self.pago else self.total


@dataclass(frozen=True)
class Mes:
    """Universo de un mes de una empresa + los hechos de escenario."""
    comprobantes: tuple
    cancelados_despues: frozenset  # UUID vigentes al descargar, cancelados al validar


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def comprobantes(rfc: str, anio: int, mes: int) -> list:
    """Comprobantes de la empresa en el mes que ya "existen" (fecha ≤ ahora)."""
    corte = _ahora()
    return [c for c in _mes(rfc.upper(), anio, mes).comprobantes if c.fecha <= corte]


def cancelados_despues(rfc: str, anio: int, mes: int) -> frozenset:
    return _mes(rfc.upper(), anio, mes).cancelados_despues


def en_rango(rfc: str, desde: date, hasta: date, tipo: Optional[str] = None,
             rfc_contraparte: Optional[str] = None) -> list:
    """Comprobantes de la empresa entre dos fechas (inclusive), filtrados por
    dirección (E/R) y, opcionalmente, por RFC de la contraparte."""
    if hasta < desde:
        return []
    out = []
    anio, mes = desde.year, desde.month
    while (anio, mes) <= (hasta.year, hasta.month):
        for c in comprobantes(rfc, anio, mes):
            if not (desde <= c.fecha.date() <= hasta):
                continue
            if tipo in ("E", "R") and c.direccion != tipo:
                continue
            if rfc_contraparte:
                otro = c.receptor_rfc if c.direccion == "E" else c.emisor_rfc
                if otro != rfc_contraparte.strip().upper():
                    continue
            out.append(c)
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
    out.sort(key=lambda c: (c.fecha, c.uuid))
    return out


def buscar(uuid: str, rfc: str, desde: date, hasta: date) -> Optional[Comprobante]:
    uuid = uuid.strip().upper()
    for c in en_rango(rfc, desde, hasta):
        if c.uuid == uuid:
            return c
    return None


def estatus(uuid: str, emisor_rfc: str, receptor_rfc: str) -> str:
    """Estatus que "contesta el SAT" en modo de grabación: Cancelado para los
    marcados en el escenario, Vigente para el resto."""
    uuid = (uuid or "").strip().upper()
    for rfc in {emisor_rfc.strip().upper(), receptor_rfc.strip().upper()}:
        if rfc not in EMPRESAS:
            continue
        # Los marcados viven en meses concretos; basta con revisar los
        # universos ya generados más los meses del escenario.
        for (r, anio, mes) in _MESES_CON_CANCELADOS:
            if r == rfc and uuid in cancelados_despues(rfc, anio, mes):
                return "Cancelado"
    return "Vigente"


_MESES_CON_CANCELADOS = ((EL_ROBLE, 2026, 9),)


# ---------------------------------------------------------------------------
# Generación del mes
# ---------------------------------------------------------------------------

@lru_cache(maxsize=96)
def _mes(rfc: str, anio: int, mes: int) -> Mes:
    emp = EMPRESAS.get(rfc)
    perfil = PERFILES.get(rfc)
    if emp is None or perfil is None or anio < ANIO_MIN or anio > 2100:
        return Mes((), frozenset())
    gen = _Generador(emp, perfil, anio, mes)
    if (rfc, anio, mes) == (EL_ROBLE, 2026, 9):
        recibidos, cancelados = gen.recibidos_septiembre_el_roble()
    else:
        recibidos, cancelados = gen.recibidos(), frozenset()
    emitidos = gen.emitidos()
    todos = sorted([*recibidos, *emitidos], key=lambda c: (c.fecha, c.uuid))
    return Mes(tuple(todos), frozenset(cancelados))


class _Generador:
    def __init__(self, emp, perfil, anio: int, mes: int):
        self.emp = emp
        self.perfil = perfil
        self.anio = anio
        self.mes = mes
        self.dias = calendar.monthrange(anio, mes)[1]
        self.fin_mes = datetime(anio, mes, self.dias, 23, 59, 59)
        self._folios: dict = {}

    # ---- utilidades ------------------------------------------------------
    def _rng(self, *partes) -> random.Random:
        return random.Random(_semilla(self.emp.rfc, self.anio, self.mes, *partes))

    def _fecha(self, rng, dia_min=1, dia_max=None, hora=(7, 20)) -> datetime:
        dia_max = min(dia_max or self.dias, self.dias)
        dia = rng.randint(max(1, dia_min), max(1, dia_max))
        return datetime(self.anio, self.mes, dia, rng.randint(*hora),
                        rng.randint(0, 59), rng.randint(0, 59))

    def _folio(self, emisor: Contraparte | str) -> tuple:
        nombre = emisor if isinstance(emisor, str) else emisor.nombre
        clave = nombre
        if clave not in self._folios:
            base = 1000 + _semilla("folio", nombre) % 40000
            base += ((self.anio - ANIO_MIN) * 12 + self.mes) * 160
            self._folios[clave] = base
        self._folios[clave] += 1
        serie = "".join(p[0] for p in nombre.split()[:2] if p.isalpha())[:2] or "A"
        return serie, str(self._folios[clave])

    def _uuid(self, *partes) -> str:
        return _uuid(self.emp.rfc, self.anio, self.mes, *partes)

    @staticmethod
    def _pac(uuid: str) -> str:
        return catalogo.PACS[int(uuid[:2], 16) % len(catalogo.PACS)]

    @staticmethod
    def _cp(nombre: str) -> str:
        return catalogo.CPS[_semilla("cp", nombre) % len(catalogo.CPS)]

    def _conceptos(self, rng, giro: str, receptor_persona: str, retencion: Optional[str],
                   dia: int, factor: float = 1.0) -> list:
        opciones = GIROS[giro]
        n = 1 if opciones[0][4][0] == opciones[0][4][1] or len(opciones) == 1 \
            else rng.randint(1, min(4, len(opciones)))
        elegidos = rng.sample(opciones, n)
        out = []
        for clave, desc, cu, unidad, (pmin, pmax), tasa, (cmin, cmax) in elegidos:
            if isinstance(cmin, int) and isinstance(cmax, int):
                cantidad = float(rng.randint(cmin, cmax))
            else:
                cantidad = round(rng.uniform(cmin, cmax), 3)
            if cu == "LTR":
                cantidad = round(rng.uniform(cmin, cmax), 3)
            if factor != 1.0 and cmax > cmin:
                # Pedido grande (compras a crédito): más piezas, mismo precio.
                cantidad = float(max(1, round(cantidad * factor)))
            pu = pmin if pmin == pmax else round(rng.uniform(pmin, pmax), 2)
            importe = _r2(cantidad * pu)
            if pmin == pmax and cmin == cmax == 1:
                desc = f"{desc}, {_MESES[self.mes - 1]} {self.anio}"
            c = Concepto(clave, desc, cu, unidad, cantidad, pu, importe, tasa)
            if tasa == "16":
                c.iva = _r2(importe * 0.16)
            # Retenciones: solo cuando quien recibe es persona moral.
            if receptor_persona == "PM" and retencion:
                if retencion == "flete":
                    c.ret_iva, c.tasa_ret_iva = _r2(importe * 0.04), "0.040000"
                elif retencion in ("arrendamiento", "honorarios"):
                    c.ret_isr, c.tasa_ret_isr = _r2(importe * 0.10), "0.100000"
                    if tasa == "16":
                        c.ret_iva, c.tasa_ret_iva = _r2(importe * 0.106667), "0.106667"
                elif retencion == "resico":
                    c.ret_isr, c.tasa_ret_isr = _r2(importe * 0.0125), "0.012500"
            out.append(c)
        return out

    def _uso(self, giro: str, lado_empresa_receptor: bool) -> str:
        if giro == "computo":
            return "I04"
        if giro == "medico":
            return "D01"
        if giro == "colegiatura":
            return "D10"
        if giro in _GIROS_MERCANCIA:
            return "G01"
        if giro.startswith("venta_"):
            return "G01" if giro in ("venta_abarrotes", "venta_pan") else "G03"
        return "G03"

    @staticmethod
    def _forma_pue(rng, giro: str, total: float) -> str:
        if giro in ("combustible", "restaurante", "hotel"):
            return rng.choice(("04", "28", "28", "01" if total < 2000 else "28"))
        if total < 1500 and giro in ("papeleria", "ferreteria", "mensajeria"):
            return rng.choice(("01", "28"))
        return "03"

    # ---- piezas ---------------------------------------------------------
    def _factura_recibida(self, p: Contraparte, fecha: datetime, metodo: str, clave: str,
                          factor: float = 1.0) -> Comprobante:
        rng = self._rng("fr", clave)
        uuid = self._uuid("R", clave)
        serie, folio = self._folio(p)
        conceptos = self._conceptos(rng, p.giro, self.emp.tipo, p.retencion, fecha.day, factor)
        c = Comprobante(
            uuid=uuid, tipo="I", fecha=fecha,
            emisor_rfc=p.rfc, emisor_nombre=p.nombre, emisor_regimen=p.regimen,
            receptor_rfc=self.emp.rfc, receptor_nombre=self.emp.nombre_sat,
            receptor_regimen=self.emp.regimen, receptor_cp=self.emp.cp,
            uso_cfdi=self._uso(p.giro, True), lugar=self._cp(p.nombre),
            serie=serie, folio=folio, direccion="R", metodo_pago=metodo,
            conceptos=conceptos, pac=self._pac(uuid),
        )
        c.forma_pago = "99" if metodo == "PPD" else self._forma_pue(rng, p.giro, c.total)
        return c

    def _factura_emitida(self, cli: Contraparte, fecha: datetime, metodo: str, clave: str) -> Comprobante:
        rng = self._rng("fe", clave)
        uuid = self._uuid("E", clave)
        serie, folio = self._folio(self.emp.nombre_sat)
        retencion = None
        if cli.persona == "PM" and self.emp.tipo == "PF" and self.emp.regimen == "612":
            retencion = "honorarios"
        if cli.persona == "PM" and cli.giro == "venta_flete":
            retencion = "flete"
        conceptos = self._conceptos(rng, cli.giro, cli.persona, retencion, fecha.day)
        c = Comprobante(
            uuid=uuid, tipo="I", fecha=fecha,
            emisor_rfc=self.emp.rfc, emisor_nombre=self.emp.nombre_sat,
            emisor_regimen=self.emp.regimen if self.emp.regimen != "605" else "606",
            receptor_rfc=cli.rfc, receptor_nombre=cli.nombre,
            receptor_regimen=cli.regimen, receptor_cp=self._cp(cli.nombre),
            uso_cfdi=self._uso(cli.giro, False), lugar=self.emp.cp,
            serie=serie, folio=folio, direccion="E", metodo_pago=metodo,
            conceptos=conceptos, pac=self._pac(uuid),
        )
        c.forma_pago = "99" if metodo == "PPD" else "03"
        return c

    def _complemento(self, emisor_rfc, emisor_nombre, emisor_regimen, receptor_rfc,
                     receptor_nombre, receptor_regimen, receptor_cp, lugar, fecha: datetime,
                     pago: Pago, clave: str, direccion: str, serie_de: str) -> Comprobante:
        uuid = self._uuid("P", clave)
        serie, folio = self._folio(serie_de + " CP")
        return Comprobante(
            uuid=uuid, tipo="P", fecha=fecha,
            emisor_rfc=emisor_rfc, emisor_nombre=emisor_nombre, emisor_regimen=emisor_regimen,
            receptor_rfc=receptor_rfc, receptor_nombre=receptor_nombre,
            receptor_regimen=receptor_regimen, receptor_cp=receptor_cp,
            uso_cfdi="CP01", lugar=lugar, serie="CP", folio=folio,
            direccion=direccion, pago=pago, pac=self._pac(uuid),
        )

    def _complemento_recibido(self, p: Contraparte, fecha: datetime, pago: Pago, clave: str):
        return self._complemento(
            p.rfc, p.nombre, p.regimen, self.emp.rfc, self.emp.nombre_sat,
            self.emp.regimen, self.emp.cp, self._cp(p.nombre), fecha, pago, clave, "R", p.nombre,
        )

    def _nota_credito_recibida(self, p: Contraparte, factura: Comprobante, fecha: datetime,
                               clave: str) -> Comprobante:
        rng = self._rng("nc", clave)
        uuid = self._uuid("NC", clave)
        serie, folio = self._folio(p.nombre + " NC")
        base = factura.subtotal * rng.uniform(0.02, 0.08)
        tasa = factura.conceptos[0].tasa
        c = Concepto("84111506", "Bonificación por pronto pago" if rng.random() < 0.5
                     else "Devolución de mercancía", "ACT", "Actividad", 1.0, _r2(base),
                     _r2(base), tasa)
        if tasa == "16":
            c.iva = _r2(c.importe * 0.16)
        return Comprobante(
            uuid=uuid, tipo="E", fecha=fecha,
            emisor_rfc=p.rfc, emisor_nombre=p.nombre, emisor_regimen=p.regimen,
            receptor_rfc=self.emp.rfc, receptor_nombre=self.emp.nombre_sat,
            receptor_regimen=self.emp.regimen, receptor_cp=self.emp.cp,
            uso_cfdi="G02", lugar=self._cp(p.nombre), serie="NC", folio=folio,
            direccion="R", metodo_pago="PUE", forma_pago="17", conceptos=[c],
            relacionados=[factura.uuid], pac=self._pac(uuid),
        )

    # ---- recibidos genéricos -------------------------------------------
    def _volumen(self, base: int, clave: str) -> int:
        rng = self._rng("vol", clave)
        estacional = {1: 0.92, 2: 0.94, 12: 1.08}.get(self.mes, 1.0)
        return max(1, int(round(base * estacional * rng.uniform(0.95, 1.05))))

    def recibidos(self) -> list:
        perfil = self.perfil
        rng = self._rng("recibidos")
        mensuales = [p for p in perfil.proveedores if p.mensual]
        variables = [p for p in perfil.proveedores if not p.mensual]
        out: list = []
        for p in mensuales:
            fecha = datetime(self.anio, self.mes, min(p.mensual, self.dias),
                             rng.randint(9, 13), rng.randint(0, 59), rng.randint(0, 59))
            out.append(self._factura_recibida(p, fecha, "PUE", f"m{p.nombre}"))
        out.extend(self._nomina_recibida())
        n = max(0, self._volumen(perfil.recibidos_mes, "R") - len(mensuales))
        if variables and n:
            elegidos = rng.choices(variables, weights=[p.peso for p in variables], k=n)
            for i, p in enumerate(elegidos):
                metodo = "PPD" if p.credito and rng.random() < 0.85 else "PUE"
                fecha = self._fecha(rng, 1, 26 if metodo == "PPD" else None)
                f = self._factura_recibida(p, fecha, metodo, f"v{i}",
                                           factor=3.0 if metodo == "PPD" else 1.0)
                out.append(f)
                if metodo == "PPD":
                    out.extend(self._pagos_mismo_mes(p, f, f"v{i}"))
                elif p.credito and rng.random() < 0.06:
                    nc_fecha = min(f.fecha + timedelta(days=rng.randint(2, 8)), self.fin_mes)
                    out.append(self._nota_credito_recibida(p, f, nc_fecha, f"v{i}"))
        return out

    def _pagos_mismo_mes(self, p: Contraparte, f: Comprobante, clave: str) -> list:
        """Plan de pago genérico: el complemento solo existe si cae en el mismo
        mes (cada mes queda autocontenido: sin huérfanos accidentales)."""
        rng = self._rng("plan", clave)
        dado = rng.random()
        if dado >= 0.75:
            return []  # sin pagar todavía
        fecha_pago = f.fecha + timedelta(days=rng.randint(4, 14))
        emision = fecha_pago + timedelta(days=rng.randint(0, 2), hours=rng.randint(1, 5))
        if emision > self.fin_mes:
            return []
        pagado = f.total if dado < 0.55 else _r2(f.total * rng.uniform(0.35, 0.7))
        pago = Pago(fecha_pago.replace(hour=12, minute=0, second=0), "03",
                    [Docto(f.uuid, f.serie, f.folio, 1, f.total, pagado, f.conceptos[0].tasa)])
        return [self._complemento_recibido(p, emision, pago, clave)]

    def _nomina_recibida(self) -> list:
        """Nómina que recibe la empresa (Laura: su patrón le timbra)."""
        info = catalogo.PATRONES.get(self.emp.rfc)
        if not info or "patron" not in info:
            return []
        patron = info["patron"]
        out = []
        for emp in catalogo.EMPLEADOS.get(self.emp.rfc, ()):
            for q, recibo in enumerate(self._recibos(emp, info)):
                uuid = self._uuid("NR", emp.num, q)
                serie, folio = self._folio(patron.nombre + " NOM")
                out.append(Comprobante(
                    uuid=uuid, tipo="N", fecha=_dt(recibo.fecha_pago, 17, 10 + q, 5),
                    emisor_rfc=patron.rfc, emisor_nombre=patron.nombre, emisor_regimen="601",
                    receptor_rfc=self.emp.rfc, receptor_nombre=self.emp.nombre_sat,
                    receptor_regimen="605", receptor_cp=self.emp.cp, uso_cfdi="CN01",
                    lugar=self._cp(patron.nombre), serie="NOM", folio=folio, direccion="R",
                    metodo_pago="PUE", forma_pago="99", nomina=recibo, pac=self._pac(uuid),
                ))
        return out

    # ---- septiembre de El Roble: el plan exacto de los guiones ----------
    def recibidos_septiembre_el_roble(self):
        TOTAL, PPD, NC = 1163, 58, 18
        rng = self._rng("sep-plan")
        provs = self.perfil.proveedores
        mensuales = [p for p in provs if p.mensual]
        credito = [p for p in provs if p.credito]
        contado = [p for p in provs if not p.mensual and not p.credito]
        out: list = []

        for p in mensuales:
            fecha = datetime(2026, 9, min(p.mensual, 30), rng.randint(9, 13),
                             rng.randint(0, 59), rng.randint(0, 59))
            out.append(self._factura_recibida(p, fecha, "PUE", f"m{p.nombre}"))

        # 58 PPD repartidas entre los 15 proveedores a crédito (por peso).
        ppd_por_prov = _repartir(PPD, [p.peso for p in credito])
        ppds: list = []
        for p, n in zip(credito, ppd_por_prov):
            for j in range(n):
                fecha = self._fecha(rng, 1, 24)
                ppds.append((p, self._factura_recibida(p, fecha, "PPD", f"ppd{p.nombre}{j}",
                                                       factor=3.0)))
        ppds.sort(key=lambda x: (x[1].fecha, x[1].uuid))
        out.extend(f for _, f in ppds)

        # Una PUE de un proveedor a crédito: es la que luego "paga" un
        # complemento (la incidencia "PUE con complemento").
        cdv = credito[0]
        pue_cdv = self._factura_recibida(cdv, datetime(2026, 9, 4, 11, 20, 41), "PUE", "pue-cdv")
        out.append(pue_cdv)

        # Complementos -----------------------------------------------------
        complementos = self._complementos_septiembre(rng, ppds, pue_cdv, cdv)

        # Notas de crédito de proveedores a crédito sobre sus facturas del mes.
        notas = []
        for k in range(NC):
            p, f = ppds[(k * 7) % len(ppds)]
            fecha = min(f.fecha + timedelta(days=rng.randint(2, 6), hours=rng.randint(1, 4)),
                        datetime(2026, 9, 30, 18, 0, 0))
            notas.append(self._nota_credito_recibida(p, f, fecha, f"nc{k}"))

        # PUE de contado hasta completar 1,163 (cada proveedor al menos una).
        fijos = len(out) + len(complementos) + len(notas)
        n_pue = TOTAL - fijos
        por_prov = _repartir(n_pue, [p.peso for p in contado], minimo=1)
        pues = []
        for p, n in zip(contado, por_prov):
            for j in range(n):
                fecha = self._fecha(rng)
                pues.append(self._factura_recibida(p, fecha, "PUE", f"pue{p.nombre}{j}"))
        out.extend(pues)
        out.extend(complementos)
        out.extend(notas)

        # 3 facturas que se cancelan después: PUE de proveedores distintos,
        # montos medianos, ni gasolina ni listas negras.
        candidatas = [
            f for f in pues
            if 2500 <= f.total <= 30000 and f.fecha.day <= 25
            and f.emisor_rfc not in catalogo.LISTAS_NEGRAS
            and catalogo.contraparte_por_rfc(f.emisor_rfc).giro
            in ("papeleria", "refacciones", "taller", "ferreteria", "electrico", "uniformes")
        ]
        candidatas.sort(key=lambda f: f.uuid)
        cancelados, vistos = [], set()
        for f in candidatas:
            if f.emisor_rfc in vistos:
                continue
            cancelados.append(f.uuid)
            vistos.add(f.emisor_rfc)
            if len(cancelados) == 3:
                break
        return out, frozenset(cancelados)

    def _complementos_septiembre(self, rng, ppds, pue_cdv, cdv) -> list:
        elegibles = [x for x in ppds if x[1].fecha.day <= 21]
        completas = elegibles[:30]
        parciales = elegibles[30:42]
        out = []

        # Completas: 4 complementos pagan dos facturas del mismo proveedor.
        por_prov: dict = {}
        for p, f in completas:
            por_prov.setdefault(p.nombre, []).append((p, f))
        dobles = 0
        grupos = []
        for nombre in sorted(por_prov):
            facturas = por_prov[nombre]
            while facturas:
                if dobles < 4 and len(facturas) >= 2:
                    grupos.append(facturas[:2])
                    facturas = facturas[2:]
                    dobles += 1
                else:
                    grupos.append(facturas[:1])
                    facturas = facturas[1:]
        for i, grupo in enumerate(grupos):
            p = grupo[0][0]
            ultima = max(f.fecha for _, f in grupo)
            fecha_pago = min(ultima + timedelta(days=rng.randint(5, 8)), datetime(2026, 9, 28))
            emision = fecha_pago + timedelta(days=rng.randint(0, 2), hours=rng.randint(2, 6))
            doctos = [Docto(f.uuid, f.serie, f.folio, 1, f.total, f.total, f.conceptos[0].tasa)
                      for _, f in grupo]
            out.append(self._complemento_recibido(
                p, emision, Pago(fecha_pago.replace(hour=12, minute=0, second=0), "03", doctos),
                f"cc{i}"))

        for i, (p, f) in enumerate(parciales):
            fecha_pago = min(f.fecha + timedelta(days=rng.randint(5, 8)), datetime(2026, 9, 28))
            emision = fecha_pago + timedelta(days=rng.randint(0, 2), hours=rng.randint(2, 6))
            pagado = _r2(f.total * rng.uniform(0.35, 0.7))
            out.append(self._complemento_recibido(
                p, emision,
                Pago(fecha_pago.replace(hour=12, minute=0, second=0), "03",
                     [Docto(f.uuid, f.serie, f.folio, 1, f.total, pagado, f.conceptos[0].tasa)]),
                f"cp{i}"))

        # PUE con complemento: paga una factura que ya era PUE.
        out.append(self._complemento_recibido(
            cdv, datetime(2026, 9, 11, 16, 2, 9),
            Pago(datetime(2026, 9, 10, 12, 0, 0), "03",
                 [Docto(pue_cdv.uuid, pue_cdv.serie, pue_cdv.folio, 1, pue_cdv.total,
                        pue_cdv.total, pue_cdv.conceptos[0].tasa)]),
            "pue-con-complemento"))

        # Huérfano: paga una factura de marzo que nunca se descargó.
        lacteos = next(p for p in self.perfil.proveedores if p.nombre.startswith("LACTEOS"))
        huerfana = _uuid("huerfana", EL_ROBLE, lacteos.rfc)
        out.append(self._complemento_recibido(
            lacteos, datetime(2026, 9, 16, 13, 41, 27),
            Pago(datetime(2026, 9, 15, 12, 0, 0), "03",
                 [Docto(huerfana, "LS", "18734", 2, 21460.80, 21460.80, "0")]),
            "huerfano"))

        # Extemporáneos: pagos de julio cuyo complemento se emitió en
        # septiembre (después del día 5 del mes siguiente al pago).
        julio = _mes(EL_ROBLE, 2026, 7).comprobantes
        pagadas_julio = {d.uuid for c in julio if c.tipo == "P" for d in c.pago.doctos}
        sin_pagar = [c for c in julio if c.direccion == "R" and c.tipo == "I"
                     and c.metodo_pago == "PPD" and c.uuid not in pagadas_julio
                     and c.fecha.day <= 18]
        sin_pagar.sort(key=lambda c: (c.fecha, c.uuid))
        vistos = set()
        extemporaneas = []
        for c in sin_pagar:
            if c.emisor_rfc in vistos:
                continue
            vistos.add(c.emisor_rfc)
            extemporaneas.append(c)
            if len(extemporaneas) == 2:
                break
        for i, (f, dia_emision) in enumerate(zip(extemporaneas, (9, 17))):
            p = catalogo.contraparte_por_rfc(f.emisor_rfc)
            fecha_pago = f.fecha + timedelta(days=10)
            out.append(self._complemento_recibido(
                p, datetime(2026, 9, dia_emision, 10 + i, 14, 33),
                Pago(fecha_pago.replace(hour=12, minute=0, second=0), "03",
                     [Docto(f.uuid, f.serie, f.folio, 1, f.total, f.total, f.conceptos[0].tasa)]),
                f"extemporaneo{i}"))
        return out

    # ---- emitidos -------------------------------------------------------
    def emitidos(self) -> list:
        perfil = self.perfil
        rng = self._rng("emitidos")
        out: list = []
        mensuales = [c for c in perfil.clientes if c.mensual]
        variables = [c for c in perfil.clientes if not c.mensual]
        for cli in mensuales:
            fecha = datetime(self.anio, self.mes, min(cli.mensual, self.dias), 10, 5, 12)
            out.append(self._factura_emitida(cli, fecha, "PUE", f"m{cli.nombre}"))
        n = max(0, self._volumen(perfil.emitidos_mes, "E") - len(mensuales))
        if variables and n:
            elegidos = rng.choices(variables, weights=[c.peso for c in variables], k=n)
            for i, cli in enumerate(elegidos):
                metodo = "PPD" if cli.credito and rng.random() < 0.8 else "PUE"
                fecha = self._fecha(rng, 1, 26 if metodo == "PPD" else None, hora=(8, 19))
                f = self._factura_emitida(cli, fecha, metodo, f"e{i}")
                out.append(f)
                if metodo == "PPD":
                    out.extend(self._cobro_mismo_mes(cli, f, f"e{i}"))
        if perfil.global_publico:
            out.extend(self._globales())
        out.extend(self._nomina_emitida())
        return out

    def _cobro_mismo_mes(self, cli: Contraparte, f: Comprobante, clave: str) -> list:
        rng = self._rng("cobro", clave)
        if rng.random() >= 0.7:
            return []
        fecha_pago = f.fecha + timedelta(days=rng.randint(5, 15))
        emision = fecha_pago + timedelta(days=rng.randint(0, 2), hours=rng.randint(1, 4))
        if emision > self.fin_mes:
            return []
        pago = Pago(fecha_pago.replace(hour=12, minute=0, second=0), "03",
                    [Docto(f.uuid, f.serie, f.folio, 1, f.total, f.total, f.conceptos[0].tasa)])
        return [self._complemento(
            self.emp.rfc, self.emp.nombre_sat, self.emp.regimen, cli.rfc, cli.nombre,
            cli.regimen, self._cp(cli.nombre), self.emp.cp, emision, pago, clave, "E",
            self.emp.nombre_sat,
        )]

    def _globales(self) -> list:
        """Factura global semanal a público en general (venta de mostrador)."""
        rng = self._rng("global")
        out = []
        dia = 7
        semana = 0
        while dia <= self.dias:
            uuid = self._uuid("G", semana)
            serie, folio = self._folio(self.emp.nombre_sat + " G")
            importe = _r2(rng.uniform(38000, 52000))
            out.append(Comprobante(
                uuid=uuid, tipo="I", fecha=datetime(self.anio, self.mes, dia, 21, 30, 4),
                emisor_rfc=self.emp.rfc, emisor_nombre=self.emp.nombre_sat,
                emisor_regimen=self.emp.regimen, receptor_rfc=RFC_PUBLICO,
                receptor_nombre="PUBLICO EN GENERAL", receptor_regimen="616",
                receptor_cp=self.emp.cp, uso_cfdi="S01", lugar=self.emp.cp,
                serie="G", folio=folio, direccion="E", metodo_pago="PUE", forma_pago="01",
                conceptos=[Concepto("01010101", "Venta de mostrador de la semana", "ACT",
                                    "Actividad", 1.0, importe, importe, "0")],
                global_semana=("02", f"{self.mes:02d}", str(self.anio)), pac=self._pac(uuid),
            ))
            dia += 7
            semana += 1
        return out

    def _nomina_emitida(self) -> list:
        info = catalogo.PATRONES.get(self.emp.rfc)
        if not info or "patron" in info:
            return []
        out = []
        for emp in catalogo.EMPLEADOS.get(self.emp.rfc, ()):
            for q, recibo in enumerate(self._recibos(emp, info)):
                uuid = self._uuid("N", emp.num, q)
                serie, folio = self._folio(self.emp.nombre_sat + " NOM")
                out.append(Comprobante(
                    uuid=uuid, tipo="N",
                    fecha=_dt(recibo.fecha_pago, 17, 10 + int(emp.num) % 40, 30),
                    emisor_rfc=self.emp.rfc, emisor_nombre=self.emp.nombre_sat,
                    emisor_regimen=self.emp.regimen, receptor_rfc=emp.rfc,
                    receptor_nombre=_plano_mayus(emp.nombre), receptor_regimen="605",
                    receptor_cp=self._cp(emp.nombre), uso_cfdi="CN01", lugar=self.emp.cp,
                    serie="NOM", folio=folio, direccion="E", metodo_pago="PUE",
                    forma_pago="99", nomina=recibo, pac=self._pac(uuid),
                ))
        return out

    def _recibos(self, emp, info) -> list:
        """Las dos quincenas del mes de un empleado."""
        from ..procesador.constants_nomina import (
            calcular_isr_bruto, calcular_spe, get_limite_spe,
        )

        out = []
        quincenas = ((1, 15), (16, self.dias))
        ingreso = date.fromisoformat(emp.ingreso)
        uma = 117.31
        for inicio_dia, fin_dia in quincenas:
            inicio = date(self.anio, self.mes, inicio_dia)
            fin = date(self.anio, self.mes, fin_dia)
            if fin < ingreso:
                continue
            pago = fin
            while pago.weekday() >= 5:  # sábado/domingo → viernes anterior
                pago -= timedelta(days=1)
            dias = 15.0
            sueldo = _r2(emp.salario_diario * dias)
            percepciones = [("001", "001", "Sueldo", sueldo, 0.0)]
            if emp.premio_puntualidad:
                percepciones.append(("010", "010", "Premio de puntualidad", _r2(sueldo * 0.10), 0.0))
            if emp.horas_extra:
                mitad = _r2(emp.horas_extra / 2)
                percepciones.append(("019", "019", "Horas extra dobles", mitad, _r2(emp.horas_extra - mitad)))
            gravado_q = sum(g for *_, g, _ in percepciones)
            gravado_mes = gravado_q * 2
            isr_mes = calcular_isr_bruto(gravado_mes, self.anio)
            if gravado_mes <= get_limite_spe(self.anio):
                isr_mes = max(0.0, isr_mes - calcular_spe(gravado_mes, self.anio, self.mes))
            isr_q = _r2(isr_mes / 2)
            if (self.emp.rfc, emp.num) == catalogo.EMPLEADO_CON_DIFERENCIA_ISR:
                isr_q = _r2(isr_q * 0.82)
            sbc = _r2(emp.salario_diario * 1.0493)
            imss = sbc * dias * 0.02375
            if sbc > 3 * uma:
                imss += (sbc - 3 * uma) * dias * 0.004
            deducciones = [("002", "002", "ISR", isr_q), ("001", "001", "Seguridad social", _r2(imss))]
            if emp.infonavit:
                deducciones.append(("010", "010", "Pago por crédito de vivienda", emp.infonavit))
            out.append(ReciboNomina(emp, info, pago, inicio, fin, dias, percepciones,
                                    deducciones, sbc))
        return out


_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre")


def _dt(d: date, h: int, m: int, s: int) -> datetime:
    return datetime(d.year, d.month, d.day, h, m % 60, s % 60)


def _plano_mayus(texto: str) -> str:
    import unicodedata
    sin = unicodedata.normalize("NFD", texto.upper())
    return "".join(c for c in sin if not unicodedata.combining(c) or c == "̃")\
        .replace("Ñ", "Ñ")


def _repartir(total: int, pesos: list, minimo: int = 0) -> list:
    """Reparte `total` en enteros proporcionales a `pesos` (residuo mayor)."""
    n = len(pesos)
    if n == 0:
        return []
    base = [minimo] * n
    resto = total - minimo * n
    if resto <= 0:
        return base
    suma = float(sum(pesos)) or 1.0
    exactos = [resto * p / suma for p in pesos]
    enteros = [int(x) for x in exactos]
    faltan = resto - sum(enteros)
    orden = sorted(range(n), key=lambda i: exactos[i] - enteros[i], reverse=True)
    for i in orden[:faltan]:
        enteros[i] += 1
    return [b + e for b, e in zip(base, enteros)]


# ---------------------------------------------------------------------------
# Serialización a XML (CFDI 4.0)
# ---------------------------------------------------------------------------

_NS_CFDI = "http://www.sat.gob.mx/cfd/4"
_NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
_NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"
_NS_PAGO = "http://www.sat.gob.mx/Pagos20"
_NS_NOM = "http://www.sat.gob.mx/nomina12"


def _b64_relleno(semilla: str, n_bytes: int) -> str:
    import base64

    salida = b""
    i = 0
    while len(salida) < n_bytes:
        salida += hashlib.sha512(f"{semilla}|{i}".encode()).digest()
        i += 1
    return base64.b64encode(salida[:n_bytes]).decode()


def _no_certificado(rfc: str) -> str:
    return "00001000000" + f"{_semilla('nocert', rfc) % 10**9:09d}"


def _a(nombre: str, valor) -> str:
    return f" {nombre}={quoteattr(str(valor))}"


def _cantidad(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".") if x != int(x) else str(int(x))


def _traslados_concepto(c: Concepto) -> str:
    if c.tasa == "":
        return ""
    if c.tasa == "exento":
        tras = f'<cfdi:Traslado{_a("Base", _fmt(c.importe))} Impuesto="002" TipoFactor="Exento"/>'
    else:
        tasa = "0.160000" if c.tasa == "16" else "0.000000"
        tras = (f'<cfdi:Traslado{_a("Base", _fmt(c.importe))} Impuesto="002" TipoFactor="Tasa"'
                f' TasaOCuota="{tasa}"{_a("Importe", _fmt(c.iva))}/>')
    rets = ""
    if c.ret_isr:
        rets += (f'<cfdi:Retencion{_a("Base", _fmt(c.importe))} Impuesto="001" TipoFactor="Tasa"'
                 f' TasaOCuota="{c.tasa_ret_isr}"{_a("Importe", _fmt(c.ret_isr))}/>')
    if c.ret_iva:
        rets += (f'<cfdi:Retencion{_a("Base", _fmt(c.importe))} Impuesto="002" TipoFactor="Tasa"'
                 f' TasaOCuota="{c.tasa_ret_iva}"{_a("Importe", _fmt(c.ret_iva))}/>')
    out = f"<cfdi:Impuestos><cfdi:Traslados>{tras}</cfdi:Traslados>"
    if rets:
        out += f"<cfdi:Retenciones>{rets}</cfdi:Retenciones>"
    return out + "</cfdi:Impuestos>"


def _impuestos_globales(comp: Comprobante) -> str:
    grupos: dict = {}
    exento_base = 0.0
    for c in comp.conceptos:
        if c.tasa == "exento":
            exento_base += c.importe
        elif c.tasa in ("16", "0"):
            b, i = grupos.get(c.tasa, (0.0, 0.0))
            grupos[c.tasa] = (b + c.importe, i + c.iva)
    if not grupos and not exento_base:
        return ""
    traslados = ""
    for tasa in sorted(grupos, reverse=True):
        b, i = grupos[tasa]
        cuota = "0.160000" if tasa == "16" else "0.000000"
        traslados += (f'<cfdi:Traslado{_a("Base", _fmt(b))} Impuesto="002" TipoFactor="Tasa"'
                      f' TasaOCuota="{cuota}"{_a("Importe", _fmt(i))}/>')
    if exento_base:
        traslados += f'<cfdi:Traslado{_a("Base", _fmt(exento_base))} Impuesto="002" TipoFactor="Exento"/>'
    rets = ""
    if comp.ret_isr:
        rets += f'<cfdi:Retencion Impuesto="001"{_a("Importe", _fmt(comp.ret_isr))}/>'
    if comp.ret_iva:
        rets += f'<cfdi:Retencion Impuesto="002"{_a("Importe", _fmt(comp.ret_iva))}/>'
    attrs = ""
    if rets:
        attrs += _a("TotalImpuestosRetenidos", _fmt(comp.ret_isr + comp.ret_iva))
    if grupos:
        attrs += _a("TotalImpuestosTrasladados", _fmt(comp.iva))
    out = f"<cfdi:Impuestos{attrs}>"
    if rets:
        out += f"<cfdi:Retenciones>{rets}</cfdi:Retenciones>"
    return out + f"<cfdi:Traslados>{traslados}</cfdi:Traslados></cfdi:Impuestos>"


def _pagos_xml(comp: Comprobante) -> str:
    pago = comp.pago
    base16 = iva16 = base0 = 0.0
    doctos = ""
    for d in pago.doctos:
        insoluto = _r2(d.saldo_ant - d.pagado)
        if d.tasa == "16":
            base = _r2(d.pagado / 1.16)
            iva = _r2(d.pagado - base)
            base16 += base
            iva16 += iva
            imp = (f'<pago20:ImpuestosDR><pago20:TrasladosDR><pago20:TrasladoDR{_a("BaseDR", _fmt(base))}'
                   f' ImpuestoDR="002" TipoFactorDR="Tasa" TasaOCuotaDR="0.160000"{_a("ImporteDR", _fmt(iva))}/>'
                   f'</pago20:TrasladosDR></pago20:ImpuestosDR>')
        else:
            base = _r2(d.pagado)
            base0 += base
            imp = (f'<pago20:ImpuestosDR><pago20:TrasladosDR><pago20:TrasladoDR{_a("BaseDR", _fmt(base))}'
                   f' ImpuestoDR="002" TipoFactorDR="Tasa" TasaOCuotaDR="0.000000" ImporteDR="0.00"/>'
                   f'</pago20:TrasladosDR></pago20:ImpuestosDR>')
        doctos += (f'<pago20:DoctoRelacionado{_a("IdDocumento", d.uuid)}{_a("Serie", d.serie)}'
                   f'{_a("Folio", d.folio)} MonedaDR="MXN" EquivalenciaDR="1"'
                   f'{_a("NumParcialidad", d.parcialidad)}{_a("ImpSaldoAnt", _fmt(d.saldo_ant))}'
                   f'{_a("ImpPagado", _fmt(d.pagado))}{_a("ImpSaldoInsoluto", _fmt(insoluto))}'
                   f' ObjetoImpDR="02">{imp}</pago20:DoctoRelacionado>')
    totales = ""
    traslados_p = ""
    if base16:
        totales += _a("TotalTrasladosBaseIVA16", _fmt(base16)) + _a("TotalTrasladosImpuestoIVA16", _fmt(iva16))
        traslados_p += (f'<pago20:TrasladoP{_a("BaseP", _fmt(base16))} ImpuestoP="002" TipoFactorP="Tasa"'
                        f' TasaOCuotaP="0.160000"{_a("ImporteP", _fmt(iva16))}/>')
    if base0:
        totales += _a("TotalTrasladosBaseIVA0", _fmt(base0)) + ' TotalTrasladosImpuestoIVA0="0.00"'
        traslados_p += (f'<pago20:TrasladoP{_a("BaseP", _fmt(base0))} ImpuestoP="002" TipoFactorP="Tasa"'
                        f' TasaOCuotaP="0.000000" ImporteP="0.00"/>')
    return (
        f'<pago20:Pagos xmlns:pago20="{_NS_PAGO}" Version="2.0">'
        f'<pago20:Totales{totales}{_a("MontoTotalPagos", _fmt(pago.monto))}/>'
        f'<pago20:Pago{_a("FechaPago", pago.fecha_pago.strftime("%Y-%m-%dT%H:%M:%S"))}'
        f'{_a("FormaDePagoP", pago.forma)} MonedaP="MXN" TipoCambioP="1"{_a("Monto", _fmt(pago.monto))}>'
        f'{doctos}<pago20:ImpuestosP><pago20:TrasladosP>{traslados_p}</pago20:TrasladosP>'
        f'</pago20:ImpuestosP></pago20:Pago></pago20:Pagos>'
    )


def _nomina_xml(comp: Comprobante) -> str:
    r = comp.nomina
    e = r.empleado
    ingreso = date.fromisoformat(e.ingreso)
    semanas = max(1, (r.fin - ingreso).days // 7)
    total_grav = _r2(sum(g for *_, g, _ in r.percepciones))
    total_exe = _r2(sum(x for *_, x in r.percepciones))
    percs = "".join(
        f'<nomina12:Percepcion{_a("TipoPercepcion", t)}{_a("Clave", c)}{_a("Concepto", n)}'
        f'{_a("ImporteGravado", _fmt(g))}{_a("ImporteExento", _fmt(x))}/>'
        for t, c, n, g, x in r.percepciones
    )
    isr = _r2(sum(i for t, _, _, i in r.deducciones if t == "002"))
    otras = _r2(sum(i for t, _, _, i in r.deducciones if t != "002"))
    deds = "".join(
        f'<nomina12:Deduccion{_a("TipoDeduccion", t)}{_a("Clave", c)}{_a("Concepto", n)}'
        f'{_a("Importe", _fmt(i))}/>'
        for t, c, n, i in r.deducciones
    )
    ded_attrs = ""
    if otras:
        ded_attrs += _a("TotalOtrasDeducciones", _fmt(otras))
    if isr:
        ded_attrs += _a("TotalImpuestosRetenidos", _fmt(isr))
    bancos = ("012", "014", "072", "002", "021")
    banco = bancos[int(e.num) % len(bancos)] if e.num.isdigit() else "012"
    cuenta = f"{_semilla('cuenta', e.nombre) % 10**10:010d}"
    return (
        f'<nomina12:Nomina xmlns:nomina12="{_NS_NOM}" Version="1.2" TipoNomina="O"'
        f'{_a("FechaPago", r.fecha_pago.isoformat())}{_a("FechaInicialPago", r.inicio.isoformat())}'
        f'{_a("FechaFinalPago", r.fin.isoformat())} NumDiasPagados="{r.dias:.3f}"'
        f'{_a("TotalPercepciones", _fmt(r.total_percepciones))}'
        f'{_a("TotalDeducciones", _fmt(r.total_deducciones))}>'
        f'<nomina12:Emisor{_a("RegistroPatronal", r.patron["registro_patronal"])}/>'
        f'<nomina12:Receptor{_a("Curp", e.curp)}{_a("NumSeguridadSocial", e.nss)}'
        f'{_a("FechaInicioRelLaboral", e.ingreso)} Antigüedad="P{semanas}W" TipoContrato="01"'
        f' Sindicalizado="No"{_a("TipoJornada", e.jornada)} TipoRegimen="02"'
        f'{_a("NumEmpleado", e.num)}{_a("Departamento", e.departamento)}{_a("Puesto", e.puesto)}'
        f'{_a("RiesgoPuesto", r.patron["riesgo"])} PeriodicidadPago="04"{_a("Banco", banco)}'
        f'{_a("CuentaBancaria", cuenta)}{_a("SalarioBaseCotApor", _fmt(r.sbc))}'
        f'{_a("SalarioDiarioIntegrado", _fmt(r.sbc))}{_a("ClaveEntFed", r.patron["entidad"])}/>'
        f'<nomina12:Percepciones{_a("TotalSueldos", _fmt(r.total_percepciones))}'
        f'{_a("TotalGravado", _fmt(total_grav))}{_a("TotalExento", _fmt(total_exe))}>{percs}'
        f'</nomina12:Percepciones>'
        f'<nomina12:Deducciones{ded_attrs}>{deds}</nomina12:Deducciones>'
        f'</nomina12:Nomina>'
    )


def xml(comp: Comprobante) -> bytes:
    """CFDI 4.0 del comprobante, listo para escribir a disco."""
    fecha = comp.fecha.strftime("%Y-%m-%dT%H:%M:%S")
    sello = _b64_relleno("sello|" + comp.uuid, 256)
    cert = _b64_relleno("cert|" + comp.emisor_rfc, 1000)
    attrs = (
        f'Version="4.0"{_a("Serie", comp.serie)}{_a("Folio", comp.folio)}{_a("Fecha", fecha)}'
        f'{_a("Sello", sello)}'
    )
    if comp.tipo in ("I", "E") and comp.forma_pago:
        attrs += _a("FormaPago", comp.forma_pago)
    if comp.tipo == "N":
        attrs += ' FormaPago="99"'
    attrs += f'{_a("NoCertificado", _no_certificado(comp.emisor_rfc))}{_a("Certificado", cert)}'
    attrs += _a("SubTotal", "0" if comp.tipo == "P" else _fmt(comp.subtotal))
    if comp.tipo == "N" and comp.descuento:
        attrs += _a("Descuento", _fmt(comp.descuento))
    attrs += ' Moneda="XXX"' if comp.tipo == "P" else ' Moneda="MXN"'
    attrs += _a("Total", "0" if comp.tipo == "P" else _fmt(comp.total))
    attrs += f'{_a("TipoDeComprobante", comp.tipo)} Exportacion="01"'
    if comp.tipo in ("I", "E", "N"):
        attrs += _a("MetodoPago", comp.metodo_pago or "PUE")
    attrs += _a("LugarExpedicion", comp.lugar)

    partes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<cfdi:Comprobante xmlns:cfdi="{_NS_CFDI}" xmlns:xsi="{_NS_XSI}"'
        f' xsi:schemaLocation="{_NS_CFDI} http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd'
        + (f' {_NS_PAGO} http://www.sat.gob.mx/sitio_internet/cfd/Pagos/Pagos20.xsd' if comp.tipo == "P" else "")
        + (f' {_NS_NOM} http://www.sat.gob.mx/sitio_internet/cfd/nomina/nomina12.xsd' if comp.tipo == "N" else "")
        + f'" {attrs}>',
    ]
    if comp.global_semana:
        per, mes, anio = comp.global_semana
        partes.append(f'<cfdi:InformacionGlobal Periodicidad="{per}" Meses="{mes}" Año="{anio}"/>')
    if comp.relacionados:
        rel = "".join(f'<cfdi:CfdiRelacionado{_a("UUID", u)}/>' for u in comp.relacionados)
        partes.append(f'<cfdi:CfdiRelacionados TipoRelacion="01">{rel}</cfdi:CfdiRelacionados>')
    partes.append(f'<cfdi:Emisor{_a("Rfc", comp.emisor_rfc)}{_a("Nombre", comp.emisor_nombre)}'
                  f'{_a("RegimenFiscal", comp.emisor_regimen)}/>')
    partes.append(f'<cfdi:Receptor{_a("Rfc", comp.receptor_rfc)}{_a("Nombre", comp.receptor_nombre)}'
                  f'{_a("DomicilioFiscalReceptor", comp.receptor_cp)}'
                  f'{_a("RegimenFiscalReceptor", comp.receptor_regimen)}{_a("UsoCFDI", comp.uso_cfdi)}/>')
    partes.append("<cfdi:Conceptos>")
    if comp.tipo == "P":
        partes.append('<cfdi:Concepto ClaveProdServ="84111506" Cantidad="1" ClaveUnidad="ACT"'
                      ' Descripcion="Pago" ValorUnitario="0" Importe="0" ObjetoImp="01"/>')
    elif comp.tipo == "N":
        partes.append(f'<cfdi:Concepto ClaveProdServ="84111505" Cantidad="1" ClaveUnidad="ACT"'
                      f' Descripcion="Pago de nómina"{_a("ValorUnitario", _fmt(comp.subtotal))}'
                      f'{_a("Importe", _fmt(comp.subtotal))}{_a("Descuento", _fmt(comp.descuento))}'
                      f' ObjetoImp="01"/>')
    else:
        for c in comp.conceptos:
            partes.append(
                f'<cfdi:Concepto{_a("ClaveProdServ", c.clave)}{_a("Cantidad", _cantidad(c.cantidad))}'
                f'{_a("ClaveUnidad", c.clave_unidad)}{_a("Unidad", c.unidad)}'
                f'{_a("Descripcion", c.descripcion)}{_a("ValorUnitario", _fmt(c.valor_unitario))}'
                f'{_a("Importe", _fmt(c.importe))} ObjetoImp="02">{_traslados_concepto(c)}'
                f'</cfdi:Concepto>'
            )
    partes.append("</cfdi:Conceptos>")
    if comp.tipo in ("I", "E"):
        partes.append(_impuestos_globales(comp))
    partes.append("<cfdi:Complemento>")
    if comp.tipo == "P":
        partes.append(_pagos_xml(comp))
    if comp.tipo == "N":
        partes.append(_nomina_xml(comp))
    timbrado = comp.fecha + timedelta(seconds=7 + int(comp.uuid[-2:], 16) % 80)
    partes.append(
        f'<tfd:TimbreFiscalDigital xmlns:tfd="{_NS_TFD}" xsi:schemaLocation="{_NS_TFD}'
        f' http://www.sat.gob.mx/sitio_internet/cfd/TimbreFiscalDigital/TimbreFiscalDigitalv11.xsd"'
        f' Version="1.1"{_a("UUID", comp.uuid)}{_a("FechaTimbrado", timbrado.strftime("%Y-%m-%dT%H:%M:%S"))}'
        f'{_a("RfcProvCertif", comp.pac)}{_a("SelloCFD", sello)}'
        f'{_a("NoCertificadoSAT", _no_certificado("SAT"))}'
        f'{_a("SelloSAT", _b64_relleno("sellosat|" + comp.uuid, 256))}/>'
    )
    partes.append("</cfdi:Complemento></cfdi:Comprobante>")
    return "".join(partes).encode("utf-8")


def metadata_txt(comps: list) -> bytes:
    """Archivo de metadata del SAT (separado por ~) para una lista de comprobantes."""
    lineas = ["Uuid~RfcEmisor~NombreEmisor~RfcReceptor~NombreReceptor~RfcPac~FechaEmision"
              "~FechaCertificacionSat~Monto~EfectoComprobante~Estatus~FechaCancelacion"]
    for c in comps:
        timbrado = c.fecha + timedelta(seconds=7 + int(c.uuid[-2:], 16) % 80)
        lineas.append("~".join((
            c.uuid, c.emisor_rfc, c.emisor_nombre, c.receptor_rfc, c.receptor_nombre, c.pac,
            c.fecha.strftime("%Y-%m-%d %H:%M:%S"), timbrado.strftime("%Y-%m-%d %H:%M:%S"),
            f"{c.monto_metadata:.2f}", c.tipo, "1", "",
        )))
    return ("\r\n".join(lineas) + "\r\n").encode("utf-8")


def nombre_archivo(comp: Comprobante) -> str:
    return f"{comp.uuid}.xml"


__all__ = [
    "Comprobante", "comprobantes", "en_rango", "buscar", "estatus", "cancelados_despues",
    "xml", "metadata_txt", "nombre_archivo", "escape",
]
