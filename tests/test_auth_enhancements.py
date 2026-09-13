"""
Tests del bounded context AUTH ampliado (auto-registro, política de
contraseñas, cambio de contraseña propia) y de las guardas anti-lockout
del bounded context ADMIN.
"""
import pytest

from app.core.exceptions import AuthenticationError, BioVisionError
from app.services.admin_service import AdminService
from app.services.auth_service import (
    AuthService, validate_password_policy, verify_password,
)


@pytest.fixture()
def session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database.base import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def seeded(session):
    admin_svc = AdminService(session)
    admin = admin_svc.create_initial_admin("admin", "ClaveSegura123", "Admin General")
    roles = {r.nombre: r for r in admin_svc.list_roles()}
    return admin, roles


# ------------------------------------------------------------------ #
# Política de contraseñas
# ------------------------------------------------------------------ #
def test_policy_requires_min_length():
    with pytest.raises(ValueError):
        validate_password_policy("A1")


def test_policy_requires_a_letter():
    with pytest.raises(ValueError, match="letter"):
        validate_password_policy("12345678")


def test_policy_requires_a_number():
    with pytest.raises(ValueError, match="number"):
        validate_password_policy("abcdefgh")


def test_policy_rejects_leading_or_trailing_spaces():
    with pytest.raises(ValueError, match="spaces"):
        validate_password_policy("  Clave123 ")


def test_policy_accepts_valid_combination():
    validate_password_policy("ClaveMuySegura99")


# ------------------------------------------------------------------ #
# Auto-registro de cuentas
# ------------------------------------------------------------------ #
def test_register_user_creates_account_with_default_role(session, seeded):
    user = AuthService(session).register_user("nuevo", "MiClave123", "Nuevo Usuario")
    assert user.username == "nuevo"
    assert user.role.nombre == "Operador"
    assert user.activo is True


def test_register_user_then_authenticate(session, seeded):
    AuthService(session).register_user("nuevo2", "MiClave123")
    logged = AuthService(session).authenticate("nuevo2", "MiClave123")
    assert logged.username == "nuevo2"


def test_register_user_duplicate_raises(session, seeded):
    auth = AuthService(session)
    auth.register_user("duplicado", "MiClave123")
    with pytest.raises(BioVisionError, match="Ya existe"):
        auth.register_user("duplicado", "OtraClave123")


def test_register_user_disabled_raises(session, seeded, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings.security, "allow_self_registration", False)
    with pytest.raises(BioVisionError, match="deshabilitado"):
        AuthService(session).register_user("bloqueado", "MiClave123")


def test_register_user_enforces_password_policy(session, seeded):
    with pytest.raises(ValueError):
        AuthService(session).register_user("débil", "123")


# ------------------------------------------------------------------ #
# Cambio de contraseña propia
# ------------------------------------------------------------------ #
def test_change_own_password_wrong_current_raises(session, seeded):
    admin, _ = seeded
    auth = AuthService(session)
    with pytest.raises(AuthenticationError, match="Current password is incorrect"):
        auth.change_own_password(admin.id, "ClaveEquivocada", "NuevaClave456")


def test_change_own_password_success(session, seeded):
    admin, _ = seeded
    auth = AuthService(session)
    auth.change_own_password(admin.id, "ClaveSegura123", "NuevaClave456")

    # La clave nueva funciona; la antigua no.
    assert verify_password("NuevaClave456", admin.password_hash) is True
    with pytest.raises(AuthenticationError):
        auth.authenticate("admin", "ClaveSegura123")
    assert auth.authenticate("admin", "NuevaClave456").username == "admin"


# ------------------------------------------------------------------ #
# Guardas anti-lockout: nunca quedar sin administrador activo
# ------------------------------------------------------------------ #
def test_cannot_deactivate_last_active_admin(session, seeded):
    admin, _ = seeded
    svc = AdminService(session)
    with pytest.raises(BioVisionError, match="último administrador"):
        svc.set_user_active(admin.id, False, usuario_actor="admin")


def test_cannot_delete_last_active_admin(session, seeded):
    admin, _ = seeded
    svc = AdminService(session)
    with pytest.raises(BioVisionError, match="último administrador"):
        svc.delete_user(admin.id, usuario_actor="admin")


def test_cannot_demote_last_active_admin(session, seeded):
    admin, roles = seeded
    svc = AdminService(session)
    with pytest.raises(BioVisionError, match="último administrador"):
        svc.update_user_role(admin.id, roles["Operador"].id, usuario_actor="admin")


def test_can_deactivate_admin_if_another_active_admin_exists(session, seeded):
    admin, roles = seeded
    svc = AdminService(session)
    second = svc.create_user("admin2", "ClaveAdmin2", roles["Administrador"].id,
                              usuario_actor="admin")
    svc.set_user_active(admin.id, False, usuario_actor="admin")
    refreshed = svc.users.get(second.id)
    assert refreshed.activo is True


