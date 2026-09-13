"""Data access for Person entities."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.database.models import Person


class PersonRepository:
    """Data access for Person. Contains no business or AI logic."""

    def __init__(self, session: Session):
        """Initialize the repository.

        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session

    def add(self, person: Person) -> Person:
        """Add a new person.

        Args:
            person: Person instance to persist.

        Returns:
            The persisted person.
        """
        self.session.add(person)
        self.session.flush()
        return person

    def get(self, person_uuid: str) -> Person | None:
        """Get a person by UUID.

        Args:
            person_uuid: Person UUID.

        Returns:
            Person or None if not found.
        """
        return self.session.get(Person, person_uuid)

    def delete(self, person_uuid: str) -> bool:
        """Delete a person by UUID.

        Args:
            person_uuid: Person UUID.

        Returns:
            True if deleted, False if not found.
        """
        person = self.get(person_uuid)
        if person is None:
            return False
        self.session.delete(person)
        return True

    def list_all(self, limit: int = 200, offset: int = 0) -> Sequence[Person]:
        """List persons with pagination.

        Args:
            limit: Maximum number of results.
            offset: Result offset.

        Returns:
            Sequence of Person objects.
        """
        stmt = select(Person).order_by(Person.apellidos, Person.nombre).limit(limit).offset(offset)
        return self.session.execute(stmt).scalars().all()

    def count(self) -> int:
        """Return the total number of persons.

        Returns:
            Total count.
        """
        return self.session.query(Person).count()

    def search_text(self, query: str, limit: int = 100,
                    empresa: str | None = None) -> Sequence[Person]:
        """Search by text across identification and contact fields (excluding company).

        Searches across nombre, apellidos, alias, departamento, cargo, telefono
        and correo. Supports multi-word queries (each token must match at least
        one field, e.g., "John Doe"). Company is excluded from free-text
        search and filtered only via the dedicated ``empresa`` parameter.

        Args:
            query: Free-text query string.
            limit: Maximum number of results.
            empresa: Optional exact company filter.

        Returns:
            Matching persons.
        """
        conditions = []
        tokens = query.split()
        for token in tokens:
            like = f"%{token}%"
            conditions.append(
                or_(
                    Person.nombre.ilike(like),
                    Person.apellidos.ilike(like),
                    Person.alias.ilike(like),
                    Person.departamento.ilike(like),
                    Person.cargo.ilike(like),
                    Person.telefono.ilike(like),
                    Person.correo.ilike(like),
                )
            )
        if empresa:
            conditions.append(Person.empresa == empresa)

        stmt = (
            select(Person)
            .where(*conditions)
            .order_by(Person.apellidos, Person.nombre)
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()

    def list_empresas(self) -> Sequence[str]:
        """Return distinct company names sorted alphabetically.

        Returns:
            List of company names.
        """
        stmt = (
            select(Person.empresa)
            .where(Person.empresa.isnot(None))
            .distinct()
            .order_by(Person.empresa)
        )
        return [e for e in self.session.execute(stmt).scalars().all() if e]
