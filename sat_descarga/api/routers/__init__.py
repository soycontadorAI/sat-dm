"""
Routers de FastAPI del agente local, partidos por dominio.

Cada router se crea con `APIRouter()` SIN prefix: las rutas completas viven en
cada decorador (p. ej. `@router.get("/empresas")`) para que sean idénticas a
las del monolito original (la UI y el CLI las consumen tal cual).

- webservice — Web Service oficial (FIEL/SOAP) + e-firma en sesión.
- portal     — scraping del portal SAT (CIEC + e.firma, jobs SSE + captcha).
- certifica  — renovación de e.firma y CSD de extremo a extremo (jobs SSE, FIEL-only).
- empresas   — catálogo de empresas + historial global.
- procesador — procesador de comprobantes (CFDI/Pagos/Nómina) + listas negras.
- utilidades — metadata, validación, organizador de XMLs.
- calculadoras — calculadoras fiscales/laborales + estado por empresa.
- diot       — DIOT 2025: prellenado, estado, export TXT y presentación (jobs).
- ce         — contabilidad electrónica (Anexo 24): envío, acuses y cola (jobs).
- tareas     — tareas personales (CRUD) + descartes de sugerencias.
- system     — health, abrir en el SO, ajustes y auth de licencia (todoconta).
- descargas  — descarga de archivos/ZIP por HTTP (reemplaza a /abrir en la web).
- sesion     — una sesión activa a la vez (reclamar, latido, estado).
"""

from .webservice import router as webservice_router
from .portal import router as portal_router
from .certifica import router as certifica_router
from .empresas import router as empresas_router
from .procesador import router as procesador_router
from .utilidades import router as utilidades_router
from .calculadoras import router as calculadoras_router
from .ce import router as ce_router
from .diot import router as diot_router
from .tareas import router as tareas_router
from .system import router as system_router
from .descargas import router as descargas_router
from .sesion import router as sesion_router

__all__ = [
    "webservice_router",
    "portal_router",
    "certifica_router",
    "empresas_router",
    "procesador_router",
    "utilidades_router",
    "calculadoras_router",
    "diot_router",
    "ce_router",
    "tareas_router",
    "system_router",
    "descargas_router",
    "sesion_router",
]
