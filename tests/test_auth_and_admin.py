"""Tests for the Administration and Security module (Phase 4)."""
import shutil
import sqlite3
from datetime import datetime, timedelta

import pytest

from app.core.exceptions import AuthenticationError, AuthorizationError, BioVisionError
from app.core.permissions import PERM_ADMIN, PERM_PERSONAS
from app.database.base import Base
from app.database.models import Person, User
from app.services.admin_service import AdminService
from app.services.auth_service import AuthService, hash_password, validate_password_policy, verify_password


@pytest.fixture()
def session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def admin_and_operador(session):
    admin_svc = AdminService(session)
    admin = admin_svc.create_initial_admin("admin", "ClaveSegura123", "Admin General")
    roles = {r.nombre: r for r in admin_svc.list_roles()}
    operador = admin_svc.create_user(
        "operador1", "Clave1234", roles["Operador"].id, "Juan Operador", usuario_actor="admin"
    )
    return admin, operador, roles


# ------------------------------------------------------------------ #
# Hash / password policy
# ------------------------------------------------------------------ #
def test_hash_and_verify_password_roundtrip():
    h = hash_password("MiClaveSegura1")
    assert verify_password("MiClaveSegura1", h) is True
    assert verify_password("otra_clave", h) is False


def test_verify_password_rejects_garbage_hash():
    assert verify_password("cualquiera", "esto-no-es-un-hash-bcrypt") is False


def test_validate_password_policy_rejects_short_password():
    with pytest.raises(ValueError):
        validate_password_policy("123")


def test_validate_password_policy_accepts_valid_password():
    validate_password_policy("ClaveValida123")  # should not raise


# ------------------------------------------------------------------ #
# Initial setup (first launch)
# ------------------------------------------------------------------ #
def test_create_initial_admin_seeds_default_roles(session):
    admin_svc = AdminService(session)
    admin = admin_svc.create_initial_admin("admin", "ClaveSegura123")

    roles = {r.nombre for r in admin_svc.list_roles()}
    assert roles == {"Administrador", "Operador", "Visualizador"}
    assert admin.role.nombre == "Administrador"
    assert admin.role.permisos_csv == "*"


def test_create_initial_admin_fails_if_users_exist(session):
    admin_svc = AdminService(session)
    admin_svc.create_initial_admin("admin", "ClaveSegura123")
    with pytest.raises(BioVisionError):
        admin_svc.create_initial_admin("otro_admin", "OtraClave123")


# ------------------------------------------------------------------ #
# Authentication
# ------------------------------------------------------------------ #
def test_authenticate_success_updates_login_fields(session, admin_and_operador):
    admin, operador, _ = admin_and_operador
    auth = AuthService(session)

    user = auth.authenticate("operador1", "Clave1234")
    assert user.username == "operador1"
    assert user.ultimo_login is not None
    assert user.intentos_fallidos == 0


def test_authenticate_unknown_username_raises(session, admin_and_operador):
    auth = AuthService(session)
    with pytest.raises(AuthenticationError):
        auth.authenticate("no_existe", "cualquiera")


def test_authenticate_wrong_password_increments_attempts(session, admin_and_operador):
    auth = AuthService(session)
    with pytest.raises(AuthenticationError):
        auth.authenticate("operador1", "clave_incorrecta")

    user = AdminService(session).users.get_by_username("operador1")
    assert user.intentos_fallidos == 1


def test_account_locks_after_max_failed_attempts(session, admin_and_operador):
    from app.core.config import settings
    auth = AuthService(session)

    for _ in range(settings.security.lockout_attempts):
        with pytest.raises(AuthenticationError):
            auth.authenticate("operador1", "clave_incorrecta")

    # Even with the CORRECT password it must remain locked.
    # The message is generic: it does not reveal that the account is locked.
    with pytest.raises(AuthenticationError, match="Invalid username or password"):
        auth.authenticate("operador1", "Clave1234")


def test_account_unlocks_after_lockout_expires(session, admin_and_operador):
    auth = AuthService(session)
    user = AdminService(session).users.get_by_username("operador1")
    user.intentos_fallidos = 999
    user.bloqueado_hasta = datetime.utcnow() - timedelta(minutes=1)  # lock has already expired
    session.commit()

    logged_in = auth.authenticate("operador1", "Clave1234")
    assert logged_in.username == "operador1"
    assert logged_in.intentos_fallidos == 0


