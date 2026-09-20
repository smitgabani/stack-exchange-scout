"""add challenge formats and JSONB challenge content

Revision ID: c4d9a1e63b57
Revises: b2c6e81f47da
Create Date: 2026-09-20 23:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4d9a1e63b57'
down_revision: str | Sequence[str] | None = 'b2c6e81f47da'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    A challenge was six fixed fields, so asking for anything more — an
    approach outline, a diagram, resources — meant a migration per idea. The
    shape becomes a *format*: a named selection of blocks from a registry the
    code defines, with the generated output stored as JSONB.

    `challenges.content` holds the whole structured result. The six original
    columns stay and are still written for the blocks that map to them, so the
    five challenges that already exist keep rendering with no backfill and the
    digest email, which reads those columns, is untouched.

    `format_name` is denormalised onto the challenge rather than joined,
    matching how `scout_runs.account_label` is handled: the record of what
    produced a challenge has to survive the format being renamed or deleted.
    """
    op.create_table(
        'challenge_formats',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=80), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
        # The selected block keys, in display order. A list rather than a join
        # table: the registry lives in code, so these are not foreign keys to
        # anything, and order is part of the format.
        sa.Column('blocks', postgresql.JSONB(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # Exactly one default, enforced by the database rather than by whichever
    # request writes last.
    op.create_index(
        'uq_challenge_formats_default',
        'challenge_formats',
        ['is_default'],
        unique=True,
        postgresql_where=sa.text('is_default'),
    )

    op.add_column('challenges', sa.Column('content', postgresql.JSONB(), nullable=True))
    op.add_column('challenges', sa.Column('format_name', sa.String(length=80), nullable=True))


def downgrade() -> None:
    """Downgrade schema.

    The six original columns were written all along, so dropping `content`
    loses only the optional blocks — every existing challenge still renders.
    """
    op.drop_column('challenges', 'format_name')
    op.drop_column('challenges', 'content')
    op.drop_index('uq_challenge_formats_default', table_name='challenge_formats')
    op.drop_table('challenge_formats')
