"""Keyboard-first module navigation, filtered by the current user's permissions."""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from app.gui import icons
from app.gui.widgets.sidebar import NAV_ITEMS
from app.i18n import tr


class CommandPalette(QDialog):
    """Search authorized modules without leaving the current workflow."""

    navigate = Signal(str)

    def __init__(self, allowed_keys: set[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("workspace.quick_navigation"))
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("workspace.find_module"))
        self.search.setAccessibleName(tr("workspace.find_module"))
        self.search.installEventFilter(self)
        layout.addWidget(self.search)
        self.results = QListWidget()
        self.results.setSpacing(4)
        for key, label, glyph in NAV_ITEMS:
            if key in allowed_keys:
                item = QListWidgetItem(icons.icon(glyph), tr(label))
                item.setData(Qt.UserRole, key)
                self.results.addItem(item)
        layout.addWidget(self.results)
        self.empty = QLabel(tr("workspace.no_modules"))
        self.empty.setWordWrap(True)
        self.empty.setObjectName("MutedLabel")
        self.empty.hide()
        layout.addWidget(self.empty)
        hint = QLabel(tr("workspace.navigation_hint"))
        hint.setObjectName("MutedLabel")
        layout.addWidget(hint)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._activate)
        self.results.itemActivated.connect(self._activate)
        self._filter("")
        self.search.setFocus()

    def _filter(self, text: str) -> None:
        first = None
        for index in range(self.results.count()):
            item = self.results.item(index)
            matches = text.strip().casefold() in item.text().casefold()
            item.setHidden(not matches)
            if matches and first is None:
                first = item
        self.results.setCurrentItem(first)
        self.empty.setVisible(first is None)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.search and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Down, Qt.Key_Up):
                visible = [self.results.item(i) for i in range(self.results.count())
                           if not self.results.item(i).isHidden()]
                current = self.results.currentItem()
                if visible:
                    index = visible.index(current) if current in visible else 0
                    step = 1 if event.key() == Qt.Key_Down else -1
                    self.results.setCurrentItem(visible[(index + step) % len(visible)])
                return True
        return super().eventFilter(watched, event)

    def _activate(self, *_args) -> None:
        item = self.results.currentItem()
        if item is not None and not item.isHidden():
            self.navigate.emit(item.data(Qt.UserRole))
            self.accept()