def test_authenticate_inactive_account_raises(session, admin_and_operador):
    _, operador, _ = admin_and_operador
    AdminService(session).set_user_active(operador.id, False, usuario_actor="admin")

    auth = AuthService(session)
    with pytest.raises(AuthenticationError, match="Invalid username or password"):
        auth.authenticate("operador1", "Clave1234")


# ------------------------------------------------------------------ #
# Permissions
# ------------------------------------------------------------------ #
def test_admin_has_all_permissions_via_wildcard(session, admin_and_operador):
    admin, _, _ = admin_and_operador
    auth = AuthService(session)
    assert auth.has_permission(admin, PERM_ADMIN) is True
    assert auth.has_permission(admin, PERM_PERSONAS) is True


def test_operador_lacks_admin_permission(session, admin_and_operador):
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    assert auth.has_permission(operador, PERM_PERSONAS) is True
    assert auth.has_permission(operador, PERM_ADMIN) is False


def test_require_permission_raises_authorization_error(session, admin_and_operador):
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    with pytest.raises(AuthorizationError):
        auth.require_permission(operador, PERM_ADMIN)


# ------------------------------------------------------------------ #
# User management
# ------------------------------------------------------------------ #
def test_create_user_duplicate_username_raises(session, admin_and_operador):
    _, _, roles = admin_and_operador
    admin_svc = AdminService(session)
    with pytest.raises(BioVisionError):
        admin_svc.create_user("operador1", "OtraClave123", roles["Operador"].id,
                              usuario_actor="admin")


def test_create_user_invalid_role_raises(session, admin_and_operador):
    admin, _, _ = admin_and_operador
    admin_svc = AdminService(session)
    with pytest.raises(BioVisionError):
        admin_svc.create_user("nuevo1", "ClaveSegura9", 99999,
                              "Nuevo Usuario", usuario_actor=admin.username)


def test_reset_password_enforces_policy(session, admin_and_operador):
    _, operador, _ = admin_and_operador
    admin_svc = AdminService(session)
    with pytest.raises(ValueError):
        admin_svc.reset_password(operador.id, "123", usuario_actor="admin")


def test_reset_password_allows_new_login(session, admin_and_operador):
    _, operador, _ = admin_and_operador
    admin_svc = AdminService(session)
    admin_svc.reset_password(operador.id, "NuevaClave456", usuario_actor="admin")

    auth = AuthService(session)
    user = auth.authenticate("operador1", "NuevaClave456")
    assert user.username == "operador1"


def test_delete_user(session, admin_and_operador):
    _, operador, _ = admin_and_operador
    admin_svc = AdminService(session)
    assert admin_svc.delete_user(operador.id, usuario_actor="admin") is True
    assert admin_svc.users.get_by_username("operador1") is None


# ------------------------------------------------------------------ #
# Role management
# ------------------------------------------------------------------ #
def test_create_role_duplicate_name_raises(session, admin_and_operador):
    admin_svc = AdminService(session)
    with pytest.raises(BioVisionError):
        admin_svc.create_role("Operador", [PERM_PERSONAS], usuario_actor="admin")


def test_update_role_permissions(session, admin_and_operador):
    _, _, roles = admin_and_operador
    admin_svc = AdminService(session)
    admin_svc.update_role_permissions(roles["Visualizador"].id, [PERM_ADMIN], usuario_actor="admin")

    updated = admin_svc.roles.get(roles["Visualizador"].id)
    assert updated.permisos_csv == PERM_ADMIN


def test_delete_role_blocked_if_in_use(session, admin_and_operador):
    _, _, roles = admin_and_operador
    admin_svc = AdminService(session)
    with pytest.raises(BioVisionError):
        admin_svc.delete_role(roles["Operador"].id, usuario_actor="admin")


def test_delete_role_succeeds_if_unused(session, admin_and_operador):
    _, _, roles = admin_and_operador
    admin_svc = AdminService(session)
    assert admin_svc.delete_role(roles["Visualizador"].id, usuario_actor="admin") is True


# ------------------------------------------------------------------ #
# Encrypted sensitive settings
# ------------------------------------------------------------------ #
def test_secure_setting_roundtrip_and_encryption_at_rest(session, admin_and_operador):
    admin_svc = AdminService(session)
    admin_svc.set_secure_setting("api_key_test", "valor-super-secreto", "Clave de prueba",
                                  usuario_actor="admin")

    raw = admin_svc.secrets.get("api_key_test")
    assert b"valor-super-secreto" not in raw.value_encrypted  # never in plain text in the DB

    value = admin_svc.get_secure_setting("api_key_test")
    assert value == "valor-super-secreto"


