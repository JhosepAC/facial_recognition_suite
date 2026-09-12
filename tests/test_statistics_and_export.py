"""
Tests del módulo de Estadísticas y Exportación (Fase 3).
"""
import json
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import pytest

from app.database.base import Base
from app.database.models import FaceEmbedding, Person, Photo, RecognitionEvent
from app.database.repositories.person_repository import PersonRepository
from app.services.export_service import ExportService
from app.services.person_service import PersonService
from app.services.statistics_service import (
    StatisticsService, diff_attribute_fields, present_attribute_fields,
)
from app.vision.face_attributes import FaceAttributes


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


@pytest.fixture()
def populated_session(session):
    """Sesión con personas y eventos de reconocimiento de ejemplo."""
    repo = PersonRepository(session)
    p1 = repo.add(Person(nombre="Ana", apellidos="Gomez", empresa="ACME", departamento="IT"))
    p2 = repo.add(Person(nombre="Luis", apellidos="Ruiz", empresa="ACME", departamento="Ventas"))
    p3 = repo.add(Person(nombre="Eva", apellidos="Diaz", empresa="Globex", departamento="IT"))
    session.commit()

    now = datetime.utcnow()
    events = [
        RecognitionEvent(origen="webcam", person_uuid=p1.uuid, confianza=92.0, distancia=0.1, fecha=now),
        RecognitionEvent(origen="webcam", person_uuid=None, confianza=10.0, distancia=0.9, fecha=now),
        RecognitionEvent(origen="video", person_uuid=p2.uuid, confianza=81.0, distancia=0.2,
                          fecha=now - timedelta(days=1)),
        RecognitionEvent(origen="imagen", person_uuid=p3.uuid, confianza=77.5, distancia=0.25,
                          fecha=now - timedelta(days=2)),
    ]
    session.add_all(events)
    session.commit()
    return session, (p1, p2, p3)


# ------------------------------------------------------------------ #
# Fase 5 (M9/T1): WAL y respaldo consistente en ese modo
# ------------------------------------------------------------------ #
def test_wal_mode_is_applied(tmp_path):
    from sqlalchemy import create_engine

    from app.database.session import set_wal_mode

    engine = create_engine(f"sqlite:///{tmp_path / 'wal.db'}")
    set_wal_mode(engine)
    with engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
    assert mode == "wal"


