"""The editable half of the block library (ADR 0005).

`challenge_blocks` holds the blocks that ship in the code. This module holds
what the user has changed about them — a reworded instruction — and the blocks
they have added themselves, and merges the two into the `Block` list the rest
of the pipeline already understands.

The merge is: start from the code registry, overlay instruction overrides,
append custom blocks. Structure always comes from code; only wording and
selection come from the database. That is what keeps a reworded `concepts`
from quietly starting to return a string and failing `validate` on every run
for the rest of the month.

A custom block never carries a schema. It names a `kind`, and the shape is
looked up from `challenge_blocks.schema_for` — so there is always a renderer
that knows how to draw the result, which is the property the code-only
registry was protecting in the first place.
"""

import logging
import re
from dataclasses import replace
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_block import BlockInstruction, CustomBlock
from app.services import challenge_blocks
from app.services.challenge_blocks import Block

logger = logging.getLogger(__name__)

# Long enough for a paragraph of guidance, short enough that twenty blocks
# cannot silently build a prompt that costs more than the question is worth.
# The whole composed instruction is capped separately by the provider.
MAX_INSTRUCTION_CHARS = 1200

# Same alphabet as the built-in keys, because this becomes a JSON key in
# `challenges.content` and a lookup on the frontend.
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,39}$")


class BlockError(RuntimeError):
    """A block or instruction was rejected before it could be stored."""


def _validate_instruction(instruction: str) -> str:
    """Reject instructions that are empty, oversized, or re-fence the input.

    The `<QUESTION>` check mirrors `prompt_service._validate` and for the same
    reason: a block instruction is concatenated into the system instruction, so
    it reaches the model through exactly the same channel as the guidance does.
    It is not the security boundary — the real fence is added in code, around
    whatever this says — but a template carrying its own fence would produce a
    nested, confusing structure.
    """
    instruction = (instruction or "").strip()
    if not instruction:
        raise BlockError("An instruction cannot be empty.")
    if len(instruction) > MAX_INSTRUCTION_CHARS:
        raise BlockError(
            f"That instruction is too long — keep it under {MAX_INSTRUCTION_CHARS} characters."
        )
    if "<QUESTION>" in instruction.upper():
        raise BlockError(
            "Do not include a <QUESTION> block — the application adds it, along with the "
            "instruction that its contents are untrusted data."
        )
    return instruction


def _validate_key(key: str) -> str:
    key = (key or "").strip().lower()
    if not _KEY_PATTERN.match(key):
        raise BlockError(
            "A key must be 3-40 characters, lowercase, starting with a letter and using only "
            "letters, digits and underscores — for example `review_checklist`."
        )
    if key in challenge_blocks.BY_KEY:
        raise BlockError(
            f"“{key}” is a built-in block. Edit its instruction instead of redefining it."
        )
    return key


def _validate_kind(kind: str) -> str:
    kind = (kind or "").strip()
    if kind not in challenge_blocks.CUSTOM_KINDS:
        raise BlockError(
            f"“{kind}” is not a layout a custom block can use. Choose one of: "
            f"{', '.join(challenge_blocks.CUSTOM_KINDS)}."
        )
    return kind


def to_block(row: CustomBlock) -> Block:
    """A stored row as the `Block` the pipeline expects.

    `column` stays None — the five columns on `challenges` predate the content
    JSONB and belong to core blocks only. `core` stays False, so a custom block
    is never demanded by `validate`: a model that cannot fill one omits it,
    rather than failing the whole generation.
    """
    return Block(
        key=row.key,
        label=row.label,
        description=row.description or "",
        kind=row.kind,
        schema=challenge_blocks.schema_for(row.kind),
        instruction=row.instruction,
        core=False,
        gated=row.gated,
        has_urls=challenge_blocks.kind_has_urls(row.kind),
        column=None,
    )


async def _overrides(db: AsyncSession) -> dict[str, str]:
    rows = await db.scalars(select(BlockInstruction))
    return {row.block_key: row.instruction for row in rows}


async def _customs(db: AsyncSession) -> dict[str, Block]:
    rows = await db.scalars(select(CustomBlock).order_by(CustomBlock.key))
    return {row.key: to_block(row) for row in rows}


async def resolve(db: AsyncSession, keys: list[str] | tuple[str, ...] | None) -> list[Block]:
    """The blocks a format selects, from code and database together.

    The database-aware counterpart to `challenge_blocks.resolve`, which stays
    as the pure path for defaults and tests. Same two guarantees as that one:
    core blocks are always present, and a key that resolves to nothing is
    skipped rather than raised on — a format naming a block that was since
    deleted still generates, an hour after the run that paid for the question.
    """
    overrides = await _overrides(db)
    customs = await _customs(db)

    chosen: list[str] = list(challenge_blocks.CORE_KEYS)
    for key in keys or ():
        if key not in chosen and (key in challenge_blocks.BY_KEY or key in customs):
            chosen.append(key)

    blocks: list[Block] = []
    for key in chosen:
        if key in challenge_blocks.BY_KEY:
            block = challenge_blocks.BY_KEY[key]
            if key in overrides:
                # Only the wording. Kind, schema and the core/gated flags are
                # whatever the code says they are.
                block = replace(block, instruction=overrides[key])
            blocks.append(block)
        else:
            blocks.append(customs[key])
    return blocks


