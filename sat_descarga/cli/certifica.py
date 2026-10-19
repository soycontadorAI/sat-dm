"""
Subcomandos del CLI para generar solicitudes de e.firma y CSD (equivalente a la
app "Certifica" del SAT):

    sat-dm generar fiel   --rfc ... --curp ... --correo ...   → .req + .key
    sat-dm renovar fiel   --cer ... --key ...                 → .ren + .key
    sat-dm solicitar csd  --cer ... --key ... --sucursal ...  → .sdg + .key

La generación es 100% local. El ENVÍO se hace aparte en CertiSAT Web
(https://www.sat.gob.mx → e.firma → "Renovación del certificado" / envío de CSD).
"""

import click

from .display import print_header, print_success, print_warning, print_error
from sat_descarga.certifica import (
    generar_requerimiento_fiel,
    generar_renovacion_fiel,
    generar_renovacion_fiel_moral,
    generar_solicitud_csd,
)


def _enviar_csd(cer, key, password, sdg_path, key_nueva, salida, ver_navegador, recuperar):
    """Sube un .sdg al portal e imprime el resultado (número de operación, acuse, cert)."""
    from sat_descarga.portal.csd import enviar_solicitud_csd_fiel

    print_warning("Subiendo el .sdg a CertiSAT Web (login con e.firma)…")
    res = enviar_solicitud_csd_fiel(
        cer, key, password, str(sdg_path),
        directorio_salida=str(salida) if salida else "./csd/",
        key_nueva_path=str(key_nueva) if key_nueva else None,
        headless=not ver_navegador, recuperar=recuperar,
    )
    if res.get("numero_operacion"):
        print_success(f"Número de operación: {res['numero_operacion']}")
    else:
        print_error("El SAT no devolvió número de operación (posible error transitorio; reintenta).")
    if res.get("estado"):
        print_success(f"Estado: {res['estado']}")
    if res.get("acuse_pdf"):
        print_success(f"Acuse: {res['acuse_pdf']}")
    if res.get("cer"):
        print_success(f"CSD emitido: {res['cer']}")
    elif recuperar:
        print_warning("El CSD aún no estaba disponible (tarda unos minutos). "
                      "Recupéralo luego con el mismo RFC en el portal.")
    return res


def _enviar_ren(cer, key, password, ren_path, key_nueva, salida, ver_navegador, recuperar):
    """Sube un .ren al portal (Renovación) e imprime el resultado."""
    from sat_descarga.portal.renovacion import enviar_renovacion_fiel

    print_warning("Subiendo el .ren a CertiSAT Web → «Renovación del certificado» (e.firma)…")
    res = enviar_renovacion_fiel(
        cer, key, password, str(ren_path),
        directorio_salida=str(salida) if salida else "./renovacion/",
        key_nueva_path=str(key_nueva) if key_nueva else None,
        headless=not ver_navegador, recuperar=recuperar,
    )
    if res.get("numero_operacion"):
        print_success(f"Número de operación: {res['numero_operacion']}")
    else:
        print_error("El SAT no devolvió número de operación (posible error transitorio; reintenta).")
    if res.get("estado"):
        print_success(f"Estado: {res['estado']}")
    if res.get("acuse_pdf"):
        print_success(f"Acuse: {res['acuse_pdf']}")
    if res.get("cer"):
        print_success(f"e.firma renovada (.cer nuevo): {res['cer']}")
        print_warning("Reemplaza tu .cer/.key por los NUEVOS; la e.firma anterior queda sustituida.")
    elif recuperar:
        print_warning("El .cer renovado aún no estaba disponible (tarda minutos). "
                      "Recupéralo luego con `sat-dm recuperar ren`.")
    return res


def _cargar_fiel(cer, key, password):
    from sat_descarga.core.fiel import FIEL

    if not password:
        password = click.prompt("Contraseña de la clave privada vigente", hide_input=True)
    return FIEL(cer, key, password)


def _nueva_password(nueva):
    if nueva:
        return nueva
    return click.prompt(
        "Contraseña para la NUEVA clave privada",
        hide_input=True,
        confirmation_prompt=True,
    )


def _reportar(res: dict, siguiente: str):
    for etiqueta, ruta in res.items():
        print_success(f"{etiqueta.upper()}: {ruta}")
    print_warning(siguiente)


# ---------------------------------------------------------------------------
# generar fiel  (e.firma nueva, sin e.firma previa)
# ---------------------------------------------------------------------------

@click.group()
def generar():
    """Genera archivos de solicitud de e.firma nueva (.req)."""


