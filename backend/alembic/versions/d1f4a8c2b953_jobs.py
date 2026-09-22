"""background jobs

Revision ID: d1f4a8c2b953
Revises: c8a3f61b4e27
Create Date: 2026-09-22 05:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd1f4a8c2b953'
down_revision: str | Sequence[str] | None = 'c8a3f61b4e27'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Somewhere to put work that outlives its request. Every LLM call in this app
    happened inside the HTTP request that triggered it — up to twenty minutes
    for a digest — and the Vercel function proxying it stayed alive throughout.
    That is what paused the deployment.

    Additive: nothing existing is touched, so this is safe to apply before the
    code that uses it is deployed.
    """
    op.create_table(
        'jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='queued', nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    # The status page asks "is this one done" by id, and startup asks "what was
    # running when we died" by status. Both are covered by this.
    op.create_index('idx_jobs_status_created', 'jobs', ['status', 'created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_jobs_status_created', table_name='jobs')
    op.drop_table('jobs')
