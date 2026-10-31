"""Genera el PDF de una cotización de marca TodoConta.

Plantilla en la marca Señal (`DESIGN.md` de todoconta-apps): papel con retícula de
puntos, tarjeta blanca con regla de 1 px, tinta `#10141B`, Geist y Geist Mono para
cifras, sentence case y el total en la tarjeta de tinta. No lleva cian: el cian es
solo para lo automático y una cotización no lo es. Se renderiza a bytes PDF con
Chromium headless vía Playwright. Las fuentes y el logo se **embeben como data-URI**
para que el render sea determinista y offline (sin depender de Google Fonts ni de
fuentes del sistema en el contenedor slim).

API:
    total_de(items) -> float
    construir_html(datos) -> str      # útil para inspección / pruebas sin Chromium
    render(datos) -> bytes            # HTML -> PDF (requiere Playwright + Chromium)

`datos` es un dict:
    {
      "emisor": {...},               # lib/emisor.cargar(...)
      "folio": "COT-NOMITEK-2026-08",
      "fecha": "05 de agosto de 2026",
      "vigenciaDias": 15,
      "cliente": {"nombre","atencion"(opc),"email","rfc"(opc)},
      "items": [{"concepto","cantidad","precioUnitario"}, ...],
      "notaIva": "..."(opc),
      "condiciones": [...](opc),      # default: emisor["condicionesDefault"]
    }
"""

from __future__ import annotations

import base64
import html as html_mod
from functools import lru_cache
from pathlib import Path

# /app/lib/cotizacion_pdf.py -> base = /app ; fuentes en /app/assets/fonts
_BASE = Path(__file__).resolve().parent.parent
_ASSETS = _BASE / "assets"
_FONTS = _ASSETS / "fonts"

# El logo Libro Mayor es de TodoConta: otra marca (p. ej. soycontador.ai) lleva su
# nombre en texto, nunca el logo equivocado.
_LOGOS = {"TodoConta": "logo-lockup.svg"}


@lru_cache(maxsize=8)
def _b64(ruta: Path) -> str:
    return base64.b64encode(ruta.read_bytes()).decode("ascii")


def _escape(valor: object) -> str:
    return html_mod.escape(str(valor), quote=True)


def _money(monto: float) -> str:
    """$1,234.56 con separador de miles y 2 decimales."""
    return "$" + f"{monto:,.2f}"


def total_de(items: list[dict]) -> float:
    return sum(float(it["cantidad"]) * float(it["precioUnitario"]) for it in items)


def _bloque_fuentes() -> str:
    geist = _b64(_FONTS / "Geist-latin.woff2")
    mono = _b64(_FONTS / "GeistMono-latin.woff2")
    return f"""
    @font-face {{
      font-family: "Geist"; font-style: normal; font-weight: 100 900;
      font-display: block; src: url(data:font/woff2;base64,{geist}) format("woff2");
    }}
    @font-face {{
      font-family: "Geist Mono"; font-style: normal; font-weight: 100 900;
      font-display: block; src: url(data:font/woff2;base64,{mono}) format("woff2");
    }}
    """


def _marca_html(emisor: dict) -> str:
    """Logo (si la marca lo tiene) o nombre en texto, más la submarca."""
    logo = _LOGOS.get(str(emisor["marca"]))
    if logo and (_ASSETS / logo).exists():
        pieza = (
            f'<img class="logo" alt="{_escape(emisor["marca"])}" '
            f'src="data:image/svg+xml;base64,{_b64(_ASSETS / logo)}">'
        )
    else:
        pieza = f'<div class="wordmark">{_escape(emisor["marca"])}</div>'
    return f'{pieza}<div class="sub">{_escape(emisor["submarca"])}</div>'


