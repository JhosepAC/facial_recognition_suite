from __future__ import annotations

from typing import Sequence

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.database.models import Person


class PersonRepository:
    """Acceso a datos de Person. No contiene lógica de negocio ni de IA."""

    def __init__(self, session: Session):
        self.session = session

    def add(self, person: Person) -> Person:
        self.session.add(person)
        self.session.flush()
        return person

    def get(self, person_uuid: str) -> Person | None:
        return self.session.get(Person, person_uuid)

    def delete(self, person_uuid: str) -> bool:
        person = self.get(person_uuid)
        if person is None:
            return False
        self.session.delete(person)
        return True

    def list_all(self, limit: int = 200, offset: int = 0) -> Sequence[Person]:
        stmt = select(Person).order_by(Person.apellidos, Person.nombre).limit(limit).offset(offset)
        return self.session.execute(stmt).scalars().all()

    def count(self) -> int:
        return self.session.query(Person).count()

    def search_text(self, query: str, limit: int = 100,
                    empresa: str | None = None) -> Sequence[Person]:
        """
        Búsqueda por texto en campos de identificación y contacto (NO empresa):
        nombre, apellidos, alias, departamento, cargo, teléfono y correo.

        Se soportan búsquedas de varias palabras (cada token debe coincidir con
        al menos un campo, p.ej. "Juan Pérez"). La empresa se excluye del texto
        libre: solo se filtra a través del combo dedicado (parámetro `empresa`).
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
        """Empresas registradas (distintas), ordenadas alfabéticamente."""
        stmt = (
            select(Person.empresa)
            .where(Person.empresa.isnot(None))
            .distinct()
            .order_by(Person.empresa)
        )
        return [e for e in self.session.execute(stmt).scalars().all() if e]
