"""Per-user UI preferences service (language, etc.).

The GUI (or Administration tab) interacts only with this service.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.database.repositories.user_preference_repository import UserPreferenceRepository
from app.i18n import _SUPPORTED, _DEFAULT, system_language


class PreferencesService:
    """Service for managing per-user preferences."""

    def __init__(self, session: Session):
        """Initialize the service.

        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session
        self.repo = UserPreferenceRepository(session)

    def get_language(self, user_id: int) -> str:
        """Return the persisted language for a user, falling back to system.

        Args:
            user_id: User identifier.

        Returns:
            Language code.
        """
        language = self.repo.get_language(user_id, default=None)
        if language in _SUPPORTED:
            return language
        return system_language()

    def set_language(self, user_id: int, language: str) -> None:
        """Persist the language preference for a user.

        Args:
            user_id: User identifier.
            language: Language code to store.
        """
        if language not in _SUPPORTED:
            language = _DEFAULT
        self.repo.set_language(user_id, language)
