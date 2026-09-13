"""TOTP code generation and verification (RFC 6238) for second-factor auth (2FA).

Uses only the standard library (HMAC-SHA1 / base32) with no external dependencies.

Typical usage:
    secret = generate_secret()                 # base32, store per user
    uri    = otpauth_uri(secret, "user")      # pair with Google Authenticator

    code = current_code(secret, now)           # code the user types
    valid = verify_code(secret, code, now)     # tolerates +/-1 window of 30 s

The secret must be stored encrypted at rest (see app.core.security) and never
shown in the UI after the provisioning step.
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
_WINDOW = 1  # Adjacent windows tolerated (+/-).


def _b32decode(secret: str) -> bytes:
    """Decode a base32 secret (tolerates missing padding and lowercase).

    Args:
        secret: Base32-encoded secret string.

    Returns:
        Decoded secret bytes.
    """
    padded = secret.strip().upper().replace(" ", "")
    padded += "=" * ((8 - len(padded) % 8) % 8)
    return base64.b32decode(padded, casefold=True)


def generate_secret(num_bytes: int = 20) -> str:
    """Generate a random secret in base32 format without padding.

    Args:
        num_bytes: Number of random bytes to generate.

    Returns:
        Base32-encoded secret string without padding.
    """
    raw = secrets.token_bytes(num_bytes)
    return base64.b32encode(raw).rstrip(b"=").decode("ascii")


def current_code(secret: str, now: float | None = None) -> str:
    """Return the 6-digit TOTP code for the given instant.

    Args:
        secret: Base32-encoded shared secret.
        now: Unix timestamp in seconds. Defaults to current time if None.

    Returns:
        6-digit TOTP code as a string.
    """
    return _code_at(secret, _counter(now))


def verify_code(secret: str, code: str, now: float | None = None,
                digits: int = _DIGITS, window: int = _WINDOW) -> bool:
    """Verify a code against the current window +/- ``window`` 30 s steps.

    Args:
        secret: Base32-encoded shared secret.
        code: Code supplied by the user.
        now: Reference Unix timestamp. Defaults to current time if None.
        digits: Expected number of digits.
        window: Number of adjacent 30 s windows to tolerate.

    Returns:
        True if the code is valid within the window, False otherwise.
    """
    code = str(code).strip()
    if not code or not code.isdigit() or len(code) != digits:
        return False
    counter = _counter(now)
    for offset in range(-window, window + 1):
        if hmac.compare_digest(_code_at(secret, counter + offset), code):
            return True
    return False


def otpauth_uri(secret: str, account: str, issuer: str = "FaceScan") -> str:
    """Build the standard pairing URI for authenticator apps (otpauth://).

    Args:
        secret: Base32-encoded shared secret.
        account: Account name (e.g., username).
        issuer: Issuer label shown in the authenticator app.

    Returns:
        otpauth URI string.
    """
    return (
        f"otpauth://totp/{issuer}:{account}?secret={secret}"
        f"&issuer={issuer}&algorithm=SHA1&digits={_DIGITS}&period={_PERIOD_SECONDS}"
    )


def _counter(now: float | None) -> int:
    """Return the TOTP time-step counter for the given instant.

    Args:
        now: Unix timestamp. Uses current time if None.

    Returns:
        Integer time-step counter.
    """
    return int((time.time() if now is None else now) // _PERIOD_SECONDS)


def _code_at(secret: str, counter: int, digits: int = _DIGITS) -> str:
    """Generate a TOTP code for a specific counter value.

    Args:
        secret: Base32-encoded shared secret.
        counter: Time-step counter.
        digits: Number of digits to produce.

    Returns:
        Zero-padded TOTP code.
    """
    key = _b32decode(secret)
    msg = struct.pack(">Q", counter & 0xFFFFFFFFFFFFFFFF)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = int.from_bytes(digest[offset:offset + 4], byteorder="big") & 0x7FFFFFFF
    return f"{binary % (10 ** digits):0{digits}d}"
