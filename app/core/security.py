"""
Cifrado simétrico local para valores sensibles guardados en la base de datos
(tabla secure_settings). Usa Fernet (AES-128 en modo CBC + HMAC) de la
librería `cryptography`, con una clave generada localmente en el primer
arranque y almacenada fuera del control de versiones (ver .gitignore).

Este módulo NO depende de la base de datos ni de la GUI: solo cifra/descifra
bytes. La persistencia vive en app/services/admin_service.py.
"""
from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.exceptions import BioVisionError

_KEY_PATH = settings.resolve_path("config/.secret.key")
_fernet_instance: Fernet | None = None


class DecryptionError(BioVisionError):
    """El valor no pudo descifrarse (clave incorrecta/rotada o dato corrupto)."""


def _load_or_create_key() -> bytes:
    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _KEY_PATH.exists():
        return _KEY_PATH.read_bytes()

    key = Fernet.generate_key()
    _KEY_PATH.write_bytes(key)
    try:
        _KEY_PATH.chmod(0o600)  # no tiene efecto en Windows; el archivo igual queda fuera del repo
    except OSError:
        pass
    return key


def _get_fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        _fernet_instance = Fernet(_load_or_create_key())
    return _fernet_instance


def encrypt_value(plaintext: str) -> bytes:
    return _get_fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_value(token: bytes) -> str:
    try:
        return _get_fernet().decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError(
            "No se pudo descifrar el valor: la clave local no coincide o el dato está corrupto."
        ) from exc
