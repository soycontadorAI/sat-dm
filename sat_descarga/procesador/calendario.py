"""
Cuadro de control local: estado de la descarga por empresa, día y dirección.

Es la tabla `descarga_dias` (migración 011) del `procesador.db`, la base de la
pantalla del calendario (docs/producto/descarga-programada.md, fase 2). Un día
sin fila es `pendiente`; la tabla solo guarda lo que ya pasó algo.

Se alimenta de tres fuentes:

- las solicitudes al Web Service (`sincronizar` lee el catálogo de
  `config_store` y traduce su estado a estado del día);
- las descargas del portal (CIEC / e.firma), que marcan su rango con `marcar`;
- el propio índice de CFDIs: un día con CFDIs en `cfdis` es al menos
  `provisional`, lo haya bajado quien lo haya bajado.

Solo el cierre mensual (fase 4, otro PR) escribe `consolidado` y `diferencia`
(con `marcar(..., forzar=True)`); aquí nada los degrada.

La dirección se cuenta como la devuelve el SAT: E = CFDIs cuyo emisor es la
empresa, R = los que la tienen de receptor (una autofactura cuenta en las
dos). Los cancelados no cuentan.
"""

from __future__ import annotations

import logging
import zlib
from datetime import date, datetime, timedelta, timezone
from typing import Iterator, Optional

from ..cli import config_store
from .db import abrir_db, normalizar_mi_rfc

logger = logging.getLogger(__name__)

ESTADOS = ("pendiente", "en_proceso", "provisional", "consolidado", "diferencia", "error")
DIRECCIONES = ("E", "R")

# Máximo de CFDIs que devuelve `dia()` en su lista.
LIMITE_CFDIS_DIA = 200

# Columnas que definen el estado de una fila (todo menos `actualizado_en`).
_COLS = ("estado", "total_bd", "total_sat", "ultima_solicitud_id",
         "error_codigo", "error_mensaje", "intentos")

_CONGELADOS = ("consolidado", "diferencia")

# Condiciones de pertenencia (la columna `mi_rfc` ya viene normalizada).
_ES_EMISOR = "UPPER(TRIM(COALESCE(emisor_rfc,''))) = ?"
_ES_RECEPTOR = "UPPER(TRIM(COALESCE(receptor_rfc,''))) = ?"
_NO_CANCELADO = "COALESCE(estado_sat,'') != 'Cancelado'"
_FECHA_BIEN = "substr(fecha,1,10) GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'"


# ---------------------------------------------------------------------------
# Fecha de hoy
# ---------------------------------------------------------------------------


# Hora de la Ciudad de México: UTC-6 fijo (ya no hay horario de verano). Fija
# y no `ZoneInfo`, que en Windows sin el paquete `tzdata` no existe.
ZONA_MX = timezone(timedelta(hours=-6), "America/Mexico_City")


def ahora_mx() -> datetime:
    return datetime.now(ZONA_MX)


def hoy() -> date:
    """Fecha de hoy en la Ciudad de México, igual en escritorio y en la nube (el
    contenedor corre en UTC): así el calendario y la descarga automática cuentan
    el mismo día que el SAT."""
    return ahora_mx().date()


def _ahora() -> str:
    # Con microsegundos: `sincronizar` compara contra su propio inicio.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


# ---------------------------------------------------------------------------
# Regla de transición
# ---------------------------------------------------------------------------


def _siguiente(actual: Optional[str], nuevo: str) -> Optional[str]:
    """Estado que resulta de aplicar `nuevo` sobre `actual` (None = sin fila).

    - sin fila / pendiente / en_proceso / error: toma `nuevo`;
    - provisional: solo sube a consolidado o diferencia;
    - consolidado / diferencia: no cambian.
    `pendiente` nunca se aplica como nuevo (devuelve `actual`; None = sigue
    sin fila).
    """
    if nuevo == "pendiente":
        return actual
    if actual in (None, "pendiente", "en_proceso", "error"):
        return nuevo
    if actual == "provisional":
        return nuevo if nuevo in _CONGELADOS else "provisional"
    return actual


