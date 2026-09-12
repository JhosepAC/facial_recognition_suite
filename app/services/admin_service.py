"""
Servicio de administración. Cubre del spec:
  - usuarios, roles, permisos
  - configuración (valores sensibles cifrados)
  - respaldo / restauración (restauración; el respaldo ya vive en ExportService)
  - limpieza de base de datos
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AuthorizationError, BioVisionError
from app.core.logger import audit_logger
from app.core.permissions import PERM_ADMIN, DEFAULT_ROLES, permissions_to_csv
from app.core.security import decrypt_value, encrypt_value
from app.database.models import Person, RecognitionEvent, Role, SecureSetting, User, VideoJob
from app.database.repositories.secure_setting_repository import SecureSettingRepository
from app.database.repositories.user_repository import RoleRepository, UserRepository
from app.database.session import engine
from app.services.auth_service import AuthService, hash_password, validate_password_policy


# Tablas imprescindibles de cualquier respaldo válido de FaceScan.
_REQUIRED_TABLES = {"persons", "users", "roles", "face_embeddings"}

# Esquema completo de la aplicación: un respaldo legítimo no debe traer nada más.
_EXPECTED_TABLES = {
    "persons", "photos", "face_embeddings", "roles", "users",
    "audit_logs", "recognition_events", "video_jobs", "video_detections",
    "secure_settings", "user_preferences", "remembered_sessions", "sqlite_sequence",
}


class AdminService:
    def __init__(self, session: Session):
        self.session = session
        self.users = UserRepository(session)
        self.roles = RoleRepository(session)
        self.secrets = SecureSettingRepository(session)

    # ------------------------------------------------------------------ #
    # Autorización (defensa en profundidad; la GUI ya filtra los módulos)
    # ------------------------------------------------------------------ #
    def _require_admin(self, usuario_actor: str | None) -> None:
        """Fuerza que `usuario_actor` tenga el permiso de administración."""
        if usuario_actor is None:
            raise AuthorizationError(
                "Operación de administración sin actor identificado."
            )
        from app.services.auth_service import AuthService
        actor = AuthService(self.session).repo.get_by_username(usuario_actor)
        AuthService(self.session).require_permission(actor, PERM_ADMIN)

    # ------------------------------------------------------------------ #
    # Arranque inicial: roles por defecto + primer administrador
    # ------------------------------------------------------------------ #
    def seed_default_roles(self) -> None:
        for nombre, permisos in DEFAULT_ROLES.items():
            if self.roles.get_by_name(nombre) is None:
                self.roles.add(Role(nombre=nombre, permisos_csv=permissions_to_csv(permisos)))
        self.session.commit()

    def create_initial_admin(self, username: str, password: str,
                              nombre_completo: str | None = None) -> User:
        if self.users.count() > 0:
            raise BioVisionError("Ya existen usuarios; no se puede repetir la configuración inicial.")
        validate_password_policy(password)
        self.seed_default_roles()
        admin_role = self.roles.get_by_name("Administrador")

        user = User(
            username=username.strip(),
            password_hash=hash_password(password),
            nombre_completo=nombre_completo,
            role_id=admin_role.id,
            activo=True,
        )
        self.users.add(user)
        self.session.commit()
        audit_logger.info("Usuario administrador inicial creado | username={}", user.username)
        return user

    # ------------------------------------------------------------------ #
    # Gestión de usuarios
    # ------------------------------------------------------------------ #
    def create_user(self, username: str, password: str, role_id: int,
                     nombre_completo: str | None = None, usuario_actor: str | None = None) -> User:
        self._require_admin(usuario_actor)
        if self.users.get_by_username(username.strip()) is not None:
            raise BioVisionError(f"Ya existe un usuario con el nombre '{username}'.")
        validate_password_policy(password)
        if self.roles.get(role_id) is None:
            raise BioVisionError("El rol seleccionado no existe.")

        user = User(
            username=username.strip(),
            password_hash=hash_password(password),
            nombre_completo=nombre_completo,
            role_id=role_id,
            activo=True,
        )
        self.users.add(user)
        self.session.commit()
        audit_logger.info("Usuario creado | username={} | por={}", user.username, usuario_actor or "sistema")
        return user

    def set_user_active(self, user_id: int, active: bool, usuario_actor: str | None = None) -> None:
        self._require_admin(usuario_actor)
        user = self.users.get(user_id)
        if user is None:
            raise BioVisionError("Usuario no encontrado.")
        if not active and self._is_only_active_admin(user):
            raise BioVisionError(
                "No puedes desactivar al último administrador activo del sistema."
            )
        user.activo = active
        if active:
            user.intentos_fallidos = 0
            user.bloqueado_hasta = None
        else:
            # Un token recordado no debe seguir funcionando si la cuenta se desactiva.
            AuthService(self.session).revoke_remembered_sessions(user.id)
        self.session.commit()
        audit_logger.info("Usuario {} | username={} | por={}",
                           "activado" if active else "desactivado", user.username, usuario_actor or "sistema")

    def reset_password(self, user_id: int, new_password: str, usuario_actor: str | None = None) -> None:
        self._require_admin(usuario_actor)
        user = self.users.get(user_id)
        if user is None:
            raise BioVisionError("Usuario no encontrado.")
        validate_password_policy(new_password)
        user.password_hash = hash_password(new_password)
        user.intentos_fallidos = 0
        user.bloqueado_hasta = None
        AuthService(self.session).revoke_remembered_sessions(user.id)
        self.session.commit()
        audit_logger.info("Contraseña reiniciada | username={} | por={}", user.username, usuario_actor or "sistema")

    def update_user_role(self, user_id: int, role_id: int, usuario_actor: str | None = None) -> None:
        self._require_admin(usuario_actor)
        user = self.users.get(user_id)
        if user is None:
            raise BioVisionError("Usuario no encontrado.")
        nuevo_rol = self.roles.get(role_id)
        if nuevo_rol is None:
            raise BioVisionError("El rol seleccionado no existe.")
        if self._is_only_active_admin(user) and nuevo_rol.nombre != "Administrador":
            raise BioVisionError(
                "No puedes cambiar el rol del último administrador activo del sistema."
            )
        user.role_id = role_id
        self.session.commit()
        audit_logger.info("Rol actualizado | username={} | por={}", user.username, usuario_actor or "sistema")

    def delete_user(self, user_id: int, usuario_actor: str | None = None) -> bool:
        self._require_admin(usuario_actor)
        user = self.users.get(user_id)
        if user is None:
            return False
        if self._is_only_active_admin(user):
            raise BioVisionError(
                "No puedes eliminar al último administrador activo del sistema."
            )
        username = user.username
        AuthService(self.session).revoke_remembered_sessions(user.id)
        deleted = self.users.delete(user_id)
        self.session.commit()
        audit_logger.info("Usuario eliminado | username={} | por={}", username, usuario_actor or "sistema")
        return deleted

    # ------------------------------------------------------------------ #
    # 2FA de usuarios
    # ------------------------------------------------------------------ #
    def generate_totp_secret(self, usuario_actor: str | None = None) -> str:
        """Genera un secreto TOTP nuevo (no persistido)."""
        self._require_admin(usuario_actor)
        return AuthService(self.session).generate_totp_secret()

    def enable_user_totp(self, user_id: int, secret: str, confirmation_code: str,
                         usuario_actor: str | None = None) -> None:
        """Habilita 2FA en el usuario indicado tras verificar su código."""
        self._require_admin(usuario_actor)
        user = self.users.get(user_id)
        if user is None:
            raise BioVisionError("Usuario no encontrado.")
        AuthService(self.session).configure_totp(user, secret, confirmation_code)

    def disable_user_totp(self, user_id: int, usuario_actor: str | None = None) -> None:
        self._require_admin(usuario_actor)
        user = self.users.get(user_id)
        if user is None:
            raise BioVisionError("Usuario no encontrado.")
        AuthService(self.session).disable_totp(user)

    def user_totp_uri(self, user_id: int, secret: str | None = None,
                      usuario_actor: str | None = None) -> str:
        self._require_admin(usuario_actor)
        user = self.users.get(user_id)
        if user is None:
            raise BioVisionError("Usuario no encontrado.")
        return AuthService(self.session).totp_uri(user, secret)

    def is_user_totp_enabled(self, user_id: int, usuario_actor: str | None = None) -> bool:
        self._require_admin(usuario_actor)
        user = self.users.get(user_id)
        if user is None:
            return False
        return AuthService(self.session).is_totp_enabled(user)

    # ------------------------------------------------------------------ #
    def _is_only_active_admin(self, user: User) -> bool:
        """True si `user` es un administrador activo y es el único de su tipo."""
        if not user.activo or user.role is None or user.role.nombre != "Administrador":
            return False
        otros_admin_activos = (
            self.session.query(User)
            .join(Role)
            .filter(User.id != user.id, Role.nombre == "Administrador", User.activo.is_(True))
            .count()
        )
        return otros_admin_activos == 0

    def list_users(self) -> list[User]:
        return list(self.users.list_all())

    # ------------------------------------------------------------------ #
    # Gestión de roles y permisos
    # ------------------------------------------------------------------ #
    def create_role(self, nombre: str, permisos: list[str], usuario_actor: str | None = None) -> Role:
        self._require_admin(usuario_actor)
        if self.roles.get_by_name(nombre) is not None:
            raise BioVisionError(f"Ya existe un rol llamado '{nombre}'.")
        role = self.roles.add(Role(nombre=nombre, permisos_csv=permissions_to_csv(permisos)))
        self.session.commit()
        audit_logger.info("Rol creado | nombre={} | por={}", nombre, usuario_actor or "sistema")
        return role

    def update_role_permissions(self, role_id: int, permisos: list[str],
                                 usuario_actor: str | None = None) -> None:
        self._require_admin(usuario_actor)
        role = self.roles.get(role_id)
        if role is None:
            raise BioVisionError("Rol no encontrado.")
        role.permisos_csv = permissions_to_csv(permisos)
        self.session.commit()
        audit_logger.info("Permisos de rol actualizados | rol={} | por={}", role.nombre, usuario_actor or "sistema")

    def delete_role(self, role_id: int, usuario_actor: str | None = None) -> bool:
        self._require_admin(usuario_actor)
        en_uso = self.session.query(User).filter(User.role_id == role_id).count()
        if en_uso > 0:
            raise BioVisionError(
                f"No se puede eliminar: {en_uso} usuario(s) tienen asignado este rol."
            )
        role = self.roles.get(role_id)
        if role is None:
            return False
        nombre = role.nombre
        deleted = self.roles.delete(role_id)
        self.session.commit()
        audit_logger.info("Rol eliminado | nombre={} | por={}", nombre, usuario_actor or "sistema")
        return deleted

    def list_roles(self) -> list[Role]:
        return list(self.roles.list_all())

    # ------------------------------------------------------------------ #
    # Configuración sensible cifrada
    # ------------------------------------------------------------------ #
    def set_secure_setting(self, key: str, plaintext_value: str, descripcion: str | None = None,
                            usuario_actor: str | None = None) -> None:
        self._require_admin(usuario_actor)
        encrypted = encrypt_value(plaintext_value)
        self.secrets.upsert(key, encrypted, descripcion)
        self.session.commit()
        audit_logger.info("Configuración sensible actualizada | clave={} | por={}",
                           key, usuario_actor or "sistema")

    def get_secure_setting(self, key: str) -> str | None:
        setting = self.secrets.get(key)
        if setting is None:
            return None
        return decrypt_value(setting.value_encrypted)

    def list_secure_setting_keys(self) -> list[SecureSetting]:
        """Devuelve los registros SIN descifrar (para listados; usar get_secure_setting para el valor)."""
        return list(self.secrets.list_all())

    def delete_secure_setting(self, key: str, usuario_actor: str | None = None) -> bool:
        self._require_admin(usuario_actor)
        deleted = self.secrets.delete(key)
        self.session.commit()
        audit_logger.info("Configuración sensible eliminada | clave={} | por={}", key, usuario_actor or "sistema")
        return deleted

    # ------------------------------------------------------------------ #
    # Limpieza de base de datos (conserva usuarios/roles/config. segura)
    # ------------------------------------------------------------------ #
    def cleanup_database(self, usuario_actor: str | None = None) -> dict:
        self._require_admin(usuario_actor)
        n_personas = self.session.query(Person).count()
        n_eventos = self.session.query(RecognitionEvent).count()
        n_videos = self.session.query(VideoJob).count()

        for person in self.session.query(Person).all():
            self.session.delete(person)  # cascada: Photo + FaceEmbedding
        self.session.query(RecognitionEvent).delete()
        for job in self.session.query(VideoJob).all():
            self.session.delete(job)  # cascada: VideoDetection
        self.session.commit()

        for dir_setting in (settings.storage.photos_dir, settings.storage.thumbnails_dir,
                             settings.video.evidence_dir):
            d = settings.resolve_path(dir_setting)
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)

        audit_logger.info(
            "Base de datos limpiada | personas={} | eventos={} | videos={} | por={}",
            n_personas, n_eventos, n_videos, usuario_actor or "sistema",
        )
        return {
            "personas_eliminadas": n_personas,
            "eventos_eliminados": n_eventos,
            "videos_eliminados": n_videos,
        }

    # ------------------------------------------------------------------ #
    # Restauración desde un respaldo SQLite (ver ExportService.backup_database)
    # ------------------------------------------------------------------ #
    def restore_database(self, backup_path: str, usuario_actor: str | None = None) -> None:
        """
        Restaura la base de datos en vivo a partir de un archivo de respaldo.

        Validación del respaldo (M11): debe ser una BD SQLite íntegra
        (``PRAGMA integrity_check``), contener las tablas esenciales y no
        traer objetos (triggers/vistas/tablas) que no pertenezcan al esquema
        de FaceScan.

        Antes de sobrescribir el archivo se termina la transacción de la
        sesión ORM (``rollback``) y se cierra el pool de conexiones
        (``engine.dispose``) para no bloquear el archivo en vivo, y las
        conexiones de copia usan ``busy_timeout`` (C2).

        La GUI debe cerrar la aplicación tras una restauración exitosa.
        """
        self._require_admin(usuario_actor)

        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise BioVisionError(f"El archivo de respaldo no existe: {backup_path}")

        try:
            probe = sqlite3.connect(str(backup_file), timeout=30)
            integrity = probe.execute("PRAGMA integrity_check").fetchone()[0]
            objects = probe.execute("SELECT type, name FROM sqlite_master").fetchall()
            probe.close()
        except sqlite3.DatabaseError as exc:
            raise BioVisionError(
                f"El archivo no es una base de datos SQLite válida: {exc}"
            ) from exc

        if integrity != "ok":
            raise BioVisionError(
                f"El respaldo falló la verificación de integridad: "
                f"PRAGMA integrity_check = '{integrity}'."
            )

        tables = {name for obj_type, name in objects if obj_type == "table"}
        extra_objects = [(obj_type, name) for obj_type, name in objects
                         if obj_type not in ("table", "index")]

        missing = sorted(_REQUIRED_TABLES - tables)
        if missing:
            raise BioVisionError(
                "El archivo no parece ser un respaldo válido de FaceScan "
                f"(faltan tablas: {', '.join(missing)})."
            )

        if extra_objects:
            detalle = "; ".join(f"{t}:{n}" for t, n in extra_objects)
            raise BioVisionError(
                "El respaldo contiene objetos no esperados "
                f"({detalle}). Restauración cancelada."
            )

        extra_tables = sorted(tables - _EXPECTED_TABLES)
        if extra_tables:
            raise BioVisionError(
                "El respaldo contiene tablas desconocidas: "
                + ", ".join(extra_tables) + ". Restauración cancelada."
            )

        # C2: liberar la transacción de la sesión ORM y el pool antes de sobrescribir.
        self.session.rollback()
        engine.dispose()

        live_db_path = settings.resolve_path(settings.database.path)
        source = sqlite3.connect(str(backup_file), timeout=30)
        dest = sqlite3.connect(str(live_db_path), timeout=30)
        try:
            with dest:
                source.backup(dest)
        finally:
            source.close()
            dest.close()

        _remove_stale_wal_files(live_db_path)

        audit_logger.info("Base de datos restaurada desde {} | por={}",
                           backup_path, usuario_actor or "sistema")


def _remove_stale_wal_files(db_path: Path) -> None:
    """Elimina los archivos '-wal'/'-shm' huérfanos de una BD en modo WAL.

    La restauración sobrescribe el archivo '.db' con un snapshot completo; un
    '-wal' previo contendría tramas del archivo antiguo que SQLite podría
    intentar reproducir en el siguiente arranque (corrupción). Como el
    snapshot ya está completo, ambos archivos son basura segura de eliminar.
    """
    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
