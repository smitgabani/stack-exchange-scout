"""Challenge formats: composing blocks, and the guarantees that hold anyway.

Two properties matter most here and neither is obvious from the happy path.
The spoiler scan has to cover blocks that did not exist when it was written,
or the newest block is the one that leaks. And gated blocks have to be exempt
from that scan — "if you're stuck" exists to point at the answer, and sits
behind the final reveal for exactly that reason.

Rows in `challenge_formats` are created and removed by the fixture.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.db import async_session
from app.models.challenge_format import ChallengeFormat
from app.services import challenge_blocks, challenge_service, format_service
from tests.conftest import delete_rows_added_since, existing_ids


@pytest.fixture
async def clean_formats():
    """Remove the formats this test made, and only those.

    This used to be `delete(ChallengeFormat)` with no WHERE. While the suite
    ran against production that deleted every format the user had created,
    on every run — which is exactly what they reported.
    """
    before = await existing_ids(ChallengeFormat)
    yield
    await delete_rows_added_since(ChallengeFormat, before)


def _block(key: str, kind: str, *, gated: bool = False) -> challenge_blocks.Block:
    """A library block, built without touching the database.

    The optional blocks left the code registry when they moved into
    `library_blocks`, so these tests construct what they need rather than
    naming one. That also keeps them honest: they are about how `validate`
    and `build_schema` treat a non-core block, not about any shipped block in
    particular.
    """
    return challenge_blocks.Block(
        key=key,
        label=key.replace("_", " ").capitalize(),
        description="",
        kind=kind,
        schema=challenge_blocks.schema_for(kind),
        instruction=f"Produce {key}.",
        gated=gated,
        has_urls=challenge_blocks.kind_has_urls(kind),
    )


def _with(*blocks: challenge_blocks.Block) -> list[challenge_blocks.Block]:
    """The core blocks plus these, which is what `resolve` returns."""
    return challenge_blocks.resolve(None) + list(blocks)


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


# --- 🔒 the spoiler scan covers blocks it was not written for ---


def test_a_solution_tell_in_a_new_block_is_caught() -> None:
    """The scan walks values generically rather than naming fields, so a block
    added later is covered the day it is added.
    """
    blocks = _with(_block("common_pitfalls", "list"))
    payload = _payload(common_pitfalls=["Forgetting await — the answer is to wrap it in a task."])

    with pytest.raises(challenge_service.ChallengeValidationError, match="reads as a solution"):
        challenge_service.validate(payload, blocks)


def test_a_solution_tell_nested_inside_a_block_is_caught() -> None:
    """Nested objects and lists are walked, not just top-level strings."""
    blocks = _with(_block("approach_outline", "steps"))
    payload = _payload(
        approach_outline=[
            {"step": "Check the loop", "detail": "Here is the working code you need."}
        ]
    )

    with pytest.raises(challenge_service.ChallengeValidationError):
        challenge_service.validate(payload, blocks)


def test_a_gated_block_is_exempt_from_the_scan() -> None:
    """It exists to point at the answer. Scanning it would make it impossible
    to produce, which would quietly defeat the feature the gate enables.
    """
    blocks = _with(_block("solution_resources", "resource_list", gated=True))
    payload = _payload(
        solution_resources=[
            {
                "title": "The accepted answer",
                "url": "https://stackoverflow.com/a/1",
                "why": "The answer is to create tasks first.",
            }
        ]
    )

    challenge = challenge_service.validate(payload, blocks)
    assert "solution_resources" in challenge.content


# --- 🧩 composition ---


def test_core_blocks_are_always_included() -> None:
    """A format saved with a typo still produces a usable challenge rather
    than failing an hour after the run that paid for the question.
    """
    blocks = challenge_blocks.resolve(["not_a_real_block"])
    keys = [b.key for b in blocks]

    assert keys == list(challenge_blocks.CORE_KEYS)


def test_the_schema_grows_with_the_selected_blocks() -> None:
    lean = challenge_blocks.build_schema(challenge_blocks.resolve(None))
    rich = challenge_blocks.build_schema(
        _with(_block("glossary", "definition_list"), _block("self_check", "checklist"))
    )

    assert "glossary" not in lean["properties"]
    assert "glossary" in rich["properties"]
    assert "self_check" in rich["properties"]


def test_every_selected_block_is_required() -> None:
    """Optional-to-the-model meant optional in practice: a nine-block format
    came back with two. Turning a block on is a request, so the schema says so.
    """
    schema = challenge_blocks.build_schema(
        _with(
            _block("glossary", "definition_list"),
            _block("self_check", "checklist"),
            _block("learning_resources", "resource_list"),
        )
    )

    assert set(schema["required"]) == set(schema["properties"])
    for key in ("glossary", "self_check", "learning_resources"):
        assert key in schema["required"]


def test_the_instructions_grow_with_the_selected_blocks() -> None:
    """Turning a block on has to change what the model is asked for, or the
    schema would request a field nothing told it to fill.
    """
    block = _block("visualisation", "diagram")
    instructions = challenge_service.compose_system_instruction(None, _with(block))

    assert block.instruction in instructions
    assert block.instruction not in challenge_service.compose_system_instruction(
        None, challenge_blocks.resolve(None)
    )
    # And the defence still lands last.
    assert instructions.rstrip().endswith(challenge_service.SAFETY_CLAUSE)


def test_output_for_a_block_that_was_not_asked_for_is_discarded() -> None:
    """The UI renders what a block declares; an unrequested key has no block,
    so storing it would mean carrying something nothing can draw.
    """
    blocks = challenge_blocks.resolve(None)
    challenge = challenge_service.validate(_payload(glossary=[{"term": "a", "definition": "b"}]), blocks)

    assert "glossary" not in challenge.content


def test_every_block_declares_a_kind_the_ui_knows() -> None:
    """A block whose kind has no renderer would silently not render at all."""
    for block in challenge_blocks.BLOCKS:
        assert block.kind in challenge_blocks.KINDS, block.key


# --- 🧩 formats ---


@pytest.mark.anyio
async def test_no_stored_format_means_the_standard_blocks(clean_formats) -> None:
    async with async_session() as session:
        fmt = await format_service.get_default(session)

    assert fmt.keys == list(challenge_blocks.CORE_KEYS)


@pytest.mark.anyio
async def test_the_first_format_created_becomes_the_default(clean_formats) -> None:
    """Otherwise creating one would appear to do nothing."""
    async with async_session() as session:
        row = await format_service.create(session, name="Deep dive", blocks=["glossary"])
        assert row.is_default is True

        fmt = await format_service.get_default(session)
        assert "glossary" in fmt.keys


@pytest.mark.anyio
async def test_core_blocks_are_stripped_rather_than_rejected(clean_formats) -> None:
    async with async_session() as session:
        row = await format_service.create(
            session, name="Redundant", blocks=["hints", "concepts", "self_check"]
        )

    assert row.blocks == ["self_check"]


@pytest.mark.anyio
async def test_an_unknown_block_is_refused(clean_formats) -> None:
    async with async_session() as session:
        with pytest.raises(format_service.FormatError, match="Unknown block"):
            await format_service.create(session, name="Bad", blocks=["teleport"])


@pytest.mark.anyio
async def test_a_duplicate_name_is_refused(clean_formats) -> None:
    async with async_session() as session:
        await format_service.create(session, name="Deep dive", blocks=[])
        with pytest.raises(format_service.FormatError, match="already exists"):
            await format_service.create(session, name="Deep dive", blocks=[])


@pytest.mark.anyio
async def test_only_one_format_is_ever_the_default(clean_formats) -> None:
    async with async_session() as session:
        first = await format_service.create(session, name="One", blocks=[])
        second = await format_service.create(session, name="Two", blocks=["glossary"])
        await format_service.set_default(session, second.id)

        rows = await format_service.list_formats(session)

    defaults = [row.name for row in rows if row.is_default]
    assert defaults == ["Two"]
    del first


# --- 🧩 link verification ---


@pytest.mark.anyio
async def test_unreachable_links_are_dropped() -> None:
    """A page full of 404s undermines confidence in everything else on it."""
    resources = [
        {"title": "Real", "url": "https://example.com/", "why": "exists"},
        {
            "title": "Invented",
            "url": "https://this-domain-should-not-resolve-9f3a2b.invalid/page",
            "why": "hallucinated",
        },
    ]

    kept, dropped = await format_service.verify_links(resources)

    assert [r["title"] for r in kept] == ["Real"]
    assert len(dropped) == 1


@pytest.mark.anyio
async def test_verification_is_skipped_for_blocks_without_urls() -> None:
    content = {"common_pitfalls": ["not a url"], "concepts": ["also not a url"]}
    blocks = _with(_block("common_pitfalls", "list"))

    dropped = await format_service.verify_content_links(content, blocks)

    assert dropped == []
    assert content["common_pitfalls"] == ["not a url"]


# --- 🧩 the API ---


@pytest.mark.anyio
async def test_the_block_catalogue_is_served_from_the_registry(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    """The editor reads this, so every block must appear without a second edit
    somewhere else — the core ones from code, the rest from `library_blocks`.
    """
    body = client.get("/llm/blocks", cookies=auth_cookies).json()

    keys = {block["key"] for block in body["blocks"]}
    # A superset, not equality: the catalogue also carries the library, which
    # a user can add to.
    assert keys >= {block.key for block in challenge_blocks.BLOCKS}
    core = {b["key"] for b in body["blocks"] if b["core"]}
    assert core == {b.key for b in challenge_blocks.BLOCKS if b.core}
    assert all(not b["editable"] for b in body["blocks"] if b["core"])


def test_formats_require_a_session(client: TestClient) -> None:
    assert client.get("/llm/formats").status_code == 401
