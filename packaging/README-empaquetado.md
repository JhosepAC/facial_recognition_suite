# Packaging FaceScan v1.1.0

This directory contains everything needed to generate the **FaceScan**
installer for Windows.

## Requirements

- Python 3.12 (project venv in `.venv`).
- **PyInstaller**: `pip install pyinstaller` (in `.venv`).
- **Inno Setup 6**: download from https://jrsoftware.org/isinfo.php and add
  `C:\Program Files (x86)\Inno Setup 6` to PATH (or leave `ISCC.exe` at that
  path).
- Project logo (`facescan.png`, root) for branding resources.
- Facial models `models/buffalo_l` (for the full offline installation). If they
  do not exist in the repo, `build.ps1` automatically copies them from
  `%USERPROFILE%\.insightface\models\buffalo_l`.

## How to Build

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

The script executes, in order:

1. **Tests** (full pytest suite; aborts on failure).
2. **Branding resources**: `make_icons.py` (facescan.ico + wizard images) and
   `make_version_info.py` (version_info.txt).
3. **Model staging** of facial models if `models/buffalo_l` is missing.
4. **PyInstaller** with `facescan.spec` (onedir mode, hidden console):
   - `dist\FaceScan\FaceScan.exe`
   - User data is written to `%LOCALAPPDATA%\FaceScan`, never to the program
     folder.
5. **Inno Setup** with `installer.iss`:
   - `dist\FaceScan-Setup-1.1.0.exe` (single installer).

## Packaging Pieces

| File | Purpose |
|---|---|
| `facescan.spec` | PyInstaller spec (datas, hidden imports, icon, version). |
| `installer.iss` | Inno Setup script (wizard with logo, model components, manuals). |
| `make_icons.py` | Generates `assets/facescan.ico`, `assets/wizard_sidebar.bmp`, `assets/wizard_banner.bmp`. |
| `make_version_info.py` | Generates `version_info.txt` from `app.__version__` (single source). |
| `manuales/programa_manual_es.md` | User manual in Spanish (installed to `{app}\manuales`). |
| `manuales/programa_manual_en.md` | User manual in English (installed to `{app}\manuales`). |
| `LICENSE.txt` | License text shown on the installer license page. |
| `build.ps1` | Full pipeline: tests → assets → models → PyInstaller → Inno Setup. |

## Where Each Thing Goes on the User's Machine

- **Program**: `C:\Program Files\FaceScan\` (installed by the installer).
- **User data** (SQLite DB, photos, video evidence, logs,
  `config/settings.yaml` and Fernet key): `%LOCALAPPDATA%\FaceScan\`.
- **Facial models**: packaged in `{app}\_internal\models` and copied once to
  `%USERPROFILE%\.insightface\models\buffalo_l` on first launch.

## Paths Inside the Frozen App

- `BASE_DIR` = `%LOCALAPPDATA%\FaceScan` (everything that is written).
- `BUNDLE_DIR` = `sys._MEIPASS` (`_internal` of onedir, read-only): default
  YAML, translations, icon font, logo, and models.
- If `config/settings.yaml` is missing, it is seeded from the bundle on first
  run.

## Installation Types

- **Full**: includes facial models (~300 MB) → 100% offline.
- **Compact**: without models → downloaded on first use of facial recognition
  (requires Internet once).
- **Custom**: user chooses components.

## Known Notes and Risks

- **SmartScreen**: the installer is not signed; Windows may show an
  "unverified publisher" warning. Out of scope for this version.
- **Size**: full installation takes ~450–550 MB.
- If a PyInstaller hook does not detect a mediapipe / onnxruntime submodule,
  they are explicitly collected with `collect_all` in the spec.
