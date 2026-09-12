"""
Pantallas de acceso (bounded context: AUTH):
  - FirstRunSetupDialog : crear el administrador principal (primer arranque).
  - RegistrationDialog  : crear una cuenta nueva desde el login (auto-registro).
  - LoginDialog         : inicio de sesión / desbloqueo por inactividad.

Diseño vertical tipo "login web": campos apilados con placeholders (sin
etiquetas duplicadas), botón primario a lo ancho y opciones mínimas.

Si el usuario marcó "Recordar sesión", se guarda un token de sesión efímero
(solo se persiste localmente su valor crudo; su hash vive en la tabla
``remembered_sessions``) y en el próximo arranque la aplicación entra
directamente, sin pasar por esta vista.
"""
from __future__ import annotations

import base64
import time

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from app.core.config import LOGO_PATH, settings
from app.core.exceptions import AuthenticationError, BioVisionError
from app.core.logger import logger
from app.core.security import DecryptionError, decrypt_value, encrypt_value
from app.database.session import get_session
from app.gui import icons
from app.i18n import tr
from app.services.admin_service import AdminService
from app.services.auth_service import AuthService

# ---------------------------------------------------------------------- #
# Persistencia local ("Recordarme"): token de sesión, nunca la contraseña.
# ---------------------------------------------------------------------- #
_APP_ORG = "FaceScan"
_APP_NAME = "FaceScan"

ACCENT_COLOR = "#3b82f6"  # azul limpio, sin componente verde


