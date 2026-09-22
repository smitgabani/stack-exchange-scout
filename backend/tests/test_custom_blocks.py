"""User-defined blocks and reworded instructions (ADR 0005).

The point of this feature is that the block library stops being code-only. The
point of these tests is that making it editable did not cost the guarantee that
made it safe: a block still cannot arrive on the page in a shape the UI has no
renderer for, and a reworded instruction still cannot change a block's shape.

Rows in `library_blocks` and `block_instructions` are removed by the fixture.
"""

import pytest
from sqlalchemy import delete, select

from app.core.db import async_session
from app.models.library_block import BlockInstruction, LibraryBlock
from app.services import (
    block_service,
    challenge_blocks,
    challenge_service,
    format_service,
)

# Keys these tests create. Named explicitly because `library_blocks` is no
# longer a scratch table: since the optional blocks moved into it, a blanket
# DELETE wipes nine blocks that shipped with the app — out of the user's live
# library, not just the test's. Only what a test made is removed.
TEST_KEYS = ("review_checklist", "further_reading", "last_resort")

# Seeded by migration c8a3f61b4e27 when the optional blocks left the code.
SHIPPED_KEYS = {
    "prerequisites",
    "glossary",
    "visualisation",
    "approach_outline",
    "common_pitfalls",
    "self_check",
    "time_estimate",
    "learning_resources",
    "solution_resources",
}


@pytest.fixture
async def clean_blocks():
    yield
    async with async_session() as session:
        await session.execute(delete(LibraryBlock).where(LibraryBlock.key.in_(TEST_KEYS)))
        await session.execute(delete(BlockInstruction))
        await session.commit()


def _payload(**extra) -> dict:
    base = {
        "problem_summary": "Coroutines appear to execute one after another.",
        "why_interesting": "It exercises how the event loop schedules work.",
        "concepts": ["event loop"],
        "starting_direction": "Look at when each coroutine is scheduled.",
        "hints": [
            {"label": "Hint 1 — Direction", "text": "Consider what gather receives."},
            {"label": "Hint 2 — Concept", "text": "Think about awaitables versus tasks."},
            {"label": "Hint 3 — Strong hint", "text": "Inspect how each item is created."},
        ],
        "estimated_difficulty": 3,
    }
    return {**base, **extra}


# --- 🔒 the shape guarantee, which is the whole reason kinds exist ---


def test_every_kind_has_a_schema() -> None:
    """A kind with no schema would make any block using it unbuildable."""
    for kind in challenge_blocks.KINDS:
        assert kind in challenge_blocks._SCHEMA_BY_KIND, kind


def test_every_built_in_block_uses_its_kind_s_schema() -> None:
    """The invariant that lets a custom block borrow a built-in's renderer.

    If `self_check` asked for something other than what `checklist` implies, a
    custom checklist block would render through a component expecting a
    different shape.
    """
    for block in challenge_blocks.BLOCKS:
        assert block.schema == challenge_blocks.schema_for(block.kind), block.key


def test_a_custom_block_cannot_claim_a_reserved_kind() -> None:
    """`progressive_hints` and `rating` are special-cased elsewhere.

    A second hints block would be silently reshaped by `_normalise_hints`, and
    a second rating block has no column to land in.
    """
    assert "progressive_hints" not in challenge_blocks.CUSTOM_KINDS
    assert "rating" not in challenge_blocks.CUSTOM_KINDS
    for kind in challenge_blocks.CUSTOM_KINDS:
        assert kind in challenge_blocks.KINDS


def test_schema_for_returns_a_fresh_copy() -> None:
    """`build_schema` embeds these by reference; a shared dict would let a
    caller mutating the generated schema edit the registry itself.
    """
    first = challenge_blocks.schema_for("stat")
    first["properties"]["value"] = {"type": "integer"}
    assert challenge_blocks.schema_for("stat")["properties"]["value"] == {"type": "string"}


# --- 🔒 what a block may be called and asked for ---


@pytest.mark.parametrize(
    "key",
    ["9lives", "ab", "has spaces", "trailing-dash", "", "x" * 41],
)
def test_a_malformed_key_is_rejected(key: str) -> None:
    with pytest.raises(block_service.BlockError, match="key must be"):
        block_service._validate_key(key)


def test_a_key_is_normalised_rather_than_rejected_for_case() -> None:
    """Case and surrounding space are fixed rather than refused.

    The key becomes a JSON key and a lookup on the frontend, so it has to be
    exact — but "the casing is wrong" is a correctable slip, not a decision
    worth bouncing someone back to the form over.
    """
    assert block_service._validate_key("  Review_Checklist  ") == "review_checklist"