def test_backup_under_wal_is_consistent(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database.session import set_wal_mode

    engine = create_engine(f"sqlite:///{tmp_path / 'live.db'}")
    Base.metadata.create_all(engine)
    set_wal_mode(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    repo = PersonRepository(s)
    repo.add(Person(nombre="Ana", apellidos="Gomez"))
    s.commit()

    backup_path = tmp_path / "backup.db"
    src = sqlite3.connect(str(tmp_path / "live.db"), timeout=30)
    dst = sqlite3.connect(str(backup_path), timeout=30)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()

    probe = sqlite3.connect(str(backup_path), timeout=30)
    try:
        assert probe.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert probe.execute("SELECT count(*) FROM persons").fetchone()[0] == 1
    finally:
        probe.close()
    s.close()


# ------------------------------------------------------------------ #
# StatisticsService
# ------------------------------------------------------------------ #
def test_summary_counts(populated_session):
    session, _ = populated_session
    summary = StatisticsService(session).summary_counts()

    assert summary["total_personas"] == 3
    assert summary["total_eventos"] == 4
    assert summary["eventos_match"] == 3
    assert summary["tasa_reconocimiento_pct"] == pytest.approx(75.0)
    assert summary["confianza_promedio"] is not None
    # M8: extremos de confianza por agregados SQL (matchs: 92.0, 81.0, 77.5)
    assert summary["confianza_minima"] == pytest.approx(77.5)
    assert summary["confianza_maxima"] == pytest.approx(92.0)
    # M5: tasa desglosada por origen (webcam 1/2=50%, video e imagen 100%)
    por_origen = summary["tasa_reconocimiento_por_origen"]
    assert por_origen["webcam"] == {"eventos": 2, "match": 1, "tasa": pytest.approx(50.0)}
    assert por_origen["video"] == {"eventos": 1, "match": 1, "tasa": 100.0}
    assert por_origen["imagen"] == {"eventos": 1, "match": 1, "tasa": 100.0}


def test_build_export_name_is_unique():
    from app.services.export_service import build_export_name

    first = build_export_name("personas", "csv")
    second = build_export_name("personas", "csv")
    assert first != second  # B2: dos exportaciones el mismo segundo no colisionan


def test_summary_counts_empty_db(session):
    summary = StatisticsService(session).summary_counts()
    assert summary["total_personas"] == 0
    assert summary["total_eventos"] == 0
    assert summary["tasa_reconocimiento_pct"] == 0.0
    assert summary["tasa_reconocimiento_por_origen"] == {}
    assert summary["confianza_promedio"] is None


def test_distribution_by_field(populated_session):
    session, _ = populated_session
    df = StatisticsService(session).distribution_df("empresa")
    acme_row = df[df["empresa"] == "ACME"].iloc[0]
    assert acme_row["total"] == 2


def test_distribution_rejects_unknown_field(populated_session):
    session, _ = populated_session
    with pytest.raises(ValueError):
        StatisticsService(session).distribution_df("campo_inexistente")


def test_recognitions_by_origin(populated_session):
    session, _ = populated_session
    df = StatisticsService(session).recognitions_by_origin_df()
    origenes = dict(zip(df["origen"], df["total"]))
    assert origenes == {"webcam": 2, "video": 1, "imagen": 1}


def test_confidence_values_only_matches(populated_session):
    session, _ = populated_session
    values = StatisticsService(session).confidence_values(only_matches=True)
    assert len(values) == 3  # excluye el evento sin persona_uuid
    assert all(v > 0 for v in values)


def test_charts_render_without_error(populated_session):
    """No valida el contenido visual, solo que cada gráfico se construye sin excepciones."""
    import matplotlib.pyplot as plt

    session, _ = populated_session
    stats = StatisticsService(session)

    figs = [
        stats.chart_persons_growth(),
        stats.chart_daily_activity(30),
        stats.chart_confidence_distribution(),
        stats.chart_distribution_by_field("empresa", "Personas por empresa"),
        stats.chart_recognitions_by_origin(),
        stats.chart_attributes_distribution(),
    ]
    for fig in figs:
        assert fig is not None
        assert len(fig.axes) >= 1
        plt.close(fig)


def test_charts_render_on_empty_db(session):
    """Los gráficos deben degradarse con gracia (mensaje 'sin datos'), no fallar, en BD vacía."""
    import matplotlib.pyplot as plt

    stats = StatisticsService(session)
    figs = [
        stats.chart_persons_growth(),
        stats.chart_daily_activity(30),
        stats.chart_confidence_distribution(),
        stats.chart_recognitions_by_origin(),
        stats.chart_attributes_distribution(),
    ]
    for fig in figs:
        assert fig is not None
        plt.close(fig)


# ------------------------------------------------------------------ #
# Análisis facial extendido (distribución y utilidades puras)
# ------------------------------------------------------------------ #
@pytest.fixture()
def attr_session(session):
    """Personas con foto principal y embedding con atributos faciales."""
    repo = PersonRepository(session)
    p1 = repo.add(Person(nombre="Ana", apellidos="Gomez"))
    p2 = repo.add(Person(nombre="Luis", apellidos="Ruiz"))
    session.flush()
    photo1 = Photo(person_uuid=p1.uuid, file_path="a.jpg", thumbnail_path="a_t.jpg",
                   es_principal=True, calidad_score=80)
    photo2 = Photo(person_uuid=p2.uuid, file_path="b.jpg", thumbnail_path="b_t.jpg",
                   es_principal=True, calidad_score=90)
    session.add_all([photo1, photo2])
    session.flush()

    emb1 = FaceEmbedding(
        person_uuid=p1.uuid, photo_id=photo1.id, vector=b"\x00" * 8, dim=512,
        facial_attributes=json.dumps(
            FaceAttributes(gafas=True, sonrisa=True, ojos_abiertos=True).to_dict()),
    )
    emb2 = FaceEmbedding(
        person_uuid=p2.uuid, photo_id=photo2.id, vector=b"\x00" * 8, dim=512,
        facial_attributes=json.dumps(FaceAttributes(mascarilla=True).to_dict()),
    )
    session.add_all([emb1, emb2])
    session.commit()
    return session, (p1, p2)


def test_attributes_distribution_df_counts(attr_session):
    session, _ = attr_session
    df = StatisticsService(session).attributes_distribution_df()
    counts = dict(zip(df["atributo"], df["personas"]))
    assert counts["gafas"] == 1
    assert counts["sonrisa"] == 1
    assert counts["mascarilla"] == 1
    assert counts["barba"] == 0


def test_attributes_distribution_df_empty(session):
    df = StatisticsService(session).attributes_distribution_df()
    assert df["personas"].sum() == 0


def test_chart_attributes_distribution_renders(attr_session):
    import matplotlib.pyplot as plt

    session, _ = attr_session
    fig = StatisticsService(session).chart_attributes_distribution()
    assert fig is not None and len(fig.axes) >= 1
    plt.close(fig)


def test_chart_attributes_distribution_empty(session):
    import matplotlib.pyplot as plt

    fig = StatisticsService(session).chart_attributes_distribution()
    assert fig is not None
    plt.close(fig)


def test_present_attribute_fields_helper():
    attrs = FaceAttributes(gafas=True, mascarilla=True)
    assert set(present_attribute_fields(attrs)) == {"gafas", "mascarilla"}
    assert present_attribute_fields(None) == []


def test_diff_attribute_fields_helper():
    live = FaceAttributes(gafas=False, sonrisa=True, ojos_abiertos=True)
    stored = FaceAttributes(gafas=True, sonrisa=True)
    fields = diff_attribute_fields(live, stored)
    assert "gafas" in fields
    assert "sonrisa" not in fields
    assert diff_attribute_fields(live, None) == []
    assert diff_attribute_fields(None, stored) == []


# ------------------------------------------------------------------ #
# Búsqueda por atributo facial (PersonService.search)
# ------------------------------------------------------------------ #
def test_search_by_attribute_present(attr_session):
    session, (p1, p2) = attr_session
    with_glasses = PersonService(session).search("", attrs=["gafas"])
    assert [p.uuid for p in with_glasses] == [p1.uuid]
    with_mask = PersonService(session).search("", attrs=["mascarilla"])
    assert [p.uuid for p in with_mask] == [p2.uuid]
    assert PersonService(session).search("", attrs=["barba"]) == []


def test_search_by_attribute_absent(attr_session):
    session, (p1, p2) = attr_session
    no_beard = PersonService(session).search("", excl_attrs=["barba"])
    assert {p.uuid for p in no_beard} == {p1.uuid, p2.uuid}


def test_search_by_attribute_combined(attr_session):
    session, (p1, p2) = attr_session
    result = PersonService(session).search(
        "", attrs=["gafas"], excl_attrs=["barba"])
    assert [p.uuid for p in result] == [p1.uuid]
    # "sin gafas" deja fuera a Ana (que las lleva) y queda solo Luis
    assert [p.uuid for p in PersonService(session).search(
        "", excl_attrs=["gafas"])] == [p2.uuid]


def test_search_by_attribute_without_analysis_excluded(session):
    repo = PersonRepository(session)
    repo.add(Person(nombre="Sin", apellidos="Datos"))
    session.commit()
    # Nadie tiene análisis facial -> el filtro por ausencia no debe devolver a nadie
    assert PersonService(session).search("", excl_attrs=["barba"]) == []


def test_search_ignores_attribute_filter_when_untouched(attr_session):
    session, (p1, p2) = attr_session
    all_persons = PersonService(session).search("")
    assert {p.uuid for p in all_persons} == {p1.uuid, p2.uuid}


# ------------------------------------------------------------------ #
# ExportService — tabular (CSV / Excel / JSON)
# ------------------------------------------------------------------ #
@pytest.mark.parametrize("fmt,ext", [("csv", "csv"), ("excel", "xlsx"), ("json", "json")])
def test_export_persons_all_formats(populated_session, tmp_path, fmt, ext):
    session, _ = populated_session
    path = str(tmp_path / f"personas.{ext}")

    count = ExportService(session).export_persons(path, fmt)
    assert count == 3

    if fmt == "csv":
        df = pd.read_csv(path)
    elif fmt == "excel":
        df = pd.read_excel(path)
    else:
        df = pd.read_json(path)

    assert len(df) == 3
    assert "nombre" in df.columns
    assert "empresa" in df.columns
    for field in ("gafas", "mascarilla", "barba", "bigote", "sonrisa", "ojos_abiertos"):
        assert field in df.columns


def test_export_recognition_events(populated_session, tmp_path):
    session, _ = populated_session
    path = str(tmp_path / "eventos.csv")

    count = ExportService(session).export_recognition_events(path, "csv")
    assert count == 4

    df = pd.read_csv(path)
    assert len(df) == 4
    assert set(df["origen"].unique()) <= {"webcam", "video", "imagen"}


def test_export_unsupported_format_raises(populated_session, tmp_path):
    session, _ = populated_session
    with pytest.raises(ValueError):
        ExportService(session).export_persons(str(tmp_path / "x.xml"), "xml")


# ------------------------------------------------------------------ #
# ExportService — PDF
# ------------------------------------------------------------------ #
def test_export_statistics_pdf(populated_session, tmp_path):
    session, _ = populated_session
    path = str(tmp_path / "reporte.pdf")

    ExportService(session).export_statistics_pdf(path, days=30)

    with open(path, "rb") as f:
        header = f.read(5)
    assert header == b"%PDF-"
    assert (tmp_path / "reporte.pdf").stat().st_size > 1000


def test_export_statistics_pdf_empty_db(session, tmp_path):
    """El reporte debe generarse igual (con gráficos vacíos) aunque no haya datos."""
    path = str(tmp_path / "reporte_vacio.pdf")
    ExportService(session).export_statistics_pdf(path, days=30)
    with open(path, "rb") as f:
        assert f.read(5) == b"%PDF-"


# ------------------------------------------------------------------ #
# ExportService — respaldo SQLite
# ------------------------------------------------------------------ #
def test_backup_database(populated_session, tmp_path, monkeypatch):
    session, _ = populated_session

    # Aísla el respaldo de la BD real de la app: crea una BD "de producción" de prueba
    source_db = tmp_path / "source.db"
    from sqlalchemy import create_engine
    engine = create_engine(f"sqlite:///{source_db}")
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.exec_driver_sql(
            "INSERT INTO persons (uuid, nombre, apellidos, fecha_creacion, fecha_modificacion) "
            "VALUES ('u1', 'Test', 'User', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )
        conn.commit()

    from app.core.config import settings
    monkeypatch.setattr(settings.database, "path", str(source_db))

    dest_path = str(tmp_path / "backup.db")
    ExportService(session).backup_database(dest_path)

    assert (tmp_path / "backup.db").exists()

    conn = sqlite3.connect(dest_path)
    cur = conn.execute("SELECT nombre, apellidos FROM persons WHERE uuid='u1'")
    row = cur.fetchone()
    conn.close()
    assert row == ("Test", "User")
