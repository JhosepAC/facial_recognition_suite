"""Generate packaging/version_info.txt for the Windows executable.

Reads the version from ``app/__init__.py`` (``__version__``), the single
source of truth, and writes a PyInstaller ``VSVersionInfo`` resource file.

Usage:
    python packaging/make_version_info.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import __version__  # noqa: E402

parts = tuple(int(x) for x in __version__.split("."))
major, minor, build = (parts + (0, 0, 0))[:3]
ver = f"{major}.{minor}.{build}.0"

content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {build}, 0),
    prodvers=({major}, {minor}, {build}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'FaceScan'),
        StringStruct('FileDescription', 'FaceScan - Plataforma de analisis biometrico facial'),
        StringStruct('FileVersion', '{ver}'),
        StringStruct('InternalName', 'FaceScan'),
        StringStruct('OriginalFilename', 'FaceScan.exe'),
        StringStruct('ProductName', 'FaceScan'),
        StringStruct('ProductVersion', '{ver}'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

out = Path(__file__).resolve().parent / "version_info.txt"
out.write_text(content, encoding="utf-8")
print(f"version_info.txt generado para FaceScan {__version__}")