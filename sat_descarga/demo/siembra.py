"""
Siembra de la cuenta de grabación.

Da de alta las empresas de demo (e.firma de ejemplo y Contraseña de ejemplo),
deja sus documentos con los semáforos que piden los guiones y un historial de
descargas de meses anteriores, para que Despacho > Empresas, Historial y la
barra de estado se vean usados. Es idempotente: correrla dos veces no duplica
nada, y nunca toca una empresa que no sea de demo.

Semáforos al sembrar (pieza 2):
  - 32-D verde: Transportes Molina, Constructora del Valle.
  - 32-D roja (con motivos): Norma Reyes Aguilar.
  - 32-D amarilla "sin analizar": Panadería La Central.
  - 32-D gris (sin bajar): Distribuidora El Roble, Servicios Integrales del
    Bajío y Laura García Cervantes (las dos primeras se bajan en cuadro).
  - Sin constancia: Panadería La Central y Transportes Molina (se bajan en
    cuadro: por ⌘K y con captcha).
"""

from __future__ import annotations

import io
import shutil
import tempfile
import uuid as uuidlib
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

from . import activo, cfdi, documentos, efirma
from .escenario import (
    CIEC_DEMO, EL_ROBLE, EMPRESAS, MOLINA, NORMA, PANADERIA, RFCS_DEMO,
)

_SIB = "SIB200117HU9"
_LAURA = "GACL850312H40"
_COV = "COV110714AB2"

# rfc -> (constancia descargada el…, (opinión descargada el…, analizada?))
DOCUMENTOS: dict = {
    EL_ROBLE: (datetime(2026, 9, 8, 10, 31), None),
    PANADERIA: (None, (datetime(2026, 7, 3, 12, 14), False)),
    _SIB: (datetime(2026, 8, 19, 16, 2), None),
    MOLINA: (None, (datetime(2026, 8, 21, 11, 47), True)),
    NORMA: (datetime(2026, 9, 2, 9, 15), (datetime(2026, 10, 1, 9, 40), True)),
    _LAURA: (datetime(2026, 8, 27, 19, 5), None),
    _COV: (datetime(2026, 9, 15, 13, 22), (datetime(2026, 9, 15, 13, 25), True)),
}

# Descargas de CFDI ya hechas: (rfc, E|R, año, mes, canal, cuándo se bajó).
DESCARGAS: tuple = (
    (EL_ROBLE, "R", 2026, 7, "ws", datetime(2026, 8, 4, 10, 12)),
    (EL_ROBLE, "R", 2026, 8, "ws", datetime(2026, 9, 3, 9, 41)),
    (EL_ROBLE, "E", 2026, 8, "ws", datetime(2026, 9, 3, 9, 44)),
    (PANADERIA, "R", 2026, 8, "ws", datetime(2026, 9, 2, 12, 8)),
    (PANADERIA, "E", 2026, 8, "ws", datetime(2026, 9, 2, 12, 5)),
    (PANADERIA, "E", 2026, 9, "ws", datetime(2026, 10, 2, 11, 20)),
    (MOLINA, "R", 2026, 8, "ciec", datetime(2026, 9, 4, 17, 2)),
    (_COV, "R", 2026, 8, "ws", datetime(2026, 9, 7, 13, 30)),
    (_SIB, "R", 2026, 8, "ws", datetime(2026, 9, 8, 10, 15)),
    (NORMA, "R", 2026, 8, "ws", datetime(2026, 9, 10, 18, 4)),
    (NORMA, "E", 2026, 8, "ws", datetime(2026, 9, 10, 18, 6)),
    (_LAURA, "R", 2026, 8, "ws", datetime(2026, 9, 12, 20, 31)),
)
# Opcional (--con-septiembre): la descarga de la pieza 1, ya hecha, para grabar
# las piezas 3 y 4 sin pasar antes por la 1.
SEPTIEMBRE_EL_ROBLE = (EL_ROBLE, "R", 2026, 9, "ws", datetime(2026, 10, 5, 9, 18))

# Buffers del procesador que la pieza 4 ya da por cargados (Nómina de Panadería).
PROCESADOR: tuple = ((PANADERIA, "E", 2026, 9),)

_NS_SIEMBRA = uuidlib.UUID("6f1c0a52-3d7e-4f4b-9a51-2f0c9b7e6a10")


