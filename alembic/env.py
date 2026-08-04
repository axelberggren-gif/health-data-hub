"""Alembic environment.

Two rules make this work with the rest of the project:

1. **The URL comes from `Settings`** (env / `.env`) unless a caller sets `sqlalchemy.url`
   explicitly — so `alembic upgrade head` targets whatever the app targets, and no
   connection string lives in a tracked file.
2. **`Base.metadata` is the target**, imported through `app.models`, so `--autogenerate`
   sees every canonical table.

SQLite can't `ALTER` most things, so `render_as_batch=True` lets future revisions rewrite
tables transparently on the default local database.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import models  # noqa: F401  (registers the canonical tables on Base.metadata)
from app.config import get_settings
from app.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# `-x db_url=…` wins, then an explicitly set sqlalchemy.url, then app settings.
_x_args = context.get_x_argument(as_dictionary=True)
_url = _x_args.get("db_url") or config.get_main_option("sqlalchemy.url") or ""
config.set_main_option("sqlalchemy.url", _url or get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (``alembic upgrade head --sql``)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
