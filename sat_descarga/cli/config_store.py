"""
Capa de datos para el catálogo de empresas y tracking de solicitudes.

Almacena en ~/.sat-descarga/:
  empresas.json              — catálogo de FIELs registradas
  solicitudes/{RFC}.json     — historial de solicitudes por empresa

Este módulo NO tiene I/O de terminal; es reutilizable por CLI y GUI.
"""

import json
import locale
import logging
import os
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from sat_descarga.core.fiel import FIEL
from sat_descarga.core import secretos

logger = logging.getLogger(__name__)

# Lock para serializar lecturas/escrituras del catálogo de solicitudes. Sin esto,
# dos requests concurrentes (p. ej. el active flow + el auto-poll de no-terminales
# pegándole a /verificar al mismo tiempo) hacen read-modify-write entrelazado y
# corrompen el JSON.
_solicitudes_lock = threading.RLock()
_envios_lock = threading.RLock()

# Mismo problema para empresas.json, historial/{RFC}.json y settings.json: el
# agente atiende requests concurrentes y los mutadores hacen read-modify-write.
_catalogo_lock = threading.RLock()

# `SAT_DM_CONFIG_DIR` permite un perfil aparte (p. ej. la cuenta de grabación de
# los tutoriales) sin tocar el catálogo del equipo. Sin la env, lo de siempre.
CONFIG_DIR = (
    Path(os.environ["SAT_DM_CONFIG_DIR"]).expanduser()
    if os.environ.get("SAT_DM_CONFIG_DIR", "").strip()
    else Path.home() / ".sat-descarga"
)
# Copia de trabajo de los certificados, ANCLADA a una ruta absoluta y siempre
# escribible. Antes era `Path("efirma")` (relativa): bajo Electron empaquetado el
# agente arranca con cwd en el directorio de la app (solo-lectura en Windows por
# UAC), y `mkdir("efirma")` reventaba con [WinError 5] Acceso denegado. Anclarla a
# CONFIG_DIR también hace que las rutas guardadas en empresas.json sean absolutas
# (antes quedaban relativas y solo resolvían si el cwd coincidía).
EFIRMA_DIR = CONFIG_DIR / "efirma"


def get_config_dir() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def _write_json_atomico(path: Path, data: dict):
    """Escritura atómica y DURABLE: a `.tmp`, se fuerza el flush a disco con
    `fsync` y luego `os.replace` (rename atómico en POSIX y NTFS), así un lector
    concurrente nunca ve un archivo a medias.

    El `fsync` no es opcional: sin él, en Windows un apagado abrupto persiste la
    metadata del rename pero deja los datos del archivo todavía en caché del SO,
    y al reiniciar queda un archivo del tamaño correcto pero LLENO DE CEROS
    (`\\x00…`). Eso es justo lo que tumbaba cada GET /empresas con un
    JSONDecodeError. Con el fsync los bytes ya están en disco antes del rename."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _cuarentena(path: Path) -> None:
    """Aísla un archivo JSON corrupto (renombrándolo a `.corrupto`) para forense,
    sin pisar una cuarentena previa. Best-effort: si no se puede mover, solo loguea."""
    try:
        destino = path.with_suffix(path.suffix + ".corrupto")
        n = 1
        while destino.exists():
            destino = path.with_suffix(path.suffix + f".corrupto{n}")
            n += 1
        os.replace(path, destino)
        logger.error(
            "[config_store] %s estaba corrupto; aislado en %s", path.name, destino.name,
        )
    except OSError:
        logger.error(
            "[config_store] %s corrupto e inamovible", path.name, exc_info=True,
        )


def _decodificaciones_legacy() -> list[str]:
    """Encodings con los que pudo haberse escrito un JSON de versiones viejas,
    en orden de preferencia. Hasta v1.3.0 la escritura era `write_text()` SIN
    `encoding=`: en Windows eso usa el code page ANSI del sistema (cp1252 en
    español), así que un nombre con acentos/Ñ quedó en disco como bytes que NO
    son UTF-8 válido — el archivo está intacto, solo hay que leerlo con el
    encoding correcto. `latin-1` va al final como red de seguridad (decodifica
    cualquier byte; si el contenido no es JSON, el parseo lo rechaza igual)."""
    orden = ["utf-8", locale.getpreferredencoding(False), "cp1252", "latin-1"]
    vistos: set[str] = set()
    unicos = []
    for enc in orden:
        clave = (enc or "").lower()
        if clave and clave not in vistos:
            vistos.add(clave)
            unicos.append(enc)
    return unicos


def _parsear_json_multi_encoding(raw: bytes):
    """Intenta parsear `raw` como JSON probando los encodings legacy en orden.
    Devuelve `(data, encoding_usado)`, o `(None, None)` si ningún encoding
    produce JSON parseable (corrupción real, p. ej. archivo lleno de NUL)."""
    for enc in _decodificaciones_legacy():
        try:
            return json.loads(raw.decode(enc)), enc
        except (UnicodeDecodeError, json.JSONDecodeError, LookupError):
            continue
    return None, None


def _load_json_resiliente(path: Path, fallback):
    """Lee JSON tolerando encodings legacy y corrupción real.

    Los archivos escritos por ≤v1.3.0 en Windows quedaron en el encoding ANSI
    (cp1252): con acentos en el contenido NO son UTF-8 válido pero están
    intactos — se rescatan probando los encodings legacy y se migran a UTF-8 en
    disco (v1.4.0/v1.5.0 los trataba como corruptos y reseteaba el catálogo:
    TODOCONTA-DESKTOP-V). Solo si ningún encoding produce JSON parseable
    (p. ej. lleno de NUL tras un apagado abrupto) se aísla el archivo dañado y
    se devuelve `fallback()` en vez de tumbar cada request con un 500."""
    if not path.exists():
        return fallback()
    try:
        raw = path.read_bytes()
    except OSError:
        _cuarentena(path)
        return fallback()
    data, usado = _parsear_json_multi_encoding(raw)
    if usado is None:
        _cuarentena(path)
        return fallback()
    if usado.lower() not in ("utf-8", "utf8"):
        # Migración one-shot: reescribir en UTF-8 para que la próxima lectura
        # sea directa. warning (no error) para no generar eventos en Sentry.
        logger.warning(
            "[config_store] %s estaba en %s; migrado a UTF-8", path.name, usado,
        )
        try:
            _write_json_atomico(path, data)
        except OSError:
            logger.warning(
                "[config_store] no se pudo migrar %s a UTF-8", path.name, exc_info=True,
            )
    return data


# ---------------------------------------------------------------------------
# Empresas
# ---------------------------------------------------------------------------

def _empresas_path() -> Path:
    return get_config_dir() / "empresas.json"


def _rescatar_cuarentena_empresas() -> Optional[dict]:
    """Recupera un catálogo que v1.4.0/v1.5.0 puso en cuarentena por error.

    Esas versiones leían empresas.json con UTF-8 estricto y trataban un archivo
    en encoding ANSI (escrito por ≤v1.3.0 en Windows) como corrupción: lo
    renombraban a `.corrupto` y arrancaban con el catálogo vacío. Si hoy NO hay
    empresas.json pero sí una cuarentena parseable, se restaura (migrada a
    UTF-8) y la cuarentena se archiva como `.rescatado` para no reintentar.
    Devuelve el catálogo restaurado o None si no había nada rescatable."""
    candidatos = sorted(
        get_config_dir().glob("empresas.json.corrupto*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for cand in candidatos:
        if cand.name.endswith(".rescatado"):
            continue
        try:
            data, usado = _parsear_json_multi_encoding(cand.read_bytes())
        except OSError:
            continue
        if not isinstance(data, dict) or "empresas" not in data:
            continue
        _write_json_atomico(_empresas_path(), data)
        try:
            cand.rename(cand.with_name(cand.name + ".rescatado"))
        except OSError:
            logger.warning(
                "[config_store] no se pudo archivar %s tras el rescate", cand.name,
            )
        logger.warning(
            "[config_store] catálogo de empresas recuperado de %s (encoding %s)",
            cand.name, usado,
        )
        return data
    return None


def load_empresas() -> dict:
    with _catalogo_lock:
        path = _empresas_path()
        # Si no hay catálogo pero quedó una cuarentena de v1.4.0/v1.5.0 (falso
        # positivo de corrupción por encoding ANSI), se restaura de ahí. Solo
        # aplica cuando empresas.json NO existe: si el usuario ya re-registró
        # empresas (o vació el catálogo a propósito), no se toca.
        if not path.exists():
            rescatado = _rescatar_cuarentena_empresas()
            if rescatado is not None:
                return rescatado
        # Tolerante a corrupción REAL: si empresas.json quedó ilegible en todos
        # los encodings (típico tras un apagado abrupto en Windows → archivo
        # lleno de NUL), se aísla y se reinicia el catálogo en vez de reventar
        # /empresas en cada llamada. Con el fsync de _write_json_atomico esto
        # deja de pasar hacia adelante.
        data = _load_json_resiliente(
            path, lambda: {"empresas": {}, "default_rfc": None},
        )
        # Migración one-shot e idempotente: normaliza rutas relativas de la
        # e.firma. Barata cuando no hay nada que hacer (solo mira is_absolute).
        if _migrar_rutas_efirma(data):
            _write_json_atomico(path, data)
        return data


def _migrar_rutas_efirma(catalogo: dict) -> bool:
    """Normaliza a ABSOLUTAS las rutas de `.cer`/`.key` guardadas como relativas.

    Los catálogos creados por versiones viejas guardaban `efirma/{RFC}/fiel.cer`
    — una ruta relativa, que el sistema resuelve contra el directorio de trabajo
    del proceso. En dev el agente arranca en la raíz del repo, que casualmente
    tiene una carpeta `efirma/`, así que "funcionaba"; en la app empacada el cwd
    es la carpeta del binario (de solo lectura en Windows) y la carga truena con
    `[Errno 2] No such file or directory: 'efirma/<RFC>/fiel.cer'`. En el modo
    hosted no existe ninguna de las dos rutas.

    La forma guardada es exactamente la ruta relativa a `CONFIG_DIR`, que es
    donde `add_empresa` copia la e.firma hoy. Orden de resolución:

    1. `CONFIG_DIR/<relativa>` — el caso normal, solo se reescribe a absoluta.
    2. `cwd/<relativa>` — la resolución legacy. Si el archivo aparece ahí, se
       **copia** a `~/.sat-descarga/efirma/{RFC}/` para que deje de depender de
       dónde arranque el proceso.
    3. Si no está en ninguna, se reescribe igual a la forma absoluta bajo
       `CONFIG_DIR`: así el error que ve el usuario nombra una ruta real en vez
       de una relativa, y la migración no vuelve a intentarlo en cada lectura.

    NO estampa `updated_at`: es una normalización local, no un cambio del
    usuario, y `cer_path` no viaja en el sync de catálogo.

    Devuelve True si cambió algo (el caller persiste).
    """
    cambios = False
    for rfc, info in (catalogo.get("empresas") or {}).items():
        if not isinstance(info, dict):
            continue
        for campo, nombre_canonico in (("cer_path", "fiel.cer"), ("key_path", "fiel.key")):
            valor = info.get(campo)
            if not valor:
                continue
            rel = Path(valor)
            if rel.is_absolute():
                continue

            destino = CONFIG_DIR / rel
            if destino.is_file():
                info[campo] = str(destino)
                cambios = True
                continue

            legacy = Path.cwd() / rel
            if legacy.is_file():
                canonico = EFIRMA_DIR / rfc / nombre_canonico
                try:
                    canonico.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(legacy, canonico)
                    info[campo] = str(canonico)
                    cambios = True
                    logger.info(
                        "[catalogo] %s: %s se copió de %s a %s (ruta relativa legacy)",
                        rfc, campo, legacy, canonico,
                    )
                except OSError as e:  # disco lleno / permisos: no romper la carga
                    logger.warning(
                        "[catalogo] %s: no se pudo copiar %s a %s: %s",
                        rfc, legacy, canonico, e,
                    )
                continue

            info[campo] = str(destino)
            cambios = True
            logger.warning(
                "[catalogo] %s: %s apuntaba a la ruta relativa %r y el archivo no "
                "se encontró; queda como %s. Vuelve a cargar la e.firma de esta "
                "empresa.", rfc, campo, valor, destino,
            )
    return cambios


def save_empresas(data: dict):
    with _catalogo_lock:
        _write_json_atomico(_empresas_path(), data)


def _efirma_dir(rfc: str) -> Path:
    """Retorna ~/.sat-descarga/efirma/{RFC}/, creándola si no existe."""
    d = EFIRMA_DIR / rfc
    d.mkdir(parents=True, exist_ok=True)
    return d


# Aviso que acompaña al respaldo VISIBLE de la e.firma en la carpeta de descargas.
# Deja claro el modelo de privacidad: todo se queda en el equipo del usuario y la
# contraseña NO se guarda en ningún archivo (solo cifrada en el keychain del SO).
_LEEME_RESPALDO_FIEL = """\
Respaldo de tu e.firma — {rfc}