@generar.command("fiel")
@click.option("--rfc", required=True, help="RFC del contribuyente")
@click.option("--curp", default="", help="CURP (persona física)")
@click.option("--correo", required=True, help="Correo electrónico")
@click.option("--nueva-password", default=None, help="Contraseña de la nueva clave privada")
@click.option("--salida", default=None, help="Directorio de salida (default: actual)")
def generar_fiel_cmd(rfc, curp, correo, nueva_password, salida):
    """Requerimiento de Generación de e.firma (.req + .key nuevos)."""
    print_header("Generación de e.firma (.req)")
    res = generar_requerimiento_fiel(rfc, curp, correo, _nueva_password(nueva_password), salida)
    _reportar(res, "Envía el .req en CertiSAT Web (requiere cita/registro de e.firma en el SAT).")


# ---------------------------------------------------------------------------
# renovar fiel  (renovación con la e.firma vigente)
# ---------------------------------------------------------------------------

@click.group()
def renovar():
    """Renueva la e.firma vigente (genera el .ren para CertiSAT Web)."""


@renovar.command("fiel")
@click.option("--cer", type=click.Path(exists=True), required=True, help="Archivo .cer VIGENTE")
@click.option("--key", type=click.Path(exists=True), required=True, help="Archivo .key VIGENTE")
@click.option("--password", default=None, help="Contraseña de la clave privada vigente (se pide oculta si falta)")
@click.option("--correo", default=None, help="Correo para el nuevo requerimiento (default: el del cert)")
@click.option("--rfc-moral", default=None, help="RFC de la persona moral (renovación PM con representante legal)")
@click.option("--nueva-password", default=None, help="Contraseña de la nueva clave privada")
@click.option("--salida", default=None, help="Directorio de salida (default: actual)")
@click.option("--enviar", is_flag=True, default=False,
              help="Además de generar, sube el .ren a CertiSAT Web (¡RENUEVA tu e.firma!)")
@click.option("--sin-recuperar", is_flag=True, default=False,
              help="(con --enviar) no esperar/descargar el .cer renovado")
@click.option("--ver-navegador", is_flag=True, default=False, help="Debug: mostrar el navegador (headful)")
@click.option("--yes", is_flag=True, default=False, help="No pedir confirmación al enviar")
def renovar_fiel_cmd(cer, key, password, correo, rfc_moral, nueva_password, salida,
                     enviar, sin_recuperar, ver_navegador, yes):
    """Requerimiento de Renovación de e.firma (.ren + .key nuevos)."""
    print_header("Renovación de e.firma (.ren)")
    if not password:
        password = click.prompt("Contraseña de la clave privada vigente", hide_input=True)
    fiel = _cargar_fiel(cer, key, password)
    if not fiel.vigente:
        print_warning("El certificado ya está vencido; el SAT solo permite renovar antes de vencer.")
    nueva = _nueva_password(nueva_password)
    if rfc_moral:
        res = generar_renovacion_fiel_moral(fiel, rfc_moral, correo or "", nueva, salida)
    else:
        res = generar_renovacion_fiel(fiel, correo, nueva, salida)
    _reportar(res, "Sube el .ren en CertiSAT Web → «Renovación del certificado» (login con la e.firma vigente).")
    if enviar:
        if not yes:
            print_warning("Enviar el .ren RENUEVA tu e.firma: el certificado actual quedará "
                          "SUSTITUIDO y deberás usar el .cer nuevo + la .key recién generada.")
            if not click.confirm("¿Continuar con el envío al SAT?", default=False):
                print_warning("Envío cancelado. El .ren quedó generado; súbelo cuando decidas.")
                return
        _enviar_ren(cer, key, password, res["ren"], res["key"], salida,
                    ver_navegador, recuperar=not sin_recuperar)


# ---------------------------------------------------------------------------
# solicitar csd  (certificado de sello digital)
# ---------------------------------------------------------------------------

@click.group()
def solicitar():
    """Solicita certificados del SAT (CSD)."""


@solicitar.command("csd")
@click.option("--cer", type=click.Path(exists=True), required=True, help="Archivo .cer de la e.firma")
@click.option("--key", type=click.Path(exists=True), required=True, help="Archivo .key de la e.firma")
@click.option("--password", default=None, help="Contraseña de la clave privada (se pide oculta si falta)")
@click.option("--sucursal", required=True, help="Nombre de la sucursal/unidad (va en el OU del CSD)")
@click.option("--nueva-password", default=None, help="Contraseña de la nueva clave privada del sello")
@click.option("--salida", default=None, help="Directorio de salida (default: actual)")
@click.option("--enviar", is_flag=True, default=False,
              help="Además de generar, sube el .sdg a CertiSAT Web y recupera el CSD")
