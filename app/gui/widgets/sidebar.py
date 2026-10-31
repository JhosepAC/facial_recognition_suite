"""Application sidebar navigation."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QLabel, QPushButton, QVBoxLayout, QWidget

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

# Accent shared with the dark workspace theme.
SELECTED_COLOR = "#3ecf8e"


class Sidebar(QWidget):
    """Sidebar with navigation buttons filtered by permissions.

    Signals:
        navigate: Emitted with the navigation key when a button is clicked.
    """

    navigate = Signal(str)

    def __init__(self, parent=None):
        """Initialize the sidebar.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(232)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 24, 16, 20)
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
            if key in ("dashboard", "comparador", "estadisticas"):
                section = QLabel()
                section.setObjectName("SectionLabel")
                section.setProperty("sectionKey", {
                    "dashboard": "workspace.records", "comparador": "workspace.analysis",
                    "estadisticas": "workspace.management",
                }[key])
                layout.addWidget(section)
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
        self.version.setStyleSheet("color: #949494; font-size: 11px; padding: 8px;")
        layout.addWidget(self.version)

        # Select Dashboard by default
        self.group.buttons()[0].setChecked(True)

        self._retranslate()
        i18n_bus().languageChanged.connect(self._retranslate)

    def _retranslate(self, _language: str | None = None) -> None:
        """Retranslate title, version, and navigation buttons."""
        self.title.setText(tr("sidebar.app_name"))
        self.version.setText(tr("sidebar.version", version=APP_VERSION))
        for key, tr_key, _glyph in NAV_ITEMS:
            self._buttons[key].setText(tr(tr_key))
        for label in self.findChildren(QLabel, "SectionLabel"):
            label.setText(tr(label.property("sectionKey")))

    def select(self, key: str) -> None:
        """Keep selection synchronized with every navigation entry point."""
        if key in self._buttons:
            self._buttons[key].setChecked(True)

    def _on_button_toggled(self, btn: QPushButton, checked: bool) -> None:
        """Update the icon color when a button is toggled.

        Args:
            btn: Button that was toggled.
            checked: Whether the button is now checked.
        """
        name = self._icon_by_button.get(btn)
        if name:
            color = SELECTED_COLOR if checked else icons.COLOR_MUTED
            btn.setIcon(icons.icon(name, ICON_SIZE, color))

    def set_allowed_keys(self, allowed_keys: set[str]) -> None:
        """Show only navigation entries the user is permitted to see.

        Args:
            allowed_keys: Set of navigation keys the user may access.
        """
        first_visible = None
        sections = {
            "workspace.records": {"dashboard", "personas"},
            "workspace.analysis": {"comparador", "busqueda", "webcam", "videos"},
            "workspace.management": {"estadisticas", "administracion"},
        }
        for label in self.findChildren(QLabel, "SectionLabel"):
            label.setVisible(bool(sections[label.property("sectionKey")] & allowed_keys))
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
