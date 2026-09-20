"""add scout run kind and external run id

Revision ID: b7e2d1a94c55
Revises: a1c4f7b23d90
Create Date: 2026-09-19 23:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7e2d1a94c55'
down_revision: str | Sequence[str] | None = 'a1c4f7b23d90'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    A run can now be either a one-shot research task or a Scout (ADR 0004), so
    the row has to say which — a research task is polled at a different
    endpoint and has no Scout to park afterwards. Kept on `scouts` rather than
    introducing M12's `scout_runs` table yet: this is the smallest change that
    makes a real research run possible, and M12-B1 migrates it properly.
    """
    op.add_column('scouts', sa.Column('run_kind', sa.String(length=16), nullable=True))
    op.add_column('scouts', sa.Column('run_external_id', sa.String(length=128), nullable=True))
    op.create_check_constraint(
        'ck_scouts_run_kind',
        'scouts',
        "run_kind IS NULL OR run_kind IN ('research_task', 'scout')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_scouts_run_kind', 'scouts', type_='check')
    op.drop_column('scouts', 'run_external_id')
    op.drop_column('scouts', 'run_kind')