def test_no_register_until_admin_seeded(session):
    # Sin usuarios ni roles sembrados, el auto-registro no encuentra rol
    # por defecto y usa el rol "Operador" sembrado dinámicamente.
    user = AuthService(session).register_user("primero", "MiClave123")
    assert user.role.nombre in {"Operador"}


# ------------------------------------------------------------------ #
# Fase 4 (A1/M7): rate limiting y uniformización de tiempos en login
# ------------------------------------------------------------------ #
def _capture_sleep(monkeypatch):
    from app.services import auth_service

    calls = []
    monkeypatch.setattr(auth_service.time, "sleep", lambda secs: calls.append(secs))
    return calls


def test_login_failure_is_throttled(session, seeded, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings.security, "login_failure_delay_ms", 300)
    calls = _capture_sleep(monkeypatch)
    with pytest.raises(AuthenticationError):
        AuthService(session).authenticate("admin", "ClaveEquivocada")
    assert calls == [0.3]


def test_successful_login_not_throttled(session, seeded, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings.security, "login_failure_delay_ms", 300)
    calls = _capture_sleep(monkeypatch)
    AuthService(session).authenticate("admin", "ClaveSegura123")
    assert calls == []


def test_register_user_is_throttled(session, seeded, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings.security, "login_failure_delay_ms", 200)
    calls = _capture_sleep(monkeypatch)
    AuthService(session).register_user("nuevo_throttle", "MiClave123")
    assert calls == [0.2]


def test_blocked_and_inactive_accounts_run_dummy_verify(session, seeded, monkeypatch):
    # M7: cuentas bloqueadas/desactivadas NO deben retornar de inmediato;
    # deben consumir una verificación "trampa" para no filtrar su estado.
    from datetime import datetime, timedelta

    from app.core.config import settings
    from app.services import auth_service

    monkeypatch.setattr(settings.security, "login_failure_delay_ms", 0)
    auth = AuthService(session)
    user = session.query(auth_service.User).filter_by(username="admin").one()
    user.bloqueado_hasta = datetime.utcnow() + timedelta(minutes=30)
    session.commit()

    verify_calls = []
    real = auth_service.verify_password

    def spy(pw, ph):
        verify_calls.append(pw)
        return real(pw, ph)

    monkeypatch.setattr(auth_service, "verify_password", spy)
    with pytest.raises(AuthenticationError):
        auth.authenticate("admin", "ClaveSegura123")
    assert len(verify_calls) == 1  # solo la verificación "trampa" (cuenta bloqueada)

    # Mismo caso con cuenta desactivada.
    user2 = session.query(auth_service.User).filter_by(username="admin").one()
    user2.bloqueado_hasta = None
    user2.activo = False
    session.commit()
    verify_calls.clear()
    with pytest.raises(AuthenticationError):
        auth.authenticate("admin", "ClaveSegura123")
    assert len(verify_calls) == 1


# ------------------------------------------------------------------ #
# Fase 4 (M3): los fallos de 2FA cuentan para el bloqueo de cuenta
# ------------------------------------------------------------------ #
def test_2fa_failures_count_toward_lockout(session, seeded, monkeypatch):
    from app.core.config import settings
    from app.core.totp import current_code, generate_secret
    from app.services import auth_service

    monkeypatch.setattr(settings.security, "login_failure_delay_ms", 0)
    auth = AuthService(session)
    user = session.query(auth_service.User).filter_by(username="admin").one()
    secret = generate_secret()
    auth.configure_totp(user, secret, current_code(secret))
    assert user.totp_enabled

    wrong = "000000" if current_code(secret) != "000000" else "111111"
    for _ in range(settings.security.lockout_attempts):
        with pytest.raises(AuthenticationError, match="Verification code"):
            auth.authenticate("admin", "ClaveSegura123", wrong)

    session.refresh(user)
    assert user.intentos_fallidos == settings.security.lockout_attempts
    assert user.bloqueado_hasta is not None

    # Ya bloqueada: aunque el código fuese correcto, el login se rechaza.
    with pytest.raises(AuthenticationError):
        auth.authenticate("admin", "ClaveSegura123", current_code(secret))


def test_successful_2fa_does_not_lock_account(session, seeded, monkeypatch):
    from app.core.config import settings
    from app.core.totp import current_code, generate_secret
    from app.services import auth_service

    monkeypatch.setattr(settings.security, "login_failure_delay_ms", 0)
    auth = AuthService(session)
    user = session.query(auth_service.User).filter_by(username="admin").one()
    secret = generate_secret()
    auth.configure_totp(user, secret, current_code(secret))

    logged = auth.authenticate("admin", "ClaveSegura123", current_code(secret))
    assert logged.username == "admin"
    session.refresh(user)
    assert user.intentos_fallidos == 0