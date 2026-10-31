"""Application-wide surfaces, controls, and interaction states."""

from PySide6.QtGui import QColor, QPalette


def get_palette(theme: str) -> QPalette:
    """Theme native viewports and auto-filled containers as well as QSS controls."""
    palette = QPalette()
    if theme == "dark":
        for role, color in {
            QPalette.Window: "#141414", QPalette.WindowText: "#ededed",
            QPalette.Base: "#171717", QPalette.AlternateBase: "#1c1c1c",
            QPalette.Text: "#ededed", QPalette.Button: "#252525",
            QPalette.ButtonText: "#ededed", QPalette.Highlight: "#315640",
            QPalette.HighlightedText: "#ffffff", QPalette.PlaceholderText: "#a3a3a3",
            QPalette.ToolTipBase: "#252525", QPalette.ToolTipText: "#ededed",
        }.items():
            palette.setColor(role, QColor(color))
        palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#949494"))
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#949494"))
    return palette

DARK_QSS = """
QWidget { color: #ededed; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QStackedWidget { background: #141414; }
QDialog, QMessageBox { background: #171717; }
QLabel { background: transparent; border: none; }
QStatusBar { background: #171717; color: #a3a3a3; }
#Sidebar { background: #171717; border-right: 1px solid #303030; }
#SidebarButton {
    text-align: left; padding: 11px 12px; border: 1px solid transparent;
    border-radius: 6px; color: #b4b4b4; background: transparent;
}
#SidebarButton:hover { background: #232323; color: #ededed; }
#SidebarButton:checked { background: #20352a; color: #65dca5; border: 1px solid #315640; }
#SidebarButton:focus { border: 1px solid #65dca5; }
#TopBar { background: #171717; border-bottom: 1px solid #303030; }
#WorkspaceTitle { font-size: 14px; font-weight: 600; }
#MutedLabel { color: #a3a3a3; }
#SectionLabel { color: #a3a3a3; font-size: 12px; padding: 16px 12px 6px 12px; }
#Card { background: #1c1c1c; border: 1px solid #303030; border-radius: 12px; }
#StatValue { font-size: 28px; font-weight: 600; color: #ededed; }
#StatLabel { color: #a3a3a3; font-size: 12px; }
QPushButton {
    background: #207f55; color: #ffffff; border: 1px solid #35a873;
    border-radius: 6px; padding: 8px 14px; font-weight: 600; min-height: 18px;
}
QPushButton:hover { background: #287e58; border-color: #65dca5; }
QPushButton:pressed { background: #1b6646; }
QPushButton:focus { border: 1px solid #a1f3c9; }
QPushButton:disabled { background: #252525; border-color: #353535; color: #949494; }
QPushButton#SecondaryButton { background: #252525; border-color: #404040; color: #ededed; }
QPushButton#SecondaryButton:hover { background: #303030; border-color: #737373; }
QPushButton#SecondaryButton:focus { border-color: #65dca5; }
QPushButton#DangerButton { background: #492323; border-color: #8f4242; color: #ffb4b4; }
QPushButton#DangerButton:hover { background: #653030; }
QPushButton#IconButton { background: transparent; border: 1px solid transparent; padding: 3px; }
QPushButton#IconButton:hover { background: #303030; }
QPushButton#IconButton:focus { border-color: #65dca5; }
QPushButton#ChipButton { background: #252525; border-color: #404040; color: #ededed; padding: 4px 12px; }
QPushButton#ChipButton:hover { border-color: #65dca5; }
QPushButton#LinkButton { background: transparent; border: none; color: #65dca5; padding: 4px; }
QPushButton#LinkButton:hover { color: #a1f3c9; text-decoration: underline; }
QPushButton#LinkButton:disabled { color: #949494; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QAbstractSpinBox {
    background: #212121; color: #ededed; border: 1px solid #404040;
    border-radius: 6px; padding: 7px 10px;
    selection-background-color: #315640; selection-color: #ffffff;
}
QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover { border-color: #737373; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QAbstractSpinBox:focus { border-color: #65dca5; }
QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled { color: #949494; background: #1c1c1c; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #252525; color: #ededed; selection-background-color: #315640; border: 1px solid #404040; }
QAbstractItemView { background: #171717; alternate-background-color: #1c1c1c; border: 1px solid #303030; border-radius: 6px; outline: 0; }
QTableView { gridline-color: #303030; selection-background-color: #203f2e; selection-color: #ededed; }
QTableView::item { padding: 7px 10px; border-bottom: 1px solid #292929; }
QTableView::item:selected { background: #203f2e; color: #ededed; }
QTableView::item:focus { border: 1px solid #65dca5; }
QHeaderView::section { background: #212121; color: #b4b4b4; padding: 10px; border: none; border-bottom: 1px solid #404040; font-weight: 600; }
QTableCornerButton::section { background: #212121; border: none; }
QTabWidget::pane { border: 1px solid #303030; border-radius: 6px; background: #171717; }
QTabBar::tab { background: transparent; color: #a3a3a3; padding: 12px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: #ededed; background: #212121; }
QTabBar::tab:selected { color: #65dca5; border-bottom-color: #3ecf8e; }
QTabBar::tab:focus { background: #20352a; }
QGroupBox { border: 1px solid #303030; border-radius: 8px; margin-top: 20px; padding: 16px 12px 12px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #d4d4d4; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: #505050; border-radius: 4px; min-height: 28px; min-width: 28px; }
QScrollBar::handle:hover { background: #737373; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QCheckBox, QRadioButton { spacing: 8px; padding: 3px 0; }
QCheckBox:focus, QRadioButton:focus { color: #65dca5; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; border: 1px solid #737373; background: #212121; border-radius: 3px; }
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: #3ecf8e; border: 1px solid #a1f3c9; }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { background: #303030; border-color: #404040; }
QSlider::groove:horizontal { height: 4px; background: #404040; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #3ecf8e; }
QSlider::handle:horizontal { background: #ededed; width: 14px; margin: -5px 0; border-radius: 7px; }
QProgressBar { background: #111111; border: 1px solid #303030; border-radius: 5px; text-align: center; color: #ededed; min-height: 18px; font-size: 12px; }
QProgressBar::chunk { background: #207f55; border-radius: 4px; }
QSplitter::handle { background: #303030; }
QSplitter::handle:hover { background: #3ecf8e; }
QMenu, QToolTip { background: #252525; color: #ededed; border: 1px solid #505050; padding: 6px; }
QMenu::item { padding: 8px 20px; }
QMenu::item:selected { background: #315640; }
QMenu::separator { background: #404040; height: 1px; margin: 4px; }
"""

