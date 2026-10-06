"""
Router: una sesión activa a la vez (F1.1). Gana la sesión más reciente: al
abrir la app o iniciar sesión, esta instalación reclama la cuenta y las demás
se cierran. Lógica y números en `api/sesion_unica.py`.

- GET  /auth/sesion           estado local, sin red (escritorio). Query opcional
                              `interaccion_hace_s` (segundos sin tocar la app).
- POST /auth/sesion/reclamar  al abrir, al iniciar sesión y "Continuar aquí".
- POST /auth/sesion/latido    al volver a la ventana (y cada 60 s en la web).

Body de los POST: `{instalacion_id?, etiqueta?, interaccion_hace_s?}`. En
escritorio el agente usa SU instalación (ignora `instalacion_id`); en la web
(modo hosted) es obligatorio: la instalación es el navegador.

Respuesta: `{cerrada, modo, otra {etiqueta, tipo, desde}, sin_conexion,
instalacion_id, etiqueta, heartbeat_segundos}`. `cerrada=true` solo con
respuesta del servicio en modo exigir; sin internet nunca.
"""

from typing import Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from .. import sesion_unica

router = APIRouter()


class SesionRequest(BaseModel):
    instalacion_id: Optional[str] = None
    etiqueta: Optional[str] = None
    interaccion_hace_s: Optional[float] = None


@router.get("/auth/sesion")
def sesion_estado(interaccion_hace_s: Optional[float] = None):
    """Estado de la sesión de esta instalación (local, sin red)."""
    return sesion_unica.estado(interaccion_hace_s)


@router.post("/auth/sesion/reclamar")
def sesion_reclamar(req: Optional[SesionRequest] = Body(default=None)):
    """Reclama la cuenta para esta instalación (cierra las demás)."""
    req = req or SesionRequest()
    try:
        return sesion_unica.reclamar(
            req.instalacion_id,
            req.etiqueta,
            0 if req.interaccion_hace_s is None else req.interaccion_hace_s,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/auth/sesion/latido")
def sesion_latido(req: Optional[SesionRequest] = Body(default=None)):
    """Pregunta al servicio si otra instalación reclamó la cuenta."""
    req = req or SesionRequest()
    try:
        return sesion_unica.latido(req.instalacion_id, req.etiqueta, req.interaccion_hace_s)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
