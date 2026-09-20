"""add account spend override

Revision ID: f1a7c94b28d3
Revises: e8b3d2f56a91
Create Date: 2026-09-20 19:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f1a7c94b28d3'
down_revision: str | Sequence[str] | None = 'e8b3d2f56a91'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Reported spend is the sum of `scout_runs.cost_usd` by account fingerprint,
    which is only ever as complete as the run history. `scout_runs` arrived
    with M12, so anything spent before it — the first research task, the M4
    Scout runs — was never recorded and cannot be recovered from this database.
    The arithmetic is right and the answer is still wrong.

    Rather than guess at the missing rows, the user states the real figure and
    it wins. NULL means "trust the calculation", which stays the default, so
    an account nobody has corrected behaves exactly as before.

    Kept as a separate column from the computed total on purpose: overwriting
    the calculation would destroy the evidence that the two disagree, which is
    the thing worth seeing.
    """
    op.add_column(
        'credentials', sa.Column('spend_override_usd', sa.Numeric(10, 4), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('credentials', 'spend_override_usd')
