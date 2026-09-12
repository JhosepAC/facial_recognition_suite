"""
Internacionalización (Español / English) de la interfaz de FaceScan.

Estrategia:
  - Catálogos JSON por idioma en app/strings/{es,en}.json.
  - ``tr(key, **kwargs)`` consulta el catálogo del idioma activo; si falta la
    clave, hace fallback al catálogo español y, en último caso, devuelve la
    propia key. Esto permite migrar las cadenas de forma incremental sin
    romper la aplicación.
  - ``I18nBus.languageChanged`` es la señal de hot-swap: cada widget que
    quiera retraducirse en vivo conecta un método ``_retranslate()``.

Este módulo es el paso previo a la ruta QTranslator: todas las cadenas de la
UI quedan centralizadas en un catálogo, de modo que migrar a Qt .ts/.qm más
adelante solo requeriría reemplazar ``tr()`` por ``QObject.translate``.
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
    """Punto único de difusión de cambios de idioma (hot-swap en vivo)."""

    languageChanged = Signal(str)


_bus = I18nBus()
_current: dict[str, str] = {"lang": _DEFAULT}


def bus() -> I18nBus:
    return _bus


@lru_cache(maxsize=len(_SUPPORTED))
def _catalog(lang: str) -> dict[str, str]:
    path = _STRINGS_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fobj:
        return json.load(fobj)


def system_language() -> str:
    """Idioma del sistema usando QLocale; si no es es/en, devuelve inglés."""
    base = QLocale.system().name().split("_")[0].lower()
    return base if base in _SUPPORTED else _DEFAULT


def current_language() -> str:
    return _current["lang"]


def set_language(language: str) -> None:
    if language not in _SUPPORTED:
        language = _DEFAULT
    if language != _current["lang"]:
        _current["lang"] = language
        _bus.languageChanged.emit(language)


def tr(key: str, **kwargs: Any) -> str:
    """Traduce una clave del catálogo del idioma activo (con fallback es)."""
    text = _catalog(_current["lang"]).get(key)
    if text is None:
        text = _catalog("es").get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text