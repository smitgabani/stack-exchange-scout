"""add question solved_at

Revision ID: a91d5c3f7e02
Revises: c4d9a1e63b57
Create Date: 2026-09-21 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a91d5c3f7e02'
down_revision: str | Sequence[str] | None = 'c4d9a1e63b57'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    `QUESTION_STATUSES` has carried `solved` since M5, unused — M8 (Feedback)
    was meant to be what set it, and M8 has not been built. Marking a
    challenge complete needs exactly that state, plus a timestamp the original
    enum never got: without one, "completed 3 days ago" cannot be shown, only
    "completed at some point".
    """
    op.add_column('questions', sa.Column('solved_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('questions', 'solved_at')
