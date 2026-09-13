"""Data access for Role and User entities."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Role, User


class RoleRepository:
    """Repository for Role entities."""

    def __init__(self, session: Session):
        """Initialize the repository.

        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session

    def add(self, role: Role) -> Role:
        """Add a new role.

        Args:
            role: Role to persist.

        Returns:
            The persisted role.
        """
        self.session.add(role)
        self.session.flush()
        return role

    def get(self, role_id: int) -> Role | None:
        """Get a role by ID.

        Args:
            role_id: Role identifier.

        Returns:
            Role or None if not found.
        """
        return self.session.get(Role, role_id)

    def get_by_name(self, nombre: str) -> Role | None:
        """Get a role by name.

        Args:
            nombre: Role name.

        Returns:
            Role or None if not found.
        """
        stmt = select(Role).where(Role.nombre == nombre)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_all(self) -> Sequence[Role]:
        """List all roles ordered by name.

        Returns:
            Sequence of Role objects.
        """
        return self.session.execute(select(Role).order_by(Role.nombre)).scalars().all()

    def delete(self, role_id: int) -> bool:
        """Delete a role by ID.

        Args:
            role_id: Role identifier.

        Returns:
            True if deleted, False if not found.
        """
        role = self.get(role_id)
        if role is None:
            return False
        self.session.delete(role)
        return True


class UserRepository:
    """Repository for User entities."""

    def __init__(self, session: Session):
        """Initialize the repository.

        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session

    def add(self, user: User) -> User:
        """Add a new user.

        Args:
            user: User to persist.

        Returns:
            The persisted user.
        """
        self.session.add(user)
        self.session.flush()
        return user

    def get(self, user_id: int) -> User | None:
        """Get a user by ID.

        Args:
            user_id: User identifier.

        Returns:
            User or None if not found.
        """
        return self.session.get(User, user_id)

    def get_by_username(self, username: str) -> User | None:
        """Get a user by username.

        Args:
            username: Username.

        Returns:
            User or None if not found.
        """
        stmt = select(User).where(User.username == username)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_all(self) -> Sequence[User]:
        """List all users ordered by username.

        Returns:
            Sequence of User objects.
        """
        return self.session.execute(select(User).order_by(User.username)).scalars().all()

    def count(self) -> int:
        """Return the total number of users.

        Returns:
            Total count.
        """
        return self.session.query(User).count()

    def delete(self, user_id: int) -> bool:
        """Delete a user by ID.

        Args:
            user_id: User identifier.

        Returns:
            True if deleted, False if not found.
        """
        user = self.get(user_id)
        if user is None:
            return False
        self.session.delete(user)
        return True
