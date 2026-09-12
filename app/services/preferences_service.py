"""
Servicio de preferencias de interfaz por usuario (idioma, etc.).
La GUI (o la pestaña de Administración) solo interactúa con este servicio.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.database.repositories.user_preference_repository import UserPreferenceRepository
from app.i18n import _SUPPORTED, _DEFAULT, system_language


class PreferencesService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = UserPreferenceRepository(session)

    def get_language(self, user_id: int) -> str:
        """Idioma persistido del usuario; si no existe, usa el del sistema."""
        language = self.repo.get_language(user_id, default=None)
        if language in _SUPPORTED:
            return language
        return system_language()

    def set_language(self, user_id: int, language: str) -> None:
        if language not in _SUPPORTED:
            language = _DEFAULT
        self.repo.set_language(user_id, language)