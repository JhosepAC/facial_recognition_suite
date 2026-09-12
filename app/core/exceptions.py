"""Excepciones de dominio de FaceScan."""


class BioVisionError(Exception):
    """Excepción base de la aplicación."""


class NoFaceDetectedError(BioVisionError):
    """No se detectó ningún rostro en la imagen/frame procesado."""


class MultipleFacesError(BioVisionError):
    """Se esperaba un único rostro pero se detectaron varios."""


class LowQualityFaceError(BioVisionError):
    """El rostro detectado no cumple el umbral mínimo de calidad/confianza."""


class PersonNotFoundError(BioVisionError):
    """No existe una persona con el identificador/criterio indicado."""


class DuplicatePersonError(BioVisionError):
    """Ya existe una persona con un rostro biométricamente equivalente."""


class AuthenticationError(BioVisionError):
    """Credenciales inválidas o sesión expirada."""


class TwoFactorRequiredError(AuthenticationError):
    """El usuario debe completar la verificación en dos pasos (2FA/TOTP)."""


class AuthorizationError(BioVisionError):
    """El usuario no tiene permisos suficientes para la acción solicitada."""


class ModelLoadError(BioVisionError):
    """Error al cargar los modelos de IA (detector / embedder)."""
