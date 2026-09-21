"""user-defined blocks and per-generation provenance

Revision ID: b4e7f2c81d39
Revises: a91d5c3f7e02
Create Date: 2026-09-21 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b4e7f2c81d39'
down_revision: str | Sequence[str] | None = 'a91d5c3f7e02'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Until now the block library lived entirely in code: a format could choose
    which blocks to include but not what any of them asked the model for, and
    a new block meant a deploy. These two tables make the library editable
    without giving up the property that made it safe — a user-defined block
    names a `kind`, and its schema is derived from that, so the frontend never
    meets a shape it has no renderer for (ADR 0005).

    Three additive changes, nothing existing is altered:

    * `custom_blocks` — blocks the user defined. No schema column on purpose.
    * `block_instructions` — a reworded instruction for a block that ships in
      code. Instruction only; kind and schema stay in code, so an edit cannot
      make `concepts` return a string and fail validation on every run.
    * `challenges.generations` — what was actually sent, per call. A list
      rather than a column because `reformat_challenge` tops a challenge up
      with a second, different instruction, and one column would have to
      either lose the original or omit the addition.
    """
    op.create_table(
        'custom_blocks',
        sa.Column('id', sa.Integer(), nullable=False),
        # Matches the built-in keys: this is what `challenges.content` is
        # keyed by and what the model is asked to return.
        sa.Column('key', sa.String(length=40), nullable=False),
        sa.Column('label', sa.String(length=60), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        # One of challenge_blocks.CUSTOM_KINDS. Not an enum: the list of
        # renderers lives in code and changes with the frontend, and a
        # database enum would need a migration to keep up with it.
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('instruction', sa.Text(), nullable=False),
        sa.Column('gated', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        # Collisions with built-in keys are rejected in the service, which can
        # see the code registry; this only guarantees customs are distinct
        # from each other.
        sa.UniqueConstraint('key', name='uq_custom_blocks_key'),
    )

    op.create_table(
        'block_instructions',
        # The registry key being overridden. Not a foreign key — there is no
        # table to point at — so the service checks membership before storing.
        sa.Column('block_key', sa.String(length=40), nullable=False),
        sa.Column('instruction', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('block_key'),
    )

    op.add_column(
        'challenges',
        sa.Column('generations', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema.

    Formats referencing a custom block survive this as a list of keys that no
    longer resolve, which `resolve` already tolerates — an unknown key is
    skipped rather than raising, so a format falls back to its built-in blocks
    instead of failing to generate.
    """
    op.drop_column('challenges', 'generations')
    op.drop_table('block_instructions')
    op.drop_table('custom_blocks')
