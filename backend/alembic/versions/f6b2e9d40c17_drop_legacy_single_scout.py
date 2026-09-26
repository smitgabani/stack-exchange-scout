"""drop legacy single scout

Revision ID: f6b2e9d40c17
Revises: e4a7c2d91b60
Create Date: 2026-09-25 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f6b2e9d40c17'
down_revision: str | Sequence[str] | None = 'e4a7c2d91b60'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    `scouts` and `scout_events` belonged to the single-Scout model M12
    replaced; M12's migration already copied what mattered into
    `scout_definitions`, `scout_instances` and `scout_runs`, and no code reads
    them any more. `scout_definitions.query_hash` was written and never read.

    Irreversible for data: downgrade restores the schema, not the rows.
    """
    op.drop_index('idx_scout_events_type', table_name='scout_events')
    op.drop_index('idx_scout_events_created_at', table_name='scout_events')
    op.drop_table('scout_events')
    op.drop_table('scouts')
    op.drop_column('scout_definitions', 'query_hash')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('scout_definitions', sa.Column('query_hash', sa.String(length=64), nullable=True))
    op.create_table(
        'scouts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('external_scout_id', sa.String(length=128), nullable=True),
        sa.Column('query_text', sa.Text(), nullable=True),
        sa.Column('query_hash', sa.String(length=64), nullable=True),
        sa.Column('sync_status', sa.String(length=16), nullable=False),
        sa.Column('last_sync_error', sa.Text(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('run_state', sa.String(length=16), nullable=False, server_default='idle'),
        sa.Column('run_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('run_finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('run_baseline_update_count', sa.Integer(), nullable=True),
        sa.Column('run_kind', sa.String(length=16), nullable=True),
        sa.Column('run_external_id', sa.String(length=128), nullable=True),
        sa.Column('account_fingerprint', sa.String(length=32), nullable=True),
        sa.Column('external_status', sa.String(length=16), nullable=True),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('update_count', sa.Integer(), nullable=True),
        sa.Column('last_update_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.String(length=64), nullable=True),
        sa.Column('detail_refreshed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("run_state IN ('idle', 'running')", name='ck_scouts_run_state'),
        sa.CheckConstraint(
            "run_kind IS NULL OR run_kind IN ('research_task', 'scout')", name='ck_scouts_run_kind'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
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
    op.create_index('idx_scout_events_created_at', 'scout_events', ['created_at'], unique=False)
    op.create_index('idx_scout_events_type', 'scout_events', ['type'], unique=False)
