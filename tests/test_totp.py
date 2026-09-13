"""
Tests for the TOTP module (app/core/totp.py).

Uses the RFC 6238 (SHA1) test vector to validate code derivation and verifies
window tolerance and pairing with standard apps (base32 secret / otpauth URI).
"""
import time

from app.core.totp import (
    current_code, generate_secret, otpauth_uri, verify_code,
)


def test_generate_secret_is_base32_and_unique():
    a = generate_secret()
    b = generate_secret()
    assert len(a) >= 16
    assert a.isalnum()
    assert a != b


def test_rfc6238_sha1_test_vector():
    # RFC 6238 Appendix B, SHA1: ASCII secret "12345678901234567890".
    # Published vector uses 8 digits: for T=59 (counter=1) it is "94287082".
    # Our module produces 6 digits, so we derive from that reference:
    # with the same secret and counter the HMAC is identical -> 6 digits 287082.
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    from app.core.totp import _code_at
    assert _code_at(secret, 1) == "287082"


def test_current_code_changes_over_time():
    secret = generate_secret()
    now = time.time()
    a = current_code(secret, now)
    b = current_code(secret, now + 60)  # +2 windows (60 s)
    assert a.isdigit() and len(a) == 6
    assert a != b


def test_verify_code_accepts_current_window():
    secret = generate_secret()
    now = time.time()
    code = current_code(secret, now)
    assert verify_code(secret, code, now) is True


def test_verify_code_tolerates_adjacent_window():
    secret = generate_secret()
    now = time.time()
    code_early = current_code(secret, now - 30)  # previous window
    code_late = current_code(secret, now + 30)   # next window
    assert verify_code(secret, code_early, now) is True
    assert verify_code(secret, code_late, now) is True


def test_verify_code_rejects_wrong_and_non_digits():
    secret = generate_secret()
    now = time.time()
    assert verify_code(secret, "000000", now) is False
    assert verify_code(secret, "", now) is False
    assert verify_code(secret, "abc123", now) is False
    assert verify_code(secret, "12345", now) is False  # short length


def test_otpauth_uri_contains_secret_and_account():
    secret = generate_secret()
    uri = otpauth_uri(secret, "jose")
    assert uri.startswith("otpauth://totp/FaceScan:jose?")
    assert f"secret={secret}" in uri
    assert "issuer=FaceScan" in uri
