"""Comparación biométrica 1:1 y 1:N por similitud coseno."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.core.config import settings
from app.utils.vector_utils import cosine_distance, cosine_similarity


def similarity_to_percent(similarity: float, threshold: float | None = None) -> float:
    """
    Convierte similitud coseno en un porcentaje de coincidencia calibrado.

    La fórmula ingenua ``(sim + 1) / 2`` muestra ~50% para rostros sin relación
    (similitud ≈ 0), lo que resulta engañoso. Aquí se usa una función logística
    centrada en el umbral de coincidencia, de modo que:
      - similitud en el umbral       -> 50%
      - muy por encima del umbral    -> cerca de 100%
      - muy por debajo del umbral    -> cerca de 0%
    """
    threshold = settings.recognition.match_threshold if threshold is None else threshold
    sim_threshold = 1.0 - threshold
    steepness = 12.0
    z = steepness * (similarity - sim_threshold)
    pct = 100.0 / (1.0 + math.exp(-z))
    return round(max(0.0, min(100.0, pct)), 2)


@dataclass
class MatchCandidate:
    person_uuid: str
    embedding_id: int
    distance: float
    similarity: float

    @property
    def confidence_pct(self) -> float:
        """Porcentaje de coincidencia calibrado con el umbral configurado."""
        return similarity_to_percent(self.similarity)

    @property
    def is_match(self) -> bool:
        return self.distance <= settings.recognition.match_threshold


def compare_pair(embedding_a: np.ndarray, embedding_b: np.ndarray) -> dict:
    """Comparador 1 vs 1 (módulo 'Comparador biométrico')."""
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
    """
    Busca 1:N contra toda la galería de embeddings.

    gallery: lista de (person_uuid, embedding_id, vector)

    Normaliza el query una sola vez y reutiliza vectores de galería ya
    normalizados (producto punto = similitud coseno), evitando re-calcular la
    norma por cada par.
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
