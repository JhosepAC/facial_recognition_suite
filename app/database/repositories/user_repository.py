from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Role, User


class RoleRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, role: Role) -> Role:
        self.session.add(role)
        self.session.flush()
        return role

    def get(self, role_id: int) -> Role | None:
        return self.session.get(Role, role_id)

    def get_by_name(self, nombre: str) -> Role | None:
        stmt = select(Role).where(Role.nombre == nombre)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_all(self) -> Sequence[Role]:
        return self.session.execute(select(Role).order_by(Role.nombre)).scalars().all()

    def delete(self, role_id: int) -> bool:
        role = self.get(role_id)
        if role is None:
            return False
        self.session.delete(role)
        return True


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user

    def get(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_all(self) -> Sequence[User]:
        return self.session.execute(select(User).order_by(User.username)).scalars().all()

    def count(self) -> int:
        return self.session.query(User).count()

    def delete(self, user_id: int) -> bool:
        user = self.get(user_id)
        if user is None:
            return False
        self.session.delete(user)
        return True
