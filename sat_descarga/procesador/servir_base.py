"""Solicitud manual que sirve de la base lo ya consolidado.

Fase 6 de docs/producto/descarga-programada.md. Un día `consolidado` del cuadro
de control ya tiene sus CFDIs completos en el índice local (cierre mensual,
fase 4), así que pedirlo otra vez al SAT gasta una descarga del mes para nada.
Aquí se parte el rango pedido en lo que se sirve de la base y lo que sí hay que
pedir al SAT (`plan`), y se escriben los XML de lo primero en la carpeta de la
descarga (`materializar`).

Sin FastAPI: el endpoint (`api/routers/webservice.py`) solo orquesta.
"""

from __future__ import annotations

import logging
import zlib
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Optional

from ..cli import config_store
from ..core import paths
from . import calendario
from .db import abrir_db, normalizar_mi_rfc

logger = logging.getLogger(__name__)

# Solicitudes al SAT que se aceptan por petición (los huecos se juntan si son más).
MAX_RANGOS = 6

# UUID por consulta al leer los documentos (tope de variables de SQLite).
_LOTE = 200


def _buscar_documentos(mi_rfc: str, uuids: list[str], columnas: str,
                       extra: str = "") -> Iterable[tuple]:
    """Filas `columnas` de `cfdi_documentos` de `uuids` (tal como están en el
    índice, ver `calendario.uuids_por_dia(mayusculas=False)`), por lotes.
    `columnas` empieza con `uuid`."""
    db = abrir_db()
    for i in range(0, len(uuids), _LOTE):
        trozo = uuids[i:i + _LOTE]
        marcas = ",".join("?" * len(trozo))
        with db.cursor() as cur:
            yield from cur.execute(
                f"SELECT {columnas} FROM cfdi_documentos"
                f" WHERE mi_rfc = ? AND uuid IN ({marcas}){extra}",
                (mi_rfc, *trozo),
            ).fetchall()


def _con_xml(mi_rfc: str, uuids: list[str]) -> set[str]:
    """UUID de `uuids` (como están en el índice) que tienen el XML guardado."""
    return {r[0] for r in _buscar_documentos(
        mi_rfc, uuids, "uuid", " AND xml_zlib IS NOT NULL")}


def plan_sin_base(desde: date, hasta: date) -> dict:
    """El flujo de siempre (`/solicitar`): un solo hueco con todo el rango
    (recortado a hoy) y nada servido de la base. Lo usa el endpoint cuando la
    petición trae filtros por RFC (lo consolidado no está filtrado) o cuando el
    índice falla."""
    hasta = min(hasta, calendario.hoy())
    if desde > hasta:
        return {"consolidados": [], "huecos": [], "uuids": {}}
    return {"consolidados": [], "huecos": [(desde, hasta)], "uuids": {}}


def plan(rfc: str, desde: date, hasta: date, direccion: str) -> dict:
    """Parte `desde..hasta` (recortado a hoy) en lo que se sirve de la base y lo
    que hay que pedir: `{"consolidados": [date…], "huecos": [(a, b)…],
    "uuids": {date: {UUID…}}}` (los UUID de los días que se sirven, para que
    `materializar` no los busque otra vez).

    Solo `consolidado` se sirve, y solo si todos sus CFDI tienen el XML guardado;
    cualquier otro estado (`diferencia` y `provisional` incluidos) es hueco,
    porque no hay garantía de que el índice esté completo. Los huecos son rangos
    contiguos mínimos, y si son más de MAX_RANGOS se juntan los más cercanos; los
    días consolidados que caen dentro de un hueco juntado se piden al SAT, así
    que ya no se sirven."""
    hasta = min(hasta, calendario.hoy())
    if desde > hasta:
        return {"consolidados": [], "huecos": [], "uuids": {}}
    dias = [desde + timedelta(days=n) for n in range((hasta - desde).days + 1)]
    guardadas = calendario.filas(rfc, dias[0], dias[-1])
    consolidados: list[date] = []
    faltan: list[date] = []
    for d in dias:
        fila = guardadas.get((d.isoformat(), direccion))
        if fila and fila["estado"] == "consolidado":
            consolidados.append(d)
        else:
            faltan.append(d)

    uuids_dia: dict[date, set[str]] = {}
    if consolidados:
        mi_rfc = normalizar_mi_rfc(rfc)
        por_dia = calendario.uuids_por_dia(
            mi_rfc, consolidados[0], consolidados[-1], mayusculas=False)
        todos = {d: por_dia.get((d.isoformat(), direccion), set()) for d in consolidados}
        tienen = _con_xml(mi_rfc, sorted(set().union(*todos.values())))
        completos: list[date] = []
        for d in consolidados:
            if todos[d] <= tienen:
                completos.append(d)
            else:
                faltan.append(d)
        consolidados = completos
        uuids_dia = {d: todos[d] for d in completos}

    huecos = calendario.rangos_contiguos(faltan, MAX_RANGOS)
    if huecos:
        consolidados = [
            d for d in consolidados if not any(a <= d <= b for a, b in huecos)
        ]
        uuids_dia = {d: uuids_dia[d] for d in consolidados}
    return {"consolidados": consolidados, "huecos": huecos, "uuids": uuids_dia}


