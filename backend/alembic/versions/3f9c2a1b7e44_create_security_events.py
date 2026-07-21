"""create security_events table

Revision ID: 3f9c2a1b7e44
Revises: aa8080bf745d
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f9c2a1b7e44'
down_revision: Union[str, Sequence[str], None] = 'aa8080bf745d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "security_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("camera_id", sa.String(length=64), nullable=False),
        sa.Column("image_path", sa.String(length=512), nullable=False),
        sa.Column("ai_description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_security_events_camera_timestamp",
        "security_events",
        ["camera_id", "timestamp"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_security_events_camera_timestamp", table_name="security_events")
    op.drop_table("security_events")