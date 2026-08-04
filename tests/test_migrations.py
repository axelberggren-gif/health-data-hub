"""Alembic migration tests (see docs/specs/TEST_SPEC_V1.md, M0).

These run Alembic programmatically against a throwaway SQLite file in ``tmp_path`` —
never the app's database (house rule: tests never touch the real ``health.db``).
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app import models  # noqa: F401  (registers the canonical tables on Base.metadata)
from app.db import Base

REPO_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(url: str) -> Config:
    """An Alembic config pointed at a specific throwaway database."""
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_migrations_recreate_the_schema(tmp_path: Path) -> None:
    """M0-T01: `alembic upgrade head` on an empty DB reproduces `Base.metadata`."""
    url = f"sqlite+pysqlite:///{tmp_path / 'migrated.db'}"

    command.upgrade(_alembic_config(url), "head")

    engine = create_engine(url, future=True)
    try:
        inspector = inspect(engine)
        migrated_tables = {t for t in inspector.get_table_names() if t != "alembic_version"}
        expected_tables = set(Base.metadata.tables)

        assert migrated_tables - expected_tables == set(), "migration creates unknown tables"
        assert expected_tables - migrated_tables == set(), "migration is missing tables"

        for table in sorted(expected_tables):
            migrated_columns = {c["name"] for c in inspector.get_columns(table)}
            expected_columns = {c.name for c in Base.metadata.tables[table].columns}
            assert migrated_columns == expected_columns, f"column drift in {table!r}"
    finally:
        engine.dispose()


def test_migrations_are_reversible(tmp_path: Path) -> None:
    """M0-T01: the initial revision downgrades cleanly back to an empty database."""
    url = f"sqlite+pysqlite:///{tmp_path / 'reversible.db'}"
    cfg = _alembic_config(url)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = create_engine(url, future=True)
    try:
        remaining = {t for t in inspect(engine).get_table_names() if t != "alembic_version"}
        assert remaining == set()
    finally:
        engine.dispose()