def construir_html(datos: dict) -> str:
    emisor = datos["emisor"]
    cliente = datos["cliente"]
    items = datos["items"]
    vigencia = datos.get("vigenciaDias", emisor.get("vigenciaDias", 15))
    nota_iva = datos.get("notaIva") or emisor.get(
        "notaIva", "Precios en pesos mexicanos (MXN), IVA incluido."
    )
    condiciones = datos.get("condiciones") or emisor.get("condicionesDefault", [])
    banco = emisor["banco"]
    total = total_de(items)

    filas = "".join(
        f"""
        <tr>
          <td>{_escape(it["concepto"])}</td>
          <td class="num mono">{_escape(it["cantidad"])}</td>
          <td class="num mono">{_escape(_money(float(it["precioUnitario"])))}</td>
          <td class="num mono">{_escape(_money(float(it["cantidad"]) * float(it["precioUnitario"])))}</td>
        </tr>"""
        for it in items
    )

    lista_cond = "".join(f"<li>{_escape(c)}</li>" for c in condiciones)

    atencion = (
        f'<p class="dim">Atención: {_escape(cliente["atencion"])}</p>'
        if cliente.get("atencion")
        else ""
    )
    cliente_rfc = (
        f'<p class="dim">RFC <span class="mono ink">{_escape(cliente["rfc"])}</span></p>'
        if cliente.get("rfc")
        else ""
    )
    # Nombre corto del emisor para el pie (primeras 2 palabras).
    pie_nombre = " ".join(str(emisor["nombre"]).split()[:2])

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Cotización {_escape(cliente["nombre"])}</title>
<style>
  {_bloque_fuentes()}
  @page {{ size: A4; margin: 0; }}
  * {{ box-sizing: border-box; }}
  :root {{
    --bg: #F5F6F8; --bg-dot: #D5DAE2; --card: #FFFFFF; --rule: #DDE1E7; --rule-soft: #ECEFF3;
    --ink: #10141B; --soft: #4A5260; --ghost: #626A78;
    --on-dark: #EEF1F5; --on-dark-soft: #AEB6C2;
  }}
  html, body {{ margin: 0; }}
  body {{
    font-family: "Geist", -apple-system, "Helvetica Neue", Arial, sans-serif;
    color: var(--ink); font-size: 13.5px; line-height: 1.5;
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }}
  .mono {{ font-family: "Geist Mono", ui-monospace, Menlo, monospace; font-weight: 500; font-variant-numeric: tabular-nums; font-size: .94em; }}
  .ink {{ color: var(--ink); }}
  .page {{
    width: 210mm; min-height: 297mm; padding: 12mm; background: var(--bg);
    background-image: radial-gradient(var(--bg-dot) 1px, transparent 1.3px); background-size: 22px 22px;
  }}
  .sheet {{
    background: var(--card); border: 1px solid var(--rule); border-radius: 14px; padding: 11mm 12mm;
    box-shadow: 0 1px 2px rgba(16, 20, 27, .05), 0 14px 34px -16px rgba(16, 20, 27, .18);
  }}
  .head {{
    display: flex; justify-content: space-between; align-items: flex-start;
    padding-bottom: 20px; border-bottom: 1px solid var(--ink); margin-bottom: 24px;
  }}
  .logo {{ height: 46px; margin-left: -5px; display: block; }}
  .wordmark {{ font-size: 26px; font-weight: 800; letter-spacing: -.03em; line-height: 46px; }}
  .sub {{ color: var(--soft); font-size: 12.5px; margin-top: 4px; }}
  .title {{ text-align: right; }}
  .title h1 {{ margin: 0 0 8px; font-size: 34px; font-weight: 800; letter-spacing: -.03em; line-height: 1; }}
  .meta {{ color: var(--soft); font-size: 12.5px; line-height: 1.7; }}
  .meta .mono {{ color: var(--ink); }}
  .parties {{ display: flex; gap: 16px; margin-bottom: 24px; }}
  .party {{ flex: 1; border: 1px solid var(--rule); border-radius: 14px; padding: 14px 18px; }}
  .label {{ font-size: 13px; font-weight: 600; color: var(--soft); margin: 0 0 8px; }}
  .party p {{ margin: 0; }}
  .party .name {{ font-weight: 700; font-size: 15px; letter-spacing: -.015em; margin-bottom: 2px; }}
  .dim {{ color: var(--soft); }}
  table.items {{ width: 100%; border-collapse: collapse; }}
  table.items th {{ text-align: left; font-size: 13px; font-weight: 600; color: var(--soft); padding: 0 0 10px; border-bottom: 1px solid var(--rule); }}
  table.items th.num, table.items td.num {{ text-align: right; white-space: nowrap; padding-left: 18px; }}
  table.items th:nth-child(2) {{ width: 74px; }}
  table.items th:nth-child(3) {{ width: 128px; }}
  table.items th:nth-child(4) {{ width: 112px; }}
  table.items td {{ padding: 14px 0; border-bottom: 1px solid var(--rule-soft); vertical-align: top; }}
  table.items td:first-child {{ padding-right: 16px; font-weight: 500; }}
  .note {{ color: var(--ghost); font-size: 12px; margin: 10px 0 22px; }}
  .total {{
    background: var(--ink); color: var(--on-dark); border-radius: 16px; padding: 20px 24px;
    display: flex; justify-content: space-between; align-items: center;
    box-shadow: inset 0 0 0 1px rgba(238, 241, 245, .1); margin-bottom: 22px;
  }}
  .total .k {{ font-size: 14px; font-weight: 600; color: var(--on-dark-soft); }}
  .total .s {{ font-size: 12.5px; color: var(--on-dark-soft); margin-top: 2px; }}
  .total .amt {{ font-family: "Geist Mono", monospace; font-weight: 500; font-size: 34px; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }}
  .cols {{ display: flex; gap: 16px; }}
  .box {{ flex: 1; border: 1px solid var(--rule); border-radius: 14px; padding: 14px 18px; }}
  .row {{ display: flex; justify-content: space-between; gap: 12px; padding: 4px 0; }}
  .row .k {{ color: var(--soft); }}
  .row .v {{ font-weight: 600; text-align: right; }}
  .box ul {{ margin: 0; padding-left: 17px; }}
  .box li {{ margin-bottom: 6px; }}
  .box li::marker {{ color: var(--ghost); }}
  .foot {{
    margin-top: 20px; padding-top: 12px; border-top: 1px solid var(--rule-soft);
    display: flex; justify-content: space-between; color: var(--ghost); font-size: 12px;
  }}
