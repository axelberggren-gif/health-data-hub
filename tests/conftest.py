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
from sqlalchemy import text  # noqa: E402

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


#: Tables whose rows are keyed by *date* rather than by a per-test external id. Distinct
#: `source_external_id`s (the usual house rule) can't isolate tests that ask "what happened
#: on day D" or "what is the 30-day baseline" — another test's rows for the same day would
#: be picked up. Tests that query by day empty these first via the `clean_db` fixture.
_DAY_SCOPED_TABLES = (
    "sleep_stage",
    "sleep_session",
    "recovery_daily",
    "cycle_day",
    "workout",
    "air_quality_reading",
)


@pytest.fixture
def clean_db(db):
    """A session with the day-scoped tables emptied, before and after the test."""

    def _wipe() -> None:
        for table in _DAY_SCOPED_TABLES:
            db.execute(text(f"DELETE FROM {table}"))  # noqa: S608 (fixed table names)
        db.commit()

    _wipe()
    yield db
    _wipe()
