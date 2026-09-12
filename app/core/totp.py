"""
Generación y verificación de códigos TOTP (RFC 6238) para el segundo factor
de autenticación (2FA), sin dependencias externas (HMAC-SHA1 / base32 / stdlib).

Uso típico:
    secret = generate_secret()                 # base32, para guardar por usuario
    uri    = otpauth_uri(secret, "usuario")    # para emparejar con Google Authenticator

    code = current_code(secret, now)           # el código que el usuario teclea
    valid = verify_code(secret, code, now)     # tolera ±1 ventana de 30 s

El secreto debe almacenarse cifrado en reposo (ver app.core.security) y nunca
mostrarse en la interfaz después de la operación que lo presenta.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

_PERIOD_SECONDS = 30
_DIGITS = 6
_WINDOW = 1  # ventanas adyacentes toleradas (+/-)


def _b32decode(secret: str) -> bytes:
    """Decodifica un secreto base32 (tolera pading ausente y minúsculas)."""
    padded = secret.strip().upper().replace(" ", "")
    padded += "=" * ((8 - len(padded) % 8) % 8)
    return base64.b32decode(padded, casefold=True)


def generate_secret(num_bytes: int = 20) -> str:
    """Genera un secreto aleatorio en formato base32 sin pading."""
    raw = secrets.token_bytes(num_bytes)
    return base64.b32encode(raw).rstrip(b"=").decode("ascii")


def current_code(secret: str, now: float | None = None) -> str:
    """Código TOTP de 6 dígitos para el instante dado (por defecto: ahora)."""
    return _code_at(secret, _counter(now))


def verify_code(secret: str, code: str, now: float | None = None,
                digits: int = _DIGITS, window: int = _WINDOW) -> bool:
    """Verifica un código contra la ventana actual ±``window`` pasos de 30 s."""
    code = str(code).strip()
    if not code or not code.isdigit() or len(code) != digits:
        return False
    counter = _counter(now)
    for offset in range(-window, window + 1):
        if hmac.compare_digest(_code_at(secret, counter + offset), code):
            return True
    return False


def otpauth_uri(secret: str, account: str, issuer: str = "FaceScan") -> str:
    """URI de emparejamiento estándar para apps autenticadoras (otpauth://)."""
    return (
        f"otpauth://totp/{issuer}:{account}?secret={secret}"
        f"&issuer={issuer}&algorithm=SHA1&digits={_DIGITS}&period={_PERIOD_SECONDS}"
    )


def _counter(now: float | None) -> int:
    return int((time.time() if now is None else now) // _PERIOD_SECONDS)


def _code_at(secret: str, counter: int, digits: int = _DIGITS) -> str:
    key = _b32decode(secret)
    msg = struct.pack(">Q", counter & 0xFFFFFFFFFFFFFFFF)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = int.from_bytes(digest[offset:offset + 4], byteorder="big") & 0x7FFFFFFF
    return f"{binary % (10 ** digits):0{digits}d}"