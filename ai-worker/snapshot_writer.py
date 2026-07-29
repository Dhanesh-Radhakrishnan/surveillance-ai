"""
snapshot_writer.py
Week 2 — Task 4: Save a clean snapshot to disk when a person is detected.
Week 3 fix: crop to YOLO bounding box (+15% padding) before writing, so the
VLM sees the person instead of fixating on static background objects
(e.g. an urn/kettle on a counter that appears in every frame).
Week 3 fix #2: enforce a minimum crop size. A person far from the camera
produces a small bbox — 15% padding of a small box is still a small, low-
context crop, and moondream2 collapses into degenerate output ('!!!',
'Unsure', empty response) when given too little to work with. Small/far
detections now get expanded further (still clamped to frame bounds) instead
of just proportionally padded.

Single responsibility: given a frame (+ optional bbox) and camera_id, write
one JPEG to SNAPSHOT_DIR and return its path. Knows nothing about YOLO,
Redis, or capture loops — callers decide WHEN to call this (only on a
qualifying detection, never every frame) and WHAT bbox to pass.
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

# WHY 15%: tight enough to exclude most background, loose enough that the
# VLM still sees full body context (feet, hands) instead of a cropped torso.
BBOX_PADDING_RATIO: float = 0.15

# WHY a floor at all: percentage padding scales with the box, so a small/
# far-away detection still yields a small crop after padding. moondream2
# needs a minimum amount of visual context to produce a confident, non-
# degenerate description regardless of how small the original detection was.
MIN_CROP_WIDTH: int = 320
MIN_CROP_HEIGHT: int = 320


def _pad_and_clamp_box(
    box_xyxy: tuple[float, float, float, float],
    frame_width: int,
    frame_height: int,
    padding_ratio: float = BBOX_PADDING_RATIO,
    min_width: int = MIN_CROP_WIDTH,
    min_height: int = MIN_CROP_HEIGHT,
) -> tuple[int, int, int, int]:
    """
    Expand box_xyxy by padding_ratio on each side, then enforce a minimum
    crop size (centered on the original box), then clamp to frame bounds.

    WHY clamp: a detection near the frame edge, once padded, can produce
    negative coords or coords beyond width/height — cv2 slicing with those
    silently returns an empty/malformed array instead of raising, which is
    worse than an explicit clamp.
    WHEN the min-size floor kicks in: person is far from camera → small
    bbox → without this, crop stays small and low-context even after
    percentage padding.
    """
    x1, y1, x2, y2 = box_xyxy
    box_w = x2 - x1
    box_h = y2 - y1

    pad_x = box_w * padding_ratio
    pad_y = box_h * padding_ratio

    x1 = x1 - pad_x
    y1 = y1 - pad_y
    x2 = x2 + pad_x
    y2 = y2 + pad_y

    # Enforce minimum size, expanding symmetrically around the box's center
    # rather than just growing one edge (keeps the person roughly centered).
    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2
    cur_w = x2 - x1
    cur_h = y2 - y1

    if cur_w < min_width:
        x1 = center_x - min_width / 2
        x2 = center_x + min_width / 2
    if cur_h < min_height:
        y1 = center_y - min_height / 2
        y2 = center_y + min_height / 2

    return (
        int(max(0, x1)),
        int(max(0, y1)),
        int(min(frame_width, x2)),
        int(min(frame_height, y2)),
    )


def _crop_to_box(
    frame: np.ndarray, box_xyxy: tuple[float, float, float, float]
) -> np.ndarray:
    """
    Return the padded crop of *frame* for box_xyxy.
    Falls back to the full frame if the computed crop is degenerate
    (zero-area) — never write an empty image.
    """
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = _pad_and_clamp_box(box_xyxy, w, h)

    if x2 <= x1 or y2 <= y1:
        logger.warning(
            "Degenerate crop box %s on %dx%d frame — falling back to full frame.",
            (x1, y1, x2, y2), w, h,
        )
        return frame

    return frame[y1:y2, x1:x2]


def save_snapshot(
    frame: np.ndarray,
    camera_id: str = config.CAMERA_ID,
    box_xyxy: tuple[float, float, float, float] | None = None,
) -> Path:
    """
    Write *frame* (optionally cropped to box_xyxy) to SNAPSHOT_DIR as a
    timestamped JPEG.

    WHY crop: moondream2 (1.6B params) has no way to distinguish "subject
    of interest" from "everything else in frame" without help — architectural
    cropping is more reliable than prompt instructions on a model this size.
    WHEN: call this only from the detection callback, after confidence
    filtering has already confirmed a qualifying person detection — never
    on every frame (disk I/O + JPEG encode cost adds up on CPU).
    box_xyxy: pass detection.box_xyxy from PersonDetector.detect(). If None,
    the full frame is saved (legacy behaviour — avoid this path going forward).

    Returns the full path so the caller can hand it straight to the
    Redis event publisher (Week 2, Task 5).
    """
    output_frame = _crop_to_box(frame, box_xyxy) if box_xyxy is not None else frame

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
        output_frame,
        [cv2.IMWRITE_JPEG_QUALITY, config.SNAPSHOT_JPEG_QUALITY],
    )
    if not ok:
        # Don't crash the pipeline over a failed write — log and let the
        # caller decide whether to skip publishing this event.
        raise IOError(f"cv2.imwrite failed for {out_path}")

    logger.info(
        "Snapshot saved: %s%s",
        out_path,
        " (cropped)" if box_xyxy is not None else " (full frame — no bbox given)",
    )
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

    # Smoke test without a real YOLO box — just proves crop math works.
    h, w = frame.shape[:2]
    fake_box = (w * 0.3, h * 0.2, w * 0.7, h * 0.9)
    path = save_snapshot(frame, camera_id="cam01_test", box_xyxy=fake_box)
    print(f"Saved (cropped) → {path}")