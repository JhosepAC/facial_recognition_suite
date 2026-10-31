"""Keep one QApplication alive for credential and headless widget tests."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    """Create the GUI-capable application before any QCoreApplication fixture."""
    app = QApplication.instance() or QApplication([])
    yield app
