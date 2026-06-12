"""
smoke_test_moondream.py
Week 1 — Task 5: Verify moondream2 is reachable via Ollama HTTP API
and can describe a static image.

Usage:
    python smoke_test_moondream.py                    # uses bundled test image
    python smoke_test_moondream.py path/to/image.jpg  # uses your own image
"""

import base64
import gc
import json
import sys
import time
from pathlib import Path

import requests

# ── Config ───────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "moondream:latest"
REQUEST_TIMEOUT = 60          # seconds — first run may need model warm-up
TEST_IMAGE_PATH = Path("/tmp/smoke_test_frame.jpg")

# ── Helpers ───────────────────────────────────────────────────────────────────

def generate_test_image(path: Path) -> None:
    """
    Create a minimal JPEG test frame if no real image is supplied.
    Uses only stdlib + Pillow (already required by ultralytics/OpenCV).
    Draws a grey rectangle simulating a surveillance still.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise SystemExit(
            "[ERROR] Pillow not installed. Run: pip install Pillow"
        )

    img = Image.new("RGB", (640, 480), color=(60, 60, 60))
    draw = ImageDraw.Draw(img)

    # Simulate a person-shaped silhouette (simple rectangles)
    draw.rectangle([280, 140, 360, 340], fill=(120, 120, 120))   # body
    draw.ellipse([292, 100, 348, 155], fill=(140, 130, 125))      # head
    draw.rectangle([260, 340, 295, 420], fill=(100, 100, 100))    # left leg
    draw.rectangle([345, 340, 380, 420], fill=(100, 100, 100))    # right leg

    # Overlay metadata text (mirrors real snapshot filenames)
    draw.rectangle([0, 440, 640, 480], fill=(20, 20, 20))
    draw.text((8, 448), "CAM-01  |  SMOKE TEST  |  640x480", fill=(200, 200, 200))

    img.save(path, format="JPEG", quality=85)
    print(f"[INFO] Test image written → {path}  ({path.stat().st_size} bytes)")


def image_to_base64(path: Path) -> str:
    """Read an image file and return a base64-encoded string (no data-URI prefix)."""
    raw = path.read_bytes()
    encoded = base64.standard_b64encode(raw).decode("utf-8")
    return encoded


def check_ollama_health() -> bool:
    """Return True if Ollama is responding at OLLAMA_BASE_URL."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        return r.status_code == 200
    except requests.exceptions.ConnectionError:
        return False


def check_model_available(model: str) -> bool:
    """Return True if the requested model is present in Ollama's model list."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        # Ollama may store as "moondream2:latest" — match on prefix
        return any(m.startswith(model) for m in models)
    except Exception:
        return False


def send_image_to_moondream(image_b64: str, prompt: str) -> dict:
    """
    POST to Ollama /api/generate with a base64 image payload.
    Returns the parsed JSON response dict.

    Ollama multimodal payload format:
      {
        "model": "moondream2",
        "prompt": "<text prompt>",
        "images": ["<base64-string>"],
        "stream": false
      }
    """
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "images": [image_b64],
        "stream": False,
    }

    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


# ── Main smoke test ───────────────────────────────────────────────────────────

def run_smoke_test(image_path: Path) -> None:
    separator = "─" * 58

    print(separator)
    print(f"  Moondream2 Smoke Test — {MODEL_NAME} via Ollama HTTP API")
    print(separator)

    # 1. Ollama reachability
    print(f"\n[1/5] Checking Ollama at {OLLAMA_BASE_URL} ...", end=" ", flush=True)
    if not check_ollama_health():
        raise SystemExit(
            f"\n[FAIL] Ollama is not running or not reachable at {OLLAMA_BASE_URL}.\n"
            "       Start it with:  ollama serve"
        )
    print("OK ✓")

    # 2. Model presence
    print(f"[2/5] Checking model '{MODEL_NAME}' is pulled ...", end=" ", flush=True)
    if not check_model_available(MODEL_NAME):
        raise SystemExit(
            f"\n[FAIL] Model '{MODEL_NAME}' not found in Ollama.\n"
            f"       Pull it with:  ollama pull {MODEL_NAME}\n"
            f"       Available models: " + ", ".join(
                m["name"] for m in requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5).json().get("models", [])
            )
        )
    print("OK ✓")

    # 3. Prepare image
    print(f"[3/5] Loading image from {image_path} ...", end=" ", flush=True)
    if not image_path.exists():
        generate_test_image(image_path)
    image_b64 = image_to_base64(image_path)
    size_kb = image_path.stat().st_size / 1024
    print(f"OK ✓  ({size_kb:.1f} KB, base64 length: {len(image_b64)} chars)")

    # 4. Send to moondream2
    #    Prompt mirrors what the real AI worker will use in Week 3:
    #    concise, structured, ≤10 words — suitable for DB storage.
    prompt = (
        "Describe what you see in this security camera image in 10 words or fewer. "
        "Focus on people, actions, and location."
    )
    print(f"[4/5] Sending image to {MODEL_NAME} (timeout={REQUEST_TIMEOUT}s) ...")
    print(f"      Prompt: \"{prompt}\"")

    t0 = time.perf_counter()
    try:
        result = send_image_to_moondream(image_b64, prompt)
    except requests.exceptions.Timeout:
        raise SystemExit(
            f"\n[FAIL] Request timed out after {REQUEST_TIMEOUT}s.\n"
            "       First inference may be slow — try increasing REQUEST_TIMEOUT."
        )
    except requests.exceptions.HTTPError as exc:
        raise SystemExit(f"\n[FAIL] Ollama returned HTTP error: {exc}")
    elapsed = time.perf_counter() - t0

    # 5. Validate response
    print(f"[5/5] Validating response ...")
    description: str = result.get("response", "").strip()
    model_used: str  = result.get("model", "unknown")
    eval_count: int  = result.get("eval_count", 0)

    assert description, "[FAIL] 'response' field is empty — moondream2 returned no text."
    assert model_used.startswith(MODEL_NAME), (
        f"[FAIL] Unexpected model in response: {model_used}"
    )

    print()
    print(separator)
    print(f"  RESULT")
    print(separator)
    print(f"  Model   : {model_used}")
    print(f"  Latency : {elapsed:.2f}s")
    print(f"  Tokens  : {eval_count}")
    print(f"  Response: {description}")
    print(separator)
    print("\n  [PASS] moondream2 is working correctly via Ollama HTTP API ✓\n")

    # Explicit cleanup — mirrors discipline required in the real pipeline
    del image_b64
    gc.collect()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        if not target.exists():
            raise SystemExit(f"[ERROR] File not found: {target}")
    else:
        target = TEST_IMAGE_PATH

    run_smoke_test(target)
