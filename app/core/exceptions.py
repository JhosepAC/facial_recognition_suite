"""FaceScan domain exceptions."""


class BioVisionError(Exception):
    """Base exception for the application."""


class NoFaceDetectedError(BioVisionError):
    """No face was detected in the processed image/frame."""


class MultipleFacesError(BioVisionError):
    """A single face was expected but multiple faces were detected."""


class LowQualityFaceError(BioVisionError):
    """The detected face does not meet the minimum quality/confidence threshold."""


class PersonNotFoundError(BioVisionError):
    """No person exists for the given identifier/criteria."""


class DuplicatePersonError(BioVisionError):
    """A person with a biometrically equivalent face already exists."""


class AuthenticationError(BioVisionError):
    """Invalid credentials or expired session."""


class TwoFactorRequiredError(AuthenticationError):
    """The user must complete two-factor verification (2FA/TOTP)."""


class AuthorizationError(BioVisionError):
    """The user lacks sufficient permissions for the requested action."""


class ModelLoadError(BioVisionError):
    """Failed to load AI models (detector / embedder)."""
