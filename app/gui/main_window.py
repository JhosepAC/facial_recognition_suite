from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget, QLabel,
    QPushButton, QApplication
)

from app.core.config import settings
from app.core.logger import audit_logger, logger
from app.core.permissions import (
    PERM_ADMIN, PERM_BUSQUEDA, PERM_COMPARADOR, PERM_DASHBOARD,
    PERM_ESTADISTICAS, PERM_PERSONAS, PERM_VIDEO, PERM_WEBCAM,
    permissions_from_csv,
)
from app.database.session import get_session
from app.database.models import User
from app.gui import icons
from app.gui.theme import get_stylesheet
from app.gui.widgets.sidebar import Sidebar
from app.gui.widgets.dashboard import DashboardWidget
from app.gui.widgets.person_registration import PersonManagementWidget
from app.gui.widgets.search_compare import PersonSearchWidget, FaceCompareWidget
from app.gui.widgets.webcam_widget import WebcamWidget
from app.gui.widgets.video_widget import VideoAnalysisWidget
from app.gui.widgets.statistics_widget import StatisticsWidget
from app.gui.widgets.admin_widget import AdministrationWidget
from app.gui.widgets.login_widget import LoginDialog
from app.i18n import bus as i18n_bus
from app.i18n import tr

# Mapea cada entrada de navegación a los permisos que la habilitan.
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
    """¿Debe bloquearse la sesión por inactividad?

    ``timeout_minutes`` > 0 activa el bloqueo tras ese tiempo sin actividad;
    ``0`` lo desactiva (el lock de sesión queda a cargo del tope máximo).
    """
    timeout_seconds = timeout_minutes * 60
    return timeout_seconds > 0 and now - last_activity >= timeout_seconds


def _session_expired(max_minutes: int, session_started: float, now: float) -> bool:
    """¿Venció el tope absoluto de duración de la sesión?

    Independiente de la actividad: ``max_minutes`` > 0 limita la duración
    total; ``0`` significa sin tope.
    """
    max_seconds = max_minutes * 60
    return max_seconds > 0 and now - session_started >= max_seconds


class MainWindow(QMainWindow):
    def __init__(self, current_user_id: int):
        super().__init__()
        self.current_user_id = current_user_id
        self.logout_requested = False
        self._last_activity = time.time()
        self._session_started = time.time()

        with get_session() as session:
            user = session.get(User, current_user_id)
            self.username = user.username
            self.role_name = user.role.nombre if user.role else "Sin rol"
            self.permisos = permissions_from_csv(user.role.permisos_csv if user.role else "")

        self.setWindowTitle(tr("main_window.title", name=settings.app.name,
                               version=settings.app.version))
        self.resize(1360, 860)
        self.setStyleSheet(get_stylesheet(settings.app.theme))

        central = QWidget()
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        self.setCentralWidget(central)

        # --- Barra superior: usuario, rol, cerrar sesión ---
        top_bar = QWidget()
        top_bar.setObjectName("TopBar")
        top_bar.setFixedHeight(48)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 0, 16, 0)

        user_box = QWidget()
        user_layout = QHBoxLayout(user_box)
        user_layout.setContentsMargins(0, 0, 0, 0)
        user_layout.setSpacing(8)
        user_layout.addWidget(icons.icon_label("person", 18, "#b7b9c4"))
        self.user_label = QLabel()
        self.user_label.setStyleSheet("color: #b7b9c4;")
        user_layout.addWidget(self.user_label)
        top_layout.addWidget(user_box)
        top_layout.addStretch()

        self.logout_btn = QPushButton()
        self.logout_btn.setObjectName("SecondaryButton")
        self.logout_btn.setIcon(icons.icon("logout", 16, "#b7b9c4"))
        self.logout_btn.clicked.connect(self._logout)
        top_layout.addWidget(self.logout_btn)
        outer_layout.addWidget(top_bar)

        # --- Cuerpo: sidebar + contenido ---
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
        for page in self.pages.values():
            self.stack.addWidget(page)

        allowed_keys = {key for key, perm in NAV_PERMISSIONS.items()
                        if "*" in self.permisos or perm in self.permisos}
        self.sidebar.set_allowed_keys(allowed_keys)

        if "dashboard" in allowed_keys:
            self.stack.setCurrentWidget(self.dashboard)
        elif allowed_keys:
            self.stack.setCurrentWidget(self.pages[next(iter(allowed_keys))])

        # --- Bloqueo automático por inactividad ---
        QApplication.instance().installEventFilter(self)
        self._lock_timer = QTimer(self)
        self._lock_timer.setInterval(30_000)  # revisa cada 30s
        self._lock_timer.timeout.connect(self._check_inactivity)
        self._lock_timer.start()

        i18n_bus().languageChanged.connect(self._retranslate)
        self._retranslate()

    # ------------------------------------------------------------------ #
    def _retranslate(self, _language: str | None = None) -> None:
        self.setWindowTitle(tr("main_window.title", name=settings.app.name,
                               version=settings.app.version))
        self.user_label.setText(f"{self.username}  ·  {self.role_name}")
        self.logout_btn.setText(tr("main_window.logout"))

    # ------------------------------------------------------------------ #
    def _navigate(self, key: str) -> None:
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
            logger.exception("Error al refrescar el módulo '{}'", key)
        self.stack.setCurrentWidget(page)

    # ------------------------------------------------------------------ #
    def _logout(self) -> None:
        audit_logger.info("Cierre de sesión | username={}", self.username)
        self.logout_requested = True
        self.close()

    # ------------------------------------------------------------------ #
    # Bloqueo automático por inactividad
    # ------------------------------------------------------------------ #
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.KeyPress):
            self._last_activity = time.time()
        return super().eventFilter(obj, event)

    def _check_inactivity(self) -> None:
        now = time.time()
        if _session_should_lock(
            settings.security.session_timeout_minutes, self._last_activity, now
        ):
            self._lock_now()
            return

        # Tope absoluto de sesión: independiente de la actividad, la sesión
        # no debe durar más que lo configurado (0 = sin límite).
        if _session_expired(
            settings.security.max_session_minutes, self._session_started, now
        ):
            audit_logger.info(
                "Sesión expirada por tope máximo | username={}", self.username,
            )
            self._logout()

    def _lock_now(self) -> None:
        self._lock_timer.stop()
        audit_logger.info("Sesión bloqueada por inactividad | username={}", self.username)

        dialog = LoginDialog(self, lock_mode=True, prefill_username=self.username)
        result = dialog.exec()

        if result == LoginDialog.Accepted and dialog.authenticated_user_id == self.current_user_id:
            self._last_activity = time.time()
            self._lock_timer.start()
        else:
            # El usuario eligió cerrar sesión, o canceló: se trata como logout.
            self._lock_timer.start()
            self._logout()

    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:  # noqa: N802
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)
