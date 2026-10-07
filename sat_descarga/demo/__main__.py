"""
Comandos del modo de grabación.

    python -m sat_descarga.demo perfil [--dir DIR]      # variables de un perfil aparte
    python -m sat_descarga.demo efirma --salida DIR      # .cer/.key de ejemplo para el alta (⌘N)
    python -m sat_descarga.demo sembrar [--sin RFC] [--con-septiembre]
    python -m sat_descarga.demo estado
    python -m sat_descarga.demo limpiar
    python -m sat_descarga.demo carpeta-xml --salida DIR  # "XML 2022 a 2025" del Organizador
    python -m sat_descarga.demo fixtures --salida DIR [--rfc RFC] [--mes AAAA-MM]

`sembrar` exige SAT_DM_MODO_GRABACION=1 (y, recomendado, el perfil aparte de
`perfil` para no mezclar con el catálogo real del equipo).
"""

from __future__ import annotations

import argparse
import base64
import os
import shlex
import sys
from pathlib import Path

from . import ENV_ESPERA, ENV_MODO, activo, espera_ws
from .escenario import CIEC_DEMO, EL_ROBLE, EMPRESAS, PASSWORD_EFIRMA


def _perfil(args) -> int:
    raiz = Path(args.dir).expanduser().resolve()
    raiz.mkdir(parents=True, exist_ok=True)
    clave_txt = raiz / "clave-secretos.txt"
    if not clave_txt.exists():
        clave_txt.write_text(base64.b64encode(os.urandom(32)).decode() + "\n", encoding="utf-8")
        try:
            clave_txt.chmod(0o600)
        except OSError:
            pass
    clave = clave_txt.read_text(encoding="utf-8").strip()
    lineas = {
        ENV_MODO: "1",
        "SAT_DM_CONFIG_DIR": str(raiz / "config"),
        "SAT_DM_DESCARGAS_DIR": str(raiz / "Descargas"),
        # Credenciales del perfil en un archivo cifrado (no en el llavero del
        # equipo): no pisa la sesión real ni pide permisos del llavero.
        "SAT_DM_SECRETS_KEY": clave,
    }
    for k, v in lineas.items():
        print(f"export {k}={shlex.quote(v)}")
    print("# Uso: eval \"$(python -m sat_descarga.demo perfil)\" y arranca la app en esa terminal.",
          file=sys.stderr)
    return 0


def _efirma(args) -> int:
    from . import efirma

    salida = Path(args.salida).expanduser()
    rfcs = [args.rfc.upper()] if args.rfc else [r for r, e in EMPRESAS.items() if "fiel" in e.accesos]
    for rfc in rfcs:
        if rfc not in EMPRESAS:
            print(f"{rfc} no es una empresa de demo.", file=sys.stderr)
            return 2
        cer, key, _ = efirma.generar(rfc, salida)
        print(f"{EMPRESAS[rfc].nombre}: {cer.name} + {key.name}")
    (salida / "LEEME.txt").write_text(
        "e.firmas de ejemplo del modo de grabación de TodoConta.\n"
        "Certificados autofirmados: no sirven ante el SAT y la app solo los acepta\n"
        f"con {ENV_MODO}=1.\n\n"
        f"Contraseña de la llave privada (.key): {PASSWORD_EFIRMA}\n"
        f"Contraseña del SAT de ejemplo (Transportes Molina): {CIEC_DEMO}\n",
        encoding="utf-8",
    )
    print(f"Contraseña de las .key: {PASSWORD_EFIRMA}  (también en {salida / 'LEEME.txt'})")
    return 0


def _sembrar(args) -> int:
    from .siembra import ModoApagado, sembrar

    try:
        sembrar(excluir=args.sin or (), con_septiembre=args.con_septiembre)
    except ModoApagado as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