def test_secure_setting_delete(session, admin_and_operador):
    admin_svc = AdminService(session)
    admin_svc.set_secure_setting("temp_key", "algo", usuario_actor="admin")
    assert admin_svc.delete_secure_setting("temp_key", usuario_actor="admin") is True
    assert admin_svc.get_secure_setting("temp_key") is None


# ------------------------------------------------------------------ #
# Database cleanup
# ------------------------------------------------------------------ #
def test_cleanup_database_removes_data_but_keeps_users(session, admin_and_operador, tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings.storage, "photos_dir", str(tmp_path / "photos"))
    monkeypatch.setattr(settings.storage, "thumbnails_dir", str(tmp_path / "thumbs"))
    monkeypatch.setattr(settings.video, "evidence_dir", str(tmp_path / "evidence"))

    from app.database.repositories.person_repository import PersonRepository
    repo = PersonRepository(session)
    for i in range(3):
        repo.add(Person(nombre=f"P{i}", apellidos="Test"))
    session.commit()

    admin_svc = AdminService(session)
    result = admin_svc.cleanup_database(usuario_actor="admin")

    assert result["personas_eliminadas"] == 3
    assert session.query(Person).count() == 0
    assert session.query(User).count() == 2  # admin + operador are preserved


# ------------------------------------------------------------------ #
# Database restore
# ------------------------------------------------------------------ #
_MINIMAL_SCHEMA = """
    CREATE TABLE persons (uuid TEXT PRIMARY KEY, nombre TEXT, apellidos TEXT);
    CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
    CREATE TABLE roles (id INTEGER PRIMARY KEY, nombre TEXT);
    CREATE TABLE face_embeddings (id INTEGER PRIMARY KEY);
"""


def _make_minimal_backup(path, extra_sql: str = "") -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(_MINIMAL_SCHEMA + extra_sql)
    conn.commit()
    conn.close()


