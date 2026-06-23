"""Database engine, session factory, and declarative base.

SQLite for local dev (``check_same_thread`` relaxed); swap to Postgres by
setting ``DATABASE_URL``. For production schema management use Alembic; the
``init_db`` helper below is a dev convenience that calls ``create_all``.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # Import models so they register on Base.metadata, then create tables.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
