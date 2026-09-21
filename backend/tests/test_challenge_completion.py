"""Marking a challenge complete.

Reuses `status = "solved"` — in `QUESTION_STATUSES` since M5, never set
anywhere, because M8 (Feedback) was meant to be what set it and M8 has not
been built. Completion is deliberately not a delete: the question and its
challenge stay exactly as they are, they just leave the default "active"
views and appear under "completed" instead — that reversal is what these
tests are mostly about.

Rows are created under a `pytest-` marker and removed in teardown; the profile
and credentials are covered by `conftest.protect_real_data`.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.db import async_session
from app.models.challenge import Challenge
from app.models.question import Question

SCRATCH_PREFIX = "https://stackoverflow.com/questions/pytest-complete-"


@pytest.fixture
async def solvable_challenge():
    """A question with a real challenge, ready to be marked complete."""
    marker = uuid.uuid4().hex[:10]
    async with async_session() as session:
        question = Question(
            canonical_url=f"{SCRATCH_PREFIX}{marker}",
            url=f"{SCRATCH_PREFIX}{marker}",
            title="asyncio.gather runs sequentially",
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
            hints=[{"label": "Hint 1", "text": "Consider what gather receives."}],
            estimated_difficulty=3,
        )
        session.add(challenge)
        await session.commit()
        await session.refresh(challenge)
        ids = (question.id, challenge.id)

    yield ids

    async with async_session() as session:
        await session.execute(delete(Challenge).where(Challenge.id == ids[1]))
        await session.execute(delete(Question).where(Question.id == ids[0]))
        await session.commit()


@pytest.fixture
async def unchallenged_question():
    """A plain candidate with no challenge — completion should refuse it."""
    marker = uuid.uuid4().hex[:10]
    async with async_session() as session:
        question = Question(
            canonical_url=f"{SCRATCH_PREFIX}{marker}",
            url=f"{SCRATCH_PREFIX}{marker}",
            title="A candidate with no challenge",
            tags=["python"],
            status="candidate",
        )
        session.add(question)
        await session.commit()
        await session.refresh(question)
        qid = question.id

    yield qid

    async with async_session() as session:
        await session.execute(delete(Question).where(Question.id == qid))
        await session.commit()


# --- 🧩 completing ---


@pytest.mark.anyio
async def test_completing_sets_status_and_a_timestamp(
    client: TestClient, auth_cookies: dict[str, str], solvable_challenge
) -> None:
    question_id, _challenge_id = solvable_challenge

    response = client.post(f"/questions/{question_id}/complete", cookies=auth_cookies)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "solved"
    assert body["solved_at"] is not None


@pytest.mark.anyio
async def test_completing_does_not_delete_anything(
    client: TestClient, auth_cookies: dict[str, str], solvable_challenge
) -> None:
    """Completion is a status change, not removal — the question and its
    challenge must both survive exactly as they were.
    """
    question_id, challenge_id = solvable_challenge

    client.post(f"/questions/{question_id}/complete", cookies=auth_cookies)

    async with async_session() as session:
        assert await session.get(Question, question_id) is not None
        challenge = await session.get(Challenge, challenge_id)
        assert challenge is not None
        assert challenge.problem_summary == "Coroutines run one after another."


@pytest.mark.anyio
async def test_completing_a_question_with_no_challenge_is_refused(
    client: TestClient, auth_cookies: dict[str, str], unchallenged_question
) -> None:
    response = client.post(f"/questions/{unchallenged_question}/complete", cookies=auth_cookies)
    assert response.status_code == 409


def test_completing_an_unknown_question_is_a_404(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.post(f"/questions/{uuid.uuid4()}/complete", cookies=auth_cookies)
    assert response.status_code == 404


def test_completing_requires_a_session(client: TestClient) -> None:
    assert client.post(f"/questions/{uuid.uuid4()}/complete").status_code == 401


# --- 🧩 the main screen stops showing it, the completed view does ---


@pytest.mark.anyio
async def test_a_completed_challenge_leaves_the_default_list(
    client: TestClient, auth_cookies: dict[str, str], solvable_challenge
) -> None:
    _question_id, challenge_id = solvable_challenge

    def visible_in_active() -> bool:
        rows = client.get("/challenges?limit=200", cookies=auth_cookies).json()
        return any(row["id"] == str(challenge_id) for row in rows)

    assert visible_in_active()

    client.post(f"/questions/{solvable_challenge[0]}/complete", cookies=auth_cookies)

    assert not visible_in_active()


@pytest.mark.anyio
async def test_a_completed_challenge_appears_under_completed(
    client: TestClient, auth_cookies: dict[str, str], solvable_challenge
) -> None:
    question_id, challenge_id = solvable_challenge

    client.post(f"/questions/{question_id}/complete", cookies=auth_cookies)

    rows = client.get("/challenges?completion=completed&limit=200", cookies=auth_cookies).json()
    mine = [row for row in rows if row["id"] == str(challenge_id)]
    assert len(mine) == 1
    assert mine[0]["question_status"] == "solved"
    assert mine[0]["solved_at"] is not None


@pytest.mark.anyio
async def test_completion_all_shows_both(
    client: TestClient, auth_cookies: dict[str, str], solvable_challenge
) -> None:
    question_id, challenge_id = solvable_challenge
    client.post(f"/questions/{question_id}/complete", cookies=auth_cookies)

    rows = client.get("/challenges?completion=all&limit=200", cookies=auth_cookies).json()
    assert any(row["id"] == str(challenge_id) for row in rows)


# --- 🧩 reopening ---


@pytest.mark.anyio
async def test_reopening_restores_the_active_view_and_clears_the_timestamp(
    client: TestClient, auth_cookies: dict[str, str], solvable_challenge
) -> None:
    question_id, challenge_id = solvable_challenge
    client.post(f"/questions/{question_id}/complete", cookies=auth_cookies)

    response = client.post(f"/questions/{question_id}/reopen", cookies=auth_cookies)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "selected"
    assert body["solved_at"] is None

    active_ids = {
        row["id"] for row in client.get("/challenges?limit=200", cookies=auth_cookies).json()
    }
    assert str(challenge_id) in active_ids


@pytest.mark.anyio
async def test_reopening_something_not_completed_is_refused(
    client: TestClient, auth_cookies: dict[str, str], solvable_challenge
) -> None:
    question_id, _challenge_id = solvable_challenge

    response = client.post(f"/questions/{question_id}/reopen", cookies=auth_cookies)

    assert response.status_code == 409


@pytest.mark.anyio
async def test_a_reopened_question_does_not_reenter_the_candidate_pool(
    client: TestClient, auth_cookies: dict[str, str], solvable_challenge
) -> None:
    """Reopening goes back to "selected", not "candidate" — it already has a
    challenge, and re-entering scoring risks a second one being generated.
    """
    question_id, _challenge_id = solvable_challenge
    client.post(f"/questions/{question_id}/complete", cookies=auth_cookies)
    client.post(f"/questions/{question_id}/reopen", cookies=auth_cookies)

    candidates = client.get("/questions?status=candidate&limit=200", cookies=auth_cookies).json()
    assert not any(row["id"] == str(question_id) for row in candidates)