def test_restore_database(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.config import settings

    live_db_path = tmp_path / "live.db"
    backup_db_path = tmp_path / "backup.db"

    live_engine = create_engine(f"sqlite:///{live_db_path}")
    Base.metadata.create_all(live_engine)
    with live_engine.connect() as conn:
        conn.exec_driver_sql(
            "INSERT INTO persons (uuid, nombre, apellidos, fecha_creacion, fecha_modificacion) "
            "VALUES ('orig', 'Original', 'User', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )
        conn.commit()

    shutil.copy2(live_db_path, backup_db_path)

    with live_engine.connect() as conn:
        conn.exec_driver_sql(
            "INSERT INTO persons (uuid, nombre, apellidos, fecha_creacion, fecha_modificacion) "
            "VALUES ('nueva', 'Nueva', 'User', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )
        conn.commit()
    live_engine.dispose()

    LiveSession = sessionmaker(bind=create_engine(f"sqlite:///{live_db_path}"))
    live_session = LiveSession()
    AdminService(live_session).create_initial_admin("admin", "ClaveSegura123")  # guard actor

    monkeypatch.setattr(settings.database, "path", str(live_db_path))

    AdminService(live_session).restore_database(str(backup_db_path), usuario_actor="admin")

    check_engine = create_engine(f"sqlite:///{live_db_path}")
    with check_engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT uuid FROM persons").fetchall()
    assert [r[0] for r in rows] == ["orig"]
    check_engine.dispose()
    live_session.close()


def test_restore_database_requires_admin(tmp_path, monkeypatch, session, admin_and_operador):
    from app.core.config import settings

    monkeypatch.setattr(settings.database, "path", str(tmp_path / "live.db"))
    backup_db = tmp_path / "backup.db"
    _make_minimal_backup(backup_db)

    with pytest.raises(AuthorizationError):
        AdminService(session).restore_database(str(backup_db), usuario_actor="operador1")


def test_restore_database_missing_file_raises(session, admin_and_operador):
    with pytest.raises(BioVisionError):
        AdminService(session).restore_database("/ruta/que/no/existe.db", usuario_actor="admin")


def test_restore_database_invalid_sqlite_raises(tmp_path, monkeypatch, session, admin_and_operador):
    from app.core.config import settings

    monkeypatch.setattr(settings.database, "path", str(tmp_path / "live.db"))
    bad_file = tmp_path / "invalido.txt"
    bad_file.write_text("esto no es una base de datos")
    with pytest.raises(BioVisionError):
        AdminService(session).restore_database(str(bad_file), usuario_actor="admin")


def test_restore_database_missing_required_tables_raises(tmp_path, monkeypatch, session, admin_and_operador):
    from app.core.config import settings

    monkeypatch.setattr(settings.database, "path", str(tmp_path / "live.db"))
    other_db = tmp_path / "otra.db"
    conn = sqlite3.connect(str(other_db))
    conn.execute("CREATE TABLE otra_cosa (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    with pytest.raises(BioVisionError, match="respaldo válido"):
        AdminService(session).restore_database(str(other_db), usuario_actor="admin")


def test_restore_database_rejects_trigger(tmp_path, monkeypatch, session, admin_and_operador):
    from app.core.config import settings

    monkeypatch.setattr(settings.database, "path", str(tmp_path / "live.db"))
    backup_db = tmp_path / "con_trigger.db"
    _make_minimal_backup(
        backup_db,
        extra_sql="CREATE TRIGGER tr_persons AFTER INSERT ON persons BEGIN SELECT 1; END;",
    )

    with pytest.raises(BioVisionError, match="objetos no esperados"):
        AdminService(session).restore_database(str(backup_db), usuario_actor="admin")


def test_restore_database_rejects_extra_table(tmp_path, monkeypatch, session, admin_and_operador):
    from app.core.config import settings

    monkeypatch.setattr(settings.database, "path", str(tmp_path / "live.db"))
    backup_db = tmp_path / "con_extra.db"
    _make_minimal_backup(backup_db, extra_sql="CREATE TABLE evil_table (id INTEGER PRIMARY KEY);")

    with pytest.raises(BioVisionError, match="tablas desconocidas"):
        AdminService(session).restore_database(str(backup_db), usuario_actor="admin")


def test_restore_database_rejects_corrupt_backup(tmp_path, monkeypatch, session, admin_and_operador):
    from app.core.config import settings

    monkeypatch.setattr(settings.database, "path", str(tmp_path / "live.db"))
    backup_db = tmp_path / "corrupto.db"
    conn = sqlite3.connect(str(backup_db))
    conn.executescript(_MINIMAL_SCHEMA)
    # Large data: forces data pages beyond the first one.
    conn.execute(
        "INSERT INTO persons (uuid, nombre, apellidos) VALUES (?, ?, ?)",
        ("p1", "Original", "User" * 5000),
    )
    conn.commit()
    conn.close()

    # Truncate the file: data pages fall beyond EOF -> malformed.
    backup_db.write_bytes(backup_db.read_bytes()[:2048])

    with pytest.raises(BioVisionError, match="integridad|SQLite"):
        AdminService(session).restore_database(str(backup_db), usuario_actor="admin")


# ------------------------------------------------------------------ #
# Phase 5 (T1/M9): restore cleans up orphaned WAL files
# ------------------------------------------------------------------ #
def test_restore_cleans_stale_wal_files(tmp_path):
    from app.services.admin_service import _remove_stale_wal_files

    live = tmp_path / "live.db"
    live.write_bytes(b"data")
    (tmp_path / "live.db-wal").write_bytes(b"wal")
    (tmp_path / "live.db-shm").write_bytes(b"shm")

    _remove_stale_wal_files(live)

    assert live.exists()
    assert not (tmp_path / "live.db-wal").exists()
    assert not (tmp_path / "live.db-shm").exists()


# ------------------------------------------------------------------ #
# Remember session (token; password is never persisted)
# ------------------------------------------------------------------ #
def test_create_and_authenticate_remembered_token(session, admin_and_operador):
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    token = auth.create_remembered_token(operador)
    assert token
    user = auth.authenticate_remembered_token(token)
    assert user is not None
    assert user.id == operador.id


def test_remembered_token_is_hashed_in_db(session, admin_and_operador):
    from app.database.models import RememberedSession
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    token = auth.create_remembered_token(operador)
    row = session.query(RememberedSession).filter_by(user_id=operador.id).one()
    assert row.token_hash != token  # raw token is never persisted
    assert len(row.token_hash) == 64  # SHA-256


def test_remembered_token_rotation_replaces_previous(session, admin_and_operador):
    from app.database.models import RememberedSession
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    first = auth.create_remembered_token(operador)
    second = auth.create_remembered_token(operador)
    assert first != second
    assert session.query(RememberedSession).filter_by(user_id=operador.id).count() == 1
    assert auth.authenticate_remembered_token(first) is None
    assert auth.authenticate_remembered_token(second) is not None


def test_authenticate_remembered_token_wrong_token_returns_none(session, admin_and_operador):
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    auth.create_remembered_token(operador)
    assert auth.authenticate_remembered_token("token-invalido") is None


def test_remembered_token_expired_is_invalid(session, admin_and_operador):
    from app.database.models import RememberedSession
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    token = auth.create_remembered_token(operador)
    row = session.query(RememberedSession).filter_by(user_id=operador.id).one()
    row.expires_at = datetime.utcnow() - timedelta(minutes=1)
    session.commit()
    assert auth.authenticate_remembered_token(token) is None
    assert session.query(RememberedSession).filter_by(user_id=operador.id).count() == 0


def test_remembered_token_inactive_user_is_invalid(session, admin_and_operador):
    from app.database.models import RememberedSession
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    token = auth.create_remembered_token(operador)
    AdminService(session).set_user_active(operador.id, False, usuario_actor="admin")
    assert auth.authenticate_remembered_token(token) is None
    assert session.query(RememberedSession).filter_by(user_id=operador.id).count() == 0


def test_remembered_token_does_not_bypass_2fa(session, admin_and_operador):
    from app.core.exceptions import TwoFactorRequiredError
    from app.core.totp import current_code, generate_secret
    from app.database.models import RememberedSession
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    secret = generate_secret()
    auth.configure_totp(operador, secret, current_code(secret))
    assert operador.totp_enabled

    token = auth.create_remembered_token(operador)
    with pytest.raises(TwoFactorRequiredError):
        auth.authenticate_remembered_token(token)
    # Token is preserved: normal login will rotate it after completing 2FA.
    assert session.query(RememberedSession).filter_by(user_id=operador.id).count() == 1


# ------------------------------------------------------------------ #
# Phase 5 (M10): auto-login via remembered token is audited
# ------------------------------------------------------------------ #
def test_remembered_token_auto_login_is_audited(session, admin_and_operador):
    from app.database.models import AuditLog
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    token = auth.create_remembered_token(operador)

    user = auth.authenticate_remembered_token(token)
    assert user is not None
    assert user.id == operador.id

    row = (
        session.query(AuditLog)
        .filter_by(usuario=operador.username, accion="LOGIN_OK")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None
    assert row.detalle == "via=remembered_token"


def test_remembered_token_blocked_account_rejected(session, admin_and_operador):
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    token = auth.create_remembered_token(operador)

    operador.bloqueado_hasta = datetime.utcnow() + timedelta(minutes=30)
    session.commit()
    assert auth.authenticate_remembered_token(token) is None


# ------------------------------------------------------------------ #
# Phase 2 (M12): changing/resetting password revokes tokens
# ------------------------------------------------------------------ #
def test_change_own_password_revokes_remembered_token(session, admin_and_operador):
    from app.database.models import RememberedSession
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    token = auth.create_remembered_token(operador)
    assert auth.authenticate_remembered_token(token) is not None

    auth.change_own_password(operador.id, "Clave1234", "NuevaClaveSegura9")
    assert auth.authenticate_remembered_token(token) is None
    assert session.query(RememberedSession).filter_by(user_id=operador.id).count() == 0


def test_change_password_revokes_remembered_token(session, admin_and_operador):
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    token = auth.create_remembered_token(operador)

    auth.change_password(operador, "OtraClaveSegura7")
    assert auth.authenticate_remembered_token(token) is None


def test_admin_reset_password_revokes_remembered_token(session, admin_and_operador):
    from app.database.models import RememberedSession
    admin, operador, _ = admin_and_operador
    auth = AuthService(session)
    admin_svc = AdminService(session)
    token = auth.create_remembered_token(operador)

    admin_svc.reset_password(operador.id, "ReseteadaSegura5", usuario_actor=admin.username)
    assert auth.authenticate_remembered_token(token) is None
    assert session.query(RememberedSession).filter_by(user_id=operador.id).count() == 0


# ------------------------------------------------------------------ #
# Phase 2 (M15): deactivating/deleting users revokes their tokens
# ------------------------------------------------------------------ #
def test_deactivate_user_revokes_remembered_token(session, admin_and_operador):
    admin, operador, _ = admin_and_operador
    auth = AuthService(session)
    admin_svc = AdminService(session)
    token = auth.create_remembered_token(operador)

    admin_svc.set_user_active(operador.id, False, usuario_actor=admin.username)
    assert operador.activo is False
    assert auth.authenticate_remembered_token(token) is None


def test_delete_user_revokes_remembered_token(session, admin_and_operador):
    from app.database.models import RememberedSession
    admin, operador, _ = admin_and_operador
    auth = AuthService(session)
    admin_svc = AdminService(session)
    token = auth.create_remembered_token(operador)

    assert admin_svc.delete_user(operador.id, usuario_actor=admin.username) is True
    assert auth.authenticate_remembered_token(token) is None
    assert session.query(RememberedSession).filter_by(user_id=operador.id).count() == 0


# ------------------------------------------------------------------ #
# Phase 2 (M13): 2FA operations require admin at service layer
# ------------------------------------------------------------------ #
def test_totp_operations_require_admin(session, admin_and_operador):
    _, operador, _ = admin_and_operador
    admin_svc = AdminService(session)
    with pytest.raises(AuthorizationError):
        admin_svc.generate_totp_secret(usuario_actor=operador.username)
    with pytest.raises(AuthorizationError):
        admin_svc.is_user_totp_enabled(operador.id, usuario_actor=operador.username)
    with pytest.raises(AuthorizationError):
        admin_svc.user_totp_uri(operador.id, "SECRETO123", usuario_actor=operador.username)


# ------------------------------------------------------------------ #
# Phase 7 (T3): complete 2FA flow at service level
# ------------------------------------------------------------------ #
def test_generate_totp_secret_returns_base32(session):
    secret = AuthService(session).generate_totp_secret()
    assert len(secret) >= 16
    assert secret.isalnum()


def test_configure_totp_wrong_code_raises_and_does_not_enable(session, admin_and_operador):
    from app.core.totp import generate_secret
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    secret = generate_secret()

    with pytest.raises(AuthenticationError, match="Verification code"):
        auth.configure_totp(operador, secret, "000000")

    session.refresh(operador)
    assert operador.totp_enabled is False
    assert operador.totp_secret is None


def test_configure_totp_enables_and_login_requires_code(session, admin_and_operador):
    from app.core.totp import current_code, generate_secret
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    secret = generate_secret()

    auth.configure_totp(operador, secret, current_code(secret))
    assert operador.totp_enabled is True

    # Without the code, password alone is no longer enough.
    with pytest.raises(AuthenticationError, match="Verification code"):
        auth.authenticate("operador1", "Clave1234")
    # With the correct code, login succeeds.
    user = auth.authenticate("operador1", "Clave1234", current_code(secret))
    assert user.username == "operador1"


def test_totp_uri_contains_account_and_secret(session, admin_and_operador):
    from app.core.totp import current_code, generate_secret
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    secret = generate_secret()

    auth.configure_totp(operador, secret, current_code(secret))
    uri = auth.totp_uri(operador)
    assert uri.startswith("otpauth://totp/FaceScan:operador1?")
    assert f"secret={secret}" in uri


def test_totp_uri_without_secret_raises(session, admin_and_operador):
    _, operador, _ = admin_and_operador
    with pytest.raises(BioVisionError, match="TOTP secret"):
        AuthService(session).totp_uri(operador)


def test_disable_totp_restores_password_only_login(session, admin_and_operador):
    from app.core.totp import current_code, generate_secret
    _, operador, _ = admin_and_operador
    auth = AuthService(session)
    secret = generate_secret()

    auth.configure_totp(operador, secret, current_code(secret))
    auth.disable_totp(operador)
    assert operador.totp_enabled is False
    assert operador.totp_secret is None

    # Password is sufficient again.
    user = auth.authenticate("operador1", "Clave1234")
    assert user.username == "operador1"


def test_admin_2fa_flow_enable_uri_disable(session, admin_and_operador):
    from app.core.totp import current_code, generate_secret
    _, operador, _ = admin_and_operador
    admin_svc = AdminService(session)

    secret = admin_svc.generate_totp_secret(usuario_actor="admin")
    assert admin_svc.is_user_totp_enabled(operador.id, usuario_actor="admin") is False

    admin_svc.enable_user_totp(operador.id, secret, current_code(secret),
                               usuario_actor="admin")
    assert admin_svc.is_user_totp_enabled(operador.id, usuario_actor="admin") is True
    assert f"secret={secret}" in admin_svc.user_totp_uri(operador.id, usuario_actor="admin")

    admin_svc.disable_user_totp(operador.id, usuario_actor="admin")
    assert admin_svc.is_user_totp_enabled(operador.id, usuario_actor="admin") is False