# ---------------------------------------------------------------------------
# Conteo del índice
# ---------------------------------------------------------------------------


def _siguiente_dia(fecha: str) -> str:
    return (date.fromisoformat(fecha) + timedelta(days=1)).isoformat()


def _conteos(mi_rfc: str, desde: str = "0000-01-01", hasta: str = "9999-12-31"
             ) -> dict[tuple[str, str], int]:
    """`{(fecha, direccion): n}` de CFDIs en el índice, solo n > 0, para los
    días `desde..hasta` (ISO, inclusive). Un solo GROUP BY."""
    limite = "9999-12-31" if hasta >= "9999-12-31" else _siguiente_dia(hasta)
    db = abrir_db()
    with db.cursor() as cur:
        filas = cur.execute(
            f"""
            SELECT substr(fecha,1,10) AS dia,
                   SUM(CASE WHEN {_ES_EMISOR} THEN 1 ELSE 0 END) AS e,
                   SUM(CASE WHEN {_ES_RECEPTOR} THEN 1 ELSE 0 END) AS r
            FROM cfdis
            WHERE mi_rfc = ? AND fecha >= ? AND fecha < ?
              AND {_NO_CANCELADO} AND {_FECHA_BIEN}
            GROUP BY dia
            """,
            (mi_rfc, mi_rfc, mi_rfc, desde, limite),
        ).fetchall()
    out: dict[tuple[str, str], int] = {}
    for dia, e, r in filas:
        try:
            date.fromisoformat(dia)
        except ValueError:
            continue
        if e:
            out[(dia, "E")] = int(e)
        if r:
            out[(dia, "R")] = int(r)
    return out


# ---------------------------------------------------------------------------
# Lectura / escritura de filas
# ---------------------------------------------------------------------------


def _validar(estado: Optional[str] = None, direccion: Optional[str] = None) -> None:
    if estado is not None and estado not in ESTADOS:
        raise ValueError(f"Estado inválido: {estado!r}")
    if direccion is not None and direccion not in DIRECCIONES:
        raise ValueError(f"Dirección inválida: {direccion!r}")


def filas(mi_rfc: str, desde: date, hasta: date) -> dict[tuple[str, str], dict]:
    """Filas guardadas de `desde` a `hasta` (inclusive): `{(fecha, dir): fila}`."""
    mi_rfc = normalizar_mi_rfc(mi_rfc)
    db = abrir_db()
    with db.cursor() as cur:
        rows = cur.execute(
            "SELECT * FROM descarga_dias WHERE mi_rfc = ? AND fecha BETWEEN ? AND ?",
            (mi_rfc, desde.isoformat(), hasta.isoformat()),
        ).fetchall()
    return {(r["fecha"], r["direccion"]): dict(r) for r in rows}


