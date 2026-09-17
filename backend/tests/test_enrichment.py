from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.integrations.stackexchange import (
    QuestionMetadata,
    StackExchangeBadRequest,
    StackExchangeError,
    parse_question,
)
from app.models.question import Question
from app.schemas.profile import Difficulty, ProfileData, Topic
from app.services import enrichment_service, filter_service

_TEST_IDS = [910001, 910002, 910003, 910004]
_LONG_BODY = "A genuinely detailed question body. " * 20


def _profile(**overrides) -> ProfileData:
    defaults = {
        "topics": [Topic(name="python", weight=80)],
        "excluded_concepts": [],
        "difficulty": Difficulty(minimum=1, maximum=5),
    }
    return ProfileData(**{**defaults, **overrides})


def _question(question_id: int, **overrides) -> Question:
    defaults = {
        "stackoverflow_question_id": question_id,
        "canonical_url": f"https://stackoverflow.com/questions/{question_id}",
        "url": f"https://stackoverflow.com/questions/{question_id}",
        "status": "enrichment_pending",
        "tags": [],
    }
    return Question(**{**defaults, **overrides})


def _metadata(question_id: int, **overrides) -> QuestionMetadata:
    defaults = {
        "question_id": question_id,
        "title": "How do I do the thing?",
        "body": _LONG_BODY,
        "tags": ["python"],
        "score": 5,
        "answer_count": 1,
        "accepted_answer_id": None,
        "is_closed": False,
        "question_created_at": datetime.now(UTC),
        "last_activity_at": datetime.now(UTC),
        "link": f"https://stackoverflow.com/questions/{question_id}/slug",
    }
    return QuestionMetadata(**{**defaults, **overrides})


class _FakeClient:
    def __init__(self, found=None, error: Exception | None = None):
        self._found = found or {}
        self._error = error
        self.calls = 0

    async def fetch_questions(self, ids):
        self.calls += 1
        if self._error:
            raise self._error
        return {i: self._found[i] for i in ids if i in self._found}


@pytest.fixture
async def _cleanup(db_session):
    yield
    await db_session.execute(delete(Question).where(Question.stackoverflow_question_id.in_(_TEST_IDS)))
    await db_session.commit()


# --- parsing ---


def test_parse_question_maps_closed_date_to_is_closed() -> None:
    assert parse_question({"question_id": 1, "closed_date": 1234567890}).is_closed is True
    assert parse_question({"question_id": 1}).is_closed is False


def test_parse_question_defaults_missing_counters_to_zero() -> None:
    parsed = parse_question({"question_id": 1})
    assert parsed.score == 0
    assert parsed.answer_count == 0
    assert parsed.accepted_answer_id is None


# --- filters (pure) ---


def test_closed_question_is_rejected() -> None:
    question = _question(1, is_closed=True, tags=["python"], body=_LONG_BODY, title="t")
    assert filter_service.evaluate(question, _profile()).reason == "closed"


def test_duplicate_question_is_rejected() -> None:
    question = _question(1, is_duplicate=True, tags=["python"], body=_LONG_BODY, title="t")
    assert filter_service.evaluate(question, _profile()).reason == "duplicate"


def test_already_presented_question_is_rejected() -> None:
    question = _question(1, status="presented", tags=["python"], body=_LONG_BODY, title="t")
    assert filter_service.evaluate(question, _profile()).reason == "already_presented"


def test_question_outside_topics_is_rejected() -> None:
    question = _question(1, tags=["haskell"], body=_LONG_BODY, title="Monads")
    assert filter_service.evaluate(question, _profile()).reason == "outside_topics"


def test_short_question_is_rejected_as_insufficient_information() -> None:
    question = _question(1, tags=["python"], body="too short", title="t")
    assert filter_service.evaluate(question, _profile()).reason == "insufficient_information"


def test_excluded_concept_is_rejected() -> None:
    question = _question(1, tags=["python"], body=_LONG_BODY + " homework ", title="t")
    profile = _profile(excluded_concepts=["homework"])
    assert filter_service.evaluate(question, profile).reason == "excluded_concept"


def test_good_question_survives() -> None:
    question = _question(1, tags=["python"], body=_LONG_BODY, title="Async gather runs sequentially")
    assert filter_service.evaluate(question, _profile()) is None


def test_empty_topic_list_does_not_reject_everything() -> None:
    # Before the user configures anything, nothing is "outside topics".
    question = _question(1, tags=["rust"], body=_LONG_BODY, title="t")
    assert filter_service.evaluate(question, _profile(topics=[])) is None


# --- enrichment stage (DB) ---


