"""The vocabulary a challenge can be built from.

A format is a selection of these blocks, not an arbitrary JSON Schema. Each
block declares four things in one place:

* `schema`   — its fragment of the structured output sent to the provider
* `instruction` — what the model is told to produce for it
* `kind`     — which renderer draws it on the frontend
* `gated`    — whether it sits behind the final reveal

Keeping those together is the point. An arbitrary schema would leave the UI
rendering key/value dumps and would leave every new field unvalidated, because
the app would have no idea what the field meant. Here, adding a capability
means adding a block and a renderer for its `kind` — the system never has to
handle a shape it has never seen.

What is left here is only what the app's own contract depends on: six blocks
that are NOT NULL columns on `challenges`, that `validate` demands on every
generation, and that the digest email reads directly. They can be reworded but
not reshaped, and they cannot be removed.

Every other block lives in `library_blocks`, where it can be edited, re-laid
out or deleted like any block the user writes themselves — nothing structural
depends on those, they exist only inside `content`. `block_service.resolve`
merges the two. The guarantee above still holds either way, because a stored
block picks a `kind` rather than writing a schema: its shape comes from
`_SCHEMA_BY_KIND`, so it is still a shape the UI knows how to draw.
"""

import copy
from dataclasses import dataclass, field
from typing import Any

# Renderer names the frontend switches on. A block may only use a kind the UI
# knows how to draw, which is asserted by a test rather than left to habit.
KINDS = (
    "prose",
    "chips",
    "progressive_hints",
    "rating",
    "steps",
    "list",
    "resource_list",
    "definition_list",
    "checklist",
    "stat",
    "diagram",
)

# The shape each kind implies. This is what makes user-defined blocks possible
# without letting anyone write a JSON Schema: a custom block picks a kind, and
# its schema follows from that choice, so there is always a renderer that knows
# what to do with the result.
#
# Every block below builds its schema from here too, so a custom `checklist`
# and the built-in `self_check` are guaranteed to ask for the same shape rather
# than merely happening to agree today.
_SCHEMA_BY_KIND: dict[str, dict[str, Any]] = {
    "prose": {"type": "string"},
    "chips": {"type": "array", "items": {"type": "string"}},
    "list": {"type": "array", "items": {"type": "string"}},
    "checklist": {"type": "array", "items": {"type": "string"}},
    "rating": {"type": "integer"},
    "progressive_hints": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"label": {"type": "string"}, "text": {"type": "string"}},
            "required": ["label", "text"],
        },
    },
    "steps": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"step": {"type": "string"}, "detail": {"type": "string"}},
            "required": ["step"],
        },
    },
    "definition_list": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"term": {"type": "string"}, "definition": {"type": "string"}},
            "required": ["term", "definition"],
        },
    },
    "resource_list": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "url": {"type": "string"},
                "why": {"type": "string"},
            },
            "required": ["title", "url", "why"],
        },
    },
    "stat": {
        "type": "object",
        "properties": {"value": {"type": "string"}, "rationale": {"type": "string"}},
        "required": ["value"],
    },
    "diagram": {
        "type": "object",
        "properties": {"caption": {"type": "string"}, "mermaid": {"type": "string"}},
        "required": ["mermaid"],
    },
}

# What a user-defined block may choose. Two kinds are deliberately withheld:
# `progressive_hints` is special-cased by `_normalise_hints` and demanded by
# `validate`, and `rating` is bound to the `estimated_difficulty` column. A
# second block of either kind would be silently mishandled rather than simply
# rendered, so the picker does not offer them.
_RESERVED_KINDS = frozenset({"progressive_hints", "rating"})
CUSTOM_KINDS: tuple[str, ...] = tuple(k for k in KINDS if k not in _RESERVED_KINDS)

# Kinds whose values carry URLs that must resolve before the challenge is
# stored. Derived from the kind so a custom resource list is link-checked on
# the same terms as the built-in ones.
_URL_KINDS = frozenset({"resource_list"})


def schema_for(kind: str) -> dict[str, Any]:
    """A fresh copy of the schema a kind implies.

    Copied rather than shared: `build_schema` embeds these by reference into
    the schema sent to the provider, and a caller mutating that result would
    otherwise be editing the registry itself.
    """
    return copy.deepcopy(_SCHEMA_BY_KIND[kind])


