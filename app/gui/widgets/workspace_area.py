"""Scrollable workspace that reflows marked splitters before measuring content."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QSplitter


class WorkspaceArea(QScrollArea):
    """Stack dense panels on compact windows; retain resizable desktop splits."""

    def resizeEvent(self, event) -> None:  # noqa: N802
        page = self.widget()
        if page is not None:
            for splitter in page.findChildren(QSplitter):
                breakpoint = splitter.property("stackBelowWidth")
                if breakpoint:
                    orientation = Qt.Vertical if self.viewport().width() < breakpoint else Qt.Horizontal
                    if splitter.orientation() != orientation:
                        splitter.setOrientation(orientation)
                        splitter.setSizes([400, 600])
            if page.layout() is not None:
                page.layout().activate()
        super().resizeEvent(event)
