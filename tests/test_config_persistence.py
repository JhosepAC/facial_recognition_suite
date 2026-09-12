"""
Tests de la capa de configuración persistente (Fase 6).

- M16: `save_setting` persiste en settings.yaml preservando comentarios.
- B7: `_build_settings` tolera claves desconocidas/mal escritas en el YAML
  (antes un typo en settings.yaml tiraba la aplicación al importar).
"""
import pytest

from app import __version__ as APP_VERSION
from app.core import config as config_module
from app.core.config import (
    SecuritySettings,
    Settings,
    _build_settings,
    _known_fields,
    save_setting,
)


# ------------------------------------------------------------------ #
# B7: carga tolerante de settings.yaml
# ------------------------------------------------------------------ #
def test_known_fields_filters_unknown_keys():
    data = {"lockout_attemps": 3, "lockout_attempts": 5, "foo": "x"}
    filtrado = _known_fields(SecuritySettings, data)
    assert filtrado == {"lockout_attempts": 5}


def test_build_settings_ignores_unknown_section_keys():
    raw = {
        "app": {"version": "9.9.9", "theme": "dark", "typo": True},
        "security": {"lockout_attempts": 7, "lockout_attemps": 3},
        "unknown_section": {"algo": 1},
    }
    s = _build_settings(raw)
    assert s.app.version == APP_VERSION  # única fuente de verdad
    assert s.app.theme == "dark"
    assert s.security.lockout_attempts == 7
    assert s.security.lockout_minutes == 15  # por defecto


def test_build_settings_does_not_crash_on_typo():
    # Antes: SecuritySettings(**{'lockout_attemps': 3}) -> TypeError en el import.
    s = _build_settings({"security": {"lockout_attemps": 3}})
    assert isinstance(s, Settings)
    assert s.security.lockout_attempts == 5


# ------------------------------------------------------------------ #
# M16: persistencia de ajustes con preservación de comentarios
# ------------------------------------------------------------------ #
@pytest.fixture()
def temp_config(tmp_path, monkeypatch):
    path = tmp_path / "settings.yaml"
    path.write_text(
        "app:\n"
        "  name: \"FaceScan\"\n"
        "recognition:\n"
        "  match_threshold: 0.4      # distancia cosena maxima\n"
        "  top_k_results: 5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    return path


def test_save_setting_persists_and_preserves_comments(temp_config):
    original = settings_recognition_match_threshold()
    try:
        save_setting("recognition", "match_threshold", 0.5)
        content = temp_config.read_text(encoding="utf-8")
        assert "match_threshold: 0.5      # distancia cosena maxima" in content
    finally:
        settings_recognition_match_threshold(original)


def test_save_setting_updates_runtime_and_is_restored_next_load(temp_config):
    original = settings_recognition_match_threshold()
    try:
        save_setting("recognition", "match_threshold", 0.55)
        assert settings_recognition_match_threshold() == 0.55

        reloaded = _build_settings(
            {"recognition": _load_recognition_from(temp_config)}
        )
        assert reloaded.recognition.match_threshold == pytest.approx(0.55)
    finally:
        settings_recognition_match_threshold(original)


def test_save_setting_rejects_non_editable_key(temp_config):
    with pytest.raises(ValueError, match="no editable"):
        save_setting("security", "lockout_attempts", 3)


def settings_recognition_match_threshold(value=None):
    """Getter/setter del singleton para no ensuciar otros tests."""
    if value is None:
        return config_module.settings.recognition.match_threshold
    config_module.settings.recognition.match_threshold = value
    return value


def _load_recognition_from(path) -> dict:
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw.get("recognition", {})