def test_a_built_in_key_cannot_be_redefined() -> None:
    """Shadowing `hints` would put two blocks in one slot of `content`."""
    with pytest.raises(block_service.BlockError, match="built-in block"):
        block_service._validate_key("hints")


def test_an_instruction_may_not_carry_its_own_question_fence() -> None:
    """Mirrors `prompt_service`: a block instruction reaches the model through
    the same channel as the guidance, so it gets the same check.
    """
    with pytest.raises(block_service.BlockError, match="<QUESTION>"):
        block_service._validate_instruction("Summarise the <QUESTION> block for me.")


def test_an_oversized_instruction_is_rejected() -> None:
    """The instruction is sent on every generation, so it is paid for on each."""
    with pytest.raises(block_service.BlockError, match="too long"):
        block_service._validate_instruction("x" * (block_service.MAX_INSTRUCTION_CHARS + 1))


def test_an_empty_instruction_is_rejected() -> None:
    with pytest.raises(block_service.BlockError, match="cannot be empty"):
        block_service._validate_instruction("   ")


def test_a_kind_with_no_renderer_is_rejected() -> None:
    with pytest.raises(block_service.BlockError, match="not a layout"):
        block_service._validate_kind("hologram")


# --- 🔒 resolution: code first, overrides over it, customs after ---


@pytest.mark.anyio
async def test_a_custom_block_resolves_with_its_kind_s_schema(clean_blocks) -> None:
    async with async_session() as session:
        await block_service.create_block(
            session,
            key="review_checklist",
            label="Before you ship",
            kind="checklist",
            instruction="List what to verify before calling this done.",
        )
        blocks = await block_service.resolve(session, ["review_checklist"])

    custom = next(b for b in blocks if b.key == "review_checklist")
    assert custom.schema == challenge_blocks.schema_for("checklist")
    assert custom.core is False
    assert custom.column is None


@pytest.mark.anyio
async def test_a_custom_resource_list_is_link_checked_like_a_built_in(clean_blocks) -> None:
    """`has_urls` comes from the kind, so nobody has to remember to set it."""
    async with async_session() as session:
        await block_service.create_block(
            session,
            key="further_reading",
            label="Further reading",
            kind="resource_list",
            instruction="Suggest documentation about the underlying topic.",
        )
        blocks = await block_service.resolve(session, ["further_reading"])

    assert next(b for b in blocks if b.key == "further_reading").has_urls is True


@pytest.mark.anyio
async def test_an_override_changes_the_wording_and_nothing_else(clean_blocks) -> None:
    """The central safety property of editable instructions.

    Rewording `concepts` must not let it start returning a string — that would
    fail `validate` on every generation until someone noticed.
    """
    async with async_session() as session:
        await block_service.set_instruction(session, "concepts", "Name at most three ideas.")
        blocks = await block_service.resolve(session, None)

    concepts = next(b for b in blocks if b.key == "concepts")
    assert concepts.instruction == "Name at most three ideas."
    assert concepts.schema == challenge_blocks.BY_KEY["concepts"].schema
    assert concepts.kind == "chips"
    assert concepts.core is True
    assert "Name at most three ideas." in challenge_blocks.build_instructions(blocks)


@pytest.mark.anyio
async def test_resetting_an_override_restores_the_code_default(clean_blocks) -> None:
    async with async_session() as session:
        await block_service.set_instruction(session, "concepts", "Name at most three ideas.")
        restored = await block_service.reset_instruction(session, "concepts")
        blocks = await block_service.resolve(session, None)

    assert restored == challenge_blocks.BY_KEY["concepts"].instruction
    concepts = next(b for b in blocks if b.key == "concepts")
    assert concepts.instruction == challenge_blocks.BY_KEY["concepts"].instruction


@pytest.mark.anyio
async def test_core_blocks_come_first_and_are_never_dropped(clean_blocks) -> None:
    async with async_session() as session:
        await block_service.create_block(
            session,
            key="review_checklist",
            label="Before you ship",
            kind="checklist",
            instruction="List what to verify.",
        )
        blocks = await block_service.resolve(session, ["review_checklist"])

    assert [b.key for b in blocks[: len(challenge_blocks.CORE_KEYS)]] == list(
        challenge_blocks.CORE_KEYS
    )
    assert blocks[-1].key == "review_checklist"


