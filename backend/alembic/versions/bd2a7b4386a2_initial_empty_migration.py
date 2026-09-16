"""initial empty migration

Revision ID: bd2a7b4386a2
Revises: 
Create Date: 2026-09-10 23:23:34.061802

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = 'bd2a7b4386a2'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
