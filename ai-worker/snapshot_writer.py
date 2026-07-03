"""
snapshot_writer.py
Week 2 — Task 4: Save a clean snapshot to disk when a person is detected.

Single responsibility: given a frame + camera_id, write one JPEG to
SNAPSHOT_DIR and return its path. Knows nothing about YOLO, Redis, or
capture loops — callers decide WHEN to call this (only on a qualifying
detection, never every frame).
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

import config

logger = logging.getLogger("snapshot_writer")

# Ensure the output directory exists once at import time, not per-call.
config.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def save_snapshot(frame: np.ndarray, camera_id: str = config.CAMERA_ID) -> Path:
    """
    Write *frame* to SNAPSHOT_DIR as a timestamped JPEG.

    WHY a fresh timestamp per call: filenames double as a natural sort order
    and avoid collisions between rapid consecutive detections.
    WHEN: call this only from the detection callback, after confidence
    filtering has already confirmed a qualifying person detection —
    never on every frame (disk I/O + JPEG encode cost adds up on CPU).

    Returns the full path so the caller can hand it straight to the
    Redis event publisher (Week 2, Task 5).
    """
    timestamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    # Colons are invalid in Windows filenames — sanitize for cross-OS safety
    # since dev happens on Windows but the pipeline deploys inside Linux containers.
    safe_timestamp = timestamp.replace(":", "-")

    filename = config.SNAPSHOT_FILENAME_TEMPLATE.format(
        camera_id=camera_id, timestamp=safe_timestamp
    )
    out_path = config.SNAPSHOT_DIR / filename

    ok = cv2.imwrite(
        str(out_path),
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, config.SNAPSHOT_JPEG_QUALITY],
    )
    if not ok:
        # Don't crash the pipeline over a failed write — log and let the
        # caller decide whether to skip publishing this event.
        raise IOError(f"cv2.imwrite failed for {out_path}")

    logger.info("Snapshot saved: %s", out_path)
    return out_path


# ── Standalone smoke test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    img_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not img_path:
        sys.exit("[ERROR] Usage: python snapshot_writer.py path/to/test_image.jpg")

    frame = cv2.imread(img_path)
    if frame is None:
        sys.exit(f"[ERROR] Could not read image: {img_path}")

    path = save_snapshot(frame, camera_id="cam01_test")
    print(f"Saved → {path}")