</style>
</head>
<body>
  <div class="page"><div class="sheet">
    <div class="head">
      <div>{_marca_html(emisor)}</div>
      <div class="title">
        <h1>Cotización</h1>
        <div class="meta">
          <div>Folio <span class="mono">{_escape(datos["folio"])}</span></div>
          <div>Fecha <span class="mono">{_escape(datos["fecha"])}</span></div>
          <div>Vigencia <span class="mono">{_escape(vigencia)}</span> días naturales</div>
        </div>
      </div>
    </div>

    <div class="parties">
      <div class="party">
        <p class="label">De</p>
        <p class="name">{_escape(emisor["nombre"])}</p>
        <p class="dim">RFC <span class="mono ink">{_escape(emisor["rfc"])}</span></p>
        <p class="dim">WhatsApp <span class="mono ink">{_escape(emisor["whatsapp"])}</span></p>
        <p class="dim">{_escape(emisor["web"])}</p>
      </div>
      <div class="party">
        <p class="label">Para</p>
        <p class="name">{_escape(cliente["nombre"])}</p>
        {atencion}
        <p class="dim">{_escape(cliente.get("email", ""))}</p>
        {cliente_rfc}
      </div>
    </div>

    <table class="items">
      <thead>
        <tr>
          <th>Concepto</th>
          <th class="num">Cantidad</th>
          <th class="num">Precio unitario</th>
          <th class="num">Importe</th>
        </tr>
      </thead>
      <tbody>{filas}
      </tbody>
    </table>
    <p class="note">{_escape(nota_iva)}</p>

    <div class="total">
      <div><div class="k">Total a pagar</div><div class="s">MXN, IVA incluido</div></div>
      <div class="amt">{_escape(_money(total))}</div>
    </div>

    <div class="cols">
      <div class="box">
        <p class="label">Datos para el pago</p>
        <div class="row"><span class="k">Banco</span><span class="v">{_escape(banco["nombre"])}</span></div>
        <div class="row"><span class="k">Beneficiario</span><span class="v">{_escape(banco["beneficiario"])}</span></div>
        <div class="row"><span class="k">RFC</span><span class="v mono">{_escape(banco["rfc"])}</span></div>
        <div class="row"><span class="k">Cuenta</span><span class="v mono">{_escape(banco["cuenta"])}</span></div>
        <div class="row"><span class="k">CLABE</span><span class="v mono">{_escape(banco["clabe"])}</span></div>
      </div>
      <div class="box">
        <p class="label">Condiciones</p>
        <ul>{lista_cond}</ul>
      </div>
    </div>

    <div class="foot">
      <div>{_escape(emisor["marca"])} · {_escape(pie_nombre)}</div>
      <div>Cotización válida por {_escape(vigencia)} días naturales</div>
    </div>
  </div></div>
</body>
</html>
"""


def render(datos: dict) -> bytes:
    """Construye el HTML y lo renderiza a bytes PDF con Chromium (Playwright)."""
    from playwright.sync_api import sync_playwright  # import lazy (extra ciec)

    html = construir_html(datos)
    with sync_playwright() as p:
        navegador = p.chromium.launch(args=["--no-sandbox"])
        try:
            pagina = navegador.new_page()
            pagina.set_content(html, wait_until="load")
            # Asegura que las @font-face embebidas terminen de cargar antes del PDF.
            pagina.evaluate("async () => { await document.fonts.ready; }")
            return pagina.pdf(
                format="A4", print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            navegador.close()