def _aplicar(mi_rfc: str, items: list[dict]) -> int:
    """Aplica la regla de transición a cada item y escribe solo lo que cambia.

    Cada item: fecha (ISO), direccion, estado, bd (total del índice) y,
    opcionales, forzar, solicitud_id, error_codigo, error_mensaje, total_sat,
    intentos. Devuelve las filas insertadas o modificadas."""
    if not items:
        return 0
    db = abrir_db()
    fmin = min(i["fecha"] for i in items)
    fmax = max(i["fecha"] for i in items)
    ahora = _ahora()
    cambiadas = 0
    with db.transaccion() as conn:
        actuales = {
            (r["fecha"], r["direccion"]): dict(r)
            for r in conn.execute(
                "SELECT * FROM descarga_dias WHERE mi_rfc = ? AND fecha BETWEEN ? AND ?",
                (mi_rfc, fmin, fmax),
            )
        }
        for it in items:
            clave = (it["fecha"], it["direccion"])
            act = actuales.get(clave)
            act_estado = act["estado"] if act else None
            forzar = bool(it.get("forzar"))
            destino = it["estado"] if forzar else _siguiente(act_estado, it["estado"])
            if destino is None:  # pendiente y sin fila: nada que guardar
                continue
            nuevo = dict(act) if act else {
                "estado": destino, "total_bd": 0, "total_sat": None,
                "ultima_solicitud_id": None, "error_codigo": None,
                "error_mensaje": None, "intentos": 0,
            }
            nuevo["total_bd"] = it["bd"]
            solo_bd = not forzar and (
                act_estado in _CONGELADOS or it["estado"] == "pendiente"
            )
            if not solo_bd:
                nuevo["estado"] = destino
                if it.get("solicitud_id") is not None:
                    nuevo["ultima_solicitud_id"] = it["solicitud_id"]
                if it.get("total_sat") is not None:
                    nuevo["total_sat"] = it["total_sat"]
                if it.get("intentos") is not None:
                    nuevo["intentos"] = it["intentos"]
                elif destino in ("provisional", "consolidado"):
                    nuevo["intentos"] = 0  # el día ya salió: los reintentos quedan atrás
                if destino in ("error", "diferencia"):
                    # En una diferencia el "mensaje" es el detalle (qué falta o sobra).
                    nuevo["error_codigo"] = it.get("error_codigo")
                    nuevo["error_mensaje"] = it.get("error_mensaje")
                else:
                    nuevo["error_codigo"] = None
                    nuevo["error_mensaje"] = None
            if act is not None and all(nuevo[c] == act[c] for c in _COLS):
                continue
            conn.execute(
                """
                INSERT INTO descarga_dias (
                    mi_rfc, fecha, direccion, estado, total_bd, total_sat,
                    ultima_solicitud_id, error_codigo, error_mensaje, intentos,
                    actualizado_en
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mi_rfc, fecha, direccion) DO UPDATE SET
                    estado = excluded.estado,
                    total_bd = excluded.total_bd,
                    total_sat = excluded.total_sat,
                    ultima_solicitud_id = excluded.ultima_solicitud_id,
                    error_codigo = excluded.error_codigo,
                    error_mensaje = excluded.error_mensaje,
                    intentos = excluded.intentos,
                    actualizado_en = excluded.actualizado_en
                """,
                (mi_rfc, it["fecha"], it["direccion"], nuevo["estado"],
                 nuevo["total_bd"], nuevo["total_sat"], nuevo["ultima_solicitud_id"],
                 nuevo["error_codigo"], nuevo["error_mensaje"], nuevo["intentos"], ahora),
            )
            cambiadas += 1
    return cambiadas


def _dias(desde: date, hasta: date) -> list[date]:
    """Días de `desde` a `hasta` recortados a hoy (vacío si no queda ninguno)."""
    hasta = min(hasta, hoy())
    if desde > hasta:
        return []
    return [desde + timedelta(days=n) for n in range((hasta - desde).days + 1)]


def rangos_contiguos(dias: list[date], maximo: int) -> list[tuple[date, date]]:
    """Rangos contiguos que cubren `dias`; si son más de `maximo`, se juntan los
    más cercanos (pedir de más unos días es más barato que muchas solicitudes)."""
    if not dias:
        return []
    dias = sorted(set(dias))
    rangos = [[dias[0], dias[0]]]
    for d in dias[1:]:
        if d - rangos[-1][1] == timedelta(days=1):
            rangos[-1][1] = d
        else:
            rangos.append([d, d])
    while len(rangos) > maximo:
        i = min(range(len(rangos) - 1), key=lambda k: rangos[k + 1][0] - rangos[k][1])
        rangos[i][1] = rangos[i + 1][1]
        del rangos[i + 1]
    return [(a, b) for a, b in rangos]


