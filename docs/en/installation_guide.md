# Installation Guide — BioVision Suite

This guide covers installation on **Windows** (primary target platform)
and notes for Linux/macOS. All processing is local: no accounts, licenses,
or Internet connection are required except for the initial download of
dependencies and the AI model package.

---

## 1. Prerequisites

| Component | Recommended Version | Notes |
|---|---|---|
| Python | 3.11 or 3.12 | 64-bit. Verify with `python --version` |
| Operating System | Windows 10/11 | Also compatible with Linux and macOS |
| Disk Space | ~2 GB | Includes dependencies + AI model package (~300 MB) |
| Webcam | Optional | Only needed for the live recognition module |
| NVIDIA GPU + CUDA | Optional | Accelerates inference; without GPU it runs on CPU |

No server database is required (embedded SQLite is used), no cloud
accounts, API keys, or commercial licenses.

---

## 2. Installation on Windows

### 2.1. Install Python

Download Python 3.12 from [python.org](https://www.python.org/downloads/)
and, during installation, check **"Add python.exe to PATH"**.

Verify in a terminal (PowerShell or CMD):

```powershell
python --version
```

### 2.2. Get the Project

Unzip the project's `.zip` file into a folder, for example
`C:\BioVisionSuite\`.

### 2.3. Create a Virtual Environment

```powershell
cd C:\BioVisionSuite
python -m venv .venv
.venv\Scripts\activate
```

The terminal should show the `(.venv)` prefix once activated.

### 2.4. Install Dependencies

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

This installs, among others: PySide6 (UI), InsightFace + ONNX Runtime
(AI), OpenCV, SQLAlchemy, Matplotlib, ReportLab, openpyxl, bcrypt, and
cryptography. Installation takes a few minutes the first time.

> **GPU Acceleration (optional):** if you have an NVIDIA GPU with CUDA
> installed, replace `onnxruntime` with `onnxruntime-gpu`:
> ```powershell
> pip uninstall onnxruntime
> pip install onnxruntime-gpu
> ```
> and then edit `config/settings.yaml`, section `vision`, and change `ctx_id: -1`
> to `ctx_id: 0`.

### 2.5. First Launch

```powershell
python -m app.main
```

On first launch two things happen automatically:

1. **Download of the AI model package** (`buffalo_l`, ~300 MB) to
   `%USERPROFILE%\.insightface\models\`. Internet connection is required
   *only this once*; on subsequent launches the app works 100% offline.
2. **Creation of the SQLite database** at `data\biovision.db`.

The application will then display a wizard to **create the administrator
account** (username + password). From then on, each time the app is opened
it will prompt for login.

---

## 3. Installation on Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m app.main
```

On Linux, if `opencv-python` has trouble opening the webcam, install the
system video dependencies (for example `sudo apt install
libgl1 v4l-utils` on Debian/Ubuntu-based distributions).

---

## 4. Verify Everything Works

When logging in for the first time you should see the **Dashboard** with
counters at zero. For a quick check of each module:

1. **Persons** → register a person with a face photo.
2. **Comparator** → compare that same photo against itself; it should show
   100% similarity.
3. **Webcam** (if you have a camera) → press "Start"; you should see yourself
   with a bounding box and your name if the camera focuses on your face.

---

## 5. Troubleshooting

| Symptom | Likely Cause | Solution |
|---|---|---|
| `ModuleNotFoundError` when running `python -m app.main` | Virtual environment not activated, or dependencies not installed | Check for the `(.venv)` prefix in the terminal and repeat `pip install -r requirements.txt` |
| AI model loading failure / `ModelLoadError` | No Internet connection on first launch, or interrupted download | Check connection and try again; check `%USERPROFILE%\.insightface\models\` |
| "Could not open camera index 0" | Webcam is in use by another app, or index is incorrect | Close other apps using the camera; try changing the index in the Webcam module selector |
| App becomes very slow when analyzing video | Limited CPU processing many frames | Increase `video.sample_interval_frames` in `config/settings.yaml` (process fewer frames) |
| Forgot administrator password | — | Another administrator can reset it from *Administration → Users*. If no administrator is available, see the recovery note below |
| "Account temporarily locked" | Configured failed login attempts exceeded | Wait the indicated time, or ask an administrator to reactivate the account from *Administration → Users* |

### Recovery If Administrator Access Is Lost

BioVision Suite has no hidden administrator account or master password
(by design, to avoid weakening security). If access to all administrator
accounts is lost, the only recovery path is:

1. Close the application.
2. Back up `data/biovision.db` just in case.
3. Delete the users table manually with a SQLite client
   (`DELETE FROM users;`), or delete `data/biovision.db` entirely if
   losing biometric data is acceptable.
4. Reopen the app: when no users are detected, it will show the initial
   setup wizard again.

---

## 6. Updating the Application

When replacing project files with a newer version, keep the `data/` folder
(contains the database and photos) and `config/.secret.key` (local encryption
key) to avoid losing information.