def _logo_label(max_width: int = 240) -> QLabel:
    """Etiqueta con el logo de la aplicación (facescan.png), centrada."""
    label = QLabel()
    pixmap = QPixmap(str(LOGO_PATH))
    if not pixmap.isNull():
        label.setPixmap(
            pixmap.scaled(max_width, max_width, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        label.setAlignment(Qt.AlignCenter)
    return label


class RememberedCredentials:
    """Guarda/recupera el token de 'recordar sesión' usando QSettings.

    Solo se almacena un token aleatorio (su hash SHA-256 vive en la BD, tabla
    ``remembered_sessions``); la contraseña jamás se guarda en el equipo. El
    auto-login expira a los ``security.remember_credentials_days`` días. El
    token se persiste **cifrado** con la clave Fernet local (M14): alguien con
    acceso al registro/archivo no puede reutilizarlo. El formato antiguo
    (texto plano o contraseña cifrada) no es un token válido y se descarta
    automáticamente.
    """

    def __init__(self) -> None:
        self._settings = QSettings(_APP_ORG, _APP_NAME)

    def _expired(self) -> bool:
        days = settings.security.remember_credentials_days
        if days <= 0:
            return False
        saved = self._settings.value("auth/remember_saved_at", 0, float)
        return bool(saved) and (time.time() - saved) > days * 86400

    def load(self) -> tuple[str, str, bool, bool]:
        """Devuelve (usuario, token, hay_token, auto_login)."""
        username = self._settings.value("auth/remember_username", "", str)
        stored = self._settings.value("auth/remember_token", "", str)
        autologin = self._settings.value("auth/remember_autologin", "false", str) == "true"
        token = ""
        if username and stored and not self._expired():
            try:
                token = decrypt_value(base64.b64decode(stored))
            except (DecryptionError, ValueError, TypeError):
                token = ""  # formato antiguo o clave rotada => pedir login
        if not username or not token:
            self.clear()
            return "", "", False, False
        return username, token, True, autologin

    def save(self, username: str, token: str) -> None:
        stored = base64.b64encode(encrypt_value(token)).decode("ascii")
        self._settings.setValue("auth/remember_username", username)
        self._settings.setValue("auth/remember_token", stored)
        self._settings.setValue("auth/remember_autologin", "true")
        self._settings.setValue("auth/remember_saved_at", time.time())
        self._settings.sync()

    def clear(self) -> None:
        self._settings.remove("auth/remember_username")
        self._settings.remove("auth/remember_token")
        self._settings.remove("auth/remember_autologin")
        self._settings.remove("auth/remember_saved_at")
        self._settings.sync()


def _capslock_on(event) -> bool:
    """Detecta Bloq Mayús activo a partir del carácter producido por la tecla.

    Qt no expone el estado de Caps Lock en KeyboardModifier, así que se deduce
    del caso del carácter: si se teclea una letra mayúscula SIN Shift, o una
    minúscula CON Shift, Caps Lock está activo.
    """
    text = event.text()
    if not text or not text.isalpha():
        return False
    shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
    if text.isupper():
        return not shift
    return shift


# ---------------------------------------------------------------------- #
# Widget reutilizable: campo de contraseña con toggle y aviso de Bloq Mayús.
# ---------------------------------------------------------------------- #
class PasswordField(QWidget):
    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.line_edit = QLineEdit()
        self.line_edit.setEchoMode(QLineEdit.Password)
        self.line_edit.setPlaceholderText(placeholder)

        leading = QAction(icons.icon("lock", 16, icons.COLOR_MUTED), "", self.line_edit)
        self.line_edit.addAction(leading, QLineEdit.ActionPosition.LeadingPosition)

        self._toggle_action = QAction(icons.icon("visibility", 16, icons.COLOR_MUTED), "",
                                      self.line_edit)
        self._toggle_action.setCheckable(True)
        self._toggle_action.triggered.connect(self._on_toggle)
        self.line_edit.addAction(self._toggle_action, QLineEdit.ActionPosition.TrailingPosition)

        self.caps_label = QLabel(icons.warn(tr("login.caps_on")))
        self.caps_label.setStyleSheet("font-size: 11px; color: #f2b134;")
        self.caps_label.setVisible(False)

        layout.addWidget(self.line_edit)
        layout.addWidget(self.caps_label)

        self.line_edit.installEventFilter(self)

    def _on_toggle(self, checked: bool) -> None:
        self.line_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        icon_name = "visibility_off" if checked else "visibility"
        self._toggle_action.setIcon(icons.icon(icon_name, 16, icons.COLOR_MUTED))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.line_edit:
            if event.type() == QEvent.KeyPress:
                self.caps_label.setVisible(_capslock_on(event))
            elif event.type() == QEvent.FocusOut:
                self.caps_label.setVisible(False)
        return super().eventFilter(obj, event)

    def text(self) -> str:
        return self.line_edit.text()

    def set_text(self, value: str) -> None:
        self.line_edit.setText(value)

    def clear(self) -> None:
        self.line_edit.clear()

    def set_focus(self) -> None:
        self.line_edit.setFocus()


def _make_username_input(placeholder: str | None = None) -> QLineEdit:
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder or tr("login.username"))
    action = QAction(icons.icon("person", 16, icons.COLOR_MUTED), "", edit)
    edit.addAction(action, QLineEdit.ActionPosition.LeadingPosition)
    return edit


def _policy_hint_label() -> QLabel:
    hint = QLabel(AuthService.password_policy_hint() + ".")
    hint.setWordWrap(True)
    hint.setStyleSheet("color: #8f92a3; font-size: 11px;")
    hint.setAlignment(Qt.AlignCenter)
    return hint


def _auth_title(title: str, subtitle: str, icon: str = "shield") -> QVBoxLayout:
    """Cabecera centrada (logo + título + subtítulo), estilo login web."""
    layout = QVBoxLayout()
    layout.setSpacing(6)

    logo = QLabel()
    logo.setAlignment(Qt.AlignCenter)
    logo.setFixedHeight(46)
    logo.setPixmap(icons.pixmap(icon, 40, ACCENT_COLOR))
    layout.addWidget(logo)

    t = QLabel(title)
    t.setAlignment(Qt.AlignCenter)
    t.setStyleSheet("font-size: 20px; font-weight: 700;")
    layout.addWidget(t)

    s = QLabel(subtitle)
    s.setAlignment(Qt.AlignCenter)
    s.setWordWrap(True)
    s.setStyleSheet("color: #8f92a3;")
    layout.addWidget(s)
    return layout


# ====================================================================== #
# Configuración inicial (primer arranque)
# ====================================================================== #
class FirstRunSetupDialog(QDialog):
    """Se muestra una única vez: cuando no existe ningún usuario en la BD."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("login.title_choose_account"))
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setMaximumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 34, 30, 30)
        root.setSpacing(14)
        root.addWidget(_logo_label())
        root.addLayout(_auth_title(
            tr("sidebar.app_name"),
            tr("login.first_admin_subtitle"),
            icon="admin_panel",
        ))

        self.username_edit = _make_username_input(tr("login.username"))
        self.nombre_edit = QLineEdit()
        self.nombre_edit.setPlaceholderText(tr("login.register_name_hint"))
        self.password_field = PasswordField(tr("login.password"))
        self.confirm_field = PasswordField(tr("login.confirm_password"))

        root.addWidget(self.username_edit)
        root.addWidget(self.nombre_edit)
        root.addWidget(self.password_field)
        root.addWidget(self.confirm_field)
        root.addWidget(_policy_hint_label())

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #e85d5d;")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.error_label)

        create_btn = QPushButton(tr("login.create_first_admin"))
        create_btn.setMinimumHeight(40)
        create_btn.clicked.connect(self._on_create)
        root.addWidget(create_btn)

    def _on_create(self) -> None:
        username = self.username_edit.text().strip()
        password = self.password_field.text()
        confirm = self.confirm_field.text()
        nombre = self.nombre_edit.text().strip() or None

        if not username or not password:
            self.error_label.setText(icons.err(tr("login.required_fields")))
            self.password_field.set_focus()
            return
        if password != confirm:
            self.error_label.setText(icons.err(tr("login.passwords_not_match")))
            self.confirm_field.clear()
            self.confirm_field.set_focus()
            return

        try:
            with get_session() as session:
                AdminService(session).create_initial_admin(username, password, nombre)
            self.accept()
        except (BioVisionError, ValueError) as exc:
            self.error_label.setText(icons.err(str(exc)))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error creando administrador inicial")
            self.error_label.setText(icons.err(f"Error inesperado: {exc}"))


# ====================================================================== #
# Registro de una cuenta nueva (auto-registro)
# ====================================================================== #
class RegistrationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("login.title_register"))
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setMaximumWidth(460)
        self.registered_user_id: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 34, 30, 30)
        root.setSpacing(14)
        root.addWidget(_logo_label())
        root.addLayout(_auth_title(
            tr("login.create_account"),
            "Se creará con un rol estándar; un administrador podrá ajustar tus "
            "permisos después.",
            icon="person_add",
        ))

        self.username_edit = _make_username_input(tr("login.username_min3"))
        self.nombre_edit = QLineEdit()
        self.nombre_edit.setPlaceholderText(tr("login.register_name_hint"))
        self.password_field = PasswordField(tr("login.password"))
        self.confirm_field = PasswordField(tr("login.confirm_password"))

        root.addWidget(self.username_edit)
        root.addWidget(self.nombre_edit)
        root.addWidget(self.password_field)
        root.addWidget(self.confirm_field)
        root.addWidget(_policy_hint_label())

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #e85d5d;")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.error_label)

        create_btn = QPushButton(tr("login.create_and_enter"))
        create_btn.setMinimumHeight(40)
        create_btn.clicked.connect(self._on_register)
        root.addWidget(create_btn)

        cancel_btn = QPushButton(tr("common.cancel"))
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.clicked.connect(self.reject)
        root.addWidget(cancel_btn)

    def _on_register(self) -> None:
        username = self.username_edit.text().strip()
        password = self.password_field.text()
        confirm = self.confirm_field.text()
        nombre = self.nombre_edit.text().strip() or None

        if len(username) < 3:
            self.error_label.setText(icons.err(tr("login.username_min_len")))
            return
        if any(ch.isspace() for ch in username):
            self.error_label.setText(icons.err(tr("login.username_no_spaces")))
            return
        if not password:
            self.error_label.setText(icons.err(tr("login.password_required")))
            self.password_field.set_focus()
            return
        if password != confirm:
            self.error_label.setText(icons.err(tr("login.passwords_not_match")))
            self.confirm_field.clear()
            self.confirm_field.set_focus()
            return

        try:
            with get_session() as session:
                user = AuthService(session).register_user(username, password, nombre)
                self.registered_user_id = user.id
            self.accept()
        except (BioVisionError, ValueError) as exc:
            self.error_label.setText(icons.err(str(exc)))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error registrando una cuenta nueva")
            self.error_label.setText(icons.err(f"Error inesperado: {exc}"))


# ====================================================================== #
# Inicio de sesión / bloqueo por inactividad
# ====================================================================== #
class LoginDialog(QDialog):
    """Pantalla de acceso vertical, minimalista y moderna.

    lock_mode=True se usa como "sesión bloqueada por inactividad": el usuario
    no puede cambiarse y se exige la contraseña de nuevo. En modo normal se
    puede recordar la sesión (auto-login en el próximo arranque) y crear una
    cuenta nueva desde aquí.
    """

    def __init__(self, parent=None, lock_mode: bool = False, prefill_username: str | None = None):
        super().__init__(parent)
        self.lock_mode = lock_mode
        self.authenticated_user_id: int | None = None
        self._remembered = RememberedCredentials()

        self.setWindowTitle(tr("login.title_locked") if lock_mode else tr("login.login_title"))
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setMaximumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 34, 30, 30)
        root.setSpacing(14)
        root.addWidget(_logo_label())
        root.addLayout(_auth_title(
            tr("login.title_locked") if lock_mode else tr("sidebar.app_name"),
            tr("login.locked_subtitle") if lock_mode else tr("login.login_subtitle"),
            icon="lock" if lock_mode else "shield",
        ))

        self.username_edit = _make_username_input()
        if prefill_username:
            self.username_edit.setText(prefill_username)
        self.username_edit.setEnabled(not lock_mode)
        root.addWidget(self.username_edit)

        self.password_field = PasswordField(tr("login.password"))
        self.password_field.line_edit.returnPressed.connect(self._on_login)
        root.addWidget(self.password_field)

        self.totp_field = QLineEdit()
        self.totp_field.setPlaceholderText(tr("login.totp_code"))
        self.totp_field.setMaxLength(6)
        self.totp_field.setVisible(False)
        self.totp_field.returnPressed.connect(self._on_login)
        root.addWidget(self.totp_field)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #e85d5d;")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.error_label)

        login_btn = QPushButton(tr("login.unlock") if lock_mode else tr("login.enter"))
        login_btn.setMinimumHeight(40)
        login_btn.clicked.connect(self._on_login)
        root.addWidget(login_btn)

        if lock_mode:
            logout_btn = QPushButton(tr("login.logout_instead"))
            logout_btn.setObjectName("SecondaryButton")
            logout_btn.clicked.connect(self.reject)
            root.addWidget(logout_btn)
        else:
            row = QHBoxLayout()
            self.remember_check = QCheckBox(tr("login.remember"))
            self.remember_check.setToolTip(
                "En el próximo inicio entrarás directamente mediante un token "
                "de sesión. Tu contraseña nunca se guarda en este equipo."
            )
            row.addWidget(self.remember_check)
            row.addStretch()
            create_btn = QPushButton(tr("login.create_account"))
            create_btn.setObjectName("LinkButton")
            create_btn.setCursor(Qt.PointingHandCursor)
            create_btn.clicked.connect(self._open_registration)
            if not self._registration_enabled():
                create_btn.setEnabled(False)
                create_btn.setToolTip("El administrador deshabilitó la creación de cuentas.")
            row.addWidget(create_btn)
            root.addLayout(row)
            root.addSpacing(2)

        # Autocompletar con la sesión recordada (solo modo normal).
        # Solo se recupera el nombre de usuario; la contraseña jamás se
        # rellena: el auto-login usa el token en app/main.py y aquí se exige
        # la contraseña en pantalla.
        if not lock_mode:
            username, _token, has_token, _autologin = self._remembered.load()
            if username:
                self.username_edit.setText(username)
                if has_token:
                    self.remember_check.setChecked(True)

        if lock_mode:
            self.password_field.set_focus()
        elif not self.username_edit.text():
            self.username_edit.setFocus()
        else:
            self.password_field.set_focus()

    # ------------------------------------------------------------------ #
    def _registration_enabled(self) -> bool:
        from app.core.config import settings
        return settings.security.allow_self_registration

    def _open_registration(self) -> None:
        dlg = RegistrationDialog(self)
        if dlg.exec() == QDialog.Accepted and dlg.registered_user_id is not None:
            self.authenticated_user_id = dlg.registered_user_id
            self.accept()

    def _on_login(self) -> None:
        username = self.username_edit.text().strip()
        password = self.password_field.text()
        totp_code = self.totp_field.text().strip() if self.totp_field.isVisible() else None
        if not username or not password:
            self.error_label.setText(icons.err(tr("login.enter_credentials")))
            return

        remember_token: str | None = None
        try:
            with get_session() as session:
                auth = AuthService(session)
                user = auth.authenticate(username, password, totp_code=totp_code)
                self.authenticated_user_id = user.id
                if not self.lock_mode and self.remember_check.isChecked():
                    # Se genera el token dentro de la misma sesión de BD.
                    remember_token = auth.create_remembered_token(user)

            if not self.lock_mode:
                if remember_token is not None:
                    self._remembered.save(username, remember_token)
                else:
                    self._remembered.clear()
            self.accept()
        except AuthenticationError as exc:
            message = str(exc)
            # Con 2FA habilitado se exige el código: se muestra el campo y se
            # pide confirmar de nuevo con él, sin descartar las credenciales.
            if "código de verificación" in message:
                self.totp_field.setVisible(True)
                self.totp_field.setFocus()
                self.error_label.setText(icons.err(message))
                return
            self.error_label.setText(icons.err(message))
            self.password_field.clear()
            self.password_field.set_focus()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error inesperado durante el login")
            self.error_label.setText(icons.err(f"Error inesperado: {exc}"))