def marcar(
    mi_rfc: str,
    desde: date,
    hasta: date,
    direccion: str,
    estado: str,
    *,
    solicitud_id: Optional[str] = None,
    error_codigo: Optional[str] = None,
    error_mensaje: Optional[str] = None,
    total_sat: Optional[int] = None,
    intentos: Optional[int] = None,
    forzar: bool = False,
) -> int:
    """Marca los días `desde..hasta` (recortados a hoy) de una dirección con
    `estado`, respetando la regla de transición (`forzar=True` la ignora: lo
    usa el cierre mensual). Refresca `total_bd` de esos días. Devuelve las
    filas cambiadas."""
    mi_rfc = normalizar_mi_rfc(mi_rfc)
    _validar(estado, direccion)
    dias = _dias(desde, hasta)
    if not dias:
        return 0
    conteos = _conteos(mi_rfc, dias[0].isoformat(), dias[-1].isoformat())
    items = []
    for d in dias:
        f = d.isoformat()
        items.append({
            "fecha": f, "direccion": direccion, "estado": estado, "forzar": forzar,
            "bd": conteos.get((f, direccion), 0), "solicitud_id": solicitud_id,
            "error_codigo": error_codigo, "error_mensaje": error_mensaje,
            "total_sat": total_sat, "intentos": intentos,
        })
    return _aplicar(mi_rfc, items)


def cerrar_dias(mi_rfc: str, resultados: dict) -> int:
    """Escribe el resultado del cierre mensual: `{(fecha_iso, dir): (estado,
    total_sat, mensaje)}` con estado consolidado o diferencia. Es la única vía
    a esos dos estados (con `forzar`); refresca `total_bd` en la misma pasada."""
    mi_rfc = normalizar_mi_rfc(mi_rfc)
    if not resultados:
        return 0
    fechas = sorted(f for f, _ in resultados)
    conteos = _conteos(mi_rfc, fechas[0], fechas[-1])
    items = []
    for (fecha, direccion), (estado, total_sat, mensaje) in resultados.items():
        _validar(estado, direccion)
        if estado not in _CONGELADOS:
            raise ValueError(f"El cierre solo escribe consolidado o diferencia, no {estado!r}")
        items.append({
            "fecha": fecha, "direccion": direccion, "estado": estado, "forzar": True,
            "bd": conteos.get((fecha, direccion), 0), "total_sat": total_sat,
            "error_codigo": None, "error_mensaje": mensaje, "intentos": 0,
        })
    return _aplicar(mi_rfc, items)


def uuids_por_dia(mi_rfc: str, desde: date, hasta: date,
                  mayusculas: bool = True) -> dict[tuple[str, str], set[str]]:
    """UUID del índice por (día, dirección), con la regla del conteo: E si la
    empresa es emisora, R si es receptora, sin cancelados. En mayúsculas, o con
    `mayusculas=False` tal como se guardó en `cfdis`."""
    mi_rfc = normalizar_mi_rfc(mi_rfc)
    out: dict[tuple[str, str], set[str]] = {}
    db = abrir_db()
    with db.cursor() as cur:
        filas_ = cur.execute(
            f"""
            SELECT {"UPPER(uuid)" if mayusculas else "uuid"}, substr(fecha,1,10), {_ES_EMISOR}, {_ES_RECEPTOR}
            FROM cfdis
            WHERE mi_rfc = ? AND fecha >= ? AND fecha < ? AND {_NO_CANCELADO} AND {_FECHA_BIEN}
            """,
            (mi_rfc, mi_rfc, mi_rfc, desde.isoformat(), _siguiente_dia(hasta.isoformat())),
        ).fetchall()
    for uuid, dia, es_e, es_r in filas_:
        if es_e:
            out.setdefault((dia, "E"), set()).add(uuid)
        if es_r:
            out.setdefault((dia, "R"), set()).add(uuid)
    return out


