"""Main application window and session management."""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.config import settings
from app.core.logger import audit_logger, logger
from app.core.permissions import (
    PERM_ADMIN,
    PERM_BUSQUEDA,
    PERM_COMPARADOR,
    PERM_DASHBOARD,
    PERM_ESTADISTICAS,
    PERM_PERSONAS,
    PERM_VIDEO,
    PERM_WEBCAM,
    permissions_from_csv,
)
from app.database.models import User
from app.database.session import get_session
from app.gui import icons
from app.gui.theme import get_palette, get_stylesheet
from app.gui.widgets.admin_widget import AdministrationWidget
from app.gui.widgets.dashboard import DashboardWidget
from app.gui.widgets.login_widget import LoginDialog
from app.gui.widgets.person_registration import PersonManagementWidget
from app.gui.widgets.search_compare import FaceCompareWidget, PersonSearchWidget
from app.gui.widgets.sidebar import Sidebar
from app.gui.widgets.sidebar import NAV_ITEMS
from app.gui.widgets.command_palette import CommandPalette
from app.gui.widgets.workspace_area import WorkspaceArea
from app.gui.widgets.statistics_widget import StatisticsWidget
from app.gui.widgets.video_widget import VideoAnalysisWidget
from app.gui.widgets.webcam_widget import WebcamWidget
from app.i18n import bus as i18n_bus
from app.i18n import tr

# Map each navigation entry to the permissions that enable it.
NAV_PERMISSIONS = {
    "dashboard": PERM_DASHBOARD,
    "personas": PERM_PERSONAS,
    "comparador": PERM_COMPARADOR,
    "busqueda": PERM_BUSQUEDA,
    "webcam": PERM_WEBCAM,
    "videos": PERM_VIDEO,
    "estadisticas": PERM_ESTADISTICAS,
    "administracion": PERM_ADMIN,
}


def _session_should_lock(timeout_minutes: int, last_activity: float, now: float) -> bool:
    """Check whether the session should be locked due to inactivity.

    Args:
        timeout_minutes: Inactivity timeout in minutes. ``0`` disables the check.
        last_activity: Timestamp of the last user activity.
        now: Current timestamp.

    Returns:
        True if the session should be locked.
    """
    timeout_seconds = timeout_minutes * 60
    return timeout_seconds > 0 and now - last_activity >= timeout_seconds


def _session_expired(max_minutes: int, session_started: float, now: float) -> bool:
    """Check whether the absolute session duration limit has been reached.

    Args:
        max_minutes: Maximum session duration in minutes. ``0`` means no limit.
        session_started: Timestamp when the session started.
        now: Current timestamp.

    Returns:
        True if the session has expired.
    """
    max_seconds = max_minutes * 60
    return max_seconds > 0 and now - session_started >= max_seconds


