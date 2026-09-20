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
"""

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


def _resource_schema() -> dict[str, Any]:
    return {
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
    }


BLOCKS: tuple[Block, ...] = (
    # --- core: always present ---
    Block(
        key="problem_summary",
        label="Problem",
        description="What the question is actually asking, in plain terms.",
        kind="prose",
        column="problem_summary",
        core=True,
        schema={"type": "string"},
        instruction="Explain the problem concisely.",
    ),
    Block(
        key="why_interesting",
        label="Why this one",
        description="Why this question is worth your time.",
        kind="prose",
        column="why_interesting",
        core=True,
        schema={"type": "string"},
        instruction="Explain why the question is interesting.",
    ),
    Block(
        key="concepts",
        label="Concepts",
        description="The technical ideas involved.",
        kind="chips",
        column="concepts",
        core=True,
        schema={"type": "array", "items": {"type": "string"}},
        instruction="Identify the technical concepts involved.",
    ),
    Block(
        key="starting_direction",
        label="Start here",
        description="Where to begin, without giving the answer.",
        kind="prose",
        column="starting_direction",
        core=True,
        schema={"type": "string"},
        instruction="Give the user a useful starting direction.",
    ),
    Block(
        key="hints",
        label="Hints",
        description="Three progressive hints, revealed one at a time.",
        kind="progressive_hints",
        column="hints",
        core=True,
        schema={
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "text": {"type": "string"}},
                "required": ["label", "text"],
            },
        },
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
        schema={"type": "integer"},
        instruction="Estimate difficulty from 1 to 5.",
    ),
    # --- optional: understanding the problem ---
    Block(
        key="prerequisites",
        label="You should know",
        description="What to understand before attempting this.",
        kind="chips",
        schema={"type": "array", "items": {"type": "string"}},
        instruction=(
            "List the prerequisite knowledge someone needs before attempting this, as short "
            "topic names. Do not explain the solution."
        ),
    ),
    Block(
        key="glossary",
        label="Terms",
        description="Unfamiliar terms from the question, defined.",
        kind="definition_list",
        schema={
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"term": {"type": "string"}, "definition": {"type": "string"}},
                "required": ["term", "definition"],
            },
        },
        instruction=(
            "Define any jargon or library-specific terms appearing in the question that a "
            "competent developer new to this area would not know. Define the term itself, not "
            "its role in the fix."
        ),
    ),
    Block(
        key="visualisation",
        label="Picture it",
        description="A diagram of the situation, drawn as Mermaid.",
        kind="diagram",
        schema={
            "type": "object",
            "properties": {
                "caption": {"type": "string"},
                "mermaid": {"type": "string"},
            },
            "required": ["mermaid"],
        },
        instruction=(
            "Draw the situation as a Mermaid diagram — a flowchart, sequence diagram or state "
            "diagram, whichever fits. Return only valid Mermaid source in the `mermaid` field, "
            "with no markdown fences. Diagram the problem as described, never the fix."
        ),
    ),
    # --- optional: attacking it ---
    Block(
        key="approach_outline",
        label="How to approach it",
        description="Ordered steps for investigating, not solving.",
        kind="steps",
        schema={
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"step": {"type": "string"}, "detail": {"type": "string"}},
                "required": ["step"],
            },
        },
        instruction=(
            "Outline an ordered investigation plan: what to check, measure or rule out, in "
            "order. Describe how to find the cause, never what the cause is."
        ),
    ),
    Block(
        key="common_pitfalls",
        label="Common pitfalls",
        description="Mistakes people make on problems like this.",
        kind="list",
        schema={"type": "array", "items": {"type": "string"}},
        instruction=(
            "List mistakes people commonly make on problems of this kind. Keep them general to "
            "the category of problem rather than specific to this bug's resolution."
        ),
    ),
    Block(
        key="self_check",
        label="Check yourself",
        description="How to know your solution is actually right.",
        kind="checklist",
        schema={"type": "array", "items": {"type": "string"}},
        instruction=(
            "List checks the user can run against their own solution to know whether it is "
            "correct — properties it must satisfy, cases it must handle. Do not state what the "
            "solution is."
        ),
    ),
    Block(
        key="time_estimate",
        label="Time",
        description="Roughly how long this should take.",
        kind="stat",
        schema={
            "type": "object",
            "properties": {
                "value": {"type": "string"},
                "rationale": {"type": "string"},
            },
            "required": ["value"],
        },
        instruction=(
            "Estimate how long this should take a competent developer, as a short phrase such "
            "as '30-60 minutes', with one sentence of rationale."
        ),
    ),
    # --- optional: resources ---
    Block(
        key="learning_resources",
        label="Learn the concepts",
        description="Documentation and guides for the underlying ideas.",
        kind="resource_list",
        has_urls=True,
        schema=_resource_schema(),
        instruction=(
            "Suggest documentation or guides that teach the underlying concepts. These must be "
            "about the general topic, never about this specific question or its resolution. "
            "Prefer official documentation. Give a real, complete URL you are confident exists; "
            "if you are not confident a URL is real, omit that resource entirely."
        ),
    ),
    Block(
        key="solution_resources",
        label="If you're stuck",
        description="Material that addresses this specific problem. Hidden until every hint is revealed.",
        kind="resource_list",
        gated=True,
        has_urls=True,
        schema=_resource_schema(),
        instruction=(
            "Suggest material that addresses this specific problem directly, for someone who "
            "has given up solving it alone. Give a real, complete URL you are confident exists; "
            "if you are not confident a URL is real, omit that resource entirely."
        ),
    ),
)

BY_KEY: dict[str, Block] = {block.key: block for block in BLOCKS}
CORE_KEYS: tuple[str, ...] = tuple(b.key for b in BLOCKS if b.core)
# The format every challenge used before formats existed.
LEGACY_KEYS: tuple[str, ...] = CORE_KEYS


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
    """The structured-output schema for this selection of blocks."""
    return {
        "type": "object",
        "properties": {block.key: block.schema for block in blocks},
        # Only the core text fields are demanded. An optional block the model
        # cannot fill for a given question is better omitted than invented.
        "required": [b.key for b in blocks if b.core and b.key != "estimated_difficulty"],
    }


def build_instructions(blocks: list[Block]) -> str:
    """The numbered list of what to produce, one line per block."""
    lines = [f"{index}. {block.instruction}" for index, block in enumerate(blocks, start=1)]
    return "\n".join(lines)


def catalogue() -> list[dict[str, Any]]:
    """The block library, for the format editor."""
    return [
        {
            "key": block.key,
            "label": block.label,
            "description": block.description,
            "kind": block.kind,
            "core": block.core,
            "gated": block.gated,
            "has_urls": block.has_urls,
        }
        for block in BLOCKS
    ]
