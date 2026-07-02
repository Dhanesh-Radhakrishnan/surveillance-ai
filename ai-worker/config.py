"""
config.py
Centralised configuration for the ai-worker package.
All pipeline constants live here — never hard-code values in other modules.

Override any value via environment variables at runtime:
    CAMERA_SOURCE=0 SNAPSHOT_DIR=/tmp/snaps python capture_loop.py
"""

import os
from pathlib import Path

# ── Camera source ─────────────────────────────────────────────────────────────
# Integer  → webcam index  (0 = default webcam)
# String   → path to a video file, e.g. "/tmp/test_clip.mp4"
# The env var is always a string, so cast to int only when it looks numeric.
_raw_source = os.environ.get("CAMERA_SOURCE", "0")
CAMERA_SOURCE: int | str = int(_raw_source) if _raw_source.isdigit() else _raw_source

# ── Frame capture ─────────────────────────────────────────────────────────────
# Target frames per second to READ from the source.
# The loop will attempt to maintain this rate via a sleep back-off.
# Lower values reduce CPU load; 5–10 fps is plenty for surveillance triggers.
CAPTURE_FPS: int = int(os.environ.get("CAPTURE_FPS", "10"))

# ── Snapshot output ───────────────────────────────────────────────────────────
SNAPSHOT_DIR: Path = Path(os.environ.get("SNAPSHOT_DIR", "/tmp/surveillance_snapshots"))

# Filename template — filled with camera id and ISO-format timestamp.
# Example: cam01_2025-06-01T14:32:07.123456.jpg
SNAPSHOT_FILENAME_TEMPLATE: str = "{camera_id}_{timestamp}.jpg"
SNAPSHOT_JPEG_QUALITY: int = int(os.environ.get("SNAPSHOT_JPEG_QUALITY", "85"))

# ── Camera identity ───────────────────────────────────────────────────────────
# Logical camera name written to Redis events and DB rows.
CAMERA_ID: str = os.environ.get("CAMERA_ID", "cam01")

# ── YOLO (Week 2, Task 2 — not used in this file yet) ────────────────────────
YOLO_MODEL_PATH: str = os.environ.get("YOLO_MODEL_PATH", "yolo11n.pt")
YOLO_CONFIDENCE_THRESHOLD: float = float(
    os.environ.get("YOLO_CONFIDENCE_THRESHOLD", "0.45")
)
YOLO_TARGET_CLASS: int = 0          # COCO class 0 = "person" — never change this

# ── Redis (Week 2, Task 5 — not used in this file yet) ───────────────────────
REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
REDIS_QUEUE_KEY: str = "surveillance:detection_events"

# ── Ollama (referenced by Week 3 worker) ─────────────────────────────────────
OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = "moondream:latest"   # NEVER change without hardware review
OLLAMA_REQUEST_TIMEOUT: int = 60

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_EVENT_QUEUE = os.getenv("REDIS_EVENT_QUEUE", "detection_events")
