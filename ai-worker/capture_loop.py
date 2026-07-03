"""
capture_loop.py
Week 2 — Task 1: OpenCV VideoCapture loop (webcam or video file).

Single responsibility: open a video source, yield frames at the configured
rate, and guarantee resource release via try/finally.

The frame callback pattern means this module never needs to know about YOLO,
Redis, or snapshots — those concerns are wired in by the caller (Week 2, T2–T5).

Usage (standalone test — no YOLO or Redis required):
    python capture_loop.py                        # default webcam
    python capture_loop.py /tmp/test_clip.mp4     # video file
    CAMERA_SOURCE=1 python capture_loop.py        # second webcam
"""

import gc
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import numpy as np

import config

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("capture_loop")

# Type alias for the per-frame callback signature.
# Receives: (frame: np.ndarray, frame_index: int, camera_id: str) → None
FrameCallback = Callable[[np.ndarray, int, str], None]


# ── VideoCapture helpers ───────────────────────────────────────────────────────

def _open_capture(source: int | str) -> cv2.VideoCapture:
    """
    Open a VideoCapture and raise immediately if it fails.
    Separating this from the loop keeps error messages clear.
    """
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(
            f"Cannot open video source: {source!r}\n"
            "  • Webcam: make sure no other app holds the device.\n"
            "  • File:   check the path exists and codec is installed."
        )
    return cap


def _log_source_info(cap: cv2.VideoCapture, source: int | str) -> None:
    """Log resolution and native FPS of the opened source (informational only)."""
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    native_fps = cap.get(cv2.CAP_PROP_FPS)  # 0.0 for live webcams
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))  # -1 for live webcams

    logger.info("Video source opened: %r", source)
    logger.info("  Resolution : %dx%d", width, height)
    logger.info("  Native FPS : %s", f"{native_fps:.1f}" if native_fps > 0 else "live (webcam)")
    if total_frames > 0:
        logger.info("  Total frames : %d (~%.1fs)", total_frames, total_frames / max(native_fps, 1))


# ── Frame rate governor ────────────────────────────────────────────────────────

class _FPSGovernor:
    """
    Lightweight token-bucket rate limiter.
    Sleeps just long enough to hit the target FPS without busy-waiting.
    """

    def __init__(self, target_fps: int) -> None:
        self._interval = 1.0 / max(target_fps, 1)
        self._last_tick = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_tick
        gap = self._interval - elapsed
        if gap > 0:
            time.sleep(gap)
        self._last_tick = time.monotonic()


# ── Public API ────────────────────────────────────────────────────────────────

def run_capture_loop(
    *,
    source: int | str = config.CAMERA_SOURCE,
    target_fps: int = config.CAPTURE_FPS,
    camera_id: str = config.CAMERA_ID,
    on_frame: FrameCallback,
    max_frames: int = 0,        # 0 = run forever (or until video file ends)
    max_consecutive_errors: int = 10,
) -> None:
    """
    Open *source* and call *on_frame* for every captured frame.

    Parameters
    ----------
    source:
        Webcam index (int) or path to a video file (str / Path).
    target_fps:
        Maximum frames per second to process. Does not affect how the source
        is read — it governs how often we HAND frames to *on_frame*.
    camera_id:
        Logical camera name embedded in snapshot filenames and Redis events.
    on_frame:
        Callable invoked with (frame_bgr, frame_index, camera_id).
        Must be cheap — heavy work (YOLO, snapshot IO) should be dispatched
        asynchronously or done selectively inside the callback.
    max_frames:
        Stop after this many frames. 0 = no limit.
    max_consecutive_errors:
        Abort the loop after this many back-to-back read failures
        (protects against a broken webcam spinning the CPU).
    """
    cap = _open_capture(source)
    governor = _FPSGovernor(target_fps)
    frame_index = 0
    consecutive_errors = 0

    _log_source_info(cap, source)
    logger.info(
        "Capture loop starting — camera_id=%r  target_fps=%d  max_frames=%s",
        camera_id, target_fps, max_frames or "∞",
    )

    try:
        while True:
            governor.wait()

            ok, frame = cap.read()

            if not ok:
                consecutive_errors += 1
                if isinstance(source, str):
                    # Video file reached end-of-file — normal termination.
                    logger.info("End of video file reached after %d frames.", frame_index)
                    break
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(
                        "Read failed %d consecutive times — aborting loop.",
                        consecutive_errors,
                    )
                    break
                logger.warning("Frame read failed (attempt %d/%d) — retrying.",
                               consecutive_errors, max_consecutive_errors)
                time.sleep(0.1)
                continue

            consecutive_errors = 0  # reset on success

            try:
                on_frame(frame, frame_index, camera_id)
            except Exception:
                # Callback errors must not kill the capture loop.
                logger.exception("on_frame callback raised on frame %d — skipping.", frame_index)
            finally:
                # Explicit frame buffer release — critical on long-running hardware.
                del frame
                gc.collect()

            frame_index += 1

            if max_frames and frame_index >= max_frames:
                logger.info("Reached max_frames=%d — stopping loop.", max_frames)
                break

    finally:
        # Guaranteed release even on KeyboardInterrupt or unhandled exception.
        cap.release()
        logger.info("VideoCapture released. Total frames processed: %d", frame_index)


# ── Standalone smoke test ─────────────────────────────────────────────────────

def _passthrough_callback(frame: np.ndarray, idx: int, cam_id: str) -> None:
    """
    Minimal callback used when running this module directly.
    Just logs frame shape — no YOLO, no Redis, no disk I/O.
    """
    h, w = frame.shape[:2]
    if idx % config.CAPTURE_FPS == 0:   # log once per second
        logger.info("Frame %d — %s — shape: %dx%d", idx, cam_id, w, h)


if __name__ == "__main__":
    source: int | str = config.CAMERA_SOURCE
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        source = int(arg) if arg.isdigit() else arg
        if isinstance(source, str) and not Path(source).exists():
            sys.exit(f"[ERROR] File not found: {source}")

    logger.info("Running capture_loop standalone test — Ctrl+C to stop.")
    try:
        run_capture_loop(
            source=source,
            on_frame=_passthrough_callback,
        )
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    except RuntimeError as exc:
        sys.exit(f"[ERROR] {exc}")
