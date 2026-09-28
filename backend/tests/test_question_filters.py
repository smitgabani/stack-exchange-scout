"""Filtering the candidate pool: topic, recency, upvotes, answered, accepted.

Writes two real rows (see test_challenge_library.py's SCRATCH_PREFIX pattern)
that contrast on every filterable field, and checks each filter returns only
the row that should match.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.core.db import async_session
from app.models.challenge import Challenge
from app.models.digest import DigestQuestion
from app.models.question import Question

SCRATCH_PREFIX = "https://stackoverflow.com/questions/pytest-filter-"


@pytest.fixture
async def two_questions():
    marker = uuid.uuid4().hex[:12]
    now = datetime.now(UTC)
    old_unanswered = Question(
        canonical_url=f"{SCRATCH_PREFIX}old-{marker}",
        url=f"{SCRATCH_PREFIX}old-{marker}",
        title="old unanswered python question",
        tags=["python"],
        score=5,
        answer_count=0,
        accepted_answer_id=None,
        question_created_at=now - timedelta(days=20),
        status="candidate",
    )
    new_answered = Question(
        canonical_url=f"{SCRATCH_PREFIX}new-{marker}",
        url=f"{SCRATCH_PREFIX}new-{marker}",
        title="new answered rust question",
        tags=["rust"],
        score=50,
        answer_count=3,
        accepted_answer_id=999,
        question_created_at=now - timedelta(hours=1),
        status="candidate",
    )
    async with async_session() as session:
        session.add_all([old_unanswered, new_answered])
        await session.commit()
        await session.refresh(old_unanswered)
        await session.refresh(new_answered)
        ids = (old_unanswered.id, new_answered.id)

    yield ids

    async with async_session() as session:
        await session.execute(delete(Challenge).where(Challenge.question_id.in_(ids)))
        await session.execute(delete(DigestQuestion).where(DigestQuestion.question_id.in_(ids)))
        await session.execute(delete(Question).where(Question.id.in_(ids)))
        await session.commit()


def _ids(rows: list[dict]) -> set[str]:
    return {row["id"] for row in rows}


@pytest.mark.anyio
async def test_topic_filter_matches_only_that_tag(client, auth_cookies, two_questions) -> None:
    old_id, new_id = two_questions
    rows = client.get(
        "/questions?status=candidate&limit=200&topic=rust", cookies=auth_cookies
    ).json()
    matched = _ids(rows)
    assert str(new_id) in matched
    assert str(old_id) not in matched


@pytest.mark.anyio
async def test_min_score_excludes_the_lower_scored_question(client, auth_cookies, two_questions) -> None:
    old_id, new_id = two_questions
    rows = client.get(
        "/questions?status=candidate&limit=200&min_score=10", cookies=auth_cookies
    ).json()
    matched = _ids(rows)
    assert str(new_id) in matched
    assert str(old_id) not in matched


@pytest.mark.anyio
async def test_answered_filter_splits_on_answer_count(client, auth_cookies, two_questions) -> None:
    old_id, new_id = two_questions

    answered = _ids(
        client.get(
            "/questions?status=candidate&limit=200&answered=true", cookies=auth_cookies
        ).json()
    )
    assert str(new_id) in answered
    assert str(old_id) not in answered

    unanswered = _ids(
        client.get(
            "/questions?status=candidate&limit=200&answered=false", cookies=auth_cookies
        ).json()
    )
    assert str(old_id) in unanswered
    assert str(new_id) not in unanswered


@pytest.mark.anyio
async def test_has_accepted_answer_filter(client, auth_cookies, two_questions) -> None:
    old_id, new_id = two_questions

    accepted = _ids(
        client.get(
            "/questions?status=candidate&limit=200&has_accepted_answer=true", cookies=auth_cookies
        ).json()
    )
    assert str(new_id) in accepted
    assert str(old_id) not in accepted


@pytest.mark.anyio
async def test_posted_within_days_excludes_the_older_question(
    client, auth_cookies, two_questions
) -> None:
    old_id, new_id = two_questions

    recent = _ids(
        client.get(
            "/questions?status=candidate&limit=200&posted_within_days=1", cookies=auth_cookies
        ).json()
    )
    assert str(new_id) in recent
    assert str(old_id) not in recent

    everything = _ids(
        client.get(
            "/questions?status=candidate&limit=200&posted_within_days=30", cookies=auth_cookies
        ).json()
    )
    assert str(old_id) in everything
    assert str(new_id) in everything
