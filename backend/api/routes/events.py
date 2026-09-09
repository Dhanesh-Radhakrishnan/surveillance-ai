"""
backend/api/routes/events.py
Week 4 — Task 2 + 3: GET /events (cursor pagination) and GET /events/{id}.
Week 5 — Task 6: added start_date/end_date range filter to GET /events for
the history search page's relative-preset + custom date-range filter.

Single responsibility: HTTP routing + request/response shaping only.
No engine creation, no session instantiation — both come from
backend.db.session via Depends(). Query logic stays inline here since it's
still thin; split into a repository module only if it grows.

RULE (from schemas file): never return backend.db.models.SecurityEvent
directly — always go through SecurityEventResponse.model_validate(orm_obj).
"""

import logging
from datetime import datetime

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


# ── GET /events — cursor-paginated history, with optional date range ────────

@router.get("", response_model=PaginatedSecurityEventsResponse)
async def list_events(
    camera_id: str | None = Query(default=None),
    start_date: datetime | None = Query(
        default=None,
        description="Return events at/after this timestamp (inclusive). W5T6 date-range filter.",
    ),
    end_date: datetime | None = Query(
        default=None,
        description="Return events at/before this timestamp (inclusive). W5T6 date-range filter.",
    ),
    cursor: datetime | None = Query(
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

    WHY start_date/end_date AND cursor can both be present (W5T6): the
    history page sets start_date/end_date once from a preset (Today/7d/30d)
    or custom range, then re-requests with cursor for page 2+ — all active
    filters are ANDed together, so pagination stays inside the chosen window.

    WHY reject start_date > end_date with 400 (not empty results): a preset
    bug or bad manual request should fail loudly, not look like "no
    detections in that window."
    """
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date must be before or equal to end_date",
        )

    stmt = select(SecurityEvent).order_by(SecurityEvent.timestamp.desc()).limit(limit)

    if camera_id is not None:
        stmt = stmt.where(SecurityEvent.camera_id == camera_id)
    if start_date is not None:
        stmt = stmt.where(SecurityEvent.timestamp >= start_date)
    if end_date is not None:
        stmt = stmt.where(SecurityEvent.timestamp <= end_date)
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