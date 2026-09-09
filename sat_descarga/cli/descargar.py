"""Comandos de descarga: flujo principal y retomar solicitudes."""

import click
from datetime import date, datetime

from . import config_store
from .empresas import _seleccionar_empresa
from .display import print_header, print_success, print_warning, print_error

from sat_descarga.core import paths

from sat_descarga import (
    descargar_cfdi,
    verificar_solicitud_existente,
    descargar_cfdi_ciec,
    descargar_cfdi_fiel,
    descargar_constancia_ciec,
    descargar_constancia_fiel,
    descargar_opinion_ciec,
    descargar_opinion_fiel,
    descargar_declaraciones_ciec,
    descargar_declaraciones_fiel,
    descargar_diot_ciec,
    descargar_diot_fiel,
)


TIPOS = {"E": "Emitidos", "R": "Recibidos"}
ESTADOS = {"V": "Vigente", "C": "Cancelado", "T": "Todos"}


def _parse_fecha(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def _rfc_de_cert(cer: str, key: str, password: str) -> str:
    """RFC del .cer (para componer la ruta en FIEL); '' si no se puede leer."""
    try:
        from sat_descarga.core.fiel import FIEL
        return FIEL(cer, key, password).rfc
    except Exception:
        return ""


def _prompt_rfc(rfc: str | None) -> str | None:
    """Resuelve RFC: usa el dado, el default, o pide interactivamente."""
    if rfc:
        return rfc
    default = config_store.get_default()
    empresas = config_store.list_empresas()
    if not empresas:
        print_error("No hay empresas registradas. Usa 'sat-dm empresas add'.")
        return None
    if len(empresas) == 1:
        return empresas[0]["rfc"]
    return _seleccionar_empresa("Selecciona empresa")


def _prompt_fechas(desde: str | None, hasta: str | None) -> tuple[date, date]:
    """Resuelve fechas: usa las dadas o pide interactivamente."""
    hoy = date.today()
    default_desde = f"{hoy.year}-01-01"
    default_hasta = hoy.strftime("%Y-%m-%d")

    if desde is None:
        desde = click.prompt("  Fecha inicio", default=default_desde)
    if hasta is None:
        hasta = click.prompt("  Fecha fin", default=default_hasta)

    return _parse_fecha(desde), _parse_fecha(hasta)


def _prompt_tipo(tipo: str | None) -> list[str]:
    """Resuelve tipo. Retorna lista de tipos a descargar."""
    if tipo is None:
        tipo = click.prompt(
            "  Tipo: (E)mitidos / (R)ecibidos / (A)mbos",
            default="A",
        )
    tipo = tipo.upper()
    if tipo == "A":
        return ["E", "R"]
    if tipo in ("E", "R"):
        return [tipo]
    print_error(f"Tipo inválido: {tipo}. Usa E, R o A.")
    raise click.Abort()


def _prompt_estado(estado: str | None) -> str:
    """Resuelve estado del comprobante."""
    if estado is None:
        estado = click.prompt(
            "  Estado: (V)igente / (C)ancelado / (T)odos",
            default="V",
        )
    estado = estado.upper()
    if estado in ESTADOS:
        return ESTADOS[estado]
    print_error(f"Estado inválido: {estado}. Usa V, C o T.")
    raise click.Abort()


def _ejecutar_descarga(
    empresa: dict,
    fecha_inicio: date,
    fecha_fin: date,
    tipo_comprobante: str,
    estado_comprobante: str,
    salida: str,
):
    """Ejecuta una descarga individual (emitidos o recibidos)."""
    rfc = empresa["rfc"]
    label = TIPOS[tipo_comprobante]
    directorio = str(paths.dir_cfdi(
        rfc, tipo_comprobante, fecha_inicio, fecha_fin, salida_base=salida,
    ))

    print_header(f"{label} — {rfc} ({fecha_inicio} a {fecha_fin})")

    try:
        zips = descargar_cfdi(
            cer_path=empresa["cer_path"],
            key_path=empresa["key_path"],
            password=empresa["password"],
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            tipo_solicitud="CFDI",
            tipo_comprobante=tipo_comprobante,
            estado_comprobante=estado_comprobante,
            directorio_salida=directorio,
            extraer=True,
        )

        if zips:
            print_success(f"{label}: {len(zips)} paquete(s) descargados en {directorio}")
            for z in zips:
                click.echo(f"    -> {z}")
        else:
            print_warning(f"{label}: Sin paquetes para descargar.")

        return True

    except RuntimeError as e:
        msg = str(e)
        if "5002" in msg or "agotado" in msg.lower():
            print_error(f"{label}: Solicitudes agotadas para este rango de fechas.")
            print_warning("Intenta de nuevo mas tarde o ajusta el rango.")
        else:
            print_error(f"{label}: {msg}")
        return False


@click.group()
def descargar():
    """Descargas del SAT: CFDIs (cfdi/ciec) y documentos (constancia, opinion)."""


@descargar.command(name="cfdi")
@click.option("--rfc", default=None, help="RFC de la empresa")
@click.option("--desde", default=None, help="Fecha inicio (YYYY-MM-DD)")
@click.option("--hasta", default=None, help="Fecha fin (YYYY-MM-DD)")
@click.option("--tipo", default=None, help="E=emitidos, R=recibidos, A=ambos")
@click.option("--estado", default=None, help="V=vigente, C=cancelado, T=todos")
@click.option("--salida", default=None, help="Directorio base de salida (default: descargas/)")
def descargar_cfdi_cmd(rfc, desde, hasta, tipo, estado, salida):
    """CFDIs vía el Web Service oficial (e-firma / FIEL)."""
    rfc = _prompt_rfc(rfc)
    if rfc is None:
        return

    try:
        empresa = config_store.get_empresa(rfc)
    except KeyError:
        print_error(f"Empresa {rfc} no registrada. Usa 'sat-dm empresas add'.")
        return

    print_header(f"Descarga Masiva — {empresa['nombre']} ({rfc})")

    fecha_inicio, fecha_fin = _prompt_fechas(desde, hasta)
    tipos = _prompt_tipo(tipo)
    estado_comprobante = _prompt_estado(estado)

    for t in tipos:
        _ejecutar_descarga(empresa, fecha_inicio, fecha_fin, t, estado_comprobante, salida)


@descargar.command(name="ciec")
@click.option("--rfc", default=None, help="RFC del contribuyente")
@click.option("--ciec", default=None, help="Contraseña CIEC (se pide oculta si falta)")
@click.option("--desde", default=None, help="Fecha inicio (YYYY-MM-DD)")
@click.option("--hasta", default=None, help="Fecha fin (YYYY-MM-DD)")
@click.option("--tipo", default="RE", help="R=recibidos, E=emitidos, RE=ambos")
@click.option("--salida", default=None, help="Directorio base de salida (default descargas/cfdi/<RFC>/)")
@click.option("--max-registros", default=2000, type=int, help="Tope de XMLs (cuota diaria del portal)")
@click.option("--ver-navegador", is_flag=True, default=False, help="Debug: mostrar el navegador (headful)")
def descargar_ciec_cmd(rfc, ciec, desde, hasta, tipo, salida, max_registros, ver_navegador):
    """CFDIs vía el portal web (CIEC). Tecleas el captcha en una mini-ventana; el navegador no se muestra."""
    if not rfc:
        rfc = click.prompt("  RFC")
    rfc = rfc.strip().upper()
    if not ciec:
        ciec = click.prompt("  Contraseña CIEC", hide_input=True)
    fecha_inicio, fecha_fin = _prompt_fechas(desde, hasta)
    # Base por RFC; la función CIEC anida {emitidos|recibidos}/{rango}/ debajo.
    salida = str(paths.dir_cfdi_base(rfc, salida_base=salida))

    print_header(f"Descarga CIEC — {rfc} ({fecha_inicio} a {fecha_fin}, tipo {tipo.upper()})")
    archivos = descargar_cfdi_ciec(
        rfc=rfc, ciec=ciec, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
        tipo_comprobante=tipo, directorio_salida=salida,
        max_registros=max_registros, headless=not ver_navegador,
    )
    if archivos:
        print_success(f"{len(archivos)} XML(s) descargados en {salida}")
    else:
        print_warning("No se descargaron XMLs.")


@descargar.command(name="fiel")
@click.option("--rfc", default=None,
              help="RFC del contribuyente (si está en el catálogo, toma cer/key/password de ahí)")
@click.option("--cer", type=click.Path(exists=True), default=None, help="Archivo .cer (e.firma)")
@click.option("--key", type=click.Path(exists=True), default=None, help="Archivo .key (e.firma)")
@click.option("--password", default=None, help="Contraseña de la clave privada (se pide oculta si falta)")
@click.option("--desde", default=None, help="Fecha inicio (YYYY-MM-DD)")
@click.option("--hasta", default=None, help="Fecha fin (YYYY-MM-DD)")
@click.option("--tipo", default="RE", help="R=recibidos, E=emitidos, RE=ambos")
@click.option("--salida", default=None, help="Directorio base de salida (default descargas/cfdi/<RFC>/)")
@click.option("--max-registros", default=2000, type=int, help="Tope de XMLs (cuota diaria del portal)")
@click.option("--ver-navegador", is_flag=True, default=False, help="Debug: mostrar el navegador (headful)")
def descargar_fiel_cmd(rfc, cer, key, password, desde, hasta, tipo, salida, max_registros, ver_navegador):
    """CFDIs vía el portal web usando e.firma. NO pide captcha (a diferencia de `descargar ciec`)."""
    # Si pasan --rfc y está en el catálogo, resolvemos cer/key/password desde ahí
    # (mismo patrón que `descargar cfdi` para WS). Si no, hace falta --cer/--key.
    if rfc and not (cer and key):
        rfc = rfc.strip().upper()
        try:
            empresa = config_store.get_empresa(rfc)
            cer = cer or empresa.get("cer_path")
            key = key or empresa.get("key_path")
            password = password or empresa.get("password")
        except KeyError:
            print_error(f"Empresa {rfc} no registrada. Pasa --cer/--key explícitamente.")
            raise click.Abort()
    if not cer or not key:
        print_error("Faltan credenciales. Pasa --rfc (empresa registrada) o --cer/--key.")
        raise click.Abort()
    if not password:
        password = click.prompt("  Contraseña de la clave privada", hide_input=True)

    # RFC para la ruta de salida: el del certificado (autoritativo).
    rfc_cert = _rfc_de_cert(cer, key, password) or (rfc or "")
    fecha_inicio, fecha_fin = _prompt_fechas(desde, hasta)
    salida = str(paths.dir_cfdi_base(rfc_cert, salida_base=salida))

    print_header(f"Descarga e.firma — {rfc_cert} ({fecha_inicio} a {fecha_fin}, tipo {tipo.upper()})")
    archivos = descargar_cfdi_fiel(
        cer_path=cer, key_path=key, password=password,
        fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
        tipo_comprobante=tipo, directorio_salida=salida,
        max_registros=max_registros, headless=not ver_navegador,
    )
    if archivos:
        print_success(f"{len(archivos)} XML(s) descargados en {salida}")
    else:
        print_warning("No se descargaron XMLs.")


@descargar.command(name="constancia")
@click.option("--metodo", type=click.Choice(["ciec", "fiel"]), default="ciec",
              help="Autenticación: ciec (captcha) o fiel (e.firma, automático)")
@click.option("--rfc", default=None, help="(metodo ciec) RFC")
@click.option("--ciec", default=None, help="(metodo ciec) Contraseña CIEC")
@click.option("--cer", type=click.Path(exists=True), default=None, help="(metodo fiel) archivo .cer")
@click.option("--key", type=click.Path(exists=True), default=None, help="(metodo fiel) archivo .key")
@click.option("--password", default=None, help="(metodo fiel) contraseña de la clave privada")
@click.option("--salida", default=None, help="Directorio base de salida (default descargas/<tipo>/<RFC>/)")
@click.option("--ver-navegador", is_flag=True, default=False, help="Debug: mostrar el navegador (headful)")
def descargar_constancia_cmd(metodo, rfc, ciec, cer, key, password, salida, ver_navegador):
    """Constancia de Situación Fiscal (PDF) vía CIEC o e.firma."""
    if metodo == "ciec":
        if not rfc:
            rfc = click.prompt("  RFC")
        rfc = rfc.strip().upper()
        if not ciec:
            ciec = click.prompt("  Contraseña CIEC", hide_input=True)
        salida = str(paths.dir_documento(paths.TIPO_CONSTANCIA, rfc, salida_base=salida))
        print_header(f"Constancia (CIEC) — {rfc}")
        pdf = descargar_constancia_ciec(
            rfc=rfc, ciec=ciec, directorio_salida=salida, headless=not ver_navegador,
        )
    else:  # fiel
        if not cer or not key:
            print_error("Con --metodo fiel debes pasar --cer y --key.")
            raise click.Abort()
        if not password:
            password = click.prompt("  Contraseña de la clave privada", hide_input=True)
        rfc = _rfc_de_cert(cer, key, password)  # ruta por RFC, igual que CIEC
        salida = str(paths.dir_documento(paths.TIPO_CONSTANCIA, rfc, salida_base=salida))
        print_header("Constancia (e.firma)")
        pdf = descargar_constancia_fiel(
            cer_path=cer, key_path=key, password=password,
            directorio_salida=salida, headless=not ver_navegador,
        )

    if pdf:
        print_success(f"Constancia descargada: {pdf}")
    else:
        print_error("No se pudo descargar la constancia (revisa el log).")
        raise click.Abort()


@descargar.command(name="opinion")
@click.option("--metodo", type=click.Choice(["ciec", "fiel"]), default="ciec",
              help="Autenticación: ciec (captcha) o fiel (e.firma, automático)")
@click.option("--rfc", default=None, help="(metodo ciec) RFC")
@click.option("--ciec", default=None, help="(metodo ciec) Contraseña CIEC")
@click.option("--cer", type=click.Path(exists=True), default=None, help="(metodo fiel) archivo .cer")
@click.option("--key", type=click.Path(exists=True), default=None, help="(metodo fiel) archivo .key")
@click.option("--password", default=None, help="(metodo fiel) contraseña de la clave privada")
@click.option("--salida", default=None, help="Directorio base de salida (default descargas/<tipo>/<RFC>/)")
@click.option("--ver-navegador", is_flag=True, default=False, help="Debug: mostrar el navegador (headful)")
def descargar_opinion_cmd(metodo, rfc, ciec, cer, key, password, salida, ver_navegador):
    """Reporte de Opinión de Cumplimiento 32-D (PDF) vía CIEC o e.firma."""
    if metodo == "ciec":
        if not rfc:
            rfc = click.prompt("  RFC")
        rfc = rfc.strip().upper()
        if not ciec:
            ciec = click.prompt("  Contraseña CIEC", hide_input=True)
        salida = str(paths.dir_documento(paths.TIPO_OPINION, rfc, salida_base=salida))
        print_header(f"Opinión 32-D (CIEC) — {rfc}")
        pdf = descargar_opinion_ciec(
            rfc=rfc, ciec=ciec, directorio_salida=salida, headless=not ver_navegador,
        )
    else:  # fiel
        if not cer or not key:
            print_error("Con --metodo fiel debes pasar --cer y --key.")
            raise click.Abort()
        if not password:
            password = click.prompt("  Contraseña de la clave privada", hide_input=True)
        rfc = _rfc_de_cert(cer, key, password)  # ruta por RFC, igual que CIEC
        salida = str(paths.dir_documento(paths.TIPO_OPINION, rfc, salida_base=salida))
        print_header("Opinión 32-D (e.firma)")
        pdf = descargar_opinion_fiel(
            cer_path=cer, key_path=key, password=password,
            directorio_salida=salida, headless=not ver_navegador,
        )

    if pdf:
        print_success(f"Opinión 32-D descargada: {pdf}")
    else:
        print_error("No se pudo descargar la opinión 32-D (revisa el log).")
        raise click.Abort()


@descargar.command(name="declaraciones")
@click.option("--metodo", type=click.Choice(["ciec", "fiel"]), default="fiel",
              help="Autenticación: fiel (e.firma, automático) o ciec (captcha)")
@click.option("--rfc", default=None,
              help="RFC del contribuyente (si está en el catálogo, toma cer/key/password de ahí)")
@click.option("--ciec", default=None, help="(metodo ciec) Contraseña CIEC")
@click.option("--cer", type=click.Path(exists=True), default=None, help="(metodo fiel) archivo .cer")
@click.option("--key", type=click.Path(exists=True), default=None, help="(metodo fiel) archivo .key")
@click.option("--password", default=None, help="(metodo fiel) contraseña de la clave privada")
@click.option("--desde", required=True, help="Primer periodo mensual (YYYY-MM)")
@click.option("--hasta", default=None, help="Último periodo mensual (YYYY-MM; default = --desde)")
@click.option("--tipo", type=click.Choice(["declaracion", "acuse", "ambos"]), default="ambos",
              help="Qué PDF bajar: la declaración, su acuse de recibo o ambos")
@click.option("--salida", default=None,
              help="Directorio base de salida (default descargas/declaracion/<RFC>/<YYYY-MM>/)")
@click.option("--ver-navegador", is_flag=True, default=False, help="Debug: mostrar el navegador (headful)")
def descargar_declaraciones_cmd(metodo, rfc, ciec, cer, key, password, desde, hasta, tipo,
                                salida, ver_navegador):
    """Declaraciones presentadas (Provisionales y Definitivas) y sus acuses, por periodo mensual."""
    rfc = (rfc or "").strip().upper() or None
    if metodo == "ciec":
        if not rfc:
            rfc = click.prompt("  RFC").strip().upper()
        if not ciec:
            try:
                ciec = config_store.get_empresa(rfc).get("ciec")
            except KeyError:
                ciec = None
        if not ciec:
            ciec = click.prompt("  Contraseña CIEC", hide_input=True)
        salida = str(paths.dir_declaraciones(rfc, salida_base=salida))
        print_header(f"Declaraciones (CIEC) — {rfc} ({desde} a {hasta or desde}, {tipo})")
        resultados = descargar_declaraciones_ciec(
            rfc=rfc, ciec=ciec, desde=desde, hasta=hasta, tipos=tipo,
            directorio_salida=salida, headless=not ver_navegador,
        )
    else:  # fiel
        if rfc and not (cer and key):
            try:
                empresa = config_store.get_empresa(rfc)
                cer = cer or empresa.get("cer_path")
                key = key or empresa.get("key_path")
                password = password or empresa.get("password")
            except KeyError:
                print_error(f"Empresa {rfc} no registrada. Pasa --cer/--key explícitamente.")
                raise click.Abort()
        if not cer or not key:
            print_error("Faltan credenciales. Pasa --rfc (empresa registrada) o --cer/--key.")
            raise click.Abort()
        if not password:
            password = click.prompt("  Contraseña de la clave privada", hide_input=True)
        rfc_cert = _rfc_de_cert(cer, key, password) or (rfc or "")
        salida = str(paths.dir_declaraciones(rfc_cert, salida_base=salida))
        print_header(f"Declaraciones (e.firma) — {rfc_cert} ({desde} a {hasta or desde}, {tipo})")
        resultados = descargar_declaraciones_fiel(
            cer_path=cer, key_path=key, password=password, desde=desde, hasta=hasta,
            tipos=tipo, directorio_salida=salida, headless=not ver_navegador,
        )

    _reportar_descargas(resultados, salida)


def _reportar_descargas(resultados, salida):
    """Imprime una línea por fila descargada y aborta si no bajó ningún PDF."""
    descargados = [r for r in resultados if r.get("archivo")]
    for r in resultados:
        marca = "✓" if r.get("archivo") else "✗"
        extra = f" + Excel {r['archivo_excel']}" if r.get("archivo_excel") else ""
        click.echo(f"  {marca} {r['periodo']} {r['tipo']:<11} op. {r['numero_operacion']} "
                   f"{r.get('tipo_declaracion', '')} {r.get('tipo_complementaria', '')} "
                   f"({r.get('fecha_presentacion', '')}) -> {r.get('archivo') or 'sin PDF'}{extra}")
    if descargados:
        print_success(f"{len(descargados)} PDF(s) en {salida}")
    else:
        print_error("No se descargó ningún PDF (revisa el log).")
        raise click.Abort()


@descargar.command(name="diot")
@click.option("--metodo", type=click.Choice(["ciec", "fiel"]), default="fiel",
              help="Autenticación: fiel (e.firma, automático) o ciec (captcha)")
@click.option("--rfc", default=None,
              help="RFC del contribuyente (si está en el catálogo, toma cer/key/password de ahí)")
@click.option("--ciec", default=None, help="(metodo ciec) Contraseña CIEC")
@click.option("--cer", type=click.Path(exists=True), default=None, help="(metodo fiel) archivo .cer")
@click.option("--key", type=click.Path(exists=True), default=None, help="(metodo fiel) archivo .key")
@click.option("--password", default=None, help="(metodo fiel) contraseña de la clave privada")
@click.option("--desde", required=True, help="Primer periodo mensual (YYYY-MM)")
@click.option("--hasta", default=None, help="Último periodo mensual (YYYY-MM; default = --desde)")
@click.option("--tipo", type=click.Choice(["declaracion", "acuse", "ambos"]), default="ambos",
              help="Qué bajar: la DIOT presentada (PDF + Excel), su acuse de recibo o ambos")
@click.option("--sin-excel", is_flag=True, default=False, help="No bajar el Excel de la declaración")
@click.option("--salida", default=None,
              help="Directorio base de salida (default descargas/diot/consultas/<RFC>/<YYYY-MM>/)")
@click.option("--ver-navegador", is_flag=True, default=False, help="Debug: mostrar el navegador (headful)")
def descargar_diot_cmd(metodo, rfc, ciec, cer, key, password, desde, hasta, tipo, sin_excel,
                       salida, ver_navegador):
    """DIOT presentadas (PDF + Excel) y sus acuses, por periodo mensual."""
    rfc = (rfc or "").strip().upper() or None
    if metodo == "ciec":
        if not rfc:
            rfc = click.prompt("  RFC").strip().upper()
        if not ciec:
            try:
                ciec = config_store.get_empresa(rfc).get("ciec")
            except KeyError:
                ciec = None
        if not ciec:
            ciec = click.prompt("  Contraseña CIEC", hide_input=True)
        salida = str(paths.dir_diot_consultas(rfc, salida_base=salida))
        print_header(f"DIOT presentadas (CIEC) — {rfc} ({desde} a {hasta or desde}, {tipo})")
        resultados = descargar_diot_ciec(
            rfc=rfc, ciec=ciec, desde=desde, hasta=hasta, tipos=tipo, excel=not sin_excel,
            directorio_salida=salida, headless=not ver_navegador,
        )
    else:  # fiel
        if rfc and not (cer and key):
            try:
                empresa = config_store.get_empresa(rfc)
                cer = cer or empresa.get("cer_path")
                key = key or empresa.get("key_path")
                password = password or empresa.get("password")
            except KeyError:
                print_error(f"Empresa {rfc} no registrada. Pasa --cer/--key explícitamente.")
                raise click.Abort()
        if not cer or not key:
            print_error("Faltan credenciales. Pasa --rfc (empresa registrada) o --cer/--key.")
            raise click.Abort()
        if not password:
            password = click.prompt("  Contraseña de la clave privada", hide_input=True)
        rfc_cert = _rfc_de_cert(cer, key, password) or (rfc or "")
        salida = str(paths.dir_diot_consultas(rfc_cert, salida_base=salida))
        print_header(f"DIOT presentadas (e.firma) — {rfc_cert} ({desde} a {hasta or desde}, {tipo})")
        resultados = descargar_diot_fiel(
            cer_path=cer, key_path=key, password=password, desde=desde, hasta=hasta,
            tipos=tipo, excel=not sin_excel, directorio_salida=salida, headless=not ver_navegador,
        )
    _reportar_descargas(resultados, salida)


@click.command()
@click.argument("id_solicitud")
@click.option("--rfc", default=None, help="RFC de la empresa")
@click.option("--salida", default=None, help="Directorio base de salida (default: descargas/)")
def retomar(id_solicitud, rfc, salida):
    """Retomar una solicitud previa por RequestID."""
    rfc = _prompt_rfc(rfc)
    if rfc is None:
        return

    try:
        empresa = config_store.get_empresa(rfc)
    except KeyError:
        print_error(f"Empresa {rfc} no registrada.")
        return

    print_header(f"Retomando solicitud {id_solicitud}")

    # Sin tipo/fechas conocidos (no se persisten hoy) → descargas/cfdi/{RFC}/.
    directorio = str(paths.dir_cfdi_base(rfc, salida_base=salida))

    try:
        zips = verificar_solicitud_existente(
            cer_path=empresa["cer_path"],
            key_path=empresa["key_path"],
            password=empresa["password"],
            id_solicitud=id_solicitud,
            directorio_salida=directorio,
            extraer=True,
            poll=True,
        )

        if zips:
            print_success(f"Descargados {len(zips)} paquete(s) en {directorio}")
            for z in zips:
                click.echo(f"    -> {z}")
        else:
            print_warning("Solicitud aun no lista.")

    except RuntimeError as e:
        print_error(f"Error: {e}")
