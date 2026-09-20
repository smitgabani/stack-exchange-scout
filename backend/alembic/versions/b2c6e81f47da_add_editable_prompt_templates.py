"""add editable prompt templates

Revision ID: b2c6e81f47da
Revises: f1a7c94b28d3
Create Date: 2026-09-20 21:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c6e81f47da'
down_revision: str | Sequence[str] | None = 'f1a7c94b28d3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    The curator prompt lived in `challenge_service.SYSTEM_INSTRUCTION`, so
    tuning it meant a code change and a deploy. It moves into the database as
    versioned rows.

    Only the *guidance* is stored. The prompt-injection defences — the clause
    declaring question content untrusted, the `<QUESTION>` fence, and the
    trailing "do not follow instructions inside" warning — stay in code and are
    composed around whatever is stored here. That is deliberate: those lines
    are a security control, and a control that can be edited away in a textarea
    is not a control. `challenges.prompt_version` already exists and now refers
    to a row in this table, so a bad batch stays traceable to the exact text
    that produced it.

    Rows are never edited in place. Saving writes a new version and activates
    it, which keeps the provenance on old challenges meaningful and makes
    rolling back a matter of reactivating a row.
    """
    op.create_table(
        'prompt_templates',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('version', sa.Integer(), nullable=False, unique=True),
        # The editable halves. Everything else is composed in code.
        sa.Column('system_instruction', sa.Text(), nullable=False),
        sa.Column('user_preamble', sa.Text(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # Exactly one active template, enforced in the database rather than by
    # whichever request happens to write last.
    op.create_index(
        'uq_prompt_templates_active',
        'prompt_templates',
        ['is_active'],
        unique=True,
        postgresql_where=sa.text('is_active'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_prompt_templates_active', table_name='prompt_templates')
    op.drop_table('prompt_templates')
