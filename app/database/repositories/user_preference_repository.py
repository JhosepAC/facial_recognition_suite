"""Acceso a datos de preferencias por usuario (idioma, etc.)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import UserPreference


class UserPreferenceRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, user_id: int) -> UserPreference | None:
        stmt = select(UserPreference).where(UserPreference.user_id == user_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_language(self, user_id: int, default: str = "en") -> str:
        pref = self.get(user_id)
        return pref.language if pref else default

    def set_language(self, user_id: int, language: str) -> UserPreference:
        pref = self.get(user_id)
        if pref is None:
            pref = UserPreference(user_id=user_id, language=language)
            self.session.add(pref)
        else:
            pref.language = language
        self.session.flush()
        return pref