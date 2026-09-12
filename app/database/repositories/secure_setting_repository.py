from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import SecureSetting


class SecureSettingRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, key: str) -> SecureSetting | None:
        return self.session.get(SecureSetting, key)

    def upsert(self, key: str, value_encrypted: bytes, descripcion: str | None = None) -> SecureSetting:
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
        return self.session.execute(select(SecureSetting).order_by(SecureSetting.key)).scalars().all()

    def delete(self, key: str) -> bool:
        setting = self.get(key)
        if setting is None:
            return False
        self.session.delete(setting)
        return True
