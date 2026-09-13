"""Data access for per-user preferences (language, etc.)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import UserPreference


class UserPreferenceRepository:
    """Repository for UserPreference entities."""

    def __init__(self, session: Session):
        """Initialize the repository.

        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session

    def get(self, user_id: int) -> UserPreference | None:
        """Get preferences for a user.

        Args:
            user_id: User identifier.

        Returns:
            UserPreference or None if not found.
        """
        stmt = select(UserPreference).where(UserPreference.user_id == user_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_language(self, user_id: int, default: str = "en") -> str:
        """Get the stored language for a user.

        Args:
            user_id: User identifier.
            default: Fallback language if no preference exists.

        Returns:
            Language code.
        """
        pref = self.get(user_id)
        return pref.language if pref else default

    def set_language(self, user_id: int, language: str) -> UserPreference:
        """Create or update the language preference for a user.

        Args:
            user_id: User identifier.
            language: Language code to store.

        Returns:
            The persisted UserPreference.
        """
        pref = self.get(user_id)
        if pref is None:
            pref = UserPreference(user_id=user_id, language=language)
            self.session.add(pref)
        else:
            pref.language = language
        self.session.flush()
        return pref
