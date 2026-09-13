# Surveillance AI — Local, Privacy-First Video Analytics

A self-hosted security camera dashboard that detects people, describes what
they're doing in plain English, and streams alerts to a live dashboard —
**with zero cloud dependency**. Every model, every byte of video, and every
inference call stays on hardware I own.

## Why this project exists

Most "AI camera" products ship your video to someone else's server. This
project asks a narrower, harder question: **how much useful surveillance
intelligence can you get out of consumer hardware you already have,
without sending a single frame off your network?**

The answer shaped every architectural decision below.

## The hardware story

This isn't a cloud GPU cluster — it's a gaming laptop and two hand-me-down
machines on the same LAN.

| Machine | Specs | Role |
|---|---|---|
| Ryzen 5 6600H laptop | RTX 3050, **4GB VRAM** | Backend, AI worker, Ollama, Postgres, Redis |
| i3 7th gen laptop | 12GB RAM, no GPU | React frontend host |
| i5 14th gen desktop | No GPU | Reserve — second capture node candidate |

**4GB of VRAM is the entire budget for AI on this project.** That number
disqualifies almost every "obvious" choice in the vision-language-model
space (13B-parameter LLaVA variants, full-size Gemma, CLIP-large) and
forced a design built around *scarcity* rather than throughput:

- **Two-stage inference, not one.** A single VLM watching a live 24/7
  video feed would either fall over on 4GB or force everything else to
  run on CPU. Instead, a cheap always-on stage (YOLO11n, CPU-only) decides
  *whether anything interesting happened at all*, and only that decision
  wakes up the expensive stage (moondream2, GPU). The VLM only ever looks
  at a handful of snapshots a minute — never a video stream.
- **YOLO11n runs on CPU, on purpose.** The nano variant is cheap enough
  that CPU inference doesn't bottleneck the pipeline, and it means the
  full 4GB VRAM budget is reserved exclusively for the VLM in Stage 2
  instead of being split between two GPU consumers.
- **moondream2 (1.6B params) over anything bigger.** It's small enough to
  live comfortably inside 4GB alongside normal desktop use, and — because
  it's small — it needs architectural help rather than clever prompting:
  frames are cropped to the YOLO bounding box (+15% padding, with a
  minimum crop size) *before* they ever reach the VLM. Asking a model
  this size to "ignore the background" in a prompt doesn't work reliably;
  removing the background from the pixels it sees does.
- **The frontend doesn't run on the GPU machine.** The dashboard is just
  a React app talking to a WebSocket — no reason to make the RTX laptop
  do double duty as a dev box when a spare laptop with Node already
  installed can host it over the LAN instead.
- **The third machine is a placeholder, not an afterthought.** The i5
  desktop is documented as a reserve capture node for a future second
  camera, but nothing today is architected around it — adding hardware
  later should be additive, not a rewrite.

Every constraint above is still true at time of writing. The honest
limitation of this project is the 4GB ceiling itself: it's the reason
moondream2 was chosen over a more capable VLM, and the clearest path to a
noticeably smarter system is simply better hardware — not better code.

## Architecture (two-stage pipeline)

The split exists because of the 4GB VRAM ceiling above: Stage 1 runs
continuously and never touches the GPU, so the entire VRAM budget stays
free for Stage 2, which only wakes up when there's actually something to
analyze.

```mermaid
flowchart TD
    subgraph S1["Stage 1 — lightweight trigger · runs continuously · CPU only"]
        CAM["📷 Camera / video file"] --> CV["OpenCV capture loop"]
        CV --> YOLO["YOLO11n person detection<br/>(CPU, confidence-filtered)"]
        YOLO -- "no person" --> CV
        YOLO -- "person detected" --> SNAP["Save cropped snapshot<br/>(bbox + 15% padding, /tmp)"]
        SNAP --> RQ["RPUSH → Redis queue"]
    end

    subgraph S2["Stage 2 — async AI analysis · on-demand · GPU (4GB budget)"]
        RQ --> WRK["Async worker<br/>BLPOP dequeue"]
        WRK --> IMG["Load snapshot from disk"]
        IMG --> OLL["moondream2 via Ollama HTTP<br/>(localhost:11434, RTX 3050)"]
        OLL --> DESC["AI description<br/>(≤15 words)"]
        DESC --> DB[("PostgreSQL<br/>SecurityEvent row")]
        DB --> PUB["PUBLISH → Redis pub/sub<br/>(events:broadcast)"]
    end

    subgraph API["FastAPI backend"]
        PUB --> WS["WebSocket /ws/events"]
        DB --> REST["REST GET /events<br/>(cursor-paginated history)"]
    end

    subgraph UI["React dashboard (i3 laptop, LAN)"]
        WS --> LIVE["Live event feed"]
        REST --> HIST["History search + snapshot viewer"]
    end
```