def _estado(args) -> int:
    from ..cli import config_store

    print(f"Modo de grabación: {'PRENDIDO' if activo() else 'apagado'} ({ENV_MODO})")
    print(f"Espera del Web Service de demo: {espera_ws():.0f} s ({ENV_ESPERA})")
    print(f"Perfil: {config_store.get_config_dir()}")
    print(f"Descargas: {config_store.get_descargas_dir()}")
    catalogo = {e["rfc"]: e for e in config_store.list_empresas()}
    reales = [r for r in catalogo if r not in EMPRESAS]
    print("Empresas de demo en el catálogo:")
    for rfc, emp in EMPRESAS.items():
        e = catalogo.get(rfc)
        if e is None:
            print(f"  - {emp.nombre} ({rfc}): no está")
            continue
        print(f"  - {emp.nombre} ({rfc}): {', '.join(e['metodos'])}; "
              f"e.firma vence {e.get('vencimiento') or 'sin e.firma'}; "
              f"32-D {e.get('opinion_status') or ('sin analizar' if e.get('opinion_path') else 'sin bajar')}; "
              f"constancia {'sí' if e.get('csf_path') else 'no'}")
    if reales:
        print(f"Además hay {len(reales)} empresa(s) reales en este perfil (no se tocan).")
    return 0


def _limpiar(args) -> int:
    from .siembra import limpiar

    limpiar()
    return 0


def _carpeta_xml(args) -> int:
    from .siembra import carpeta_xml

    n = carpeta_xml(Path(args.salida).expanduser())
    print(f"{n} XML (con duplicados) en {args.salida}")
    return 0


def _fixtures(args) -> int:
    """Vuelca los fixtures (XML, metadata y PDF) a una carpeta para revisarlos."""
    from . import cfdi, documentos

    salida = Path(args.salida).expanduser()
    anio, mes = (int(x) for x in args.mes.split("-"))
    rfcs = [args.rfc.upper()] if args.rfc else list(EMPRESAS)
    for rfc in rfcs:
        comps = cfdi.comprobantes(rfc, anio, mes)
        for tipo, carpeta in (("R", "recibidos"), ("E", "emitidos")):
            d = salida / rfc / f"{anio}-{mes:02d}" / carpeta
            d.mkdir(parents=True, exist_ok=True)
            for c in comps:
                if c.direccion == tipo:
                    (d / cfdi.nombre_archivo(c)).write_bytes(cfdi.xml(c))
        (salida / rfc / f"{anio}-{mes:02d}" / "metadata.txt").write_bytes(cfdi.metadata_txt(comps))
        documentos.constancia_pdf(rfc, salida / rfc / f"constancia_{rfc}.pdf")
        documentos.opinion_pdf(rfc, salida / rfc / f"opinion32d_{rfc}.pdf")
        cancelados = cfdi.cancelados_despues(rfc, anio, mes)
        print(f"{rfc}: {len(comps)} CFDIs de {mes:02d}/{anio}"
              + (f", {len(cancelados)} se cancelan después" if cancelados else ""))
    _texto, png = documentos.captcha_png(semilla=7)
    (salida / "captcha.png").write_bytes(png)
    print(f"Listo en {salida}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sat_descarga.demo",
                                     description="Modo de grabación de TodoConta.")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("perfil", help="variables de entorno de un perfil de grabación aparte")
    p.add_argument("--dir", default=str(Path.home() / "TodoConta-grabacion"))
    p.set_defaults(fn=_perfil)

    p = sub.add_parser("efirma", help="e.firmas de ejemplo para dar de alta a mano (⌘N)")
    p.add_argument("--salida", required=True)
    p.add_argument("--rfc", help=f"solo esta empresa (p. ej. {EL_ROBLE})")
    p.set_defaults(fn=_efirma)

    p = sub.add_parser("sembrar", help="empresas de demo, documentos e historial")
    p.add_argument("--sin", action="append", metavar="RFC",
                   help="no sembrar esta empresa (repetible)")
    p.add_argument("--con-septiembre", action="store_true",
                   help="deja ya descargados los recibidos de septiembre de El Roble")
    p.set_defaults(fn=_sembrar)

    p = sub.add_parser("estado", help="qué hay sembrado y con qué perfil")
    p.set_defaults(fn=_estado)

    p = sub.add_parser("limpiar", help="quita las empresas de demo (solo esas)")
    p.set_defaults(fn=_limpiar)

    p = sub.add_parser("carpeta-xml", help="carpeta de XML viejos con duplicados (Organizador)")
    p.add_argument("--salida", required=True)
    p.set_defaults(fn=_carpeta_xml)

    p = sub.add_parser("fixtures", help="vuelca XML, metadata y PDF de ejemplo a una carpeta")
    p.add_argument("--salida", required=True)
    p.add_argument("--rfc")
    p.add_argument("--mes", default="2026-09", help="AAAA-MM (default 2026-09)")
    p.set_defaults(fn=_fixtures)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
