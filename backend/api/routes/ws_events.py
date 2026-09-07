"""
backend/api/routes/ws_events.py
Week 4 — Task 5: WebSocket endpoint for live event broadcast.
Week 4 — Task 6 refactor: EVENTS_CHANNEL moved to backend/constants.py so
ai-worker/ollama_worker.py (a separate OS process with no FastAPI install
requirement) doesn't need to import this fastapi-heavy module just to read
one string constant.

Single responsibility: accept WebSocket connections and relay messages
published on a Redis pub/sub channel to each connected client. Knows
nothing about SQLAlchemy, YOLO, or Ollama — the Week 3/4 worker (W4T6)
is the only publisher; this file only relays.

WHY Redis pub/sub (not an in-process list of WebSocket connections):
  ollama_worker.py runs as a SEPARATE OS process from this FastAPI app —
  they share no Python memory. An in-process ConnectionManager here would
  never see events published by the worker process. Redis pub/sub is the
  one channel both processes already share (same Redis instance as the
  detection queue — just PUBLISH/SUBSCRIBE instead of RPUSH/BLPOP).
"""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.constants import EVENTS_CHANNEL
from backend.db.redis_session import get_redis_connection

logger = logging.getLogger("backend.api.ws_events")

router = APIRouter(tags=["websocket"])


async def _watch_for_disconnect(websocket: WebSocket) -> None:
    """
    WHY this exists: the dashboard client never SENDS text on this socket —
    it only receives. But without something awaiting websocket.receive(),
    FastAPI/Starlette won't surface a client-initiated close (browser tab
    closed, network drop) until we try to send and fail. This task's only
    job is to raise WebSocketDisconnect promptly when that happens.
    """
    while True:
        await websocket.receive_text()


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    """
    WHEN: React dashboard (W5T3) opens this on mount and reconnects on drop.
    WHAT: subscribes to EVENTS_CHANNEL on the shared Redis client and
    forwards every published message (already-JSON text from the worker)
    to this one client until it disconnects.
    """
    await websocket.accept()

    redis_client = await get_redis_connection()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(EVENTS_CHANNEL)
    logger.info("WebSocket client connected — subscribed to %r", EVENTS_CHANNEL)

    disconnect_task = asyncio.create_task(_watch_for_disconnect(websocket))

    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message is not None:
                data = message["data"]
                payload = data.decode("utf-8") if isinstance(data, bytes) else data
                await websocket.send_text(payload)

            if disconnect_task.done():
                disconnect_task.result()
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
    finally:
        disconnect_task.cancel()
        await pubsub.unsubscribe(EVENTS_CHANNEL)
        await pubsub.aclose()