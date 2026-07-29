"""
backend/schemas/security_event.py
Week 4 — Task 1: Pydantic v2 schemas for SecurityEvent request/response.

Single responsibility: define the API-facing shapes only. No DB session
logic, no queries — routes (W4T2/T3) import these and db_writer/models.py
stays the only place that knows about the ORM.

RULE: routes must NEVER return backend.db.models.SecurityEvent directly.
Always construct SecurityEventResponse.model_validate(orm_obj) instead.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── Response: one event ──────────────────────────────────────────────────────

class SecurityEventResponse(BaseModel):
    """
    Outbound shape for a single SecurityEvent row.

    WHY image_path -> snapshot_filename: the ORM stores an absolute local
    path (e.g. /tmp/surveillance_snapshots/cam01_....jpg). Never leak server
    filesystem layout over the API — expose only the filename. W5 dashboard
    will resolve it against a static-file route (e.g. /snapshots/{filename}).
    """

    model_config = ConfigDict(from_attributes=True)  # lets .model_validate(orm_obj) work

    id: int
    timestamp: datetime
    camera_id: str
    snapshot_filename: str = Field(
        validation_alias="image_path",
        description="Filename only — resolve against the snapshot static route, not a full path.",
    )
    ai_description: str | None = Field(
        default=None,
        description="Null if Ollama timed out or returned empty (W3T7) — event still valid.",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="YOLO detection confidence that triggered this event.",
    )


# ── Request: query params for GET /events (W4T2) ────────────────────────────

class SecurityEventQueryParams(BaseModel):
    """
    Inbound filter/pagination params for the history endpoint.

    WHY cursor (not offset): offset pagination re-scans skipped rows on every
    page and drifts under concurrent inserts (a 24/7 pipeline is always
    inserting) — cursor on (timestamp, id) is stable and index-friendly,
    matching the composite index already on security_events.
    """

    camera_id: str | None = Field(
        default=None,
        description="Filter to one camera_id. Omit to return events across all cameras.",
    )
    cursor: datetime | None = Field(
        default=None,
        description="Return events strictly older than this timestamp. Omit for the first page.",
    )
    limit: int = Field(default=25, ge=1, le=100)


# ── Response: paginated envelope ────────────────────────────────────────────

class PaginatedSecurityEventsResponse(BaseModel):
    """
    Wraps a page of events plus the cursor to request the next page.

    WHY next_cursor can be None: signals "no more pages" to the frontend —
    it's the timestamp of the last item in `items`, or None if items is empty
    or this was already the final page.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[SecurityEventResponse]
    next_cursor: datetime | None = None
    limit: int