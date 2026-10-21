"""
Puente con el espacio en línea del usuario (su agente personal en la nube).

"Subir credenciales al espacio": la e.firma/CIEC de una empresa viaja cifrada
(HTTPS) DIRECTO del equipo del usuario a su contenedor personal — exactamente
el mismo lugar donde quedan cuando las captura en la versión web. NUNCA tocan
la base de datos compartida ni servicios de terceros: el destino es la misma
alta autenticada que usa la web (/empresas/fiel, /empresas/ciec) contra el
agente remoto del usuario.

El provisioner resuelve (con la sesión de la cuenta) dónde vive ese espacio y
lo enciende si estaba apagado — funciona aunque el usuario nunca haya abierto
la versión web.
"""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

PROVISIONER_URL = os.environ.get(
    "TODOCONTA_PROVISIONER_URL", "https://agente.todoconta.com"
).rstrip("/")

_TIMEOUT = 30


class EspacioOnlineError(RuntimeError):
    """Error con mensaje en español apto para mostrarse al usuario final."""


def _conectar_espacio() -> tuple[str, str]:
    """Resuelve (base_url, token) del agente online del usuario vía provisioner."""
    from . import license_client as lc

    session = lc.load_session()
    if session is None:
        raise EspacioOnlineError(
            "Inicia sesión en tu cuenta para poder usar tu espacio en línea."
        )

    def _pedir(s):
        return requests.post(
            f"{PROVISIONER_URL}/provision/con-token",
            json={"access_token": s.access_token, "refresh_token": s.refresh_token},
            timeout=_TIMEOUT,
        )

    try:
        resp = _pedir(session)
        if resp.status_code == 401:
            nueva = lc.try_refresh_session(session)
            if nueva is None:
                raise EspacioOnlineError("Tu sesión expiró. Vuelve a iniciar sesión.")
            resp = _pedir(nueva)
    except requests.RequestException as e:
        raise EspacioOnlineError(
            "No se pudo contactar tu espacio en línea. Revisa tu internet e intenta de nuevo."
        ) from e

    if resp.status_code in (401, 403):
        try:
            detalle = resp.json().get("detail")
        except ValueError:
            detalle = None
        raise EspacioOnlineError(
            detalle or "Tu cuenta no tiene acceso a la versión web por el momento."
        )
    if resp.status_code != 200:
        raise EspacioOnlineError(
            "Tu espacio en línea no está disponible en este momento. Intenta más tarde."
        )
    data = resp.json()
    return data["base_url"].rstrip("/"), data["token"]


def _validar_alta(resp: requests.Response, que: str) -> None:
    if resp.status_code == 200:
        return
    detalle = None
    try:
        detalle = resp.json().get("detail")
    except ValueError:
        pass
    logger.warning("[espacio] alta de %s respondió %s: %s", que, resp.status_code, detalle)
    raise EspacioOnlineError(
        detalle or f"Tu espacio no pudo guardar la {que}. Intenta más tarde."
    )


def subir_credenciales(
    rfc: str, metodos: list[str], conexion: tuple[str, str] | None = None
) -> dict:
    """
    Sube las credenciales locales de la empresa a su espacio en línea.
    `metodos` ⊆ {"fiel", "ciec"}. Devuelve {"ok": True, "subidos": [...]}.
    Lanza KeyError si el RFC no existe y EspacioOnlineError con mensaje de
    usuario en cualquier otro problema.
    """
    from ..cli import config_store

    empresa = config_store.get_empresa(rfc)  # KeyError si no existe
    base, token = conexion or _conectar_espacio()
    headers = {"X-Agent-Token": token}
    subidos: list[str] = []

    if "fiel" in metodos:
        cer = empresa.get("cer_path")
        key = empresa.get("key_path")
        pwd = empresa.get("password")
        if not (cer and key and pwd and os.path.exists(cer) and os.path.exists(key)):
            raise EspacioOnlineError(
                "Esta empresa no tiene la e.firma completa en este equipo."
            )
        try:
            with open(cer, "rb") as fc, open(key, "rb") as fk:
                resp = requests.post(
                    f"{base}/empresas/fiel",
                    headers=headers,
                    files={
                        "cer_file": ("fiel.cer", fc, "application/octet-stream"),
                        "key_file": ("fiel.key", fk, "application/octet-stream"),
                    },
                    data={
                        "password": pwd,
                        "nombre": empresa.get("nombre") or "",
                        # El agente remoto valida que el cert sea de ESTE RFC.
                        "rfc_esperado": rfc,
                    },
                    timeout=60,
                )
        except requests.RequestException as e:
            raise EspacioOnlineError(
                "Se interrumpió la subida de la e.firma. Intenta de nuevo."
            ) from e
        _validar_alta(resp, "e.firma")
        subidos.append("fiel")

    if "ciec" in metodos:
        ciec = empresa.get("ciec")
        if not ciec:
            raise EspacioOnlineError("Esta empresa no tiene CIEC guardada en este equipo.")
        try:
            resp = requests.post(
                f"{base}/empresas/ciec",
                headers=headers,
                json={"rfc": rfc, "nombre": empresa.get("nombre") or "", "ciec": ciec},
                timeout=_TIMEOUT,
            )
        except requests.RequestException as e:
            raise EspacioOnlineError(
                "Se interrumpió la subida de la CIEC. Intenta de nuevo."
            ) from e
        _validar_alta(resp, "CIEC")
        subidos.append("ciec")

    if not subidos:
        raise EspacioOnlineError("No hay credenciales que subir para los métodos elegidos.")
    logger.info("[espacio] credenciales de %s subidas: %s", rfc, subidos)
    return {"ok": True, "subidos": subidos}