def _documentos(mi_rfc: str, uuids: list[str]) -> Iterable[tuple[str, Optional[bytes]]]:
    """`(uuid, xml | None)` por lotes; None = indexado pero sin XML guardado."""
    for i in range(0, len(uuids), _LOTE):
        trozo = uuids[i:i + _LOTE]
        docs = {r[0]: r[1] for r in _buscar_documentos(
            mi_rfc, trozo, "uuid, xml_zlib")}
        for u in trozo:
            blob = docs.get(u)
            yield u, (zlib.decompress(blob) if blob is not None else None)


def materializar(
    rfc: str,
    dias_consolidados: list[date],
    direccion: str,
    *,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    uuids_por_dia: Optional[dict] = None,
) -> dict:
    """Escribe `{UUID}.xml` de los días consolidados en la carpeta de la descarga
    del rango PEDIDO (`desde..hasta`; por omisión, del primer al último día), la
    misma que usaría la descarga del SAT: así "abrir carpeta" junta todo.

    Devuelve `{"ruta": str | None, "cfdis": n, "sin_xml": m}`. Con 0 CFDI
    escritos no crea la carpeta ni registra nada. Los CFDI ya están en el
    índice: el historial se registra directo, sin reindexar. `uuids_por_dia`
    (`{date: {UUID…}}` con el UUID tal como está guardado, lo que devuelve `plan`
    en "uuids"; `calendario.uuids_por_dia(..., mayusculas=False)`) evita volver a
    calcularlos."""
    if not dias_consolidados:
        return {"ruta": None, "cfdis": 0, "sin_xml": 0}
    mi_rfc = normalizar_mi_rfc(rfc)
    dias = sorted(set(dias_consolidados))
    desde = desde or dias[0]
    hasta = hasta or dias[-1]

    if uuids_por_dia is None:
        por_dia = calendario.uuids_por_dia(mi_rfc, dias[0], dias[-1], mayusculas=False)
        uuids_por_dia = {d: por_dia.get((d.isoformat(), direccion), set()) for d in dias}
    uuids = sorted(set().union(*(uuids_por_dia.get(d, set()) for d in dias)))

    carpeta = Path(paths.dir_cfdi(
        mi_rfc, direccion, desde, hasta, salida_base=config_store.get_descargas_dir(),
    ))
    escritos = sin_xml = 0
    for uuid, xml in _documentos(mi_rfc, uuids):
        if xml is None:
            sin_xml += 1
            continue
        if escritos == 0:
            carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"{uuid.upper()}.xml").write_bytes(xml)
        escritos += 1
    if not escritos:
        return {"ruta": None, "cfdis": 0, "sin_xml": sin_xml}

    config_store.registrar_descarga(
        mi_rfc, "base", "cfdi",
        descripcion=f"Desde la base · {desde.isoformat()} a {hasta.isoformat()} "
                    f"({escritos} CFDI consolidados)",
        ruta=str(carpeta), total=escritos,
    )
    return {"ruta": str(carpeta), "cfdis": escritos, "sin_xml": sin_xml}