@pytest.mark.anyio
async def test_successful_enrichment_promotes_to_candidate(db_session, _cleanup) -> None:
    db_session.add(_question(_TEST_IDS[0]))
    await db_session.commit()

    client = _FakeClient(found={_TEST_IDS[0]: _metadata(_TEST_IDS[0])})
    result = await enrichment_service.run(db_session, _profile(), client=client)

    assert result.succeeded == 1
    question = await db_session.scalar(
        select(Question).where(Question.stackoverflow_question_id == _TEST_IDS[0])
    )
    assert question.status == "candidate"
    assert question.score == 5
    assert question.tags == ["python"]
    assert question.fetched_at is not None


@pytest.mark.anyio
async def test_stack_exchange_failure_keeps_question_pending_not_rejected(db_session, _cleanup) -> None:
    """The M5 headline rule: an outage must never reject a candidate."""
    db_session.add(_question(_TEST_IDS[1]))
    await db_session.commit()

    client = _FakeClient(error=StackExchangeError("503 upstream down"))
    result = await enrichment_service.run(db_session, _profile(), client=client)

    assert result.failed == 1
    question = await db_session.scalar(
        select(Question).where(Question.stackoverflow_question_id == _TEST_IDS[1])
    )
    assert question.status == "enrichment_pending", "an API outage must not reject the candidate"
    assert question.enrichment_attempts == 1
    assert question.next_retry_at is not None
    assert "503" in question.enrichment_error


@pytest.mark.anyio
async def test_question_missing_from_api_is_rejected(db_session, _cleanup) -> None:
    # The API answered and doesn't have it — genuinely gone, so this is the one
    # permanent failure, distinct from an outage.
    db_session.add(_question(_TEST_IDS[2]))
    await db_session.commit()

    result = await enrichment_service.run(db_session, _profile(), client=_FakeClient(found={}))

    assert result.skipped == 1
    question = await db_session.scalar(
        select(Question).where(Question.stackoverflow_question_id == _TEST_IDS[2])
    )
    assert question.status == "rejected"
    assert question.rejection_reason == "not_found_on_stack_overflow"


@pytest.mark.anyio
async def test_enriched_closed_question_is_rejected_and_never_a_candidate(db_session, _cleanup) -> None:
    db_session.add(_question(_TEST_IDS[3]))
    await db_session.commit()

    client = _FakeClient(found={_TEST_IDS[3]: _metadata(_TEST_IDS[3], is_closed=True)})
    await enrichment_service.run(db_session, _profile(), client=client)

    question = await db_session.scalar(
        select(Question).where(Question.stackoverflow_question_id == _TEST_IDS[3])
    )
    assert question.status == "rejected"
    assert question.rejection_reason == "closed"


@pytest.mark.anyio
async def test_backoff_defers_retry_so_a_dead_api_is_not_hammered(db_session, _cleanup) -> None:
    db_session.add(_question(_TEST_IDS[0]))
    await db_session.commit()

    client = _FakeClient(error=StackExchangeError("down"))
    now = datetime.now(UTC)
    await enrichment_service.run(db_session, _profile(), client=client, now=now)

    # A second run in the same instant must skip the row entirely.
    second = await enrichment_service.run(db_session, _profile(), client=client, now=now)
    assert second.processed == 0
    assert client.calls == 1

    # Once the backoff has elapsed it is picked up again.
    third = await enrichment_service.run(
        db_session, _profile(), client=client, now=now + timedelta(hours=12)
    )
    assert third.processed == 1


@pytest.mark.anyio
async def test_implausible_question_id_is_rejected_without_calling_the_api(db_session, _cleanup) -> None:
    """A malformed id 400s the whole batch at Stack Exchange, so it must never
    be sent — and it's a parse failure, not something retrying can fix.
    """
    question = _question(_TEST_IDS[0])
    question.stackoverflow_question_id = 99999999999  # out of int32 range
    db_session.add(question)
    await db_session.commit()

    client = _FakeClient(found={})
    try:
        result = await enrichment_service.run(db_session, _profile(), client=client)

        assert client.calls == 0, "an implausible id must never reach the API"
        assert result.skipped == 1
        stored = await db_session.scalar(
            select(Question).where(Question.stackoverflow_question_id == 99999999999)
        )
        assert stored.status == "rejected"
        assert stored.rejection_reason == "invalid_question_id"
    finally:
        await db_session.execute(
            delete(Question).where(Question.stackoverflow_question_id == 99999999999)
        )
        await db_session.commit()


@pytest.mark.anyio
async def test_permanent_bad_request_does_not_schedule_a_retry(db_session, _cleanup) -> None:
    # A 4xx will fail identically forever, so parking the row for retry would
    # loop it against a request that can never succeed.
    db_session.add(_question(_TEST_IDS[1]))
    await db_session.commit()

    client = _FakeClient(error=StackExchangeBadRequest("400 bad_parameter"))
    result = await enrichment_service.run(db_session, _profile(), client=client)

    assert result.failed == 1
    question = await db_session.scalar(
        select(Question).where(Question.stackoverflow_question_id == _TEST_IDS[1])
    )
    assert question.status == "enrichment_pending"
    assert question.next_retry_at is None, "a permanent rejection must not be queued for retry"
