"""
backend/db/models.py
Week 3 — Task 1: SecurityEvent SQLAlchemy 2.0 async model.

Single responsibility: define the ORM schema. No session logic, no queries
here — that belongs to the Week 3 worker (T5) and Week 4 API routes.

Imported by alembic/env.py as:
    from backend.db.models import Base
    target_metadata = Base.metadata
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base — all future tables inherit from this."""
    pass


class SecurityEvent(Base):
    """
    One row per person-detection event, fully resolved with an AI description.

    Lifecycle:
      1. Redis worker (W3T3) dequeues a detection event (already has
         timestamp, camera_id, snapshot_path from Week 2).
      2. Worker sends the snapshot to moondream2 (W3T4) and gets a description.
      3. Worker INSERTs one SecurityEvent row (W3T5) — ai_description is
         nullable so a row can still be written if Ollama times out (W3T7),
         instead of silently dropping the event.
    """

    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Server-side default — DB assigns the timestamp, not Python, so worker
    # clock drift across machines (RTX laptop vs LAN nodes) never matters.
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    camera_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # Path only, never image bytes — DB stays lightweight, snapshots live on disk.
    image_path: Mapped[str] = mapped_column(String(512), nullable=False)

    # Nullable: worker may write the row before/without a successful VLM
    # response (Ollama timeout, model unload, etc. — handled in W3T7).
    ai_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Week 4 GET /events will filter by camera and sort by time —
        # composite index matches that query shape directly.
        Index("ix_security_events_camera_timestamp", "camera_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<SecurityEvent id={self.id} camera_id={self.camera_id!r} "
            f"timestamp={self.timestamp!r}>"
        )