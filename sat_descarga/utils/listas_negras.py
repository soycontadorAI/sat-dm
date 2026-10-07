"""
Validación de RFCs contra las listas negras del SAT (Art. 69 y 69-B del CFF).

Consume el endpoint Next.js de todoconta-apps que materializa las listas en
Supabase (un cron mensual el día 5 las descarga del SAT y Datos Abiertos).
La fuente de verdad vive en un solo lugar: el agente Python NO replica el
cron, solo consulta.

- EFOS (Empresa que Factura Operaciones Simuladas) = RFC con `situacion`
  "Definitivo" o "Presunto" en la lista 69-B.
- EDOS (Empresa que Deduce Operaciones Simuladas) = receptor de un CFDI cuyo
  emisor es EFOS. Se detecta cruzando los emisores del buffer del procesador
  contra el lookup batch.

Requiere sesión iniciada en la app desktop (Bearer guardado en el keyring por
`license_client`); sin sesión, las funciones de red levantan `RuntimeError`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional

import requests

from .. import demo
from ..api import license_client

logger = logging.getLogger(__name__)


# El endpoint Next acepta hasta 200 RFCs por POST; loteamos internamente.
_BATCH_SIZE = 200
_TIMEOUT = 30  # 200 RFCs * 2 queries en PL/pgSQL puede tardar segundos


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


@dataclass
class MatchListaNegra:
    """Resultado de la consulta de un RFC contra las dos listas del SAT."""
    rfc: str
    en_lista_69b: bool
    situacion_69b: Optional[str]            # Definitivo | Presunto | Desvirtuado | Sentencia Favorable
    fecha_publicacion_69b: Optional[str]
    en_lista_69: bool
    supuestos_69: list[str] = field(default_factory=list)
    risk_level: str = "limpio"              # "alto" | "medio" | "limpio"
    error: Optional[str] = None

    @property
    def es_efos(self) -> bool:
        """EFOS = en 69-B con situación Definitivo o Presunto (sin aclaración)."""
        return self.situacion_69b in ("Definitivo", "Presunto")


@dataclass
class ListasMetadata:
    """Cuándo fue la última actualización del cron por lista. Lo muestra la UI."""
    lista_69b_updated_at: Optional[str]
    lista_69_updated_at: Optional[str]
    record_count_69b: Optional[int] = None
    record_count_69: Optional[int] = None


# ---------------------------------------------------------------------------
# Cliente HTTP hacia todoconta-apps
# ---------------------------------------------------------------------------


def _bearer_headers() -> dict[str, str]:
    """Construye los headers con el Bearer de la sesión activa.

    Levanta RuntimeError si no hay sesión — la UI traduce eso a un CTA
    "Inicia sesión para validar listas negras".
    """
    session = license_client.load_session()
    if session is None:
        raise RuntimeError(
            "Sesión requerida. Inicia sesión en la app para validar listas negras."
        )
    return {
        "Authorization": f"Bearer {session.access_token}",
        "Content-Type": "application/json",
    }


def _parse_match(rfc: str, payload: dict) -> MatchListaNegra:
    """Mapea una entrada del response del endpoint Next a `MatchListaNegra`.

    El endpoint devuelve `{rfc, lista_69b: [...], lista_69: [...], risk_level}`.
    Cada elemento de las listas puede tener varios registros (p. ej. presunto +
    sentencia para el mismo RFC); nos quedamos con el primero — es el más
    reciente porque PL/pgSQL ordena por `fecha_publicacion DESC`.
    """
    items_69b = payload.get("lista_69b") or []
    items_69 = payload.get("lista_69") or []

    situacion = items_69b[0].get("situacion") if items_69b else None
    fecha_pub = items_69b[0].get("fecha_publicacion") if items_69b else None

    # `supuestos_69` puede repetirse si el RFC tiene varios créditos firmes en
    # años distintos; deduplicamos manteniendo orden.
    supuestos: list[str] = []
    for it in items_69:
        s = it.get("supuesto")
        if s and s not in supuestos:
            supuestos.append(s)

    return MatchListaNegra(
        rfc=rfc,
        en_lista_69b=bool(items_69b),
        situacion_69b=situacion,
        fecha_publicacion_69b=fecha_pub,
        en_lista_69=bool(items_69),
        supuestos_69=supuestos,
        risk_level=payload.get("risk_level") or "limpio",
    )


def _parse_metadata(meta: dict) -> ListasMetadata:
    return ListasMetadata(
        lista_69b_updated_at=meta.get("lista_69b_updated_at"),
        lista_69_updated_at=meta.get("lista_69_updated_at"),
        record_count_69b=meta.get("record_count_69b"),
        record_count_69=meta.get("record_count_69"),
    )


def _normalizar_rfcs(rfcs: Iterable[str]) -> list[str]:
    """Trim + upper + deduplica preservando orden. RFCs vacíos se descartan."""
    visto: set[str] = set()
    out: list[str] = []
    for rfc in rfcs:
        if not rfc:
            continue
        clean = rfc.strip().upper()
        if not clean or clean in visto:
            continue
        visto.add(clean)
        out.append(clean)
    return out


def consultar_rfcs(
    rfcs: Iterable[str],
) -> tuple[list[MatchListaNegra], ListasMetadata]:
    """Consulta una lista de RFCs contra el endpoint batch de todoconta-apps.

    Lotea internamente si vienen > 200 RFCs. Las RFCs no encontradas en
    ninguna lista vuelven con `en_lista_*=False` y `risk_level="limpio"`.

    Returns:
        (matches en el mismo orden que la entrada normalizada, metadata global)

    Raises:
        RuntimeError: si no hay sesión o el endpoint responde error de red.
    """
    rfcs_norm = _normalizar_rfcs(rfcs)
    if not rfcs_norm:
        return [], ListasMetadata(None, None)

    if demo.activo():
        # Modo de grabación: los RFC inventados del escenario (y cualquiera con
        # fecha imposible) se contestan aquí; solo los reales van a la red.
        from ..demo import sat as sat_demo

        de_demo = [r for r in rfcs_norm if sat_demo.es_rfc_de_demo(r)]
        if de_demo:
            apartados = frozenset(de_demo)
            reales = [r for r in rfcs_norm if r not in apartados]
            por_rfc = {m.rfc: m for m in sat_demo.consultar_listas(de_demo)}
            if reales:
                matches_reales, metadata = _consultar_rfcs_red(reales)
                por_rfc.update({m.rfc: m for m in matches_reales})
            else:
                metadata = consultar_metadata()
            return [por_rfc[r] for r in rfcs_norm], metadata

    return _consultar_rfcs_red(rfcs_norm)


def _consultar_rfcs_red(rfcs_norm: list[str]) -> tuple[list[MatchListaNegra], ListasMetadata]:
    """Consulta (ya normalizada) contra el endpoint batch de todoconta-apps."""
    headers = _bearer_headers()
    url = f"{license_client.API_BASE_URL}/api/desktop/listas-negras/batch"

    by_rfc: dict[str, MatchListaNegra] = {}
    metadata: Optional[ListasMetadata] = None

    for i in range(0, len(rfcs_norm), _BATCH_SIZE):
        chunk = rfcs_norm[i : i + _BATCH_SIZE]
        try:
            resp = requests.post(
                url, json={"rfcs": chunk}, headers=headers, timeout=_TIMEOUT,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"No se pudo contactar listas negras: {e}") from e

        if resp.status_code == 401:
            license_client.clear_session()
            raise RuntimeError(
                "Sesión expirada. Vuelve a iniciar sesión para validar listas negras."
            )
        if resp.status_code != 200:
            try:
                detail = resp.json().get("error", resp.text)
            except ValueError:
                detail = resp.text
            raise RuntimeError(
                f"Listas negras: error {resp.status_code} — {detail}"
            )

        data = resp.json()
        results = data.get("results") or {}
        for rfc, payload in results.items():
            by_rfc[rfc.upper()] = _parse_match(rfc.upper(), payload)

        # La metadata es la misma en cada batch; nos quedamos con la primera.
        if metadata is None and data.get("metadata"):
            metadata = _parse_metadata(data["metadata"])

    # Para RFCs que el endpoint omitió (no hay match en ninguna lista),
    # devolvemos un MatchListaNegra "limpio" para que el consumidor siempre
    # tenga una respuesta por RFC consultado.
    matches: list[MatchListaNegra] = []
    for rfc in rfcs_norm:
        m = by_rfc.get(rfc)
        if m is None:
            m = MatchListaNegra(
                rfc=rfc, en_lista_69b=False, situacion_69b=None,
                fecha_publicacion_69b=None, en_lista_69=False,
                supuestos_69=[], risk_level="limpio",
            )
        matches.append(m)

    return matches, metadata or ListasMetadata(None, None)


def consultar_metadata() -> ListasMetadata:
    """Pide solo la metadata (última actualización del cron mensual del SAT).

    Usa el endpoint dedicado `/api/desktop/listas-negras/metadata`, que no
    toca las tablas grandes de listas — solo lee `sat_listas_metadata`.

    En modo de grabación, si no hay sesión o red, se usa el corte de ejemplo
    (día 5 del mes, como el cron) para que la pantalla no truene en cuadro.
    """
    try:
        return _consultar_metadata_red()
    except RuntimeError:
        if demo.activo():
            from ..demo import sat as sat_demo
            return sat_demo.metadata_listas()
        raise


def _consultar_metadata_red() -> ListasMetadata:
    headers = _bearer_headers()
    url = f"{license_client.API_BASE_URL}/api/desktop/listas-negras/metadata"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
    except requests.RequestException as e:
        raise RuntimeError(f"No se pudo contactar listas negras: {e}") from e

    if resp.status_code == 401:
        license_client.clear_session()
        raise RuntimeError(
            "Sesión expirada. Vuelve a iniciar sesión para validar listas negras."
        )
    if resp.status_code != 200:
        try:
            detail = resp.json().get("error", resp.text)
        except ValueError:
            detail = resp.text
        raise RuntimeError(f"Listas negras metadata: error {resp.status_code} — {detail}")

    return _parse_metadata(resp.json())


# ---------------------------------------------------------------------------
# Helpers de alto nivel: detección EFOS / EDOS
# ---------------------------------------------------------------------------


@dataclass
class EdosResultado:
    """Un CFDI marcado como EDOS porque su emisor es EFOS."""
    cfdi_uuid: str
    emisor_rfc: str
    situacion_69b: Optional[str]
    fecha_publicacion_69b: Optional[str]


def detectar_edos(
    cfdis: Iterable[tuple[str, str]],
) -> tuple[list[EdosResultado], ListasMetadata]:
    """Detecta EDOS sobre una lista de tuples (uuid, emisor_rfc).

    Solo cuenta como EDOS si el emisor está en 69-B con `Definitivo` o
    `Presunto`. Aclaraciones (Desvirtuado / Sentencia Favorable) ya no
    representan riesgo fiscal.
    """
    pares = list(cfdis)
    emisores_unicos = _normalizar_rfcs(rfc for _, rfc in pares)
    matches, meta = consultar_rfcs(emisores_unicos)

    efos_por_rfc = {m.rfc: m for m in matches if m.es_efos}

    edos: list[EdosResultado] = []
    for uuid, emisor in pares:
        if not emisor:
            continue
        m = efos_por_rfc.get(emisor.strip().upper())
        if m is None:
            continue
        edos.append(EdosResultado(
            cfdi_uuid=uuid,
            emisor_rfc=m.rfc,
            situacion_69b=m.situacion_69b,
            fecha_publicacion_69b=m.fecha_publicacion_69b,
        ))
    return edos, meta


# ---------------------------------------------------------------------------
# Helpers de mapping para persistencia en el procesador SQLite
# ---------------------------------------------------------------------------


def clasificar(match: MatchListaNegra) -> str:
    """Etiqueta corta para columnas `*_en_lista_negra` (filtros en la UI).

    "EFOS"     → en 69-B con Definitivo/Presunto.
    "Aclarado" → en 69-B con Desvirtuado/Sentencia Favorable (antecedente, sin riesgo activo).
    "69"       → solo en lista 69 (créditos firmes, no localizado, etc.).
    "Limpio"   → no aparece en ninguna lista.
    """
    if match.en_lista_69b and match.situacion_69b in ("Definitivo", "Presunto"):
        return "EFOS"
    if match.en_lista_69b:
        return "Aclarado"
    if match.en_lista_69:
        return "69"
    return "Limpio"


def match_to_json_dict(match: MatchListaNegra) -> dict:
    """Serializa el match a dict para guardar en la columna TEXT de SQLite."""
    return {
        "situacion_69b": match.situacion_69b,
        "fecha_publicacion_69b": match.fecha_publicacion_69b,
        "supuestos_69": match.supuestos_69,
        "risk_level": match.risk_level,
    }
