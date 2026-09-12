"""
Genera los recursos de marca a partir del logo facescan.png (raíz del proyecto):
  - packaging/assets/facescan.ico      (icono multi-resolución 16..256 px)
  - packaging/assets/wizard_sidebar.bmp (imagen lateral del wizard, 164x314)
  - packaging/assets/wizard_banner.bmp  (imagen superior del wizard, 58x58)

Uso:
    python packaging/make_icons.py
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "facescan.png"
OUT = Path(__file__).resolve().parent / "assets"
OUT.mkdir(parents=True, exist_ok=True)

img = Image.open(SRC).convert("RGBA")

# Recorte cuadrado centrado para no deformar el logo en los iconos.
w, h = img.size
side = min(w, h)
img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))

ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(OUT / "facescan.ico", format="ICO", sizes=ICO_SIZES)

img.resize((164, 314), Image.LANCZOS).save(OUT / "wizard_sidebar.bmp", format="BMP")
img.resize((58, 58), Image.LANCZOS).save(OUT / "wizard_banner.bmp", format="BMP")

print("Recursos de marca generados en", OUT)