class MainWindow(QMainWindow):
    """Main window containing navigation, content stack, and session handling.

    Attributes:
        current_user_id: Identifier of the authenticated user.
        logout_requested: Whether the user requested an explicit logout.
    """

    def __init__(self, current_user_id: int):
        """Initialize the main window.

        Args:
            current_user_id: Identifier of the authenticated user.
        """
        super().__init__()
        self.current_user_id = current_user_id
        self.logout_requested = False
        self._last_activity = time.time()
        self._session_started = time.time()

        with get_session() as session:
            user = session.get(User, current_user_id)
            self.username = user.username
            self.role_name = user.role.nombre if user.role else "No role"
            self.permisos = permissions_from_csv(user.role.permisos_csv if user.role else "")

        self.setWindowTitle(tr("main_window.title", name=settings.app.name,
                               version=settings.app.version))
        self.resize(1360, 860)
        self.setMinimumSize(1040, 700)
        self.setStyleSheet(get_stylesheet(settings.app.theme))
        self.setPalette(get_palette(settings.app.theme))

        central = QWidget()
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        self.setCentralWidget(central)

        # --- Top bar: user, role, log out ---
        top_bar = QWidget()
        top_bar.setObjectName("TopBar")
        top_bar.setFixedHeight(60)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 0, 16, 0)

        user_box = QWidget()
        user_layout = QHBoxLayout(user_box)
        user_layout.setContentsMargins(0, 0, 0, 0)
        user_layout.setSpacing(8)
        user_layout.addWidget(icons.icon_label("person", 18, "#b4b4b4"))
        self.user_label = QLabel()
        self.user_label.setStyleSheet("color: #b4b4b4;")
        user_layout.addWidget(self.user_label)
        self.workspace_label = QLabel()
        self.workspace_label.setObjectName("WorkspaceTitle")
        top_layout.addWidget(self.workspace_label)
        top_layout.addStretch()
        self.quick_nav_btn = QPushButton()
        self.quick_nav_btn.setObjectName("SecondaryButton")
        self.quick_nav_btn.setIcon(icons.icon("search", 16))
        self.quick_nav_btn.clicked.connect(self._open_navigation)
        top_layout.addWidget(self.quick_nav_btn)
        top_layout.addWidget(user_box)

        self.logout_btn = QPushButton()
        self.logout_btn.setObjectName("SecondaryButton")
        self.logout_btn.setIcon(icons.icon("logout", 16, "#b4b4b4"))
        self.logout_btn.clicked.connect(self._logout)
        top_layout.addWidget(self.logout_btn)
        outer_layout.addWidget(top_bar)

        # --- Body: sidebar + content ---
        body = QWidget()
        root_layout = QHBoxLayout(body)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        outer_layout.addWidget(body, stretch=1)

        self.sidebar = Sidebar()
        self.sidebar.navigate.connect(self._navigate)
        root_layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack, stretch=1)

        self.dashboard = DashboardWidget()
        self.pages = {
            "dashboard": self.dashboard,
            "personas": PersonManagementWidget(self.username),
            "comparador": FaceCompareWidget(),
            "busqueda": PersonSearchWidget(self.username, self.permisos),
            "webcam": WebcamWidget(self.username),
            "videos": VideoAnalysisWidget(self.username),
            "estadisticas": StatisticsWidget(),
            "administracion": AdministrationWidget(self.username, self.current_user_id),
        }
        self.page_hosts = {}
        for key, page in self.pages.items():
            host = WorkspaceArea()
            host.setWidgetResizable(True)
            host.setWidget(page)
            self.page_hosts[key] = host
            self.stack.addWidget(host)

        allowed_keys = {key for key, perm in NAV_PERMISSIONS.items()
                        if "*" in self.permisos or perm in self.permisos}
        self.allowed_keys = allowed_keys
        self.sidebar.set_allowed_keys(allowed_keys)
        self.dashboard.set_allowed_keys(allowed_keys)
        self.dashboard.navigate.connect(self._navigate)
        self._nav_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._nav_shortcut.activated.connect(self._open_navigation)

        if "dashboard" in allowed_keys:
            self.stack.setCurrentWidget(self.page_hosts["dashboard"])
        elif allowed_keys:
            first_key = next(key for key, _, _ in NAV_ITEMS if key in allowed_keys)
            self._navigate(first_key)
        else:
            self.no_access_label = QLabel(tr("workspace.no_access"))
            self.no_access_label.setAlignment(Qt.AlignCenter)
            self.no_access_label.setWordWrap(True)
            self.stack.addWidget(self.no_access_label)
            self.stack.setCurrentWidget(self.no_access_label)

        # --- Automatic lock on inactivity ---
        QApplication.instance().installEventFilter(self)
        self._lock_timer = QTimer(self)
        self._lock_timer.setInterval(30_000)  # Check every 30s
        self._lock_timer.timeout.connect(self._check_inactivity)
        self._lock_timer.start()

        i18n_bus().languageChanged.connect(self._retranslate)
        self._retranslate()

    def _retranslate(self, _language: str | None = None) -> None:
        """Retranslate window title and top-bar labels."""
        self.setWindowTitle(tr("main_window.title", name=settings.app.name,
                               version=settings.app.version))
        self.user_label.setText(f"{self.username}  ·  {self.role_name}")
        self.logout_btn.setText(tr("main_window.logout"))
        self.quick_nav_btn.setText(tr("workspace.quick_navigation") + "  Ctrl+K")
        self.quick_nav_btn.setToolTip(tr("workspace.find_module"))
        if hasattr(self, "no_access_label"):
            self.no_access_label.setText(tr("workspace.no_access"))
            self.workspace_label.setText(tr("sidebar.app_name"))
        self._update_workspace_title()

    def _update_workspace_title(self) -> None:
        for key, label, _ in NAV_ITEMS:
            if self.stack.currentWidget() is self.page_hosts[key]:
                self.workspace_label.setText(tr("sidebar.app_name") + "  /  " + tr(label))
                break

    def _open_navigation(self) -> None:
        dialog = CommandPalette(self.allowed_keys, self)
        dialog.navigate.connect(self._navigate)
        dialog.exec()

    def _navigate(self, key: str) -> None:
        """Navigate to the page identified by key.

        Args:
            key: Navigation key (e.g., ``"dashboard"``).
        """
        permission = NAV_PERMISSIONS.get(key)
        if permission is None or ("*" not in self.permisos and permission not in self.permisos):
            return
        page = self.pages.get(key)
        if page is None:
            return
        try:
            if key == "dashboard":
                self.dashboard.refresh()
            elif key == "busqueda":
                self.pages["busqueda"].refresh_ui()
            elif key == "videos":
                self.pages["videos"].refresh_ui()
            elif key == "estadisticas":
                self.pages["estadisticas"].refresh()
            elif key == "administracion":
                self.pages["administracion"].refresh_all()
        except Exception:  # noqa: BLE001
            logger.exception("Error refreshing module '{}'", key)
        self.stack.setCurrentWidget(self.page_hosts[key])
        self.sidebar.select(key)
        self._update_workspace_title()

    def _logout(self) -> None:
        """Handle explicit logout and close the window."""
        audit_logger.info("Session closed | username={}", self.username)
        self.logout_requested = True
        self.close()

    # ------------------------------------------------------------------ #
    # Automatic lock on inactivity
    # ------------------------------------------------------------------ #
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """Track user activity to reset the inactivity timer.

        Args:
            obj: Object that triggered the event.
            event: Qt event.

        Returns:
            False to allow normal event propagation.
        """
        if event.type() in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.KeyPress):
            self._last_activity = time.time()
        return super().eventFilter(obj, event)

    def _check_inactivity(self) -> None:
        """Check timeouts and lock or expire the session if needed."""
        now = time.time()
        if _session_should_lock(
            settings.security.session_timeout_minutes, self._last_activity, now
        ):
            self._lock_now()
            return

        # Absolute session cap: regardless of activity, the session
        # must not exceed the configured limit (0 = unlimited).
        if _session_expired(
            settings.security.max_session_minutes, self._session_started, now
        ):
            audit_logger.info(
                "Session expired (max duration) | username={}", self.username,
            )
            self._logout()

    def _lock_now(self) -> None:
        """Lock the session and prompt for re-authentication."""
        self._lock_timer.stop()
        audit_logger.info("Session locked due to inactivity | username={}", self.username)

        dialog = LoginDialog(self, lock_mode=True, prefill_username=self.username)
        result = dialog.exec()

        if result == LoginDialog.Accepted and dialog.authenticated_user_id == self.current_user_id:
            self._last_activity = time.time()
            self._lock_timer.start()
        else:
            # User chose to log out or cancelled: treat as logout.
            self._lock_timer.start()
            self._logout()

    def closeEvent(self, event) -> None:  # noqa: N802
        """Remove the global event filter on close.

        Args:
            event: Close event.
        """
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)
