"""
stage1_pipeline.py
Week 3 — Task 8 prerequisite: wire Stage 1 together.

Single responsibility: connect the four independent Week 2 modules into one
running pipeline. Contains NO detection/snapshot/publish logic itself —
that all still lives in detector.py / snapshot_writer.py / redis_publisher.py.
This file only orchestrates the call order + per-camera cooldown.

Run:
    python stage1_pipeline.py                  # default webcam
    python stage1_pipeline.py /tmp/clip.mp4     # video file
"""

import logging
import sys
import time
from pathlib import Path

import numpy as np

import config
from detector import PersonDetector
from snapshot_writer import save_snapshot
from redis_publisher import RedisEventPublisher, build_event
from capture_loop import run_capture_loop

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("stage1_pipeline")

# Minimum seconds between two published events for the SAME camera.
# WHY: at CAPTURE_FPS=10, a person standing in frame for 3s would otherwise
# fire ~30 snapshot+publish events instead of 1.
EVENT_COOLDOWN_SECONDS: float = float(
    __import__("os").environ.get("EVENT_COOLDOWN_SECONDS", "5.0")
)


class Stage1Pipeline:
    """
    Holds long-lived detector + publisher instances (loaded once, not per-frame)
    and per-camera cooldown state.
    """

    def __init__(self) -> None:
        self._detector = PersonDetector()
        self._publisher = RedisEventPublisher()
        self._last_event_time: dict[str, float] = {}

    def _cooldown_active(self, camera_id: str) -> bool:
        last = self._last_event_time.get(camera_id, 0.0)
        return (time.monotonic() - last) < EVENT_COOLDOWN_SECONDS

    def on_frame(self, frame: np.ndarray, frame_index: int, camera_id: str) -> None:
        """
        Callback handed to run_capture_loop. Runs on every captured frame —
        must stay cheap. YOLO inference is the expensive part; everything
        after it only runs when a qualifying detection exists.
        """
        detections = self._detector.detect(frame)
        if not detections:
            return

        if self._cooldown_active(camera_id):
            logger.debug("Detection on %s suppressed — within cooldown window.", camera_id)
            return

        # Highest-confidence detection wins if multiple people are in frame —
        # avoids publishing N events for one qualifying frame.
        best = max(detections, key=lambda d: d.confidence)

        # Crop to the detected person + 15% padding on each side, clamped to
        # frame bounds. WHY: removes background objects (urn/kettle/curtain)
        # from what moondream2 sees, instead of relying on prompt instructions
        # to ignore them — small VLMs handle negation unreliably.
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = best.box_xyxy
        pad_x, pad_y = (x2 - x1) * 0.15, (y2 - y1) * 0.15
        x1 = max(0, int(x1 - pad_x))
        y1 = max(0, int(y1 - pad_y))
        x2 = min(w, int(x2 + pad_x))
        y2 = min(h, int(y2 + pad_y))
        cropped = frame[y1:y2, x1:x2]

        try:
            snapshot_path = save_snapshot(cropped, camera_id=camera_id)
        except IOError:
            logger.exception("Snapshot write failed — event dropped for this detection.")
            return

        # NOTE: this block must stay at method level (8-space indent), not
        # nested inside the try/except above — it needs to run on every
        # successful snapshot, not just the exception path.
        event = build_event(
            camera_id=camera_id,
            snapshot_path=str(snapshot_path),
            confidence=best.confidence,
        )
        ok = self._publisher.publish(event)
        if ok:
            self._last_event_time[camera_id] = time.monotonic()
            logger.info(
                "Event published — camera=%s conf=%.2f snapshot=%s",
                camera_id, best.confidence, snapshot_path,
            )


def main() -> None:
    source: int | str = config.CAMERA_SOURCE
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        source = int(arg) if arg.isdigit() else arg
        if isinstance(source, str) and not Path(source).exists():
            sys.exit(f"[ERROR] File not found: {source}")

    pipeline = Stage1Pipeline()
    logger.info(
        "Stage 1 pipeline starting — camera_id=%r cooldown=%.1fs — Ctrl+C to stop.",
        config.CAMERA_ID, EVENT_COOLDOWN_SECONDS,
    )
    try:
        run_capture_loop(source=source, on_frame=pipeline.on_frame)
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    except RuntimeError as exc:
        sys.exit(f"[ERROR] {exc}")


if __name__ == "__main__":
    main()