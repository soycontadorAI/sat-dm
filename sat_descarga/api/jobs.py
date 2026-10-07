"""
Bridge de jobs para el agente local (desktop): ejecuta una operación de scraping en
un *worker thread*, transmite su progreso por SSE, y resuelve el captcha CIEC con un
patrón **suspend/resume**.

El problema que resuelve: `iniciar_sesion_ciec` corre dentro de un `with
sync_playwright()` VIVO y bloquea en el callback `pedir_captcha(img, intento, max)`.
En el desktop no hay ventana tkinter: la imagen del captcha debe mostrarse en la UI
(Electron) y la solución regresar por HTTP. Por eso el callback que inyectamos:
  1. emite la imagen por SSE (`captcha_required`),
  2. BLOQUEA el thread del job en una cola hasta que el front haga
     `POST /jobs/{id}/captcha {solution}` (o `null` para cancelar),
  3. devuelve la solución a Playwright, que la teclea y continúa.

Es agnóstico al framework web: `JobRegistry.stream()` cede texto SSE listo para una
`StreamingResponse`, pero el módulo no importa FastAPI (así es testeable con threads).
"""

import base64
import json
import logging
import queue
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ..core.errores import ErrorEsperado

logger = logging.getLogger(__name__)

# Centinela que cierra el stream SSE de un job.
_FIN = object()

# Tiempo máximo que esperamos a que el usuario teclee el captcha antes de abortar
# (libera el browser para no dejar la sesión del SAT colgada).
CAPTCHA_TIMEOUT_S = 300


def _serializable(valor: Any) -> Any:
    """Convierte el resultado del job a algo JSON-serializable (Path → str, etc.)."""
    if isinstance(valor, Path):
        return str(valor)
    if isinstance(valor, (list, tuple)):
        return [_serializable(v) for v in valor]
    if isinstance(valor, dict):
        return {k: _serializable(v) for k, v in valor.items()}
    return valor


@dataclass
class Job:
    """Estado de una operación en curso (una por descarga/scrape)."""
    id: str
    estado: str = "pending"  # pending | running | captcha | done | error | cancelled
    resultado: Any = None
    error: Optional[str] = None
    _eventos: "queue.Queue" = field(default_factory=queue.Queue)
    _captcha_resp: "queue.Queue" = field(default_factory=queue.Queue)


