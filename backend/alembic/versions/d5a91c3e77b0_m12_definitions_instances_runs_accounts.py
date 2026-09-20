"""M12: scout definitions, instances, runs, and multi-account credentials

Revision ID: d5a91c3e77b0
Revises: c3f8a0b17e42
Create Date: 2026-09-20 06:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd5a91c3e77b0'
down_revision: str | Sequence[str] | None = 'c3f8a0b17e42'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema (ADR 0004).

    Splits the single `scouts` row into the durable half (a definition the user
    owns) and the disposable half (whatever exists at Yutori), with a run
    ledger joining them. The existing row is carried over rather than dropped —
    it holds the query that has actually been producing candidates.
    """
    op.create_table(
        'scout_definitions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('query_source', sa.String(length=16), nullable=False, server_default='topics'),
        sa.Column('query_text', sa.Text(), nullable=True),
        sa.Column('query_hash', sa.String(length=64), nullable=True),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='draft'),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'ready', 'archived')", name='ck_scout_definitions_status'),
        sa.CheckConstraint("query_source IN ('topics', 'freeform')", name='ck_scout_definitions_query_source'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'scout_instances',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('definition_id', sa.UUID(), nullable=True),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('external_id', sa.String(length=128), nullable=False),
        sa.Column('account_fingerprint', sa.String(length=32), nullable=True),
        sa.Column('state', sa.String(length=24), nullable=True),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("kind IN ('research_task', 'scout')", name='ck_scout_instances_kind'),
        sa.ForeignKeyConstraint(['definition_id'], ['scout_definitions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kind', 'external_id', name='uq_scout_instances_kind_external'),
    )

    op.create_table(
        'scout_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('definition_id', sa.UUID(), nullable=True),
        sa.Column('instance_id', sa.UUID(), nullable=True),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('account_fingerprint', sa.String(length=32), nullable=True),
        sa.Column('account_label', sa.String(length=120), nullable=True),
        sa.Column('cost_usd', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='running'),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_by', sa.String(length=16), nullable=True),
        sa.Column('webhook_event_id', sa.UUID(), nullable=True),
        sa.Column('questions_found', sa.Integer(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'failed', 'timed_out')", name='ck_scout_runs_status'),
        sa.CheckConstraint("kind IN ('research_task', 'scout')", name='ck_scout_runs_kind'),
        sa.ForeignKeyConstraint(['definition_id'], ['scout_definitions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['instance_id'], ['scout_instances.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_scout_runs_definition', 'scout_runs', ['definition_id'], unique=False)
    op.create_index('idx_scout_runs_started_at', 'scout_runs', ['started_at'], unique=False)

    # --- credentials: many keys, one active per provider --------------------
    op.add_column('credentials', sa.Column('label', sa.String(length=120), nullable=True))
    op.add_column('credentials', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('credentials', sa.Column('account_fingerprint', sa.String(length=32), nullable=True))

    # Uniqueness here is a unique *index* (SQLAlchemy's unique=True + index=True
    # produce one index, not a constraint), so it is dropped and recreated
    # without the uniqueness rather than dropped as a constraint — which is
    # what a first attempt tried, and what would have failed mid-migration.
    #
    # Replaced by a partial unique index so several keys can coexist while
    # exactly one per provider is active. Worth holding in the database rather
    # than in a service: picking the wrong key spends someone else's money.
    op.drop_index('ix_credentials_key_name', table_name='credentials')
    op.create_index('ix_credentials_key_name', 'credentials', ['key_name'], unique=False)
    op.create_index(
        'uq_credentials_active_per_provider',
        'credentials',
        ['key_name'],
        unique=True,
        postgresql_where=sa.text('is_active'),
    )
    op.execute("UPDATE credentials SET label = key_name WHERE label IS NULL")

    # --- carry the existing Scout over --------------------------------------
    # Its query is the one that has actually been producing candidates, so it
    # becomes the first definition rather than being discarded. The remote
    # Scout, where one is still referenced, becomes its instance.
    op.execute(
        """
        INSERT INTO scout_definitions
            (id, name, query_source, query_text, query_hash, status, created_at, updated_at)
        SELECT gen_random_uuid(), 'My interests', 'topics', query_text, query_hash,
               CASE WHEN query_text IS NULL THEN 'draft' ELSE 'ready' END,
               created_at, updated_at
        FROM scouts
        LIMIT 1
        """
    )
    op.execute(
        """
        INSERT INTO scout_instances
            (id, definition_id, kind, external_id, account_fingerprint, state, created_at, updated_at)
        SELECT gen_random_uuid(), (SELECT id FROM scout_definitions LIMIT 1), 'scout',
               s.external_scout_id, s.account_fingerprint, s.external_status, s.created_at, s.updated_at
        FROM scouts s
        WHERE s.external_scout_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_credentials_active_per_provider', table_name='credentials')
    op.drop_index('ix_credentials_key_name', table_name='credentials')
    op.create_index('ix_credentials_key_name', 'credentials', ['key_name'], unique=True)
    op.drop_column('credentials', 'account_fingerprint')
    op.drop_column('credentials', 'is_active')
    op.drop_column('credentials', 'label')

    op.drop_index('idx_scout_runs_started_at', table_name='scout_runs')
    op.drop_index('idx_scout_runs_definition', table_name='scout_runs')
    op.drop_table('scout_runs')
    op.drop_table('scout_instances')
    op.drop_table('scout_definitions')
