"""
db_writer.py
Week 3 — Task 5: Write AnalysisResult rows into PostgreSQL via async SQLAlchemy.
Week 4 — Task 6 update: write_security_event() now returns a WrittenEvent
(id + timestamp + all fields) instead of a bare int. The worker needs the
DB-assigned timestamp (server_default=func.now(), only known after
session.refresh()) to build the WebSocket broadcast payload — returning
just the id would force a second query for no reason.

Single responsibility: own the async engine/session and one insert function.
Knows nothing about Redis or Ollama — ollama_worker.py just calls write_security_event().
"""

import logging
import sys
from dataclasses import dataclass
from datetime import datetime
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


@dataclass
class WrittenEvent:
    """
    What the caller (ollama_worker.py) needs to broadcast over WebSocket
    without re-querying the DB. Mirrors SecurityEventResponse's fields
    (schemas file) so the worker can build that exact JSON shape directly.
    """
    id: int
    timestamp: datetime
    camera_id: str
    image_path: str
    ai_description: str | None
    confidence: float | None


async def write_security_event(
    camera_id: str,
    image_path: str,
    ai_description: str | None,
    confidence: float | None = None,
) -> WrittenEvent | None:
    """
    Insert one SecurityEvent row. Returns a WrittenEvent on success, or None
    on failure.

    WHY never raise: matches W3T7 — a DB failure must not crash the worker loop.
    ai_description=None is valid (Ollama timeout case) — row is still written.

    WHY return WrittenEvent (not just id, W4T6 change): the worker's
    broadcast payload needs `timestamp`, which is server-assigned and only
    known after session.refresh() — this function already does that refresh,
    so handing the full row back avoids a redundant SELECT in the worker.
    """
    try:
        async with _SessionFactory() as session:
            event = SecurityEvent(
                camera_id=camera_id,
                image_path=image_path,
                ai_description=ai_description,
                confidence=confidence,
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            logger.info("SecurityEvent written — id=%d camera=%s", event.id, camera_id)
            return WrittenEvent(
                id=event.id,
                timestamp=event.timestamp,
                camera_id=event.camera_id,
                image_path=event.image_path,
                ai_description=event.ai_description,
                confidence=event.confidence,
            )
    except Exception:
        logger.exception("DB write failed — event dropped (camera=%s, path=%s)", camera_id, image_path)
        return None


async def dispose_engine() -> None:
    """Call on worker shutdown — releases the connection pool cleanly."""
    await _engine.dispose()