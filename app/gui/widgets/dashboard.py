"""Dashboard — landing view.

Welcome greeting and a summary of recent recognition activity. Kept
intentionally simple: detailed metrics and charts live in the
Statistics module.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, QLocale
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.database.models import RecognitionEvent
from app.database.session import get_session
from app.gui import icons
from app.i18n import bus as i18n_bus
from app.i18n import current_language, tr


def _greeting() -> str:
    """Return a time-based greeting key.

    Returns:
        Localized greeting string.
    """
    hour = datetime.now().hour
    if hour < 12:
        return tr("dashboard.greeting_morning")
    if hour < 19:
        return tr("dashboard.greeting_afternoon")
    return tr("dashboard.greeting_evening")


def _today_text() -> str:
    """Return the current date formatted for the active locale.

    Returns:
        Formatted date string (e.g., "Monday, August 9, 2026").
    """
    lang = current_language()
    locale = QLocale(lang if lang == "es" else "en")
    # Spanish: "lunes 9 de agosto de 2026" · English: "Monday, August 9, 2026"
    fmt = "dddd d 'de' MMMM 'de' yyyy" if lang == "es" else "dddd, MMMM d, yyyy"
    return locale.toString(QDate.currentDate(), fmt)


class DashboardWidget(QWidget):
    """Landing dashboard with greeting and recent activity."""

    def __init__(self, parent=None):
        """Initialize the dashboard widget.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(icons.icon_label("home", 26, "#6fa8ff"))

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.saludo_label = QLabel()
        self.saludo_label.setStyleSheet("font-size: 24px; font-weight: 700;")
        self.fecha_label = QLabel()
        self.fecha_label.setStyleSheet("color: #8f92a3; font-size: 12px;")
        title_col.addWidget(self.saludo_label)
        title_col.addWidget(self.fecha_label)
        header.addLayout(title_col)
        header.addStretch()

        layout.addLayout(header)

        self.actividad_title = QLabel()
        self.actividad_title.setStyleSheet("font-size: 16px; font-weight: 600; margin-top: 12px;")
        layout.addWidget(self.actividad_title)

        self.actividad_container = QVBoxLayout()
        actividad_frame = QFrame()
        actividad_frame.setObjectName("Card")
        actividad_frame.setLayout(self.actividad_container)
        layout.addWidget(actividad_frame)

        layout.addStretch()

        i18n_bus().languageChanged.connect(self._retranslate)
        self._retranslate()
        self.refresh()

    def _retranslate(self, _language: str | None = None) -> None:
        """Retranslate greeting and section titles."""
        self.saludo_label.setText(f"{_greeting()}, {tr('dashboard.welcome')}")
        self.fecha_label.setText(_today_text())
        self.actividad_title.setText(tr("dashboard.recent_activity"))

    def refresh(self) -> None:
        """Reload recent recognition events and rebuild the list."""
        with get_session() as session:
            ultimos = (
                session.query(RecognitionEvent)
                .order_by(RecognitionEvent.fecha.desc())
                .limit(8)
                .all()
            )
            eventos = [
                {
                    "origen": e.origen,
                    "fecha": e.fecha,
                    "person_uuid": e.person_uuid,
                    "confianza": e.confianza,
                }
                for e in ultimos
            ]

        while self.actividad_container.count():
            item = self.actividad_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not eventos:
            empty = QLabel(tr("dashboard.no_recent"))
            empty.setStyleSheet("color: #8f92a3; padding: 12px;")
            self.actividad_container.addWidget(empty)
        else:
            for evento in eventos:
                origen_glyph = {"webcam": "videocam", "video": "movie", "imagen": "image"}.get(
                    evento["origen"])
                origen = icons.html_glyph(origen_glyph, 14) if origen_glyph else "•"
                if evento["confianza"]:
                    estado = (
                        tr("dashboard.match") if evento["person_uuid"]
                        else tr("dashboard.unknown")
                    )
                    texto = (
                        f"{origen}&nbsp; {evento['fecha']:%Y-%m-%d %H:%M}&nbsp;&nbsp;—&nbsp;&nbsp;"
                        f"{estado}&nbsp; ({evento['confianza']:.1f}%)"
                    )
                else:
                    texto = f"{origen}&nbsp; {tr('dashboard.no_confidence')}"
                row = QLabel(texto)
                row.setStyleSheet("padding: 6px 10px; border-bottom: 1px solid #2a2b33;")
                self.actividad_container.addWidget(row)