class ModoApagado(RuntimeError):
    pass


def _id_solicitud(rfc: str, tipo: str, anio: int, mes: int) -> str:
    return str(uuidlib.uuid5(_NS_SIEMBRA, f"{rfc}|{tipo}|{anio}|{mes}"))


def _rango(anio: int, mes: int) -> tuple:
    import calendar

    return date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])


def _alta(emp, existentes: dict, tmp: Path, hoy: date, avisar) -> None:
    from ..cli import config_store

    actual = existentes.get(emp.rfc) or {}
    metodos = actual.get("metodos", [])
    agregado = False
    if "fiel" in emp.accesos and "fiel" not in metodos:
        cer, key, pwd = efirma.generar(emp.rfc, tmp, hoy)
        config_store.add_empresa(emp.nombre, str(cer), str(key), pwd)
        avisar(f"  + {emp.nombre} ({emp.rfc}): e.firma de ejemplo")
        agregado = True
    if "ciec" in emp.accesos and "ciec" not in metodos:
        config_store.add_empresa_ciec(emp.rfc, emp.nombre, CIEC_DEMO)
        avisar(f"  + {emp.nombre} ({emp.rfc}): Contraseña de ejemplo")
        agregado = True
    if not agregado:
        avisar(f"  = {emp.nombre} ({emp.rfc}) ya estaba")


def _documentos(rfc: str, base: Path, ahora: datetime, avisar) -> None:
    from ..cli import config_store
    from ..core import paths

    emp = config_store.load_empresas()["empresas"].get(rfc) or {}
    csf, opinion = DOCUMENTOS.get(rfc, (None, None))
    if csf and csf <= ahora and not emp.get("csf_path"):
        destino = paths.dir_documento(paths.TIPO_CONSTANCIA, rfc, salida_base=base) \
            / f"constancia_{rfc}_{csf:%Y%m%d}.pdf"
        documentos.constancia_pdf(rfc, destino, csf.date())
        config_store.set_csf_descargada(rfc, str(destino), cuando=csf)
        _aplicar_csf(rfc, destino)
        config_store.registrar_descarga(
            rfc, "fiel" if "fiel" in EMPRESAS[rfc].accesos else "ciec", "constancia",
            descripcion="Constancia de Situación Fiscal", ruta=str(destino), cuando=csf)
        avisar(f"  · constancia de {rfc} ({csf:%d/%m/%Y})")
    if opinion and opinion[0] <= ahora and not emp.get("opinion_path"):
        cuando, analizada = opinion
        destino = paths.dir_documento(paths.TIPO_OPINION, rfc, salida_base=base) \
            / f"opinion32d_{rfc}_{cuando:%Y%m%d}.pdf"
        documentos.opinion_pdf(rfc, destino, cuando.date())
        config_store.set_opinion_descargada(rfc, str(destino), cuando=cuando)
        if analizada:
            _aplicar_opinion(rfc, destino)
        config_store.registrar_descarga(
            rfc, "fiel" if "fiel" in EMPRESAS[rfc].accesos else "ciec", "opinion",
            descripcion="Opinión de Cumplimiento 32-D", ruta=str(destino), cuando=cuando)
        avisar(f"  · opinión 32-D de {rfc} ({cuando:%d/%m/%Y}"
               + ("" if analizada else ", sin analizar") + ")")


def _aplicar_csf(rfc: str, pdf: Path) -> None:
    """Mismo camino que la descarga real (api/routers/portal.py)."""
    from ..cli import config_store
    from ..utils.csf_parser import parsear_csf

    datos = parsear_csf(pdf)
    config_store.aplicar_datos_csf(
        rfc, nombre=datos.nombre,
        regimenes=[{"clave": r.clave, "descripcion": r.descripcion} for r in datos.regimenes],
        actividades=[{"descripcion": a.descripcion, "principal": a.principal,
                      "porcentaje": a.porcentaje} for a in datos.actividades],
    )


def _aplicar_opinion(rfc: str, pdf: Path) -> None:
    from ..cli import config_store
    from ..utils.opinion_parser import parsear_opinion

    datos = parsear_opinion(pdf)
    config_store.aplicar_datos_opinion(
        rfc, sentido=datos.sentido,
        motivos=[{"titulo": m.titulo, "descripcion": m.descripcion, "detalles": m.detalles}
                 for m in datos.motivos],
    )


