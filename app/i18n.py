"""Internationalization (Spanish / English) for the FaceScan UI.

Strategy:
    - Per-language JSON catalogs in ``app/strings/{es,en}.json``.
    - ``tr(key, **kwargs)`` looks up the active language catalog; if the
      key is missing it falls back to the Spanish catalog and, as a last
      resort, returns the key itself. This allows incremental migration
      without breaking the application.
    - ``I18nBus.languageChanged`` is the hot-swap signal: each widget that
      wants live retranslation connects a ``_retranslate()`` method.

This module is the precursor to the QTranslator route: all UI strings are
centralized in a catalog so migrating to Qt ``.ts/.qm`` later would only
require replacing ``tr()`` with ``QObject.translate``.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from PySide6.QtCore import QLocale, QObject, Signal

_STRINGS_DIR = Path(__file__).resolve().parent / "strings"
_SUPPORTED = ("es", "en")
_DEFAULT = "en"


class I18nBus(QObject):
    """Single broadcast point for language changes (live hot-swap)."""

    languageChanged = Signal(str)


_bus = I18nBus()
_current: dict[str, str] = {"lang": _DEFAULT}


def bus() -> I18nBus:
    """Return the global i18n bus instance.

    Returns:
        The singleton ``I18nBus`` used to broadcast language changes.
    """
    return _bus


@lru_cache(maxsize=len(_SUPPORTED))
def _catalog(lang: str) -> dict[str, str]:
    """Load and cache the translation catalog for a language.

    Args:
        lang: Language code (e.g., ``"es"`` or ``"en"``).

    Returns:
        Dictionary mapping translation keys to localized strings.
    """
    path = _STRINGS_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fobj:
        return json.load(fobj)


def system_language() -> str:
    """Detect the system language via QLocale.

    Returns:
        ``"es"`` or ``"en"`` if the system locale matches; otherwise the
        default language (English).
    """
    base = QLocale.system().name().split("_")[0].lower()
    return base if base in _SUPPORTED else _DEFAULT


def current_language() -> str:
    """Return the currently active language code.

    Returns:
        Active language code.
    """
    return _current["lang"]


def set_language(language: str) -> None:
    """Set the active language and emit the change signal if needed.

    Args:
        language: Desired language code. Falls back to the default if
            unsupported.
    """
    if language not in _SUPPORTED:
        language = _DEFAULT
    if language != _current["lang"]:
        _current["lang"] = language
        _bus.languageChanged.emit(language)


def tr(key: str, **kwargs: Any) -> str:
    """Translate a catalog key for the active language (with Spanish fallback).

    Args:
        key: Translation key to look up.
        **kwargs: Optional format arguments applied to the translated string.

    Returns:
        Translated and formatted string, or ``key`` itself if not found.
    """
    text = _catalog(_current["lang"]).get(key)
    if text is None:
        text = _catalog("es").get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text