@click.option("--sin-recuperar", is_flag=True, default=False,
              help="(con --enviar) no esperar/descargar el .cer emitido")
@click.option("--ver-navegador", is_flag=True, default=False, help="Debug: mostrar el navegador (headful)")
def solicitar_csd_cmd(cer, key, password, sucursal, nueva_password, salida,
                      enviar, sin_recuperar, ver_navegador):
    """Solicitud de Certificado de Sello Digital (.sdg + .key nuevos)."""
    print_header("Solicitud de CSD (.sdg)")
    if not password:
        password = click.prompt("Contraseña de la clave privada vigente", hide_input=True)
    fiel = _cargar_fiel(cer, key, password)
    res = generar_solicitud_csd(fiel, sucursal, _nueva_password(nueva_password), salida)
    _reportar(res, "Sube el .sdg en CertiSAT Web → envío de solicitud de Certificados de Sello Digital.")
    if enviar:
        _enviar_csd(cer, key, password, res["sdg"], res["key"], salida,
                    ver_navegador, recuperar=not sin_recuperar)


@click.group()
def enviar():
    """Envía al portal del SAT solicitudes ya generadas (CSD)."""


@enviar.command("csd")
@click.option("--cer", type=click.Path(exists=True), required=True, help="Archivo .cer de la e.firma")
@click.option("--key", type=click.Path(exists=True), required=True, help="Archivo .key de la e.firma")
@click.option("--password", default=None, help="Contraseña de la clave privada (se pide oculta si falta)")
@click.option("--sdg", "sdg_path", type=click.Path(exists=True), required=True, help="Archivo .sdg a subir")
@click.option("--key-nueva", type=click.Path(exists=True), default=None,
              help="La .key generada junto al .sdg (para confirmar el CSD recuperado)")
@click.option("--salida", default=None, help="Directorio de salida (default: ./csd/)")
@click.option("--sin-recuperar", is_flag=True, default=False, help="No esperar/descargar el .cer emitido")
@click.option("--ver-navegador", is_flag=True, default=False, help="Debug: mostrar el navegador (headful)")
def enviar_csd_cmd(cer, key, password, sdg_path, key_nueva, salida, sin_recuperar, ver_navegador):
    """Sube un .sdg a CertiSAT Web y recupera el CSD emitido."""
    print_header("Envío de solicitud de CSD")
    if not password:
        password = click.prompt("Contraseña de la clave privada vigente", hide_input=True)
    _enviar_csd(cer, key, password, sdg_path, key_nueva, salida,
                ver_navegador, recuperar=not sin_recuperar)


@enviar.command("ren")
@click.option("--cer", type=click.Path(exists=True), required=True, help="Archivo .cer de la e.firma VIGENTE")
@click.option("--key", type=click.Path(exists=True), required=True, help="Archivo .key de la e.firma VIGENTE")
@click.option("--password", default=None, help="Contraseña de la clave privada (se pide oculta si falta)")
@click.option("--ren", "ren_path", type=click.Path(exists=True), required=True, help="Archivo .ren a subir")
@click.option("--key-nueva", type=click.Path(exists=True), default=None,
              help="La .key generada junto al .ren (para confirmar la e.firma renovada)")
@click.option("--salida", default=None, help="Directorio de salida (default: ./renovacion/)")
@click.option("--sin-recuperar", is_flag=True, default=False, help="No esperar/descargar el .cer renovado")
@click.option("--ver-navegador", is_flag=True, default=False, help="Debug: mostrar el navegador (headful)")
@click.option("--yes", is_flag=True, default=False, help="No pedir confirmación")
def enviar_ren_cmd(cer, key, password, ren_path, key_nueva, salida, sin_recuperar, ver_navegador, yes):
    """Sube un .ren a CertiSAT Web (¡RENUEVA tu e.firma!) y recupera el .cer nuevo."""
    print_header("Envío de renovación de e.firma")
    if not yes:
        print_warning("Esto RENUEVA tu e.firma: el certificado actual quedará SUSTITUIDO.")
        if not click.confirm("¿Continuar con el envío al SAT?", default=False):
            print_warning("Envío cancelado.")
            return
    if not password:
        password = click.prompt("Contraseña de la clave privada vigente", hide_input=True)
    _enviar_ren(cer, key, password, ren_path, key_nueva, salida,
                ver_navegador, recuperar=not sin_recuperar)


