"""Generate branding resources from the project logo.

Creates the following assets from ``facescan.png`` at the repository root:

- ``packaging/assets/facescan.ico``: multi-resolution icon (16..256 px)
- ``packaging/assets/wizard_sidebar.bmp``: wizard sidebar image (164x314)
- ``packaging/assets/wizard_banner.bmp``: wizard banner image (58x58)

Usage:
    python packaging/make_icons.py
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "facescan.png"
OUT = Path(__file__).resolve().parent / "assets"
OUT.mkdir(parents=True, exist_ok=True)

img = Image.open(SRC).convert("RGBA")

# Center-cropped square to avoid distorting the logo in icons.
w, h = img.size
side = min(w, h)
img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))

ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(OUT / "facescan.ico", format="ICO", sizes=ICO_SIZES)

img.resize((164, 314), Image.LANCZOS).save(OUT / "wizard_sidebar.bmp", format="BMP")
img.resize((58, 58), Image.LANCZOS).save(OUT / "wizard_banner.bmp", format="BMP")

print("Recursos de marca generados en", OUT)