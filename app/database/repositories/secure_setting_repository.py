"""Data access for encrypted secure settings."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import SecureSetting


class SecureSettingRepository:
    """Repository for SecureSetting entities."""

    def __init__(self, session: Session):
        """Initialize the repository.

        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session

    def get(self, key: str) -> SecureSetting | None:
        """Get a secure setting by key.

        Args:
            key: Setting key.

        Returns:
            SecureSetting or None if not found.
        """
        return self.session.get(SecureSetting, key)

    def upsert(self, key: str, value_encrypted: bytes, descripcion: str | None = None) -> SecureSetting:
        """Create or update a secure setting.

        Args:
            key: Setting key.
            value_encrypted: Encrypted value bytes.
            descripcion: Optional description.

        Returns:
            The persisted SecureSetting.
        """
        setting = self.get(key)
        if setting is None:
            setting = SecureSetting(key=key, value_encrypted=value_encrypted, descripcion=descripcion)
            self.session.add(setting)
        else:
            setting.value_encrypted = value_encrypted
            if descripcion is not None:
                setting.descripcion = descripcion
        self.session.flush()
        return setting

    def list_all(self) -> Sequence[SecureSetting]:
        """List all secure settings ordered by key.

        Returns:
            Sequence of SecureSetting objects.
        """
        return self.session.execute(select(SecureSetting).order_by(SecureSetting.key)).scalars().all()

    def delete(self, key: str) -> bool:
        """Delete a secure setting by key.

        Args:
            key: Setting key.

        Returns:
            True if deleted, False if not found.
        """
        setting = self.get(key)
        if setting is None:
            return False
        self.session.delete(setting)
        return True
