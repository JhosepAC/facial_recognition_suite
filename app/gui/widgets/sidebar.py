from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QButtonGroup, QLabel

from app import __version__ as APP_VERSION
from app.gui import icons
from app.i18n import bus as i18n_bus
from app.i18n import tr

NAV_ITEMS = [
    ("dashboard", "sidebar.dashboard", "home"),
    ("personas", "sidebar.persons", "people"),
    ("comparador", "sidebar.comparator", "compare"),
    ("busqueda", "sidebar.search", "search"),
    ("webcam", "sidebar.webcam", "videocam"),
    ("videos", "sidebar.videos", "movie"),
    ("estadisticas", "sidebar.stats", "chart"),
    ("administracion", "sidebar.admin", "settings"),
]

ICON_SIZE = 18

# Acento de la entrada seleccionada: azul limpio (sin componente verde).
SELECTED_COLOR = "#3b82f6"


class Sidebar(QWidget):
    navigate = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 20, 12, 20)
        layout.setSpacing(4)

        self.title = QLabel()
        self.title.setStyleSheet("font-size: 16px; font-weight: 700; padding: 0 8px 16px 8px;")
        layout.addWidget(self.title)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.group.buttonToggled.connect(self._on_button_toggled)
        self._buttons: dict[str, QPushButton] = {}
        self._icon_by_button: dict[QPushButton, str] = {}

        for key, tr_key, glyph_name in NAV_ITEMS:
            btn = QPushButton(tr(tr_key))
            btn.setObjectName("SidebarButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setIcon(icons.icon(glyph_name, ICON_SIZE, icons.COLOR_MUTED))
            btn.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            btn.clicked.connect(lambda _checked, k=key: self.navigate.emit(k))
            self.group.addButton(btn)
            layout.addWidget(btn)
            self._buttons[key] = btn
            self._icon_by_button[btn] = glyph_name

        layout.addStretch()

        self.version = QLabel()
        self.version.setStyleSheet("color: #6b6e7d; font-size: 11px; padding: 8px;")
        layout.addWidget(self.version)

        # Selecciona Dashboard por defecto
        self.group.buttons()[0].setChecked(True)

        self._retranslate()
        i18n_bus().languageChanged.connect(self._retranslate)

    def _retranslate(self, _language: str | None = None) -> None:
        self.title.setText(tr("sidebar.app_name"))
        self.version.setText(tr("sidebar.version", version=APP_VERSION))
        for key, tr_key, _glyph in NAV_ITEMS:
            self._buttons[key].setText(tr(tr_key))

    def _on_button_toggled(self, btn: QPushButton, checked: bool) -> None:
        name = self._icon_by_button.get(btn)
        if name:
            color = SELECTED_COLOR if checked else icons.COLOR_MUTED
            btn.setIcon(icons.icon(name, ICON_SIZE, color))

    def set_allowed_keys(self, allowed_keys: set[str]) -> None:
        """Oculta las entradas de navegación para las que el usuario no tiene permiso."""
        first_visible = None
        for key, btn in self._buttons.items():
            visible = key in allowed_keys
            btn.setVisible(visible)
            if visible and first_visible is None:
                first_visible = btn

        if first_visible is not None and not any(b.isChecked() and b.isVisible() for b in self._buttons.values()):
            first_visible.setChecked(True)
            self.navigate.emit(
                next(k for k, b in self._buttons.items() if b is first_visible)
            )