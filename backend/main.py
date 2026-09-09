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
from fastapi import Depends
from redis.asyncio import Redis

from backend.db.redis_session import get_redis_connection
from backend.services.health import HealthResponse, build_health_response
from backend.api.routes.events import router as events_router
from backend.api.routes.ws_events import router as ws_events_router
from backend.db.session import dispose_engine
from backend.db.redis_session import dispose_redis

from fastapi.staticfiles import StaticFiles
app.mount("/snapshots", StaticFiles(directory=str(config.SNAPSHOT_DIR)), name="snapshots")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backend.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: nothing to warm up yet — DB engine is lazy-created on first
    # use, and the Redis client is already connected at import time
    # (backend/db/redis_session.py) since it's a single shared pooled client.
    logger.info("FastAPI startup — DB engine ready on first query, Redis client ready.")
    yield
    # Shutdown: release both connection pools cleanly — mirrors
    # ollama_worker.py's finally-block discipline for the Redis worker.
    await dispose_engine()
    await dispose_redis()
    logger.info("FastAPI shutdown — DB engine and Redis client disposed.")


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


@app.get("/health", response_model=HealthResponse)
async def health(redis: Redis = Depends(get_redis_connection)) -> HealthResponse:
    """
    W4T7: liveness + resource metrics — queue depth and VRAM usage.
    WHY Depends(get_redis_connection): same DI pattern as every other
    Redis-touching route/handler in this codebase — never instantiate
    a client directly inside a route.
    """
    return await build_health_response(redis)


app.include_router(events_router)
app.include_router(ws_events_router)