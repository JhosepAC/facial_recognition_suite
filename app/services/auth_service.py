"""Authentication service (bounded context: AUTH). Covers:
  - authentication (login)
  - password hashing (bcrypt)
  - automatic lockout after failed attempts
  - password policy
  - self-registration ("create account" from the login screen)
  - password change (with current password verification)
  - per-user permissions (via Role.permisos_csv), which determine which
    dashboard modules are visible/blocked.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timedelta

import bcrypt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    AuthenticationError, AuthorizationError, BioVisionError, TwoFactorRequiredError,
)
from app.core.logger import audit_logger
from app.core.permissions import permissions_from_csv
from app.core.security import decrypt_value, encrypt_value
from app.core.totp import generate_secret, otpauth_uri, verify_code
from app.database.models import AuditLog, RememberedSession, Role, User
from app.database.repositories.user_repository import RoleRepository, UserRepository


# Single message for all credential failures: does not reveal whether
# the user exists, is locked, or disabled (prevents account enumeration).
_INVALID_CREDENTIALS_MSG = "Invalid username or password."


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# Precomputed dummy hash: consume time comparable to a real
# verification on all login rejection paths (avoids timing oracle:
# non-existent, locked, or disabled accounts respond identically).
_DUMMY_HASH = hash_password("invalid-trap-password")


def validate_password_policy(password: str) -> None:
    """Validate password policy: minimum length + letters + numbers."""
    min_len = settings.security.min_password_length
    if len(password) < min_len:
        raise ValueError(f"Password must be at least {min_len} characters.")
    if not any(c.isalpha() for c in password):
        raise ValueError("Password must include at least one letter.")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password must include at least one number.")
    if password != password.strip():
        raise ValueError("Password must not contain leading or trailing spaces.")


class AuthService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = UserRepository(session)
        self.roles = RoleRepository(session)

    # ------------------------------------------------------------------ #
    # Database audit (visible in the Audit tab)
    # ------------------------------------------------------------------ #
    def _add_audit(self, accion: str, usuario: str | None, detalle: str | None = None) -> None:
        self.session.add(AuditLog(usuario=usuario, accion=accion, detalle=detalle))

    @staticmethod
    def _login_throttle() -> None:
        """Retraso configurable entre intentos de login fallidos (rate limiting).

        Se aplica en TODAS las rutas de rechazo para frenar la fuerza bruta y,
        de paso, uniformizar el tiempo de respuesta de cada intento.
        """
        ms = settings.security.login_failure_delay_ms
        if ms > 0:
            time.sleep(ms / 1000.0)

    # ------------------------------------------------------------------ #
    # Authentication
    # ------------------------------------------------------------------ #
    def authenticate(self, username: str, password: str, totp_code: str | None = None) -> User:
        username = self._normalize_username(username)
        user = self.repo.get_by_username(username)

        if user is None:
            # Consume the same time as a real hash verification to
            # avoid revealing whether the user exists (prevents enumeration).
            verify_password(password, _DUMMY_HASH)
            self._login_throttle()
            audit_logger.info("Login fallido (usuario inexistente) | username={}", username)
            raise AuthenticationError(_INVALID_CREDENTIALS_MSG)

        if user.bloqueado_hasta and user.bloqueado_hasta > datetime.utcnow():
            verify_password(password, _DUMMY_HASH)
            self._login_throttle()
            raise AuthenticationError(_INVALID_CREDENTIALS_MSG)

        if not user.activo:
            verify_password(password, _DUMMY_HASH)
            self._login_throttle()
            audit_logger.info("Login rechazado (cuenta desactivada) | username={}", username)
            raise AuthenticationError(_INVALID_CREDENTIALS_MSG)

        if not verify_password(password, user.password_hash):
            user.intentos_fallidos += 1
            intentos = user.intentos_fallidos
            if intentos >= settings.security.lockout_attempts:
                user.bloqueado_hasta = datetime.utcnow() + timedelta(
                    minutes=settings.security.lockout_minutes
                )
                audit_logger.info(
                    "Cuenta bloqueada por intentos fallidos | username={} | intentos={}",
                    username, intentos,
                )
            self.session.commit()
            self._login_throttle()
            audit_logger.info(
                "Login fallido (contraseña incorrecta) | username={} | intentos={}",
                username, intentos,
            )
            raise AuthenticationError(_INVALID_CREDENTIALS_MSG)

        # Second factor (TOTP): password is already valid, now the code.
        if user.totp_enabled:
            if not self._verify_totp(user, totp_code):
                # 2FA failures count toward account lockout (same
                # policy as password): prevents code brute-force.
                user.intentos_fallidos += 1
                intentos = user.intentos_fallidos
                if intentos >= settings.security.lockout_attempts:
                    user.bloqueado_hasta = datetime.utcnow() + timedelta(
                        minutes=settings.security.lockout_minutes
                    )
                self._add_audit("LOGIN_2FA_FAIL", username, f"intentos={intentos}")
                self.session.commit()
                self._login_throttle()
                audit_logger.info(
                    "Login fallido (2FA incorrecto) | username={} | intentos={}",
                    username, intentos,
                )
                raise AuthenticationError("Verification code is incorrect.")

        # Authentication exitosa: resetear contador de intentos y bloqueo.
        user.intentos_fallidos = 0
        user.bloqueado_hasta = None
        user.ultimo_login = datetime.utcnow()
        self._add_audit("LOGIN_OK", username)
        self.session.commit()
        audit_logger.info("Login exitoso | username={}", username)
        return user

    # ------------------------------------------------------------------ #
    # Account creation (self-registration from the login screen)
    # ------------------------------------------------------------------ #
    def register_user(self, username: str, password: str,
                      nombre_completo: str | None = None) -> User:
        """Register a new account with the default configured role.

        Uses ``settings.security.default_registration_role``. Allows the user
        to create their own account if the administrator has it enabled.
        """
        self._login_throttle()  # Throttle mass account creation.
        if not settings.security.allow_self_registration:
            raise BioVisionError(
                "El registro de nuevas cuentas está deshabilitado por el administrador."
            )

        username = self._normalize_username(username)
        if self.repo.get_by_username(username) is not None:
            raise BioVisionError(f"Ya existe un usuario con el nombre '{username}'.")
        validate_password_policy(password)

        role = self._default_registration_role()

        user = User(
            username=username,
            password_hash=hash_password(password),
            nombre_completo=nombre_completo or None,
            role_id=role.id,
            activo=True,
        )
        self.repo.add(user)
        self.session.commit()
        audit_logger.info("Cuenta creada por auto-registro | username={} | rol={}", username, role.nombre)
        return user

    def _default_registration_role(self) -> Role:
        nombre = settings.security.default_registration_role.strip() or "Operador"
        role = self.roles.get_by_name(nombre)
        if role is None:
            # If the configured role no longer exists, re-seed or use Operador.
            role = self.roles.get_by_name("Operador")
        if role is None:
            from app.core.permissions import DEFAULT_ROLES, permissions_to_csv
            self.roles.add(Role(nombre="Operador", permisos_csv=permissions_to_csv(
                DEFAULT_ROLES["Operador"]
            )))
            self.session.flush()
            role = self.roles.get_by_name("Operador")
        assert role is not None
        return role

    # ------------------------------------------------------------------ #
    # Passwords
    # ------------------------------------------------------------------ #
    def change_own_password(self, user_id: int, current_password: str, new_password: str) -> None:
        """Change the authenticated user's password, verifying the current one."""
        user = self.repo.get(user_id)
        if user is None:
            raise AuthenticationError("Usuario no encontrado.")

        if not verify_password(current_password, user.password_hash):
            audit_logger.info("Cambio de contraseña rechazado (clave actual incorrecta) | username={}",
                               user.username)
            raise AuthenticationError("Current password is incorrect.")

        validate_password_policy(new_password)
        user.password_hash = hash_password(new_password)
        user.intentos_fallidos = 0
        user.bloqueado_hasta = None
        self.revoke_remembered_sessions(user.id)
        self.session.commit()
        audit_logger.info("Contraseña actualizada | username={}", user.username)

    def change_password(self, user: User, new_password: str) -> None:
        """Cambio de contraseña sin verificación previa (flujo de administración)."""
        validate_password_policy(new_password)
        user.password_hash = hash_password(new_password)
        self.revoke_remembered_sessions(user.id)
        self.session.commit()
        audit_logger.info("Contraseña actualizada | username={}", user.username)

    # ------------------------------------------------------------------ #
    # Second factor (2FA / TOTP)
    # ------------------------------------------------------------------ #
    def is_totp_enabled(self, user: User) -> bool:
        return bool(user.totp_enabled)

    def generate_totp_secret(self) -> str:
        """Generate a new TOTP secret (base32) without persisting it."""
        return generate_secret()

    def configure_totp(self, user: User, secret: str, confirmation_code: str) -> None:
        """Guarda el secreto y lo activa tras verificar el código de emparejamiento.

        Flujo en dos tiempos: el administrador genera el secreto y lo muestra al
        usuario; cuando el usuario confirma que ya lo agregó a su app
        autenticadora introduciendo el código actual, se persiste y se habilita.
        """
        if not verify_code(secret, confirmation_code):
            raise AuthenticationError("Verification code is incorrect.")

        user.totp_secret = encrypt_value(secret)
        user.totp_enabled = True
        self._add_audit("TOTP_ENABLE", user.username)
        self.session.commit()
        audit_logger.info("2FA activado | username={}", user.username)

    def disable_totp(self, user: User) -> None:
        user.totp_secret = None
        user.totp_enabled = False
        self._add_audit("TOTP_DISABLE", user.username)
        self.session.commit()
        audit_logger.info("2FA desactivado | username={}", user.username)

    def totp_uri(self, user: User, secret: str | None = None) -> str:
        """URI otpauth para emparejar una app autenticadora."""
        if secret is None:
            if not user.totp_secret:
                raise BioVisionError("User has no TOTP secret configured.")
            secret = decrypt_value(user.totp_secret)
        return otpauth_uri(secret, user.username)

    def _verify_totp(self, user: User, code: str | None) -> bool:
        if not user.totp_secret:
            return False
        try:
            secret = decrypt_value(user.totp_secret)
        except Exception:  # noqa: BLE001 - token corrupto => no autenticar
            return False
        return verify_code(secret, code or "")

    # ------------------------------------------------------------------ #
    # Permissions / module gating
    # ------------------------------------------------------------------ #
    def has_permission(self, user: User | None, permission: str) -> bool:
        if user is None or user.role is None:
            return False
        perms = permissions_from_csv(user.role.permisos_csv)
        return "*" in perms or permission in perms

    def require_permission(self, user: User | None, permission: str) -> None:
        if not self.has_permission(user, permission):
            nombre = user.username if user is not None else "<desconocido>"
            raise AuthorizationError(
                f"El usuario '{nombre}' no tiene el permiso requerido: {permission}"
            )

    # ------------------------------------------------------------------ #
    # Remembered session (ephemeral token; password is never persisted)
    # ------------------------------------------------------------------ #
    def create_remembered_token(self, user: User) -> str:
        """Crea un token de 'recordar sesión' y devuelve el token crudo (única vez).

        Solo se guarda el hash SHA-256 del token en la BD. Cada usuario tiene un
        único token válido: crearlo reemplaza el anterior (rotación).
        """
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        days = settings.security.remember_credentials_days
        expires_at = None if days <= 0 else datetime.utcnow() + timedelta(days=days)
        self.session.query(RememberedSession).filter_by(user_id=user.id).delete()
        self.session.add(RememberedSession(user_id=user.id, token_hash=token_hash,
                                          expires_at=expires_at))
        self.session.commit()
        return token

    def revoke_remembered_sessions(self, user_id: int) -> None:
        """Invalida todos los tokens de 'recordar sesión' del usuario.

        Se llama al cambiar o reiniciar la contraseña y al desactivar/eliminar
        la cuenta: un token robado no debe sobrevivir a esos eventos.
        """
        self.session.query(RememberedSession).filter_by(user_id=user_id).delete()
        self.session.commit()

    def authenticate_remembered_token(self, token: str) -> User | None:
        """Authenticate via the 'remember me' token.

        Returns ``None`` if the token does not exist, is expired, belongs to a
        deactivated or locked account. If the user has 2FA enabled, raises
        ``TwoFactorRequiredError`` (auto-login must not bypass the second
        factor) without discarding the token.
        """
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        row = self.session.query(RememberedSession).filter_by(token_hash=token_hash).one_or_none()
        if row is None:
            return None
        if row.expires_at is not None and row.expires_at < datetime.utcnow():
            self.session.delete(row)
            self.session.commit()
            return None
        user = row.user
        if user is None or not user.activo:
            self.session.delete(row)
            self.session.commit()
            audit_logger.info("Auto-login rechazado (cuenta desactivada) | username={}", user.username if user else "-")
            return None
        if user.totp_enabled:
            # El auto-login no debe saltarse el segundo factor. El token se
            # conserva: la pantalla de login se abre precargada y, al volver a
            # autenticar, el token se rota como en cualquier login normal.
            raise TwoFactorRequiredError("Se requiere el código de verificación.")
        if user.bloqueado_hasta and user.bloqueado_hasta > datetime.utcnow():
            audit_logger.info("Auto-login rechazado (cuenta bloqueada) | username={}", user.username)
            return None
        # M10: el reingreso por token recordado queda auditado, igual que un
        # login normal (no puede haber accesos sin traza).
        self._add_audit("LOGIN_OK", user.username, "via=remembered_token")
        self.session.commit()
        audit_logger.info("Login por token recordado | username={}", user.username)
        return user

    @staticmethod
    def _normalize_username(username: str) -> str:
        return username.strip()

    @staticmethod
    def password_policy_hint() -> str:
        return (
            f"Mínimo {settings.security.min_password_length} caracteres, "
            "con al menos una letra y un número."
        )