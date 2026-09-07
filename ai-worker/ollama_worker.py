"""
ollama_worker.py
Week 3 — Task 3 + 7: Async Redis worker — dequeue → load snapshot → send to Ollama.
Week 4 — Task 6: after a successful DB write, broadcast the event payload on
the same Redis pub/sub channel ws_events.py subscribes to. This is the only
publisher for that channel — ws_events.py just relays.

Single responsibility: pull DetectionEvents off the Redis queue Week 2 built,
load the referenced snapshot from disk, and get a description back from
moondream2. Does NOT touch PostgreSQL directly — that's db_writer.py, wired in
separately so this module stays testable in isolation (SOLID).

Run:
    python ollama_worker.py
"""

import asyncio
import base64
import gc
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import redis.asyncio as aioredis
from ollama import AsyncClient
from redis.exceptions import RedisError

import config
import db_writer

# ai-worker/ and backend/ are sibling top-level dirs — mirrors db_writer.py's fix.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.constants import EVENTS_CHANNEL

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ollama_worker")

DESCRIPTION_PROMPT = (
    "You are reviewing a single security camera snapshot. "
    "In one sentence of 15 words or fewer, describe the person: "
    "their approximate action and location in frame (e.g. 'walking near front door', "
    "'standing by driveway'). "
    "Ignore pets, vehicles, shadows, reflections, and lighting changes — do not mention them. "
    "If you cannot clearly identify a person, start your reply with 'Uncertain:' "
    "followed by the briefest reason."
)

OLLAMA_GENERATE_OPTIONS: dict = {
    "temperature": 0.5,
    "top_p": 0.9,
    "repeat_penalty": 1.3,
    "num_predict": 40,
}


@dataclass
class AnalysisResult:
    """What db_writer needs to write a SecurityEvent row."""
    camera_id: str
    snapshot_path: str
    confidence: float
    timestamp: str
    ai_description: str | None  # None if Ollama failed or snapshot missing


class OllamaWorker:
    """
    WHY a class (not a bare loop): holds long-lived Redis + Ollama clients so
    we don't reconnect per event — matches the pattern in redis_publisher.py.
    """

    def __init__(
        self,
        redis_url: str = config.REDIS_URL,
        ollama_host: str = config.OLLAMA_BASE_URL,
        model: str = config.OLLAMA_MODEL,
    ) -> None:
        self._redis = aioredis.from_url(redis_url, socket_timeout=5.0)
        self._ollama = AsyncClient(host=ollama_host)
        self._model = model
        self._queue_key = config.REDIS_QUEUE_KEY
        logger.info("OllamaWorker ready — queue=%r model=%r", self._queue_key, model)

    async def _dequeue(self) -> dict | None:
        try:
            result = await self._redis.blpop(self._queue_key, timeout=5)
        except RedisError:
            logger.exception("Redis BLPOP failed — retrying after backoff.")
            await asyncio.sleep(2)
            return None

        if result is None:
            return None

        _, payload = result
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            logger.error("Malformed event payload dropped: %r", payload)
            return None

    def _load_snapshot_b64(self, snapshot_path: str) -> str | None:
        path = Path(snapshot_path)
        if not path.exists():
            logger.error("Snapshot file missing: %s", path)
            return None
        raw = path.read_bytes()
        return base64.standard_b64encode(raw).decode("utf-8")

    async def _analyze(self, image_b64: str) -> str | None:
        try:
            response = await asyncio.wait_for(
                self._ollama.generate(
                    model=self._model,
                    prompt=DESCRIPTION_PROMPT,
                    images=[image_b64],
                    options=OLLAMA_GENERATE_OPTIONS,
                ),
                timeout=config.OLLAMA_REQUEST_TIMEOUT,
            )
            text = response.response
            if not text:
                logger.warning("Ollama returned an empty response body.")
                return None
            return text.strip()
        except asyncio.TimeoutError:
            logger.error(
                "Ollama request timed out after %ds — description will be null.",
                config.OLLAMA_REQUEST_TIMEOUT,
            )
            return None
        except Exception:
            logger.exception("Ollama analysis failed — description will be null.")
            return None

    async def _broadcast_event(self, written: db_writer.WrittenEvent) -> None:
        """
        W4T6: publish the just-written row on EVENTS_CHANNEL for ws_events.py
        to relay to connected dashboard clients.

        WHY the same field shape as SecurityEventResponse: the dashboard's
        WebSocket handler and its REST /events handler should be able to
        share one deserialization type on the frontend — no reason for the
        live-push payload to look different from the paginated-history payload.

        WHY this never raises: a broadcast is a "nice to have" side effect —
        the event is already durably in Postgres by this point. A Redis
        publish hiccup must not be treated the same as a failed DB write.
        """
        payload = {
            "id": written.id,
            "timestamp": written.timestamp.isoformat(),
            "camera_id": written.camera_id,
            "snapshot_filename": Path(written.image_path).name,
            "ai_description": written.ai_description,
            "confidence": written.confidence,
        }
        try:
            await self._redis.publish(EVENTS_CHANNEL, json.dumps(payload))
            logger.debug("Broadcast event id=%d on %r", written.id, EVENTS_CHANNEL)
        except RedisError:
            logger.exception(
                "WebSocket broadcast publish failed — event id=%d still persisted in DB.",
                written.id,
            )

    async def process_one(self) -> AnalysisResult | None:
        event = await self._dequeue()
        if event is None:
            return None

        image_b64 = self._load_snapshot_b64(event["snapshot_path"])
        description = await self._analyze(image_b64) if image_b64 else None

        result = AnalysisResult(
            camera_id=event["camera_id"],
            snapshot_path=event["snapshot_path"],
            confidence=event["confidence"],
            timestamp=event["timestamp"],
            ai_description=description,
        )

        logger.info(
            "Processed event — camera=%s desc=%r",
            result.camera_id, result.ai_description,
        )

        del image_b64
        gc.collect()

        return result

    async def run_forever(self) -> None:
        logger.info("Worker loop starting — Ctrl+C to stop.")
        try:
            while True:
                try:
                    result = await self.process_one()
                except Exception:
                    logger.exception("Unhandled error in process_one — skipping this cycle.")
                    await asyncio.sleep(1)
                    continue

                if result is not None:
                    written = await db_writer.write_security_event(
                        camera_id=result.camera_id,
                        image_path=result.snapshot_path,
                        ai_description=result.ai_description,
                        confidence=result.confidence,
                    )
                    # W4T6: only broadcast on a confirmed DB write — a None
                    # here means db_writer already logged the failure (W3T7).
                    if written is not None:
                        await self._broadcast_event(written)
        finally:
            await self._redis.aclose()
            await db_writer.dispose_engine()
            logger.info("Redis connection closed.")


if __name__ == "__main__":
    worker = OllamaWorker()
    try:
        asyncio.run(worker.run_forever())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")