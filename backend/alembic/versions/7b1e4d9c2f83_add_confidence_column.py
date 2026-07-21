"""add confidence column to security_events

Revision ID: 7b1e4d9c2f83
Revises: 3f9c2a1b7e44
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b1e4d9c2f83'
down_revision: Union[str, Sequence[str], None] = '3f9c2a1b7e44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "security_events",
        sa.Column("confidence", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("security_events", "confidence")