LIGHT_QSS = """
QWidget {
    color: #1d1e24;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}
/* Background is NOT applied to the generic QWidget: that would cause every
   label or plain container to paint its own box (different background /
   "underline" effect). */
QMainWindow { background-color: #ffffff; }
QStackedWidget, QStatusBar { background-color: #f5f6f8; }
QDialog, QMessageBox, QMenu, QToolTip { background-color: #f5f6f8; color: #1d1e24; }
QLabel { background: transparent; border: none; }

#Sidebar { background-color: #ffffff; border-right: 1px solid #e2e4ea; }
#SidebarButton {
    text-align: left; padding: 10px 16px; border: none; border-radius: 6px;
    color: #4a4d5c; background: transparent;
}
#SidebarButton:hover { background-color: #eef1f8; }
#SidebarButton:checked {
    background-color: transparent; color: #2563eb; border-left: 3px solid #2563eb;
}

#TopBar { background-color: #ffffff; border-bottom: 1px solid #e2e4ea; }

QPushButton {
    background-color: #2f6fed; color: white; border: none; border-radius: 6px;
    padding: 8px 16px; font-weight: 600;
}
QPushButton:hover { background-color: #487fee; }
QPushButton#SecondaryButton { background-color: #e9ebf1; color: #1d1e24; }

QLineEdit, QTextEdit, QComboBox, QSpinBox, QDateEdit {
    background-color: #ffffff; border: 1px solid #d9dce4; border-radius: 5px;
    padding: 6px 8px;
}
QTableWidget { background-color: #ffffff; gridline-color: #e2e4ea; border: 1px solid #e2e4ea; border-radius: 6px; }
QHeaderView::section { background-color: #f1f2f6; padding: 6px; border: none; border-bottom: 1px solid #e2e4ea; }

#Card { background-color: #ffffff; border: 1px solid #e2e4ea; border-radius: 10px; }
#StatValue { font-size: 26px; font-weight: 700; color: #1d1e24; }
#StatLabel { color: #7b7e8c; font-size: 12px; }

QPushButton#DangerButton { background-color: #c0392b; color: #ffffff; }
QPushButton#DangerButton:hover { background-color: #d64541; }

QPushButton#IconButton {
    background-color: transparent;
    border: none;
    border-radius: 4px;
    padding: 2px;
}
QPushButton#IconButton:hover { background-color: #e9ebf1; }

QPushButton#ChipButton {
    background-color: #eef1f8;
    border: 1px solid #d9dce4;
    border-radius: 14px;
    padding: 4px 12px;
    color: #1d1e24;
    font-size: 12px;
}
QPushButton#ChipButton:hover { background-color: #e4ebf7; border-color: #2f6fed; }

QPushButton#LinkButton {
    background: transparent;
    border: none;
    color: #2563eb;
    padding: 2px 4px;
    font-weight: 600;
}
QPushButton#LinkButton:hover { color: #1d4ed8; }
QPushButton#LinkButton:disabled { color: #9aa0ae; }

QProgressBar {
    background-color: #f1f2f6;
    border: 1px solid #d9dce4;
    border-radius: 6px;
    text-align: center;
    color: #4a4d5c;
    font-size: 11px;
    font-family: 'Consolas';
    height: 16px;
}
QProgressBar::chunk {
    background-color: #2f6fed;
    border-radius: 5px;
}
"""


def get_stylesheet(theme: str) -> str:
    """Return the QSS stylesheet for the given theme.

    Args:
        theme: Theme name (``"dark"`` or ``"light"``).

    Returns:
        QSS string for the requested theme.
    """
    return DARK_QSS if theme == "dark" else LIGHT_QSS
