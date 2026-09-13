"""Data access for FaceEmbedding entities."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import FaceEmbedding


class EmbeddingRepository:
    """Data access for FaceEmbedding."""

    def __init__(self, session: Session):
        """Initialize the repository.

        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session

    def add(self, embedding: FaceEmbedding) -> FaceEmbedding:
        """Add a new embedding.

        Args:
            embedding: FaceEmbedding to persist.

        Returns:
            The persisted embedding.
        """
        self.session.add(embedding)
        self.session.flush()
        return embedding

    def list_all(self) -> Sequence[FaceEmbedding]:
        """Fetch all embeddings in the biometric gallery.

        Scalability note: for large galleries the 1:N search does not iterate
        this list; ``app.recognition.ann_index`` builds an in-memory FAISS index
        (ANN) that is rebuilt only when the set changes and falls back to exact
        linear search if ``faiss-cpu`` is not installed.

        Returns:
            Sequence of FaceEmbedding objects.
        """
        stmt = select(FaceEmbedding)
        return self.session.execute(stmt).scalars().all()

    def list_by_person(self, person_uuid: str) -> Sequence[FaceEmbedding]:
        """List embeddings for a specific person.

        Args:
            person_uuid: Person UUID.

        Returns:
            Sequence of FaceEmbedding objects.
        """
        stmt = select(FaceEmbedding).where(FaceEmbedding.person_uuid == person_uuid)
        return self.session.execute(stmt).scalars().all()

    def delete_by_photo(self, photo_id: int) -> None:
        """Delete embeddings associated with a photo.

        Args:
            photo_id: Photo identifier.
        """
        stmt = select(FaceEmbedding).where(FaceEmbedding.photo_id == photo_id)
        for emb in self.session.execute(stmt).scalars().all():
            self.session.delete(emb)
