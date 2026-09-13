"""
backend/db/session.py
Week 4 — Task 4 prerequisite: async engine + session DI for FastAPI routes.

Single responsibility: own the engine/sessionmaker and expose one
get_db_session() dependency. Routes NEVER instantiate sessions themselves —
they take `db: AsyncSession = Depends(get_db_session)`.

WHY this is separate from ai-worker/db_writer.py:
  db_writer.py is the Week 3 worker's own engine (different process, no
  FastAPI, no Depends()). Sharing one engine across worker + API would tie
  their lifecycles together for no benefit — two small modules, same DSN
  pattern, is the correct SOLID split here.
"""

import os
from collections.abc import AsyncGenerator
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Config (env-overridable, mirrors ai-worker/config.py defaults) ───────────
POSTGRES_USER = os.environ.get("POSTGRES_USER", "")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "")
POSTGRES_HOST: str = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT: int = int(os.environ.get("POSTGRES_PORT", "5432"))

_DATABASE_URL = (
    f"postgresql+asyncpg://{quote_plus(POSTGRES_USER)}:"
    f"{quote_plus(POSTGRES_PASSWORD)}@"
    f"{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# ── Engine + sessionmaker (created once at import, never per-request) ───────
# pool_pre_ping=True: catches stale connections after Postgres restarts —
# cheap check, avoids a whole request failing on a dead pooled connection.
_engine = create_async_engine(_DATABASE_URL, pool_pre_ping=True)
_SessionFactory = async_sessionmaker(_engine, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency — yields one AsyncSession per request.

    WHEN: every route that touches the DB takes
      `db: AsyncSession = Depends(get_db_session)`
    WHY yield (not return): guarantees the session is closed after the
    response is built, even if the route raises — same try/finally
    discipline as VideoCapture.release() elsewhere in this codebase.
    """
    async with _SessionFactory() as session:
        yield session


async def dispose_engine() -> None:
    """Call on FastAPI shutdown — releases the connection pool cleanly."""
    await _engine.dispose()