def _zip(comps: list) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for c in comps:
            zf.writestr(cfdi.nombre_archivo(c), cfdi.xml(c))
    return buf.getvalue()


def _descarga(rfc: str, tipo: str, anio: int, mes: int, canal: str, cuando: datetime,
              base: Path, avisar) -> None:
    """Deja una descarga de CFDI hecha: archivos en la carpeta convencional,
    solicitud "Descargada" (Web Service) y renglón en el historial."""
    from ..cli import config_store
    from ..core import paths
    from ..webservice.descarga import _extraer_zip

    desde, hasta = _rango(anio, mes)
    cuales = {"E": "emitidos", "R": "recibidos"}[tipo]
    comps = [c for c in cfdi.en_rango(rfc, desde, hasta, tipo)]
    if not comps:
        return
    if canal == "ws":
        id_sol = _id_solicitud(rfc, tipo, anio, mes)
        if config_store.get_solicitud(rfc, id_sol):
            return
        salida = paths.dir_cfdi(rfc, tipo, desde, hasta, salida_base=base)
        salida.mkdir(parents=True, exist_ok=True)
        paquete = f"{id_sol.upper()}_01"
        zip_bytes = _zip(comps)
        (salida / f"{paquete}.zip").write_bytes(zip_bytes)
        _extraer_zip(zip_bytes, salida, paquete)
        config_store.save_solicitud(
            rfc, id_sol, desde.isoformat(), hasta.isoformat(), tipo=f"CFDI · {cuales}",
            tipo_comprobante=tipo, cuando=cuando.replace(hour=max(0, cuando.hour - 1)),
        )
        config_store.update_solicitud(
            rfc, id_sol, "descargada", package_ids=[paquete],
            mensaje="Solicitud Aceptada", numero_cfdis=len(comps),
        )
        config_store.registrar_descarga(
            rfc, "ws", "cfdi", descripcion=f"Descarga WS · solicitud {id_sol[:8]}…",
            ruta=str(salida), total=len(comps), cuando=cuando,
        )
    else:
        desc = f"CFDIs {cuales} · {desde} a {hasta}"
        if any(d.get("descripcion") == desc for d in config_store.list_descargas(rfc)):
            return
        salida = paths.dir_cfdi(rfc, tipo, desde, hasta, salida_base=base)
        salida.mkdir(parents=True, exist_ok=True)
        for c in comps:
            (salida / cfdi.nombre_archivo(c)).write_bytes(cfdi.xml(c))
        config_store.registrar_descarga(
            rfc, canal, "cfdi", descripcion=desc,
            ruta=str(paths.dir_cfdi_base(rfc, salida_base=base)), total=len(comps),
            cuando=cuando,
        )
    avisar(f"  · {len(comps)} CFDIs {cuales} de {mes:02d}/{anio} de {rfc} ({canal})")


def _procesador(rfc: str, tipo: str, anio: int, mes: int, avisar) -> None:
    """Carga al buffer del procesador (como "Importar desde la empresa")."""
    from ..procesador import abrir_db, parse_cfdi
    from ..procesador.validaciones import validar_y_anotar

    desde, hasta = _rango(anio, mes)
    parseados = []
    for c in cfdi.en_rango(rfc, desde, hasta, tipo):
        d = parse_cfdi(cfdi.xml(c), file_name=cfdi.nombre_archivo(c))
        validar_y_anotar(d)
        parseados.append(d)
    if parseados:
        r = abrir_db().agregar(parseados, mi_rfc=rfc, direccion_fija=tipo)
        if r.get("agregados"):
            avisar(f"  · procesador: {r['agregados']} CFDIs de {rfc} ({mes:02d}/{anio})")


