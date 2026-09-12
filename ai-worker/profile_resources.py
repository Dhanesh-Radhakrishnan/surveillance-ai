"""
ai-worker/profile_resources.py
Week 6 — Task 1: Profile RAM and VRAM usage under a 1-hour continuous run.

Run ALONGSIDE stage1_pipeline.py and ollama_worker.py (separate terminals)
during the soak test. Samples system RAM + VRAM (mirrors
backend/services/health.py's nvidia-smi approach, standalone here) plus the
two pipeline processes' own RSS every --interval seconds, writes a CSV, and
prints a leak-detection summary on completion or Ctrl+C.

Usage:
    python profile_resources.py                  # 1 hour, 10s interval
    python profile_resources.py --duration 300    # 5 min smoke test
    python profile_resources.py --interval 5

Requires: pip install psutil
"""
import argparse
import csv
import gc
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import psutil
except ImportError:
    sys.exit("[ERROR] psutil not installed. Run: pip install psutil")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("profile_resources")

# Matched by substring against full cmdline (both run as `python <script>.py`)
# — WHY per-process, not just system total: system RAM also includes
# Postgres/Redis/Ollama containers + the OS, which can mask a leak inside
# one specific loop (YOLO frame loop vs. moondream2 event loop).
TRACKED_SCRIPTS = ("stage1_pipeline.py", "ollama_worker.py")

NVIDIA_SMI_TIMEOUT_SECONDS = 3.0


@dataclass
class Sample:
    timestamp: str
    system_ram_used_mb: float
    system_ram_percent: float
    vram_used_mb: int | None
    vram_total_mb: int | None
    vram_percent: float | None
    stage1_rss_mb: float | None
    worker_rss_mb: float | None