def kind_has_urls(kind: str) -> bool:
    return kind in _URL_KINDS


@dataclass(frozen=True)
class Block:
    key: str
    label: str
    description: str
    kind: str
    schema: dict[str, Any]
    instruction: str
    # Core blocks are the five fields tdd.md §8.7 requires plus difficulty;
    # they cannot be switched off, and legacy challenges have exactly these.
    core: bool = False
    # Shown only after the last hint has been revealed.
    gated: bool = False
    # Whose `url` fields are checked before the challenge is stored.
    has_urls: bool = False
    # Columns on `challenges` that this block also populates, for the five
    # fields that predate the JSONB content column.
    column: str | None = None
    examples: list[str] = field(default_factory=list)


BLOCKS: tuple[Block, ...] = (
    # --- core: always present ---
    Block(
        key="problem_summary",
        label="Problem",
        description="What the question is actually asking, in plain terms.",
        kind="prose",
        column="problem_summary",
        core=True,
        schema=schema_for("prose"),
        instruction="Explain the problem concisely.",
    ),
    Block(
        key="why_interesting",
        label="Why this one",
        description="Why this question is worth your time.",
        kind="prose",
        column="why_interesting",
        core=True,
        schema=schema_for("prose"),
        instruction="Explain why the question is interesting.",
    ),
    Block(
        key="concepts",
        label="Concepts",
        description="The technical ideas involved.",
        kind="chips",
        column="concepts",
        core=True,
        schema=schema_for("chips"),
        instruction="Identify the technical concepts involved.",
    ),
    Block(
        key="starting_direction",
        label="Start here",
        description="Where to begin, without giving the answer.",
        kind="prose",
        column="starting_direction",
        core=True,
        schema=schema_for("prose"),
        instruction="Give the user a useful starting direction.",
    ),
    Block(
        key="hints",
        label="Hints",
        description="Three progressive hints, revealed one at a time.",
        kind="progressive_hints",
        column="hints",
        core=True,
        schema=schema_for("progressive_hints"),
        instruction=(
            "Provide exactly three progressive hints: the first points at the relevant area, "
            "the second names the important concept, the third gets close to the solution "
            "without giving it."
        ),
    ),
    Block(
        key="estimated_difficulty",
        label="Difficulty",
        description="The model's own 1-5 estimate.",
        kind="rating",
        column="estimated_difficulty",
        core=True,
        schema=schema_for("rating"),
        instruction="Estimate difficulty from 1 to 5.",
    ),
)

BY_KEY: dict[str, Block] = {block.key: block for block in BLOCKS}
# Every block here is core now; the tuple is kept because the rest of the
# pipeline asks "what must always be present" rather than "what is in code".
CORE_KEYS: tuple[str, ...] = tuple(b.key for b in BLOCKS if b.core)


def resolve(keys: list[str] | tuple[str, ...] | None) -> list[Block]:
    """The blocks a format selects, always including the core ones.

    Core blocks are added rather than validated for, so a format saved with a
    typo still produces a usable challenge instead of failing at generation
    time — an hour after the run that paid for the question.
    """
    chosen = list(CORE_KEYS)
    for key in keys or ():
        if key in BY_KEY and key not in chosen:
            chosen.append(key)
    return [BY_KEY[key] for key in chosen]


def build_schema(blocks: list[Block]) -> dict[str, Any]:
    """The structured-output schema for this selection of blocks.

    Every selected block is required. Marking only the core fields was the
    original instinct — an optional block the model cannot fill is better
    omitted than invented — but in practice it meant the model simply declined
    the harder ones: a nine-block format returned two. Turning a block on is a
    request, so the schema states it as one, and quality is handled where it
    belongs, in validation and link checking.
    """
    return {
        "type": "object",
        "properties": {block.key: block.schema for block in blocks},
        "required": [block.key for block in blocks],
    }


def build_instructions(blocks: list[Block]) -> str:
    """The numbered list of what to produce, one line per block."""
    lines = [f"{index}. {block.instruction}" for index, block in enumerate(blocks, start=1)]
    return "\n".join(lines)
