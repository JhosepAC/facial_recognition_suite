"""
Utilidades para exportaciones tabulares (CSV/Excel).

`sanitize_formula` previene la inyección de fórmulas (CSV/Excel Formula
Injection, OWASP): valores de texto que comienzan con los caracteres
reservados del motor de hojas de cálculo (`=`, `+`, `-`, `@`, tab y CR)
se prefijan con una comilla simple para que se traten como texto y no como
fórmula ejecutada al abrir el archivo.
"""
from __future__ import annotations

from typing import Any

_FORMULA_DANGER_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_formula(value: Any) -> Any:
    """Escapa strings peligrosos; devuelve el resto (números, None, bool) intacto."""
    if isinstance(value, str) and value and value[0] in _FORMULA_DANGER_PREFIXES:
        return "'" + value
    return value