"""
alembic/env.py
Alembic migration environment — async-native, SQLAlchemy 2.0.

Reads DATABASE_URL from the environment. Set it before running migrations:

  Windows PowerShell:
    $env:DATABASE_URL = "postgresql+asyncpg://surveillance:2%402serveillance@localhost:5432/surveillance_db"
    alembic upgrade head

  Linux / WSL / Docker:
    export DATABASE_URL="postgresql+asyncpg://surveillance:2%402serveillance@localhost:5432/surveillance_db"
    alembic upgrade head

  Or add it to a .env file and load it via python-dotenv before calling alembic.

Note on the password:
  The raw password is  2@2serveillance
  In a URL DSN the '@' MUST be percent-encoded as %40, giving:
    2%402serveillance
  asyncpg decodes this automatically; no manual unquoting needed.
"""

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# This file lives at backend/alembic/env.py — parents[2] is the repo root
# (surveillance-ai/). Without this, running `alembic` from inside backend/
# fails with ModuleNotFoundError: No module named 'backend', because the
# 'backend' package itself isn't visible from inside its own directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Week 3: import the ORM models so autogenerate can diff against them.
from backend.db.models import Base

# ── Alembic Config object ─────────────────────────────────────────────────────
config = context.config

# Inject DATABASE_URL from environment into the alembic config object at
# runtime so alembic.ini can stay credential-free.
_db_url = os.environ.get("DATABASE_URL")
if not _db_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set.\n"
        "Example:\n"
        "  postgresql+asyncpg://surveillance:2%402serveillance@localhost:5432/surveillance_db\n"
        "Set it in your shell or .env before running alembic commands."
    )
config.set_main_option("sqlalchemy.url", _db_url.replace("%", "%%"))

# Interpret the config file for Python logging (if present).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Target metadata ───────────────────────────────────────────────────────────
# Week 3 change: now points at the real ORM metadata instead of None, so
# `alembic revision --autogenerate` can detect model changes going forward.
target_metadata = Base.metadata


# ── Offline migrations (generates SQL without a live DB connection) ───────────
def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    Useful for generating a SQL script to review before applying.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (connects to DB and applies changes directly) ───────────
def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,  # Week 3+: detect column type changes, not just add/drop
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Create an async engine and run migrations using asyncpg.
    Must use NullPool — connection pooling is managed outside Alembic.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online mode — wraps the async runner in asyncio.run()."""
    asyncio.run(run_async_migrations())


# ── Dispatch ──────────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()