def aplicar_cancelaciones(mi_rfc: str, canceladas: dict) -> list[tuple[str, str]]:
    """Marca como cancelados (`estado_sat`, `fecha_cancelacion`) los CFDI de la
    empresa cuyo UUID está en `canceladas` ({uuid: fecha_cancelacion}) y aún no lo
    estaban. Devuelve `[(uuid, fecha_emision)]` de los recién cancelados."""
    mi_rfc = normalizar_mi_rfc(mi_rfc)
    if not canceladas:
        return []
    db = abrir_db()
    ahora = _ahora()
    nuevas: list[tuple[str, str]] = []
    with db.transaccion() as conn:
        claves = {u.upper(): f for u, f in canceladas.items()}
        lista = list(claves)
        for i in range(0, len(lista), 500):
            trozo = lista[i:i + 500]
            marcas = ",".join("?" * len(trozo))
            for uuid, fecha in conn.execute(
                f"SELECT uuid, fecha FROM cfdis WHERE mi_rfc = ? AND UPPER(uuid) IN ({marcas})"
                f" AND {_NO_CANCELADO}",
                (mi_rfc, *trozo),
            ).fetchall():
                nuevas.append((uuid, fecha or ""))
        for uuid, _fecha in nuevas:
            conn.execute(
                "UPDATE cfdis SET estado_sat = 'Cancelado', fecha_cancelacion = ?, validado_en = ?"
                " WHERE mi_rfc = ? AND uuid = ?",
                (claves.get(uuid.upper()) or None, ahora, mi_rfc, uuid),
            )
    return nuevas


# ---------------------------------------------------------------------------
# Sincronización con las solicitudes y el índice
# ---------------------------------------------------------------------------


def _parse_fecha(valor) -> Optional[date]:
    try:
        return date.fromisoformat(str(valor)[:10])
    except (ValueError, TypeError):
        return None


def _direccion_de(sol: dict) -> Optional[str]:
    d = (sol.get("tipo_comprobante") or "").strip().upper()
    if d in DIRECCIONES:
        return d
    texto = (sol.get("tipo") or "").lower()
    if "emitidos" in texto:
        return "E"
    if "recibidos" in texto:
        return "R"
    return None


def _es_metadata(sol: dict) -> bool:
    return config_store.es_metadata(sol)


def _candidato(sol: dict) -> Optional[tuple[str, Optional[str], Optional[str]]]:
    """`(estado, error_codigo, error_mensaje)` que una solicitud da a sus días.

    El resultado de la solicitud viene en `codigo_estado_solicitud`
    (CodigoEstadoSolicitud de VerificaSolicitud): un 5004 llega con
    EstadoSolicitud=5 y CodEstatus=5000, y significa "sin CFDI en el periodo"."""
    estado = str(sol.get("estado") or "").strip()
    if not estado:
        return None
    mensaje = sol.get("mensaje")
    codigo = str(sol.get("codigo_estado_solicitud") or "")
    if estado == "descargada":
        return ("provisional", None, None)
    if estado == "5" and (
        codigo == "5004"  # el CodEstatus 5004 es otra cosa: "no se encontró la solicitud"
        or "No se encontró la información" in (mensaje or "")
        # Guardadas antes de que se guardara el código: con el mensaje genérico
        # de la verificación, el rechazo casi siempre es el 5004 (el 5003, tope
        # de registros, es raro). El cierre mensual lo verifica contra el SAT.
        or (not codigo and (mensaje or "").strip() in ("", "Solicitud Aceptada"))
    ):
        return ("provisional", None, None)  # 5004: sin CFDI ese día, cuenta como 0
    if estado in ("solicitada", "1", "2", "3"):
        return ("en_proceso", None, None)
    # El código más útil: el de la solicitud, luego el de la verificación (5000 no dice nada).
    error = next((c for c in (codigo, str(sol.get("cod_estatus") or "")) if c and c != "5000"), estado)
    return ("error", error, mensaje)


