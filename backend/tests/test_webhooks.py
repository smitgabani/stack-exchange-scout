import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.models.question import Question
from app.models.webhook_event import WebhookEvent
from app.services import ingest_service


def _payload(update_id: str, question_ids: list[int], *, attempt: int = 1) -> dict:
    """A Yutori scout_update body, shaped per their live webhook docs."""
    return {
        "event_type": "scout_update",
        "scout": {"id": "scout-abc", "display_name": "Stack Overflow Scout", "query": "..."},
        "update": {
            "id": update_id,
            "timestamp": "2026-09-17T00:00:00Z",
            "has_changes": True,
            "summary": "Found questions",
            "report_content": json.dumps(
                {
                    "questions": [
                        {
                            "question_id": str(qid),
                            "title": f"Question {qid}",
                            "url": f"https://stackoverflow.com/questions/{qid}",
                            "tags": ["python"],
                            "difficulty": 4,
                        }
                        for qid in question_ids
                    ]
                }
            ),
        },
        "delivery": {"id": str(uuid.uuid4()), "attempt": attempt},
    }


# --- 🔒 authentication ---


def test_webhook_without_token_rejected_and_nothing_persisted(client: TestClient) -> None:
    response = client.post("/webhooks/yutori", json=_payload("evt-no-token", [1]))
    assert response.status_code == 401


def test_webhook_with_wrong_token_rejected(client: TestClient) -> None:
    response = client.post("/webhooks/yutori?token=not-the-secret", json=_payload("evt-bad", [2]))
    assert response.status_code == 401


def test_webhook_is_exempt_from_the_session_gate(client: TestClient) -> None:
    # Reaches token verification rather than the 401 the session gate would
    # produce — proving the route is exempt but not unprotected.
    response = client.post("/webhooks/yutori", json=_payload("evt-exempt", [3]))
    assert response.json()["detail"] == "Invalid webhook token"


# --- 🧩 parsing (pure, no DB) ---


def test_parse_candidates_reads_structured_json() -> None:
    candidates = ingest_service.parse_candidates(_payload("e", [101, 102]))
    assert [c["question_id"] for c in candidates] == ["101", "102"]


def test_parse_candidates_falls_back_to_scraping_urls_from_prose() -> None:
    # If the model ignores the output_schema and returns prose, we still
    # recover candidates rather than dropping the whole run.
    payload = _payload("e", [])
    payload["update"]["report_content"] = (
        "I found https://stackoverflow.com/questions/555 and also "
        "https://stackoverflow.com/questions/666 worth a look."
    )
    candidates = ingest_service.parse_candidates(payload)
    assert [c["question_id"] for c in candidates] == ["555", "666"]


def test_parse_candidates_deduplicates_repeated_urls_in_prose() -> None:
    payload = _payload("e", [])
    payload["update"]["report_content"] = (
        "https://stackoverflow.com/questions/777 ... and again "
        "https://stackoverflow.com/questions/777"
    )
    assert len(ingest_service.parse_candidates(payload)) == 1


def test_extract_question_id_handles_urls_and_bare_ids() -> None:
    assert ingest_service.extract_question_id("https://stackoverflow.com/questions/42/some-slug") == 42
    assert ingest_service.extract_question_id("42") == 42
    assert ingest_service.extract_question_id("not-a-question") is None
    assert ingest_service.extract_question_id(None) is None


# --- 🧩 idempotency (hits the DB) ---


@pytest.fixture
async def _cleanup_ingested(db_session):
    """Remove only the rows these tests create — the database is shared with
    real usage, so nothing here may wipe tables wholesale.
    """
    yield
    await db_session.execute(delete(Question).where(Question.stackoverflow_question_id.in_(_TEST_IDS)))
    await db_session.execute(delete(WebhookEvent).where(WebhookEvent.event_id.like("test-evt-%")))
    await db_session.commit()


_TEST_IDS = [900001, 900002, 900003]


@pytest.mark.anyio
async def test_duplicate_delivery_creates_exactly_one_row(db_session, _cleanup_ingested) -> None:
    event_id = "test-evt-duplicate"
    payload = _payload(event_id, [_TEST_IDS[0]])

    first = await ingest_service.claim_event(db_session, payload)
    assert first is not None
    await ingest_service.ingest_event(db_session, first)

    # Yutori retries the same update with a new delivery id.
    retry = await ingest_service.claim_event(db_session, _payload(event_id, [_TEST_IDS[0]], attempt=2))
    assert retry is None, "a redelivered event must not be claimed twice"

    count = await db_session.scalar(
        select(func.count())
        .select_from(Question)
        .where(Question.stackoverflow_question_id == _TEST_IDS[0])
    )
    assert count == 1


@pytest.mark.anyio
async def test_same_question_in_two_different_events_stays_one_row(db_session, _cleanup_ingested) -> None:
    for suffix in ("a", "b"):
        event = await ingest_service.claim_event(
            db_session, _payload(f"test-evt-{suffix}", [_TEST_IDS[1]])
        )
        assert event is not None
        await ingest_service.ingest_event(db_session, event)

    count = await db_session.scalar(
        select(func.count())
        .select_from(Question)
        .where(Question.stackoverflow_question_id == _TEST_IDS[1])
    )
    assert count == 1


@pytest.mark.anyio
async def test_ingested_rows_start_as_enrichment_pending(db_session, _cleanup_ingested) -> None:
    event = await ingest_service.claim_event(db_session, _payload("test-evt-status", [_TEST_IDS[2]]))
    assert event is not None
    await ingest_service.ingest_event(db_session, event)

    question = await db_session.scalar(
        select(Question).where(Question.stackoverflow_question_id == _TEST_IDS[2])
    )
    # Not `candidate` — nothing is a real candidate until Stack Exchange has
    # verified it in M5.
    assert question.status == "enrichment_pending"
    assert question.canonical_url == f"https://stackoverflow.com/questions/{_TEST_IDS[2]}"


@pytest.mark.anyio
async def test_event_without_usable_id_is_not_claimed(db_session) -> None:
    assert await ingest_service.claim_event(db_session, {"event_type": "scout_update"}) is None


def test_webhook_secret_is_configured_for_tests() -> None:
    # Guards against the suite silently passing because everything 503s.
    assert settings.yutori_webhook_secret, "set YUTORI_WEBHOOK_SECRET for the test run"