**Reading the diagram:**
- **Stage 1 never blocks on Stage 2.** A busy or restarting Ollama process
  can't stall the capture loop — the queue absorbs the gap.
- **The dashboard never receives raw video.** Only structured events
  (description + snapshot filename + confidence) cross the WebSocket —
  matching the "no raw video stream in browser" rule for this project.
- **Two independent OS processes**, not two threads in one app — the
  capture/detection loop and the AI worker can be restarted, scaled, or
  moved to a different machine independently.

## Stack

- **Capture / detection:** OpenCV, YOLO11n (ultralytics), CPU-only
- **AI analysis:** moondream2 via Ollama HTTP API — never loaded directly
  in Python, always over `localhost:11434`
- **Backend:** FastAPI, SQLAlchemy 2.0 (async), Alembic, PostgreSQL,
  Redis (queue + pub/sub)
- **Frontend:** React + TypeScript + Vite + Tailwind v4
- **Infra:** Docker Compose (Postgres + Redis only) — no Kubernetes, no
  cloud, ever

## Setup

Everything below runs on the RTX 3050 laptop unless noted. The frontend is
the one piece meant to run on a separate LAN machine (see hardware table
above) — its own subsection covers that.

### Prerequisites

- Docker Desktop (for PostgreSQL + Redis)
- [Ollama](https://ollama.com) installed natively — **not** in Docker,
  so it has direct access to the RTX 3050's VRAM
- Python 3.11+ (no virtualenv required, but one is fine if you prefer)
- Node.js ≥ 20.19 — required on whichever machine hosts the frontend
- NVIDIA drivers current enough for `nvidia-smi` to report the RTX 3050

### 1. Start Postgres + Redis

```bash
git clone <this-repo>
cd surveillance-ai
docker-compose up -d
```

- Both containers bind to `0.0.0.0`, not `127.0.0.1` — required so the
  i3 frontend/backend split and any future capture node on the LAN can
  reach them, not just processes on `localhost`.
- Default credentials live in `docker-compose.yml` as fallbacks
  (`surveillance` / `changeme`). **These are development defaults,
  not secrets** — they're checked into version control today and will be
  moved to `.env`-only placeholders before this repo goes public (tracked
  as a Week 6 cleanup item). Override them via a root `.env` file if you
  want different values locally:

  ```
  POSTGRES_USER=surveillance
  POSTGRES_PASSWORD=changeme
  POSTGRES_DB=surveillance_db
  ```

### 2. Install Ollama and pull moondream2

```bash
ollama pull moondream
ollama serve          # if not already running as a background service
```

- Verify it's actually using the GPU, not silently falling back to CPU —
  either watch `nvidia-smi` while running the smoke test below, or check
  the `vram` field on `GET /health` once the backend is up.
- Confirm the pull worked and hits GPU:
  ```bash
  python ai-worker/smoke_test_moondream.py
  ```

### 3. Python dependencies

No virtualenv is required, but one is recommended if you run other
Python projects on this machine.

```bash
pip install fastapi uvicorn[standard] sqlalchemy[asyncio] alembic asyncpg \
            redis ollama opencv-python ultralytics numpy requests Pillow \
            pydantic python-dotenv
```

### 4. Environment variables

| Variable | Used by | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | Alembic (`backend/alembic/env.py`) | *(none — required)* | `postgresql+asyncpg://surveillance:changeme@localhost:5432/surveillance_db` — the `@` in the password **must** be percent-encoded as `%40` |
| `POSTGRES_USER/PASSWORD/DB/HOST/PORT` | backend, ai-worker | matches `docker-compose.yml` | Only needed if you changed the Docker defaults |
| `REDIS_URL` | backend, ai-worker | `redis://localhost:6379/0` | |
| `OLLAMA_BASE_URL` | ai-worker | `http://localhost:11434` | |
| `CAMERA_SOURCE` | ai-worker | `0` | Webcam index, or a path to a video file |
| `SNAPSHOT_DIR` | ai-worker, backend | `/tmp/surveillance_snapshots` | Must match on both — backend serves this dir via `StaticFiles` |

Windows PowerShell sets these as `$env:DATABASE_URL = "..."` (per-session,
not persisted) — set them before running `alembic` or the worker in that
shell.

The frontend has its own env file, separate from the above:

```bash
cd frontend
cp .env.example .env.local
```

`VITE_WS_URL` / `VITE_API_URL` in `.env.local` point at `localhost` by
default — update these to the RTX laptop's LAN IP once the frontend is
actually running from the i3 machine (W5T8).

### 5. Run database migrations

```bash
cd backend
alembic upgrade head
```

Must be run from the `backend/` directory — `alembic.ini`'s
`script_location` is relative to it.

### 6. Run the pipeline (RTX laptop — separate terminals)

```bash
# Terminal 1 — capture + detection (Stage 1)
python ai-worker/stage1_pipeline.py

# Terminal 2 — async AI worker (Stage 2)
python ai-worker/ollama_worker.py

# Terminal 3 — API + WebSocket server
uvicorn backend.main:app --host 0.0.0.0 --reload
```

Run `python ai-worker/test_connections.py` first if anything above fails
silently — it checks Postgres, Redis, and Ollama independently and tells
you which one is unreachable.

### 7. Run the frontend (i3 laptop, or any LAN machine)

```bash
cd frontend
npm install
npm run dev
```

Vite's dev server is already configured to bind `0.0.0.0` — reachable
from the RTX laptop or any other device on the LAN at
`http://<i3-ip>:5173`.

## Multi-node capability (reserve hardware)

The original plan penciled in the i5 desktop as the frontend host and the
i3 laptop as reserve. That flipped during Week 5 (**W5T8**): the i3 laptop
already had Node.js and dev tooling installed, so it became the frontend
host to avoid a mid-sprint environment-setup detour, leaving the **i5
desktop as the current reserve machine**. If you're comparing against an
earlier version of this doc or the project tracker, that's the
discrepancy — the i5 is the one documented as multi-node capable below,
not the i3.

**What "multi-node capable" means today:** the i5 could run its own
Stage 1 (`ai-worker/stage1_pipeline.py`) as a second camera, publishing
detection events to the *same* Redis instance on the RTX laptop — every
Stage 1 setting (`CAMERA_SOURCE`, `CAMERA_ID`, `REDIS_URL`,
`YOLO_CONFIDENCE_THRESHOLD`, etc.) already reads from environment
variables in `ai-worker/config.py`, so pointing a second machine at the
same queue is theoretically just:

```bash
# On the i5, pointed at the RTX laptop's LAN IP
$env:REDIS_URL = "redis://<rtx-laptop-ip>:6379/0"
$env:CAMERA_ID = "cam02"
python ai-worker/stage1_pipeline.py
```

YOLO11n (CPU) is light enough that the i5's lack of a GPU isn't a
blocker — Stage 1 was designed to run on CPU from the start.

**What's *not* solved yet — the honest gap:** `redis_publisher.py` puts
a local filesystem path (`snapshot_path`) into the queued event, and
`ollama_worker.py` reads that path directly off disk. That's correct
today because capture and the worker share one machine and one disk. A
second physical capture node breaks this silently — the RTX laptop's
worker would try to open a path that only exists on the i5. This project
does **not** currently solve that (shared network mount, or shipping
image bytes through Redis instead of a path) — it's flagged here as the
real next step *if* multi-node is ever built out, rather than architected
speculatively before it's needed. Per this project's own scope rules,
reserve hardware stays documented, not built around, until there's an
actual second camera to justify it.

