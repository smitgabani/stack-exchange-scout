"""add time spent to questions

Revision ID: 67fcd0393287
Revises: f6b2e9d40c17
Create Date: 2026-09-28 00:26:20.588764

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '67fcd0393287'
down_revision: str | Sequence[str] | None = 'f6b2e9d40c17'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    How long solving a challenge took, in seconds — set by the frontend timer
    when a challenge is marked complete. Nullable: most existing `solved`
    rows predate the timer and have nothing to backfill it with.
    """
    op.add_column("questions", sa.Column("time_spent_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("questions", "time_spent_seconds")
