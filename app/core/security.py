"""Local symmetric encryption for sensitive values stored in the database.

Covers the ``secure_settings`` table. Uses Fernet (AES-128-CBC + HMAC) from the
``cryptography`` library, with a key generated locally on first startup and
stored outside version control (see .gitignore).

This module does not depend on the database or the GUI; it only encrypts and
decrypts bytes. Persistence lives in app.services.admin_service.
"""

from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.exceptions import BioVisionError

_KEY_PATH = settings.resolve_path("config/.secret.key")
_fernet_instance: Fernet | None = None


class DecryptionError(BioVisionError):
    """The value could not be decrypted (wrong/rotated key or corrupted data)."""


def _load_or_create_key() -> bytes:
    """Load the local Fernet key or create it on first run.

    Returns:
        Raw key bytes.
    """
    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _KEY_PATH.exists():
        return _KEY_PATH.read_bytes()

    key = Fernet.generate_key()
    _KEY_PATH.write_bytes(key)
    try:
        _KEY_PATH.chmod(0o600)  # No effect on Windows; file remains outside the repo.
    except OSError:
        pass
    return key


def _get_fernet() -> Fernet:
    """Return the singleton Fernet instance.

    Returns:
        Configured Fernet instance.
    """
    global _fernet_instance
    if _fernet_instance is None:
        _fernet_instance = Fernet(_load_or_create_key())
    return _fernet_instance


def encrypt_value(plaintext: str) -> bytes:
    """Encrypt a plaintext string.

    Args:
        plaintext: Value to encrypt.

    Returns:
        Fernet token bytes.
    """
    return _get_fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_value(token: bytes) -> str:
    """Decrypt a Fernet token.

    Args:
        token: Token produced by :func:`encrypt_value`.

    Returns:
        Decrypted plaintext string.

    Raises:
        DecryptionError: If the token cannot be decrypted with the local key.
    """
    try:
        return _get_fernet().decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError(
            "Could not decrypt value: local key mismatch or corrupted data."
        ) from exc
