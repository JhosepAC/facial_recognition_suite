"""
Tests del token de 'recordar sesión' cifrado en reposo (Fase 5, M14).

Verifica que el token NO se persiste en claro en QSettings (se guarda cifrado
con Fernet + base64) y que un valor en formato antiguo se descarta.
"""
import base64
import configparser

import pytest
from PySide6.QtCore import QCoreApplication, QSettings


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication(["test"])
    yield app


@pytest.fixture()
def settings_file(tmp_path, monkeypatch, qapp):
    import app.gui.widgets.login_widget as login_widget

    path = tmp_path / "test.ini"
    monkeypatch.setattr(
        login_widget,
        "QSettings",
        lambda org, name: QSettings(str(path), QSettings.Format.IniFormat),
    )
    return path


@pytest.fixture()
def credentials(settings_file, monkeypatch):
    from app.core.config import settings
    from app.gui.widgets.login_widget import RememberedCredentials

    monkeypatch.setattr(settings.security, "remember_credentials_days", 30)
    return RememberedCredentials()


def test_token_stored_encrypted_not_plaintext(credentials, settings_file):
    credentials.save("jose", "TOKEN_SECRETO")

    cfg = configparser.ConfigParser()
    cfg.read(settings_file)
    stored = cfg["auth"]["remember_token"]
    assert stored != "TOKEN_SECRETO"  # nunca en claro

    from app.core.security import decrypt_value

    assert decrypt_value(base64.b64decode(stored)) == "TOKEN_SECRETO"

    usuario, token, hay, auto = credentials.load()
    assert usuario == "jose"
    assert token == "TOKEN_SECRETO"
    assert hay is True
    assert auto is True


def test_old_plaintext_format_is_discarded(credentials):
    credentials.save("jose", "x")
    # Simular un valor en claro (formato antiguo previo al cifrado en reposo).
    credentials._settings.setValue("auth/remember_token", "TOKEN_PLANO")
    credentials._settings.sync()

    usuario, token, hay, _ = credentials.load()
    assert token == ""
    assert hay is False
    assert usuario == ""