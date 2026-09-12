"""
Motor y fábrica de sesiones de SQLAlchemy.

Uso típico:
    from app.database.session import get_session, init_db

    init_db()
    with get_session() as session:
        session.add(persona)
        session.commit()
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import inspect as sqla_inspect

from app.core.config import settings
from app.core.logger import logger
from app.database.base import Base
from app.database import models  # noqa: F401  (registra los modelos en Base.metadata)

_db_path = settings.resolve_path(settings.database.path)
_db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{_db_path}",
    echo=settings.database.echo_sql,
    connect_args={"check_same_thread": False},
)

# M9: en cada conexión, un timeout de espera ante bloqueos (los hilos de
# fondo —webcam/video— compiten con la GUI) y synchronous=NORMAL, que con WAL
# garantiza consistencia sin sacrificar rendimiento.
@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def set_wal_mode(target_engine) -> None:
    """Activa el journal WAL en un motor SQLite (persistente por archivo).

    WAL permite lectores concurrentes mientras se escribe (ideal con los
    workers de fondo) y reduce el riesgo de corrupción por cortes. Se aplica
    en ``init_db`` para la BD real y en los tests sobre motores temporales.
    """
    with target_engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _add_columns_if_missing(table: str, columns: dict[str, str]) -> None:
    """Migración ligera: agrega columnas faltantes a una tabla existente."""
    inspector = sqla_inspect(engine)
    if table not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns(table)}
    with engine.begin() as connection:
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                )
                logger.info("Migración: columna {}.{} añadida", table, name)


def init_db() -> None:
    """Crea las tablas si no existen e incluye migraciones ligeras. Idempotente."""
    Base.metadata.create_all(bind=engine)
    set_wal_mode(engine)
    # Migraciones para bases SQLite existentes (create_all no altera tablas viejas)
    _add_columns_if_missing("recognition_events", {"det_confidence": "FLOAT"})
    _add_columns_if_missing(
        "video_detections",
        {"det_confidence": "FLOAT", "quality_score": "FLOAT",
         "facial_attributes": "TEXT"},
    )
    _add_columns_if_missing("face_embeddings", {"facial_attributes": "TEXT"})
    _add_columns_if_missing(
        "users",
        {"totp_secret": "BLOB", "totp_enabled": "BOOLEAN"},
    )
    logger.info("Base de datos inicializada en: {}", _db_path)


@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