@click.group()
def recuperar():
    """Descarga certificados ya emitidos por el SAT (CSD, e.firma renovada)."""


@recuperar.command("csd")
@click.option("--cer", type=click.Path(exists=True), required=True, help="Archivo .cer de la e.firma")
@click.option("--key", type=click.Path(exists=True), required=True, help="Archivo .key de la e.firma")
@click.option("--password", default=None, help="Contraseña de la clave privada (se pide oculta si falta)")
@click.option("--key-nueva", type=click.Path(exists=True), default=None,
              help="La .key del sello (para confirmar que el CSD recuperado es el correcto)")
@click.option("--salida", default=None, help="Directorio de salida (default: ./csd/)")
@click.option("--ver-navegador", is_flag=True, default=False, help="Debug: mostrar el navegador (headful)")
def recuperar_csd_cmd(cer, key, password, key_nueva, salida, ver_navegador):
    """Descarga el último CSD emitido del RFC (útil cuando tardó en publicarse)."""
    from sat_descarga.portal.csd import recuperar_ultimo_csd_fiel

    print_header("Recuperación de CSD")
    if not password:
        password = click.prompt("Contraseña de la clave privada vigente", hide_input=True)
    res = recuperar_ultimo_csd_fiel(
        cer, key, password,
        directorio_salida=str(salida) if salida else "./csd/",
        key_nueva_path=str(key_nueva) if key_nueva else None,
        headless=not ver_navegador,
    )
    if res.get("cer"):
        print_success(f"CSD descargado: {res['cer']}")
    else:
        print_warning("No se encontró/descargó el CSD (¿aún no se publica? reintenta en unos minutos).")


@recuperar.command("ren")
@click.option("--cer", type=click.Path(exists=True), required=True, help="Archivo .cer de la e.firma para autenticar")
@click.option("--key", type=click.Path(exists=True), required=True, help="Archivo .key de la e.firma para autenticar")
@click.option("--password", default=None, help="Contraseña de la clave privada (se pide oculta si falta)")
@click.option("--key-nueva", type=click.Path(exists=True), default=None,
              help="La .key nueva del .ren (para confirmar la e.firma renovada)")
@click.option("--salida", default=None, help="Directorio de salida (default: ./renovacion/)")
@click.option("--publica", is_flag=True, default=False,
              help="Buscar en la Recuperación pública del SAT (sin login, con captcha). "
                   "Úsalo cuando la e.firma anterior ya quedó revocada; requiere --key-nueva.")
@click.option("--ver-navegador", is_flag=True, default=False, help="Debug: mostrar el navegador (headful)")
def recuperar_ren_cmd(cer, key, password, key_nueva, salida, publica, ver_navegador):
    """Descarga el .cer de la e.firma renovada (útil cuando tardó en publicarse)."""
    print_header("Recuperación de e.firma renovada")
    if not password:
        password = click.prompt("Contraseña de la clave privada vigente", hide_input=True)
    directorio = str(salida) if salida else "./renovacion/"

    if publica:
        # Al emitir la e.firma nueva el SAT revoca la anterior y con ella ya no
        # se entra a CertiSAT: se busca por RFC en el servicio público.
        from functools import partial

        from sat_descarga.core.fiel import FIEL
        from sat_descarga.portal.captcha import pedir_captcha
        from sat_descarga.portal.recuperacion_publica import recuperar_cert_emparejado

        if not key_nueva:
            print_error("--publica requiere --key-nueva (la .key generada junto al .ren).")
            raise SystemExit(1)
        rfc = FIEL(cer, key, password).rfc
        cer_nuevo = recuperar_cert_emparejado(
            rfc, str(key_nueva), password,
            partial(pedir_captcha, respetar_mayusculas=True), directorio,
        )
        if cer_nuevo:
            print_success(f".cer renovado descargado: {cer_nuevo}")
        else:
            print_warning("El SAT todavía no publica un certificado que empareje con la "
                          ".key nueva. Reintenta en unos minutos.")
        return

    from sat_descarga.portal.renovacion import recuperar_renovacion_fiel

    res = recuperar_renovacion_fiel(
        cer, key, password,
        directorio_salida=directorio,
        key_nueva_path=str(key_nueva) if key_nueva else None,
        headless=not ver_navegador,
    )
    if res.get("cer"):
        print_success(f".cer renovado descargado: {res['cer']}")
    else:
        print_warning("No se encontró/descargó el .cer (¿aún no se publica? Si la e.firma "
                      "anterior ya quedó revocada, usa --publica).")