async def known_keys(db: AsyncSession) -> set[str]:
    """Every key a format may legally name, built-in or custom."""
    rows = await db.scalars(select(CustomBlock.key))
    return set(challenge_blocks.BY_KEY) | set(rows)


# --- the library, for the editor ----------------------------------------


async def catalogue(db: AsyncSession) -> list[dict[str, Any]]:
    """The whole library with effective instructions, for the block editor.

    Each entry says what the instruction currently is and what it would revert
    to, so the editor can offer "reset" without having to know the defaults.
    """
    overrides = await _overrides(db)
    rows = await db.scalars(select(CustomBlock).order_by(CustomBlock.key))

    entries: list[dict[str, Any]] = [
        {
            "key": block.key,
            "label": block.label,
            "description": block.description,
            "kind": block.kind,
            "core": block.core,
            "gated": block.gated,
            "has_urls": block.has_urls,
            "custom": False,
            "instruction": overrides.get(block.key, block.instruction),
            "default_instruction": block.instruction,
            "is_overridden": block.key in overrides,
        }
        for block in challenge_blocks.BLOCKS
    ]
    entries.extend(
        {
            "key": row.key,
            "label": row.label,
            "description": row.description or "",
            "kind": row.kind,
            "core": False,
            "gated": row.gated,
            "has_urls": challenge_blocks.kind_has_urls(row.kind),
            "custom": True,
            "instruction": row.instruction,
            "default_instruction": None,
            "is_overridden": False,
        }
        for row in rows
    )
    return entries


# --- custom blocks -------------------------------------------------------


async def create_custom(
    db: AsyncSession,
    *,
    key: str,
    label: str,
    kind: str,
    instruction: str,
    description: str | None = None,
    gated: bool = False,
) -> CustomBlock:
    key = _validate_key(key)
    kind = _validate_kind(kind)
    instruction = _validate_instruction(instruction)

    label = (label or "").strip()
    if not label:
        raise BlockError("A block needs a label — it is the heading on the challenge page.")
    if len(label) > 60:
        raise BlockError("That label is too long.")

    existing = await db.scalar(select(CustomBlock).where(CustomBlock.key == key))
    if existing is not None:
        raise BlockError(f"A block with the key “{key}” already exists.")

    row = CustomBlock(
        key=key,
        label=label,
        description=(description or "").strip() or None,
        kind=kind,
        instruction=instruction,
        gated=gated,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info("Custom block %s created (kind=%s, gated=%s)", row.key, row.kind, row.gated)
    return row


async def update_custom(
    db: AsyncSession,
    block_id: int,
    *,
    label: str,
    kind: str,
    instruction: str,
    description: str | None = None,
    gated: bool = False,
) -> CustomBlock | None:
    """Edit a custom block. The key is deliberately not editable.

    Changing it would orphan the values already stored under the old key in
    every `challenges.content` that has one — they would stop rendering with
    no indication why.
    """
    row = await db.get(CustomBlock, block_id)
    if row is None:
        return None

    kind = _validate_kind(kind)
    instruction = _validate_instruction(instruction)
    label = (label or "").strip()
    if not label:
        raise BlockError("A block needs a label — it is the heading on the challenge page.")

    row.label = label
    row.description = (description or "").strip() or None
    row.kind = kind
    row.instruction = instruction
    row.gated = gated
    await db.commit()
    await db.refresh(row)
    return row


async def delete_custom(db: AsyncSession, block_id: int) -> bool:
    """Remove a custom block. Challenges that already have its output keep it.

    The value stays in `challenges.content`, but nothing resolves the key any
    more, so it stops being rendered — the same thing that happens to a block
    deleted from the code registry.
    """
    row = await db.get(CustomBlock, block_id)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    logger.info("Custom block %s deleted", row.key)
    return True


# --- instruction overrides ----------------------------------------------


async def set_instruction(db: AsyncSession, block_key: str, instruction: str) -> str:
    """Reword a built-in block. Custom blocks are edited through `update_custom`."""
    if block_key not in challenge_blocks.BY_KEY:
        raise BlockError(f"“{block_key}” is not a built-in block.")
    instruction = _validate_instruction(instruction)

    row = await db.get(BlockInstruction, block_key)
    if row is None:
        db.add(BlockInstruction(block_key=block_key, instruction=instruction))
    else:
        row.instruction = instruction
    await db.commit()
    logger.info("Instruction for built-in block %s overridden", block_key)
    return instruction


async def reset_instruction(db: AsyncSession, block_key: str) -> str:
    """Drop the override, returning the block to the instruction in the code."""
    if block_key not in challenge_blocks.BY_KEY:
        raise BlockError(f"“{block_key}” is not a built-in block.")
    await db.execute(delete(BlockInstruction).where(BlockInstruction.block_key == block_key))
    await db.commit()
    return challenge_blocks.BY_KEY[block_key].instruction
