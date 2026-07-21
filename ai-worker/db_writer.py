"""
db_writer.py
Week 3 — Task 5: Write AnalysisResult rows into PostgreSQL via async SQLAlchemy.

Single responsibility: own the async engine/session and one insert function.
Knows nothing about Redis or Ollama — ollama_worker.py just calls write_security_event().
"""

import logging
import sys
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# ai-worker/ and backend/ are sibling top-level dirs — mirrors alembic/env.py's fix.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.db.models import SecurityEvent

import config

logger = logging.getLogger("db_writer")

# ── Engine (created once at import — never per-call, mirrors PersonDetector pattern) ──
_DATABASE_URL = (
    f"postgresql+asyncpg://{config.POSTGRES_USER}:"
    f"{quote_plus(config.POSTGRES_PASSWORD)}@"
    f"{config.POSTGRES_HOST}:{config.POSTGRES_PORT}/{config.POSTGRES_DB}"
)
_engine = create_async_engine(_DATABASE_URL, pool_pre_ping=True)
_SessionFactory = async_sessionmaker(_engine, expire_on_commit=False)


async def write_security_event(
    camera_id: str,
    image_path: str,
    ai_description: str | None,
) -> int | None:
    """
    Insert one SecurityEvent row. Returns the new row's id, or None on failure.

    WHY never raise: matches W3T7 — a DB failure must not crash the worker loop.
    ai_description=None is valid (Ollama timeout case) — row is still written.
    """
    try:
        async with _SessionFactory() as session:
            event = SecurityEvent(
                camera_id=camera_id,
                image_path=image_path,
                ai_description=ai_description,
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            logger.info("SecurityEvent written — id=%d camera=%s", event.id, camera_id)
            return event.id
    except Exception:
        logger.exception("DB write failed — event dropped (camera=%s, path=%s)", camera_id, image_path)
        return None


async def dispose_engine() -> None:
    """Call on worker shutdown — releases the connection pool cleanly."""
    await _engine.dispose()