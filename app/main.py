"""FaceScan entry point.

Startup flow:
    1. Initialize the database.
    2. If no users exist, show the initial setup dialog
       (creates the administrator account).
    3. If the user saved their session ("Remember session"), enter directly
       by validating the session token; otherwise show the login screen.
    4. Open the main window for that user.
    5. If the user logs out (instead of closing the application), show the
       login again without auto-login (the session was explicitly closed).

Run with:
    python -m app.main
"""
import shutil
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog

from app.core.config import LOGO_PATH, settings
from app.core.exceptions import TwoFactorRequiredError
from app.core.logger import logger
from app.database.models import User
from app.database.session import get_session, init_db
from app.gui.main_window import MainWindow
from app.gui.theme import get_stylesheet
from app.gui.widgets.login_widget import (
    FirstRunSetupDialog,
    LoginDialog,
    RememberedCredentials,
)
from app.i18n import set_language as set_i18n_language, system_language
from app.services.auth_service import AuthService
from app.services.preferences_service import PreferencesService


def _ensure_models() -> None:
    """Install bundled facial models into ``~/.insightface``.

    In frozen mode (PyInstaller), models are bundled inside the executable
    and copied once to the standard InsightFace directory:

        %USERPROFILE%\\.insightface\\models\\<model>

    This allows the application to work offline after installation.
    """
    try:
        from app.core.config import BUNDLE_DIR

        model = settings.vision.detector_model

        target = (
            Path.home()
            / ".insightface"
            / "models"
            / model
        )

        source = (
            BUNDLE_DIR
            / "models"
            / model
        )

        # -------------------------------------------------------------
        # Minimum expected files for the buffalo_l package.
        #
        # The folder alone is not sufficient.
        # -------------------------------------------------------------
        expected_models = {
            "1k3d68.onnx",
            "2d106det.onnx",
            "det_10g.onnx",
            "genderage.onnx",
            "w600k_r50.onnx",
        }

        existing_models = {
            file.name
            for file in target.glob("*.onnx")
        } if target.exists() else set()

        # -------------------------------------------------------------
        # All models are already installed.
        # -------------------------------------------------------------
        if expected_models.issubset(existing_models):
            logger.info(
                "InsightFace models already installed at {}",
                target,
            )
            return

        # -------------------------------------------------------------
        # Not present in the bundle.
        #
        # This can happen during development because models may have been
        # previously installed by InsightFace in ~/.insightface.
        # -------------------------------------------------------------
        if not source.exists():
            logger.info(
                "No bundled facial models at {}. "
                "Existing models at {} will be used if installed.",
                source,
                target,
            )
            return

        # -------------------------------------------------------------
        # Create parent directory.
        # -------------------------------------------------------------
        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # -------------------------------------------------------------
        # If there is a partial installation, remove it before copying.
        # -------------------------------------------------------------
        if target.exists():
            shutil.rmtree(target)

        shutil.copytree(
            source,
            target,
        )

        logger.info(
            "Bundled facial models installed successfully at {}",
            target,
        )

    except Exception:  # noqa: BLE001
        logger.exception(
            "Could not install bundled facial models."
        )


def _apply_user_language(user_id: int) -> None:
    """Activate the user's persisted language (or system language as fallback).

    Args:
        user_id: Identifier of the authenticated user.
    """
    try:
        with get_session() as session:
            language = PreferencesService(session).get_language(user_id)
        set_i18n_language(language)
    except Exception:  # noqa: BLE001
        logger.warning("Could not load language preference; using system language.")
        set_i18n_language(system_language())


def _try_auto_login() -> tuple[int | None, str | None]:
    """Resume the saved session without showing the login screen.

    Returns:
        Tuple ``(user_id, prefill_username)``. If the token is valid but the
        user has 2FA enabled, returns ``(None, username)``: the token is not
        discarded (it is kept for the regular login) and the screen is opened
        pre-filled.
    """
    username, token, has_token, autologin = RememberedCredentials().load()
    if not autologin or not username or not has_token or not token:
        return None, None

    user_id: int | None = None
    try:
        with get_session() as session:
            user = AuthService(session).authenticate_remembered_token(token)
            if user is not None:
                user_id = user.id  # Retrieve ID while the session is still open
    except TwoFactorRequiredError:
        return None, username
    except Exception:  # noqa: BLE001 - invalid token or transient error
        user_id = None

    if user_id is None:
        # Invalid, expired, or deactivated account token: discard it and
        # show the regular login (plain-text password was never bypassed).
        RememberedCredentials().clear()
        return None, None

    return user_id, None


def main() -> None:
    """Run the FaceScan application lifecycle."""
    logger.info("Starting FaceScan...")
    init_db()
    _ensure_models()

    app = QApplication(sys.argv)
    app.setApplicationName("FaceScan")
    app.setWindowIcon(QIcon(str(LOGO_PATH)))
    app.setStyleSheet(get_stylesheet(settings.app.theme))

    with get_session() as session:
        has_users = session.query(User).count() > 0

    if not has_users:
        setup_dialog = FirstRunSetupDialog()
        if setup_dialog.exec() != QDialog.Accepted:
            sys.exit(0)

    first_iteration = True
    while True:
        authenticated_id: int | None = None
        prefill_username: str | None = None

        if first_iteration:
            authenticated_id, prefill_username = _try_auto_login()
            first_iteration = False

        if authenticated_id is None:
            login_dialog = LoginDialog(prefill_username=prefill_username)
            if login_dialog.exec() != QDialog.Accepted:
                sys.exit(0)
            authenticated_id = login_dialog.authenticated_user_id

        _apply_user_language(authenticated_id)
        window = MainWindow(current_user_id=authenticated_id)
        window.show()
        app.exec()

        if not window.logout_requested:
            break  # Window was closed normally (not via "Log out") -> exit

    sys.exit(0)


if __name__ == "__main__":
    main()
