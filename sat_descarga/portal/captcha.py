"""
Mini-ventana para capturar el captcha del SAT en los flujos CIEC.

La idea (UX que el usuario pidió): el browser de Playwright corre HEADLESS (no se ve
ninguna ventana del navegador) y lo único que aparece en la pantalla es esta mini-
ventana con la IMAGEN del captcha, un INPUT para teclearlo y un botón Enviar. Una vez
capturado, el resto del proceso sigue tras bambalinas.

tkinter es stdlib; Pillow (extra `ciec`) renderiza el JPEG inline (`data:image/...`)
del captcha. Fase 2 (futuro): reemplazar `pedir_captcha` por un OCR que lo resuelva solo.
"""

import base64
import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def bytes_de_data_uri(src: str) -> bytes:
    """Decodifica una imagen `data:image/jpeg;base64,XXXX` a bytes crudos."""
    if not src:
        raise ValueError("src del captcha vacío")
    if "," in src:
        src = src.split(",", 1)[1]
    return base64.b64decode(src)


def pedir_captcha(imagen: bytes, intento: int = 1, max_intentos: int = 3,
                  respetar_mayusculas: bool = False) -> Optional[str]:
    """
    Abre una mini-ventana con la imagen del captcha + input + botón Enviar.

    Bloquea hasta que el usuario envía (Enter o el botón) o cierra la ventana.

    Returns:
        El texto tecleado (en MAYÚSCULAS, sin espacios; tal cual con
        `respetar_mayusculas`, p. ej. la recuperación pública de certificados),
        o None si el usuario cancela (cierra la ventana o presiona Escape sin texto).
    """
    try:
        import tkinter as tk
        from PIL import Image, ImageTk
    except Exception as e:  # pragma: no cover - depende del entorno
        raise RuntimeError(
            "Se requiere tkinter + Pillow para la ventana del captcha. "
            f"Instala el extra: pip install -e '.[ciec]'. Detalle: {e}"
        )

    resultado = {"texto": None}
    root = tk.Tk()
    root.title(f"Captcha SAT — intento {intento}/{max_intentos}")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    img = Image.open(io.BytesIO(imagen))
    # Escalar la imagen para que sea cómoda de leer (los captchas del SAT son chicos).
    escala = max(1, 110 // img.height) if img.height else 1
    if escala > 1:
        img = img.resize((img.width * escala, img.height * escala), Image.LANCZOS)
    tkimg = ImageTk.PhotoImage(img)  # mantener referencia viva durante el mainloop

    tk.Label(root, text="Teclea el captcha:").pack(padx=16, pady=(14, 6))
    tk.Label(root, image=tkimg).pack(padx=16)
    entry = tk.Entry(root, font=("TkDefaultFont", 18), justify="center", width=16)
    entry.pack(padx=16, pady=10)
    entry.focus_force()

    def _finalizar(texto):
        resultado["texto"] = texto
        root.quit()  # sale del mainloop; la ventana se cierra abajo

    def _texto():
        t = entry.get().strip()
        return t if respetar_mayusculas else t.upper()

    entry.bind("<Return>", lambda *_: _finalizar(_texto()))
    root.bind("<Escape>", lambda *_: _finalizar(None))
    root.protocol("WM_DELETE_WINDOW", lambda: _finalizar(None))
    tk.Button(root, text="Enviar",
              command=lambda: _finalizar(_texto()),
              default="active").pack(pady=(0, 14))

    root.mainloop()

    # En macOS, tras salir del mainloop la ventana queda PINTADA si no se bombea el
    # event loop, y enseguida arranca la descarga (bloqueante, sin GUI), dejándola
    # "fantasma" en pantalla. withdraw()+update() la quitan ANTES de seguir.
    texto = resultado["texto"]
    try:
        root.withdraw()
        root.update()
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass
    return texto or None