# ---------------------------------------------------------------------------
# Continuidad bidireccional (pieza 2): el espacio en la nube como hub
# ---------------------------------------------------------------------------


def _fiel_mas_nueva(a: dict, b: dict) -> bool:
    """True si las dos empresas tienen e.firma y la de `a` vence después.

    Al renovar, el SAT revoca el certificado anterior: si solo viajara la
    e.firma que "falta", el otro lado se quedaría con la revocada para
    siempre. Entre dos e.firmas del mismo RFC, la que vence después es la
    emitida después (vencimiento en ISO, YYYY-MM-DD).
    """
    va, vb = a.get("vencimiento") or "", b.get("vencimiento") or ""
    return (
        "fiel" in a.get("metodos", [])
        and "fiel" in b.get("metodos", [])
        and bool(va) and va > vb
    )


# Renovaciones que, con la sincronización APAGADA, obligan a revisar el espacio:
# la e.firma vieja quedó revocada y, si estaba en los dos lados, el otro se
# quedaría con ella. En memoria: el sync corre justo después de renovar.
_renovadas_aqui: set[str] = set()
# Vencimientos de la web ya revisados en esta sesión: si el espacio no tenía la
# e.firma nueva, no se vuelve a conectar en cada pasada del poller.
_revisadas_web: dict[str, str] = {}


def marcar_renovada(rfc: str) -> None:
    """La e.firma de `rfc` se acaba de renovar en este equipo."""
    _renovadas_aqui.add(rfc)


def _renovada_en_la_web(empresa: dict) -> bool:
    """El catálogo dice que la otra instalación tiene una e.firma que vence
    después que la de aquí (allá se renovó), y aún no se revisó."""
    vs = empresa.get("vencimiento_sync") or ""
    return (
        "fiel" in empresa.get("metodos", [])
        and vs > (empresa.get("vencimiento") or "")
        and _revisadas_web.get(empresa["rfc"]) != vs
    )


