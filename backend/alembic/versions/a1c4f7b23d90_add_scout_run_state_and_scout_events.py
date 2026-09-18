"""add scout run state and scout_events

Revision ID: a1c4f7b23d90
Revises: 65551c6e0e28
Create Date: 2026-09-17 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1c4f7b23d90'
down_revision: str | Sequence[str] | None = '65551c6e0e28'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Our own run state, plus the fields mirrored from Yutori's scout detail so
    # the Scout page can show real values instead of guesses.
    op.add_column('scouts', sa.Column('run_state', sa.String(length=16), nullable=False, server_default='idle'))
    op.add_column('scouts', sa.Column('run_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('scouts', sa.Column('run_finished_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('scouts', sa.Column('run_baseline_update_count', sa.Integer(), nullable=True))
    op.add_column('scouts', sa.Column('external_status', sa.String(length=16), nullable=True))
    op.add_column('scouts', sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('scouts', sa.Column('update_count', sa.Integer(), nullable=True))
    op.add_column('scouts', sa.Column('last_update_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('scouts', sa.Column('rejection_reason', sa.String(length=64), nullable=True))
    op.add_column('scouts', sa.Column('detail_refreshed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint('ck_scouts_run_state', 'scouts', "run_state IN ('idle', 'running')")

    op.create_table(
        'scout_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('scout_id', sa.UUID(), nullable=True),
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('query_text', sa.Text(), nullable=True),
        sa.Column('query_hash', sa.String(length=64), nullable=True),
        sa.Column('external_update_id', sa.String(length=128), nullable=True),
        sa.Column('cost_usd', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "type IN ('query_synced', 'run_started', 'update_received', 'parked', 'error')",
            name='ck_scout_events_type',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    # The page reads this newest-first, and the spend total filters by type.
    op.create_index('idx_scout_events_created_at', 'scout_events', ['created_at'], unique=False)
    op.create_index('idx_scout_events_type', 'scout_events', ['type'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_scout_events_type', table_name='scout_events')
    op.drop_index('idx_scout_events_created_at', table_name='scout_events')
    op.drop_table('scout_events')

    op.drop_constraint('ck_scouts_run_state', 'scouts', type_='check')
    for column in (
        'detail_refreshed_at',
        'rejection_reason',
        'last_update_at',
        'update_count',
        'next_run_at',
        'external_status',
        'run_baseline_update_count',
        'run_finished_at',
        'run_started_at',
        'run_state',
    ):
        op.drop_column('scouts', column)
