"""Changing a challenge's format after the fact.

A top-up, not a regeneration. The properties worth pinning are the ones a
casual implementation gets wrong: existing blocks must survive untouched
(hints you have already revealed must not change mid-solve), the challenge
must keep its id (the link in a sent digest depends on it), and asking for a
format that adds nothing must not spend a call.
"""

import uuid

import pytest
from sqlalchemy import delete

from app.core.db import async_session
from app.models.challenge import Challenge
from app.models.challenge_format import ChallengeFormat
from app.models.question import Question
from app.schemas.profile import ProfileData
from app.services import digest_service, format_service
from tests.conftest import delete_rows_added_since, existing_ids

SCRATCH = "https://stackoverflow.com/questions/pytest-reformat-"

ORIGINAL_HINTS = [
    {"label": "Hint 1 — Direction", "text": "The original first hint."},
    {"label": "Hint 2 — Concept", "text": "The original second hint."},
    {"label": "Hint 3 — Strong hint", "text": "The original third hint."},
]


class _TopUpProvider:
    """Returns only the blocks it was asked for, and records the request."""

    name = "fake"
    model = "fake-1"

    def __init__(self):
        self.schemas: list[dict | None] = []

    async def generate_json(
        self, *, system_instruction: str, prompt: str, schema: dict | None = None
    ) -> dict:
        self.schemas.append(schema)
        asked = list((schema or {}).get("properties", {}))
        payload: dict = {}
        if "common_pitfalls" in asked:
            payload["common_pitfalls"] = ["Assuming the loop is synchronous."]
        if "self_check" in asked:
            payload["self_check"] = ["Does it still work with an empty input?"]
        if "prerequisites" in asked:
            payload["prerequisites"] = ["async/await"]
        # Deliberately also returns a core field it was not asked for.
        payload["hints"] = [{"label": "Hint 1 — Direction", "text": "A REPLACEMENT hint."}]
        return payload


@pytest.fixture
async def existing_challenge():
    marker = uuid.uuid4().hex[:10]
    formats_before = await existing_ids(ChallengeFormat)
    async with async_session() as session:
        question = Question(
            canonical_url=f"{SCRATCH}{marker}",
            url=f"{SCRATCH}{marker}",
            title="asyncio.gather runs sequentially",
            body="<p>Why does this run one at a time?</p>",
            tags=["python"],
            status="selected",
        )
        session.add(question)
        await session.commit()
        await session.refresh(question)

        challenge = Challenge(
            question_id=question.id,
            problem_summary="Coroutines run one after another.",
            why_interesting="It exercises the event loop.",
            concepts=["event loop"],
            starting_direction="Look at scheduling.",
            hints=ORIGINAL_HINTS,
            estimated_difficulty=3,
            content={
                "problem_summary": "Coroutines run one after another.",
                "why_interesting": "It exercises the event loop.",
                "concepts": ["event loop"],
                "starting_direction": "Look at scheduling.",
                "hints": ORIGINAL_HINTS,
                "estimated_difficulty": 3,
            },
            format_name="Standard",
        )
        session.add(challenge)
        await session.commit()
        await session.refresh(challenge)
        ids = (challenge.id, question.id)

    yield ids

    async with async_session() as session:
        await session.execute(delete(Challenge).where(Challenge.id == ids[0]))
        await session.execute(delete(Question).where(Question.id == ids[1]))
        await session.commit()
    # Only the formats this test created — it used to wipe the table.
    await delete_rows_added_since(ChallengeFormat, formats_before)


async def _reformat(challenge_id, question_id, blocks: list[str], provider=None) -> dict:
    async with async_session() as session:
        fmt = await format_service.create(session, name=f"F-{uuid.uuid4().hex[:6]}", blocks=blocks)
        challenge = await session.get(Challenge, challenge_id)
        question = await session.get(Question, question_id)
        return await digest_service.reformat_challenge(
            session,
            ProfileData(),
            challenge,
            question,
            format_id=fmt.id,
            provider=provider or _TopUpProvider(),
        )


@pytest.mark.anyio
async def test_only_the_missing_blocks_are_requested(existing_challenge) -> None:
    """Regenerating everything would be a different, worse feature."""
    challenge_id, question_id = existing_challenge
    provider = _TopUpProvider()

    await _reformat(challenge_id, question_id, ["common_pitfalls", "self_check"], provider)

    asked = list(provider.schemas[0]["properties"])
    assert sorted(asked) == ["common_pitfalls", "self_check"]


@pytest.mark.anyio
async def test_existing_blocks_are_not_replaced(existing_challenge) -> None:
    """The provider returns a replacement hint; it must be ignored. Hints you
    have already revealed changing under you mid-solve is the exact failure.
    """
    challenge_id, question_id = existing_challenge

    await _reformat(challenge_id, question_id, ["common_pitfalls"])

    async with async_session() as session:
        challenge = await session.get(Challenge, challenge_id)

    assert challenge.content["hints"] == ORIGINAL_HINTS
    assert challenge.content["problem_summary"] == "Coroutines run one after another."