@pytest.mark.anyio
async def test_a_deleted_custom_block_stops_resolving_without_raising(clean_blocks) -> None:
    """A format naming a since-deleted block must still generate.

    Raising here would mean discovering the problem an hour after the run that
    paid for the question — the same argument as the built-in `resolve`.
    """
    async with async_session() as session:
        row = await block_service.create_block(
            session,
            key="review_checklist",
            label="Before you ship",
            kind="checklist",
            instruction="List what to verify.",
        )
        await block_service.delete_block(session, row.id)
        blocks = await block_service.resolve(session, ["review_checklist"])

    assert [b.key for b in blocks] == list(challenge_blocks.CORE_KEYS)


# --- 🔒 custom blocks inherit the spoiler scan ---


@pytest.mark.anyio
async def test_a_solution_tell_in_a_custom_block_is_caught(clean_blocks) -> None:
    """The scan walks values generically, so it covers blocks that did not
    exist when it was written — including ones the user invents at runtime.
    """
    async with async_session() as session:
        await block_service.create_block(
            session,
            key="review_checklist",
            label="Before you ship",
            kind="checklist",
            instruction="List what to verify.",
        )
        blocks = await block_service.resolve(session, ["review_checklist"])

    payload = _payload(review_checklist=["Confirm the answer is to await the gather call."])
    with pytest.raises(challenge_service.ChallengeValidationError, match="reads as a solution"):
        challenge_service.validate(payload, blocks)


@pytest.mark.anyio
async def test_a_gated_custom_block_is_exempt_from_the_scan(clean_blocks) -> None:
    """Gating is how a block opts out of the spoiler scan.

    Documented by test rather than left implicit: it is the one way a user can
    deliberately ask for solution-shaped material, exactly as the built-in
    `solution_resources` does.
    """
    async with async_session() as session:
        await block_service.create_block(
            session,
            key="last_resort",
            label="Last resort",
            kind="list",
            instruction="Explain the resolution for someone who has given up.",
            gated=True,
        )
        blocks = await block_service.resolve(session, ["last_resort"])

    payload = _payload(last_resort=["The answer is to await the gather call."])
    challenge = challenge_service.validate(payload, blocks)
    assert challenge.content["last_resort"]


# --- 🔒 formats accept both halves of the library ---


@pytest.mark.anyio
async def test_a_format_may_name_a_custom_block(clean_blocks) -> None:
    async with async_session() as session:
        await block_service.create_block(
            session,
            key="review_checklist",
            label="Before you ship",
            kind="checklist",
            instruction="List what to verify.",
        )
        row = await format_service.create(
            session, name="With checklist", blocks=["review_checklist"]
        )
        fmt = await format_service.get_by_id(session, row.id)
        await session.delete(row)
        await session.commit()

    assert "review_checklist" in fmt.keys


@pytest.mark.anyio
async def test_a_format_naming_nothing_real_is_still_rejected(clean_blocks) -> None:
    """Widening validation to custom keys must not widen it to any string."""
    async with async_session() as session:
        with pytest.raises(format_service.FormatError, match="Unknown block"):
            await format_service.create(session, name="Bad", blocks=["teleport"])


# --- 🔒 provenance survives a reworded instruction ---


def test_a_generation_record_names_the_blocks_and_the_text() -> None:
    """What makes rewording safe after the fact: the challenge remembers the
    instruction that produced it, not the one in force when it is read.
    """
    extra = challenge_blocks.Block(
        key="glossary",
        label="Terms",
        description="",
        kind="definition_list",
        schema=challenge_blocks.schema_for("definition_list"),
        instruction="Define the jargon.",
    )
    blocks = [*challenge_blocks.resolve(None), extra]
    record = challenge_service.generation_record(
        system_instruction="…the composed instruction…",
        blocks=blocks,
        prompt_version=3,
        provider="gemini",
        model="gemini-2.0-flash",
    )

    assert record["system_instruction"] == "…the composed instruction…"
    assert "glossary" in record["blocks"]
    assert record["prompt_version"] == 3
    assert record["at"]


# --- 🔒 the suite must not eat the library it is testing against ---


@pytest.mark.anyio
async def test_the_shipped_library_blocks_survive_the_suite() -> None:
    """Guards the cleanup itself, like the scratch-row guard on questions.

    `library_blocks` holds nine blocks that ship with the app, seeded by
    migration. An over-broad DELETE in a fixture removes them from the user's
    real library and nothing else notices — this test is what notices.
    """
    async with async_session() as session:
        keys = set((await session.scalars(select(LibraryBlock.key))).all())

    missing = SHIPPED_KEYS - keys
    assert not missing, f"shipped library blocks were deleted by the suite: {sorted(missing)}"
