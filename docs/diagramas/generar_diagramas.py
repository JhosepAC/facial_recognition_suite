"""Regenera docs/diagramas/{arquitectura,uml_clases}.png con matplotlib.

Uso:
    .venv\\Scripts\\python.exe docs/diagramas/generar_diagramas.py

Solo requiere matplotlib (ya incluido en requirements.txt). Los diagramas se
generan con un tema oscuro coherente con la interfaz.
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)))

BG = "#0f1115"
BOX = "#1c1e26"
BORDER = "#34364a"
TITLE = "#e8eaf6"
TEXT = "#aeb3c5"
ACCENT = "#4f8cff"
GREEN = "#2ecc71"
GOLD = "#f2b134"

plt.rcParams["figure.facecolor"] = BG
plt.rcParams["savefig.facecolor"] = BG


def _box(ax, x, y, w, h, color=BORDER, fc=BOX, lw=1.2, r=0.08):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle=f"round,pad=0.0,rounding_size={r}",
        linewidth=lw, edgecolor=color, facecolor=fc))


def _text(ax, x, y, s, size=10, color=TEXT, weight="normal", ha="center", va="center"):
    ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, ha=ha, va=va,
            family="DejaVu Sans")


def _arrow(ax, x1, y1, x2, y2, color=ACCENT, lw=1.6):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                                 mutation_scale=14, linewidth=lw, color=color))


def arquitectura():
    fig, ax = plt.subplots(figsize=(11.5, 7.2))
    ax.set_xlim(0, 100); ax.set_ylim(0, 66); ax.axis("off")

    _text(ax, 50, 63.5, "BioVision Suite — Arquitectura por capas", size=15, color=TITLE, weight="bold")

    _box(ax, 4, 50, 92, 10, color=ACCENT)
    _text(ax, 50, 57.5, "Capa de presentación (GUI)", size=11, color=TITLE, weight="bold")
    _text(ax, 50, 54.2, "app/gui/  main_window · sidebar · widgets (PySide6 / QThread workers)", size=9, color=TEXT)
    _text(ax, 50, 51.6, "Login · Dashboard · Personas · Comparador · Búsqueda · Webcam · Videos · Estadísticas · Administración", size=8, color="#7e84a6")

    _box(ax, 4, 36, 92, 10, color=GOLD)
    _text(ax, 50, 43.5, "Capa de servicios (lógica de negocio)", size=11, color=TITLE, weight="bold")
    _text(ax, 50, 40.2, "app/services/  auth · person · video · export · statistics · admin · calibration · preferences", size=9, color=TEXT)
    _text(ax, 50, 37.6, "Única puerta de entrada desde la GUI · validaciones · transacciones · auditoría", size=8, color="#7e84a6")

    _box(ax, 4, 22, 44, 10, color=GREEN)
    _text(ax, 26, 29.5, "Reconocimiento / IA", size=11, color=TITLE, weight="bold")
    _text(ax, 26, 26.2, "app/recognition/  matcher · ann_index (FAISS) · recognition_service", size=8.5, color=TEXT)
    _text(ax, 26, 23.8, "app/vision/  face_engine · face_attributes · face_quality · video_processor", size=8.5, color=TEXT)

    _box(ax, 52, 22, 44, 10, color="#b084d9")
    _text(ax, 74, 29.5, "Persistencia (Repository Pattern)", size=11, color=TITLE, weight="bold")
    _text(ax, 74, 26.2, "app/database/  models (SQLAlchemy 2.0) · session · repositories/", size=8.5, color=TEXT)
    _text(ax, 74, 23.8, "SQLite · auditoría (logs/audit.log) · cifrado (secure_settings)", size=8.5, color=TEXT)

    _box(ax, 4, 8, 92, 10, color="#4e5a7a")
    _text(ax, 50, 15.5, "Infraestructura y recursos", size=11, color=TITLE, weight="bold")
    _text(ax, 50, 12.2, "app/core/ config (YAML) · logger (loguru) · security (Fernet) · permissions · exceptions", size=9, color=TEXT)
    _text(ax, 50, 9.6, "app/utils/ vector_utils · app/i18n/ strings es/en · app/gui/assets/ (iconos)", size=8.5, color="#9aa0b3")

    _arrow(ax, 50, 50, 50, 46.4, color=ACCENT)
    _arrow(ax, 50, 36, 50, 32.4, color=GOLD)
    _arrow(ax, 26, 22, 26, 18.4, color=GREEN)
    _arrow(ax, 74, 22, 74, 18.4, color="#b084d9")

    fig.savefig(os.path.join(OUT, "arquitectura.png"), dpi=150)
    plt.close(fig)
    print("arquitectura.png OK")


def uml():
    fig, ax = plt.subplots(figsize=(12.5, 8.2))
    ax.set_xlim(0, 125); ax.set_ylim(0, 82); ax.axis("off")

    _text(ax, 62, 79.5, "Modelo de datos — BioVision Suite (SQLAlchemy 2.0)", size=14, color=TITLE, weight="bold")

    entities = [
        (2, 60, 30, 16, "Person", "uuid PK\nnombre, apellidos, alias\nsexo, edad_aprox, f_nacimiento\nempresa, depto, cargo\ntel, correo, observaciones"),
        (37, 60, 26, 16, "Photo", "id PK\nperson_uuid FK\nfile_path, thumbnail_path\nes_principal, calidad_score"),
        (68, 60, 26, 16, "FaceEmbedding", "id PK\nperson_uuid FK, photo_id FK\nvector (512-d), dim\nmodel_name, det_conf, quality\nfacial_attributes (JSON)"),
        (98, 60, 25, 16, "UserPreference", "id PK\nuser_id FK (único)\nlanguage (es/en)"),
        (2, 40, 30, 16, "RecognitionEvent", "id PK\nfecha, origen\nperson_uuid FK\nconfianza, distancia\ndet_conf, usuario\nevidencia_path"),
        (37, 40, 26, 16, "VideoJob", "id PK\nfile_path, nombre\nfps, duración, total_frames\nframes_procesados, estado\nmensaje_error, usuario"),
        (68, 40, 26, 16, "VideoDetection", "id PK\nvideo_job_id FK\nframe_number, timestamp\nperson_uuid FK, confianza\nbbox (x1..y2), evidencia_path\nattrs, quality"),
        (98, 40, 25, 16, "SecureSetting", "key PK\nvalue_encrypted\ndescripcion"),
        (2, 20, 30, 16, "Role", "id PK\nnombre (único)\npermisos_csv"),
        (37, 20, 26, 16, "User", "id PK\nusername (único)\npassword_hash\nactivo, role_id FK\nintentos_fallidos\nbloqueado_hasta, ultimo_login"),
        (68, 20, 26, 16, "AuditLog", "id PK\nfecha, usuario\naccion, detalle"),
    ]

    for (x, y, w, h, title, fields) in entities:
        _box(ax, x, y, w, h, color=ACCENT if title == "Person" else BORDER)
        _box(ax, x, y + h - 3.4, w, 3.4, color=ACCENT, fc="#23263a")
        _text(ax, x + w / 2, y + h - 1.7, title, size=10.5, color=TITLE, weight="bold")
        _text(ax, x + w / 2, y + 3.2, fields, size=7.6, color=TEXT)

    def rel(x1, y1, x2, y2):
        _arrow(ax, x1, y1, x2, y2, color=ACCENT, lw=1.4)

    rel(32, 70, 37, 70)
    rel(32, 68, 68, 68)
    rel(63, 68, 68, 68)
    rel(32, 30, 37, 30)
    rel(63, 30, 98, 30)
    rel(63, 48, 68, 48)
    rel(32, 48, 37, 48)

    fig.savefig(os.path.join(OUT, "uml_clases.png"), dpi=150)
    plt.close(fig)
    print("uml_clases.png OK")


if __name__ == "__main__":
    arquitectura()
    uml()