def _solicitudes_cfdi(solicitudes: list[dict]) -> list[dict]:
    """Solicitudes de CFDI con dirección y fechas válidas:
    `{id, direccion, desde, hasta, ts, cand}`."""
    out = []
    for sol in solicitudes:
        if _es_metadata(sol):
            continue
        direccion = _direccion_de(sol)
        desde = _parse_fecha(sol.get("fecha_inicio"))
        hasta = _parse_fecha(sol.get("fecha_fin"))
        cand = _candidato(sol)
        if not (direccion and desde and hasta and cand) or desde > hasta:
            continue
        out.append({
            "id": sol.get("id_solicitud"), "direccion": direccion,
            "desde": desde, "hasta": hasta,
            "ts": str(sol.get("timestamp") or ""), "cand": cand,
        })
    return out


def sincronizar(mi_rfc: str, desde: Optional[date] = None,
                hasta: Optional[date] = None) -> dict:
    """Pone al día `descarga_dias` con las solicitudes de CFDI del catálogo y
    el índice. Idempotente: solo escribe las filas que cambian. Nunca borra.
    Con `desde`/`hasta` solo toca esos días (la pantalla sincroniza el año que
    muestra). Devuelve `{"cambiadas": n}`."""
    mi_rfc = normalizar_mi_rfc(mi_rfc)
    tope = hoy()
    ini = desde or date.min
    fin = min(hasta or date.max, tope)
    inicio = _ahora()
    catalogo = config_store.list_solicitudes(mi_rfc)
    ids_catalogo = {s.get("id_solicitud") for s in catalogo}

    # 1) Lo que dicen las solicitudes, por (día, dirección).
    por_dia: dict[tuple[str, str], dict] = {}
    for s in _solicitudes_cfdi(catalogo):
        estado, codigo, mensaje = s["cand"]
        for d in _dias(max(s["desde"], ini), min(s["hasta"], fin)):
            info = por_dia.setdefault((d.isoformat(), s["direccion"]), {
                "prov": False, "proc": False, "err": None, "n_err": 0, "ultima": None,
            })
            if info["ultima"] is None or s["ts"] >= info["ultima"][0]:
                info["ultima"] = (s["ts"], s["id"])
            if estado == "provisional":
                info["prov"] = True
            elif estado == "en_proceso":
                info["proc"] = True
            else:
                info["n_err"] += 1
                if info["err"] is None or s["ts"] >= info["err"][0]:
                    info["err"] = (s["ts"], codigo, mensaje)

    # 2) Índice y filas actuales.
    if ini > fin:
        return {"cambiadas": 0}
    conteos = _conteos(mi_rfc, ini.isoformat(), fin.isoformat())
    existentes = filas(mi_rfc, ini, fin)

    items = []
    for clave in set(por_dia) | set(conteos) | set(existentes):
        fecha, direccion = clave
        info = por_dia.get(clave)
        bd = conteos.get(clave, 0)
        estado = codigo = mensaje = None
        solicitud_id = intentos = None
        if info:
            solicitud_id = info["ultima"][1]
            if info["prov"]:
                estado = "provisional"
            elif info["proc"]:
                estado = "en_proceso"
            elif info["err"]:
                estado = "error"
                _, codigo, mensaje = info["err"]
                intentos = info["n_err"]
        if estado in (None, "error") and bd > 0:
            estado, codigo, mensaje, intentos = "provisional", None, None, None
        act = existentes.get(clave)
        if (estado is None and act and act["estado"] in ("en_proceso", "error")
                and act.get("ultima_solicitud_id")
                and act["ultima_solicitud_id"] not in ids_catalogo
                and act["actualizado_en"] < inicio):
            # Lo puso así una solicitud que ya no está en el catálogo (el usuario
            # la borró): sin ella el día vuelve a "por descargar". Si la fila se
            # tocó después de leer el catálogo, es de una solicitud nueva: se deja.
            items.append({"fecha": fecha, "direccion": direccion, "bd": bd,
                          "estado": "pendiente", "forzar": True})
            continue
        items.append({
            "fecha": fecha, "direccion": direccion, "bd": bd,
            "estado": estado or "pendiente", "solicitud_id": solicitud_id,
            "error_codigo": codigo, "error_mensaje": mensaje, "intentos": intentos,
        })
    return {"cambiadas": _aplicar(mi_rfc, items)}


