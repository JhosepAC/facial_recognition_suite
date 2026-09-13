# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for FaceScan (onedir mode).
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all, collect_data_files, collect_dynamic_libs, collect_submodules,
)

PACKAGING = Path(SPECPATH).resolve()
ROOT = PACKAGING.parent

datas = [
    (str(ROOT / "config" / "settings.yaml"), "config"),
    (str(ROOT / "app" / "strings" / "*.json"), "app/strings"),
    (str(ROOT / "app" / "gui" / "assets" / "MaterialIcons-Regular.ttf"), "app/gui/assets"),
    (str(ROOT / "facescan.png"), "."),
]
binaries = []
hiddenimports = []

# insightface, faiss, and onnxruntime: collect entire packages.
for _pkg in ("insightface", "faiss", "onnxruntime"):
    _datas, _binaries, _hidden = collect_all(_pkg)
    datas += _datas
    binaries += _binaries
    hiddenimports += _hidden

hiddenimports += ["onnx", "onnxruntime.capi.onnxruntime_pybind11_state"]

# scikit-image (required by InsightFace for face alignment).
hiddenimports += collect_submodules("skimage")

_mp_hidden = []
for _m in (
    "mediapipe.python.solutions.face_mesh",
    "mediapipe.python",
    "mediapipe.framework",
    "mediapipe.calculators",
    "mediapipe.gpu",
    "mediapipe.modules",
    "mediapipe.util",
):
    _mp_hidden += collect_submodules(_m)
hiddenimports += [
    m for m in _mp_hidden
    if not m.startswith(
        ("mediapipe.tasks", "mediapipe.examples", "mediapipe.util.sequence")
    )
]
datas += collect_data_files("mediapipe", excludes=["mediapipe.tasks", "mediapipe.examples"])
binaries += collect_dynamic_libs("mediapipe")

hiddenimports += [
    "cv2",
    "pandas",
    "matplotlib",
    "matplotlib.backends.backend_agg",
    "openpyxl",
    "reportlab",
    "cryptography",
    "bcrypt",
    "PIL",
    "yaml",
    "loguru",
    "sqlalchemy",
]

_models_src = ROOT / "models" / "buffalo_l"
if _models_src.exists():
    datas.append((str(_models_src), "models/buffalo_l"))

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Note: scikit-image was removed from excludes (required at runtime).
    excludes=[
        "tkinter", "test", "tests", "pytest",
        "sentencepiece", "jax", "jaxlib", "torch", "sympy", "mpmath",
        "imageio", "tifffile",
        "mediapipe.tasks", "mediapipe.examples", "mediapipe.util.sequence",
        "onnxruntime.transformers", "onnxruntime.tools", "onnxruntime.quantization",
        "faiss.contrib.torch",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FaceScan",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(PACKAGING / "assets" / "facescan.ico"),
    version=str(PACKAGING / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FaceScan",
)