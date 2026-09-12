"""Temas visuales (QSS) inspirados en herramientas profesionales tipo IDE."""

DARK_QSS = """
QWidget {
    color: #e6e6e6;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}
/* El fondo NO se aplica al QWidget genérico: eso haría que cada etiqueta o
   contenedor plano pintara una caja propia (fondo distinto / "subrayado").
   Solo pintan las superficies estructurales y las tarjetas explícitas. */
QMainWindow { background-color: #16171c; }
QStackedWidget, QStatusBar { background-color: #1e1f26; }
QDialog, QMessageBox, QMenu, QToolTip { background-color: #1e1f26; color: #e6e6e6; }
QLabel { background: transparent; border: none; }

#Sidebar {
    background-color: #14151a;
    border-right: 1px solid #2a2b33;
}
#SidebarButton {
    text-align: left;
    padding: 10px 16px;
    border: none;
    border-radius: 6px;
    color: #b7b9c4;
    background: transparent;
}
#SidebarButton:hover { background-color: #22232c; color: #ffffff; }
#SidebarButton:checked {
    background-color: transparent;
    color: #3b82f6;
    border-left: 3px solid #3b82f6;
}

#TopBar {
    background-color: #191a20;
    border-bottom: 1px solid #2a2b33;
}

QPushButton {
    background-color: #2f6fed;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton:hover { background-color: #4c84ff; }
QPushButton:pressed { background-color: #2258c9; }
QPushButton:disabled { background-color: #33343d; color: #77798a; }

QPushButton#SecondaryButton {
    background-color: #2a2b33;
    color: #e6e6e6;
}
QPushButton#SecondaryButton:hover { background-color: #34353f; }

QLineEdit, QTextEdit, QComboBox, QSpinBox, QDateEdit {
    background-color: #24252d;
    border: 1px solid #34353f;
    border-radius: 5px;
    padding: 6px 8px;
    color: #e6e6e6;
    selection-background-color: #2f6fed;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border: 1px solid #6fa8ff; }

QTableWidget {
    background-color: #1a1b21;
    gridline-color: #2a2b33;
    border: 1px solid #2a2b33;
    border-radius: 6px;
}
QHeaderView::section {
    background-color: #22232c;
    color: #b7b9c4;
    padding: 6px;
    border: none;
    border-bottom: 1px solid #2a2b33;
}
QTableWidget::item:selected { background-color: #2f6fed44; }

QTabWidget::pane { border: 1px solid #2a2b33; border-radius: 6px; }
QTabBar::tab {
    background: #1a1b21; padding: 8px 16px; color: #b7b9c4;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
}
QTabBar::tab:selected { background: #24252d; color: #ffffff; }

QScrollBar:vertical { background: #1a1b21; width: 10px; }
QScrollBar::handle:vertical { background: #34353f; border-radius: 5px; }

#Card {
    background-color: #22232c;
    border: 1px solid #2a2b33;
    border-radius: 10px;
}
#StatValue { font-size: 26px; font-weight: 700; color: #ffffff; }
#StatLabel { color: #8f92a3; font-size: 12px; }

QPushButton#DangerButton {
    background-color: #b03a2e;
    color: #ffffff;
}
QPushButton#DangerButton:hover { background-color: #c0392b; }

QPushButton#IconButton {
    background-color: transparent;
    border: none;
    border-radius: 4px;
    padding: 2px;
}
QPushButton#IconButton:hover { background-color: #34353f; }

QPushButton#ChipButton {
    background-color: #2a2b33;
    border: 1px solid #34353f;
    border-radius: 14px;
    padding: 4px 12px;
    color: #e6e6e6;
    font-size: 12px;
}
QPushButton#ChipButton:hover { background-color: #34353f; border-color: #4880e8; }

QPushButton#LinkButton {
    background: transparent;
    border: none;
    color: #3b82f6;
    padding: 2px 4px;
    font-weight: 600;
}
QPushButton#LinkButton:hover { color: #5b96f7; }
QPushButton#LinkButton:disabled { color: #6b6e7d; }

QProgressBar {
    background-color: #1a1b21;
    border: 1px solid #2a2b33;
    border-radius: 6px;
    text-align: center;
    color: #b7b9c4;
    font-size: 11px;
    font-family: 'Consolas';
    height: 16px;
}
QProgressBar::chunk {
    background-color: #2f6fed;
    border-radius: 5px;
}
"""

LIGHT_QSS = """
QWidget {
    color: #1d1e24;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}
/* El fondo NO se aplica al QWidget genérico: eso haría que cada etiqueta o
   contenedor plano pintara una caja propia (fondo distinto / "subrayado"). */
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
    return DARK_QSS if theme == "dark" else LIGHT_QSS