# ---------------------------------------------------------------------------
# Lectura para la API
# ---------------------------------------------------------------------------


def _entrada(fila: dict) -> dict:
    """Fila de `descarga_dias` → entrada del contrato JSON."""
    out = {"estado": fila["estado"], "total_bd": fila["total_bd"]}
    for campo in ("total_sat", "error_codigo", "error_mensaje"):
        if fila.get(campo) is not None:
            out[campo] = fila[campo]
    if (fila.get("intentos") or 0) > 0:
        out["intentos"] = fila["intentos"]
    out["actualizado_en"] = fila["actualizado_en"]
    return out


def anio(mi_rfc: str, anio: int) -> dict:
    """Calendario del año: días con algo, resumen por estado y años con datos."""
    mi_rfc = normalizar_mi_rfc(mi_rfc)
    hoy_ = hoy()
    ini, fin = date(anio, 1, 1), date(anio, 12, 31)
    guardadas = filas(mi_rfc, ini, fin)

    dias: dict[str, dict] = {}
    for (fecha, direccion), fila in sorted(guardadas.items()):
        if fila["estado"] != "pendiente":
            dias.setdefault(fecha, {})[direccion] = _entrada(fila)

    resumen = {d: {e: 0 for e in ESTADOS} for d in DIRECCIONES}
    for d in _dias(ini, fin):
        for direccion in DIRECCIONES:
            fila = guardadas.get((d.isoformat(), direccion))
            resumen[direccion][fila["estado"] if fila else "pendiente"] += 1

    # Años para el selector: con filas, con CFDI en el índice o con solicitudes
    # (la pantalla sincroniza un año a la vez, así que no todos tienen filas aún).
    db = abrir_db()
    with db.cursor() as cur:
        anios_con_datos = {int(r[0]) for r in cur.execute(
            "SELECT DISTINCT substr(fecha,1,4) FROM descarga_dias WHERE mi_rfc = ?"
            " UNION SELECT DISTINCT substr(fecha,1,4) FROM cfdis WHERE mi_rfc = ?",
            (mi_rfc, mi_rfc),
        ) if r[0] and str(r[0]).isdigit()}
    for s in _solicitudes_cfdi(config_store.list_solicitudes(mi_rfc)):
        anios_con_datos.update(range(s["desde"].year, min(s["hasta"], hoy_).year + 1))
    anios_con_datos = {a for a in anios_con_datos if 1990 <= a <= hoy_.year}
    anios_con_datos.add(hoy_.year)
    return {
        "rfc": mi_rfc, "anio": anio, "hoy": hoy_.isoformat(),
        "anios": sorted(anios_con_datos), "dias": dias, "resumen": resumen,
    }


