"""Load and expose global application configuration from config/settings.yaml.

Usage:
    from app.core.config import settings
    print(settings.database.path)
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import List
import os
import re
import shutil
import sys
import warnings
import yaml

from app import __version__ as APP_VERSION

_SOURCE_ROOT = Path(__file__).resolve().parents[2]


def _is_frozen() -> bool:
    """Return True when running from a PyInstaller bundle.

    Returns:
        True if the app is frozen, False otherwise.
    """
    return bool(getattr(sys, "frozen", False))


def _user_data_root() -> Path:
    """Return the per-user data directory for the packaged app.

    Returns:
        Path to the FaceScan data root.
    """
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "FaceScan"

if _is_frozen():
    BASE_DIR = _user_data_root()
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", _SOURCE_ROOT))
else:
    BASE_DIR = _SOURCE_ROOT
    BUNDLE_DIR = _SOURCE_ROOT

CONFIG_PATH = BASE_DIR / "config" / "settings.yaml"
LOGO_PATH = BUNDLE_DIR / "facescan.jpg"


@dataclass
class AppSettings:
    """General application settings."""

    name: str = "FaceScan"
    version: str = APP_VERSION
    theme: str = "dark"
    language: str = "es"


@dataclass
class DatabaseSettings:
    """Database connection settings."""

    path: str = "data/biovision.db"
    echo_sql: bool = False


@dataclass
class VisionSettings:
    """Face detection and quality-gate settings."""

    detector_backend: str = "insightface"
    detector_model: str = "buffalo_l"
    det_size: List[int] = field(default_factory=lambda: [640, 640])
    ctx_id: int = -1
    min_face_confidence: float = 0.30
    embedding_dim: int = 512
    quality_min_score: float = 25.0
    retry_downscale: float = 0.5
    min_face_size: int = 32
    max_yaw_deg: float = 35.0
    max_pitch_deg: float = 40.0
    enroll_require_single_face: bool = True
    enable_face_attributes: bool = True


@dataclass
class RecognitionSettings:
    """Biometric matching and ANN index settings."""

    similarity_metric: str = "cosine"
    match_threshold: float = 0.55
    top_k_results: int = 5
    apply_quality_gate: bool = False
    dedupe_threshold: float = 0.30
    live_attr_check: bool = True
    ann_enabled: bool = True
    ann_min_size: int = 256
    ann_ivf_min_size: int = 2000
    ann_nlist: int = 0
    ann_nprobe: int = 0
    ann_persist: bool = False
    ann_index_dir: str = "data/ann_index"


@dataclass
class CameraSettings:
    """Webcam capture settings."""

    default_index: int = 0
    frame_width: int = 960
    frame_height: int = 540
    target_fps: int = 30
    recognition_interval_frames: int = 10
    max_recognition_width: int = 640
    display_max_fps: int = 30


@dataclass
class VideoSettings:
    """Video file analysis settings."""

    allowed_extensions: List[str] = field(
        default_factory=lambda: [".mp4", ".avi", ".mov", ".mkv"]
    )
    sample_interval_frames: int = 15
    max_processing_width: int = 960
    evidence_crop_padding: float = 0.25
    save_evidence_thumbnails: bool = True
    evidence_dir: str = "data/video_evidence"
    max_evidence_per_job: int = 500


@dataclass
class StorageSettings:
    """Filesystem storage locations."""

    photos_dir: str = "data/photos"
    thumbnails_dir: str = "data/thumbnails"
    exports_dir: str = "exports"
    logs_dir: str = "logs"


@dataclass
class SecuritySettings:
    """Authentication and session security settings."""

    session_timeout_minutes: int = 30
    max_session_minutes: int = 0
    remember_credentials_days: int = 30
    min_password_length: int = 8
    lockout_attempts: int = 5
    lockout_minutes: int = 15
    login_failure_delay_ms: int = 250
    allow_self_registration: bool = True
    default_registration_role: str = "Operador"


@dataclass
class LoggingSettings:
    """Logging output settings."""

    level: str = "INFO"
    rotation: str = "10 MB"
    retention: str = "30 days"


@dataclass
class Settings:
    """Root settings container aggregating all groups."""

    app: AppSettings = field(default_factory=AppSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    vision: VisionSettings = field(default_factory=VisionSettings)
    recognition: RecognitionSettings = field(default_factory=RecognitionSettings)
    camera: CameraSettings = field(default_factory=CameraSettings)
    video: VideoSettings = field(default_factory=VideoSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)
    security: SecuritySettings = field(default_factory=SecuritySettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)

    def resolve_path(self, relative: str) -> Path:
        """Resolve a YAML-relative path to an absolute path under BASE_DIR.

        Args:
            relative: Relative or absolute path string.

        Returns:
            Absolute path.
        """
        p = Path(relative)
        return p if p.is_absolute() else (BASE_DIR / p)


def _known_fields(cls, data: dict) -> dict:
    """Filter a YAML dict to the dataclass declared fields.

    Unknown or misspelled keys in settings.yaml (e.g., a typo in
    ``lockout_attempts``) must not crash the application at import time;
    unrecognized values are ignored and defaults are used.

    Args:
        cls: Target dataclass.
        data: Raw dict from YAML.

    Returns:
        Filtered dict with only known fields.
    """
    known = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in known}


def _build_settings(raw: dict) -> Settings:
    """Build a Settings instance from raw YAML data.

    Args:
        raw: Parsed YAML dictionary.

    Returns:
        Populated Settings instance.
    """
    app_raw = dict(raw.get("app", {}))
    app_raw["version"] = APP_VERSION  # Single source of truth.

    return Settings(
        app=AppSettings(**_known_fields(AppSettings, app_raw)),
        database=DatabaseSettings(**_known_fields(DatabaseSettings, raw.get("database", {}))),
        vision=VisionSettings(**_known_fields(VisionSettings, raw.get("vision", {}))),
        recognition=RecognitionSettings(
            **_known_fields(RecognitionSettings, raw.get("recognition", {}))
        ),
        camera=CameraSettings(**_known_fields(CameraSettings, raw.get("camera", {}))),
        video=VideoSettings(**_known_fields(VideoSettings, raw.get("video", {}))),
        storage=StorageSettings(**_known_fields(StorageSettings, raw.get("storage", {}))),
        security=SecuritySettings(**_known_fields(SecuritySettings, raw.get("security", {}))),
        logging=LoggingSettings(**_known_fields(LoggingSettings, raw.get("logging", {}))),
    )


def _load_settings() -> Settings:
    """Load settings from disk or return defaults.

    Returns:
        Loaded Settings instance.
    """
    if not CONFIG_PATH.exists():
        # In the frozen app the YAML is bundled read-only; seed it under
        # %LOCALAPPDATA%\\FaceScan\\config on first run so the user can
        # customize it (same policy as in development).
        bundled = BUNDLE_DIR / "config" / "settings.yaml"
        if _is_frozen() and bundled.exists():
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled, CONFIG_PATH)
        else:
            return Settings()

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return _build_settings(raw)


settings = _load_settings()


_EDITABLE_SETTINGS: dict[str, set[str]] = {
    "vision": {"quality_min_score", "min_face_size", "max_yaw_deg", "max_pitch_deg",
               "enable_face_attributes"},
    "recognition": {"match_threshold", "apply_quality_gate", "top_k_results",
                    "live_attr_check", "ann_persist",
                    "ann_enabled", "ann_min_size", "ann_ivf_min_size",
                    "ann_nlist", "ann_nprobe"},
}


def _yaml_inline(value) -> str:
    """Serialize an allowed value as single-line YAML text.

    Args:
        value: Value to serialize.

    Returns:
        YAML inline representation.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_yaml_inline(v) for v in value) + "]"
    return str(value)


