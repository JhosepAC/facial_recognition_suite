"""
Tests de la calibración del análisis facial extendido y de la persistencia de
edad/género. No dependen de insightface/mediapipe: los modelos solo se tocan
cuando se pide explícitamente un re-análisis, y allí se sustituyen por dobles.
"""
import json

import pytest

from app.database.base import Base
from app.database.models import FaceEmbedding, Person, Photo
from app.database.repositories.person_repository import PersonRepository
from app.services.calibration_service import CalibrationService
from app.vision.face_attributes import FaceAttributes, classify_from_conf


@pytest.fixture()
def session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    yield s
    s.close()


def _make_person(session, nombre, apellidos, conf, edad=None, genero=None):
    person = PersonRepository(session).add(Person(nombre=nombre, apellidos=apellidos))
    session.flush()
    photo = Photo(person_uuid=person.uuid, file_path="f_no_existe.jpg",
                  thumbnail_path=None, es_principal=True, calidad_score=80)
    session.add(photo)
    session.flush()
    attrs = FaceAttributes(
        gafas=conf["gafas"] >= 0.5, conf=conf, edad=edad, genero=genero)
    emb = FaceEmbedding(
        person_uuid=person.uuid, photo_id=photo.id, vector=b"\x00" * 8, dim=512,
        quality_score=80,
        facial_attributes=json.dumps(attrs.to_dict(), ensure_ascii=False),
    )
    session.add(emb)
    session.commit()
    return person


@pytest.fixture()
def cal_session(session):
    """Dos personas: Ana con gafas alta confianza, Luis con gafas baja confianza."""
    p0 = _make_person(session, "Ana", "Gomez",
                      {"gafas": 0.95, "barba": 0.1, "sonrisa": 0.8},
                      edad=34, genero="F")
    p1 = _make_person(session, "Luis", "Ruiz",
                      {"gafas": 0.20, "barba": 0.05, "sonrisa": 0.1},
                      edad=40, genero="M")
    return session, (p0, p1)


# ------------------------------------------------------------------ #
# FaceAttributes: roundtrip con edad/género
# ------------------------------------------------------------------ #
def test_attrs_roundtrip_preserves_age_gender():
    attrs = FaceAttributes(gafas=True, conf={"gafas": 0.9}, edad=42, genero="F")
    parsed = FaceAttributes.from_dict(attrs.to_dict())
    assert parsed is not None
    assert parsed.edad == 42
    assert parsed.genero == "F"
    assert parsed.gafas is True
    assert parsed.conf == {"gafas": 0.9}


def test_attrs_from_dict_tolerates_bad_age():
    attrs = FaceAttributes.from_dict({"gafas": True, "edad": "viejo", "genero": None})
    assert attrs is not None
    assert attrs.edad is None
    assert attrs.genero is None


# ------------------------------------------------------------------ #
# classify_from_conf (umbrales configurables)
# ------------------------------------------------------------------ #
def test_classify_from_conf_default_threshold():
    out = classify_from_conf({"gafas": 0.5})
    assert out.gafas is True
    out2 = classify_from_conf({"gafas": 0.499})
    assert out2.gafas is False


def test_classify_from_conf_custom_threshold():
    out = classify_from_conf({"gafas": 0.6}, thresholds={"gafas": 0.7})
    assert out.gafas is False
    out2 = classify_from_conf({"gafas": 0.6}, thresholds={"gafas": 0.5})
    assert out2.gafas is True


def test_classify_from_conf_empty_conf():
    out = classify_from_conf({})
    assert out.gafas is False and out.barba is False


# ------------------------------------------------------------------ #
# CalibrationService: recopilación y agregación
# ------------------------------------------------------------------ #
def test_collect_entries(cal_session):
    session, _ = cal_session
    entries = CalibrationService(session).collect()
    assert len(entries) == 2
    by_name = {e["nombre"]: e for e in entries}
    assert by_name["Ana Gomez"]["attrs"].edad == 34
    assert by_name["Luis Ruiz"]["attrs"].genero == "M"
    assert by_name["Ana Gomez"]["calidad"] == 80


def test_aggregate_respects_thresholds(cal_session):
    session, _ = cal_session
    entries = CalibrationService(session).collect()
    service = CalibrationService(session)
    loose = service.aggregate(entries, {"gafas": 0.05})
    assert loose["gafas"]["presente"] == 2
    strict = service.aggregate(entries, {"gafas": 0.9})
    assert strict["gafas"]["presente"] == 1
    assert strict["gafas"]["con_conf"] == 2


def test_reclassify_in_memory(cal_session):
    session, _ = cal_session
    entries = CalibrationService(session).collect()
    ana = next(e for e in entries if e["nombre"].startswith("Ana"))
    strict = CalibrationService.reclassify(ana["attrs"], {"gafas": 0.99})
    assert strict.gafas is False
    assert strict.edad == 34
    assert strict.genero == "F"


def test_apply_thresholds_persists_and_preserves_age_gender(cal_session):
    session, _ = cal_session
    service = CalibrationService(session)
    updated = service.apply_thresholds({"gafas": 0.9})
    assert updated == 2

    session.expire_all()
    entries = service.collect()
    ana = next(e for e in entries if e["nombre"].startswith("Ana"))
    luis = next(e for e in entries if e["nombre"].startswith("Luis"))
    assert ana["attrs"].gafas is True   # 0.95 >= 0.9
    assert luis["attrs"].gafas is False  # 0.20 < 0.9
    assert ana["attrs"].edad == 34
    assert luis["attrs"].genero == "M"


# ------------------------------------------------------------------ #
# Re-análisis de fotos
# ------------------------------------------------------------------ #
def test_refresh_primary_photo_missing_file_returns_none(cal_session):
    session, _ = cal_session
    entry = {"foto": "ruta_que_no_existe.jpg", "emb_id": None}
    assert CalibrationService(session).refresh_primary_photo(entry) is None


def test_refresh_all_persists_new_attrs(cal_session, monkeypatch):
    session, _ = cal_session
    service = CalibrationService(session)
    monkeypatch.setattr(
        CalibrationService, "refresh_primary_photo",
        lambda self, entry: FaceAttributes(gafas=True, conf={"gafas": 0.88}))
    refreshed = service.refresh_all()
    assert refreshed == 2

    session.expire_all()
    entries = service.collect()
    assert all(e["attrs"].gafas and e["attrs"].conf == {"gafas": 0.88}
               for e in entries)