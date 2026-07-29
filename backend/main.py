"""
backend/main.py
Week 4 — Task 4: FastAPI app instance.

Single responsibility: create the app, wire CORS, mount routers, handle
startup/shutdown. Route logic itself lives in backend/api/routes/ — this
file never contains query logic (SOLID, same rule as ai-worker modules).

Run (from repo root):
    uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes.events import router as events_router
from backend.db.session import dispose_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backend.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: nothing to warm up yet — engine is lazy-created on first use.
    logger.info("FastAPI startup — DB engine ready on first query.")
    yield
    # Shutdown: release the connection pool cleanly — mirrors
    # ollama_worker.py's finally-block discipline for the Redis worker.
    await dispose_engine()
    logger.info("FastAPI shutdown — DB engine disposed.")


app = FastAPI(
    title="Surveillance AI — Backend API",
    version="0.1.0",
    lifespan=lifespan,
)

# WHY permissive origins for now: Week 5 dashboard runs on the i5 LAN machine
# at an arbitrary LAN IP, not localhost — tighten this to an explicit
# allow-list once that IP is fixed, instead of before it's known.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Basic liveness check — full queue/VRAM version is W4T7, not this."""
    return {"status": "ok"}


app.include_router(events_router)