Esta carpeta contiene una COPIA de tu e.firma (fiel.cer y fiel.key) hecha por TodoConta.

• Todo queda en tu equipo. TodoConta NUNCA sube tu e.firma a ningún servidor ni
  conserva una copia fuera de tu computadora.
• Tu CONTRASEÑA no se guarda aquí ni en ningún archivo. Vive cifrada en el llavero
  de tu sistema operativo (Windows Credential Manager / macOS Keychain), solo por
  comodidad para no pedírtela en cada descarga.
• Resguarda tu contraseña en un lugar seguro: si la pierdes NO podemos recuperarla
  (el .key está cifrado con esa misma contraseña). El camino oficial es revocar y
  regenerar tu e.firma en sat.gob.mx con tu CURP y correo.
"""


def _respaldar_fiel_en_descargas(rfc: str, cer_dest: Path, key_dest: Path) -> None:
    """Guarda (best-effort) una copia VISIBLE de los .cer/.key en
    <descargas>/fiel/{RFC}/, junto a CFDI/constancia/opinión, con un LÉEME.

    La copia de trabajo que carga el agente vive en ~/.sat-descarga/efirma/ (a esa
    apuntan cer_path/key_path en empresas.json); esta es un respaldo para el usuario.
    NO se copia la contraseña: vive solo en el keychain del SO (core.secretos). Si la
    carpeta de descargas no es escribible, NO se interrumpe el registro — solo se
    loguea un warning (un respaldo que falla nunca debe tumbar el alta, que fue justo
    la clase de bug del WinError 5)."""
    try:
        backup_dir = Path(get_descargas_dir()) / "fiel" / rfc
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cer_dest, backup_dir / "fiel.cer")
        shutil.copy2(key_dest, backup_dir / "fiel.key")
        (backup_dir / "LÉEME.txt").write_text(
            _LEEME_RESPALDO_FIEL.format(rfc=rfc), encoding="utf-8"
        )
    except Exception as e:  # noqa: BLE001 — best-effort, nunca debe romper el alta
        logger.warning(
            "No se pudo guardar el respaldo de la e.firma de %s en descargas: %s", rfc, e
        )


def _metodos(info: dict) -> list[str]:
    """
    Métodos de autenticación de una empresa, como lista (['ciec'], ['fiel'] o ambos).
    Compat: migra el viejo campo `metodo` (string) y, si solo hay .cer, infiere 'fiel'.
    """
    if info.get("metodos"):
        return list(info["metodos"])
    if info.get("metodo"):
        return [info["metodo"]]
    return ["fiel"] if info.get("cer_path") else []


def add_empresa(nombre: str, cer_path: str, key_path: str, password: str,
                rfc_esperado: Optional[str] = None,
                antes_de_guardar: Optional[Callable[[str], None]] = None) -> str:
    """
    Registra una empresa por e.firma (FIEL) — o le AGREGA el método e.firma si el RFC
    ya existía (p. ej. con CIEC), sin quitar el otro método. Valida la FIEL, copia
    .cer/.key a ~/.sat-descarga/efirma/{RFC}/ (copia de trabajo del agente), deja un
    respaldo visible en <descargas>/fiel/{RFC}/ y guarda la contraseña en el keychain.
    Retorna el RFC.

    `nombre` puede venir vacío: se resuelve con la razón social del certificado
    (CN del subject) y, en último caso, con el RFC.

    Si se pasa `rfc_esperado` (al agregar e.firma a una empresa existente), se valida
    que el RFC del certificado coincida; si no, se rechaza (evita subir la e.firma de
    otro contribuyente).

    `antes_de_guardar(rfc)` (opcional) corre con el RFC ya validado y ANTES de copiar
    o guardar nada; si lanza, no queda rastro del alta. Lo usa el router para el tope
    de empresas del plan (el RFC solo se conoce al leer el certificado).
    """
    cer_src = Path(cer_path).expanduser().resolve()
    key_src = Path(key_path).expanduser().resolve()

    fiel = FIEL(str(cer_src), str(key_src), password)
    rfc = fiel.rfc

    # Las e.firmas de ejemplo del modo de grabación solo entran con el modo
    # prendido (el SAT nunca las aceptaría).
    from sat_descarga.demo.efirma import exigir_permitida
    exigir_permitida(fiel)

    if rfc_esperado and rfc != rfc_esperado.strip().upper():
        raise ValueError(
            f"La e.firma corresponde al RFC {rfc}, no a {rfc_esperado.strip().upper()}. "
            "Sube la e.firma de este contribuyente."
        )
    if antes_de_guardar is not None:
        antes_de_guardar(rfc)

    dest = _efirma_dir(rfc)
    cer_dest = dest / "fiel.cer"
    key_dest = dest / "fiel.key"
    if cer_src.resolve() != cer_dest.resolve():
        shutil.copy2(cer_src, cer_dest)
    if key_src.resolve() != key_dest.resolve():
        shutil.copy2(key_src, key_dest)
    secretos.guardar(rfc, secretos.FIEL, password)
    _respaldar_fiel_en_descargas(rfc, cer_dest, key_dest)

    with _catalogo_lock:
        data = load_empresas()
        existente = data["empresas"].get(rfc, {})
        entry = {
            **existente,
            "nombre": existente.get("nombre") or nombre or fiel.legal_name or rfc,
            "metodos": sorted(set(_metodos(existente)) | {"fiel"}),
            "cer_path": str(cer_dest),
            "key_path": str(key_dest),
            "vencimiento": fiel.not_valid_after.strftime("%Y-%m-%d"),
        }
        entry.pop("metodo", None)  # quitar campo legacy
        _stamp_sync(entry)
        data["empresas"][rfc] = entry
        if data["default_rfc"] is None:
            data["default_rfc"] = rfc
        save_empresas(data)
    return rfc


def add_empresa_ciec(rfc: str, nombre: str, ciec: str) -> str:
    """
    Registra una empresa por CIEC — o le AGREGA el método CIEC si el RFC ya existía
    (p. ej. con e.firma), sin quitar el otro. Guarda la contraseña CIEC en el keychain.

    `nombre` puede venir vacío: queda el RFC como nombre y se completa después
    (p. ej. al parsear la Constancia de Situación Fiscal).
    """
    rfc = rfc.strip().upper()
    secretos.guardar(rfc, secretos.CIEC, ciec)

    with _catalogo_lock:
        data = load_empresas()
        existente = data["empresas"].get(rfc, {})
        entry = {
            **existente,
            "nombre": existente.get("nombre") or nombre or rfc,
            "metodos": sorted(set(_metodos(existente)) | {"ciec"}),
        }
        entry.pop("metodo", None)
        _stamp_sync(entry)
        data["empresas"][rfc] = entry
        if data["default_rfc"] is None:
            data["default_rfc"] = rfc
        save_empresas(data)
    return rfc


def remove_empresa(rfc: str):
    with _catalogo_lock:
        data = load_empresas()
        data["empresas"].pop(rfc, None)
        if data["default_rfc"] == rfc:
            rfcs = list(data["empresas"].keys())
            data["default_rfc"] = rfcs[0] if rfcs else None
        save_empresas(data)
    # Borrar credenciales del keychain (ambos métodos; no falla si no existen).
    secretos.borrar(rfc, secretos.FIEL)
    secretos.borrar(rfc, secretos.CIEC)


def remove_efirma(rfc: str):
    """
    Quita SOLO el método e.firma de una empresa (la CIEC no se toca): borra
    .cer/.key de ./efirma/{RFC}/, la contraseña del keychain y los campos del
    catálogo. Caso de uso: la e.firma venció y el contribuyente no puede
    renovarla aún — la empresa queda operando solo con CIEC.
    Lanza KeyError si el RFC no existe.
    """
    with _catalogo_lock:
        data = load_empresas()
        if rfc not in data["empresas"]:
            raise KeyError(f"No se encontró empresa con RFC {rfc}")
        info = data["empresas"][rfc]
        info["metodos"] = [m for m in _metodos(info) if m != "fiel"]
        for campo in ("cer_path", "key_path", "vencimiento"):
            info.pop(campo, None)
        info.pop("metodo", None)  # campo legacy
        _stamp_sync(info)
        save_empresas(data)
    secretos.borrar(rfc, secretos.FIEL)
    shutil.rmtree(EFIRMA_DIR / rfc, ignore_errors=True)


def list_empresas() -> list[dict]:
    data = load_empresas()
    default = data.get("default_rfc")
    result = []
    for rfc, info in data["empresas"].items():
        result.append({
            "rfc": rfc,
            "nombre": info["nombre"],
            "metodos": _metodos(info),
            "cer_path": info.get("cer_path"),
            "vencimiento": info.get("vencimiento", ""),
            "default": rfc == default,
            "archived_at": info.get("archived_at"),
            "csf_path": info.get("csf_path"),
            "csf_descargada_en": info.get("csf_descargada_en"),
            "opinion_path": info.get("opinion_path"),
            "opinion_descargada_en": info.get("opinion_descargada_en"),
            # Sentido de la última 32-D parseada (positiva/negativa/otro) + motivos
            # de la negativa → semáforo y detalle de la empresa en la UI.
            "opinion_status": info.get("opinion_status"),
            "opinion_motivos": info.get("opinion_motivos", []),
            "regimenes_fiscales": info.get("regimenes_fiscales", []),
            "actividades_economicas": info.get("actividades_economicas", []),
            # None = sin configurar → la UI lo deriva del régimen (RESICO no
            # presenta DIOT); bool = override manual del usuario.
            "presenta_diot": info.get("presenta_diot"),
            "renovacion_pendiente": info.get("renovacion_pendiente"),
            "csds": info.get("csds", []),
            # Sync de catálogo: métodos con credenciales EN OTRA instalación
            # (badge "requiere credenciales aquí" cuando local no tiene).
            "metodos_sync": info.get("metodos_sync", []),
            "updated_at": info.get("updated_at"),
        })
    return result


# Campos editables por update_empresa(). Cualquier otra key del patch se ignora.
_EDITABLE_FIELDS = {"regimenes_fiscales", "actividades_economicas", "presenta_diot"}


def update_empresa(rfc: str, patch: dict):
    """
    Aplica un patch parcial a la empresa. Solo acepta keys en `_EDITABLE_FIELDS`;
    el resto se ignora silenciosamente (defensa básica).
    Valida shapes:
      - regimenes_fiscales:    list[{clave: str, descripcion: str}]
      - actividades_economicas: list[{descripcion: str, principal?: bool, porcentaje?: num}]
      - presenta_diot:         bool (override manual; ausente = derivar del régimen)
    Lanza ValueError si el shape es inválido y KeyError si el RFC no existe.

    Estampa `updated_at`: régimen/actividades/DIOT ahora viajan en el sync de
    catálogo, así que una edición manual debe propagarse a la otra instalación
    (misma regla last-write-wins por fila).
    """
    with _catalogo_lock:
        data = load_empresas()
        if rfc not in data["empresas"]:
            raise KeyError(f"No se encontró empresa con RFC {rfc}")

        for key, value in patch.items():
            if key not in _EDITABLE_FIELDS:
                continue
            if key == "presenta_diot":
                if not isinstance(value, bool):
                    raise ValueError("presenta_diot debe ser bool")
                data["empresas"][rfc][key] = value
                continue
            if not isinstance(value, list):
                raise ValueError(f"{key} debe ser una lista")
            if key == "regimenes_fiscales":
                for item in value:
                    if not isinstance(item, dict) \
                            or not isinstance(item.get("clave"), str) \
                            or not isinstance(item.get("descripcion"), str):
                        raise ValueError("régimen inválido: requiere clave y descripcion (str)")
                data["empresas"][rfc][key] = [
                    {"clave": i["clave"], "descripcion": i["descripcion"]} for i in value
                ]
            elif key == "actividades_economicas":
                for item in value:
                    if not isinstance(item, dict) \
                            or not isinstance(item.get("descripcion"), str):
                        raise ValueError("actividad inválida: requiere descripcion (str)")
                    if "principal" in item and not isinstance(item["principal"], bool):
                        raise ValueError("actividad.principal debe ser bool")
                    if item.get("porcentaje") is not None \
                            and not isinstance(item["porcentaje"], (int, float)):
                        raise ValueError("actividad.porcentaje debe ser numérico")
                data["empresas"][rfc][key] = [
                    {k: v for k, v in i.items()
                     if k in ("descripcion", "principal", "porcentaje") and v is not None}
                    for i in value
                ]
        _stamp_sync(data["empresas"][rfc])
        save_empresas(data)


def actualizar_nombre_si_placeholder(rfc: str, nuevo_nombre: str) -> bool:
    """
    Actualiza el nombre de la empresa SOLO si el guardado es un placeholder
    (vacío o igual al RFC) — señal de que la extracción del nombre falló al darla
    de alta (p. ej. cert con Ñ cuyo subject cryptography no pudo parsear). Si la
    empresa ya tiene un nombre real, no se toca. Devuelve True si lo cambió.

    Se llama al cargar la e.firma (cuando ya tenemos `fiel.legal_name`), para que
    el nombre se corrija solo sin pedirle al usuario borrar y volver a agregar.
    """
    nuevo = (nuevo_nombre or "").strip()
    if not nuevo or nuevo == rfc:
        return False
    with _catalogo_lock:
        data = load_empresas()
        emp = data["empresas"].get(rfc)
        if emp is None:
            return False
        actual = (emp.get("nombre") or "").strip()
        if actual and actual != rfc:
            return False  # ya tiene un nombre real; no lo pisamos
        emp["nombre"] = nuevo
        _stamp_sync(emp)
        save_empresas(data)
        return True


def archive_empresa(rfc: str):
    """
    Soft-delete: marca la empresa como archivada (no la borra). Si era la default,
    promueve la primera empresa activa restante (o None si no quedan activas).
    """
    with _catalogo_lock:
        data = load_empresas()
        if rfc not in data["empresas"]:
            raise KeyError(f"No se encontró empresa con RFC {rfc}")
        data["empresas"][rfc]["archived_at"] = datetime.now().isoformat(timespec="seconds")
        _stamp_sync(data["empresas"][rfc])
        if data.get("default_rfc") == rfc:
            candidatos = [
                r for r, info in data["empresas"].items()
                if r != rfc and not info.get("archived_at")
            ]
            data["default_rfc"] = candidatos[0] if candidatos else None
        save_empresas(data)


def unarchive_empresa(rfc: str):
    """Reactiva una empresa archivada."""
    with _catalogo_lock:
        data = load_empresas()
        if rfc not in data["empresas"]:
            raise KeyError(f"No se encontró empresa con RFC {rfc}")
        data["empresas"][rfc]["archived_at"] = None
        _stamp_sync(data["empresas"][rfc])
        save_empresas(data)


def _marca_de_tiempo(cuando: Optional[datetime]) -> str:
    """Marca ISO de los registros. `cuando` solo lo usa la siembra del modo de
    grabación (historial con fechas pasadas); en operación normal es ahora."""
    return (cuando or datetime.now()).isoformat(timespec="seconds")


def set_csf_descargada(rfc: str, path: str, *, cuando: Optional[datetime] = None):
    """Best-effort: persiste path + timestamp de la última CSF descargada."""
    with _catalogo_lock:
        data = load_empresas()
        if rfc not in data["empresas"]:
            return
        data["empresas"][rfc]["csf_path"] = path
        data["empresas"][rfc]["csf_descargada_en"] = _marca_de_tiempo(cuando)
        _stamp_sync(data["empresas"][rfc])
        save_empresas(data)


def aplicar_datos_csf(rfc: str, *, nombre: str,
                      regimenes: list[dict], actividades: list[dict]) -> bool:
    """
    Best-effort: aplica a la empresa los datos parseados de su Constancia de
    Situación Fiscal. La constancia MANDA: sobrescribe nombre (si viene),
    regímenes fiscales y actividades económicas aunque estuvieran configurados
    a mano — es el documento oficial y unifica placeholders (nombre == RFC) y
    casing inconsistente. Devuelve True si aplicó cambios.

    Shapes esperados (ya validados por el parser):
      regimenes:   [{clave: str ("" si no matcheó el catálogo), descripcion: str}]
      actividades: [{descripcion: str, principal: bool, porcentaje?: num}]

    Sí estampa `updated_at`: el `nombre` viaja en el sync de catálogo y este
    cambio debe ganar el merge LWW.
    """
    with _catalogo_lock:
        data = load_empresas()
        emp = data["empresas"].get(rfc)
        if emp is None:
            return False
        nuevo_nombre = (nombre or "").strip()
        if nuevo_nombre:
            emp["nombre"] = nuevo_nombre
        emp["regimenes_fiscales"] = [
            {"clave": str(r.get("clave") or ""), "descripcion": str(r.get("descripcion") or "")}
            for r in regimenes
        ]
        emp["actividades_economicas"] = [
            {k: v for k, v in {
                "descripcion": str(a.get("descripcion") or ""),
                "principal": bool(a.get("principal", False)),
                "porcentaje": a.get("porcentaje"),
            }.items() if v is not None}
            for a in actividades
        ]
        _stamp_sync(emp)
        save_empresas(data)
        return True


def set_opinion_descargada(rfc: str, path: str, *, cuando: Optional[datetime] = None):
    """Best-effort: persiste path + timestamp de la última opinión 32-D descargada."""
    with _catalogo_lock:
        data = load_empresas()
        if rfc not in data["empresas"]:
            return
        data["empresas"][rfc]["opinion_path"] = path
        data["empresas"][rfc]["opinion_descargada_en"] = _marca_de_tiempo(cuando)
        _stamp_sync(data["empresas"][rfc])
        save_empresas(data)


def aplicar_datos_opinion(rfc: str, *, sentido: str, motivos: list[dict]) -> bool:
    """
    Best-effort: aplica a la empresa el sentido de su Opinión de Cumplimiento
    32-D (positiva/negativa/otro) y, si es negativa, los motivos parseados.
    Alimenta el semáforo de la UI. Devuelve True si aplicó cambios.

    Shape de `motivos` (ya validado por el parser):
      [{titulo: str, descripcion: str, detalles: list[str]}]

    El sentido es derivado del PDF (no editable a mano); se estampa `updated_at`
    para mantener la consistencia con el resto de mutadores.
    """
    with _catalogo_lock:
        data = load_empresas()
        emp = data["empresas"].get(rfc)
        if emp is None:
            return False
        emp["opinion_status"] = sentido or None
        emp["opinion_motivos"] = [
            {
                "titulo": str(m.get("titulo") or ""),
                "descripcion": str(m.get("descripcion") or ""),
                "detalles": [str(d) for d in (m.get("detalles") or [])],
            }
            for m in motivos
        ]
        _stamp_sync(emp)
        save_empresas(data)
        return True


# ---------------------------------------------------------------------------
# Sync de catálogo entre instalaciones (desktop ⇄ online) — SOLO metadata
#
# Cada mutación de empresa deja `updated_at` (UTC) en SU entrada — nunca un
# stamp global en save_empresas(), que causaría falsos ganadores en el merge
# last-write-wins del backend (/api/desktop/empresas-sync). Las credenciales
# (cer_path/key_path/keychain) y `default_rfc` son locales del equipo: no viajan.
# ---------------------------------------------------------------------------


def _ahora_sync() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stamp_sync(entry: dict) -> None:
    """Marca la última modificación de la empresa (para el merge LWW del sync)."""
    entry["updated_at"] = _ahora_sync()


def _ts_sync(valor) -> float:
    """Timestamp comparable de un ISO (naive se asume UTC); 0 si no parsea."""
    if not valor:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def catalogo_para_sync() -> list[dict]:
    """
    Catálogo local en el shape que espera /api/desktop/empresas-sync.

    `metodos` viaja como la UNIÓN de los locales y los conocidos del otro lado
    (`metodos_sync`): es un campo informativo ("dónde hay credenciales"), y el
    merge remoto es por fila completa — sin la unión, una edición local con
    metodos=[] pisaría lo que el otro equipo reportó. Empresas sin `updated_at`
    (previas al sync) se estampan una sola vez aquí.
    """
    with _catalogo_lock:
        data = load_empresas()
        cambios = False
        catalogo = []
        for rfc, info in data["empresas"].items():
            if not info.get("updated_at"):
                _stamp_sync(info)
                cambios = True
            metodos = sorted(set(_metodos(info)) | set(info.get("metodos_sync", [])))
            catalogo.append({
                "rfc": rfc,
                "nombre": info.get("nombre") or rfc,
                "metodos": metodos,
                "vencimiento": info.get("vencimiento") or None,
                "archived_at": info.get("archived_at") or None,
                "csf_descargada_en": info.get("csf_descargada_en") or None,
                "opinion_descargada_en": info.get("opinion_descargada_en") or None,
                # Metadata fiscal parseada (CSF/opinión) o editada a mano: viaja
                # para que la otra instalación la vea sin re-descargar el PDF.
                "regimenes_fiscales": info.get("regimenes_fiscales") or [],
                "actividades_economicas": info.get("actividades_economicas") or [],
                "presenta_diot": info.get("presenta_diot"),
                "opinion_status": info.get("opinion_status") or None,
                "opinion_motivos": info.get("opinion_motivos") or [],
                "updated_at": info["updated_at"],
            })
        if cambios:
            save_empresas(data)
        return catalogo


def aplicar_sync_remoto(remotas: list[dict]) -> int:
    """
    Aplica el catálogo fusionado que devolvió el backend. Solo pisa entradas
    locales cuando la fila remota es MÁS nueva; las empresas nuevas se crean
    SIN credenciales (metodos=[]; `metodos_sync` alimenta el badge "requiere
    credenciales aquí" de la UI). Nunca toca cer_path/key_path/keychain ni
    default_rfc. Devuelve cuántas entradas cambió.
    """
    aplicadas = 0
    with _catalogo_lock:
        data = load_empresas()
        for r in remotas:
            rfc = str(r.get("rfc", "")).strip().upper()
            if not rfc:
                continue
            local = data["empresas"].get(rfc)
            remoto_ts = _ts_sync(r.get("updated_at"))
            if local is not None and _ts_sync(local.get("updated_at")) >= remoto_ts:
                continue

            if local is None:
                local = {"metodos": []}
                data["empresas"][rfc] = local

            if r.get("nombre"):
                local["nombre"] = r["nombre"]
            local.setdefault("nombre", rfc)
            local["metodos_sync"] = [
                m for m in (r.get("metodos") or []) if m in ("fiel", "ciec")
            ]
            local["archived_at"] = r.get("archived_at") or None
            # El vencimiento local viene del certificado real: solo se adopta
            # el remoto cuando aquí NO hay e.firma cargada.
            if not local.get("cer_path") and r.get("vencimiento"):
                local["vencimiento"] = r["vencimiento"]
            # Tracking de documentos: field-level y solo hacia adelante — una
            # fila remota más nueva por OTRO campo no borra lo descargado aquí.
            for campo in ("csf_descargada_en", "opinion_descargada_en"):
                if r.get(campo) and _ts_sync(r[campo]) > _ts_sync(local.get(campo)):
                    local[campo] = r[campo]
            # Metadata fiscal (régimen/actividades/opinión). La fila remota ya
            # ganó el LWW, pero solo se pisa con valores PRESENTES: así una
            # descarga de opinión (fila más nueva, régimen intacto pero vacío en
            # ese lado) no borra el régimen que la otra instalación sí parseó.
            # Contrapartida: "vaciar todo el régimen a mano" no se propaga.
            for campo in ("regimenes_fiscales", "actividades_economicas",
                          "opinion_motivos"):
                if r.get(campo):
                    local[campo] = r[campo]
            if r.get("opinion_status"):
                local["opinion_status"] = r["opinion_status"]
            if isinstance(r.get("presenta_diot"), bool):
                local["presenta_diot"] = r["presenta_diot"]
            local["updated_at"] = r.get("updated_at") or _ahora_sync()
            aplicadas += 1
        if aplicadas:
            save_empresas(data)
    return aplicadas


# ---------------------------------------------------------------------------
# Certifica: renovación de e.firma y Certificados de Sello Digital (CSD)
# ---------------------------------------------------------------------------

def respaldar_efirma_anterior(rfc: str) -> Optional[Path]:
    """
    Antes de sustituir la e.firma por la renovada, copia (best-effort) los
    fiel.cer/fiel.key actuales a ~/.sat-descarga/efirma/{RFC}/anterior_{stamp}/.
    El cert viejo deja de servir en cuanto el SAT emite el nuevo, pero el
    respaldo permite forense/recuperación manual. Nunca lanza; devuelve la
    carpeta del respaldo o None si no había nada que respaldar o falló.
    """
    try:
        origen = EFIRMA_DIR / rfc
        cer = origen / "fiel.cer"
        key = origen / "fiel.key"
        if not cer.exists() and not key.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destino = origen / f"anterior_{stamp}"
        destino.mkdir(parents=True, exist_ok=True)
        for src in (cer, key):
            if src.exists():
                shutil.copy2(src, destino / src.name)
        return destino
    except Exception as e:  # noqa: BLE001 — un respaldo que falla no debe frenar el trámite
        logger.warning("No se pudo respaldar la e.firma anterior de %s: %s", rfc, e)
        return None


def set_renovacion_pendiente(rfc: str, data: dict):
    """
    Persiste el estado de una renovación ENVIADA cuyo certificado nuevo aún no
    se descarga (el SAT tarda minutos en emitirlo). Se guarda en cuanto hay
    número de operación: si la app muere a media recuperación, la UI puede
    retomar con /renovar/recuperar. Shape:
    {numero_operacion, acuse_pdf, key_path, solicitado_en}.
    """
    with _catalogo_lock:
        catalogo = load_empresas()
        if rfc not in catalogo["empresas"]:
            return
        catalogo["empresas"][rfc]["renovacion_pendiente"] = {
            **data,
            "solicitado_en": data.get("solicitado_en")
            or datetime.now().isoformat(timespec="seconds"),
        }
        save_empresas(catalogo)


def get_renovacion_pendiente(rfc: str) -> Optional[dict]:
    data = load_empresas()
    empresa = data["empresas"].get(rfc) or {}
    return empresa.get("renovacion_pendiente")


def clear_renovacion_pendiente(rfc: str):
    with _catalogo_lock:
        catalogo = load_empresas()
        if rfc in catalogo["empresas"]:
            catalogo["empresas"][rfc].pop("renovacion_pendiente", None)
            save_empresas(catalogo)


def registrar_csd(rfc: str, entry: dict) -> dict:
    """
    Agrega un CSD solicitado a la lista `csds` de la empresa. Entry:
    {uso, numero_operacion, acuse_pdf, cer_path, key_path,
     estado: "pendiente"|"emitido", solicitado_en, recuperado_en}.
    Devuelve el registro persistido.
    """
    registro = {
        "estado": "pendiente",
        "cer_path": None,
        "recuperado_en": None,
        **entry,
        "solicitado_en": entry.get("solicitado_en")
        or datetime.now().isoformat(timespec="seconds"),
    }
    with _catalogo_lock:
        catalogo = load_empresas()
        if rfc not in catalogo["empresas"]:
            raise KeyError(f"No se encontró empresa con RFC {rfc}")
        catalogo["empresas"][rfc].setdefault("csds", []).append(registro)
        save_empresas(catalogo)
    return registro


def update_csd(rfc: str, numero_operacion: str, patch: dict) -> bool:
    """Actualiza el CSD identificado por su número de operación. True si lo encontró."""
    with _catalogo_lock:
        catalogo = load_empresas()
        empresa = catalogo["empresas"].get(rfc)
        if empresa is None:
            return False
        for csd in empresa.get("csds", []):
            if csd.get("numero_operacion") == numero_operacion:
                csd.update(patch)
                save_empresas(catalogo)
                return True
        return False


def get_csd_pendiente(rfc: str, numero_operacion: Optional[str] = None) -> Optional[dict]:
    """El CSD pendiente de recuperar (por número de operación, o el más reciente)."""
    data = load_empresas()
    empresa = data["empresas"].get(rfc) or {}
    pendientes = [c for c in empresa.get("csds", []) if c.get("estado") == "pendiente"]
    if numero_operacion:
        for c in pendientes:
            if c.get("numero_operacion") == numero_operacion:
                return c
        return None
    return pendientes[-1] if pendientes else None


def get_empresa(rfc: str) -> dict:
    """
    Devuelve los datos de la empresa MÁS sus credenciales del keychain: `password`
    (FIEL) y/o `ciec` (CIEC), según los métodos que tenga. `metodos` es una lista.
    Compat: respeta un `password` en texto plano de un catálogo viejo.
    """
    data = load_empresas()
    empresa = data["empresas"].get(rfc)
    if empresa is None:
        raise KeyError(f"No se encontró empresa con RFC {rfc}")
    info = {"rfc": rfc, **empresa}
    info["metodos"] = _metodos(empresa)
    info.pop("metodo", None)

    password = empresa.get("password") or secretos.obtener(rfc, secretos.FIEL)
    if password:
        info["password"] = password
    ciec = secretos.obtener(rfc, secretos.CIEC)
    if ciec:
        info["ciec"] = ciec
    return info


def get_default() -> Optional[str]:
    return load_empresas().get("default_rfc")


def set_default(rfc: str):
    with _catalogo_lock:
        data = load_empresas()
        if rfc not in data["empresas"]:
            raise KeyError(f"No se encontró empresa con RFC {rfc}")
        data["default_rfc"] = rfc
        save_empresas(data)


# ---------------------------------------------------------------------------
# Solicitudes
# ---------------------------------------------------------------------------

# Estados de una solicitud WS en el catálogo:
#   "solicitada"  — creada, aún sin verificar contra el SAT
#   "1"/"2"       — en cola / procesando (según el SAT)
#   "3"           — lista para descargar
#   "4"/"5"       — error del SAT / rechazada
#   "vencida"     — no-terminal por más de SOLICITUD_VENCIMIENTO_HORAS; el SAT
#                   ya no la va a resolver (su SLA es 72 h) y dejamos de pollearla
#   "descargada"  — paquetes descargados con éxito
ESTADOS_PENDIENTES = frozenset({"solicitada", "1", "2"})

# El SAT se compromete a resolver una solicitud en máximo 72 horas. Pasado ese
# plazo (con margen) la marcamos vencida localmente para que no quede "abierta"
# para siempre — el usuario puede volver a solicitarla.
SOLICITUD_VENCIMIENTO_HORAS = 72


def _solicitudes_dir() -> Path:
    d = get_config_dir() / "solicitudes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _solicitudes_path(rfc: str) -> Path:
    return _solicitudes_dir() / f"{rfc}.json"


def _load_solicitudes(rfc: str) -> dict:
    """Lee el catálogo de solicitudes de la empresa, tolerando encodings legacy
    (≤v1.3.0 escribía sin `encoding=` → ANSI en Windows; se migra a UTF-8). Si
    el JSON quedó corrupto (p. ej. write race anterior, antes de que esto fuera
    atómico), recupera el primer objeto válido con raw_decode y reescribe el
    archivo limpio."""
    path = _solicitudes_path(rfc)
    if not path.exists():
        return {"solicitudes": []}
    raw_bytes = path.read_bytes()
    data, usado = _parsear_json_multi_encoding(raw_bytes)
    if usado is not None:
        if usado.lower() not in ("utf-8", "utf8"):
            logger.warning(
                "[config_store] solicitudes/%s.json estaba en %s; migrado a UTF-8",
                rfc, usado,
            )
            _save_solicitudes(rfc, data)
        return data
    # JSON inválido en todos los encodings: típicamente el write race legacy
    # (dos objetos concatenados). Recuperar el primer objeto válido.
    raw = raw_bytes.decode("utf-8", errors="replace")
    logger.warning(
        "[config_store] solicitudes/%s.json corrupto; recuperando primer objeto…",
        rfc,
    )
    try:
        obj, _end = json.JSONDecoder().raw_decode(raw)
    except json.JSONDecodeError:
        logger.error(
            "[config_store] No se pudo recuperar; reseteando catálogo de %s", rfc,
        )
        obj = {"solicitudes": []}
    if not isinstance(obj, dict) or "solicitudes" not in obj:
        obj = {"solicitudes": obj if isinstance(obj, list) else []}
    _save_solicitudes(rfc, obj)
    return obj


def _save_solicitudes(rfc: str, data: dict):
    _write_json_atomico(_solicitudes_path(rfc), data)


def save_solicitud(
    rfc: str,
    id_solicitud: str,
    fecha_inicio: str,
    fecha_fin: str,
    tipo: str,
    estado: str = "solicitada",
    *,
    tipo_comprobante: Optional[str] = None,  # "E" (emitidos) / "R" (recibidos)
    cuando: Optional[datetime] = None,
):
    """Guarda una solicitud WS. `tipo_comprobante` se conserva para luego ubicar la
    descarga en la carpeta correcta (`{RFC}/{emitidos|recibidos}/{rango}/`)."""
    with _solicitudes_lock:
        data = _load_solicitudes(rfc)
        registro = {
            "id_solicitud": id_solicitud,
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "tipo": tipo,
            "estado": estado,
            "timestamp": _marca_de_tiempo(cuando),
        }
        if tipo_comprobante:
            registro["tipo_comprobante"] = tipo_comprobante.strip().upper()
        data["solicitudes"].append(registro)
        _save_solicitudes(rfc, data)


def update_solicitud(
    rfc: str,
    id_solicitud: str,
    estado: str,
    package_ids: Optional[list] = None,
    *,
    mensaje: Optional[str] = None,
    numero_cfdis: Optional[int] = None,
):
    """Actualiza el estado y, opcionalmente, los campos auxiliares que devuelve el
    SAT en /verificar (mensaje, numero_cfdis). Estos últimos alimentan los detalles
    de la fila expandida en la UI."""
    with _solicitudes_lock:
        data = _load_solicitudes(rfc)
        for sol in data["solicitudes"]:
            if sol["id_solicitud"] == id_solicitud:
                sol["estado"] = estado
                if package_ids is not None:
                    sol["package_ids"] = package_ids
                if mensaje is not None:
                    sol["mensaje"] = mensaje
                if numero_cfdis is not None:
                    sol["numero_cfdis"] = numero_cfdis
                break
        _save_solicitudes(rfc, data)


def delete_solicitud(rfc: str, id_solicitud: str) -> bool:
    """Borra una solicitud del catálogo de la empresa. Devuelve True si se borró,
    False si no se encontró."""
    with _solicitudes_lock:
        data = _load_solicitudes(rfc)
        n = len(data["solicitudes"])
        data["solicitudes"] = [s for s in data["solicitudes"] if s.get("id_solicitud") != id_solicitud]
        if len(data["solicitudes"]) == n:
            return False
        _save_solicitudes(rfc, data)
        return True


def get_solicitudes_pendientes(rfc: str) -> list[dict]:
    """Solicitudes que siguen vivas en el SAT (en cola/procesando) y por tanto
    deben seguirse verificando. Excluye terminales: lista (3), error (4),
    rechazada (5), vencida y descargada."""
    with _solicitudes_lock:
        data = _load_solicitudes(rfc)
    return [s for s in data["solicitudes"] if s["estado"] in ESTADOS_PENDIENTES]


def marcar_solicitudes_vencidas(
    rfc: str, horas: int = SOLICITUD_VENCIMIENTO_HORAS,
) -> list[dict]:
    """Marca como "vencida" toda solicitud pendiente (solicitada/1/2) con más de
    `horas` desde su creación. El SAT no resuelve solicitudes más allá de su SLA
    de 72 h; sin esto, una solicitud que el SAT dejó colgada (p. ej. en semanas
    de fallas) se pollearía para siempre. Devuelve las recién vencidas (copia)."""
    limite = datetime.now() - timedelta(hours=horas)
    vencidas: list[dict] = []
    with _solicitudes_lock:
        data = _load_solicitudes(rfc)
        for sol in data["solicitudes"]:
            if sol.get("estado") not in ESTADOS_PENDIENTES:
                continue
            ts = sol.get("timestamp")
            try:
                creada = datetime.fromisoformat(ts) if ts else None
            except ValueError:
                creada = None
            # Sin timestamp o malformado = registro legacy, por definición viejo.
            if creada is not None and creada > limite:
                continue
            sol["estado"] = "vencida"
            sol["mensaje"] = (
                f"El SAT no resolvió la solicitud en {horas} horas. "
                "Vuelve a solicitar el periodo."
            )
            vencidas.append(dict(sol))
        if vencidas:
            _save_solicitudes(rfc, data)
    return vencidas


def list_solicitudes(rfc: str) -> list[dict]:
    """Todas las solicitudes de la empresa, más recientes primero (para Historial)."""
    with _solicitudes_lock:
        data = _load_solicitudes(rfc)
    return list(reversed(data["solicitudes"]))


def get_solicitud(rfc: str, id_solicitud: str) -> Optional[dict]:
    with _solicitudes_lock:
        data = _load_solicitudes(rfc)
    for s in data["solicitudes"]:
        if s["id_solicitud"] == id_solicitud:
            return s
    return None


# ---------------------------------------------------------------------------
# Historial de descargas (log unificado: WS + CIEC + documentos)
#
# A diferencia de `solicitudes/` (lifecycle de las solicitudes WS, para retomar),
# esto es un registro plano de descargas YA COMPLETADAS, por empresa, para que la
# pantalla Historial las muestre. Una línea por descarga terminada.
# ---------------------------------------------------------------------------

def _historial_dir() -> Path:
    d = get_config_dir() / "historial"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _historial_path(rfc: str) -> Path:
    return _historial_dir() / f"{rfc}.json"


def registrar_descarga(
    rfc: str,
    canal: str,                 # "ws" | "ciec" | "fiel"
    tipo: str,                  # "cfdi" | "metadata" | "constancia" | "opinion"
    descripcion: str = "",
    ruta: str = "",
    total: Optional[int] = None,  # nº de XML (CFDIs) cuando aplica
    estado: str = "completada",
    *,
    cuando: Optional[datetime] = None,
) -> dict:
    """Registra una descarga completada en el historial de la empresa. Devuelve el registro."""
    rfc = rfc.strip().upper()
    path = _historial_path(rfc)
    registro = {
        "timestamp": _marca_de_tiempo(cuando),
        "canal": canal,
        "tipo": tipo,
        "descripcion": descripcion,
        "ruta": ruta,
        "total": total,
        "estado": estado,
    }
    with _catalogo_lock:
        data = _load_json_resiliente(path, lambda: {"descargas": []})
        data["descargas"].append(registro)
        _write_json_atomico(path, data)
    return registro


def list_descargas(rfc: str) -> list[dict]:
    """Descargas de una empresa, más recientes primero."""
    path = _historial_path(rfc)
    data = _load_json_resiliente(path, lambda: {"descargas": []})
    return list(reversed(data.get("descargas", [])))


def list_todas_descargas() -> list[dict]:
    """Descargas de TODAS las empresas (con rfc + nombre), más recientes primero."""
    nombres = {e["rfc"]: e["nombre"] for e in list_empresas()}
    resultado: list[dict] = []
    for path in _historial_dir().glob("*.json"):
        rfc = path.stem
        try:
            data, _usado = _parsear_json_multi_encoding(path.read_bytes())
        except OSError:
            continue
        if not isinstance(data, dict):
            continue
        for d in data.get("descargas", []):
            resultado.append({**d, "rfc": rfc, "nombre": nombres.get(rfc, rfc)})
    resultado.sort(key=lambda d: d.get("timestamp", ""), reverse=True)
    return resultado


# ---------------------------------------------------------------------------
# Ajustes (settings.json) — p. ej. la carpeta base de descargas
# ---------------------------------------------------------------------------

def _settings_path() -> Path:
    return get_config_dir() / "settings.json"


def _load_settings() -> dict:
    return _load_json_resiliente(_settings_path(), dict)


def _save_settings(data: dict):
    with _catalogo_lock:
        _write_json_atomico(_settings_path(), data)


def descargas_dir_default() -> str:
    """Carpeta de descargas por defecto: la carpeta Documentos del usuario.

    En modo hosted el contenedor la fija con SAT_DM_DESCARGAS_DIR (apunta al
    volumen /data/descargas) para que las descargas sobrevivan al contenedor.
    """
    env = os.environ.get("SAT_DM_DESCARGAS_DIR", "").strip()
    if env:
        return env
    return str(Path.home() / "Documents" / "TodoConta")


def get_descargas_dir() -> str:
    """Carpeta base donde se guardan las descargas (configurable)."""
    return _load_settings().get("descargas_dir") or descargas_dir_default()


def asegurar_descargas_dir() -> str:
    """Devuelve la carpeta de descargas, creándola si no existe."""
    d = get_descargas_dir()
    Path(d).mkdir(parents=True, exist_ok=True)
    return d


def get_sync_credenciales() -> bool:
    """Continuidad de credenciales con el espacio en línea (default: activada).

    ⚠️ El default cambia la promesa histórica "tu e.firma nunca sale de tu
    equipo" → "…salvo a TU espacio privado": anunciado en el release y
    desactivable aquí (Ajustes → Sincronización).
    """
    valor = _load_settings().get("sync_credenciales")
    return True if valor is None else bool(valor)


def set_sync_credenciales(activado: bool) -> bool:
    with _catalogo_lock:
        data = _load_settings()
        data["sync_credenciales"] = bool(activado)
        _save_settings(data)
    return bool(activado)


def set_descargas_dir(path: str) -> str:
    """Fija la carpeta base de descargas (y la crea). Retorna la ruta absoluta."""
    p = str(Path(path).expanduser())
    Path(p).mkdir(parents=True, exist_ok=True)
    with _catalogo_lock:
        data = _load_settings()
        data["descargas_dir"] = p
        _save_settings(data)
    return p


# ---------------------------------------------------------------------------
# Config del organizador — GLOBAL por usuario, NO por empresa
# ---------------------------------------------------------------------------
#
# Un despacho define su método de organización UNA vez y aplica a todas sus
# empresas (pedido de usuario real: despachos con 10-30+ RFCs y una sola forma
# de trabajar). Vive en settings.json — sobrevive reinstalaciones y opera igual
# en la versión web (el agente del usuario persiste su propio settings).

ORGANIZADOR_DEFAULTS = {
    "estructura": "rfc_emisor/anio/mes",          # preset del select, o "custom"
    "niveles_custom": ["anio", "mes", "flujo"],   # builder de estructura custom
    "renombrar_patron": "emisor_fecha_total",     # preset de renombrado, o "custom"
    "partes_nombre": ["fecha", "rfc_emisor", "folio_fiscal"],
    "separador": "-",
    "copiar": True,
}


def get_organizador_config() -> dict:
    """Config global del organizador + `guardada` (si el usuario ya fijó la suya).

    `guardada=False` deja que la UI migre una config previa de localStorage la
    primera vez, en lugar de pisarla con los defaults."""
    guardado = _load_settings().get("organizador")
    cfg = {
        **ORGANIZADOR_DEFAULTS,
        **{k: v for k, v in (guardado or {}).items() if k in ORGANIZADOR_DEFAULTS},
    }
    cfg["guardada"] = guardado is not None
    return cfg


def set_organizador_config(patch: dict) -> dict:
    """Aplica un patch parcial (solo claves conocidas) y regresa la config final."""
    limpio = {k: v for k, v in patch.items() if k in ORGANIZADOR_DEFAULTS}
    with _catalogo_lock:
        data = _load_settings()
        cfg = data.get("organizador") or {}
        cfg.update(limpio)
        data["organizador"] = cfg
        _save_settings(data)
    return get_organizador_config()


# ---------------------------------------------------------------------------
# Envíos pendientes (contabilidad electrónica / DIOT): cola de reintento diferido
# ---------------------------------------------------------------------------
# El portal del SAT se pone lento o entra en mantenimiento sin aviso; cuando un
# envío agota sus reintentos por errores TRANSITORIOS (nunca por errores de
# fondo), queda aquí para retomarse después con `sat-dm ce reanudar` o con el
# poller de la app. Reanudar es idempotente: siempre se consulta el portal
# antes de subir (omitir_enviados), así que un pendiente "de más" no duplica.
#
# Esquema — ~/.sat-descarga/envios/{RFC}.json:
#   {"version": 1, "envios": [{
#       "id": uuid4.hex[:12], "tramite": "ce",         # "diot" reservado
#       "rfc": "...", "archivos": ["/abs/x.zip", ...], # lo que FALTA por enviar
#       "params": {"sellar": true, "motivo": "mensual",
#                  "salida": null, "junto_al_zip": false},
#       "estado": "pendiente" | "curso" | "completado" | "abandonado",
#       "intentos": 0,                                  # corridas completas fallidas
#       "creado": iso, "ultimo_intento": iso | null,
#       "ultimo_error": str | null, "resultado": dict | null }]}
#
# Sin vencimiento automático (a diferencia de solicitudes/): la obligación
# fiscal no caduca a las 72 h. "abandonado" es decisión manual.

ESTADOS_ENVIO = ("pendiente", "curso", "completado", "abandonado")


def _envios_dir() -> Path:
    d = get_config_dir() / "envios"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _envios_path(rfc: str) -> Path:
    return _envios_dir() / f"{rfc.strip().upper()}.json"


def _load_envios(rfc: str) -> dict:
    path = _envios_path(rfc)
    data = _load_json_resiliente(path, lambda: {"version": 1, "envios": []})
    data.setdefault("version", 1)
    data.setdefault("envios", [])
    return data


def _save_envios(rfc: str, data: dict):
    _write_json_atomico(_envios_path(rfc), data)


def save_envio_pendiente(rfc: str, tramite: str, archivos: list,
                         params: Optional[dict] = None,
                         error: Optional[str] = None) -> str:
    """Encola archivos para reintentar más tarde. Devuelve el id del registro.

    Dedup: si ya hay un pendiente del mismo trámite, FUSIONA los archivos y
    actualiza el error en vez de crear otro registro — una corrida cortada a
    media tanda no debe fabricar N pendientes del mismo lote.
    """
    import uuid

    rfc = rfc.strip().upper()
    archivos = [str(a) for a in archivos]
    with _envios_lock:
        data = _load_envios(rfc)
        for e in data["envios"]:
            if e["tramite"] == tramite and e["estado"] == "pendiente":
                previos = set(e["archivos"])
                e["archivos"] += [a for a in archivos if a not in previos]
                if error:
                    e["ultimo_error"] = str(error)[:500]
                if params:
                    e["params"] = params
                _save_envios(rfc, data)
                return e["id"]
        registro = {
            "id": uuid.uuid4().hex[:12],
            "tramite": tramite,
            "rfc": rfc,
            "archivos": archivos,
            "params": params or {},
            "estado": "pendiente",
            "intentos": 0,
            "creado": datetime.now().isoformat(timespec="seconds"),
            "ultimo_intento": None,
            "ultimo_error": str(error)[:500] if error else None,
            "resultado": None,
        }
        data["envios"].append(registro)
        _save_envios(rfc, data)
        return registro["id"]


def update_envio(rfc: str, envio_id: str, *, estado: Optional[str] = None,
                 archivos: Optional[list] = None, error: Optional[str] = None,
                 resultado: Optional[dict] = None) -> bool:
    """Actualiza un envío pendiente; pasar a "curso" estampa el intento."""
    rfc = rfc.strip().upper()
    if estado is not None and estado not in ESTADOS_ENVIO:
        raise ValueError(f"estado inválido: {estado}")
    with _envios_lock:
        data = _load_envios(rfc)
        for e in data["envios"]:
            if e["id"] != envio_id:
                continue
            if estado == "curso":
                e["intentos"] = int(e.get("intentos") or 0) + 1
                e["ultimo_intento"] = datetime.now().isoformat(timespec="seconds")
            if estado is not None:
                e["estado"] = estado
            if archivos is not None:
                e["archivos"] = [str(a) for a in archivos]
            if error is not None:
                e["ultimo_error"] = str(error)[:500]
            if resultado is not None:
                e["resultado"] = resultado
            _save_envios(rfc, data)
            return True
        return False


def get_envios_pendientes(rfc: Optional[str] = None) -> list:
    """Envíos en estado "pendiente". Sin RFC recorre todas las empresas."""
    with _envios_lock:
        if rfc:
            rfcs = [rfc.strip().upper()]
        else:
            rfcs = sorted(p.stem for p in _envios_dir().glob("*.json"))
        out = []
        for r in rfcs:
            out.extend(e for e in _load_envios(r)["envios"]
                       if e.get("estado") == "pendiente")
        return out
