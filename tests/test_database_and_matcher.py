"""
Basic tests for the data layer and the biometric matcher.

Does not depend on insightface/PySide6 (AI model loading is not tested here).
"""
import numpy as np
import pytest

from app.database.base import Base
from app.database.models import Person
from app.database.repositories.person_repository import PersonRepository
from app.recognition.matcher import compare_pair, rank_candidates, similarity_to_percent
from app.utils.vector_utils import bytes_to_vector, vector_to_bytes


@pytest.fixture()
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    yield s
    s.close()


def test_create_and_search_person(session):
    repo = PersonRepository(session)
    p = repo.add(Person(nombre="Ana", apellidos="Torres", empresa="UPC"))
    session.commit()

    assert repo.count() == 1
    results = repo.search_text("Ana")
    assert len(results) == 1
    assert results[0].nombre_completo == "Ana Torres"


def test_vector_roundtrip():
    vec = np.random.rand(512).astype(np.float32)
    data = vector_to_bytes(vec)
    restored = bytes_to_vector(data, dim=512)
    assert np.allclose(vec, restored, atol=1e-6)


def test_compare_identical_vectors_is_match():
    a = np.random.rand(512).astype(np.float32)
    result = compare_pair(a, a.copy())
    assert result["distancia_coseno"] == pytest.approx(0.0, abs=1e-6)
    assert result["es_misma_persona_probable"] is True


def test_compare_unrelated_vectors_low_percentage():
    """Unrelated faces must not show ~50% similarity (regression for 50% bug)."""
    rng = np.random.default_rng(42)
    a = rng.normal(size=512).astype(np.float32)
    b = rng.normal(size=512).astype(np.float32)
    a /= np.linalg.norm(a)
    b /= np.linalg.norm(b)
    result = compare_pair(a, b)
    assert result["porcentaje_similitud"] < 10.0


def test_similarity_to_percent_is_calibrated_on_threshold():
    """Percentage should be ~50% at the threshold and ~0% for non-matches."""
    from app.core.config import settings

    threshold = settings.recognition.match_threshold
    assert similarity_to_percent(1.0 - threshold) == pytest.approx(50.0, abs=1.0)
    assert similarity_to_percent(0.0) < 5.0
    assert similarity_to_percent(1.0) > 90.0


def test_rank_candidates_orders_by_distance():
    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    close = np.array([0.99, 0.01, 0.0], dtype=np.float32)
    far = np.array([0.0, 1.0, 0.0], dtype=np.float32)

    gallery = [("uuid-far", 1, far), ("uuid-close", 2, close)]
    ranked = rank_candidates(query, gallery, top_k=2)

    assert ranked[0].person_uuid == "uuid-close"
    assert ranked[1].person_uuid == "uuid-far"