def dia(mi_rfc: str, fecha: date) -> dict:
    """Detalle de un día: estado E/R, solicitudes que lo cubren y CFDIs."""
    mi_rfc = normalizar_mi_rfc(mi_rfc)
    f = fecha.isoformat()
    guardadas = filas(mi_rfc, fecha, fecha)
    conteos = _conteos(mi_rfc, f, f)

    out: dict = {"rfc": mi_rfc, "fecha": f}
    for direccion in DIRECCIONES:
        fila = guardadas.get((f, direccion))
        out[direccion] = _entrada(fila) if fila else {
            "estado": "pendiente", "total_bd": conteos.get((f, direccion), 0),
        }

    sols = []
    for sol in config_store.list_solicitudes(mi_rfc):
        if _es_metadata(sol):
            continue
        desde, hasta = _parse_fecha(sol.get("fecha_inicio")), _parse_fecha(sol.get("fecha_fin"))
        if not (desde and hasta and desde <= fecha <= hasta):
            continue
        sols.append({
            "id_solicitud": sol.get("id_solicitud"),
            "tipo_comprobante": _direccion_de(sol),
            "fecha_inicio": sol.get("fecha_inicio"),
            "fecha_fin": sol.get("fecha_fin"),
            "estado": sol.get("estado"),
            "mensaje": sol.get("mensaje"),
            "numero_cfdis": sol.get("numero_cfdis"),
            "timestamp": sol.get("timestamp"),
        })
    sols.sort(key=lambda s: str(s["timestamp"] or ""), reverse=True)
    out["solicitudes"] = sols

    # Misma regla que el conteo: una autofactura sale en emitidos Y en recibidos,
    # así la lista cuadra con las tarjetas y con la celda (E + R).
    base = f"mi_rfc = ? AND fecha >= ? AND fecha < ? AND {_NO_CANCELADO}"
    columnas = ("tipo, serie, folio, fecha, emisor_rfc, emisor_nombre,"
                " receptor_rfc, receptor_nombre, total, moneda, estado_sat")
    union = (f"SELECT uuid, 'E' AS direccion, {columnas} FROM cfdis WHERE {base} AND {_ES_EMISOR}"
             " UNION ALL "
             f"SELECT uuid, 'R' AS direccion, {columnas} FROM cfdis WHERE {base} AND {_ES_RECEPTOR}")
    params = (mi_rfc, f, _siguiente_dia(f), mi_rfc) * 2
    db = abrir_db()
    with db.cursor() as cur:
        total = cur.execute(f"SELECT COUNT(*) FROM ({union})", params).fetchone()[0]
        rows = cur.execute(
            f"SELECT * FROM ({union}) ORDER BY direccion, fecha, uuid LIMIT ?",
            params + (LIMITE_CFDIS_DIA,),
        ).fetchall()
    out["cfdis"] = [dict(r) for r in rows]
    out["cfdis_total"] = int(total)
    return out


def xml_del_mes(
    mi_rfc: str, anio: int, mes: int, direccion: Optional[str] = None,
) -> Iterator[tuple[str, Optional[bytes]]]:
    """`(uuid, xml | None)` de los CFDIs del mes (regla E/R de arriba; sin
    `direccion` van ambos, cada UUID una vez). `None` = el CFDI está en el
    índice pero sin XML guardado. Lee los documentos por lotes para no cargar
    todo en memoria ni retener el candado de la DB."""
    mi_rfc = normalizar_mi_rfc(mi_rfc)
    if direccion is not None:
        _validar(direccion=direccion)
    ini = date(anio, mes, 1)
    fin = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
    if direccion == "E":
        lado, extra = f"({_ES_EMISOR})", (mi_rfc,)
    elif direccion == "R":
        lado, extra = f"({_ES_RECEPTOR})", (mi_rfc,)
    else:
        lado, extra = f"({_ES_EMISOR} OR {_ES_RECEPTOR})", (mi_rfc, mi_rfc)

    db = abrir_db()
    with db.cursor() as cur:
        uuids = [r[0] for r in cur.execute(
            f"SELECT uuid FROM cfdis WHERE mi_rfc = ? AND fecha >= ? AND fecha < ?"
            f" AND {_NO_CANCELADO} AND {lado} ORDER BY fecha, uuid",
            (mi_rfc, ini.isoformat(), fin.isoformat()) + extra,
        )]
    lote = 200
    for i in range(0, len(uuids), lote):
        trozo = uuids[i:i + lote]
        marcas = ",".join("?" * len(trozo))
        with db.cursor() as cur:
            docs = {r[0]: r[1] for r in cur.execute(
                f"SELECT uuid, xml_zlib FROM cfdi_documentos"
                f" WHERE mi_rfc = ? AND uuid IN ({marcas})",
                (mi_rfc, *trozo),
            )}
        for u in trozo:
            blob = docs.get(u)
            yield u, (zlib.decompress(blob) if blob is not None else None)
