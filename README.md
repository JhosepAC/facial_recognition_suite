# BioVision Suite (FaceScan) — Facial Biometric Analysis Platform

> **Language:** English | [Español](README-es.md)

<div align="center">

[![Python Version](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![GUI Framework](https://img.shields.io/badge/GUI-PySide6%20(Qt%206)-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)
[![AI Vision Engine](https://img.shields.io/badge/AI%20Engine-InsightFace%20%2B%20ONNX%20Runtime-FF6F00?style=for-the-badge&logo=onnx&logoColor=white)](https://insightface.ai/)
[![Vector Index](https://img.shields.io/badge/ANN%20Search-FAISS%20CPU-00599C?style=for-the-badge)](https://github.com/facebookresearch/faiss)
[![Database](https://img.shields.io/badge/Database-SQLite%20%2B%20SQLAlchemy%202.0-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://www.sqlalchemy.org/)
[![Tests](https://img.shields.io/badge/Tests-199%20Passed-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)](https://docs.pytest.org/)
[![Security](https://img.shields.io/badge/Security-Fernet%20AES--128%20%7C%20Bcrypt%20%7C%20TOTP-blueviolet?style=for-the-badge)](https://cryptography.io/)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-success?style=for-the-badge)](#)

<p align="center">
  <b>BioVision Suite</b> is a comprehensive desktop platform for enrollment, 1:1 comparison, 1:N search, real-time recognition and forensic video analysis with state-of-the-art computer vision. Built with a <b>100% local and offline</b> model: no cloud dependencies, no API quotas, and enterprise-grade encryption to guarantee privacy and sovereignty of biometric data.
</p>

</div>

---

## 📑 Table of Contents

1. [Overview and Value Proposition](#-overview-and-value-proposition)
2. [Key Features](#-key-features)
3. [Quick Start — How to Run and Test](#-quick-start--how-to-run-and-test)
4. [System Architecture and Technical Foundations](#-system-architecture-and-technical-foundations)
5. [Project Structure](#-project-structure)
6. [System Requirements](#-system-requirements)
7. [Installation and Setup](#-installation-and-setup)
8. [Detailed Process and Operation Guide](#-detailed-process-and-operation-guide)
9. [Global Configuration (`settings.yaml`)](#-global-configuration-settingsyaml)
10. [Security, Access Control and Backup](#-security-access-control-and-backup)
11. [Quality Assurance and Automated Tests](#-quality-assurance-and-automated-tests)
12. [Regulatory Compliance and Data Privacy](#-regulatory-compliance-and-data-privacy)
13. [Additional Documentation](#-additional-documentation)
14. [License and Credits](#-license-and-credits)

---

## 🌟 Overview and Value Proposition

**BioVision Suite** provides a robust, self-contained solution for facial biometric analysis. Unlike alternatives that depend on cloud services or external APIs, BioVision Suite runs all inference and storage **strictly locally**:

* **Privacy and Data Sovereignty**: Faces, mathematical vectors and logs remain on the host machine.
* **No Recurring Costs**: No subscriptions, per-query licenses or internet connection required to operate.
* **Optimized Performance**: Accelerated inference via **ONNX Runtime** (supports multi-threaded CPU and NVIDIA CUDA GPU) and vector indexing with **FAISS** for large-scale databases.
* **Clean Architecture**: Strict separation between the graphical interface (PySide6), domain service layer, mathematical inference engines and ORM persistence repository.

---

## ✨ Key Features

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              BioVision Suite Core                               │
├─────────────────────┬─────────────────────┬─────────────────────────────────────┤
│ 👤 Enrollment       │ 🔍 Search 1:N       │ 📹 Forensic Video & Webcam          │
│ • Multiple photos   │ • FAISS indexing    │ • Multi-face tracking 30 FPS        │
│ • Quality control   │ • Semantic filter   │ • Live anomaly detection            │
│ • 512D ArcFace      │ • Photo search      │ • Frame-by-frame nav & KPIs         │
├─────────────────────┼─────────────────────┼─────────────────────────────────────┤
│ ⚖️ Comparator 1:1   │ 🎭 Facial Analysis  │ 🛡️ Security & Audit                 │
│ • Cosine distance   │ • 6 key attributes  │ • RBAC (Roles & Perms)              │
│ • Calibrated score  │ • Age/gender est.   │ • 2FA TOTP & AES-128 enc.           │
│ • Visual verdict    │ • Live calibration  │ • Hot consistent backups            │
└─────────────────────┴─────────────────────┴─────────────────────────────────────┘
```

* **Analytical Dashboard**: Real-time summary of biometric database size, daily identification volume, breakdown by source and confidence metrics.
* **Enrollment with Quality Gate**: Automatic photo validation on registration: rejects blurry images, excessive angle (yaw/pitch), group photos or poor illumination.
* **Accelerated Vector Search (FAISS ANN)**: `IndexFlatIP` indexing for small galleries and `IndexIVFFlat` with Voronoi clustering for large galleries, with transparent fallback to linear search.
* **Extended Facial Analysis (MediaPipe + InsightFace)**: Detection of glasses, mask, beard, mustache, smile and open eyes, plus age and gender estimation.
* **Real-Time Monitoring (Webcam)**: Dynamic overlay with subject name, confidence, attribute chips and **visual disparity alerts** (e.g. *"registered with glasses, seen without glasses"*).
* **Forensic Video Processor**: Background processing of MP4, AVI, MOV and MKV files with adaptive sampling, integrated adaptive player, timeline with clickable subject chips and enriched export.
* **Enterprise Security**: Bcrypt-protected authentication, TOTP second factor (Google Authenticator compatible), automatic brute-force lockout, inactivity auto-lock and immutable audit logs (`logs/audit.log`).
* **Export and Reporting**: Export to CSV, JSON, corporate-styled Excel sheets and executive PDF reports generated with ReportLab.

---

## 🚀 Quick Start — How to Run and Test

This is the fastest way to verify the installation. Copy-paste the commands for your OS. Total time: ~5 minutes + model download (~300 MB, first run only).

### Prerequisites
- **Python 3.11 or 3.12 (64-bit)** — check with `python --version`
- **Windows 10/11, Linux Ubuntu 22.04+ or macOS** — Windows is the primary target
- ~2 GB free disk space (dependencies + AI models)

### 1. Clone and enter the project
```bash
git clone https://github.com/JhosepAC/facial_recognition_suite.git
cd facial_recognition_suite
```

### 2. Create and activate a virtual environment
**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\activate
```
**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```
> **Optional GPU acceleration:** if you have an NVIDIA GPU with CUDA drivers:
> ```bash
> pip uninstall onnxruntime
> pip install onnxruntime-gpu
> ```
> Then set `vision.ctx_id: 0` in `config/settings.yaml`.

### 4. Run the application
```bash
python -m app.main
```
Alternatives:
```bash
pip install -e .   # editable install, enables the CLI entry point
biovision          # same as python -m app.main
```

**What happens on first run:**
1. `insightface` downloads the `buffalo_l` model bundle (~300 MB) to `%USERPROFILE%\.insightface\models\buffalo_l` (Windows) or `~/.insightface/models/buffalo_l` (Linux/macOS). **Internet is required only this once**; afterwards the suite runs 100% offline.
2. A SQLite database is created at `data/biovision.db`.
3. An **Initial Setup wizard** appears to create the **System Administrator** account (name, username, email, password). After creation, the app logs in automatically. Subsequent starts require login.

### 5. Quick manual smoke test (2 minutes)
1. **Persons** → fill **Name** and **Surname**, add a face photo (drag & drop). Click **Save person** → should show `Embedding registered` and clear the form.
2. **Comparator** → load the same photo as Image A and Image B → **Compare faces** → should show `~100%` and `Same person`.
3. **Search** → upload the same photo → should return the person you just registered at the top with `>90%`.
4. **Webcam** (if you have a camera) → select camera index → **Start** → you should see a green box with your name when facing the camera.
5. **Video** → select any `*.mp4` → choose `Standard (every 15 frames)` → **Analyze video** → progress bar completes and detections appear.

### 6. Run automated tests
```bash
# All 199 tests (no GUI, no models required — uses SQLite in-memory + mocks)
.venv\Scripts\python -m pytest          # Windows
python -m pytest                        # Linux/macOS

# Verbose
.venv\Scripts\python -m pytest -v

# With coverage
.venv\Scripts\python -m pytest --cov=app tests/

# Single module
.venv\Scripts\python -m pytest tests/test_video_service.py -v
```

**Expected result:** `199 passed` (or `101+` depending on version) with no failures. If a test fails, see `logs/app.log` and ensure the virtual environment is activated.

### Troubleshooting quick start
| Symptom | Fix |
|---|---|
| `ModuleNotFoundError` | Ensure `(.venv)` is visible in terminal and `pip install -r requirements.txt` succeeded |
| `ModelLoadError` on first run | Check internet connection; retry; verify `%USERPROFILE%\.insightface\models\` |
| `Cannot open camera index 0` | Close other apps using the camera; try index 1 in Webcam module |
| App feels slow on video | Increase `video.sample_interval_frames` in `config/settings.yaml` |
| Forgot admin password | See `docs/en/installation_guide.md` → Recovery section |

---

## 🏗️ System Architecture and Technical Foundations

Strict **Layered Architecture** decoupled via modern design patterns (*Repository Pattern*, *Service Layer*, *Lazy Singleton* and *Dependency Injection*).

### Layered Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                         PRESENTATION LAYER (GUI)                       │
│               PySide6 (Qt 6) — Windows, Widgets, QSS Themes            │
└───────────────────────────────────┬────────────────────────────────────┘
                                     │ Invokes exclusively
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         SERVICE LAYER (LOGIC)                          │
│  PersonService | RecognitionService | VideoService | AuthService       │
│  AdminService  | StatisticsService  | ExportService| CalibrationService│
└──────────────┬────────────────────┬────────────────────┬───────────────┘
                │                    │                    │
                ▼                    ▼                    ▼
┌──────────────────────┐  ┌───────────────────┐  ┌───────────────────────┐
│   VISION LAYER       │  │RECOGNITION LAYER  │  │ PERSISTENCE LAYER     │
│ • InsightFace SCRFD  │  │ • Cosine Matcher  │  │ • ORM Repositories    │
│ • ArcFace (ONNX)     │  │ • FAISS ANN Index │  │ • SQLAlchemy 2.0      │
│ • MediaPipe FaceMesh │  │ • Top-K Ranking   │  │ • Embedded SQLite     │
│ • Quality Gate       │  │ • Score Calibrator│  │ • Fernet AES Enc.     │
└──────────────────────┘  └───────────────────┘  └───────────────────────┘
                ▲                    ▲                    ▲
                └────────────────────┴────────────────────┘
                                     │
┌───────────────────────────────────┴────────────────────────────────────┐
│                       CROSS-CUTTING CORE (CORE)                        │
│   Settings (YAML) | Logger (Loguru) | Exceptions | Perms | TOTP       │
└────────────────────────────────────────────────────────────────────────┘
```

### Biometric Pipeline and Algorithms

```
[ Image / Frame BGR ]
           │
           ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 1. FACE DETECTION (SCRFD / RetinaFace)                                 │
│    Localization of faces, bounding boxes and 5 facial landmarks.       │
└──────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. QUALITY CONTROL (Quality Gate)                                      │
│    Sharpness (Laplacian), illumination, minimum size and               │
│    3D rotation (Yaw / Pitch) from reference points.                    │
└──────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. VECTOR EXTRACTION & ANALYSIS (ArcFace + MediaPipe FaceMesh)         │
│    • Normalized 512D biometric embedding inference.                    │
│    • Attribute detection: glasses, mask, beard, smile, etc.            │
│    • Age and gender estimation.                                        │
└──────────────────────────────────┬─────────────────────────────────────┘
                                    │
           ┌────────────────────────┴────────────────────────┐
           ▼                                                 ▼
[ Registration Module ]                             [ Search / Match Module ]
   Persistence in SQLite                             Search in FAISS / Matcher
   (float32 binary Vector)                           Cosine Distance & % Score
```

#### Mathematical Foundations:

1. **Cosine Distance and Similarity**:
   Given two facial embedding vectors $\mathbf{a}, \mathbf{b} \in \mathbb{R}^{512}$:
   $$\text{Similarity}(a, b) = \frac{\mathbf{a} \cdot \mathbf{b}}{\|\mathbf{a}\| \|\mathbf{b}\|} \in [-1, 1]$$
   $$\text{Distance}(a, b) = 1 - \text{Similarity}(a, b) \in [0, 2]$$
   Two faces belong to the same subject if $\text{Distance}(a, b) \le \theta_{\text{match}}$ (default threshold: $0.55$).

2. **Logistic Percentage Calibration**:
   To avoid confusing linear representations in the UI, similarity is transformed via a sigmoid/logistic function centered at the operating threshold $\theta$:
   $$\text{Score \%} = \frac{100}{1 + e^{-k \cdot (\text{Similarity} - (1 - \theta))}}$$
   This guarantees the exact threshold represents $\approx 50\%$ certainty, values far above reach $>90\%$ and unrelated comparisons fall near $0\%$.

### Technology Mapping

| Component | Selected Technology | Technical Justification |
|---|---|---|
| **Face Detection** | SCRFD / RetinaFace (`insightface==1.0.1`) | High speed and accuracy under occlusion and extreme angles. |
| **Embeddings** | ArcFace 512D (`insightface` + `onnxruntime==1.18.1`) | State-of-the-art in biometric discrimination and angular class separation. |
| **Attributes & Landmarks** | MediaPipe FaceMesh (`mediapipe==0.10.21`) | 468 3D landmarks for geometric and texture attribute analysis. |
| **Vector Search 1:N** | FAISS CPU (`faiss-cpu==1.15.0`) | Sub-linear search `IndexIVFFlat` and hardware vectorization `IndexFlatIP`. |
| **User Interface** | PySide6 (`PySide6==6.7.2` - Qt 6) | High-performance GUI with native rendering, QSS styles and modular architecture. |
| **Persistence Layer** | SQLAlchemy 2.0 + SQLite | Maintenance-free embedded database with strongly typed models. |
| **Security & Encryption** | `bcrypt==4.2.0` + `cryptography==43.0.0` | Salted hashing for passwords and Fernet symmetric encryption (AES-128-CBC + HMAC). |
| **Report Generation** | `openpyxl==3.1.5` + `reportlab==4.2.2` | Enriched spreadsheets and executive vector PDF reports. |
| **Test Suite** | `pytest==8.3.2` | 199 unit and integration tests without graphical dependencies. |

## 📁 Project Structure

```
facial_recognition_suite/
│
├── app/                               # Main application source code
│   ├── __init__.py                    # Single source of truth for version (__version__)
│   ├── main.py                        # Entry point and application bootstrap
│   │
│   ├── core/                          # Core and cross-cutting components
│   │   ├── config.py                  # Typed configuration manager (settings.yaml)
│   │   ├── exceptions.py              # Domain exceptions (BioVisionError)
│   │   ├── logger.py                  # Unified logging with Loguru (app.log / audit.log)
│   │   ├── permissions.py             # Permission catalog and default roles (RBAC)
│   │   ├── security.py                # Fernet (AES-128) cryptography and bcrypt hashing
│   │   └── totp.py                    # 2FA TOTP generation and verification (RFC 6238)
│   │
│   ├── database/                      # Persistence and ORM layer
│   │   ├── base.py                    # SQLAlchemy 2.0 declarative base
│   │   ├── models.py                  # 11 domain entities (Person, Photo, Embedding...)
│   │   ├── session.py                 # Session context manager (Unit of Work)
│   │   └── repositories/              # Repository Pattern
│   │       ├── person_repository.py
│   │       ├── embedding_repository.py
│   │       ├── video_repository.py
│   │       ├── user_repository.py
│   │       ├── secure_setting_repository.py
│   │       └── user_preference_repository.py
│   │
│   ├── vision/                        # Inference and artificial vision engines
│   │   ├── face_engine.py             # Lazy singleton for InsightFace / ONNX
│   │   ├── face_quality.py            # Quality Gate (Laplacian sharpness, yaw/pitch, light)
│   │   ├── face_attributes.py         # Attribute extraction on MediaPipe FaceMesh
│   │   └── video_processor.py         # Frame sampling, rescaling and bbox cropping
│   │
│   ├── recognition/                   # Comparison, matching and vector search
│   │   ├── matcher.py                 # Cosine similarity/distance and logistic percentage
│   │   ├── ann_index.py               # FAISS index (IndexFlatIP / IndexIVFFlat + fallback)
│   │   ├── ann_benchmark.py           # Recall benchmark and nprobe calibration
│   │   └── recognition_service.py     # 1:N search orchestration and deduplication
│   │
│   ├── services/                      # Business Logic (Service Layer)
│   │   ├── person_service.py          # Enrollment, photo management and records
│   │   ├── auth_service.py            # Authentication, brute-force blocking and 2FA
│   │   ├── admin_service.py           # Users, roles, backups and safe cleanup
│   │   ├── video_service.py           # Forensic video batch analysis
│   │   ├── statistics_service.py      # Statistical aggregations and time series
│   │   ├── calibration_service.py     # Threshold calibration and reclassification
│   │   ├── export_service.py          # Multi-format export (CSV/Excel/JSON/PDF)
│   │   └── preferences_service.py     # User preferences
│   │
│   ├── gui/                           # User Interface (PySide6 / Qt)
│   │   ├── main_window.py             # Main window and navigation control
│   │   ├── theme.py                   # Dark / Light style engine via QSS
│   │   ├── icons.py                   # Vector icon generator
│   │   └── widgets/                   # Modular interface views
│   │       ├── dashboard.py           # Live metrics and recent activity
│   │       ├── person_registration.py # Person creation, drag & drop dataset and webcam
│   │       ├── search_compare.py      # 1:N search by photo/text and 1:1 comparator
│   │       ├── webcam_widget.py       # Webcam monitoring with disparity alerts
│   │       ├── video_widget.py        # Forensic video player and timeline
│   │       ├── statistics_widget.py   # Analytical charts and PDF export
│   │       ├── admin_widget.py        # Administration, roles, backups and calibration
│   │       ├── login_widget.py        # Login screen, account registration and 2FA
│   │       └── sidebar.py             # Conditional navigation menu by role
│   │
│   └── utils/                         # Complementary utilities
│       ├── vector_utils.py            # Binary serialization of float32 vectors
│       └── spreadsheet.py             # Corporate styles for Excel sheets
│
├── config/                            # Configuration files
│   └── settings.yaml                  # System operational parameters
│
├── data/                              # Local persistence directory (git-ignored)
│   ├── biovision.db                   # SQLite database
│   ├── photos/                        # Original photo storage
│   ├── thumbnails/                    # Fast-view thumbnails
│   └── video_evidence/                # Forensic evidence crops
│
├── docs/                              # Complete technical documentation
│   ├── en/                              # Documentation in English
│   │   ├── installation_guide.md      # Detailed installation guide
│   │   ├── user_manual.md             # Operational user manual
│   │   ├── technical_manual.md        # Architecture and algorithms manual
│   │   ├── developer_guide.md         # Guide to extend the platform
│   │   └── diagrams/                  # Architecture and UML class diagrams
│   │       ├── architecture.png
│   │       ├── class_diagram.png
│   │       └── generate_diagrams.py
│   ├── es/                              # Documentación en español
│   │   ├── guia_instalacion.md        # Guía detallada de instalación
│   │   ├── manual_usuario.md          # Manual operativo de usuario
│   │   ├── manual_tecnico.md          # Manual de arquitectura y algoritmos
│   │   ├── guia_desarrolladores.md    # Guía para extender la plataforma
│   │   └── diagramas/                 # Diagramas de arquitectura y clases UML
│   │       ├── arquitectura.png
│   │       ├── uml_clases.png
│   │       └── generar_diagramas.py
│
├── exports/                           # Report and export output folder
├── logs/                              # Execution logs (app.log) and audit (audit.log)
├── tests/                             # Suite of 199 automated tests with pytest
├── pyproject.toml                     # Package metadata and dependencies
├── requirements.txt                   # Pinned production dependencies
├── CHANGELOG.md                       # Change history
├── CONTRIBUTING.md                    # Contributor guide
└── SECURITY.md                        # Disclosure and security policies
```

---

## 💻 System Requirements

### Hardware Requirements

| Resource | Minimum (CPU Inference) | Recommended (GPU Inference) |
|---|---|---|
| **Processor** | Intel Core i5 / AMD Ryzen 5 (4 cores, $\ge 2.5\text{ GHz}$) | Intel Core i7/i9 or AMD Ryzen 7/9 |
| **RAM** | 8 GB RAM | 16 GB - 32 GB RAM |
| **Storage** | 5 GB free space (SSD recommended) | 10 GB+ SSD (depending on video/photo volume) |
| **GPU** | Not required (multi-threaded CPU) | NVIDIA GeForce RTX 3000/4000 series (CUDA 12+) |
| **Camera** | USB Webcam 720p @ 30 FPS | HD / Full HD 1080p Camera |

### Software Requirements
* **Operating System**: Windows 10 / 11 (64-bit) (Fully compatible with Linux Ubuntu 22.04+ and macOS).
* **Python**: Version **3.11** or **3.12** (64-bit).

---

## 🚀 Installation and Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-user/facial_recognition_suite.git
cd facial_recognition_suite
```

### 2. Set Up Virtual Environment

On **Windows (PowerShell)**:
```powershell
python -m venv .venv
.venv\Scripts\activate
```

On **Linux / macOS**:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

Upgrade pip and install project dependencies:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> **GPU Acceleration (Optional):**
> If you have an NVIDIA GPU with CUDA drivers configured, install the GPU version of ONNX Runtime:
> ```bash
> pip uninstall onnxruntime
> pip install onnxruntime-gpu
> ```
> Then set `vision.ctx_id: 0` in `config/settings.yaml`.

### 4. Download AI Models (Online and Air-Gapped)

* **Automatic Download**: On first run, `insightface` will download the `buffalo_l` model bundle (~300 MB) directly to `%USERPROFILE%\.insightface\models\buffalo_l` (Windows) or `~/.insightface/models/buffalo_l` (Linux/macOS). After that, the suite works **100% offline**.
* **Air-Gapped Environments**: If the target machine has no internet from the first start, download the `buffalo_l` bundle on a machine with access and manually unzip it to the path above before running.

### 5. Run the System

Run the suite with the Python interpreter:
```bash
python -m app.main
```

Or install the package in editable mode to enable the terminal command:
```bash
pip install -e .
biovision
```

### 6. First-Run Wizard

On first launch:
1. The app detects no users in `data/biovision.db`.
2. The **Initialization Wizard** starts to configure the **System Administrator** account (Name, username, email and password).
3. Once the root account is created, the app logs in automatically. Subsequent starts require username/password login.

---

## 📖 Detailed Process and Operation Guide

### Process 1: Registration and Biometric Enrollment
The **Persons** module enrolls new subjects in the biometric database:
1. **Complete the Data Form**:
   * Enter mandatory fields: **Name** and **Surname**.
   * Optionally add: alias, gender, age, company, department, position, email and notes.
2. **Upload the Photo Dataset**:
   * **Drag and Drop**: Drag one or multiple photos to the dataset area.
   * **File Explorer**: Click *"+ Add photos"*.
   * **Direct Webcam Capture**: Click *"Webcam"* to take a live photo with preview.
   * The first valid photo is automatically assigned as the subject's **Primary Photo**.
3. **Quality Gate Validation**:
   * On *"Save person"*, a background worker processes each photo:
   * Evaluates sharpness via Laplacian variance (minimum quality score: $25.0$).
   * Validates it is not a group photo (`enroll_require_single_face: true`).
   * Checks maximum head orientation ($\text{Yaw} \le 35^\circ$, $\text{Pitch} \le 40^\circ$).
   * Extracts the 512D biometric vector and facial attributes (glasses, beard, etc.).
4. **Automatic Cleanup**:
   * If photos are valid, they are persisted and the form resets automatically for the next enrollment.

### Process 2: 1:1 Facial Comparison
Verifies correspondence between two specific photos (e.g. ID document vs live photo):
1. Go to **Comparator**.
2. Load **Image A** and **Image B**.
3. Click **"Compare faces"**.
4. The system calculates cosine distance, normalizes via the calibrated logistic function and displays:
   * **Similarity Percentage**: Calibrated score (e.g. $98.5\%$).
   * **Cosine Distance**: Continuous value (e.g. $0.18$).
   * **Biometric Verdict**: *"Same person"* (green) or *"Different people"* (red).

### Process 3: Intelligent Search 1:N and Facial Filtering
Locate registered persons:
1. Go to **Search**.
2. **Photo Search (1:N)**:
   * Upload an image with the subject's face.
   * The system queries the **FAISS** index (or does vectorized linear search if the database is small).
   * Returns candidates with highest match sorted by similarity.
3. **Text and Facial Attribute Search**:
   * Filter by name, surname, alias, company or email.
   * Combine with **Facial Analysis Filters**: people with/without glasses, mask, beard, mustache, smile or open eyes.

### Process 4: Live Facial Recognition (Webcam)
Automatic continuous identification of multiple faces via camera:
1. Go to **Webcam**.
2. Select the capture device and click **"Start camera"**.
3. The system processes frames at 30 FPS with multi-face tracking:
   * Draws bounding boxes with recognized subject name and confidence %.
   * Shows chips with real-time visual attributes.
   * **Visual Disparity Alert**: If the registered profile differs from live appearance (e.g. *"registered with glasses, but seen without glasses"*), a highlighted visual warning is emitted.
4. Each successful identification is stored in the recognition events table and in `logs/audit.log`.

### Process 5: Forensic Video Analysis
Automated processing of video recordings (CCTV, local files):
1. Go to **Video** and select a compatible file (.mp4, .avi, .mov, .mkv).
2. Configure frame sampling frequency (*Detailed: every 5 frames, Standard: every 15 frames, Fast: every 30 frames*).
3. Click **"Start analysis"**. Processing runs in background with real-time progress.
4. **Result Exploration**:
   * **Adaptive Player**: View video with bounding boxes over identified faces.
   * **Person Chips**: Click any detected person's chip to jump to the exact frame of first appearance.
   * **Detections Table**: Filter by minimum confidence and double-click to navigate to timestamp.
   * **Report Export**: Download result as **Corporate Excel** (summary sheet with KPIs + detections sheet with conditional formatting and filters) or **CSV**.

### Process 6: Facial Calibration and Threshold Tuning
1. Go to **Administration → Facial calibration**.
2. Use sliders to adjust facial attribute detection thresholds (glasses, mask, beard, mustache, smile, open eyes).
3. The table instantly reclassifies all persons in memory showing new results and raw confidence.
4. Options:
   * **"Apply thresholds and save"**: Updates labels in DB for all records.
   * **"Re-analyze primary photos"**: Re-runs neural inference on all photos to recalculate scores and demographic estimates (age and gender).

### Process 7: Statistics Panel and Report Generation
1. Go to **Statistics** to examine operational metrics and trends.
2. Charts generated with Matplotlib:
   * Cumulative evolution of registered subjects.
   * Daily recognition activity volume (7, 30, 90 and 365 days).
   * Confidence distribution histogram.
   * Distribution by source channel (Webcam / Video / Image).
   * Demographic distribution (company, department, facial attributes).
3. **Executive Export**: Click **"Export PDF"** to generate a formal report with corporate design, executive KPI summary and embedded vector charts.

### Process 8: System Administration, Users and Security
1. **User and Role Control (RBAC)**:
   * Create, edit, activate/deactivate and delete users.
   * Assign roles: **Administrator** (full access), **Operator** (daily operation) or **Viewer** (read-only).
   * Granular permission editing per role via checkboxes.
2. **Two-Factor Authentication (2FA TOTP)**:
   * 2FA activation compatible with RFC 6238 (Google Authenticator, Authy, Microsoft Authenticator).
3. **Backup and Restore**:
   * **Generate Backup**: Uses SQLite's native API (`sqlite3.Connection.backup`) to generate a consistent hot copy without blocking the database.
   * **Restore Backup**: Validates `.db` file schema and restores system state.
   * **Data Cleanup**: Complete removal of biometric data and photos preserving users and roles (requires typing "DELETE" to confirm).
4. **Audit Viewer**: Inspection and filtering of critical events in `logs/audit.log` (logins, enrollments, deletions, exports).

---

## ⚙️ Global Configuration (`settings.yaml`)

The [`config/settings.yaml`](config/settings.yaml) file parametrizes all system modules:

| Section | Parameter | Default | Description |
|---|---|---|---|
| `app` | `theme` | `"dark"` | Visual theme (`"dark"` or `"light"`). |
| `app` | `language` | `"es"` | UI language. |
| `database` | `path` | `"data/biovision.db"` | SQLite database file path. |
| `vision` | `detector_model` | `"buffalo_l"` | InsightFace model bundle (SCRFD + ArcFace). |
| `vision` | `ctx_id` | `-1` | Inference device (`-1` = CPU, `0` = First CUDA GPU). |
| `vision` | `min_face_confidence` | `0.30` | Minimum detector confidence to accept a face. |
| `vision` | `quality_min_score` | `25.0` | Minimum quality score (0–100) in Quality Gate. |
| `vision` | `max_yaw_deg` / `max_pitch_deg` | `35.0` / `40.0` | Max head rotation tolerance on enrollment (degrees). |
| `recognition` | `match_threshold` | `0.55` | Max cosine distance to consider a biometric match. |
| `recognition` | `ann_enabled` | `true` | Enables FAISS approximate vector index for 1:N searches. |
| `recognition` | `ann_min_size` | `256` | Minimum gallery size to switch from linear to FAISS. |
| `recognition` | `ann_ivf_min_size` | `2000` | Threshold to activate `IndexIVFFlat` clustering (approximate ANN). |
| `camera` | `recognition_interval_frames` | `10` | Run recognition every N frames to optimize performance. |
| `video` | `sample_interval_frames` | `15` | Default video sampling (1 frame every 15). |
| `video` | `max_processing_width` | `960` | Pre-scaling width for fast inference. |
| `security` | `session_timeout_minutes` | `30` | Minutes of inactivity before locking session. |
| `security` | `lockout_attempts` | `5` | Failed attempts before temporarily locking account. |
| `security` | `lockout_minutes` | `15` | Duration of brute-force lockout. |

---

## 🔒 Security, Access Control and Backup

* **Sensitive Configuration Encryption**: The suite generates a local symmetric key in `config/.secret.key` (git-ignored). Confidential values are encrypted at rest with **Fernet** (AES-128-CBC + HMAC-SHA256) inside the `secure_settings` table.
* **Brute-Force Protection**: Progressive throttling on authentication attempts and strict lockout after the configured limit.
* **Inactivity Lock**: Global event filter monitors keyboard/mouse activity; after the timeout, the session is locked and password re-entry is required.
* **Immutable Audit**: Every creation, deletion, modification, export or authentication is logged with timestamp in `logs/audit.log` (365-day retention).

---

## 🧪 Quality Assurance and Automated Tests

The project includes **199 automated tests** validating business logic, mathematical algorithms, repositories, security policies and export services, running decoupled from the GUI and heavy models via test doubles (*mocks* and in-memory SQLite sessions):

```bash
# Run all tests
pytest

# Verbose
pytest -v

# With coverage
pytest --cov=app tests/
```

### Test Coverage:
* `test_database_and_matcher.py`: ORM models, repositories and cosine matcher math.
* `test_ann_index.py`: FAISS vector indexing (`IndexFlatIP` and `IndexIVFFlat`), degradation and benchmarks.
* `test_video_service.py`: Decoding pipeline, sampling, bbox rescaling and video export.
* `test_statistics_and_export.py`: Statistical aggregations, PDF report and Excel sheet generation.
* `test_auth_and_admin.py`: Bcrypt authentication, RBAC permissions, Fernet encryption and backups.
* `test_auth_enhancements.py` & `test_totp.py`: Login policies and RFC 6238 2FA verification.
* `test_calibration.py` & `test_attributes_colors.py`: Threshold calibration and extended facial analysis.
* `test_person_permissions.py` & `test_session_lock_policy.py`: Granular security and inactivity lock.

---

## ⚖️ Regulatory Compliance and Data Privacy

Biometric facial data is **sensitive personal data**:

1. **Legal Framework**: Compliant with **Law No. 29733** (Peruvian Personal Data Protection Law), its regulation (D.S. 003-2013-JUS) and international standards such as **GDPR (EU General Data Protection Regulation)**.
2. **Consent and Purpose**: Before enrolling real subjects, obtain prior informed consent and define a legal basis for processing.
3. **Data Nature**: Stored vectors are non-invertible 512-dimensional numerical representations generated by deep neural networks; the original facial image cannot be reconstructed from the vector alone.
4. **ARCO Rights**: The suite provides native mechanisms for Access, Rectification, Cancellation and Opposition (editing and complete deletion of records and associated vectors).

---

## 📚 Additional Documentation

For extended technical documentation, see the [`docs/`](docs/) folder:

* 📘 [**User Manual (`docs/en/user_manual.md`)**](docs/en/user_manual.md): Detailed usage guide for each module for operators.
* ⚙️ [**Technical Manual (`docs/en/technical_manual.md`)**](docs/en/technical_manual.md): Internal architecture, design patterns and mathematical models.
* 🛠️ [**Installation Guide (`docs/en/installation_guide.md`)**](docs/en/installation_guide.md): Instructions for Windows, Linux, macOS and air-gapped deployment.
* 💻 [**Developer Guide (`docs/en/developer_guide.md`)**](docs/en/developer_guide.md): Code conventions and guide to add modules and tests.
* 📊 [**Architecture and UML Diagrams (`docs/en/diagrams/`)**](docs/en/diagrams/): Structural and relational system diagrams.

---

## 📄 License and Credits

* **License**: Proprietary / Institutional Use. All rights reserved.
* **Vision Models**: Developed and trained by the open-source community of **InsightFace** and **MediaPipe**.
* **Development**: BioVision Suite Team.
