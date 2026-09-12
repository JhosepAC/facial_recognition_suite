"""
Punto de entrada de FaceScan.

Flujo de arranque:
  1. Inicializa la base de datos.
  2. Si no existe ningún usuario, muestra el diálogo de configuración inicial
     (crea la cuenta de administrador).
  3. Si el usuario guardó su sesión ("Recordar sesión"), ingresa directamente
     validando el token de sesión; si no, muestra la pantalla de login.
  4. Abre la ventana principal para ese usuario.
  5. Si el usuario cierra sesión (en vez de cerrar la aplicación), vuelve a
     mostrar el login sin auto-login (la sesión fue cerrada explícitamente).

Ejecutar con:
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
from app.database.session import get_session, init_db
from app.database.models import User
from app.gui.main_window import MainWindow
from app.gui.theme import get_stylesheet
from app.gui.widgets.login_widget import (
    FirstRunSetupDialog, LoginDialog, RememberedCredentials,
)
from app.i18n import set_language as set_i18n_language, system_language
from app.services.auth_service import AuthService
from app.services.preferences_service import PreferencesService


def _ensure_models() -> None:
    """
    Instala los modelos faciales empaquetados en ~/.insightface.

    En modo congelado (PyInstaller), los modelos viajan dentro del bundle
    y se copian una vez al directorio estándar de InsightFace:

        %USERPROFILE%\\.insightface\\models\\<modelo>

    De esta forma la aplicación puede funcionar sin Internet después de
    instalarse.
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
        # Archivos mínimos esperados del paquete buffalo_l.
        #
        # No basta con que exista la carpeta.
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
        # Ya están todos los modelos instalados.
        # -------------------------------------------------------------
        if expected_models.issubset(existing_models):
            logger.info(
                "Modelos InsightFace ya instalados en {}",
                target,
            )
            return

        # -------------------------------------------------------------
        # No existen en el bundle.
        #
        # Esto puede ocurrir durante desarrollo, porque los modelos pueden
        # haber sido instalados previamente por InsightFace en ~/.insightface.
        # -------------------------------------------------------------
        if not source.exists():
            logger.info(
                "No hay modelos faciales empaquetados en {}. "
                "Se utilizarán los modelos existentes en {} si están "
                "instalados.",
                source,
                target,
            )
            return

        # -------------------------------------------------------------
        # Crear directorio padre.
        # -------------------------------------------------------------
        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # -------------------------------------------------------------
        # Si hay una instalación parcial, eliminarla antes de copiar.
        # -------------------------------------------------------------
        if target.exists():
            shutil.rmtree(target)

        shutil.copytree(
            source,
            target,
        )

        logger.info(
            "Modelos faciales empaquetados instalados correctamente en {}",
            target,
        )

    except Exception:  # noqa: BLE001
        logger.exception(
            "No se pudieron instalar los modelos faciales empaquetados."
        )

def _apply_user_language(user_id: int) -> None:
    """Activa el idioma persistido del usuario (o el del sistema si no existe)."""
    try:
        with get_session() as session:
            language = PreferencesService(session).get_language(user_id)
        set_i18n_language(language)
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo cargar la preferencia de idioma; se usará el del sistema.")
        set_i18n_language(system_language())

def _try_auto_login() -> tuple[int | None, str | None]:
    """Reanuda la sesión guardada sin pasar por la pantalla de login.

    Devuelve ``(user_id, prefill_username)``. Si el token es válido pero el
    usuario tiene 2FA, devuelve ``(None, username)``: el token NO se descarta
    (se conserva para el login normal) y la pantalla se abre precargada.
    """
    username, token, has_token, autologin = RememberedCredentials().load()
    if not autologin or not username or not has_token or not token:
        return None, None

    user_id: int | None = None
    try:
        with get_session() as session:
            user = AuthService(session).authenticate_remembered_token(token)
            if user is not None:
                user_id = user.id  # <-- Se obtiene la ID mientras la sesión está abierta
    except TwoFactorRequiredError:
        return None, username
    except Exception:  # noqa: BLE001 - token inválido o error transitorio
        user_id = None

    if user_id is None:
        # Token no válido, vencido o de una cuenta desactivada: se descarta y se
        # muestra el login normal (nunca se saltó la contraseña en texto plano).
        RememberedCredentials().clear()
        return None, None

    return user_id, None

def main() -> None:
    logger.info("Iniciando FaceScan...")
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
            break  # la ventana se cerró normalmente (no por "Cerrar sesión") -> salir

    sys.exit(0)


if __name__ == "__main__":
    main()