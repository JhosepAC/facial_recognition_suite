from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import FaceEmbedding


class EmbeddingRepository:
    """Acceso a datos de FaceEmbedding."""

    def __init__(self, session: Session):
        self.session = session

    def add(self, embedding: FaceEmbedding) -> FaceEmbedding:
        self.session.add(embedding)
        self.session.flush()
        return embedding

    def list_all(self) -> Sequence[FaceEmbedding]:
        """
        Trae todos los embeddings de la base biométrica.

        Nota de escalabilidad: para bases grandes, la búsqueda 1:N no recorre
        esta lista: `app/recognition/ann_index.py` construye un índice FAISS en
        memoria (ANN) que se reconstruye solo cuando el conjunto cambia y cae
        a búsqueda lineal exacta si `faiss-cpu` no está instalado.
        """
        stmt = select(FaceEmbedding)
        return self.session.execute(stmt).scalars().all()

    def list_by_person(self, person_uuid: str) -> Sequence[FaceEmbedding]:
        stmt = select(FaceEmbedding).where(FaceEmbedding.person_uuid == person_uuid)
        return self.session.execute(stmt).scalars().all()

    def delete_by_photo(self, photo_id: int) -> None:
        stmt = select(FaceEmbedding).where(FaceEmbedding.photo_id == photo_id)
        for emb in self.session.execute(stmt).scalars().all():
            self.session.delete(emb)
