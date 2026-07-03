"""
redis_publisher.py
Week 2 — Task 5: Push detection event metadata to Redis queue.

Single responsibility: serialize a DetectionEvent and RPUSH it onto Redis.
Knows nothing about YOLO, OpenCV, or snapshots — caller builds the event,
this module just ships it.

Connection failures must never crash the capture loop — log and continue.
"""

import gc
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import redis
from redis.exceptions import RedisError

import config

logger = logging.getLogger("redis_publisher")


@dataclass
class DetectionEvent:
    """One person-detection event, ready for Redis + later DB insertion."""
    timestamp: str        # ISO-8601 UTC
    camera_id: str
    snapshot_path: str
    confidence: float


class RedisEventPublisher:
    """
    Thin wrapper around a sync Redis client.

    WHY sync (not async) here: this runs inside the sync capture_loop
    callback (W2T1). Async Redis belongs to the Week 3 worker instead.
    """

    def __init__(self, redis_url: str = config.REDIS_URL) -> None:
        self._client = redis.from_url(redis_url, socket_timeout=3.0)
        self._queue_key = config.REDIS_QUEUE_KEY
        logger.info("RedisEventPublisher ready — queue=%r", self._queue_key)

    def publish(self, event: DetectionEvent) -> bool:
        """
        RPUSH the event as JSON. Returns True on success, False on failure.

        WHEN: call once per qualifying detection, after snapshot_writer
        has already saved the frame — never before.
        """
        payload = None
        try:
            payload = json.dumps(asdict(event))
            self._client.rpush(self._queue_key, payload)
            logger.debug("Event published: %s", event.snapshot_path)
            return True
        except RedisError:
            logger.exception("Redis publish failed — event dropped: %s", event)
            return False
        finally:
            del payload
            gc.collect()


def build_event(camera_id: str, snapshot_path: str, confidence: float) -> DetectionEvent:
    """Helper: stamp current UTC time and build a DetectionEvent."""
    return DetectionEvent(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        camera_id=camera_id,
        snapshot_path=str(snapshot_path),
        confidence=confidence,
    )


# ── Standalone smoke test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    publisher = RedisEventPublisher()
    test_event = build_event("cam01_test", "/tmp/test_snap.jpg", 0.91)
    ok = publisher.publish(test_event)
    print("Published ✓" if ok else "Publish FAILED — check Redis is running")