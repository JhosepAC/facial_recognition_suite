"""Navigation regressions: permissions, keyboard activation, and language changes."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.database.models import Role, User
from app.gui.widgets.command_palette import CommandPalette
from app.gui.widgets.sidebar import Sidebar
from app.gui.widgets.workspace_area import WorkspaceArea
from app.i18n import set_language, tr


def test_palette_filters_and_opens_only_authorized_modules(qt_app):
    set_language("en")
    palette = CommandPalette({"personas", "busqueda"})
    selected = []
    palette.navigate.connect(selected.append)
    assert palette.results.count() == 2
    palette.search.setText("SEARCH")
    QTest.keyClick(palette.search, Qt.Key_Return)
    assert selected == ["busqueda"]
    palette.search.setText("administration")
    QTest.keyClick(palette.search, Qt.Key_Return)
    assert selected == ["busqueda"]
    assert not palette.empty.isHidden()
    palette.close()


def test_palette_handles_no_permissions(qt_app):
    palette = CommandPalette(set())
    selected = []
    palette.navigate.connect(selected.append)
    QTest.keyClick(palette.search, Qt.Key_Return)
    assert selected == []
    assert not palette.empty.isHidden()
    palette.close()


def test_palette_arrow_keys_select_visible_results_from_search(qt_app):
    set_language("en")
    palette = CommandPalette({"dashboard", "personas", "videos"})
    selected = []
    palette.navigate.connect(selected.append)
    QTest.keyClick(palette.search, Qt.Key_Down)
    QTest.keyClick(palette.search, Qt.Key_Return)
    assert selected == ["personas"]
    palette.search.setText("video")
    QTest.keyClick(palette.search, Qt.Key_Up)
    QTest.keyClick(palette.search, Qt.Key_Return)
    assert selected == ["personas", "videos"]
    palette.close()


def test_workspace_stacks_compact_panels_and_restores_wide_layout(qt_app):
    from PySide6.QtWidgets import QSplitter, QVBoxLayout

    page = QWidget()
    layout = QVBoxLayout(page)
    splitter = QSplitter(Qt.Horizontal)
    splitter.setProperty("stackBelowWidth", 900)
    splitter.addWidget(QWidget())
    splitter.addWidget(QWidget())
    layout.addWidget(splitter)
    host = WorkspaceArea()
    host.setWidgetResizable(True)
    host.setWidget(page)
    host.resize(700, 600)
    host.show()
    qt_app.processEvents()
    assert splitter.orientation() == Qt.Vertical
    host.resize(1200, 700)
    qt_app.processEvents()
    assert splitter.orientation() == Qt.Horizontal
    host.close()


def test_sidebar_selection_and_live_translation(qt_app):
    sidebar = Sidebar()
    sidebar.set_allowed_keys({"videos", "busqueda"})
    sidebar.select("videos")
    assert sidebar._buttons["videos"].isChecked()
    assert sidebar._buttons["administracion"].isHidden()
    set_language("es")
    assert sidebar._buttons["videos"].text() == tr("sidebar.videos")
    set_language("en")
    sidebar.close()


def test_window_rejects_unauthorized_navigation_and_syncs_shortcuts(qt_app, monkeypatch):
    from app.database import session as db
    from app.gui import main_window

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=engine))
    with db.get_session() as session:
        role = Role(nombre="Search only", permisos_csv=main_window.PERM_BUSQUEDA)
        session.add(role)
        session.flush()
        user = User(username="navigation_test", password_hash="unused", role_id=role.id)
        session.add(user)
        session.flush()
        uid = user.id
    for name in ("PersonManagementWidget", "FaceCompareWidget", "PersonSearchWidget",
                 "WebcamWidget", "VideoAnalysisWidget", "StatisticsWidget", "AdministrationWidget"):
        monkeypatch.setattr(main_window, name, lambda *_args: QWidget())
    window = main_window.MainWindow(uid)
    try:
        assert window.stack.currentWidget() is window.page_hosts["busqueda"]
        assert window.sidebar._buttons["busqueda"].isChecked()
        assert window.dashboard.actions["personas"][0].isHidden()
        window._navigate("administracion")
        assert window.stack.currentWidget() is window.page_hosts["busqueda"]
        window._navigate("unknown")
        assert window.stack.currentWidget() is window.page_hosts["busqueda"]
        with db.get_session() as session:
            session.query(Role).first().permisos_csv = ""
        no_access = main_window.MainWindow(uid)
        try:
            assert no_access.stack.currentWidget() is no_access.no_access_label
            no_access._navigate("dashboard")
            assert no_access.stack.currentWidget() is no_access.no_access_label
        finally:
            no_access.close()
            no_access.deleteLater()
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()
        engine.dispose()


def test_search_detail_language_switch_covers_all_attributes(qt_app, monkeypatch):
    from app.gui.widgets.search_compare import PersonSearchWidget

    monkeypatch.setattr(PersonSearchWidget, "refresh_ui", lambda self: None)
    widget = PersonSearchWidget("preview", {"*"})
    try:
        set_language("es")
        widget._retranslate()
        set_language("en")
        widget._retranslate()
        assert widget._attr_name_items["edad"].text() == tr("attrs.age")
    finally:
        widget.close()
        widget.deleteLater()
