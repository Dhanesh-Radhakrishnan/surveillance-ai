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

Auto-generate behaviour:
  When models are added in Week 3+, import the SQLAlchemy Base here so
  autogenerate can diff the schema:

    from backend.db.models import Base          # add this import
    target_metadata = Base.metadata             # replace None below
"""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

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
# Set to Base.metadata once SQLAlchemy models are defined (Week 3).
# Until then, autogenerate will produce empty migrations — which is correct
# for W1T7: we just want to confirm Alembic wires up and connects cleanly.
#
# Week 3 change:
#   from backend.db.models import Base
#   target_metadata = Base.metadata
target_metadata = None


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
        # compare_type=True  ← uncomment in Week 3+ to detect column type changes
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
