"""
backend/api/routes/events.py
Week 4 — Task 2 + 3: GET /events (cursor pagination) and GET /events/{id}.

Single responsibility: HTTP routing + request/response shaping only.
No engine creation, no session instantiation — both come from
backend.db.session via Depends(). Query logic stays inline here since it's
still thin (two small SELECTs); split into a repository module only if it
grows.

RULE (from schemas file): never return backend.db.models.SecurityEvent
directly — always go through SecurityEventResponse.model_validate(orm_obj).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import SecurityEvent
from backend.db.session import get_db_session
from backend.schemas.security_event import (
    PaginatedSecurityEventsResponse,
    SecurityEventResponse,
)

logger = logging.getLogger("backend.api.events")

router = APIRouter(prefix="/events", tags=["events"])


# ── GET /events — cursor-paginated history ───────────────────────────────────

@router.get("", response_model=PaginatedSecurityEventsResponse)
async def list_events(
    camera_id: str | None = Query(default=None),
    cursor: str | None = Query(
        default=None,
        description="ISO-8601 timestamp — return events strictly older than this.",
    ),
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedSecurityEventsResponse:
    """
    WHY cursor (timestamp) not offset: matches the composite index on
    (camera_id, timestamp) in security_events — offset pagination would
    re-scan skipped rows and drift under concurrent 24/7 inserts.
    WHEN: dashboard history page (W5T6) calls this repeatedly with
    next_cursor from the previous page.
    """
    stmt = select(SecurityEvent).order_by(SecurityEvent.timestamp.desc()).limit(limit)

    if camera_id is not None:
        stmt = stmt.where(SecurityEvent.camera_id == camera_id)
    if cursor is not None:
        stmt = stmt.where(SecurityEvent.timestamp < cursor)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    next_cursor = rows[-1].timestamp if rows else None

    return PaginatedSecurityEventsResponse(
        items=[SecurityEventResponse.model_validate(r) for r in rows],
        next_cursor=next_cursor,
        limit=limit,
    )


# ── GET /events/{id} — single event detail ───────────────────────────────────

@router.get("/{event_id}", response_model=SecurityEventResponse)
async def get_event(
    event_id: int,
    db: AsyncSession = Depends(get_db_session),
) -> SecurityEventResponse:
    """
    WHY 404 (not None/empty body): a missing id is a client error the
    dashboard's snapshot viewer (W5T5) needs to distinguish from "event
    exists but has no AI description yet" — those are different UI states.
    WHEN: dashboard snapshot viewer clicks into one event from the feed/history list.
    """
    event = await db.get(SecurityEvent, event_id)

    if event is None:
        logger.info("GET /events/%d — not found", event_id)
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

    return SecurityEventResponse.model_validate(event)