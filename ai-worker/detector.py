"""
detector.py
Week 2 — Task 2 + 3: YOLO11n person detection with confidence filtering.

Single responsibility: given a frame, return only high-confidence person
detections. Knows nothing about video capture, Redis, or snapshots.

Instantiate PersonDetector ONCE at process startup (loading weights per-frame
would be catastrophic for FPS and CPU load) and reuse it in the capture loop's
on_frame callback.
"""

import logging
from dataclasses import dataclass

import numpy as np
from ultralytics import YOLO

import config

logger = logging.getLogger("detector")


@dataclass
class Detection:
    """One qualifying person detection above the confidence threshold."""
    confidence: float
    box_xyxy: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixel coords


class PersonDetector:
    """
    Wraps a YOLO11n model, forced to CPU, filtered to COCO class 0 (person) only.

    WHY CPU: reserves the entire 4GB VRAM budget exclusively for moondream2
    in Week 3 — YOLO11n nano is cheap enough to run comfortably on CPU.
    """

    def __init__(
        self,
        model_path: str = config.YOLO_MODEL_PATH,
        confidence_threshold: float = config.YOLO_CONFIDENCE_THRESHOLD,
    ) -> None:
        logger.info("Loading YOLO11n weights from %s (CPU)...", model_path)
        self._model = YOLO(model_path)
        self._model.to("cpu")
        self._confidence_threshold = confidence_threshold
        logger.info(
            "PersonDetector ready — class=%d (person), conf_threshold=%.2f",
            config.YOLO_TARGET_CLASS, confidence_threshold,
        )

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """
        Run inference on a single BGR frame.
        Returns only person detections with confidence >= threshold.
        Empty list means "nothing worth alerting on" — caller decides what to do.
        """
        results = self._model.predict(
            source=frame,
            classes=[config.YOLO_TARGET_CLASS],   # person-only at inference time
            conf=self._confidence_threshold,       # W2T3: skip low-conf at the source
            verbose=False,
        )

        detections: list[Detection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                conf = float(box.conf[0])
                # Belt-and-braces: YOLO's own conf= arg already filters this,
                # but an explicit re-check keeps the threshold logic visible
                # and testable independent of the model call.
                if conf < self._confidence_threshold:
                    continue
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
                detections.append(Detection(confidence=conf, box_xyxy=(x1, y1, x2, y2)))

        if detections:
            logger.debug("Frame: %d qualifying person detection(s)", len(detections))

        return detections


# ── Standalone smoke test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import cv2

    logging.basicConfig(level=logging.INFO)

    img_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not img_path:
        sys.exit("[ERROR] Usage: python detector.py path/to/test_image.jpg")

    frame = cv2.imread(img_path)
    if frame is None:
        sys.exit(f"[ERROR] Could not read image: {img_path}")

    detector = PersonDetector()
    results = detector.detect(frame)

    print(f"\n{len(results)} qualifying detection(s):")
    for i, d in enumerate(results, start=1):
        print(f"  [{i}] confidence={d.confidence:.2f}  box={d.box_xyxy}")