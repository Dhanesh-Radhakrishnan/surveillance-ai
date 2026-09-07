"""
backend/services/health.py
Week 4 — Task 7: queue depth + VRAM usage for the enhanced /health endpoint.

Single responsibility: compute the two "is the pipeline actually healthy"
signals — how backed up is the detection queue, and how much of the 4GB
VRAM budget is in use. No HTTP concerns here — main.py's route just calls
build_health_response() and returns it.

WHY these two signals specifically: they're the two hard resource
constraints of this whole project (4GB VRAM ceiling, single-worker queue
throughput) — a green /health with a growing queue or near-full VRAM is
exactly the failure mode this project's hardware story cares about.
"""

import asyncio
import subprocess
import logging

from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

from backend.constants import REDIS_QUEUE_KEY

logger = logging.getLogger("backend.services.health")

# nvidia-smi call is expected to return almost instantly — this timeout
# only guards against a genuinely hung driver, not normal latency.
NVIDIA_SMI_TIMEOUT_SECONDS: float = 3.0


# ── Response shapes ───────────────────────────────────────────────────────────

class VramInfo(BaseModel):
    """
    WHY nullable fields aren't used here (unlike HealthResponse.vram below):
    if we got this far, nvidia-smi succeeded and gave us real numbers —
    the "might not be available" case is represented by VramInfo being
    None at the HealthResponse level, not by null fields inside it.
    """
    used_mb: int
    total_mb: int
    percent_used: float


class HealthResponse(BaseModel):
    """
    WHY queue_depth/vram are Optional (not just always-present ints):
    each can independently fail for reasons unrelated to overall app
    health (Redis blip, nvidia-smi missing on a non-GPU LAN machine) —
    None communicates "couldn't measure this" distinctly from "measured
    as zero".
    """
    status: str
    queue_depth: int | None
    vram: VramInfo | None


# ── Queue depth ────────────────────────────────────────────────────────────────

async def get_queue_depth(redis: Redis) -> int | None:
    """
    LLEN on the Stage 1 → Stage 2 detection queue.

    WHEN: called once per /health request. Cheap, non-blocking Redis op —
    safe to call on every health check without a caching layer.
    WHY None on failure (not raise): a Redis hiccup shouldn't fail the
    entire /health response — the rest of the payload can still be useful.
    """
    try:
        return await redis.llen(REDIS_QUEUE_KEY)
    except RedisError:
        logger.exception("Queue depth check failed — Redis LLEN error.")
        return None


# ── VRAM usage ──────────────────────────────────────────────────────────────────

async def get_vram_usage() -> VramInfo | None:
    """
    Shells out to nvidia-smi for used/total VRAM on the RTX 3050.

    WHY asyncio.to_thread + blocking subprocess.run (not
    asyncio.create_subprocess_exec): Windows' default uvicorn setup
    (esp. with --reload) runs a SelectorEventLoop, and Windows'
    SelectorEventLoop does NOT support asyncio subprocess transports at
    all — create_subprocess_exec raises NotImplementedError there
    unconditionally, regardless of anything in this codebase. Running the
    blocking call inside a thread pool worker via to_thread() sidesteps
    that limitation entirely while still never blocking the event loop —
    same non-blocking guarantee, portable across Windows AND Linux.

    WHY this can legitimately return None: nvidia-smi won't exist on the
    i5/i3 LAN machines (no NVIDIA GPU). Missing binary, timeout, or
    unexpected output are all treated the same: "can't tell you VRAM
    right now" rather than a 500.
    """
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=NVIDIA_SMI_TIMEOUT_SECONDS,
        )

        if result.returncode != 0:
            logger.warning("nvidia-smi exited non-zero: %s", result.stderr.strip())
            return None

        # Expected line format: "1024, 4096"  (used_mb, total_mb)
        # WHY splitlines()[0]: multi-GPU boxes would list one line per GPU —
        # this project has exactly one NVIDIA GPU (RTX 3050), so the first
        # line is always the right one.
        first_line = result.stdout.strip().splitlines()[0]
        used_str, total_str = (part.strip() for part in first_line.split(","))
        used_mb, total_mb = int(used_str), int(total_str)

        return VramInfo(
            used_mb=used_mb,
            total_mb=total_mb,
            percent_used=round((used_mb / total_mb) * 100, 1) if total_mb else 0.0,
        )

    except FileNotFoundError:
        logger.warning("nvidia-smi not found on PATH — no NVIDIA GPU on this host.")
        return None
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        logger.exception("VRAM check failed — could not parse nvidia-smi output.")
        return None

# ── Combined health payload ──────────────────────────────────────────────────

async def build_health_response(redis: Redis) -> HealthResponse:
    """
    WHEN: called directly by the /health route in main.py.
    WHY status is always "ok" here (not degraded on None sub-fields):
    a missing VRAM reading on a non-GPU host, or a transient Redis blip,
    describes the SUB-SYSTEM's observability — not whether the FastAPI
    process itself is alive and serving requests. Keep status/liveness and
    resource-metric availability as separate concerns.
    """
    queue_depth = await get_queue_depth(redis)
    vram = await get_vram_usage()
    return HealthResponse(status="ok", queue_depth=queue_depth, vram=vram)