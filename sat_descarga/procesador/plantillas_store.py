"""Plantillas de export del usuario en ``~/.sat-descarga/plantillas-export.json``.

Son del usuario, no de una empresa: un solo archivo, con el patrón resiliente
del resto de la config (escritura atómica, lectura tolerante, ``RLock``).
Las plantillas del sistema (`plantillas.SISTEMA`) no se guardan aquí: se
listan siempre primero y no se editan ni se borran (se duplican).

Esquema:
    {
      "version": 1,
      "predeterminada": "clasico" | "<id de una plantilla del usuario>",
      "plantillas": [
        {
          "id": "a1b2c3d4e5f6",
          "nombre": "Gastos para inventario",
          "columnas": [{"campo": "fecha_emision", "encabezado": "Fecha"}, ...],
          "detalle_concepto": [{"campo": "no_identificacion", "encabezado": "SKU"}, ...],
          "creada_en": "...", "updated_at": "...Z"
        }
      ]
    }

`updated_at` queda listo para el sync desktop ⇄ online (mismo merge LWW que
las tareas); el sync aún no existe.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Optional

from ..cli.config_store import (
    _ahora_sync,
    _load_json_resiliente,
    _write_json_atomico,
    get_config_dir,
)
from .plantillas import (
    ID_PREDETERMINADA,
    SISTEMA,
    Plantilla,
    normalizar_columnas,
    normalizar_nombre,
)

_lock = threading.RLock()


def _path() -> Path:
    return get_config_dir() / "plantillas-export.json"


def _vacio() -> dict:
    return {"version": 1, "predeterminada": ID_PREDETERMINADA, "plantillas": []}


def _load() -> dict:
    data = _load_json_resiliente(_path(), _vacio)
    data.setdefault("version", 1)
    data.setdefault("predeterminada", ID_PREDETERMINADA)
    data.setdefault("plantillas", [])
    return data


def _de_usuario(p: dict) -> Plantilla:
    return Plantilla(
        id=p["id"],
        nombre=p.get("nombre") or "Sin nombre",
        columnas=p.get("columnas") or [],
        detalle_concepto=p.get("detalle_concepto") or [],
    )


def _predeterminada_valida(data: dict) -> str:
    pid = data.get("predeterminada")
    if pid in SISTEMA or any(p["id"] == pid for p in data["plantillas"]):
        return pid
    return ID_PREDETERMINADA


def listar() -> dict:
    """Sistema primero, luego las del usuario (en orden de creación)."""
    with _lock:
        data = _load()
        return {
            "predeterminada": _predeterminada_valida(data),
            "plantillas": [p.a_dict() for p in SISTEMA.values()]
            + [_de_usuario(p).a_dict() for p in data["plantillas"]],
        }


def obtener(plantilla_id: str) -> Optional[Plantilla]:
    if plantilla_id in SISTEMA:
        return SISTEMA[plantilla_id]
    with _lock:
        for p in _load()["plantillas"]:
            if p["id"] == plantilla_id:
                return _de_usuario(p)
    return None


def predeterminada() -> Plantilla:
    with _lock:
        pid = _predeterminada_valida(_load())
    return obtener(pid) or SISTEMA[ID_PREDETERMINADA]


def _validar(nombre, columnas, detalle_concepto) -> dict:
    cols = normalizar_columnas(columnas, "cfdi")
    if not cols:
        raise ValueError("La plantilla necesita al menos una columna.")
    return {
        "nombre": normalizar_nombre(nombre),
        "columnas": cols,
        "detalle_concepto": normalizar_columnas(detalle_concepto or [], "concepto"),
    }


def crear(nombre, columnas, detalle_concepto=None) -> dict:
    """Crea una plantilla del usuario. ValueError si no es válida."""
    limpio = _validar(nombre, columnas, detalle_concepto)
    ahora = _ahora_sync()
    nueva = {"id": uuid.uuid4().hex[:12], **limpio, "creada_en": ahora, "updated_at": ahora}
    with _lock:
        data = _load()
        data["plantillas"].append(nueva)
        _write_json_atomico(_path(), data)
    return _de_usuario(nueva).a_dict()


def actualizar(plantilla_id: str, nombre, columnas, detalle_concepto=None) -> Optional[dict]:
    """Reemplaza nombre y columnas. None si no existe; ValueError si es del
    sistema o no es válida."""
    if plantilla_id in SISTEMA:
        raise ValueError("Las plantillas del sistema no se editan: duplícala.")
    limpio = _validar(nombre, columnas, detalle_concepto)
    with _lock:
        data = _load()
        for p in data["plantillas"]:
            if p["id"] == plantilla_id:
                p.update(limpio)
                p["updated_at"] = _ahora_sync()
                _write_json_atomico(_path(), data)
                return _de_usuario(p).a_dict()
    return None


def eliminar(plantilla_id: str) -> bool:
    """Borra una plantilla del usuario. Si era la predeterminada, vuelve la
    del sistema. ValueError si es del sistema."""
    if plantilla_id in SISTEMA:
        raise ValueError("Las plantillas del sistema no se borran.")
    with _lock:
        data = _load()
        antes = len(data["plantillas"])
        data["plantillas"] = [p for p in data["plantillas"] if p["id"] != plantilla_id]
        if len(data["plantillas"]) == antes:
            return False
        if data.get("predeterminada") == plantilla_id:
            data["predeterminada"] = ID_PREDETERMINADA
        _write_json_atomico(_path(), data)
        return True


def fijar_predeterminada(plantilla_id: str) -> str:
    """ValueError si la plantilla no existe."""
    with _lock:
        data = _load()
        if plantilla_id not in SISTEMA and not any(
            p["id"] == plantilla_id for p in data["plantillas"]
        ):
            raise ValueError("Esa plantilla no existe.")
        data["predeterminada"] = plantilla_id
        _write_json_atomico(_path(), data)
        return plantilla_id
