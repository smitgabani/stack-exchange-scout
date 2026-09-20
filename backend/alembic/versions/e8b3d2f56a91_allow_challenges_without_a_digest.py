"""allow challenges without a digest

Revision ID: e8b3d2f56a91
Revises: d5a91c3e77b0
Create Date: 2026-09-20 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e8b3d2f56a91'
down_revision: str | Sequence[str] | None = 'd5a91c3e77b0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    A challenge could only exist as part of a digest, which made "I want this
    question as a challenge" impossible to express: the digest is chosen by the
    scoring formula, and a question the formula passed over has no digest to
    belong to.

    The alternative was to synthesise a digest per promotion, which was
    rejected: `POST /digest/send` with no argument sends the most recent digest
    whose status is `generated`, so an ad-hoc digest would silently become the
    thing the next send emails.

    `uq_challenges_digest_question` still prevents a duplicate inside one
    digest, but NULLs compare as distinct in Postgres, so it cannot stop a
    question being promoted twice. The partial index below does exactly that
    and only for manual rows.
    """
    op.alter_column('challenges', 'digest_id', existing_type=sa.UUID(), nullable=True)
    op.create_index(
        'uq_challenges_manual_question',
        'challenges',
        ['question_id'],
        unique=True,
        postgresql_where=sa.text('digest_id IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema.

    Manual challenges have no digest to fall back to, so they are dropped
    rather than reassigned — inventing a digest for them on the way down would
    put rows into the digest history that were never sent.
    """
    op.drop_index('uq_challenges_manual_question', table_name='challenges')
    op.execute('DELETE FROM challenges WHERE digest_id IS NULL')
    op.alter_column('challenges', 'digest_id', existing_type=sa.UUID(), nullable=False)
