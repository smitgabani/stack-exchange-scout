"""Per-run attribution: what a run returned, and what became of it.

The interesting case is the one that looks like a bug and is not. Ingest
dedupes on `canonical_url` and only moves `last_seen_at` on a re-sighting, so a
question a run returned but which was already known still points at the event
that *first* saw it. Counting yield by `questions.source_event_id` therefore
reports zero for a run that returned plenty — true about its new yield,
misleading about what it did. `run_detail` reads the run's stored payload
instead, and these tests pin that difference.

Rows are created under a `pytest-` marker and removed in teardown; the profile
and credentials are covered by `conftest.protect_real_data`.
"""

import uuid

import pytest
from sqlalchemy import delete

from app.core.db import async_session
from app.models.question import Question
from app.models.scout_definition import ScoutRun
from app.models.webhook_event import WebhookEvent
from app.services import definition_service

MARKER = "pytest-run-detail"


def _payload(question_ids: list[int]) -> dict:
    return {
        "event_type": "scout.update",
        "source": "pull",
        "update": {
            "id": f"{MARKER}-{uuid.uuid4().hex[:8]}",
            "report_content": {
                "questions": [
                    {
                        "url": f"https://stackoverflow.com/questions/{qid}",
                        "title": f"Question {qid}",
                        "tags": ["python"],
                        "difficulty": 3,
                    }
                    for qid in question_ids
                ]
            },
        },
    }


@pytest.fixture
async def scenario():
    """A run whose payload holds two questions: one new here, one already known.

    Built directly rather than through ingest so the attribution being tested
    is the thing under test, not the thing that set it up.
    """
    base = 990_000_000 + int(uuid.uuid4().int % 100_000)
    new_id, known_id = base, base + 1

    async with async_session() as session:
        this_event = WebhookEvent(
            provider="yutori",
            event_id=f"{MARKER}-this-{uuid.uuid4().hex[:8]}",
            event_type="scout.update",
            payload=_payload([new_id, known_id]),
            status="processed",
        )
        earlier_event = WebhookEvent(
            provider="yutori",
            event_id=f"{MARKER}-earlier-{uuid.uuid4().hex[:8]}",
            event_type="scout.update",
            payload=_payload([known_id]),
            status="processed",
        )
        session.add_all([this_event, earlier_event])
        await session.commit()
        await session.refresh(this_event)
        await session.refresh(earlier_event)

        run = ScoutRun(
            kind="research_task",
            status="succeeded",
            cost_usd=0.35,
            account_label="pytest",
            webhook_event_id=this_event.id,
            questions_found=2,
            delivered_by="poll",
        )
        # Discovered by this run.
        fresh = Question(
            stackoverflow_question_id=new_id,
            canonical_url=f"https://stackoverflow.com/questions/{new_id}",
            url=f"https://stackoverflow.com/questions/{new_id}",
            title=f"Question {new_id}",
            tags=["python"],
            status="candidate",
            candidate_score=80,
            source_event_id=this_event.id,
        )
        # Returned by this run, but first seen by the earlier one.
        known = Question(
            stackoverflow_question_id=known_id,
            canonical_url=f"https://stackoverflow.com/questions/{known_id}",
            url=f"https://stackoverflow.com/questions/{known_id}",
            title=f"Question {known_id}",
            tags=["python"],
            status="rejected",
            rejection_reason="closed_as_duplicate",
            source_event_id=earlier_event.id,
        )
        session.add_all([run, fresh, known])
        await session.commit()
        await session.refresh(run)
        ids = (run.id, this_event.id, earlier_event.id, new_id, known_id)

    yield ids

    async with async_session() as session:
        await session.execute(
            delete(Question).where(Question.stackoverflow_question_id.in_([new_id, known_id]))
        )
        await session.execute(delete(ScoutRun).where(ScoutRun.id == ids[0]))
        await session.execute(delete(WebhookEvent).where(WebhookEvent.id.in_([ids[1], ids[2]])))
        await session.commit()


@pytest.mark.anyio
async def test_a_rediscovered_question_still_counts_as_returned(scenario) -> None:
    """The bug this endpoint exists to avoid: attributing by source_event_id
    reports one question for a run that returned two.
    """
    run_id, *_ = scenario
    async with async_session() as session:
        detail = await definition_service.run_detail(session, run_id)

    assert detail["unique_questions"] == 2
    assert len(detail["questions"]) == 2


@pytest.mark.anyio
async def test_new_and_already_known_are_told_apart(scenario) -> None:
    run_id, _this, _earlier, new_id, known_id = scenario
    async with async_session() as session:
        detail = await definition_service.run_detail(session, run_id)

    by_id = {q["stackoverflow_question_id"]: q for q in detail["questions"]}
    assert by_id[new_id]["first_seen_here"] is True
    assert by_id[known_id]["first_seen_here"] is False
    assert detail["new_here"] == 1
    assert detail["already_known"] == 1


@pytest.mark.anyio
async def test_cost_per_new_question_ignores_rediscoveries(scenario) -> None:
    """$0.35 for one new question is the real price, not $0.175 for two."""
    run_id, *_ = scenario
    async with async_session() as session:
        detail = await definition_service.run_detail(session, run_id)

    assert detail["cost_per_new_question"] == pytest.approx(0.35)


@pytest.mark.anyio
async def test_each_question_reports_what_became_of_it(scenario) -> None:
    run_id, _this, _earlier, new_id, known_id = scenario
    async with async_session() as session:
        detail = await definition_service.run_detail(session, run_id)

    by_id = {q["stackoverflow_question_id"]: q for q in detail["questions"]}
    assert by_id[new_id]["fate"] == "in_pool"
    assert by_id[known_id]["fate"] == "filtered_out"
    assert by_id[known_id]["rejection_reason"] == "closed_as_duplicate"
    assert detail["fates"] == {"in_pool": 1, "filtered_out": 1}


@pytest.mark.anyio
async def test_an_uningested_result_is_reported_as_such(scenario) -> None:
    """A paid result still sitting in the inbox is the most expensive thing
    this page can show, so it has to be visible rather than read as an empty
    run.
    """
    run_id, this_event_id, *_ = scenario
    async with async_session() as session:
        event = await session.get(WebhookEvent, this_event_id)
        event.status = "received"
        await session.commit()

        detail = await definition_service.run_detail(session, run_id)

    assert detail["event_status"] == "received"
    assert detail["unique_questions"] == 2


@pytest.mark.anyio
async def test_a_run_with_no_stored_payload_does_not_crash() -> None:
    """Runs predating payload capture exist, and must render as "nothing
    recorded" rather than 500.
    """
    async with async_session() as session:
        run = ScoutRun(kind="research_task", status="succeeded", cost_usd=0.35, account_label="pytest")
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = run.id

    try:
        async with async_session() as session:
            detail = await definition_service.run_detail(session, run_id)

        assert detail["has_payload"] is False
        assert detail["unique_questions"] == 0
        assert detail["questions"] == []
        assert detail["cost_per_new_question"] is None
    finally:
        async with async_session() as session:
            await session.execute(delete(ScoutRun).where(ScoutRun.id == run_id))
            await session.commit()


@pytest.mark.anyio
async def test_an_unknown_run_is_none(scenario) -> None:
    async with async_session() as session:
        assert await definition_service.run_detail(session, uuid.uuid4()) is None
