"""Interface icons: single source (Google Material Icons) for the entire GUI."""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QLabel

_FONT_PATH = Path(__file__).resolve().parent / "assets" / "MaterialIcons-Regular.ttf"
FONT_FAMILY = "Material Icons"

# Icon color palette (aligned with the default dark theme).
COLOR_OK = "#2ecc71"
COLOR_WARN = "#f2b134"
COLOR_ERROR = "#e85d5d"
COLOR_MUTED = "#b7b9c4"

# Codepoints for Google Material Icons (MaterialIcons-Regular.ttf).
GLYPHS = {
    "home": "\ue88a",
    "people": "\ue7ef",
    "person": "\ue7fd",
    "compare": "\ue915",
    "search": "\ue8b6",
    "videocam": "\ue04b",
    "movie": "\ue02c",
    "chart": "\ue24b",
    "settings": "\ue8b8",
    "lock": "\ue897",
    "check_circle": "\ue86c",
    "warning": "\ue002",
    "error": "\ue000",
    "info": "\ue88e",
    "image": "\ue3f4",
    "camera": "\ue412",
    "skip_previous": "\ue045",
    "skip_next": "\ue044",
    "logout": "\ue9ba",
    "refresh": "\ue5d5",
    "add": "\ue145",
    "delete": "\ue872",
    "upload": "\ue2c6",
    "visibility": "\ue8f4",
    "play": "\ue037",
    "stop": "\ue047",
    "sync": "\ue627",
    "account_circle": "\ue853",
    "edit": "\ue150",
    "star": "\ue838",
    "star_border": "\ue83a",
    "person_add": "\ue7fe",
    "photo_library": "\ue413",
    "close": "\ue5cd",
    "delete_forever": "\ue92b",
    "circle": "\uef4a",
    "crop_free": "\ue3c2",
    "swap_horiz": "\ue8d4",
    "scan": "\ue8df",
    "download": "\ue2c4",
    "schedule": "\ue8b5",
    "video_library": "\ue3a5",
    "folder_open": "\ue2c7",
    "pause": "\ue034",
    "replay": "\ue042",
    "description": "\ue873",
    "filter_list": "\ue152",
    "first_page": "\ue05c",
    "last_page": "\ue05d",
    "visibility_off": "\ue8f5",
    "key": "\ue073",
    "security": "\ue32a",
    "backup": "\ue864",
    "cleaning_services": "\ue0ff",
    "admin_panel": "\uef39",
    "groups": "\ue7ef",
    "shield": "\ue9e1",
    "manage_accounts": "\ue02d",
    "save": "\ue161",
    "lock_open": "\ue898",
    "verified_user": "\ue8f2",
    "assignment": "\ue85d",
    "account_tree": "\ue97a",
    "restart_alt": "\uf053",
    "person_search": "\ue8a8",
    "login": "\uea77",
    "check_box": "\ue834",
    "check_box_outline_blank": "\ue835",
    "person_remove": "\ue8ef",
    "email": "\ue0be",
    "badge": "\uea67",
}


def _glyph(name: str) -> str:
    """Return the glyph for an icon name, falling back to info.

    Args:
        name: Icon key in ``GLYPHS``.

    Returns:
        Unicode glyph character.
    """
    return GLYPHS.get(name, GLYPHS["info"])


def _font(size: int) -> QFont:
    """Return the Material Icons font at the given pixel size.

    Args:
        size: Desired pixel size.

    Returns:
        Configured ``QFont`` instance.
    """
    # addApplicationFont is idempotent within the same QApplication
    # instance and safe to call repeatedly across instances.
    if _FONT_PATH.exists():
        QFontDatabase.addApplicationFont(str(_FONT_PATH))
    font = QFont(FONT_FAMILY)
    font.setPixelSize(size)
    return font


def pixmap(name: str, size: int = 20, color: str = COLOR_MUTED) -> QPixmap:
    """Render an icon glyph to a pixmap.

    Args:
        name: Icon name.
        size: Pixmap width/height in pixels.
        color: CSS color for the glyph.

    Returns:
        Rendered ``QPixmap``.
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(color))
    painter.setFont(_font(size))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, _glyph(name))
    painter.end()
    return pm


def icon(name: str, size: int = 20, color: str = COLOR_MUTED) -> QIcon:
    """Create an icon from a glyph.

    Args:
        name: Icon name.
        size: Icon size in pixels.
        color: Glyph color.

    Returns:
        ``QIcon`` containing the rendered pixmap.
    """
    return QIcon(pixmap(name, size, color))


def icon_label(name: str, size: int = 20, color: str = COLOR_MUTED) -> QLabel:
    """Create a label displaying an icon pixmap.

    Args:
        name: Icon name.
        size: Icon size in pixels.
        color: Glyph color.

    Returns:
        ``QLabel`` with the icon pixmap.
    """
    label = QLabel()
    label.setPixmap(pixmap(name, size, color))
    label.setFixedSize(size, size)
    return label


def html_glyph(name: str, size: int = 14, color: str | None = None) -> str:
    """Return an HTML span with the icon glyph for rich-text labels.

    Args:
        name: Icon name.
        size: Font size in pixels.
        color: Optional CSS color.

    Returns:
        HTML string with the styled glyph.
    """
    cp = ord(_glyph(name))
    color_style = f"color:{color};" if color else ""
    return (
        f'<span style="font-family:\'{FONT_FAMILY}\'; font-size:{size}px; '
        f"{color_style} vertical-align:middle;\">&#x{cp:04X};</span>"
    )


def status_html(icon_name: str, text: str, color: str, size: int = 15) -> str:
    """Return status text with an embedded icon (same icon font).

    Args:
        icon_name: Icon name.
        text: Status message.
        color: Icon color.
        size: Icon size.

    Returns:
        HTML string combining icon and escaped text.
    """
    safe_text = html.escape(str(text))
    return f"{html_glyph(icon_name, size, color)}&nbsp; {safe_text}"


def ok(text: str) -> str:
    """Format a success status message.

    Args:
        text: Message text.

    Returns:
        HTML status string with a success icon.
    """
    return status_html("check_circle", text, COLOR_OK)


def warn(text: str) -> str:
    """Format a warning status message.

    Args:
        text: Message text.

    Returns:
        HTML status string with a warning icon.
    """
    return status_html("warning", text, COLOR_WARN)


def err(text: str) -> str:
    """Format an error status message.

    Args:
        text: Message text.

    Returns:
        HTML status string with an error icon.
    """
    return status_html("error", text, COLOR_ERROR)