def save_setting(section: str, key: str, value) -> None:
    """Update a runtime setting (in memory) and persist it to settings.yaml.

    Preserves file comments by rewriting line-by-line without a full YAML
    re-parse.

    Args:
        section: Settings group name.
        key: Setting key within the group.
        value: New value to save.

    Raises:
        ValueError: If the setting is not editable or does not exist.
    """
    if section not in _EDITABLE_SETTINGS or key not in _EDITABLE_SETTINGS[section]:
        raise ValueError(f"Setting not editable via GUI: {section}.{key}")
    group = getattr(settings, section, None)
    if group is None or not hasattr(group, key):
        raise ValueError(f"Setting does not exist: {section}.{key}")
    setattr(group, key, value)

    if not CONFIG_PATH.exists():
        warnings.warn(f"settings.yaml not found; setting kept in memory only: {section}.{key}")
        return

    pattern = re.compile(rf"^(\s*{re.escape(key)}\s*:\s*).*?(\s*#.*)?\s*$")
    section_pattern = re.compile(r"^(\s*)([A-Za-z_][\w]*)\s*:\s*$")
    lines = CONFIG_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = False
    in_target_section = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = line[: len(line) - len(stripped)]
        section_match = section_pattern.match(line)
        if section_match:
            current_section = section_match.group(2)
            in_target_section = current_section == section and not section_match.group(1).strip()
            continue
        if not in_target_section:
            continue
        match = pattern.match(line)
        if match and indent:
            comment = match.group(2) or ""
            newline = f"{indent}{key}: {_yaml_inline(value)}{comment}\n"
            if newline != line:
                lines[i] = newline
                changed = True
    if changed:
        CONFIG_PATH.write_text("".join(lines), encoding="utf-8")
    else:
        warnings.warn(f"Key not found in settings.yaml: {section}.{key}")