def sincronizar_credenciales() -> dict | None:
    """
    Replica credenciales entre este equipo y el espacio en línea del usuario,
    en ambos sentidos — la nube no puede alcanzar este equipo, así que la
    desktop siempre inicia: EMPUJA lo que a la web le falta y JALA lo que se
    capturó en la web (alta local automática). Una e.firma más nueva (renovada)
    reemplaza a la del otro lado.

    Con el ajuste "sincronizar credenciales" apagado solo hace eso último, y
    solo cuando hubo una renovación: cambia la e.firma revocada por la nueva
    donde el usuario ya la tenía, nunca sube ni baja una que el otro lado no
    tuviera. Sin renovación de por medio ni se conecta. Best-effort: nunca lanza.
    """
    import base64
    import tempfile

    from ..cli import config_store

    locales = {e["rfc"]: e for e in config_store.list_empresas()}
    solo_renovadas = not config_store.get_sync_credenciales()
    web_renovadas = {
        rfc: loc["vencimiento_sync"]
        for rfc, loc in locales.items() if _renovada_en_la_web(loc)
    }
    if solo_renovadas and not (_renovadas_aqui or web_renovadas):
        return None
    try:
        conexion = _conectar_espacio()
    except EspacioOnlineError as e:
        logger.info("[espacio] sync de credenciales omitido: %s", e)
        return None
    base, token = conexion
    headers = {"X-Agent-Token": token}

    # Estado REAL del agente remoto (no la unión del catálogo en la nube).
    try:
        r = requests.get(f"{base}/empresas", headers=headers, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        remotas = {e["rfc"]: e for e in r.json().get("empresas", [])}
    except (requests.RequestException, ValueError):
        return None
    _revisadas_web.update(web_renovadas)
    renovadas = set(_renovadas_aqui)
    reintentar: set[str] = set()

    subidas: list[str] = []
    bajadas: list[str] = []

    # Push: credenciales locales que a la web le faltan (archivadas no viajan).
    for rfc, loc in locales.items():
        if loc.get("archived_at"):
            continue
        rem = remotas.get(rfc) or {}
        faltan = [] if solo_renovadas else [
            m for m in loc.get("metodos", []) if m not in rem.get("metodos", [])
        ]
        if _fiel_mas_nueva(loc, rem):
            faltan.append("fiel")
        if not faltan:
            continue
        try:
            subir_credenciales(rfc, faltan, conexion=conexion)
            subidas.append(rfc)
        except (EspacioOnlineError, KeyError) as e:
            logger.info("[espacio] push de %s omitido: %s", rfc, e)
            reintentar.add(rfc)
    # Una renovada que no se pudo subir se reintenta en la siguiente pasada.
    _renovadas_aqui.difference_update(renovadas - reintentar)

    # Pull: credenciales capturadas en la web que aquí faltan.
    for rfc, rem in remotas.items():
        if rem.get("archived_at"):
            continue
        loc = locales.get(rfc)
        faltan = [] if solo_renovadas else [
            m for m in rem.get("metodos", [])
            if m not in (loc or {}).get("metodos", [])
        ]
        # Renovada en la web: la local quedó revocada y se reemplaza.
        reemplaza_fiel = bool(loc) and _fiel_mas_nueva(rem, loc)
        if reemplaza_fiel:
            faltan.append("fiel")
        if not faltan:
            continue
        try:
            cred = requests.get(
                f"{base}/empresas/{rfc}/credenciales", headers=headers, timeout=_TIMEOUT
            )
            if cred.status_code != 200:
                continue
            data = cred.json()
            nombre = data.get("nombre") or ""
            if "fiel" in faltan and data.get("fiel"):
                f = data["fiel"]
                with tempfile.TemporaryDirectory() as td:
                    cer = os.path.join(td, "fiel.cer")
                    key = os.path.join(td, "fiel.key")
                    with open(cer, "wb") as fh:
                        fh.write(base64.b64decode(f["cer_b64"]))
                    with open(key, "wb") as fh:
                        fh.write(base64.b64decode(f["key_b64"]))
                    if reemplaza_fiel:
                        config_store.respaldar_efirma_anterior(rfc)
                    # add_empresa valida el par y COPIA a ~/.sat-descarga/efirma/.
                    config_store.add_empresa(nombre, cer, key, f["password"], rfc_esperado=rfc)
                if reemplaza_fiel:
                    _recargar_sesion_si_activa(rfc)
                bajadas.append(f"{rfc}:fiel")
            if "ciec" in faltan and data.get("ciec"):
                config_store.add_empresa_ciec(rfc, nombre, data["ciec"])
                bajadas.append(f"{rfc}:ciec")
        except Exception as e:  # noqa: BLE001 — una empresa mala no frena al resto
            logger.info("[espacio] pull de %s omitido: %s", rfc, e)

    if subidas or bajadas:
        logger.info(
            "[espacio] credenciales sincronizadas · subidas=%s bajadas=%s", subidas, bajadas
        )
    return {"subidas": subidas, "bajadas": bajadas}


def _recargar_sesion_si_activa(rfc: str) -> None:
    """Si la e.firma reemplazada era la de la sesión, carga la nueva (best-effort)."""
    from ..cli import config_store
    from .state import _cargar_fiel_empresa, _session

    if _session.get("rfc") != rfc:
        return
    try:
        _cargar_fiel_empresa(config_store.get_empresa(rfc))
    except Exception as e:  # noqa: BLE001 — la sesión se recarga al reactivar
        logger.info("[espacio] no se pudo recargar la sesión de %s: %s", rfc, e)