def get_vram() -> tuple[int | None, int | None, float | None]:
    """
    Same nvidia-smi approach as backend/services/health.py's get_vram_usage,
    but plain subprocess.run — this script has no event loop to protect
    (standalone sync monitor, not FastAPI), so the Windows asyncio-subprocess
    limitation documented there doesn't apply here.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=NVIDIA_SMI_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None, None, None
        used_str, total_str = (p.strip() for p in result.stdout.strip().splitlines()[0].split(","))
        used, total = int(used_str), int(total_str)
        return used, total, round((used / total) * 100, 1) if total else None
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None, None, None


def find_tracked_rss() -> dict[str, float | None]:
    """
    None means 'not found running' — profiler still logs system stats either way.

    WHY filter on proc name (not just cmdline substring): a shell wrapper
    that launched the script (e.g. `cmd /c python ollama_worker.py` from an
    IDE task runner) can carry the script name in ITS OWN cmdline while
    itself being a near-empty process — matching on cmdline alone silently
    picks up that wrapper's tiny RSS instead of the real interpreter's.
    WHY max-wins (not last-wins) on multiple matches: a launcher stub
    (py.exe) and the real python.exe it execs can both match — keeping the
    largest RSS favours the real interpreter without needing to hardcode
    which process names are "wrappers" vs "real" across platforms.
    """
    PYTHON_PROCESS_NAMES = {"python", "python.exe", "python3", "pythonw.exe"}
    found: dict[str, float | None] = {name: None for name in TRACKED_SCRIPTS}

    for proc in psutil.process_iter(["name", "cmdline", "memory_info"]):
        try:
            proc_name = (proc.info["name"] or "").lower()
            if proc_name not in PYTHON_PROCESS_NAMES:
                continue
            cmdline = " ".join(proc.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        for script in TRACKED_SCRIPTS:
            if script in cmdline:
                rss = round(proc.info["memory_info"].rss / (1024 * 1024), 1)
                if found[script] is None or rss > found[script]:
                    found[script] = rss

    return found


def take_sample() -> Sample:
    vmem = psutil.virtual_memory()
    vram_used, vram_total, vram_pct = get_vram()
    rss = find_tracked_rss()
    return Sample(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        system_ram_used_mb=round(vmem.used / (1024 * 1024), 1),
        system_ram_percent=vmem.percent,
        vram_used_mb=vram_used,
        vram_total_mb=vram_total,
        vram_percent=vram_pct,
        stage1_rss_mb=rss["stage1_pipeline.py"],
        worker_rss_mb=rss["ollama_worker.py"],
    )


def summarize(samples: list[Sample]) -> None:
    """
    WHY first-10%-vs-last-10% average (not min/max): a genuine slow leak
    shows as a rising trend across the hour, not a single spike — min/max
    would flag normal GC sawtooth as a false "leak". This is the check that
    verifies the project's existing gc.collect()+del discipline actually
    held for a full hour, not just a few seconds.
    """
    if len(samples) < 10:
        logger.warning("Too few samples (%d) for trend analysis.", len(samples))
        return

    n = max(1, len(samples) // 10)
    first, last = samples[:n], samples[-n:]
    avg = lambda vals: sum(vals) / len(vals)

    first_ram, last_ram = avg([s.system_ram_used_mb for s in first]), avg([s.system_ram_used_mb for s in last])
    ram_drift_mb = last_ram - first_ram
    ram_drift_pct = (ram_drift_mb / first_ram) * 100 if first_ram else 0

    v_first = [s.vram_used_mb for s in first if s.vram_used_mb is not None]
    v_last = [s.vram_used_mb for s in last if s.vram_used_mb is not None]
    vram_drift_mb = (avg(v_last) - avg(v_first)) if v_first and v_last else None

    sep = "─" * 58
    print(f"\n{sep}\n  RESOURCE PROFILE SUMMARY — {len(samples)} samples\n{sep}")
    print(f"  System RAM   : {first_ram:.0f} MB → {last_ram:.0f} MB  (Δ {ram_drift_mb:+.0f} MB / {ram_drift_pct:+.1f}%)")
    print(f"  VRAM         : {avg(v_first):.0f} MB → {avg(v_last):.0f} MB" if vram_drift_mb is not None
          else "  VRAM         : nvidia-smi unavailable — skipped")

    s1 = [s.stage1_rss_mb for s in samples if s.stage1_rss_mb is not None]
    w1 = [s.worker_rss_mb for s in samples if s.worker_rss_mb is not None]
    print(f"  stage1_pipeline.py RSS : min {min(s1):.0f} — max {max(s1):.0f} MB" if s1
          else "  stage1_pipeline.py     : not detected running")
    print(f"  ollama_worker.py RSS   : min {min(w1):.0f} — max {max(w1):.0f} MB" if w1
          else "  ollama_worker.py       : not detected running")
    print(sep)
    print(f"  {'⚠ RAM grew ' + format(ram_drift_pct, '+.1f') + '% — investigate.' if ram_drift_pct > 15 else '✓ RAM stable — no obvious leak trend.'}\n")


def run_profiler(duration_seconds: int, interval_seconds: int, output_path: Path) -> None:
    samples: list[Sample] = []
    end_time = time.monotonic() + duration_seconds
    logger.info("Profiling started — duration=%ds interval=%ds output=%s — Ctrl+C to stop early.",
                duration_seconds, interval_seconds, output_path)
    try:
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(asdict(take_sample()).keys()))
            writer.writeheader()
            while time.monotonic() < end_time:
                sample = take_sample()
                samples.append(sample)
                writer.writerow(asdict(sample))
                f.flush()  # survive Ctrl+C mid-run without losing rows
                logger.info("RAM %.0f%% (%.0fMB)  VRAM %s  stage1=%s  worker=%s",
                            sample.system_ram_percent, sample.system_ram_used_mb,
                            f"{sample.vram_percent}%" if sample.vram_percent is not None else "n/a",
                            f"{sample.stage1_rss_mb}MB" if sample.stage1_rss_mb else "—",
                            f"{sample.worker_rss_mb}MB" if sample.worker_rss_mb else "—")
                del sample
                gc.collect()
                time.sleep(interval_seconds)
    except KeyboardInterrupt:
        logger.info("Interrupted — summarizing %d samples collected so far.", len(samples))
    finally:
        summarize(samples)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Profile RAM/VRAM over a long pipeline run (W6T1).")
    parser.add_argument("--duration", type=int, default=3600, help="Total seconds (default 3600 = 1hr)")
    parser.add_argument("--interval", type=int, default=10, help="Seconds between samples (default 10)")
    parser.add_argument("--output", type=str, default=None, help="CSV output path")
    args = parser.parse_args()
    out = Path(args.output) if args.output else Path(f"profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    run_profiler(args.duration, args.interval, out)