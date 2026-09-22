"""Payload size, paging, the merged bootstrap call, and the spend ceiling.

These are performance changes, so the tests assert the properties that make
them safe rather than the speed itself: that a list no longer carries what it
never rendered, that a cursor pages through a stable sequence, that one call
answers what three used to, and that a loop cannot spend without limit.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core import ratelimit
from app.core.db import async_session
from app.models.challenge import Challenge
from app.models.question import Question

SCRATCH = "https://stackoverflow.com/questions/pytest-phase34-"


@pytest.fixture
async def three_challenges():
    """Three challenges with distinct created_at, newest last."""
    from datetime import UTC, datetime, timedelta

    made: list[tuple[uuid.UUID, uuid.UUID]] = []
    base = datetime.now(UTC) - timedelta(days=10)
    async with async_session() as session:
        for i in range(3):
            marker = uuid.uuid4().hex[:10]
            question = Question(
                canonical_url=f"{SCRATCH}{marker}",
                url=f"{SCRATCH}{marker}",
                title=f"Question {i}",
                tags=["python"],
                status="selected",
            )
            session.add(question)
            await session.commit()
            await session.refresh(question)

            challenge = Challenge(
                question_id=question.id,
                problem_summary="x" * 500,
                why_interesting="y" * 500,
                concepts=["event loop"],
                starting_direction="z" * 500,
                hints=[{"label": "Hint 1", "text": "h"}],
                estimated_difficulty=3,
                content={"problem_summary": "x" * 2000, "hints": [{"label": "a", "text": "b"}]},
                created_at=base + timedelta(days=i),
            )
            session.add(challenge)
            await session.commit()
            await session.refresh(challenge)
            made.append((challenge.id, question.id))

    yield made

    async with async_session() as session:
        for challenge_id, question_id in made:
            await session.execute(delete(Challenge).where(Challenge.id == challenge_id))
            await session.execute(delete(Question).where(Question.id == question_id))
        await session.commit()


# --- 🔒 the list stops shipping what it never showed ---


@pytest.mark.anyio
async def test_the_list_omits_the_generated_content(
    client: TestClient, auth_cookies: dict[str, str], three_challenges
) -> None:
    """`content` averages 2.7KB a row and neither the challenges list nor the
    dashboard renders a byte of it. At the old limit of 200 that was over half
    a megabyte across a billed function.
    """
    rows = client.get("/challenges?limit=50", cookies=auth_cookies).json()
    assert rows

    for row in rows:
        assert "content" not in row
        assert "problem_summary" not in row
        assert "hints" not in row
        # Still everything the list actually draws.
        for field in ("id", "question_title", "question_tags", "estimated_difficulty"):
            assert field in row


@pytest.mark.anyio
async def test_the_detail_view_still_carries_everything(
    client: TestClient, auth_cookies: dict[str, str], three_challenges
) -> None:
    """Trimming the list must not trim the page that renders the challenge."""
    challenge_id = three_challenges[0][0]
    body = client.get(f"/challenges/{challenge_id}", cookies=auth_cookies).json()

    assert body["content"]
    assert body["problem_summary"]
    assert "block_meta" in body


# --- 🔒 the cursor pages through a stable sequence ---


@pytest.mark.anyio
async def test_a_cursor_returns_the_next_page_without_repeats(
    client: TestClient, auth_cookies: dict[str, str], three_challenges
) -> None:
    first = client.get("/challenges?limit=2", cookies=auth_cookies).json()
    assert len(first) == 2

    cursor = first[-1]["created_at"]
    second = client.get(f"/challenges?limit=2&before={cursor}", cookies=auth_cookies).json()

    ids_first = {r["id"] for r in first}
    ids_second = {r["id"] for r in second}
    assert not (ids_first & ids_second), "a cursor page repeated a row from the previous page"


@pytest.mark.anyio
async def test_a_row_inserted_mid_scroll_does_not_shift_the_page(
    client: TestClient, auth_cookies: dict[str, str], three_challenges
) -> None:
    """The reason for keyset over offset.

    With OFFSET, inserting a newer row pushes everything down, so page two
    repeats the last row of page one. A cursor is anchored to a value, so it
    cannot.
    """
    first = client.get("/challenges?limit=2", cookies=auth_cookies).json()
    cursor = first[-1]["created_at"]

    # A challenge arrives while the reader is on page one.
    async with async_session() as session:
        marker = uuid.uuid4().hex[:10]
        question = Question(
            canonical_url=f"{SCRATCH}{marker}", url=f"{SCRATCH}{marker}",
            title="Arrived mid-scroll", tags=["python"], status="selected",
        )
        session.add(question)
        await session.commit()
        await session.refresh(question)
        challenge = Challenge(
            question_id=question.id, problem_summary="p", why_interesting="w",
            concepts=[], starting_direction="s", hints=[], estimated_difficulty=1,
        )
        session.add(challenge)
        await session.commit()
        await session.refresh(challenge)
        inserted = (challenge.id, question.id)

    try:
        second = client.get(f"/challenges?limit=2&before={cursor}", cookies=auth_cookies).json()
        assert not ({r["id"] for r in first} & {r["id"] for r in second})
    finally:
        async with async_session() as session:
            await session.execute(delete(Challenge).where(Challenge.id == inserted[0]))
            await session.execute(delete(Question).where(Question.id == inserted[1]))
            await session.commit()


# --- 🔒 one call answers what three used to ---


def test_bootstrap_answers_session_and_both_keys(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    body = client.get("/auth/bootstrap", cookies=auth_cookies).json()

    assert body["authenticated"] is True
    for field in ("onboarding_complete", "yutori_key", "gemini_key"):
        assert field in body


def test_bootstrap_without_a_session_reports_nothing_else(client: TestClient) -> None:
    """Key status is not usable without a session, and looking it up would
    wake the database to produce an answer nobody may have.
    """
    body = client.get("/auth/bootstrap").json()

    assert body["authenticated"] is False
    assert body["onboarding_complete"] is False


# --- 🔒 a loop cannot spend without limit ---


def test_the_llm_endpoints_stop_accepting_after_the_hourly_ceiling(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    """Each of these costs a real LLM call. Nothing used to stop a retry loop
    from spending repeatedly, and the only evidence would have been the bill.
    """
    ratelimit.reset()
    try:
        limit, _ = ratelimit._LIMITS["llm"]
        payload = {"question_id": str(uuid.uuid4())}
        last = None
        for _ in range(limit + 1):
            last = client.post("/jobs/llm-test", cookies=auth_cookies, json=payload)

        assert last.status_code == 429
        assert "Retry-After" in last.headers
    finally:
        ratelimit.reset()


def test_the_ceiling_is_generous_enough_for_a_person(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    """A backstop against a loop, not a quota — clicking must never hit it."""
    limit, window = ratelimit._LIMITS["llm"]
    assert limit >= 20
    assert window >= 3600