@pytest.mark.anyio
async def test_the_new_blocks_are_added(existing_challenge) -> None:
    challenge_id, question_id = existing_challenge

    result = await _reformat(challenge_id, question_id, ["common_pitfalls", "self_check"])

    assert sorted(result["added"]) == ["common_pitfalls", "self_check"]
    async with async_session() as session:
        challenge = await session.get(Challenge, challenge_id)
    assert challenge.content["common_pitfalls"] == ["Assuming the loop is synchronous."]


@pytest.mark.anyio
async def test_the_challenge_keeps_its_id(existing_challenge) -> None:
    """The link in an already-sent digest points at this id."""
    challenge_id, question_id = existing_challenge

    await _reformat(challenge_id, question_id, ["prerequisites"])

    async with async_session() as session:
        assert await session.get(Challenge, challenge_id) is not None


@pytest.mark.anyio
async def test_a_format_that_adds_nothing_spends_no_call(existing_challenge) -> None:
    """Nothing is missing, so there is nothing to ask for — and asking anyway
    would charge for a no-op.
    """
    challenge_id, question_id = existing_challenge
    provider = _TopUpProvider()

    result = await _reformat(challenge_id, question_id, [], provider)

    assert result["spent_call"] is False
    assert result["added"] == []
    assert provider.schemas == []


@pytest.mark.anyio
async def test_the_format_name_is_recorded(existing_challenge) -> None:
    challenge_id, question_id = existing_challenge

    result = await _reformat(challenge_id, question_id, ["self_check"])

    async with async_session() as session:
        challenge = await session.get(Challenge, challenge_id)
    assert challenge.format_name == result["format"]


@pytest.mark.anyio
async def test_a_legacy_challenge_is_topped_up_from_its_columns(existing_challenge) -> None:
    """Challenges made before formats have `content` null. Without reading the
    columns, every core block would look missing and be regenerated.
    """
    challenge_id, question_id = existing_challenge
    async with async_session() as session:
        challenge = await session.get(Challenge, challenge_id)
        challenge.content = None
        await session.commit()

    provider = _TopUpProvider()
    await _reformat(challenge_id, question_id, ["self_check"], provider)

    asked = list(provider.schemas[0]["properties"])
    assert asked == ["self_check"]

    async with async_session() as session:
        challenge = await session.get(Challenge, challenge_id)
    assert challenge.content["hints"] == ORIGINAL_HINTS


@pytest.mark.anyio
async def test_a_spoiler_in_an_added_block_is_refused(existing_challenge) -> None:
    """The scan applies to a top-up exactly as it does to a fresh generation."""

    class _Spoiler(_TopUpProvider):
        async def generate_json(self, *, system_instruction, prompt, schema=None):
            return {"common_pitfalls": ["Here is the working code you need for this."]}

    challenge_id, question_id = existing_challenge

    with pytest.raises(digest_service.PromotionError):
        await _reformat(challenge_id, question_id, ["common_pitfalls"], _Spoiler())


@pytest.mark.anyio
async def test_blocks_the_model_declines_are_reported(existing_challenge) -> None:
    """The bug this reporting exists for: nine blocks requested, two returned,
    and nothing on the page said so. A short challenge must be explained.
    """

    class _Partial(_TopUpProvider):
        async def generate_json(self, *, system_instruction, prompt, schema=None):
            self.schemas.append(schema)
            # Answers one of the two requested blocks and ignores the other.
            return {"self_check": ["Does it handle an empty list?"]}

    challenge_id, question_id = existing_challenge

    result = await _reformat(
        challenge_id, question_id, ["self_check", "common_pitfalls"], _Partial()
    )

    assert result["added"] == ["self_check"]
    assert result["missing"] == ["common_pitfalls"]


@pytest.mark.anyio
async def test_a_resource_block_emptied_by_link_checking_is_reported(existing_challenge) -> None:
    """Every link invented, so the block is empty and not worth storing — but
    it must not read as a block that was never asked for.
    """

    class _BadLinks(_TopUpProvider):
        async def generate_json(self, *, system_instruction, prompt, schema=None):
            self.schemas.append(schema)
            return {
                "learning_resources": [
                    {
                        "title": "Invented",
                        "url": "https://not-a-real-host-8c1f2a.invalid/guide",
                        "why": "hallucinated",
                    }
                ]
            }

    challenge_id, question_id = existing_challenge

    result = await _reformat(challenge_id, question_id, ["learning_resources"], _BadLinks())

    assert result["added"] == []
    assert result["missing"] == ["learning_resources"]
    assert len(result["dropped_links"]) == 1
