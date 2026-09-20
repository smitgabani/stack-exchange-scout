"""add scout account fingerprint

Revision ID: c3f8a0b17e42
Revises: b7e2d1a94c55
Create Date: 2026-09-20 00:15:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3f8a0b17e42'
down_revision: str | Sequence[str] | None = 'b7e2d1a94c55'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Yutori exposes no account identifier, so ADR 0004 records which key created
    a remote object as sha256(key)[:16]. Without it, using a key from another
    account fails as `403 "Only the creator of a scout can edit it"` at the
    moment of the edit, rather than being known beforehand.

    Left NULL for the existing row: we cannot know which key created it, and
    guessing would be worse than admitting the gap. It is filled the next time
    a Scout is created or successfully read.
    """
    op.add_column('scouts', sa.Column('account_fingerprint', sa.String(length=32), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('scouts', 'account_fingerprint')
