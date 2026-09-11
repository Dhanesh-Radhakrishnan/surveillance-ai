"""
backend/schemas/security_event.py
Week 4 — Task 1: Pydantic v2 schemas for SecurityEvent request/response.
Week 5 — Task 6: added start_date/end_date range filter fields for the
history search page's relative-preset (Today/7d/30d) + custom range filter.

Single responsibility: define the API-facing shapes only. No DB session
logic, no queries — routes (W4T2/T3) import these and db_writer/models.py
stays the only place that knows about the ORM.

RULE: routes must NEVER return backend.db.models.SecurityEvent directly.
Always construct SecurityEventResponse.model_validate(orm_obj) instead.
"""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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

    @field_validator("snapshot_filename", mode="before")
    @classmethod
    def _strip_to_filename(cls, v: str) -> str:
        """
        WHY: image_path in the DB is the full absolute server path
        (e.g. /tmp/surveillance_snapshots/cam01_....jpg) — db_writer.py
        never stripped it, only ollama_worker.py's WebSocket broadcast did
        (via Path(written.image_path).name). GET /events was leaking the
        full path straight through, which produced a malformed
        /snapshots//tmp/... URL on the frontend and a silent 404 →
        'Snapshot unavailable'. This makes both delivery paths consistent.
        """
        return Path(v).name


# ── Request: query params for GET /events (W4T2, extended W5T6) ────────────

class SecurityEventQueryParams(BaseModel):
    """
    Inbound filter/pagination params for the history endpoint.

    WHY cursor (not offset): offset pagination re-scans skipped rows on every
    page and drifts under concurrent inserts (a 24/7 pipeline is always
    inserting) — cursor on (timestamp, id) is stable and index-friendly,
    matching the composite index already on security_events.

    WHY start_date/end_date are separate from cursor (W5T6): cursor answers
    "give me the next page," date range answers "only show me this window."
    The history page's relative presets (Today/7d/30d) or custom range set
    these once per search; cursor still drives pagination *within* that
    window on subsequent page requests — both are applied together (AND).
    """

    camera_id: str | None = Field(
        default=None,
        description="Filter to one camera_id. Omit to return events across all cameras.",
    )
    start_date: datetime | None = Field(
        default=None,
        description="Return events at or after this timestamp (inclusive). Omit for no lower bound.",
    )
    end_date: datetime | None = Field(
        default=None,
        description="Return events at or before this timestamp (inclusive). Omit for no upper bound.",
    )
    cursor: datetime | None = Field(
        default=None,
        description="Return events strictly older than this timestamp. Omit for the first page.",
    )
    limit: int = Field(default=25, ge=1, le=100)

    @model_validator(mode="after")
    def _check_range_order(self) -> "SecurityEventQueryParams":
        """
        WHY validate here (not just trust the frontend): a preset bug or a
        manually-crafted request with end_date before start_date would
        otherwise just silently return zero rows — a 422 makes the mistake
        obvious immediately instead of looking like "no detections happened."
        """
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be before or equal to end_date")
        return self


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