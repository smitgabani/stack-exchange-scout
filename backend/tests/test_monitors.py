"""One live monitor per scout, and every billed monitor run in the ledger (M13 F0).

A Scout-mode run creates a monitor that keeps running — and billing — on its
own interval. These tests pin the promises that stop those piling up: a second
run is refused while one is live, replacing stops the old one before creating
anything, and runs a monitor does on its own schedule are recorded exactly once.

No test may reach Yutori: every client here is a fake.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.integrations.yutori import YutoriError
from app.models.scout_definition import ScoutDefinition, ScoutInstance, ScoutRun
from app.models.webhook_event import WebhookEvent
from app.repositories import credential_repository
from app.schemas.profile import ProfileData
from app.services import definition_service, scout_service

MARKER = "pytest-monitors"


@pytest.fixture
def profile_data() -> ProfileData:
    return ProfileData.model_validate(
        {"topics": [{"name": "rust", "weight": 80}], "preferred_concepts": [], "excluded_concepts": []}
    )


async def _make_definition(db, name: str) -> ScoutDefinition:
    return await definition_service.create_definition(db, name=name, notes=MARKER)


async def _drop_definition(db, definition: ScoutDefinition) -> None:
    await db.execute(delete(ScoutRun).where(ScoutRun.definition_id == definition.id))
    await db.execute(delete(ScoutInstance).where(ScoutInstance.definition_id == definition.id))
    await db.execute(delete(ScoutDefinition).where(ScoutDefinition.id == definition.id))
    await db.commit()


@pytest.fixture
async def definition(db_session):
    made = await _make_definition(db_session, "Monitor test")
    try:
        yield made
    finally:
        await _drop_definition(db_session, made)


@pytest.fixture
async def other_definition(db_session):
    made = await _make_definition(db_session, "Monitor test (other)")
    try:
        yield made
    finally:
        await _drop_definition(db_session, made)


@pytest.fixture(autouse=True)
async def clean_events(db_session):
    """WebhookEvent isn't snapshotted by conftest, so these tests tidy their own."""
    yield
    await db_session.execute(delete(WebhookEvent).where(WebhookEvent.event_id.like(f"{MARKER}%")))
    await db_session.commit()


class FakeClient:
    def __init__(self, *, stop_error: Exception | None = None):
        self.calls: list[tuple[str, object]] = []
        self.stop_error = stop_error

    async def create_scout(self, **kwargs):
        self.calls.append(("create_scout", kwargs))
        return {"id": f"{MARKER}-scout-{uuid.uuid4().hex[:8]}"}

    async def create_research_task(self, **kwargs):
        self.calls.append(("create_research_task", kwargs))
        return {"task_id": f"{MARKER}-task-{uuid.uuid4().hex[:8]}", "status": "queued"}

    async def mark_done(self, scout_id):
        self.calls.append(("mark_done", scout_id))
        if self.stop_error is not None:
            raise self.stop_error
        return {}

    async def get_scout(self, scout_id):
        self.calls.append(("get_scout", scout_id))
        return {"id": scout_id, "status": "active"}


def _patch(monkeypatch, client) -> None:
    async def fake(db):
        return client

    monkeypatch.setattr(scout_service, "get_client", fake)
    monkeypatch.setattr(settings, "public_base_url", "https://example.test")


async def _clear_in_flight(db) -> None:
    """The one-paid-run-at-a-time guard is global; settle any leftover runs."""
    await db.execute(
        ScoutRun.__table__.update().where(ScoutRun.status == "running").values(status="succeeded")
    )
    await db.commit()


