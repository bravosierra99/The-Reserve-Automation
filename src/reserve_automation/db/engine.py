"""Database engine configuration with SQLite WAL mode."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from .base import Base

# Module-level engine and session factory, initialized by init_db()
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _set_sqlite_pragmas(dbapi_conn, connection_record):
    """Set SQLite pragmas on every new connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def init_db(database_url: str = "sqlite:///data/reserve.db") -> Engine:
    """Initialize the database engine and create tables.

    Idempotent: if already initialized with the same URL, returns the
    existing engine without re-creating it. This is important for tests
    where the root conftest initializes in-memory SQLite and seeds data,
    then the app lifespan calls init_db again.

    Args:
        database_url: SQLAlchemy database URL. Defaults to SQLite file at data/reserve.db.

    Returns:
        The configured SQLAlchemy engine.
    """
    global _engine, _SessionLocal

    # Skip re-initialization if already set up with the same URL
    if _engine is not None and str(_engine.url) == database_url:
        return _engine

    # Ensure the directory exists for file-based SQLite
    if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
        db_path = database_url.replace("sqlite:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # For in-memory SQLite, use StaticPool so all sessions share the same
    # connection (and thus the same database). Without this, each connection
    # gets its own empty in-memory database.
    extra_kwargs = {}
    if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
        extra_kwargs["poolclass"] = NullPool
    if ":memory:" in database_url:
        extra_kwargs["poolclass"] = StaticPool

    _engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
        echo=False,
        **extra_kwargs,
    )

    # Set WAL mode and other pragmas on every connection
    event.listen(_engine, "connect", _set_sqlite_pragmas)

    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    # Import all models to ensure they're registered with Base.metadata
    from . import models as _models  # noqa: F401

    Base.metadata.create_all(bind=_engine)

    _run_migrations(_engine)

    return _engine


def _run_migrations(engine: Engine) -> None:
    """Add columns that may be missing from existing databases."""
    migrations = [
        ("tasting_notes",     "hidden BOOLEAN NOT NULL DEFAULT 0"),
        ("cocktail_tastings", "hidden BOOLEAN NOT NULL DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for table, col_def in migrations:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
                conn.commit()
            except Exception:
                pass  # Column already exists


def get_engine() -> Engine:
    """Get the current engine, raising if not initialized."""
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
