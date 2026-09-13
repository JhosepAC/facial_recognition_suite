"""SQLAlchemy engine and session factory.

Typical usage:
    from app.database.session import get_session, init_db

    init_db()
    with get_session() as session:
        session.add(person)
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
from app.database import models  # noqa: F401  (register models in Base.metadata)

_db_path = settings.resolve_path(settings.database.path)
_db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{_db_path}",
    echo=settings.database.echo_sql,
    connect_args={"check_same_thread": False},
)

# On each connection, set a blocking timeout (background threads — webcam/video
# — compete with the GUI) and synchronous=NORMAL, which with WAL guarantees
# consistency without sacrificing performance.
@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """Apply SQLite pragmas for concurrency and durability.

    Args:
        dbapi_connection: Raw DB-API connection.
        _connection_record: SQLAlchemy connection record (unused).
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def set_wal_mode(target_engine) -> None:
    """Enable WAL journal mode on a SQLite engine (persistent per file).

    WAL allows concurrent readers while writing (ideal with background workers)
    and reduces corruption risk on power loss. Applied in ``init_db`` for the
    real DB and in tests on temporary engines.

    Args:
        target_engine: SQLAlchemy engine to configure.
    """
    with target_engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _add_columns_if_missing(table: str, columns: dict[str, str]) -> None:
    """Lightweight migration: add missing columns to an existing table.

    Args:
        table: Table name.
        columns: Mapping of column name to SQL definition.
    """
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
                logger.info("Migration: column {}.{} added", table, name)


def init_db() -> None:
    """Create tables if missing and run lightweight migrations. Idempotent."""
    Base.metadata.create_all(bind=engine)
    set_wal_mode(engine)
    # Migrations for existing SQLite databases (create_all does not alter old tables).
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
    logger.info("Database initialized at: {}", _db_path)


@contextmanager
def get_session() -> Iterator[Session]:
    """Provide a transactional scope for database operations.

    Yields:
        SQLAlchemy session with automatic commit/rollback handling.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