def sembrar(ahora: Optional[datetime] = None, excluir: Iterable[str] = (),
            con_septiembre: bool = False, historial_cfdi: bool = True,
            avisar: Callable[[str], None] = print) -> list:
    """Siembra la cuenta de grabación. Devuelve los RFC sembrados.

    `historial_cfdi=False` omite las descargas de meses anteriores (los XML en
    disco); `con_septiembre=True` deja ya hecha la descarga de la pieza 1."""
    if not activo():
        raise ModoApagado(
            "La siembra solo corre con el modo de grabación prendido "
            "(SAT_DM_MODO_GRABACION=1)."
        )
    from ..cli import config_store

    ahora = ahora or datetime.now()
    excluir = {r.strip().upper() for r in excluir}
    base = Path(config_store.asegurar_descargas_dir())
    avisar(f"Perfil: {config_store.get_config_dir()}")
    avisar(f"Descargas: {base}")

    tmp = Path(tempfile.mkdtemp(prefix="todoconta-grabacion-"))
    sembradas = []
    try:
        existentes = {e["rfc"]: e for e in config_store.list_empresas()}
        avisar("Empresas:")
        for rfc, emp in EMPRESAS.items():
            if rfc in excluir:
                continue
            _alta(emp, existentes, tmp, ahora.date(), avisar)
            sembradas.append(rfc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    avisar("Documentos:")
    for rfc in sembradas:
        _documentos(rfc, base, ahora, avisar)

    avisar("Descargas e historial:")
    planes = (list(DESCARGAS) if historial_cfdi else []) \
        + ([SEPTIEMBRE_EL_ROBLE] if con_septiembre else [])
    for rfc, tipo, anio, mes, canal, cuando in planes:
        if rfc in sembradas and cuando <= ahora:
            _descarga(rfc, tipo, anio, mes, canal, cuando, base, avisar)

    for rfc, tipo, anio, mes in PROCESADOR:
        if rfc in sembradas and historial_cfdi:
            _procesador(rfc, tipo, anio, mes, avisar)

    if EL_ROBLE in sembradas or EL_ROBLE in existentes:
        config_store.set_default(EL_ROBLE)
    avisar("Listo. Abre (o recarga) la app para ver las empresas.")
    return sembradas


def limpiar(avisar: Callable[[str], None] = print) -> None:
    """Quita TODO lo de las empresas de demo (y solo eso): catálogo, credenciales,
    solicitudes, historial, buffers del procesador y carpetas de descargas."""
    from ..cli import config_store
    from ..core import paths
    from ..procesador import abrir_db

    base = Path(config_store.get_descargas_dir())
    catalogo = config_store.load_empresas()["empresas"]
    db = abrir_db()
    for rfc in sorted(RFCS_DEMO):
        if rfc in catalogo:
            config_store.remove_empresa(rfc)
            avisar(f"  - {rfc}")
        db.borrar(rfc)
        shutil.rmtree(config_store.EFIRMA_DIR / rfc, ignore_errors=True)
        for archivo in (config_store._solicitudes_path(rfc), config_store._historial_path(rfc)):
            archivo.unlink(missing_ok=True)
        for carpeta in (paths.dir_cfdi_base(rfc, salida_base=base),
                        paths.dir_documento(paths.TIPO_CONSTANCIA, rfc, salida_base=base),
                        paths.dir_documento(paths.TIPO_OPINION, rfc, salida_base=base),
                        base / "fiel" / rfc):
            shutil.rmtree(carpeta, ignore_errors=True)
    (config_store.get_config_dir() / "grabacion" / "solicitudes.json").unlink(missing_ok=True)
    avisar("Listo: empresas de demo quitadas.")


def carpeta_xml(destino: Path, rfc: str = PANADERIA, desde: tuple = (2022, 1),
                hasta: tuple = (2025, 12), uno_de_cada: int = 4,
                duplicados: int = 60) -> int:
    """Carpeta revuelta de XML de años anteriores, con duplicados, para el
    Organizador (pieza 5, "XML 2022 a 2025"). Devuelve cuántos archivos dejó."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    escritos = []
    anio, mes = desde
    while (anio, mes) <= hasta:
        for i, c in enumerate(cfdi.comprobantes(rfc, anio, mes)):
            if c.tipo == "N" or i % uno_de_cada:
                continue
            ruta = destino / cfdi.nombre_archivo(c)
            ruta.write_bytes(cfdi.xml(c))
            escritos.append(ruta)
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
    paso = max(1, len(escritos) // max(1, duplicados))
    for n, ruta in enumerate(escritos[::paso][:duplicados]):
        nombre = f"{ruta.stem} (1).xml" if n % 2 else f"Copia de {ruta.name}"
        shutil.copy2(ruta, destino / nombre)
    return len(escritos) + min(duplicados, len(escritos[::paso]))
