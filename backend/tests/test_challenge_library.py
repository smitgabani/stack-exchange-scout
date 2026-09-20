"""The challenge library: promotion by hand, dismissal, and deletion.

These tests write real rows. `conftest.protect_real_data` snapshots the profile
and credentials but not `questions`, `challenges` or `digests`, so every test
here cleans up the rows it created — see the `scratch_question` fixture. Rows
are created with a `pytest-` URL prefix so anything left behind by an
interrupted run is identifiable rather than indistinguishable from real data.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.db import async_session
from app.models.challenge import Challenge
from app.models.digest import Digest, DigestQuestion
from app.models.question import Question
from app.schemas.profile import ProfileData
from app.services import digest_service

SCRATCH_PREFIX = "https://stackoverflow.com/questions/pytest-"


def _valid_payload() -> dict:
    return {
        "problem_summary": "Coroutines appear to execute one after another.",
        "why_interesting": "It exercises how the event loop actually schedules work.",
        "concepts": ["event loop", "coroutines"],
        "starting_direction": "Look at when each coroutine is actually scheduled.",
        "hints": [
            {"label": "Hint 1 — Direction", "text": "Consider what gather receives."},
            {"label": "Hint 2 — Concept", "text": "Think about awaitables versus tasks."},
            {"label": "Hint 3 — Strong hint", "text": "Inspect how each item is created."},
        ],
        "estimated_difficulty": 3,
    }


class _StubProvider:
    """Stands in for Gemini/OpenAI so no test here spends money or needs a key."""

    name = "fake"
    model = "fake-1"

    async def generate_json(
        self, *, system_instruction: str, prompt: str, schema: dict | None = None
    ) -> dict:
        return _valid_payload()


@pytest.fixture
async def scratch_question():
    """A question row that exists only for one test, removed afterwards."""
    marker = uuid.uuid4().hex[:12]
    async with async_session() as session:
        question = Question(
            stackoverflow_question_id=None,
            canonical_url=f"{SCRATCH_PREFIX}{marker}",
            url=f"{SCRATCH_PREFIX}{marker}",
            title="asyncio.gather runs sequentially",
            body="<p>Why does this run one at a time?</p>",
            tags=["python", "asyncio"],
            score=12,
            answer_count=1,
            difficulty=4,
            status="candidate",
        )
        session.add(question)
        await session.commit()
        await session.refresh(question)
        question_id = question.id

    yield question_id

    async with async_session() as session:
        await session.execute(delete(Challenge).where(Challenge.question_id == question_id))
        await session.execute(delete(DigestQuestion).where(DigestQuestion.question_id == question_id))
        await session.execute(delete(Question).where(Question.id == question_id))
        await session.commit()


async def _promote(question_id: uuid.UUID) -> Challenge:
    async with async_session() as session:
        question = await session.get(Question, question_id)
        return await digest_service.promote_question(
            session, ProfileData(), question, provider=_StubProvider()
        )


# --- 🧩 promotion ---


@pytest.mark.anyio
async def test_promoting_creates_a_challenge_that_belongs_to_no_digest(scratch_question) -> None:
    """The point of the feature: a challenge the scoring formula never chose."""
    challenge = await _promote(scratch_question)

    assert challenge.digest_id is None
    assert challenge.source == "manual"
    assert challenge.problem_summary


@pytest.mark.anyio
async def test_promoting_marks_the_question_selected(scratch_question) -> None:
    """Otherwise the next digest would curate a second challenge for it —
    `select_candidates` only ever looks at rows still marked `candidate`.
    """
    await _promote(scratch_question)

    async with async_session() as session:
        question = await session.get(Question, scratch_question)
        assert question.status == "selected"


@pytest.mark.anyio
async def test_the_same_question_cannot_be_promoted_twice(scratch_question) -> None:
    await _promote(scratch_question)

    with pytest.raises(digest_service.PromotionError, match="already has a challenge"):
        await _promote(scratch_question)


@pytest.mark.anyio
async def test_an_unenriched_question_is_refused_rather_than_curated(scratch_question) -> None:
    """There is no body yet, so the prompt would be empty and the call wasted."""
    async with async_session() as session:
        question = await session.get(Question, scratch_question)
        question.status = "enrichment_pending"
        await session.commit()

    with pytest.raises(digest_service.PromotionError, match="not been enriched"):
        await _promote(scratch_question)


# --- 🧩 the library spans every digest ---


@pytest.mark.anyio
async def test_list_challenges_includes_manual_ones(
    client: TestClient, auth_cookies: dict[str, str], scratch_question
) -> None:
    challenge = await _promote(scratch_question)

    response = client.get("/challenges", cookies=auth_cookies)
    assert response.status_code == 200
    rows = response.json()

    mine = [row for row in rows if row["id"] == str(challenge.id)]
    assert len(mine) == 1
    assert mine[0]["source"] == "manual"
    assert mine[0]["digest_id"] is None
    assert mine[0]["question_title"] == "asyncio.gather runs sequentially"


@pytest.mark.anyio
async def test_source_filter_separates_picked_from_generated(
    client: TestClient, auth_cookies: dict[str, str], scratch_question
) -> None:
    challenge = await _promote(scratch_question)

    manual = client.get("/challenges?source=manual", cookies=auth_cookies).json()
    from_digests = client.get("/challenges?source=digest", cookies=auth_cookies).json()

    assert any(row["id"] == str(challenge.id) for row in manual)
    assert all(row["id"] != str(challenge.id) for row in from_digests)
    assert all(row["digest_id"] is not None for row in from_digests)


def test_list_challenges_requires_a_session(client: TestClient) -> None:
    assert client.get("/challenges").status_code == 401


# --- 🧩 deletion leaves the question and the digest alone ---


@pytest.mark.anyio
async def test_deleting_a_challenge_keeps_its_question(
    client: TestClient, auth_cookies: dict[str, str], scratch_question
) -> None:
    challenge = await _promote(scratch_question)

    assert client.delete(f"/challenges/{challenge.id}", cookies=auth_cookies).status_code == 204
    assert client.get(f"/challenges/{challenge.id}", cookies=auth_cookies).status_code == 404

    async with async_session() as session:
        assert await session.get(Question, scratch_question) is not None


@pytest.mark.anyio
async def test_deleting_a_sent_digests_challenge_leaves_the_digest_intact(
    client: TestClient, auth_cookies: dict[str, str], scratch_question
) -> None:
    """Allowed on purpose — the UI warns the emailed link will break — but the
    digest row survives so the history stays honest about what was sent.
    """
    async with async_session() as session:
        digest = Digest(status="sent", question_count=1)
        session.add(digest)
        await session.commit()
        await session.refresh(digest)
        digest_id = digest.id

        challenge = Challenge(
            digest_id=digest_id,
            question_id=scratch_question,
            **{k: v for k, v in _valid_payload().items() if k != "estimated_difficulty"},
            estimated_difficulty=3,
        )
        session.add(challenge)
        session.add(DigestQuestion(digest_id=digest_id, question_id=scratch_question, position=0))
        await session.commit()
        await session.refresh(challenge)
        challenge_id = challenge.id

    try:
        assert client.delete(f"/challenges/{challenge_id}", cookies=auth_cookies).status_code == 204

        async with async_session() as session:
            assert await session.get(Digest, digest_id) is not None
            assert await session.get(Question, scratch_question) is not None
    finally:
        async with async_session() as session:
            await session.execute(delete(DigestQuestion).where(DigestQuestion.digest_id == digest_id))
            await session.execute(delete(Challenge).where(Challenge.digest_id == digest_id))
            await session.execute(delete(Digest).where(Digest.id == digest_id))
            await session.commit()


def test_deleting_a_challenge_that_does_not_exist_is_a_404(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    assert client.delete(f"/challenges/{uuid.uuid4()}", cookies=auth_cookies).status_code == 404


# --- 🧩 dismissal keeps the row so the question is not rediscovered ---


@pytest.mark.anyio
async def test_dismissing_keeps_the_row_so_ingest_still_knows_the_url(
    client: TestClient, auth_cookies: dict[str, str], scratch_question
) -> None:
    """A hard delete would make the URL unknown again, and the next run would
    rediscover the same question — possibly having paid for it twice.
    """
    response = client.post(f"/questions/{scratch_question}/dismiss", cookies=auth_cookies)
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["rejection_reason"] == "user_dismissed"

    async with async_session() as session:
        assert await session.get(Question, scratch_question) is not None


@pytest.mark.anyio
async def test_a_dismissed_question_leaves_the_default_pool_and_comes_back_on_restore(
    client: TestClient, auth_cookies: dict[str, str], scratch_question
) -> None:
    def in_candidate_pool() -> bool:
        rows = client.get("/questions?status=candidate&limit=200", cookies=auth_cookies).json()
        return any(row["id"] == str(scratch_question) for row in rows)

    assert in_candidate_pool()

    client.post(f"/questions/{scratch_question}/dismiss", cookies=auth_cookies)
    assert not in_candidate_pool()

    dismissed = client.get(
        "/questions?status=rejected&rejection_reason=user_dismissed&limit=200", cookies=auth_cookies
    ).json()
    assert any(row["id"] == str(scratch_question) for row in dismissed)

    assert client.post(f"/questions/{scratch_question}/restore", cookies=auth_cookies).status_code == 200
    assert in_candidate_pool()


@pytest.mark.anyio
async def test_restore_refuses_a_question_the_filters_rejected(
    client: TestClient, auth_cookies: dict[str, str], scratch_question
) -> None:
    """Restoring it would only get it re-rejected by the same rule next run."""
    async with async_session() as session:
        question = await session.get(Question, scratch_question)
        question.status = "rejected"
        question.rejection_reason = "closed_as_duplicate"
        await session.commit()

    response = client.post(f"/questions/{scratch_question}/restore", cookies=auth_cookies)
    assert response.status_code == 409


@pytest.mark.anyio
async def test_a_promoted_question_reports_its_challenge(
    client: TestClient, auth_cookies: dict[str, str], scratch_question
) -> None:
    """So the UI can link to the challenge instead of offering to make another."""
    before = client.get(f"/questions/{scratch_question}", cookies=auth_cookies).json()
    assert before["challenge_id"] is None

    challenge = await _promote(scratch_question)

    after = client.get(f"/questions/{scratch_question}", cookies=auth_cookies).json()
    assert after["challenge_id"] == str(challenge.id)


@pytest.mark.anyio
async def test_no_scratch_rows_leak_into_the_real_pool() -> None:
    """Guards the cleanup itself: the fixture's rows must not outlive the run."""
    async with async_session() as session:
        leftover = (
            await session.scalars(
                select(Question).where(Question.canonical_url.like(f"{SCRATCH_PREFIX}%"))
            )
        ).all()
    assert leftover == []
