"""
Descargas al SAT del mes y su tope en el plan `gratis` (F1 de planes v3;
docs/operacion/plan-app-v3.md de todoconta-apps, sección 2).

Un solo contador para TODO lo que se baja del SAT: solicitudes de CFDI por el
Web Service (incluida la metadata), descargas de CFDIs por el portal (Contraseña
o e.firma), constancia, opinión 32-D y acuses. Cuenta lo que salió bien: un
intento fallido no gasta. Bajar los paquetes de una solicitud ya contada (a
mano o el poller) no cuenta otra vez.

- Se reinicia cada mes (mes calendario del equipo).
- Se cuenta siempre, para cualquier plan; el resumen del mes viaja con la
  sincronización del catálogo (`descargas_mes`).
- Solo se hace cumplir con planes v3 vigentes (`planes_v3_activo`) y plan
  `gratis`. El tope sale de `limites.descargas_mes` si la licencia lo trae; si
  no, 10 (decidido por Israel 2026-09-29). Sin licencia nunca hay tope.
- Al tope: HTTP 402 con `detail` + `tope_descargas` (mismo formato que el tope
  de empresas), vía el manejador de `LimitePlanAlcanzado` en server.py.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from ..cli import config_store
from . import license_client as lc
from .limites_plan import LimitePlanAlcanzado, licencia_en_cache, licencia_fresca

logger = logging.getLogger(__name__)

TOPE_GRATIS = 10
ARCHIVO = "descargas-mes.json"

SIGUIENTE_PLAN = {"codigo": "esencial", "nombre": "Esencial", "descargas": None}

_MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

_lock = threading.Lock()


class TopeDescargasAlcanzado(LimitePlanAlcanzado):
    """Descarga rechazada: el plan ya usó sus descargas del mes (HTTP 402)."""

    def __init__(self, mensaje: str, datos: dict):
        super().__init__(mensaje, "tope_descargas", datos)


@dataclass(frozen=True)
class CupoDescargas:
    tope: Optional[int]
    usadas: int
    mes: str
    plan_codigo: Optional[str]
    plan_nombre: Optional[str]

    @property
    def agotado(self) -> bool:
        return self.tope is not None and self.usadas >= self.tope

    @property
    def reinicia(self) -> str:
        anio, mes = (int(x) for x in self.mes.split("-"))
        siguiente = date(anio + (mes == 12), 1 if mes == 12 else mes + 1, 1)
        return siguiente.isoformat()

    def como_dict(self) -> dict:
        return {
            "aplica": self.tope is not None,
            "tope": self.tope,
            "usadas": self.usadas,
            "mes": self.mes,
            "reinicia": self.reinicia,
            "plan_codigo": self.plan_codigo,
            "plan_nombre": self.plan_nombre,
            "siguiente_plan": dict(SIGUIENTE_PLAN) if self.tope is not None else None,
        }


# ---------------------------------------------------------------------------
# Contador
# ---------------------------------------------------------------------------


def _mes_actual() -> str:
    return datetime.now().strftime("%Y-%m")


def _ruta():
    return config_store.CONFIG_DIR / ARCHIVO


def _leer() -> dict:
    """Contador del mes en curso. Un archivo de otro mes (o ilegible) = cero."""
    mes = _mes_actual()
    try:
        import json

        datos = json.loads(_ruta().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        datos = {}
    if not isinstance(datos, dict) or datos.get("mes") != mes:
        return {"mes": mes, "usadas": 0, "por_tipo": {}}
    usadas = datos.get("usadas")
    por_tipo = datos.get("por_tipo")
    return {
        "mes": mes,
        "usadas": usadas if isinstance(usadas, int) and usadas >= 0 else 0,
        "por_tipo": por_tipo if isinstance(por_tipo, dict) else {},
    }


def usadas_del_mes() -> int:
    return _leer()["usadas"]


def _es_demo(rfc: Optional[str]) -> bool:
    """Modo de grabación: lo de una empresa de demo no sale al SAT, así que ni
    gasta ni cuenta descargas del mes (la cuenta de grabación no se agota)."""
    from .. import demo

    return demo.aplica(rfc)


def registrar(tipo: str, rfc: Optional[str] = None) -> None:
    """Suma una descarga al mes en curso. Best-effort: nunca lanza (contar no
    debe romper una descarga que ya salió bien). `rfc`: la empresa de la
    descarga (no cuenta si es de demo en modo de grabación)."""
    if _es_demo(rfc):
        return
    try:
        with _lock:
            datos = _leer()
            datos["usadas"] += 1
            datos["por_tipo"][tipo] = int(datos["por_tipo"].get(tipo, 0) or 0) + 1
            _ruta().parent.mkdir(parents=True, exist_ok=True)
            config_store._write_json_atomico(_ruta(), datos)
    except Exception:  # noqa: BLE001
        logger.warning("[descargas-mes] no se pudo registrar la descarga", exc_info=True)


def resumen() -> dict:
    """Lo que viaja con la sincronización del catálogo: `{mes, usadas, por_tipo}`."""
    try:
        return _leer()
    except Exception:  # noqa: BLE001
        return {"mes": _mes_actual(), "usadas": 0, "por_tipo": {}}


# ---------------------------------------------------------------------------
# Tope
# ---------------------------------------------------------------------------


def tope_de(licencia: Optional[dict]) -> Optional[int]:
    """Tope de descargas del mes que se hace cumplir (None = sin tope)."""
    lic = licencia or {}
    if not lc.planes_v3_activos(lic) or lic.get("plan_codigo") != "gratis":
        return None
    limites = lic.get("limites") if isinstance(lic.get("limites"), dict) else {}
    valor = limites.get("descargas_mes")
    if isinstance(valor, int) and not isinstance(valor, bool) and valor > 0:
        return valor
    return TOPE_GRATIS


def estado(licencia: Optional[dict] = None, *, desde_cache: bool = True) -> CupoDescargas:
    lic = licencia if licencia is not None else (licencia_en_cache() if desde_cache else None)
    lic = lic or {}
    codigo = lic.get("plan_codigo") if isinstance(lic.get("plan_codigo"), str) else None
    nombre = lic.get("plan_nombre") if isinstance(lic.get("plan_nombre"), str) else None
    return CupoDescargas(
        tope=tope_de(lic),
        usadas=usadas_del_mes(),
        mes=_mes_actual(),
        plan_codigo=codigo,
        plan_nombre=nombre,
    )


def _fecha_larga(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} de {_MESES[d.month - 1]}"


def error_de_tope(cupo: CupoDescargas) -> TopeDescargasAlcanzado:
    nombre = cupo.plan_nombre or "Gratis"
    mensaje = (
        f"Tu plan {nombre} incluye {cupo.tope} descargas al mes y ya usaste las "
        f"{cupo.usadas}. Se renuevan el {_fecha_larga(cupo.reinicia)}; para seguir "
        f"hoy, cambia a {SIGUIENTE_PLAN['nombre']} (descargas sin límite)."
    )
    datos: dict[str, Any] = {
        k: v for k, v in cupo.como_dict().items() if k != "aplica"
    }
    return TopeDescargasAlcanzado(mensaje, datos)


def exigir(rfc: Optional[str] = None) -> None:
    """Lanza `TopeDescargasAlcanzado` si el plan ya usó sus descargas del mes.
    Antes de rechazar confirma con la licencia del servicio (pudo cambiar de
    plan hace un momento). Una empresa de demo en modo de grabación no pasa
    por el tope (no toca al SAT)."""
    if _es_demo(rfc):
        return
    cupo = estado()
    if not cupo.agotado:
        return
    fresca = licencia_fresca()
    if fresca is not None:
        cupo = estado(fresca)
        if not cupo.agotado:
            return
    logger.info("[descargas-mes] rechazada: %s de %s (plan %s)", cupo.usadas, cupo.tope, cupo.plan_codigo)
    raise error_de_tope(cupo)
