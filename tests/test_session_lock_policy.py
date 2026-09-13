"""
Tests for the inactivity session lock policy and the absolute duration cap
(Phase 7, T2).

Covers the pure functions extracted in ``app.gui.main_window`` that decide
when to lock (inactivity) or expire (maximum duration) the session.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui.main_window import _session_expired, _session_should_lock


# ------------------------------------------------------------------ #
# Inactivity lock (session_timeout_minutes)
# ------------------------------------------------------------------ #
def test_inactivity_lock_disabled_when_timeout_zero():
    assert _session_should_lock(0, 1000.0, 10_000.0) is False


def test_inactivity_no_lock_before_threshold():
    assert _session_should_lock(30, 100.0, 100.0 + 30 * 60 - 1) is False


def test_inactivity_lock_at_threshold_boundary():
    assert _session_should_lock(30, 100.0, 100.0 + 30 * 60) is True


def test_inactivity_lock_after_threshold():
    assert _session_should_lock(30, 100.0, 100.0 + 30 * 60 + 30) is True


def test_inactivity_recent_activity_postpones_lock():
    # 1 min of activity 29 min ago => still inside the 30 min window.
    assert _session_should_lock(30, 100.0, 100.0 + 29 * 60) is False


# ------------------------------------------------------------------ #
# Absolute session cap (max_session_minutes)
# ------------------------------------------------------------------ #
def test_max_session_disabled_when_zero():
    assert _session_expired(0, 1000.0, 99_000.0) is False


def test_max_session_not_expired_before_boundary():
    assert _session_expired(60, 100.0, 100.0 + 60 * 60 - 1) is False


def test_max_session_expired_at_boundary():
    assert _session_expired(60, 100.0, 100.0 + 60 * 60) is True


def test_max_session_expired_regardless_of_activity():
    # Cap is absolute: recent activity does not extend it.
    assert _session_expired(60, 100.0, 100.0 + 60 * 60 + 60) is True
