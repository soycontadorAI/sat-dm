"""
Tope de empresas activas por plan (F1 de planes v3; reglas en
docs/operacion/plan-app-v3.md de todoconta-apps, secciones 2 y 3).

- "Empresas activas" = las NO archivadas del catálogo local. Archivar (o
  eliminar) libera cupo; desarchivar lo ocupa.
- Al llegar al tope no se pueden dar de alta empresas nuevas (e.firma o
  Contraseña) ni desarchivar. Las que ya están siguen funcionando completas, y
  agregarle credenciales a una empresa que ya existe nunca cuenta como alta.
- Excedido por sincronización (altas en dos equipos sin internet): no se borra
  nada; se bloquean altas nuevas y el mensaje dice cuántas sobran.
- Legado, fundadores y cualquier licencia sin `limites.empresas` (backend
  viejo, cache de antes de F0, fallback offline sin cache): sin tope.

Cuándo se hace cumplir: con un tope numérico en la licencia Y (los planes v3 ya
están vigentes según el backend, `planes_v3_activo`, o el plan es uno de los
que se venden con tope). Antes del Día C la prueba (50) y el gratis (5) no se
aplican: los topes de esos dos se encienden con el interruptor del backend.

La licencia sale del cache local (sin red). Solo cuando el cache dice que no
hay lugar se pide una licencia fresca antes de rechazar: así quien acaba de
cambiar de plan no se topa con el tope viejo. Es el mismo código en escritorio
y en la web (el agente hosted usa este router).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from ..cli import config_store
from . import license_client as lc
from .limites_plan import LimitePlanAlcanzado, licencia_en_cache, licencia_fresca

logger = logging.getLogger(__name__)

# Planes que se venden con tope de empresas: su tope aplica aunque el
# interruptor del Día C no haya llegado en la licencia.
PLANES_V3_CON_TOPE = ("esencial", "pro", "completo", "medida")

# Planes sin tope pase lo que pase (sección 3: "Legado y fundadores: sin tope").
_PLANES_SIN_TOPE = (
    "desktop",
    "desktop_ia",
    "fundador",
    "profesional",
    "despachos",
    "empresarial",
    "legado",
)

# A qué plan se sugiere subir desde cada uno. Mismos topes que el seed de la
# migración 038 (todoconta-apps, `CATALOGO_PLANES`): si cambian allá, aquí.
SIGUIENTE_PLAN: dict[str, Optional[dict]] = {
    "gratis": {"codigo": "esencial", "nombre": "Esencial", "empresas": 10},
    "esencial": {"codigo": "pro", "nombre": "Pro", "empresas": 50},
    "trial": {"codigo": "completo", "nombre": "Completo", "empresas": 100},
    "pro": {"codigo": "completo", "nombre": "Completo", "empresas": 100},
    "completo": {"codigo": "medida", "nombre": "A la medida", "empresas": None},
    "medida": None,
}

class TopeEmpresasAlcanzado(LimitePlanAlcanzado):
    """Alta o desarchivado rechazado por el tope del plan (HTTP 402). Cuerpo:
    `detail` + `tope_empresas` con lo que la UI necesita para el diálogo de
    Archivar / Cambiar de plan."""

    def __init__(self, mensaje: str, datos: dict):
        super().__init__(mensaje, "tope_empresas", datos)


@dataclass(frozen=True)
class CupoEmpresas:
    tope: Optional[int]
    activas: int
    plan_codigo: Optional[str]
    plan_nombre: Optional[str]

    @property
    def lleno(self) -> bool:
        return self.tope is not None and self.activas >= self.tope

    @property
    def sobran(self) -> int:
        return max(0, self.activas - self.tope) if self.tope is not None else 0


# ---------------------------------------------------------------------------
# Licencia y conteo
# ---------------------------------------------------------------------------


def tope_de(licencia: Optional[dict]) -> Optional[int]:
    """Tope de empresas que se hace cumplir para esta licencia (None = sin tope)."""
    lic = licencia or {}
    codigo = lic.get("plan_codigo")
    if lic.get("legado") is True or codigo in _PLANES_SIN_TOPE:
        return None
    tope = lc.limites_de(lic)["empresas"]
    if tope is None:
        return None
    if lc.planes_v3_activos(lic) or codigo in PLANES_V3_CON_TOPE:
        return tope
    return None


def _empresas_activas(catalogo: dict) -> int:
    return sum(1 for info in catalogo.values() if not info.get("archived_at"))


def estado_cupo(licencia: Optional[dict], catalogo: Optional[dict] = None) -> CupoEmpresas:
    """Tope, empresas activas y plan, para una licencia dada."""
    if catalogo is None:
        catalogo = config_store.load_empresas()["empresas"]
    lic = licencia or {}
    codigo = lic.get("plan_codigo") if isinstance(lic.get("plan_codigo"), str) else None
    nombre = lic.get("plan_nombre") if isinstance(lic.get("plan_nombre"), str) else None
    return CupoEmpresas(
        tope=tope_de(lic),
        activas=_empresas_activas(catalogo),
        plan_codigo=codigo,
        plan_nombre=nombre,
    )


# ---------------------------------------------------------------------------
# Mensaje y payload del 402
# ---------------------------------------------------------------------------


def _empresas(n: int) -> str:
    return "1 empresa" if n == 1 else f"{n} empresas"


def _salida(siguiente: Optional[dict]) -> str:
    if siguiente and siguiente.get("empresas"):
        return f"cambia a {siguiente['nombre']} ({_empresas(siguiente['empresas'])})"
    if siguiente:
        return "escríbenos para un plan a la medida"
    return "escríbenos para ampliarlo"


def _mensaje(cupo: CupoEmpresas, siguiente: Optional[dict]) -> str:
    tope = cupo.tope or 0
    if cupo.plan_codigo == "trial":
        sujeto = "tu prueba"
    else:
        sujeto = f"tu plan {cupo.plan_nombre}" if cupo.plan_nombre else "tu plan"
    salida = _salida(siguiente)
    if cupo.sobran > 0:
        return (
            f"Tienes {cupo.activas} empresas activas y {sujeto} incluye {tope}: "
            f"te {'sobra 1' if cupo.sobran == 1 else f'sobran {cupo.sobran}'}. "
            f"Archiva las que ya no trabajes o {salida}."
        )
    return (
        f"{sujeto[0].upper()}{sujeto[1:]} incluye {_empresas(tope)}. "
        f"Archiva una que ya no trabajes o {salida}."
    )


def error_de_tope(cupo: CupoEmpresas) -> TopeEmpresasAlcanzado:
    siguiente = SIGUIENTE_PLAN.get(cupo.plan_codigo or "")
    datos: dict[str, Any] = {
        "plan_codigo": cupo.plan_codigo,
        "plan_nombre": cupo.plan_nombre,
        "tope": cupo.tope,
        "activas": cupo.activas,
        "sobran": cupo.sobran,
        "siguiente_plan": dict(siguiente) if siguiente else None,
    }
    return TopeEmpresasAlcanzado(_mensaje(cupo, siguiente), datos)


# ---------------------------------------------------------------------------
# Verificaciones que usan los endpoints
# ---------------------------------------------------------------------------


def _ocupa_lugar_nuevo(rfc: str, accion: str) -> bool:
    catalogo = config_store.load_empresas()["empresas"]
    info = catalogo.get(rfc)
    if accion == "alta":
        # Agregar credenciales a una empresa que ya existe (activa o archivada)
        # no cambia cuántas hay activas: `add_empresa*` conserva `archived_at`.
        return info is None
    # Desarchivar: solo ocupa lugar si de verdad estaba archivada.
    return info is not None and bool(info.get("archived_at"))


def _exigir(rfc: str, accion: str) -> None:
    rfc = (rfc or "").strip().upper()
    if not rfc or not _ocupa_lugar_nuevo(rfc, accion):
        return
    cupo = estado_cupo(licencia_en_cache())
    if not cupo.lleno:
        return
    # El cache dice que no hay lugar: confirmar con la licencia del servicio
    # (pudo haber cambiado de plan hace un momento) antes de rechazar.
    fresca = licencia_fresca()
    if fresca is not None:
        cupo = estado_cupo(fresca)
        if not cupo.lleno:
            return
    logger.info(
        "[tope] %s rechazada: %s de %s empresas (plan %s)",
        accion, cupo.activas, cupo.tope, cupo.plan_codigo,
    )
    raise error_de_tope(cupo)


def exigir_cupo_para_alta(rfc: str) -> None:
    """Lanza `TopeEmpresasAlcanzado` si dar de alta `rfc` (nuevo en el
    catálogo) excede el tope del plan."""
    _exigir(rfc, "alta")


def exigir_cupo_para_desarchivar(rfc: str) -> None:
    """Lanza `TopeEmpresasAlcanzado` si desarchivar `rfc` excede el tope."""
    _exigir(rfc, "desarchivar")
