"""
Administration module (bounded context: ADMIN).

Redesigned to:
  - visually improve each tab (cards, icons, searches, states)
  - strengthen logic: anti-lockout protection (last admin), validations,
    confirmations for destructive actions, permission/role consistency
  - connect to AUTH: roles managed here determine which modules
    remain visible in the dashboard (module locking).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSlider, QSpinBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from app.core.config import settings, save_setting
from app.core.exceptions import BioVisionError
from app.core.logger import logger
from app.core.permissions import ALL_PERMISSIONS, PERMISSION_LABELS
from app.core.security import DecryptionError
from app.database.models import AuditLog, User
from app.database.session import get_session
from app.gui import icons
from app.gui.widgets.login_widget import PasswordField
from app.i18n import bus as i18n_bus
from app.i18n import set_language as set_i18n_language
from app.i18n import tr
from app.services.admin_service import AdminService
from app.services.auth_service import AuthService
from app.services.calibration_service import CalibrationService
from app.services.export_service import ExportService
from app.services.preferences_service import PreferencesService
from app.vision.face_attributes import ATTR_FIELDS, default_thresholds

COLOR_OK = icons.COLOR_OK
COLOR_WARN = icons.COLOR_WARN
COLOR_ERROR = icons.COLOR_ERROR
COLOR_MUTED = icons.COLOR_MUTED


def _error_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #e85d5d;")
    return label


def _status_color(user: User) -> tuple[str, str]:
    if not user.activo:
        return "Desactivada", COLOR_ERROR
    if user.bloqueado_hasta and user.bloqueado_hasta > datetime.utcnow():
        return "Bloqueada", COLOR_WARN
    return "Activa", COLOR_OK


def _confirm_action(parent: QWidget, title: str, message: str) -> bool:
    return QMessageBox.question(parent, title, message) == QMessageBox.Yes


# ====================================================================== #
# Dialog: change my password (requires current password)
# ====================================================================== #
class ChangePasswordDialog(QDialog):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.setWindowTitle("Cambiar mi contraseña")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        intro = QLabel(icons.status_html(
            "person",
            "Cambia la contraseña de tu propia cuenta. Necesitarás escribir la actual.",
            "#8f92a3", 13,
        ))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(10)
        self.current_field = PasswordField("Contraseña actual")
        self.new_field = PasswordField("Nueva contraseña")
        self.confirm_field = PasswordField("Confirmar nueva contraseña")
        form.addRow("Actual *", self.current_field)
        form.addRow("Nueva *", self.new_field)
        form.addRow("Confirmar *", self.confirm_field)
        layout.addLayout(form)

        hint = QLabel(AuthService.password_policy_hint() + ".")
        hint.setStyleSheet("color: #8f92a3; font-size: 11px;")
        layout.addWidget(hint)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #e85d5d;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Guardar contraseña")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn, stretch=2)
        btn_row.addWidget(cancel_btn, stretch=1)
        layout.addLayout(btn_row)

    def _on_save(self) -> None:
        current = self.current_field.text()
        new = self.new_field.text()
        confirm = self.confirm_field.text()
        if not current or not new:
            self.error_label.setText(icons.err("Ingresa tu contraseña actual y la nueva."))
            return
        if new != confirm:
            self.error_label.setText(icons.err("Las contraseñas no coinciden."))
            self.confirm_field.clear()
            return
        try:
            with get_session() as session:
                AuthService(session).change_own_password(self.user_id, current, new)
            self.accept()
        except Exception as exc:  # noqa: BLE001  (AuthenticationError / ValueError)
            self.error_label.setText(icons.err(str(exc)))


# ====================================================================== #
# Tab: Users
# ====================================================================== #
class TotpSetupDialog(QDialog):
    """Configure/disable two-factor authentication (TOTP) for a user.

    Flow: if the user has no 2FA, a secret is generated, its
    otpauth URI is shown and the current code from the authenticator app is
    requested to confirm pairing. If already has 2FA, allows disabling it.
    """

    def __init__(self, user_id: int, username: str, actor_username: str, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.username = username
        self.actor_username = actor_username
        self.result_message = ""
        self._secret: str | None = None
        self.setWindowTitle(f"2FA — {username}")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        intro = QLabel(icons.status_html(
            "security",
            "La verificación en dos pasos exige un código generado por una app "
            "autenticadora (Google Authenticator, Authy…) además de la contraseña.",
            "#8f92a3", 13,
        ))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.secret_edit = QLineEdit()
        self.secret_edit.setReadOnly(True)
        self.secret_edit.setPlaceholderText("Secreto (solo se muestra una vez al habilitar)")
        self.uri_edit = QLineEdit()
        self.uri_edit.setReadOnly(True)
        self.uri_edit.setPlaceholderText("URI otpauth:// (para escanear con la app)")
        layout.addWidget(self.secret_edit)
        layout.addWidget(self.uri_edit)
        self.secret_edit.setVisible(False)
        self.uri_edit.setVisible(False)

        self.code_field = PasswordField("Código de 6 dígitos de la app")
        self.code_field.setVisible(False)
        layout.addWidget(self.code_field)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #e85d5d;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        btn_row = QHBoxLayout()
        self.action_btn = QPushButton()
        self.action_btn.clicked.connect(self._on_action)
        cancel_btn = QPushButton("Cerrar")
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.action_btn, stretch=2)
        btn_row.addWidget(cancel_btn, stretch=1)
        layout.addLayout(btn_row)

        self._load_state()

    def _load_state(self) -> None:
        with get_session() as session:
            enabled = AdminService(session).is_user_totp_enabled(
                self.user_id, usuario_actor=self.actor_username)
        if enabled:
            self.status_label.setText(
                icons.ok(f"El usuario '{self.username}' tiene la verificación en dos pasos ACTIVADA.")
            )
            self.action_btn.setText("Desactivar 2FA")
            self.action_btn.setObjectName("DangerButton")
        else:
            self.status_label.setText(
                f"El usuario '{self.username}' no tiene verificación en dos pasos. "
                "Pulsa 'Generar secreto' para habilitarla."
            )
            self.action_btn.setText("Generar secreto")
            self.action_btn.setObjectName("")

    def _on_action(self) -> None:
        if self.action_btn.text() == "Desactivar 2FA":
            if not _confirm_action(self, "Desactivar 2FA",
                                   f"¿Desactivar la verificación en dos pasos de '{self.username}'?"):
                return
            try:
                with get_session() as session:
                    AdminService(session).disable_user_totp(self.user_id,
                                                            usuario_actor=self.actor_username)
                self.result_message = f"2FA desactivado para '{self.username}'."
                self.accept()
            except BioVisionError as exc:
                self.error_label.setText(icons.err(str(exc)))
            return

        if self._secret is None:
            try:
                with get_session() as session:
                    self._secret = AdminService(session).generate_totp_secret(
                        usuario_actor=self.actor_username)
                    self._uri = AdminService(session).user_totp_uri(
                        self.user_id, self._secret, usuario_actor=self.actor_username)
            except BioVisionError as exc:
                self.error_label.setText(icons.err(str(exc)))
                return
            self.secret_edit.setText(self._secret)
            self.uri_edit.setText(self._uri)
            self.secret_edit.setVisible(True)
            self.uri_edit.setVisible(True)
            self.code_field.setVisible(True)
            self.action_btn.setText("Confirmar y activar")
            self.code_field.set_focus()
            self.status_label.setText(
                "Agrega el secreto a tu app autenticadora y escribe el código que "
                "muestra ahora para confirmar."
            )
            return

        code = self.code_field.text().strip()
        if not code:
            self.error_label.setText(icons.err("Ingresa el código de 6 dígitos de la app."))
            return
        try:
            with get_session() as session:
                AdminService(session).enable_user_totp(
                    self.user_id, self._secret, code, usuario_actor=self.actor_username)
            self.result_message = f"2FA activado para '{self.username}'."
            self.accept()
        except BioVisionError as exc:
            self.error_label.setText(icons.err(str(exc)))


# ====================================================================== #
# Tab: Users
# ====================================================================== #
class UsersTab(QWidget):
    def __init__(self, current_username: str, current_user_id: int, parent=None):
        super().__init__(parent)
        self.current_username = current_username
        self.current_user_id = current_user_id
        self._user_meta: dict[int, tuple[str, str]] = {}
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # -- Header: search and refresh -------------------------
        header = QHBoxLayout()
        header.addWidget(QLabel("Usuarios del sistema"))
        header.addStretch()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar por usuario o nombre…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMaximumWidth(260)
        self.search_edit.textChanged.connect(self._apply_filter)
        header.addWidget(self.search_edit)
        refresh_btn = QPushButton("Actualizar")
        refresh_btn.setObjectName("SecondaryButton")
        refresh_btn.setIcon(icons.icon("refresh", 16))
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        root.addLayout(header)

        # -- Table -------------------------------------------------------
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Usuario", "Nombre completo", "Rol", "Estado", "Último login"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self.table, stretch=1)

        # -- Actions bar sobre el seleccionado --------------------
        actions = QGroupBox("Acciones sobre el usuario seleccionado")
        grid = QGridLayout(actions)
        grid.setSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self.role_combo = QComboBox()
        apply_role_btn = QPushButton("Aplicar rol")
        apply_role_btn.setObjectName("SecondaryButton")
        apply_role_btn.setIcon(icons.icon("swap_horiz", 16))
        apply_role_btn.clicked.connect(self._change_role)
        grid.addWidget(QLabel("Cambiar rol:"), 0, 0)
        grid.addWidget(self.role_combo, 0, 1)
        grid.addWidget(apply_role_btn, 0, 2)

        self.new_password_field = PasswordField("Nueva contraseña")
        reset_btn = QPushButton("Restablecer contraseña")
        reset_btn.setObjectName("SecondaryButton")
        reset_btn.clicked.connect(self._reset_password)
        grid.addWidget(QLabel("Contraseña:"), 1, 0)
        grid.addWidget(self.new_password_field, 1, 1)
        grid.addWidget(reset_btn, 1, 2)

        self.toggle_active_btn = QPushButton("Activar / Desactivar")
        self.toggle_active_btn.setObjectName("SecondaryButton")
        self.toggle_active_btn.clicked.connect(self._toggle_active)
        delete_btn = QPushButton("Eliminar usuario")
        delete_btn.setObjectName("DangerButton")
        delete_btn.setIcon(icons.icon("delete", 16))
        delete_btn.clicked.connect(self._delete_user)
        grid.addWidget(self.toggle_active_btn, 2, 0)
        grid.addWidget(delete_btn, 2, 1, 1, 2)

        my_pass_btn = QPushButton("Cambiar mi contraseña")
        my_pass_btn.setObjectName("SecondaryButton")
        my_pass_btn.setIcon(icons.icon("key", 16))
        my_pass_btn.clicked.connect(self._open_change_own_password)
        grid.addWidget(my_pass_btn, 3, 0)
        row3_hint = QLabel("Tu propia cuenta (requiere la contraseña actual)")
        row3_hint.setStyleSheet("color: #8f92a3; font-size: 11px;")
        grid.addWidget(row3_hint, 3, 1, 1, 2)

        self.totp_btn = QPushButton("Configurar verificación en 2 pasos (2FA)")
        self.totp_btn.setObjectName("SecondaryButton")
        self.totp_btn.setIcon(icons.icon("security", 16))
        self.totp_btn.clicked.connect(self._open_totp_dialog)
        grid.addWidget(self.totp_btn, 4, 0, 1, 3)
        root.addWidget(actions)

        # -- Bottom column: create user ----------------------------
        create_box = QGroupBox("Crear nuevo usuario")
        form = QFormLayout(create_box)
        form.setSpacing(8)
        self.new_username_edit = QLineEdit()
        self.new_nombre_edit = QLineEdit()
        self.new_password_create_field = PasswordField("Contraseña")
        self.new_confirm_field = PasswordField("Confirmar contraseña")
        self.new_role_combo = QComboBox()

        form.addRow("Usuario *", self.new_username_edit)
        form.addRow("Nombre completo", self.new_nombre_edit)
        form.addRow("Contraseña *", self.new_password_create_field)
        form.addRow("Confirmar contraseña *", self.new_confirm_field)
        form.addRow("Rol *", self.new_role_combo)

        hint = QLabel(AuthService.password_policy_hint() + ".")
        hint.setStyleSheet("color: #8f92a3; font-size: 11px;")
        form.addRow(hint)

        create_btn = QPushButton("Crear usuario")
        create_btn.setIcon(icons.icon("person_add", 16))
        create_btn.clicked.connect(self._create_user)
        form.addRow(create_btn)
        root.addWidget(create_box)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        with get_session() as session:
            svc = AdminService(session)
            users = svc.list_users()
            roles = svc.list_roles()
            rows = []
            for u in users:
                estado, color = _status_color(u)
                ultimo = u.ultimo_login.strftime("%Y-%m-%d %H:%M") if u.ultimo_login else "—"
                rows.append((u.id, u.username, u.nombre_completo or "",
                             u.role.nombre if u.role else "Sin rol",
                             estado, color, ultimo))
            role_options = [(r.id, r.nombre) for r in roles]

        self._user_meta = {}
        self.table.setRowCount(len(rows))
        for i, (uid, username, nombre, rol, estado, color, ultimo) in enumerate(rows):
            self._user_meta[uid] = (estado, color)

            item_user = QTableWidgetItem(username)
            item_user.setData(Qt.UserRole, uid)
            self.table.setItem(i, 0, item_user)
            self.table.setItem(i, 1, QTableWidgetItem(nombre))
            self.table.setItem(i, 2, QTableWidgetItem(rol))

            item_estado = QTableWidgetItem(estado)
            item_estado.setForeground(QColor(color))
            self.table.setItem(i, 3, item_estado)
            self.table.setItem(i, 4, QTableWidgetItem(ultimo))

        for combo in (self.role_combo, self.new_role_combo):
            combo.clear()
            for role_id, nombre in role_options:
                combo.addItem(nombre, userData=role_id)

        self._apply_filter()
        self._update_action_labels()
        self.status_label.setText("")

    def _apply_filter(self) -> None:
        term = self.search_edit.text().strip().lower()
        for i in range(self.table.rowCount()):
            user_item = self.table.item(i, 0)
            name_item = self.table.item(i, 1)
            haystack = f"{user_item.text() if user_item else ''} {name_item.text() if name_item else ''}".lower()
            self.table.setRowHidden(i, bool(term) and term not in haystack)

    def _update_action_labels(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self.toggle_active_btn.setText("Activar / Desactivar")
            return
        estado = self.table.item(row, 3).text()
        self.toggle_active_btn.setText("Activar cuenta" if estado == "Desactivada" else "Desactivar cuenta")

    def _selected_user_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _on_selection_changed(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            user_id = self._selected_user_id()
            rol_text = self.table.item(row, 2).text()
            index = self.role_combo.findText(rol_text)
            if index >= 0:
                self.role_combo.setCurrentIndex(index)
        self._update_action_labels()

    # ------------------------------------------------------------------ #
    def _create_user(self) -> None:
        username = self.new_username_edit.text().strip()
        password = self.new_password_create_field.text()
        confirm = self.new_confirm_field.text()
        role_id = self.new_role_combo.currentData()
        if not username or not password or role_id is None:
            self.status_label.setText(icons.warn("Completa usuario, contraseña y rol."))
            return
        if password != confirm:
            self.status_label.setText(icons.err("Las contraseñas no coinciden."))
            self.new_confirm_field.clear()
            return
        try:
            with get_session() as session:
                AdminService(session).create_user(
                    username, password, role_id,
                    self.new_nombre_edit.text().strip() or None,
                    usuario_actor=self.current_username,
                )
            self.new_username_edit.clear()
            self.new_nombre_edit.clear()
            self.new_password_create_field.clear()
            self.new_confirm_field.clear()
            self.refresh()
            self.status_label.setText(icons.ok(f"Usuario '{username}' creado."))
        except (BioVisionError, ValueError) as exc:
            self.status_label.setText(icons.err(str(exc)))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error creando usuario")
            self.status_label.setText(icons.err(f"Error inesperado: {exc}"))

    def _change_role(self) -> None:
        user_id = self._selected_user_id()
        role_id = self.role_combo.currentData()
        if user_id is None or role_id is None:
            return
        try:
            with get_session() as session:
                AdminService(session).update_user_role(user_id, role_id, usuario_actor=self.current_username)
            self.refresh()
            self.status_label.setText(icons.ok("Rol actualizado."))
        except BioVisionError as exc:
            QMessageBox.warning(self, "No se pudo cambiar el rol", str(exc))

    def _reset_password(self) -> None:
        user_id = self._selected_user_id()
        new_password = self.new_password_field.text()
        if user_id is None or not new_password:
            QMessageBox.warning(self, "Falta información",
                                "Selecciona un usuario e ingresa la nueva contraseña.")
            return
        try:
            with get_session() as session:
                AdminService(session).reset_password(user_id, new_password, usuario_actor=self.current_username)
            self.new_password_field.clear()
            QMessageBox.information(self, "Listo", "Contraseña restablecida correctamente.")
        except ValueError as exc:
            QMessageBox.warning(self, "Contraseña inválida", str(exc))
        except BioVisionError as exc:
            QMessageBox.warning(self, "No se pudo restablecer", str(exc))

    def _toggle_active(self) -> None:
        row = self.table.currentRow()
        user_id = self._selected_user_id()
        if user_id is None:
            return
        username = self.table.item(row, 0).text()
        if username == self.current_username:
            QMessageBox.warning(self, "Acción no permitida", "No puedes desactivar tu propia cuenta.")
            return

        eso_activo = self.table.item(row, 3).text() != "Desactivada"
        accion = "desactivar" if eso_activo else "activar"
        if not _confirm_action(self, "Confirmar", f"¿{accion.capitalize()} el usuario '{username}'?"):
            return
        try:
            with get_session() as session:
                AdminService(session).set_user_active(user_id, not eso_activo, usuario_actor=self.current_username)
            self.refresh()
        except BioVisionError as exc:
            QMessageBox.warning(self, "No se pudo cambiar el estado", str(exc))

    def _delete_user(self) -> None:
        row = self.table.currentRow()
        user_id = self._selected_user_id()
        if user_id is None:
            return
        username = self.table.item(row, 0).text()
        if username == self.current_username:
            QMessageBox.warning(self, "Acción no permitida", "No puedes eliminar tu propia cuenta.")
            return
        if not _confirm_action(
            self, "Confirmar eliminación",
            f"¿Eliminar al usuario '{username}'? This action cannot be undone.",
        ):
            return
        try:
            with get_session() as session:
                AdminService(session).delete_user(user_id, usuario_actor=self.current_username)
            self.refresh()
        except BioVisionError as exc:
            QMessageBox.warning(self, "No se pudo eliminar", str(exc))

    def _open_change_own_password(self) -> None:
        dlg = ChangePasswordDialog(self.current_user_id, self)
        if dlg.exec() == QDialog.Accepted:
            QMessageBox.information(self, "Listo", "Tu contraseña fue actualizada correctamente.")

    def _open_totp_dialog(self) -> None:
        user_id = self._selected_user_id()
        if user_id is None:
            QMessageBox.information(self, "2FA",
                                    "Selecciona un usuario de la tabla para configurar su verificación.")
            return
        username = self.table.item(self.table.currentRow(), 0).text()
        dlg = TotpSetupDialog(user_id, username, self.current_username, self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()
            QMessageBox.information(self, "2FA", dlg.result_message)


# ====================================================================== #
# Tab: Roles and permissions (define per-user module locking)
# ====================================================================== #
class RolesTab(QWidget):
    def __init__(self, current_username: str, parent=None):
        super().__init__(parent)
        self.current_username = current_username
        self._checkboxes: dict[str, QCheckBox] = {}
        self._selected_role_id: int | None = None
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setSpacing(12)

        left = QVBoxLayout()
        header = QHBoxLayout()
        header.addWidget(QLabel("Roles del sistema"))
        header.addStretch()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar rol…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMaximumWidth(200)
        self.search_edit.textChanged.connect(self._apply_filter)
        header.addWidget(self.search_edit)
        refresh_btn = QPushButton("Actualizar")
        refresh_btn.setObjectName("SecondaryButton")
        refresh_btn.setIcon(icons.icon("refresh", 16))
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        left.addLayout(header)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Rol", "Usuarios", "Permisos"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setColumnWidth(0, 160)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_role_selected)
        left.addWidget(self.table, stretch=1)

        delete_btn = QPushButton("Eliminar rol seleccionado")
        delete_btn.setObjectName("DangerButton")
        delete_btn.setIcon(icons.icon("delete", 16))
        delete_btn.clicked.connect(self._delete_role)
        left.addWidget(delete_btn)
        root.addLayout(left, stretch=1)

        # -- Editor ------------------------------------------------------
        editor = QGroupBox("Editor de rol")
        ed_layout = QVBoxLayout(editor)
        ed_layout.setSpacing(10)

        form = QFormLayout()
        self.role_name_edit = QLineEdit()
        form.addRow("Nombre del rol", self.role_name_edit)
        ed_layout.addLayout(form)

        self.wildcard_cb = QCheckBox("Todos los permisos (*)")
        self.wildcard_cb.toggled.connect(self._on_wildcard_toggled)
        ed_layout.addWidget(self.wildcard_cb)

        ed_layout.addWidget(QLabel("Permisos específicos"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        for idx, perm in enumerate(ALL_PERMISSIONS):
            cb = QCheckBox(PERMISSION_LABELS.get(perm, perm))
            self._checkboxes[perm] = cb
            grid.addWidget(cb, idx // 2, idx % 2)
        ed_layout.addLayout(grid)

        quick_row = QHBoxLayout()
        all_btn = QPushButton("Marcar todos")
        all_btn.setObjectName("ChipButton")
        all_btn.clicked.connect(lambda: [cb.setChecked(True) for cb in self._checkboxes.values()])
        none_btn = QPushButton("Desmarcar todos")
        none_btn.setObjectName("ChipButton")
        none_btn.clicked.connect(lambda: [cb.setChecked(False) for cb in self._checkboxes.values()])
        quick_row.addWidget(all_btn)
        quick_row.addWidget(none_btn)
        quick_row.addStretch()
        ed_layout.addLayout(quick_row)

        btn_row = QHBoxLayout()
        create_btn = QPushButton("Crear rol")
        create_btn.clicked.connect(self._create_role)
        btn_row.addWidget(create_btn)
        dup_btn = QPushButton("Duplicar en editor")
        dup_btn.setObjectName("SecondaryButton")
        dup_btn.clicked.connect(self._duplicate_role)
        btn_row.addWidget(dup_btn)
        save_btn = QPushButton("Guardar cambios")
        save_btn.clicked.connect(self._save_permissions)
        btn_row.addWidget(save_btn)
        ed_layout.addLayout(btn_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        ed_layout.addWidget(self.status_label)
        ed_layout.addStretch()

        root.addWidget(editor, stretch=1)

    # ------------------------------------------------------------------ #
    def _on_wildcard_toggled(self, checked: bool) -> None:
        for cb in self._checkboxes.values():
            cb.setEnabled(not checked)
            cb.setChecked(False)

    def _checked_permissions(self) -> list[str]:
        if self.wildcard_cb.isChecked():
            return ["*"]
        return [perm for perm, cb in self._checkboxes.items() if cb.isChecked()]

    def _load_permissions(self, permisos_csv: str) -> None:
        es_total = permisos_csv.strip() == "*"
        self.wildcard_cb.setChecked(es_total)
        for perm, cb in self._checkboxes.items():
            cb.setEnabled(not es_total)
            cb.setChecked(es_total or perm in permisos_csv)

    def refresh(self) -> None:
        with get_session() as session:
            svc = AdminService(session)
            roles = svc.list_roles()
            role_counts: dict[str, int] = {}
            for r in roles:
                role_counts[r.nombre] = session.query(User).filter(User.role_id == r.id).count()
            rows = [(r.id, r.nombre,
                     r.permisos_csv or "",
                     role_counts.get(r.nombre, 0))
                    for r in roles]

        self.table.setRowCount(len(rows))
        for i, (role_id, nombre, permisos, count) in enumerate(rows):
            etiqueta = "Todos los permisos (*)" if permisos.strip() == "*" else (permisos or "—")
            item = QTableWidgetItem(nombre)
            item.setData(Qt.UserRole, role_id)
            self.table.setItem(i, 0, item)
            item_count = QTableWidgetItem(str(count))
            item_count.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 1, item_count)
            self.table.setItem(i, 2, QTableWidgetItem(etiqueta))
        self._apply_filter()

    def _apply_filter(self) -> None:
        term = self.search_edit.text().strip().lower()
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            hay = (item.text() if item else "").lower()
            self.table.setRowHidden(i, bool(term) and term not in hay)

    def _selected_role_data(self) -> tuple[int | None, str, str]:
        row = self.table.currentRow()
        if row < 0:
            return None, "", ""
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole), item.text(), self.table.item(row, 2).text()

    def _on_role_selected(self) -> None:
        role_id, nombre, etiqueta = self._selected_role_data()
        if role_id is None:
            return
        self._selected_role_id = role_id
        with get_session() as session:
            role = AdminService(session).roles.get(role_id)
            if role is None:
                return
            self.role_name_edit.setText(role.nombre)
            self._load_permissions(role.permisos_csv or "")

    def _create_role(self) -> None:
        nombre = self.role_name_edit.text().strip()
        if not nombre:
            self.status_label.setText(icons.warn("Ingresa un nombre de rol."))
            return
        try:
            with get_session() as session:
                AdminService(session).create_role(nombre, self._checked_permissions(),
                                                   usuario_actor=self.current_username)
            self.status_label.setText(icons.ok(f"Rol '{nombre}' creado."))
            self.refresh()
        except BioVisionError as exc:
            self.status_label.setText(icons.err(str(exc)))

    def _save_permissions(self) -> None:
        if self._selected_role_id is None:
            self.status_label.setText(icons.warn("Selecciona primero un rol de la tabla."))
            return
        nombre = self.role_name_edit.text().strip()
        if not nombre:
            self.status_label.setText(icons.warn("El nombre del rol no puede quedar vacío."))
            return
        try:
            with get_session() as session:
                svc = AdminService(session)
                role = svc.roles.get(self._selected_role_id)
                if role is None:
                    raise BioVisionError("Selected role no longer exists.")
                if role.nombre != nombre:
                    if svc.roles.get_by_name(nombre) is not None:
                        raise BioVisionError(f"Ya existe un rol llamado '{nombre}'.")
                    role.nombre = nombre
                svc.update_role_permissions(role.id, self._checked_permissions(),
                                            usuario_actor=self.current_username)
            self.status_label.setText(icons.ok("Permisos actualizados."))
            self.refresh()
        except BioVisionError as exc:
            self.status_label.setText(icons.err(str(exc)))

    def _duplicate_role(self) -> None:
        role_id, nombre, _ = self._selected_role_data()
        if role_id is None:
            self.status_label.setText(icons.warn("Selecciona primero un rol de la tabla."))
            return
        with get_session() as session:
            role = AdminService(session).roles.get(role_id)
            if role is None:
                return
            self.role_name_edit.setText(f"{role.nombre} (copia)")
            self._load_permissions(role.permisos_csv or "")
        self._selected_role_id = None
        self.status_label.setText(icons.ok("Rol copiado en el editor; ajusta y pulsa 'Crear rol'."))

    def _delete_role(self) -> None:
        role_id, nombre, _ = self._selected_role_data()
        if role_id is None:
            return
        if nombre == "Administrador":
            QMessageBox.warning(self, "Acción no permitida",
                                "El rol 'Administrador' no se puede eliminar.")
            return
        if not _confirm_action(self, "Confirmar eliminación",
                               f"¿Eliminar el rol '{nombre}'?"):
            return
        try:
            with get_session() as session:
                AdminService(session).delete_role(role_id, usuario_actor=self.current_username)
            self._selected_role_id = None
            self.refresh()
            self.status_label.setText(icons.ok(f"Rol '{nombre}' eliminado."))
        except BioVisionError as exc:
            QMessageBox.warning(self, "No se puede eliminar", str(exc))


# ====================================================================== #
# Tab: Backup, restore and cleanup
# ====================================================================== #
class BackupTab(QWidget):
    def __init__(self, current_username: str, parent=None):
        super().__init__(parent)
        self.current_username = current_username
        self._build_ui()

    def refresh(self) -> None:
        # No derived DB state in this tab; refresh is a no-op
        # (kept for compatibility with Admin module refresh_all).
        pass

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.addLayout(self._card_info())
        layout.addWidget(self._backup_card(), stretch=1)
        layout.addWidget(self._restore_card())
        layout.addWidget(self._cleanup_card())
        layout.addStretch()

    def _card_info(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Backup, restauración y limpieza"))
        row.addStretch()
        self.last_backup_label = QLabel("Sin respaldos registrados en esta sesión.")
        self.last_backup_label.setStyleSheet("color: #8f92a3; font-size: 11px;")
        row.addWidget(self.last_backup_label)
        return row

    def _backup_card(self) -> QGroupBox:
        box = QGroupBox("Backup")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)
        desc = QLabel("Generate a consistent copy of the entire database (persons, "
                      "embeddings, events, videos, users and roles).")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        backup_btn = QPushButton("Generar respaldo (.db)")
        backup_btn.setIcon(icons.icon("backup", 16))
        backup_btn.clicked.connect(self._backup)
        layout.addWidget(backup_btn)
        return box

    def _restore_card(self) -> QGroupBox:
        box = QGroupBox("Restore")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)
        warning = QLabel(
            icons.warn(
                "Restoring COMPLETELY replaces the current database. "
                "The app will close after restoring; you must reopen it."
            )
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #f2b134;")
        layout.addWidget(warning)
        restore_btn = QPushButton("Restaurar desde archivo…")
        restore_btn.setObjectName("SecondaryButton")
        restore_btn.clicked.connect(self._restore)
        layout.addWidget(restore_btn)
        return box

    def _cleanup_card(self) -> QGroupBox:
        box = QGroupBox("Database cleanup")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)
        danger = QLabel(
            icons.err(
                "Delete ALL persons, photos, embeddings, recognition events and "
                "video jobs. Users, roles and secure settings are NOT deleted. "
                "This action cannot be undone."
            )
        )
        danger.setWordWrap(True)
        danger.setStyleSheet("color: #e85d5d;")
        layout.addWidget(danger)

        row = QHBoxLayout()
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setPlaceholderText("Escribe ELIMINAR para confirmar")
        row.addWidget(self.confirm_edit)
        cleanup_btn = QPushButton("Limpiar base de datos")
        cleanup_btn.setObjectName("DangerButton")
        cleanup_btn.clicked.connect(self._cleanup)
        row.addWidget(cleanup_btn)
        layout.addLayout(row)
        return box

    # ------------------------------------------------------------------ #
    def _backup(self) -> None:
        nombre = f"biovision_backup_{datetime.now():%Y%m%d_%H%M%S}.db"
        path, _ = QFileDialog.getSaveFileName(self, "Guardar respaldo", nombre, "SQLite (*.db)")
        if not path:
            return
        try:
            with get_session() as session:
                ExportService(session).backup_database(path)
            import os
            size_kb = os.path.getsize(path) / 1024
            self.last_backup_label.setText(
                f"Último respaldo: {path} ({size_kb:,.0f} KB) · {datetime.now():%H:%M:%S}"
            )
            QMessageBox.information(self, "Backup generado",
                                    f"La copia se guardó en:\n{path}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error generando respaldo")
            QMessageBox.warning(self, "Error", str(exc))

    def _restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar respaldo", "", "SQLite (*.db)")
        if not path:
            return
        confirm = QMessageBox.question(
            self, "Confirmar restauración",
            f"Esto reemplazará TODA la base de datos actual con el contenido de:\n{path}\n\n"
            "La aplicación se cerrará al finalizar. ¿Continuar?",
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            with get_session() as session:
                AdminService(session).restore_database(path, usuario_actor=self.current_username)
            QMessageBox.information(
                self, "Restore completa",
                "La base de datos fue restaurada. La aplicación se cerrará ahora; ábrela de nuevo "
                "para continuar con los datos restaurados.",
            )
            QApplication.instance().quit()
        except BioVisionError as exc:
            QMessageBox.warning(self, "No se pudo restaurar", str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error restaurando base de datos")
            QMessageBox.warning(self, "Error inesperado", str(exc))

    def _cleanup(self) -> None:
        if self.confirm_edit.text().strip().upper() != "ELIMINAR":
            QMessageBox.warning(self, "Confirmación requerida",
                                "Escribe la palabra ELIMINAR para confirmar la limpieza.")
            return
        try:
            with get_session() as session:
                result = AdminService(session).cleanup_database(usuario_actor=self.current_username)
            QMessageBox.information(
                self, "Limpieza completada",
                f"{result['personas_eliminadas']} personas, "
                f"{result['eventos_eliminados']} eventos y "
                f"{result['videos_eliminados']} videos fueron eliminados.",
            )
            self.confirm_edit.clear()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error limpiando la base de datos")
            QMessageBox.warning(self, "Error", str(exc))


# ====================================================================== #
# Tab: Secure settings
# ====================================================================== #
class SecureConfigTab(QWidget):
    def __init__(self, current_username: str, parent=None):
        super().__init__(parent)
        self.current_username = current_username
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setSpacing(12)

        left = QVBoxLayout()
        header = QHBoxLayout()
        header.addWidget(QLabel("Configuraciones sensibles (cifradas en reposo)"))
        header.addStretch()
        refresh_btn = QPushButton("Actualizar")
        refresh_btn.setObjectName("SecondaryButton")
        refresh_btn.setIcon(icons.icon("refresh", 16))
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        left.addLayout(header)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Clave", "Descripción", "Última modificación"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        left.addWidget(self.table, stretch=1)

        btn_row = QHBoxLayout()
        reveal_btn = QPushButton("Ver valor")
        reveal_btn.setObjectName("SecondaryButton")
        reveal_btn.clicked.connect(self._reveal)
        btn_row.addWidget(reveal_btn)
        delete_btn = QPushButton("Eliminar")
        delete_btn.setObjectName("DangerButton")
        delete_btn.clicked.connect(self._delete)
        btn_row.addWidget(delete_btn)
        left.addLayout(btn_row)
        root.addLayout(left, stretch=2)

        form_box = QGroupBox("Guardar valor cifrado")
        form = QFormLayout(form_box)
        form.setSpacing(8)
        self.key_edit = QLineEdit()
        self.desc_edit = QLineEdit()
        self.value_field = PasswordField("Valor secreto")
        form.addRow("Clave", self.key_edit)
        form.addRow("Descripción", self.desc_edit)
        form.addRow("Valor", self.value_field)

        info = QLabel(icons.status_html("security", "El valor se cifra con Fernet antes de guardarse.",
                                        "#8f92a3", 13))
        info.setWordWrap(True)
        form.addRow(info)

        save_btn = QPushButton("Guardar (cifrado)")
        save_btn.clicked.connect(self._save)
        form.addRow(save_btn)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        form.addRow(self.status_label)
        root.addWidget(form_box, stretch=1)

    def refresh(self) -> None:
        with get_session() as session:
            rows = [(s.key, s.descripcion or "—",
                     s.fecha_modificacion.strftime("%Y-%m-%d %H:%M") if s.fecha_modificacion else "—")
                    for s in AdminService(session).list_secure_setting_keys()]
        self.table.setRowCount(len(rows))
        for i, (key, desc, fecha) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(key))
            self.table.setItem(i, 1, QTableWidgetItem(desc))
            self.table.setItem(i, 2, QTableWidgetItem(fecha))

    def _selected_key(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).text()

    def _save(self) -> None:
        key = self.key_edit.text().strip()
        value = self.value_field.text()
        if not key or not value:
            self.status_label.setText(icons.warn("Completa la clave y el valor."))
            return
        with get_session() as session:
            AdminService(session).set_secure_setting(
                key, value, self.desc_edit.text().strip() or None, usuario_actor=self.current_username
            )
        self.status_label.setText(icons.ok(f"'{key}' guardado de forma cifrada."))
        self.key_edit.clear()
        self.desc_edit.clear()
        self.value_field.clear()
        self.refresh()

    def _reveal(self) -> None:
        key = self._selected_key()
        if key is None:
            QMessageBox.information(self, "Selecciona primero", "Selecciona una configuración de la tabla.")
            return
        try:
            with get_session() as session:
                value = AdminService(session).get_secure_setting(key)
        except DecryptionError as exc:
            QMessageBox.warning(self, "No se pudo descifrar", str(exc))
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle(f"Valor de '{key}'")
        box.setText("El valor descifrado es:")
        box.setInformativeText(value or "(vacío)")
        box.setDetailedText("Este valor se muestra solo en memoria y no se registra en los logs.")
        box.addButton("Copiar al portapapeles", QMessageBox.AcceptRole)
        box.addButton("Cerrar", QMessageBox.RejectRole)
        box.exec()

    def _delete(self) -> None:
        key = self._selected_key()
        if key is None:
            return
        if not _confirm_action(self, "Confirmar eliminación",
                               f"¿Eliminar la configuración '{key}'?"):
            return
        with get_session() as session:
            AdminService(session).delete_secure_setting(key, usuario_actor=self.current_username)
        self.refresh()


# ====================================================================== #
# Tab: Extended facial analysis calibration
# ====================================================================== #
ATTR_LABEL_KEYS = {
    "gafas": "attrs.glasses",
    "mascarilla": "attrs.mask",
    "barba": "attrs.beard",
    "bigote": "attrs.mustache",
    "sonrisa": "attrs.smile",
    "ojos_abiertos": "attrs.eyes_open",
}


class CalibrationRefreshWorker(QThread):
    """Re-analyze primary photos in background (heavy CPU models)."""
    progress = Signal(int, int)
    completed = Signal(int)

    def __init__(self, limit: int = 300, parent=None):
        super().__init__(parent)
        self.limit = limit

    def run(self) -> None:
        with get_session() as session:
            service = CalibrationService(session)
            count = service.refresh_all(
                limit=self.limit,
                progress=lambda cur, total: self.progress.emit(cur, total),
            )
        self.completed.emit(count)


class CalibrationTab(QWidget):
    """Facial analysis diagnostics: slide thresholds and see the effect.

    The sample is the raw confidences already stored (primary photo of
    each person). Changing a threshold re-classifies in memory and shows
    instantly how many persons "change"; applying persists the new
    booleans in the embeddings. It can also re-run models on
    photos to regenerate confidences for older records.
    """

    def __init__(self, current_username: str, parent=None):
        super().__init__(parent)
        self.current_username = current_username
        self._entries: list[dict] = []
        self._thresholds = default_thresholds()
        self._sliders: dict[str, QSlider] = {}
        self._name_labels: dict[str, QLabel] = {}
        self._value_labels: dict[str, QLabel] = {}
        self._worker: CalibrationRefreshWorker | None = None
        self._build_ui()
        i18n_bus().languageChanged.connect(self._retranslate)
        self._retranslate()
        self.refresh()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.header_title = QLabel()
        self.header_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(self.header_title)
        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #8f92a3; font-size: 12px;")
        root.addWidget(self.hint_label)

        sliders_grid = QGridLayout()
        sliders_grid.setHorizontalSpacing(16)
        for i, field in enumerate(ATTR_FIELDS):
            name = QLabel(tr(ATTR_LABEL_KEYS[field]))
            name.setStyleSheet("color: #c9cbd6; font-size: 12px;")
            slider = QSlider(Qt.Horizontal)
            slider.setRange(5, 95)
            slider.setValue(int(round(self._thresholds[field] * 100)))
            slider.setSingleStep(5)
            slider.setPageStep(10)
            slider.valueChanged.connect(self._recompute)
            value = QLabel(f"{self._thresholds[field]:.2f}")
            value.setStyleSheet("color: #6fa8ff; font-size: 12px; font-weight: 600;")
            value.setMinimumWidth(34)
            sliders_grid.addWidget(name, i, 0)
            sliders_grid.addWidget(slider, i, 1)
            sliders_grid.addWidget(value, i, 2)
            self._name_labels[field] = name
            self._sliders[field] = slider
            self._value_labels[field] = value
        root.addLayout(sliders_grid)

        self.counts_label = QLabel()
        self.counts_label.setWordWrap(True)
        self.counts_label.setStyleSheet("color: #8f92a3; font-size: 12px;")
        root.addWidget(self.counts_label)

        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton()
        self.refresh_btn.setObjectName("SecondaryButton")
        self.refresh_btn.clicked.connect(self._start_refresh)
        btn_row.addWidget(self.refresh_btn)
        self.apply_btn = QPushButton()
        self.apply_btn.setObjectName("PrimaryButton")
        self.apply_btn.clicked.connect(self._apply_thresholds)
        btn_row.addWidget(self.apply_btn)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #8f92a3; font-size: 12px;")
        btn_row.addWidget(self.status_label)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.table = QTableWidget(0, 11)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        root.addWidget(self.table, stretch=1)

    # ------------------------------------------------------------------ #
    def _retranslate(self, _language: str | None = None) -> None:
        self.header_title.setText(tr("admin.calibration_title"))
        self.hint_label.setText(tr("admin.calibration_hint"))
        self.refresh_btn.setText(tr("admin.calibration_refresh"))
        self.apply_btn.setText(tr("admin.calibration_apply"))
        for field, name in self._name_labels.items():
            name.setText(tr(ATTR_LABEL_KEYS[field]))
        self._set_headers()
        self._recompute()

    def _set_headers(self) -> None:
        headers = ([tr("search.result_name")] +
                   [tr(ATTR_LABEL_KEYS[f]) for f in ATTR_FIELDS] +
                   [tr("attrs.age"), tr("attrs.gender"),
                    tr("attrs.eye_color"), tr("attrs.hair_color")])
        self.table.setHorizontalHeaderLabels(headers)

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        with get_session() as session:
            self._entries = CalibrationService(session).collect()
        self._recompute()

    def _current_thresholds(self) -> dict[str, float]:
        return {f: float(self._sliders[f].value()) / 100.0 for f in ATTR_FIELDS}

    def _recompute(self) -> None:
        thresholds = self._current_thresholds()
        for field in self._sliders:
            self._value_labels[field].setText(f"{thresholds[field]:.2f}")

        if not self._entries:
            self.counts_label.setText(tr("admin.calibration_no_data"))
            self.table.setRowCount(0)
            return

        with get_session() as session:
            counts = CalibrationService(session).aggregate(self._entries, thresholds)

        parts = [f"{tr(ATTR_LABEL_KEYS[f])}: {counts[f]['presente']}/{counts[f]['con_conf']}"
                 for f in ATTR_FIELDS if counts[f]["con_conf"]]
        self.counts_label.setText(tr("admin.calibration_counts").format("  ·  ".join(parts)))

        self.table.setRowCount(len(self._entries))
        for r, entry in enumerate(self._entries):
            attrs = CalibrationService.reclassify(entry["attrs"], thresholds)
            name_item = QTableWidgetItem(entry["nombre"])
            thumb = entry.get("thumb")
            pix = QPixmap(thumb) if thumb and Path(thumb).exists() else QPixmap()
            if pix.isNull():
                name_item.setIcon(icons.icon("person", 18, "#8f92a3"))
            else:
                name_item.setIcon(QIcon(pix.scaled(
                    28, 28, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)))
            self.table.setItem(r, 0, name_item)
            entry_attrs = entry["attrs"]
            for c, field in enumerate(ATTR_FIELDS, start=1):
                present = bool(getattr(attrs, field)) if attrs else False
                item = QTableWidgetItem("✓" if present else "—")
                item.setForeground(QColor("#2ecc71" if present else "#6b6e7d"))
                item.setTextAlignment(Qt.AlignCenter)
                if entry_attrs is not None and field in (entry_attrs.conf or {}):
                    item.setToolTip(f"{entry_attrs.conf[field]:.2f}")
                self.table.setItem(r, c, item)
            edad = attrs.edad if attrs else None
            genero = attrs.genero if attrs else None
            edad_item = QTableWidgetItem(str(edad) if edad else "—")
            edad_item.setTextAlignment(Qt.AlignCenter)
            genero_txt = tr("attrs.gender_male" if genero == "M" else "attrs.gender_female")
            genero_item = QTableWidgetItem(genero_txt if genero in ("M", "F") else "—")
            genero_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 7, edad_item)
            self.table.setItem(r, 8, genero_item)
            for c, key in enumerate(("color_ojos", "color_pelo"), start=9):
                val = getattr(attrs, key) if attrs else None
                item = QTableWidgetItem(val if val else "—")
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, item)

    # ------------------------------------------------------------------ #
    def _start_refresh(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self.status_label.setText(tr("admin.calibration_running"))
        self._worker = CalibrationRefreshWorker(limit=300)
        self._worker.progress.connect(
            lambda cur, total: self.status_label.setText(
                tr("admin.calibration_running") + f"  {cur}/{total}"))
        self._worker.completed.connect(self._on_refresh_done)
        self._worker.start()

    def _on_refresh_done(self, count: int) -> None:
        self.refresh_btn.setEnabled(True)
        self.status_label.setText(tr("admin.calibration_refreshed").format(count))
        self.refresh()

    def _apply_thresholds(self) -> None:
        if not self._entries:
            QMessageBox.information(
                self, tr("admin.calibration_title"), tr("admin.calibration_no_data"))
            return
        thresholds = self._current_thresholds()
        with get_session() as session:
            updated = CalibrationService(session).apply_thresholds(thresholds)
        from app.core.logger import audit_logger  # noqa: PLC0415
        desc = ", ".join(f"{f}={v:.2f}" for f, v in thresholds.items())
        audit_logger.info(
            "Umbrales del análisis facial calibrados | {} | registros={} | usuario={}",
            desc, updated, self.current_username or "sistema")
        QMessageBox.information(
            self, tr("admin.calibration_title"),
            tr("admin.calibration_applied").format(updated))
        self.refresh()


# ====================================================================== #
# Tab: Recognition settings (quality gate and threshold)
# ====================================================================== #
class _AnnDiagnoseWorker(QThread):
    """Build the ANN index and run the recall benchmark in background."""

    finished_ok = Signal(str)
    failed = Signal(str)

    def run(self) -> None:
        try:
            from app.recognition.ann_benchmark import (  # noqa: PLC0415
                format_diagnosis_report, run_ann_diagnosis,
            )
            with get_session() as session:
                report = format_diagnosis_report(run_ann_diagnosis(session))
            self.finished_ok.emit(report)
        except Exception as exc:  # noqa: BLE001 - reported to the user only
            self.failed.emit(str(exc))


class RecognitionConfigTab(QWidget):
    """
    Allow hot, persistent tuning (settings.yaml) of
    quality gate and match threshold parameters.

    Changes immediately affect enrollment, 1:1 comparison,
    1:N search, webcam and video (all read `settings` at runtime).
    """

    _FIELDS = [
        ("recognition", "match_threshold", "recognition.match_threshold",
         (0.05, 0.95, 0.05)),
        ("recognition", "apply_quality_gate", "recognition.apply_quality_gate", None),
        ("vision", "quality_min_score", "recognition.quality_min_score",
         (0.0, 100.0, 1.0)),
        ("recognition", "top_k_results", "recognition.top_k_results",
         (1, 100, 1)),
        ("vision", "min_face_size", "recognition.min_face_size", (16, 512, 1)),
        ("vision", "max_yaw_deg", "recognition.max_yaw_deg", (0.0, 90.0, 1.0)),
        ("vision", "max_pitch_deg", "recognition.max_pitch_deg",
         (0.0, 90.0, 1.0)),
        ("vision", "enable_face_attributes",
         "recognition.enable_face_attributes", None),
        ("recognition", "live_attr_check", "recognition.live_attr_check", None),
        ("recognition", "ann_enabled", "recognition.ann_enabled", None),
        ("recognition", "ann_min_size", "recognition.ann_min_size",
         (100, 1_000_000, 100)),
        ("recognition", "ann_ivf_min_size", "recognition.ann_ivf_min_size",
         (100, 1_000_000, 100)),
        ("recognition", "ann_nlist", "recognition.ann_nlist", (0, 65_536, 16)),
        ("recognition", "ann_nprobe", "recognition.ann_nprobe", (0, 2_048, 1)),
        ("recognition", "ann_persist", "recognition.ann_persist", None),
    ]

    def __init__(self, current_username: str, parent=None):
        super().__init__(parent)
        self.current_username = current_username
        self._widgets: list[tuple[str, str, QWidget]] = []
        self._build_ui()
        i18n_bus().languageChanged.connect(self._retranslate)
        self._retranslate()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        header = QHBoxLayout()
        self.header_title = QLabel()
        header.addWidget(self.header_title)
        header.addStretch()
        self.header_hint = QLabel()
        header.addWidget(self.header_hint)
        root.addLayout(header)

        self.form_box = QGroupBox()
        form = QFormLayout(self.form_box)
        form.setSpacing(8)

        for section, key, tr_key, bounds in self._FIELDS:
            current = getattr(getattr(settings, section), key)
            if isinstance(current, bool):
                widget = QCheckBox(tr(tr_key))
                widget.setToolTip(f"{section}.{key}")
                form.addRow("", widget)
            elif isinstance(current, float):
                lo, hi, step = bounds
                widget = QDoubleSpinBox()
                widget.setRange(lo, hi)
                widget.setSingleStep(step)
                widget.setDecimals(2 if step < 1 else 1)
                form.addRow(tr(tr_key), widget)
            else:
                lo, hi, step = bounds
                widget = QSpinBox()
                widget.setRange(int(lo), int(hi))
                widget.setSingleStep(int(step))
                form.addRow(tr(tr_key), widget)
            self._widgets.append((section, key, widget))

        root.addWidget(self.form_box)

        self.ann_box = QGroupBox()
        ann_layout = QVBoxLayout(self.ann_box)
        ann_layout.setSpacing(8)
        self.ann_status = QLabel()
        self.ann_status.setWordWrap(True)
        self.ann_status.setTextFormat(Qt.TextFormat.RichText)
        ann_layout.addWidget(self.ann_status)
        ann_diag_row = QHBoxLayout()
        self.diagnose_btn = QPushButton()
        self.diagnose_btn.setObjectName("SecondaryButton")
        self.diagnose_btn.clicked.connect(self._on_diagnose)
        ann_diag_row.addWidget(self.diagnose_btn)
        ann_diag_row.addStretch()
        ann_layout.addLayout(ann_diag_row)
        root.addWidget(self.ann_box)

        btn_row = QHBoxLayout()
        self.save_btn = QPushButton()
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self._save)
        btn_row.addWidget(self.save_btn)
        self.reset_btn = QPushButton()
        self.reset_btn.setObjectName("SecondaryButton")
        self.reset_btn.clicked.connect(self.refresh)
        btn_row.addWidget(self.reset_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)
        root.addStretch()

    def _retranslate(self, _language: str | None = None) -> None:
        self.header_title.setText(tr("recognition.settings_title"))
        self.header_hint.setText(tr("recognition.settings_hint"))
        self.form_box.setTitle(tr("recognition.title"))
        self.ann_box.setTitle(tr("recognition.ann_status_title"))
        self.diagnose_btn.setText(tr("recognition.ann_diagnose_button"))
        self.save_btn.setText(tr("recognition.save_button"))
        self.reset_btn.setText(tr("recognition.reload_button"))
        self._update_ann_status()
        form = self.form_box.layout()
        for (section, key, tr_key, bounds), (_, _, widget) in zip(self._FIELDS, self._widgets):
            if isinstance(widget, QCheckBox):
                widget.setText(tr(tr_key))
            else:
                for r in range(form.rowCount()):
                    if form.itemAt(r, QFormLayout.FieldRole) is widget:
                        label_item = form.itemAt(r, QFormLayout.LabelRole)
                        if label_item is not None and label_item.widget() is not None:
                            label_item.widget().setText(tr(tr_key))
                        break

    def refresh(self) -> None:
        for section, key, widget in self._widgets:
            value = getattr(getattr(settings, section), key)
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value))
            else:
                widget.setValue(int(value))

    def _values(self) -> list[tuple[str, str, object]]:
        values: list[tuple[str, str, object]] = []
        for section, key, widget in self._widgets:
            if isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QDoubleSpinBox):
                value = round(widget.value(), 2)
            else:
                value = int(widget.value())
            values.append((section, key, value))
        return values

    def _save(self) -> None:
        try:
            changes = [(s, k, v) for s, k, v in self._values()
                       if v != getattr(getattr(settings, s), k)]
            for section, key, value in changes:
                save_setting(section, key, value)
        except (ValueError, OSError) as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("common.error"),
                                f"No se pudo guardar la configuración:\n{exc}")
            return

        if not changes:
            QMessageBox.information(self, tr("recognition.no_changes"),
                                    tr("recognition.no_changes_desc"))
            return

        from app.core.logger import audit_logger  # noqa: PLC0415
        desc = ", ".join(f"{s}.{k}={v}" for s, k, v in changes)
        audit_logger.info("Configuración de reconocimiento actualizada | {} | usuario={}",
                          desc, self.current_username or "sistema")
        QMessageBox.information(self, tr("recognition.saved"),
                                tr("recognition.saved_desc"))
        self._update_ann_status()

    def _update_ann_status(self) -> None:
        """Passive summary of ANN config (live state seen on diagnose)."""
        rec = settings.recognition
        faiss_ok = False
        try:
            from app.recognition.ann_index import _faiss_available  # noqa: PLC0415
            faiss_ok = _faiss_available()
        except Exception:  # noqa: BLE001
            faiss_ok = False
        faiss_line = (tr("recognition.ann_faiss_installed")
                      if faiss_ok else tr("recognition.ann_faiss_missing"))
        if rec.ann_enabled:
            summary = tr("recognition.ann_state_summary").format(
                min_size=rec.ann_min_size,
                ivf=rec.ann_ivf_min_size,
                nlist=rec.ann_nlist or tr("recognition.ann_auto"),
                nprobe=rec.ann_nprobe or tr("recognition.ann_auto"))
        else:
            summary = tr("recognition.ann_state_disabled")
        self.ann_status.setText(
            f"<b>{tr('recognition.ann_status_title')}</b><br/>{faiss_line}<br/>{summary}")

    def _on_diagnose(self) -> None:
        if not self.diagnose_btn.isEnabled():
            return
        self.diagnose_btn.setEnabled(False)
        self._ann_worker = _AnnDiagnoseWorker()
        self._ann_worker.finished_ok.connect(self._on_diagnose_done)
        self._ann_worker.failed.connect(self._on_diagnose_failed)
        self._ann_worker.start()

    def _on_diagnose_done(self, report: str) -> None:
        self.diagnose_btn.setEnabled(True)
        self.ann_status.setText(report)

    def _on_diagnose_failed(self, message: str) -> None:
        self.diagnose_btn.setEnabled(True)
        self.ann_status.setStyleSheet("color: #ff6b6b;")
        self.ann_status.setText(f"<b>{tr('recognition.ann_status_title')}</b><br/>{message}")
class PreferencesTab(QWidget):
    """
    Interface preferences for the logged-in user. Currently language
    (Spanish/English), applied live across the app.
    """

    def __init__(self, current_username: str, current_user_id: int, parent=None):
        super().__init__(parent)
        self.current_username = current_username
        self.current_user_id = current_user_id
        self._build_ui()
        i18n_bus().languageChanged.connect(self._retranslate)
        self._retranslate()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        header = QHBoxLayout()
        self.title_label = QLabel()
        header.addWidget(self.title_label)
        header.addStretch()
        root.addLayout(header)

        form_box = QGroupBox("Idioma")
        form = QFormLayout(form_box)
        form.setSpacing(8)

        self.language_combo = QComboBox()
        self.language_combo.addItem("Español", "es")
        self.language_combo.addItem("English", "en")
        self.language_label = QLabel()
        form.addRow(self.language_label, self.language_combo)

        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #8f92a3;")
        form.addRow("", self.hint_label)
        root.addWidget(form_box)

        btn_row = QHBoxLayout()
        self._save_btn = QPushButton()
        self._save_btn.setObjectName("PrimaryButton")
        self._save_btn.clicked.connect(self._save)
        btn_row.addWidget(self._save_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)
        root.addStretch()

    def _retranslate(self, _language: str | None = None) -> None:
        self.title_label.setText(tr("prefs.title"))
        self.language_label.setText(tr("prefs.language"))
        self.hint_label.setText(tr("prefs.language_desc"))
        if hasattr(self, "_save_btn"):
            self._save_btn.setText(tr("prefs.save"))

    def refresh(self) -> None:
        with get_session() as session:
            language = PreferencesService(session).get_language(self.current_user_id)
        index = self.language_combo.findData(language)
        if index >= 0:
            self.language_combo.setCurrentIndex(index)

    def _save(self) -> None:
        language = self.language_combo.currentData()
        with get_session() as session:
            PreferencesService(session).set_language(self.current_user_id, language)
        set_i18n_language(language)
        from app.core.logger import audit_logger  # noqa: PLC0415
        audit_logger.info("Preferencia de idioma actualizada | language={} | usuario={}",
                          language, self.current_username or "sistema")
        QMessageBox.information(self, tr("prefs.saved"), tr("prefs.saved_desc"))
class AuditTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Audit log (logs/audit.log)"))

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filtrar por usuario o acción…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self.refresh)
        toolbar.addWidget(self.filter_edit, stretch=1)

        self.range_check = QCheckBox("Rango de fechas")
        self.range_check.toggled.connect(self._toggle_range)
        toolbar.addWidget(self.range_check)

        self.from_date = QDateEdit(QDate.currentDate().addDays(-7))
        self.to_date = QDateEdit(QDate.currentDate())
        for d in (self.from_date, self.to_date):
            d.setCalendarPopup(True)
            d.setDisplayFormat("yyyy-MM-dd")
            d.setEnabled(False)
        self.from_date.dateChanged.connect(self.refresh)
        self.to_date.dateChanged.connect(self.refresh)
        toolbar.addWidget(QLabel("Desde"))
        toolbar.addWidget(self.from_date)
        toolbar.addWidget(QLabel("Hasta"))
        toolbar.addWidget(self.to_date)

        self.limit_combo = QComboBox()
        self.limit_combo.addItems(["300", "1000", "5000", "Todas"])
        self.limit_combo.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(QLabel("Mostrar:"))
        toolbar.addWidget(self.limit_combo)

        refresh_btn = QPushButton("Actualizar")
        refresh_btn.setObjectName("SecondaryButton")
        refresh_btn.setIcon(icons.icon("refresh", 16))
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setStyleSheet("font-family: 'Consolas', monospace; font-size: 11px;")
        layout.addWidget(self.text_area, stretch=1)

    def _toggle_range(self, checked: bool) -> None:
        self.from_date.setEnabled(checked)
        self.to_date.setEnabled(checked)
        self.refresh()

    def refresh(self) -> None:
        log_path = settings.resolve_path(settings.storage.logs_dir) / "audit.log"
        lines: list[str] = []
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()

        # Audit events persisted in DB (login, 2FA, etc.).
        try:
            with get_session() as session:
                db_events = session.query(AuditLog).order_by(AuditLog.id.desc()).all()
                # Access attributes inside the session to avoid DetachedInstanceError
                for ev in db_events:
                    fecha = ev.fecha.strftime("%Y-%m-%d %H:%M:%S") if ev.fecha else ""
                    detalle = f" | {ev.detalle}" if ev.detalle else ""
                    lines.append(f"{fecha} | AUDIT | {ev.accion} | {ev.usuario or 'systema'}{detalle}")
        except Exception:  # noqa: BLE001 - audit tab must never break the widget
            logger.exception("Error leyendo auditoría de la base de datos")

        texto = self.filter_edit.text().strip().lower()
        if texto:
            lines = [ln for ln in lines if texto in ln.lower()]

        if self.range_check.isChecked():
            desde = self.from_date.date().toString("yyyy-MM-dd")
            hasta = self.to_date.date().toString("yyyy-MM-dd")
            lines = [ln for ln in lines if desde <= ln[:10] <= hasta]

        limite = self.limit_combo.currentText()
        if limite.isdigit():
            lines = lines[-int(limite):]

        self.text_area.setPlainText("\n".join(lines) if lines else "Sin coincidencias para ese filtro.")
        self.text_area.verticalScrollBar().setValue(self.text_area.verticalScrollBar().maximum())


# ====================================================================== #
# Main Administration widget
# ====================================================================== #
class AdministrationWidget(QWidget):
    _TAB_TITLES = [
        "admin.tab_users", "admin.tab_roles", "admin.tab_backup",
        "admin.tab_secure", "admin.tab_recognition", "admin.tab_calibration",
        "admin.tab_preferences", "admin.tab_audit",
    ]

    def __init__(self, current_username: str, current_user_id: int | None = None, parent=None):
        super().__init__(parent)
        self.current_username = current_username
        self.current_user_id = current_user_id or 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        self.title_label = QLabel("Administración")
        self.title_label.setStyleSheet("font-size: 22px; font-weight: 700;")
        title_block.addWidget(self.title_label)
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: #8f92a3;")
        title_block.addWidget(self.summary_label)
        header.addLayout(title_block)
        header.addStretch()

        refresh_all_btn = QPushButton(tr("admin.refresh_all"))
        refresh_all_btn.setObjectName("SecondaryButton")
        refresh_all_btn.setIcon(icons.icon("refresh", 16))
        refresh_all_btn.clicked.connect(self.refresh_all)
        header.addWidget(refresh_all_btn)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs_users = UsersTab(current_username, self.current_user_id)
        self.tabs_roles = RolesTab(current_username)
        self.tabs_backup = BackupTab(current_username)
        self.tabs_secure = SecureConfigTab(current_username)
        self.tabs_reco = RecognitionConfigTab(current_username)
        self.tabs_cal = CalibrationTab(current_username)
        self.tabs_prefs = PreferencesTab(current_username, self.current_user_id)
        self.tabs_audit = AuditTab()
        self.tabs.addTab(self.tabs_users, "")
        self.tabs.addTab(self.tabs_roles, "")
        self.tabs.addTab(self.tabs_backup, "")
        self.tabs.addTab(self.tabs_secure, "")
        self.tabs.addTab(self.tabs_reco, "")
        self.tabs.addTab(self.tabs_cal, "")
        self.tabs.addTab(self.tabs_prefs, "")
        self.tabs.addTab(self.tabs_audit, "")
        self.tabs.currentChanged.connect(lambda _idx: self.refresh_all())
        layout.addWidget(self.tabs, stretch=1)

        i18n_bus().languageChanged.connect(self._retranslate)
        self._retranslate()
        self.refresh_all()

    def _retranslate(self, _language: str | None = None) -> None:
        self.title_label.setText(tr("admin.title"))
        for i, key in enumerate(self._TAB_TITLES):
            self.tabs.setTabText(i, tr(key))
        self.tabs_prefs._retranslate()

    def refresh_all(self) -> None:
        with get_session() as session:
            n_users = session.query(User).count()
            n_roles = AdminService(session).list_roles().__len__()
        self.summary_label.setText(
            tr("admin.summary", users=n_users, roles=n_roles)
        )
        self.tabs_users.refresh()
        self.tabs_roles.refresh()
        self.tabs_backup.refresh()
        self.tabs_secure.refresh()
        self.tabs_reco.refresh()
        self.tabs_cal.refresh()
        self.tabs_prefs.refresh()
        self.tabs_audit.refresh()