class JobRegistry:
    """Catálogo de jobs + utilidades de emisión/captcha/stream. Thread-safe."""

    # Jobs ya terminados que se conservan para consultas de /jobs/{id}; el resto
    # se poda al crear un job nuevo. Sin esto, el registry (y la cola de eventos
    # de cada job, si nadie la consumió) crece con cada descarga de la sesión.
    MAX_TERMINADOS = 20

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def crear(self) -> Job:
        job = Job(id=uuid.uuid4().hex)
        with self._lock:
            self._podar()
            self._jobs[job.id] = job
        return job

    def _podar(self) -> None:
        """Poda los jobs terminados más viejos (dict preserva orden de inserción),
        conservando los últimos MAX_TERMINADOS. Llamar con `self._lock` tomado."""
        terminados = [
            jid for jid, j in self._jobs.items()
            if j.estado in ("done", "error", "cancelled")
        ]
        exceso = len(terminados) - self.MAX_TERMINADOS
        for jid in terminados[:max(exceso, 0)]:
            del self._jobs[jid]

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def hay_activo(self) -> bool:
        """True si hay algún job en curso (la sesión del agente es de un usuario)."""
        with self._lock:
            return any(j.estado in ("pending", "running", "captcha")
                       for j in self._jobs.values())

    # ---- emisión de eventos (SSE) ----
    def emitir(self, job: Job, tipo: str, **data) -> None:
        """Encola un evento para el stream SSE del job."""
        job._eventos.put({"event": tipo, **data})

    def stream(self, job: Job):
        """
        Generador SÍNCRONO de líneas SSE (`data: {...}\\n\\n`) hasta que el job
        termina. FastAPI lo itera en un threadpool, así que el `queue.get()`
        bloqueante no congela el event loop.
        """
        while True:
            ev = job._eventos.get()
            if ev is _FIN:
                break
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    # ---- captcha suspend/resume ----
    def pedir_captcha_callback(self, job: Job) -> Callable[[bytes, int, int], Optional[str]]:
        """
        Devuelve un `pedir_captcha(img_bytes, intento, max)` para inyectar en
        `iniciar_sesion_ciec`. Emite la imagen por SSE y BLOQUEA el worker thread
        hasta que llega la solución (o None = cancelar / timeout).
        """
        def _pedir(imagen: bytes, intento: int, max_intentos: int) -> Optional[str]:
            job.estado = "captcha"
            b64 = base64.b64encode(imagen).decode()
            self.emitir(
                job, "captcha_required",
                imagen=f"data:image/jpeg;base64,{b64}",
                intento=intento, max=max_intentos,
            )
            try:
                solucion = job._captcha_resp.get(timeout=CAPTCHA_TIMEOUT_S)
            except queue.Empty:
                self.emitir(job, "captcha_timeout")
                return None
            job.estado = "running"
            return solucion  # str = intentar; None = cancelar
        return _pedir

    def responder_captcha(self, job: Job, solucion: Optional[str]) -> None:
        """El front entrega la solución del captcha (o None para cancelar)."""
        job._captcha_resp.put(solucion)

    # ---- ejecución en worker thread ----
    def ejecutar(
        self,
        job: Job,
        fn: Callable[[], Any],
        al_completar: Optional[Callable[[Any], None]] = None,
    ) -> threading.Thread:
        """
        Corre `fn()` en un thread daemon. `fn` hace el scrape (y usa el callback de
        captcha de este registry). Captura resultado/errores y cierra el stream.

        Si se pasa `al_completar`, se invoca con el resultado cuando el job termina
        bien (p. ej. para registrar la descarga en el historial). Sus errores se
        registran pero NO tumban el job ni se propagan al front.
        """
        # El hilo nuevo no hereda el contexto de la petición: el origen de la
        # acción (uso por acción) se pasa a mano para los eventos del job.
        from .uso import fijar_origen, origen_actual

        origen = origen_actual()

        def _run():
            fijar_origen(origen)
            job.estado = "running"
            self.emitir(job, "estado", estado="running")
            try:
                job.resultado = fn()
                job.estado = "done"
                if al_completar is not None:
                    try:
                        al_completar(job.resultado)
                    except Exception:  # noqa: BLE001 - registrar no debe romper la descarga
                        logger.exception("[job %s] al_completar falló", job.id)
                self.emitir(job, "done", resultado=_serializable(job.resultado))
            except Exception as e:  # noqa: BLE001 - se reporta al front
                msg = str(e)
                # El login lanza RuntimeError("Captcha cancelado…") al cancelar.
                if "cancel" in msg.lower():
                    job.estado = "cancelled"
                    self.emitir(job, "cancelled", mensaje=msg)
                else:
                    job.estado = "error"
                    job.error = msg
                    self.emitir(job, "error", mensaje=msg)
                    if isinstance(e, ErrorEsperado):
                        # CIEC incorrecta, Chromium sin poder bajar, SAT caído:
                        # el usuario ya recibió el mensaje; no es un bug del
                        # agente → warning, sin evento en Sentry.
                        logger.warning("[job %s] falló (esperado): %s", job.id, msg)
                    else:
                        logger.exception("[job %s] error", job.id)
            finally:
                job._eventos.put(_FIN)

        t = threading.Thread(target=_run, name=f"job-{job.id}", daemon=True)
        t.start()
        return t


# Registry global del agente (un proceso = un usuario local).
registry = JobRegistry()
