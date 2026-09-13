"""1:1 and 1:N biometric comparison via cosine similarity."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.core.config import settings
from app.utils.vector_utils import cosine_distance, cosine_similarity


def similarity_to_percent(similarity: float, threshold: float | None = None) -> float:
    """Convert cosine similarity to a calibrated match percentage.

    The naive formula ``(sim + 1) / 2`` shows ~50% for unrelated faces
    (similarity approx. 0), which is misleading. A logistic function centered
    on the match threshold is used instead, so that:
      - similarity at threshold   -> 50%
      - well above threshold      -> near 100%
      - well below threshold      -> near 0%

    Args:
        similarity: Cosine similarity in [-1, 1].
        threshold: Match threshold. Defaults to settings.

    Returns:
        Calibrated percentage in [0, 100].
    """
    threshold = settings.recognition.match_threshold if threshold is None else threshold
    sim_threshold = 1.0 - threshold
    steepness = 12.0
    z = steepness * (similarity - sim_threshold)
    pct = 100.0 / (1.0 + math.exp(-z))
    return round(max(0.0, min(100.0, pct)), 2)


@dataclass
class MatchCandidate:
    """Candidate match for a query embedding."""

    person_uuid: str
    embedding_id: int
    distance: float
    similarity: float

    @property
    def confidence_pct(self) -> float:
        """Calibrated match percentage using the configured threshold."""
        return similarity_to_percent(self.similarity)

    @property
    def is_match(self) -> bool:
        """Whether the candidate meets the match threshold."""
        return self.distance <= settings.recognition.match_threshold


def compare_pair(embedding_a: np.ndarray, embedding_b: np.ndarray) -> dict:
    """Compare two embeddings 1:1 (biometric comparator module).

    Args:
        embedding_a: First embedding.
        embedding_b: Second embedding.

    Returns:
        Dictionary with cosine distance, similarity, percentage, and threshold.
    """
    distance = cosine_distance(embedding_a, embedding_b)
    similarity = cosine_similarity(embedding_a, embedding_b)
    return {
        "distancia_coseno": round(distance, 4),
        "similitud": round(similarity, 4),
        "porcentaje_similitud": similarity_to_percent(similarity),
        "es_misma_persona_probable": distance <= settings.recognition.match_threshold,
        "umbral_usado": settings.recognition.match_threshold,
    }


def rank_candidates(
    query_embedding: np.ndarray,
    gallery: list[tuple[str, int, np.ndarray]],
    top_k: int | None = None,
) -> list[MatchCandidate]:
    """Search 1:N against the entire embedding gallery.

    Args:
        query_embedding: Query embedding vector.
        gallery: List of (person_uuid, embedding_id, vector).
        top_k: Maximum results to return. Defaults to settings.

    Returns:
        List of MatchCandidate sorted by distance ascending.

    Notes:
        Normalizes the query once and reuses already-normalized gallery
        vectors (dot product equals cosine similarity), avoiding per-pair
        norm recomputation.
    """
    top_k = top_k or settings.recognition.top_k_results
    query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-10)
    candidates: list[MatchCandidate] = []

    for person_uuid, embedding_id, vector in gallery:
        if abs(1.0 - np.linalg.norm(vector)) > 1e-3:
            vector = vector / (np.linalg.norm(vector) + 1e-10)
        similarity = float(np.dot(query_norm, vector))
        distance = 1.0 - similarity
        candidates.append(
            MatchCandidate(
                person_uuid=person_uuid,
                embedding_id=embedding_id,
                distance=distance,
                similarity=similarity,
            )
        )

    candidates.sort(key=lambda c: c.distance)
    return candidates[:top_k]
