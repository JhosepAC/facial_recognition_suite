"""Tabular export utilities (CSV/Excel).

``sanitize_formula`` prevents CSV/Excel formula injection (OWASP): text values
starting with spreadsheet-reserved characters (``=``, ``+``, ``-``, ``@``, tab
and CR) are prefixed with a single quote so they are treated as text rather
than executed as a formula when the file is opened.
"""

from __future__ import annotations

from typing import Any

_FORMULA_DANGER_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_formula(value: Any) -> Any:
    """Escape dangerous strings; return other types (numbers, None, bool) unchanged.

    Args:
        value: Cell value to sanitize.

    Returns:
        Sanitized value with a leading single quote if it started with a
        formula prefix, otherwise the original value.
    """
    if isinstance(value, str) and value and value[0] in _FORMULA_DANGER_PREFIXES:
        return "'" + value
    return value