async def _instance(db, definition, *, external_id=None, fingerprint=None, **extra) -> ScoutInstance:
    instance = ScoutInstance(
        definition_id=definition.id if definition else None,
        kind="scout",
        external_id=external_id or f"{MARKER}-scout-{uuid.uuid4().hex[:8]}",
        account_fingerprint=fingerprint,
        state="active",
        **extra,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return instance


async def _event(db, scout_id: str | None, *, question_ids=(101,)) -> WebhookEvent:
    payload: dict = {
        "event_type": "scout_update",
        "update": {
            "id": f"{MARKER}-{uuid.uuid4().hex[:8]}",
            "report_content": json.dumps(
                {
                    "questions": [
                        {"url": f"https://stackoverflow.com/questions/{q}"} for q in question_ids
                    ]
                }
            ),
        },
    }
    if scout_id is not None:
        payload["scout"] = {"id": scout_id}
    event = WebhookEvent(
        provider="yutori",
        event_id=payload["update"]["id"],
        event_type="scout_update",
        payload=payload,
        status="received",
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


# ---------------------------------------------------------------------------
# One live monitor per scout
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_second_scout_run_is_refused_while_a_monitor_is_live(
    db_session, definition, profile_data, monkeypatch
):
    """The bug this fixes: every press used to create another monitor."""
    client = FakeClient()
    _patch(monkeypatch, client)
    await _clear_in_flight(db_session)

    first = await definition_service.run_definition(
        db_session, definition, profile_data, mode="scout"
    )
    assert first.started is True
    await _clear_in_flight(db_session)

    second = await definition_service.run_definition(
        db_session, definition, profile_data, mode="scout"
    )
    assert second.started is False
    assert second.conflict == "live_monitor"
    assert second.live["external_id"] == first.external_id
    assert [c[0] for c in client.calls] == ["create_scout"]


@pytest.mark.anyio
async def test_replacing_stops_the_old_monitor_before_creating_the_new_one(
    db_session, definition, profile_data, monkeypatch
):
    client = FakeClient()
    _patch(monkeypatch, client)
    await _clear_in_flight(db_session)

    first = await definition_service.run_definition(
        db_session, definition, profile_data, mode="scout"
    )
    await _clear_in_flight(db_session)
    second = await definition_service.run_definition(
        db_session, definition, profile_data, mode="scout", replace=True
    )

    assert second.started is True
    assert [c[0] for c in client.calls] == ["create_scout", "mark_done", "create_scout"]
    assert client.calls[1][1] == first.external_id

    old = await db_session.get(ScoutInstance, uuid.UUID(first.instance_id))
    await db_session.refresh(old)
    assert old.state == "done"
    assert "superseded_at" in old.detail
    new = await db_session.get(ScoutInstance, uuid.UUID(second.instance_id))
    assert new.detail["replaces"] == first.external_id
    assert new.detail["output_interval"] == settings.scout_run_interval_seconds


@pytest.mark.anyio
async def test_nothing_is_created_when_the_old_monitor_cannot_be_stopped(
    db_session, definition, profile_data, monkeypatch
):
    """Two monitors running is exactly the state being prevented."""
    live = await _instance(db_session, definition)
    client = FakeClient(stop_error=YutoriError("Yutori is down"))
    _patch(monkeypatch, client)
    await _clear_in_flight(db_session)

    outcome = await definition_service.run_definition(
        db_session, definition, profile_data, mode="scout", replace=True
    )

    assert outcome.started is False
    assert "no new one was created" in outcome.error
    assert [c[0] for c in client.calls] == ["mark_done"]
    await db_session.refresh(live)
    assert live.state == "active"


@pytest.mark.anyio
async def test_another_accounts_monitor_is_not_replaced(
    db_session, definition, profile_data, monkeypatch
):
    await _instance(db_session, definition, fingerprint="someone-else")
    client = FakeClient()
    _patch(monkeypatch, client)

    async def mine(db, key_name):
        return SimpleNamespace(account_fingerprint="mine", label="Mine", key_name=key_name)

    monkeypatch.setattr(credential_repository, "get", mine)
    await _clear_in_flight(db_session)

    outcome = await definition_service.run_definition(
        db_session, definition, profile_data, mode="scout", replace=True
    )

    assert outcome.started is False
    assert "different API key" in outcome.error
    assert client.calls == []


@pytest.mark.anyio
async def test_research_runs_are_not_blocked_by_a_live_monitor(
    db_session, definition, profile_data, monkeypatch
):
    await _instance(db_session, definition)
    client = FakeClient()
    _patch(monkeypatch, client)
    await _clear_in_flight(db_session)

    outcome = await definition_service.run_definition(
        db_session, definition, profile_data, mode="research"
    )

    assert outcome.started is True
    assert [c[0] for c in client.calls] == ["create_research_task"]


@pytest.mark.anyio
async def test_the_run_route_answers_409_with_the_live_monitor(
    client, auth_cookies, db_session, definition, monkeypatch
):
    live = await _instance(db_session, definition)
    _patch(monkeypatch, FakeClient())

    async def has_key(db, key_name):
        return SimpleNamespace(account_fingerprint=None, label=None, key_name=key_name)

    monkeypatch.setattr(credential_repository, "get", has_key)
    await _clear_in_flight(db_session)

    # The route's require_yutori_key dependency checks that a key is stored.
    from app.api import deps

    async def ok():
        return None

    client.app.dependency_overrides[deps.require_yutori_key] = ok
    try:
        response = client.post(
            f"/scout-definitions/{definition.id}/run?mode=scout", cookies=auth_cookies
        )
    finally:
        client.app.dependency_overrides.pop(deps.require_yutori_key, None)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "live_monitor"
    assert detail["monitor"]["external_id"] == live.external_id


# ---------------------------------------------------------------------------
# Scheduled runs reach the ledger
# ---------------------------------------------------------------------------


async def _runs_for(db, instance) -> list[ScoutRun]:
    return list(await db.scalars(select(ScoutRun).where(ScoutRun.instance_id == instance.id)))


@pytest.mark.anyio
async def test_a_scheduled_update_is_recorded_once(db_session, definition):
    instance = await _instance(db_session, definition)
    event = await _event(db_session, instance.external_id, question_ids=(1, 2))

    await definition_service.record_scheduled_runs(db_session)
    await definition_service.record_scheduled_runs(db_session)

    runs = await _runs_for(db_session, instance)
    assert len(runs) == 1
    run = runs[0]
    assert run.kind == "scout"
    assert run.status == "succeeded"
    assert run.detail["trigger"] == "schedule"
    assert run.webhook_event_id == event.id
    assert run.questions_found == 2
    assert float(run.cost_usd) == settings.yutori_run_cost_usd


@pytest.mark.anyio
async def test_a_running_manual_run_keeps_its_own_update(db_session, definition):
    instance = await _instance(db_session, definition)
    db_session.add(
        ScoutRun(
            definition_id=definition.id,
            instance_id=instance.id,
            kind="scout",
            status="running",
            started_at=datetime.now(UTC) - timedelta(minutes=5),
        )
    )
    await db_session.commit()
    await _event(db_session, instance.external_id)

    await definition_service.record_scheduled_runs(db_session)

    runs = await _runs_for(db_session, instance)
    assert [r.status for r in runs] == ["running"]


@pytest.mark.anyio
async def test_a_late_update_completes_a_timed_out_run_instead_of_charging_twice(
    db_session, definition
):
    instance = await _instance(db_session, definition)
    timed_out = ScoutRun(
        definition_id=definition.id,
        instance_id=instance.id,
        kind="scout",
        status="timed_out",
        error="No update arrived before the timeout",
        started_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(timed_out)
    await db_session.commit()
    event = await _event(db_session, instance.external_id)

    await definition_service.record_scheduled_runs(db_session)

    runs = await _runs_for(db_session, instance)
    assert len(runs) == 1
    await db_session.refresh(timed_out)
    assert timed_out.status == "succeeded"
    assert timed_out.webhook_event_id == event.id
    assert timed_out.error is None


@pytest.mark.anyio
async def test_updates_older_than_the_monitor_record_are_not_counted(db_session, definition):
    """Those were the legacy single-Scout path's, already accounted for there."""
    external_id = f"{MARKER}-scout-{uuid.uuid4().hex[:8]}"
    await _event(db_session, external_id)
    instance = await _instance(db_session, definition, external_id=external_id)

    await definition_service.record_scheduled_runs(db_session)

    assert await _runs_for(db_session, instance) == []


@pytest.mark.anyio
async def test_a_manual_run_ignores_another_monitors_update(
    db_session, definition, monkeypatch
):
    """Before M13 any update after the run started was taken as its result."""
    mine = await _instance(db_session, definition)
    run = ScoutRun(
        definition_id=definition.id,
        instance_id=mine.id,
        kind="scout",
        status="running",
        started_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(run)
    await db_session.commit()
    await _event(db_session, f"{MARKER}-someone-elses-scout")
    _patch(monkeypatch, FakeClient())

    result = await definition_service.sync_run(db_session, run.id)

    assert result["status"] == "running"
    await db_session.refresh(run)
    assert run.webhook_event_id is None


@pytest.mark.anyio
async def test_a_manual_run_claims_its_own_monitors_update(db_session, definition, monkeypatch):
    mine = await _instance(db_session, definition)
    run = ScoutRun(
        definition_id=definition.id,
        instance_id=mine.id,
        kind="scout",
        status="running",
        started_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(run)
    await db_session.commit()
    event = await _event(db_session, mine.external_id)
    _patch(monkeypatch, FakeClient())

    result = await definition_service.sync_run(db_session, run.id)

    assert result["status"] == "succeeded"
    await db_session.refresh(run)
    assert run.webhook_event_id == event.id


# ---------------------------------------------------------------------------
# Clearing the pile-up
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stop_superseded_stops_only_the_older_monitors(
    db_session, definition, other_definition, monkeypatch
):
    older = await _instance(db_session, definition)
    newer = await _instance(db_session, definition)
    unrelated = await _instance(db_session, other_definition)
    client = FakeClient()
    _patch(monkeypatch, client)

    summary = await definition_service.monitors_summary(db_session)
    flagged = {m["external_id"] for m in summary["monitors"] if m["superseded"]}
    assert older.external_id in flagged
    assert newer.external_id not in flagged
    assert unrelated.external_id not in flagged

    result = await definition_service.stop_superseded(db_session)

    stopped_here = [c[1] for c in client.calls if c[0] == "mark_done"]
    assert older.external_id in stopped_here
    assert newer.external_id not in stopped_here
    assert unrelated.external_id not in stopped_here
    assert older.external_id in result["stopped"]
    await db_session.refresh(older)
    await db_session.refresh(newer)
    assert older.state == "done"
    assert newer.state == "active"


@pytest.mark.anyio
async def test_monthly_cost_follows_the_interval(db_session, definition):
    await _instance(db_session, definition, detail={"output_interval": 86400})

    summary = await definition_service.monitors_summary(db_session)
    row = next(m for m in summary["monitors"] if m["definition_id"] == str(definition.id))

    assert row["output_interval"] == 86400
    assert row["monthly_cost_usd"] == round(30 * settings.yutori_run_cost_usd, 2)
