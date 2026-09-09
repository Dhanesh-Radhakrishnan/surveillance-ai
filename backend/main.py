"""
backend/main.py
Week 4 — Task 4: FastAPI app instance.
...
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis

from backend.db.redis_session import get_redis_connection
from backend.services.health import HealthResponse, build_health_response
from backend.api.routes.events import router as events_router
from backend.api.routes.ws_events import router as ws_events_router
from backend.db.session import dispose_engine
from backend.db.redis_session import dispose_redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backend.main")

# W5T5: snapshot dir default — mirrors ai-worker/config.py's own default
# rather than importing it (backend/ never imports from ai-worker/).
SNAPSHOT_DIR = Path(os.environ.get("SNAPSHOT_DIR", "/tmp/surveillance_snapshots"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI startup — DB engine ready on first query, Redis client ready.")
    yield
    await dispose_engine()
    await dispose_redis()
    logger.info("FastAPI shutdown — DB engine and Redis client disposed.")


app = FastAPI(
    title="Surveillance AI — Backend API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# W5T5: mount AFTER `app` exists — a mount call needs an app instance to
# attach to, same as add_middleware()/include_router() below it.
app.mount("/snapshots", StaticFiles(directory=str(SNAPSHOT_DIR)), name="snapshots")


@app.get("/health", response_model=HealthResponse)
async def health(redis: Redis = Depends(get_redis_connection)) -> HealthResponse:
    return await build_health_response(redis)


app.include_router(events_router)
app.include_router(ws_events_router)