# -*- mode: python ; coding: utf-8 -*-
"""
Spec de PyInstaller para empaquetar el agente FastAPI como `sat-agent.exe`
distribuible junto al shell Electron.

Uso:
    pyinstaller packaging/sat-agent.spec --noconfirm --clean

Salida:
    Windows/Linux (onedir):
        packaging/dist/sat-agent/sat-agent[.exe]  # binario + dlls/pyd en carpeta
    macOS (onefile):
        packaging/dist/sat-agent                  # un solo binario
    packaging/build/                              # artefactos intermedios

El binario se invoca con:
    sat-agent[.exe] --port <N>

Decisiones — `onedir` en Windows/Linux, `onefile` en macOS (`MODO_ONEFILE`):
- **onedir (Windows/Linux)** — un .exe + dlls en carpeta. Razones:
    1. `onefile` extrae a %TEMP% en cada arranque (1-3s extra de latencia).
    2. Antivirus marcan más frecuentemente los `onefile`.
    3. Patches/updates más fáciles en carpeta (electron-updater reemplaza la
       carpeta completa).
- **onefile (macOS)** — un solo binario. Razón: firmar el bundle para
  notarización recorre y firma CADA Mach-O anidado, y cada `codesign --timestamp`
  pega al servidor de timestamps de Apple (que estrangula a los runners de CI).
  Con onedir son cientos de archivos → la firma revienta el timeout del job (45
  min). Con onefile es UN binario → firma en segundos. El hardened runtime carga
  los dylibs extraídos gracias a `disable-library-validation` en los entitlements
  (ya presente en desktop/build/entitlements.mac.plist).
- Playwright SÍ está incluido (sus driver/binding); el navegador Chromium se
  descarga en runtime (ver `sat_descarga/portal/setup.py`).
- Pesados excluidos: pillow, tkinter, matplotlib, IPython.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Path al root del repo: el spec vive en `packaging/`, así que ..  es la raíz.
REPO_ROOT = Path(SPECPATH).parent  # type: ignore[name-defined]
ENTRY = REPO_ROOT / "sat_descarga" / "api" / "__main__.py"

# -----------------------------------------------------------------------------
# Datas (archivos no-Python que el agente necesita en runtime)
# -----------------------------------------------------------------------------

datas: list[tuple[str, str]] = []

# Migraciones SQL del procesador (leídas con Path(__file__).parent / "migrations").
migrations_dir = REPO_ROOT / "sat_descarga" / "procesador" / "migrations"
if migrations_dir.exists():
    for sql in migrations_dir.glob("*.sql"):
        datas.append((str(sql), "sat_descarga/procesador/migrations"))
    readme = migrations_dir / "README.md"
    if readme.exists():
        datas.append((str(readme), "sat_descarga/procesador/migrations"))

# Driver de Playwright (node + cli + package.json). Sin esto sync_playwright()
# revienta porque no encuentra el driver embebido. Chromium NO se incluye —
# se descarga en runtime (ver portal/setup.py). OJO: portal/setup.py también
# depende de `driver/package/browsers.json` (revisiones exactas de browsers)
# que viaja en estos datas — no excluirlo.
datas.extend(collect_data_files("playwright", include_py_files=False))


# -----------------------------------------------------------------------------
# Hidden imports (paquetes detectados como dinámicos por PyInstaller)
# -----------------------------------------------------------------------------

hiddenimports: list[str] = [
    # uvicorn — loops y protocols se cargan por nombre
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    # pydantic
    "pydantic.deprecated.decorator",
    "pydantic_core",
    # lxml (Windows pierde imports dinámicos de xpath)
    "lxml._elementpath",
    "lxml.etree",
    "lxml.html",
    # email (FastAPI multipart upload)
    "email.mime.multipart",
    "email.mime.text",
    "email.mime.base",
    "email.mime.application",
    # python-multipart (uploads)
    "multipart",
    # keyring backends — SIN ESTOS el `keyring` cae a un backend null que
    # silenciosamente retorna None. En Windows era además una de las fuentes
    # del hang del lifespan. Forzar los nativos para que estén en el bundle.
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.fail",
    # playwright (driver runtime)
    "playwright.sync_api",
    "playwright._impl._driver",
    "playwright._impl._connection",
    "playwright._impl._helper",
    "playwright._impl._api_types",
    # fpdf2 (export PDF de calculadoras; importado dentro de los endpoints)
    "fpdf",
    "fpdf.fpdf",
    # Internos del agente (importados dinámicamente desde server.py)
    "sat_descarga.cli.config_store",
    "sat_descarga.cli.empresas",
    "sat_descarga.procesador",
    "sat_descarga.procesador.db",
    "sat_descarga.procesador.cfdi_parser",
    "sat_descarga.procesador.exportar",
    "sat_descarga.procesador.exportar_pagos",
    "sat_descarga.procesador.exportar_nomina",
    "sat_descarga.procesador.reportes_cfdi",
    "sat_descarga.procesador.reportes_pagos",
    "sat_descarga.procesador.reportes_nomina",
    "sat_descarga.portal.setup",
    "sat_descarga.portal.cfdi",
    "sat_descarga.portal.constancia",
    "sat_descarga.portal.opinion",
    "sat_descarga.portal.login",
    "sat_descarga.calculadoras",
    "sat_descarga.calculadoras.exportar",
    "sat_descarga.calculadoras.store",
    # Modo de grabación (SAT_DM_MODO_GRABACION=1): se importa dentro de las
    # funciones que hablan con el SAT, solo cuando aplica.
    "sat_descarga.demo",
    "sat_descarga.demo.escenario",
    "sat_descarga.demo.catalogo",
    "sat_descarga.demo.cfdi",
    "sat_descarga.demo.documentos",
    "sat_descarga.demo.efirma",
    "sat_descarga.demo.sat",
    "sat_descarga.demo.siembra",
    "fpdf.table",
    "fpdf.fonts",
]

# Recolectar todos los submódulos de uvicorn y playwright (cinturón + tirantes).
hiddenimports.extend(collect_submodules("uvicorn"))
hiddenimports.extend(collect_submodules("playwright"))

# -----------------------------------------------------------------------------
# Excludes (paquetes que NO queremos en el bundle — ahorro de tamaño)
# -----------------------------------------------------------------------------

excludes: list[str] = [
    "pillow",
    "PIL",
    "tkinter",
    "matplotlib",
    "IPython",
    "jedi",
    "pytest",
    "setuptools",
    # supabase: solo lo usa `hosted.py` (Railway/cloud), no el agente local.
    "supabase",
    "gotrue",
    "postgrest",
    "storage3",
    "realtime",
    # dotenv: idem
    "python_dotenv",
    "dotenv",
]


# -----------------------------------------------------------------------------
# Analysis + EXE + COLLECT
# -----------------------------------------------------------------------------

a = Analysis(  # noqa: F821 — PyInstaller inyecta esto
    [str(ENTRY)],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

# onefile solo en macOS (firma rápida para notarización); onedir en Windows/Linux.
MODO_ONEFILE = sys.platform == "darwin"

# Notas comunes a ambos modos:
# - upx=False: UPX a veces dispara antivirus.
# - console=False: en Windows producción ya no se abre una ventana negra DOS
#   paralela al .exe (confunde a usuarios — "¿es virus?"). Los logs se persisten
#   a %LOCALAPPDATA%\TodoConta\logs\agent.log desde __main__.py. En dev no aplica.

if MODO_ONEFILE:
    exe = EXE(  # noqa: F821
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="sat-agent",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
else:
    exe = EXE(  # noqa: F821
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="sat-agent",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )

    coll = COLLECT(  # noqa: F821
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="sat-agent",
    )
