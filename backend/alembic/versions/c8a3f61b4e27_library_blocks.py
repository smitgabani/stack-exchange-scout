"""move the optional blocks out of code and into the library table

Revision ID: c8a3f61b4e27
Revises: b4e7f2c81d39
Create Date: 2026-09-22 01:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c8a3f61b4e27'
down_revision: str | Sequence[str] | None = 'b4e7f2c81d39'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The nine blocks that lived in `challenge_blocks.BLOCKS` and are moving here
# verbatim: same keys, same kinds, same wording. Existing challenges store
# their content under these keys and existing formats name them, so nothing
# may change but where they are read from.
SEED = [
        {
            'key': 'prerequisites',
            'label': 'You should know',
            'description': 'What to understand before attempting this.',
            'kind': 'chips',
            'instruction': (
                'List the prerequisite knowledge someone needs before attempting this, as short topic names. Do not explain the solution.'
            ),
            'gated': False,
        },
        {
            'key': 'glossary',
            'label': 'Terms',
            'description': 'Unfamiliar terms from the question, defined.',
            'kind': 'definition_list',
            'instruction': (
                'Define any jargon or library-specific terms appearing in the question that a competent developer new to this area would not know. Define the term itself, not its role in the fix.'
            ),
            'gated': False,
        },
        {
            'key': 'visualisation',
            'label': 'Picture it',
            'description': 'A diagram of the situation, drawn as Mermaid.',
            'kind': 'diagram',
            'instruction': (
                'Draw the situation as a Mermaid diagram — a flowchart, sequence diagram or state diagram, whichever fits. Return only valid Mermaid source in the `mermaid` field, with no markdown fences. Diagram the problem as described, never the fix.'
            ),
            'gated': False,
        },
        {
            'key': 'approach_outline',
            'label': 'How to approach it',
            'description': 'Ordered steps for investigating, not solving.',
            'kind': 'steps',
            'instruction': (
                'Outline an ordered investigation plan: what to check, measure or rule out, in order. Describe how to find the cause, never what the cause is.'
            ),
            'gated': False,
        },
        {
            'key': 'common_pitfalls',
            'label': 'Common pitfalls',
            'description': 'Mistakes people make on problems like this.',
            'kind': 'list',
            'instruction': (
                "List mistakes people commonly make on problems of this kind. Keep them general to the category of problem rather than specific to this bug's resolution."
            ),
            'gated': False,
        },
        {
            'key': 'self_check',
            'label': 'Check yourself',
            'description': 'How to know your solution is actually right.',
            'kind': 'checklist',
            'instruction': (
                'List checks the user can run against their own solution to know whether it is correct — properties it must satisfy, cases it must handle. Do not state what the solution is.'
            ),
            'gated': False,
        },
        {
            'key': 'time_estimate',
            'label': 'Time',
            'description': 'Roughly how long this should take.',
            'kind': 'stat',
            'instruction': (
                "Estimate how long this should take a competent developer, as a short phrase such as '30-60 minutes', with one sentence of rationale."
            ),
            'gated': False,
        },
        {
            'key': 'learning_resources',
            'label': 'Learn the concepts',
            'description': 'Documentation and guides for the underlying ideas.',
            'kind': 'resource_list',
            'instruction': (
                'Suggest documentation or guides that teach the underlying concepts. These must be about the general topic, never about this specific question or its resolution. Prefer official documentation. Give a real, complete URL you are confident exists; if you are not confident a URL is real, omit that resource entirely.'
            ),
            'gated': False,
        },
        {
            'key': 'solution_resources',
            'label': "If you're stuck",
            'description': 'Material that addresses this specific problem. Hidden until every hint is revealed.',
            'kind': 'resource_list',
            'instruction': (
                'Suggest material that addresses this specific problem directly, for someone who has given up solving it alone. Give a real, complete URL you are confident exists; if you are not confident a URL is real, omit that resource entirely.'
            ),
            'gated': True,
        },
    ]


def upgrade() -> None:
    """Upgrade schema.

    ADR 0005 left the library in two halves: blocks in code, which could only
    be reworded, and blocks in the database, which could be anything. The
    split was not where users expected it. Of the fifteen built-ins, six are
    genuinely structural — they are NOT NULL columns on `challenges`, they are
    what `validate` demands on every generation, and the digest email reads
    them directly. The other nine live only in `content` JSONB and nothing
    depends on their shape.

    So the nine move here, becoming ordinary library rows: editable, including
    their layout, and deletable. The six stay in code, where the app's own
    contract can keep depending on them.

    Seeded rather than left to the application, so a format that already names
    `glossary` keeps resolving across the deploy rather than losing the block
    until something recreates it.
    """
    # `custom_blocks` no longer means "the ones the user made" — it is now the
    # whole editable library, most of which shipped with the app.
    op.rename_table('custom_blocks', 'library_blocks')

    blocks = sa.table(
        'library_blocks',
        sa.column('key', sa.String),
        sa.column('label', sa.String),
        sa.column('description', sa.Text),
        sa.column('kind', sa.String),
        sa.column('instruction', sa.Text),
        sa.column('gated', sa.Boolean),
    )

    # A reworded instruction already overrides the code default, so it wins
    # over the seeded wording — otherwise this migration would silently undo
    # an edit the user had made before the move.
    connection = op.get_bind()
    overrides = dict(
        connection.execute(
            sa.text("SELECT block_key, instruction FROM block_instructions")
        ).fetchall()
    )

    existing = {
        row[0]
        for row in connection.execute(sa.text("SELECT key FROM library_blocks")).fetchall()
    }

    rows = [
        {**block, 'instruction': overrides.get(block['key'], block['instruction'])}
        for block in SEED
        if block['key'] not in existing
    ]
    if rows:
        op.bulk_insert(blocks, rows)

    # Their overrides have been folded into the rows above; the table now
    # holds overrides for the six core blocks only.
    if overrides:
        connection.execute(
            sa.text(
                "DELETE FROM block_instructions WHERE block_key = ANY(:keys)"
            ),
            {"keys": [b['key'] for b in SEED]},
        )


def downgrade() -> None:
    """Downgrade schema.

    The nine seeded rows are removed, which returns them to being served from
    code. A block the user edited loses that edit, and one they deleted comes
    back — both are the point of going back.
    """
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM library_blocks WHERE key = ANY(:keys)"),
        {"keys": [b['key'] for b in SEED]},
    )
    op.rename_table('library_blocks', 'custom_blocks')
