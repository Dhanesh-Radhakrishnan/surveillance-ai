"""
backend/db/redis_session.py
Week 4 — Task 4 (closeout): Redis connection DI for FastAPI routes.

Single responsibility: own the shared async Redis client and expose one
get_redis_connection() dependency. Routes NEVER call redis.asyncio.from_url()
themselves — they take `r: aioredis.Redis = Depends(get_redis_connection)`.

WHY this differs from backend/db/session.py's pattern:
  SQLAlchemy AsyncSession is NOT safe to share across concurrent requests —
  each request must get its own session, hence get_db_session() does
  `async with _SessionFactory() as session: yield session` per call.
  redis.asyncio.Redis is different: it already wraps an internal connection
  pool and IS safe to share as a single long-lived instance across concurrent
  requests. Creating a new client per-request would just mean reconnecting
  the pool on every call for no benefit — so this module creates ONE client
  at import time (same lifecycle as db_writer.py's engine and
  redis_publisher.py's client) and yields that same instance every time.

No consumer yet: nothing in Week 4 routes touches Redis today (GET /events
and GET /events/{id} are DB-only). This dependency exists so W4T5 (WebSocket
broadcast), W4T6 (worker push), and W4T7 (queue-depth health check) can wire
in via Depends() immediately instead of each inventing their own connection.
"""

import logging
import os

import redis.asyncio as aioredis

logger = logging.getLogger("backend.db.redis_session")

# ── Config (env-overridable, mirrors ai-worker/config.py's REDIS_URL default) ─
REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# socket_timeout mirrors the ai-worker/ollama_worker.py fix (W3): must exceed
# any blocking call (e.g. BLPOP) issued against this client, or the client
# raises a spurious timeout mid-block. FastAPI routes using this dependency
# for pub/sub or queue-depth checks (LLEN) are quick, non-blocking calls, but
# the same client instance may later be reused for a blocking read — keep
# the value consistent with the rest of the codebase rather than tuning it
# down for the currently-known use cases.
REDIS_SOCKET_TIMEOUT: float = 10.0

# ── Client (created once at import — never per-request) ──────────────────────
_redis_client: aioredis.Redis = aioredis.from_url(
    REDIS_URL, socket_timeout=REDIS_SOCKET_TIMEOUT
)
logger.info("Redis client initialized — url=%r timeout=%.1fs", REDIS_URL, REDIS_SOCKET_TIMEOUT)


async def get_redis_connection() -> aioredis.Redis:
    """
    FastAPI dependency — returns the shared Redis client.

    WHEN: any route or WebSocket handler that needs to publish, subscribe,
    or inspect queue depth takes
      `r: aioredis.Redis = Depends(get_redis_connection)`

    WHY a plain return (not `yield` + cleanup like get_db_session): there is
    no per-call resource to release here — the same pooled client is reused
    for the life of the app process, and is torn down once, at shutdown, via
    dispose_redis().
    """
    return _redis_client


async def dispose_redis() -> None:
    """
    Call on FastAPI shutdown — closes the pooled connection cleanly.
    Mirrors backend/db/session.py's dispose_engine() and
    ollama_worker.py's `await self._redis.aclose()` in its finally block.
    """
    await _redis_client.aclose()
    logger.info("Redis client connection closed.")