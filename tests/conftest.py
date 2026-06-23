"""Shared test fixtures.

SAFETY: we repoint ``DATABASE_URL`` at a throwaway temp file *before* importing the
app, so the suite never reads or writes the real ``health.db``. Tests also never make
real network calls to WHOOP / Mill — no real credentials are used anywhere in CI.
"""

import os
import tempfile
from pathlib import Path

# This MUST run before any `from app ...` import: app/db.py builds its engine at
# import time from settings, which read this environment variable.
_TEST_DB = Path(tempfile.gettempdir()) / "health_hub_test.db"
_TEST_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_TEST_DB}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine, init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Create the canonical schema once for the whole test session."""
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)
    _TEST_DB.unlink(missing_ok=True)


@pytest.fixture
def db():
    """A database session bound to the throwaway test database."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client():
    """A TestClient that boots the real app (runs its lifespan / init_db)."""
    from app.main import app

    with TestClient(app) as c:
        yield c
