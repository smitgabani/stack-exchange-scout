"""query templates and yutori defaults

Revision ID: e4a7c2d91b60
Revises: d1f4a8c2b953
Create Date: 2026-09-24 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e4a7c2d91b60'
down_revision: str | Sequence[str] | None = 'd1f4a8c2b953'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Two things that were fixed in code become editable (M13):

    * `query_templates` — the text a topics-based scout sends Yutori, with
      placeholders for the profile's topics, concepts and difficulty. Versioned
      exactly like `prompt_templates`: rows are never edited, a save writes a
      new version and activates it, and rolling back is reactivating a row.
      With no active row the built-in template in `query_generator` applies.
    * `yutori_defaults` — the settings every scout starts from (interval,
      timezone, visibility, output schema, …). A single row; scouts store only
      what they override, so a change here reaches every scout that hasn't
      said otherwise.

    Additive: nothing existing is touched, so this is safe to apply before the
    code that uses it is deployed.
    """
    op.create_table(
        'query_templates',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('version', sa.Integer(), nullable=False, unique=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # Exactly one active template, enforced in the database rather than by
    # whichever request happens to write last.
    op.create_index(
        'uq_query_templates_active',
        'query_templates',
        ['is_active'],
        unique=True,
        postgresql_where=sa.text('is_active'),
    )

    op.create_table(
        'yutori_defaults',
        # Always 1: there is one set of defaults. The check makes a second row
        # impossible rather than merely unexpected.
        sa.Column('id', sa.SmallInteger(), primary_key=True),
        sa.Column(
            'settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint('id = 1', name='ck_yutori_defaults_singleton'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('yutori_defaults')
    op.drop_index('uq_query_templates_active', table_name='query_templates')
    op.drop_table('query_templates')
