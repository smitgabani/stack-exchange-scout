"""Scout lifecycle tests.

`conftest.py` points at the real (shared) database, so every test here
monkeypatches `YutoriClient`. Nothing in this file may reach Yutori's API: a
stray `create_scout` would start a billable run, and a stray `delete_scout`
would destroy the live Scout.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select

from app.api.scout import mask_webhook_url
from app.core.config import settings
from app.integrations.yutori import YutoriError, YutoriNotFound
from app.models.scout import Scout, ScoutEvent
from app.models.webhook_event import WebhookEvent
from app.schemas.profile import ProfileData
from app.services import scout_service


async def _async_value(value):
    """Tiny awaitable so a coroutine function can be monkeypatched inline."""
    return value


class FakeClient:
    """Records calls instead of making them."""

    def __init__(self, *, detail: dict | None = None, updates: list | None = None) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.detail = detail or {}
        self.updates = updates or []
        self.raise_not_found_on: set[str] = set()
        self.research_task: dict = {"status": "running"}

    def _record(self, name: str, *args):
        self.calls.append((name, args))
        if name in self.raise_not_found_on:
            raise YutoriNotFound(f"404 from {name}")

    async def create_scout(self, **kwargs):
        self._record("create_scout", kwargs)
        return {"id": "new-scout-id"}

    async def update_scout(self, scout_id, **kwargs):
        self._record("update_scout", scout_id, kwargs)
        return {}

    async def restart(self, scout_id):
        self._record("restart", scout_id)
        return {}

    async def mark_done(self, scout_id):
        self._record("mark_done", scout_id)
        return {}

    async def delete_scout(self, scout_id):
        self._record("delete_scout", scout_id)
        return {}

    async def get_scout(self, scout_id):
        self._record("get_scout", scout_id)
        return self.detail

    async def get_updates(self, scout_id, *, page_size=20, cursor=None):
        self._record("get_updates", scout_id)
        return {"updates": self.updates}

    async def get_usage(self, period="30d"):
        self._record("get_usage", period)
        return {"scout_runs": 6, "num_active_scouts": 1, "active_scout_ids": ["scout-1"]}

    async def create_research_task(self, **kwargs):
        self._record("create_research_task", kwargs)
        return {"task_id": "task-1", "status": "queued", "view_url": "https://y/t/1"}

    async def get_research_task(self, task_id):
        self._record("get_research_task", task_id)
        return self.research_task

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


@pytest.fixture
def profile_data() -> ProfileData:
    return ProfileData.model_validate(
        {
            "topics": [{"name": "rust", "weight": 80}],
            "preferred_concepts": [],
            "excluded_concepts": [],
        }
    )


async def _snapshot_scouts(db_session) -> list[dict]:
    """Copy every scouts row out before a test clears the table.

    This suite runs against the shared production database, which holds the real
    Scout — and `external_scout_id` is the only link to the live Scout at
    Yutori. Losing it would mean the next run creates a second Scout: $0.35 and
    an orphan billing on its own interval. So the rows come back exactly as they
    were, primary keys included.
    """
    rows = (await db_session.scalars(select(Scout))).all()
    return [
        {column.name: getattr(row, column.name) for column in Scout.__table__.columns}
        for row in rows
    ]


async def _restore_scouts(db_session, snapshot: list[dict]) -> None:
    await db_session.execute(delete(Scout))
    for values in snapshot:
        await db_session.execute(Scout.__table__.insert().values(**values))
    await db_session.commit()


@pytest.fixture
async def scout_row(db_session):
    """A throwaway scout row, with the real one snapshotted and put back."""
    snapshot = await _snapshot_scouts(db_session)
    started_at = datetime.now(UTC)

    await db_session.execute(delete(Scout))
    await db_session.commit()

    scout = Scout(
        provider="yutori",
        external_scout_id="scout-1",
        query_text="old query",
        query_hash="oldhash",
        sync_status="active",
        run_state="idle",
        update_count=3,
    )
    db_session.add(scout)
    await db_session.commit()
    await db_session.refresh(scout)
    try:
        yield scout
    finally:
        # Only events this test produced — the timeline is real history.
        await db_session.execute(delete(ScoutEvent).where(ScoutEvent.created_at >= started_at))
        await _restore_scouts(db_session, snapshot)


def _patch_client(monkeypatch, client: FakeClient) -> None:
    async def fake_get_client(db):
        return client

    monkeypatch.setattr(scout_service, "get_client", fake_get_client)
    monkeypatch.setattr(settings, "public_base_url", "https://example.test")


@pytest.mark.anyio
async def test_start_run_refuses_while_a_run_is_in_flight(
    db_session, scout_row, profile_data, monkeypatch
):
    """The guard that stops a double-click buying two runs — and it must refuse
    before any outbound call, so a refused attempt costs nothing."""
    client = FakeClient()
    _patch_client(monkeypatch, client)

    scout_row.run_state = "running"
    scout_row.run_started_at = datetime.now(UTC)
    await db_session.commit()

    result = await scout_service.start_run(db_session, profile_data, mode="scout")

    assert result.action == "busy"
    assert client.calls == []


@pytest.mark.anyio
async def test_start_run_restarts_an_existing_scout(
    db_session, scout_row, profile_data, monkeypatch
):
    client = FakeClient(detail={"status": "active", "update_count": 3})
    _patch_client(monkeypatch, client)

    result = await scout_service.start_run(db_session, profile_data, mode="scout")

    assert result.action == "started"
    assert result.mechanism == "restart"
    assert "restart" in client.names()
    assert "create_scout" not in client.names()

    # Yutori rejects restart on a live Scout with 400 "Scout is not completed",
    # so the stop has to come first. Asserted as an order, not a presence.
    assert client.names().index("mark_done") < client.names().index("restart")

    await db_session.refresh(scout_row)
    assert scout_row.run_state == "running"
    assert scout_row.run_baseline_update_count == 3


@pytest.mark.anyio
async def test_start_run_creates_when_no_scout_exists(db_session, profile_data, monkeypatch):
    snapshot = await _snapshot_scouts(db_session)
    started_at = datetime.now(UTC)
    await db_session.execute(delete(Scout))
    await db_session.commit()

    client = FakeClient(detail={"status": "active"})
    _patch_client(monkeypatch, client)
    try:
        result = await scout_service.start_run(db_session, profile_data, mode="scout")

        assert result.action == "started"
        assert result.mechanism == "create"
        assert "create_scout" in client.names()
    finally:
        await db_session.execute(delete(ScoutEvent).where(ScoutEvent.created_at >= started_at))
        await _restore_scouts(db_session, snapshot)


@pytest.mark.anyio
async def test_start_run_recreate_mechanism_deletes_then_creates(
    db_session, scout_row, profile_data, monkeypatch
):
    """The fallback for if `/restart` turns out to only resume the schedule."""
    client = FakeClient(detail={"status": "active"})
    _patch_client(monkeypatch, client)
    monkeypatch.setattr(settings, "scout_run_mechanism", "recreate")

    result = await scout_service.start_run(db_session, profile_data, mode="scout")

    assert result.mechanism == "recreate"
    assert client.names().index("delete_scout") < client.names().index("create_scout")


@pytest.mark.anyio
async def test_start_run_records_cost_and_mechanism(
    db_session, scout_row, profile_data, monkeypatch
):
    client = FakeClient(detail={"status": "active"})
    _patch_client(monkeypatch, client)

    await scout_service.start_run(db_session, profile_data, mode="scout")

    event = await db_session.scalar(
        select(ScoutEvent).where(ScoutEvent.type == "run_started").order_by(ScoutEvent.created_at.desc())
    )
    assert event is not None
    assert float(event.cost_usd) == settings.yutori_run_cost_usd
    assert event.detail["mechanism"] == "restart"


@pytest.mark.anyio
async def test_start_run_reports_whether_the_run_began_immediately(
    db_session, scout_row, profile_data, monkeypatch
):
    """The experiment Yutori's docs don't answer: a next run far in the future
    means restart only resumed the schedule rather than firing a run."""
    later = datetime.now(UTC) + timedelta(days=30)
    client = FakeClient(detail={"status": "active", "next_run_timestamp": later.isoformat()})
    _patch_client(monkeypatch, client)

    result = await scout_service.start_run(db_session, profile_data, mode="scout")

    assert result.started_immediately is False


@pytest.mark.anyio
@pytest.mark.anyio
async def test_start_run_continues_when_mark_done_is_rejected(
    db_session, scout_row, profile_data, monkeypatch
):
    """An already-parked Scout may refuse another `done`. That must not stop the
    restart, which is the step that decides whether the run happened."""

    class RefusesDone(FakeClient):
        async def mark_done(self, scout_id):
            self.calls.append(("mark_done", (scout_id,)))
            raise YutoriError("400: Scout is not active")

    client = RefusesDone(detail={"status": "done"})
    _patch_client(monkeypatch, client)

    result = await scout_service.start_run(db_session, profile_data, mode="scout")

    assert result.action == "started"
    assert "restart" in client.names()


@pytest.mark.anyio
async def test_park_is_idempotent_and_survives_a_404(db_session, scout_row, monkeypatch):
    client = FakeClient()
    client.raise_not_found_on = {"mark_done"}
    _patch_client(monkeypatch, client)

    first = await scout_service.park(db_session)
    second = await scout_service.park(db_session)

    assert first.action == "parked"
    assert second.action == "parked"


@pytest.mark.anyio
async def test_finish_run_completes_when_a_webhook_arrived(db_session, scout_row, monkeypatch):
    client = FakeClient(detail={"status": "active", "update_count": 3})
    _patch_client(monkeypatch, client)

    scout_row.run_state = "running"
    scout_row.run_started_at = datetime.now(UTC) - timedelta(minutes=5)
    scout_row.run_baseline_update_count = 3
    await db_session.commit()

    event = WebhookEvent(
        provider="yutori",
        event_id=f"test-{datetime.now(UTC).timestamp()}",
        payload={"update": {}},
        status="received",
    )
    db_session.add(event)
    await db_session.commit()

    try:
        assert await scout_service.finish_run_if_complete(db_session) is True
        await db_session.refresh(scout_row)
        assert scout_row.run_state == "idle"
        assert "mark_done" in client.names()
    finally:
        await db_session.delete(event)
        await db_session.commit()


@pytest.mark.anyio
async def test_finish_run_completes_when_update_count_moved(db_session, scout_row, monkeypatch):
    """Catches a run whose webhook was lost entirely — Yutori's own counter is
    the evidence that the run produced something."""
    client = FakeClient(detail={"status": "active", "update_count": 4})
    _patch_client(monkeypatch, client)

    scout_row.run_state = "running"
    scout_row.run_started_at = datetime.now(UTC)
    scout_row.run_baseline_update_count = 3
    scout_row.detail_refreshed_at = None
    await db_session.commit()

    assert await scout_service.finish_run_if_complete(db_session) is True
    await db_session.refresh(scout_row)
    assert scout_row.run_state == "idle"


@pytest.mark.anyio
async def test_finish_run_times_out_a_run_that_produced_nothing(
    db_session, scout_row, monkeypatch
):
    """A run that finds nothing never webhooks, so without the timeout the Scout
    would sit 'running' forever and never get parked."""
    client = FakeClient(detail={"status": "active", "update_count": 3})
    _patch_client(monkeypatch, client)

    scout_row.run_state = "running"
    scout_row.run_started_at = datetime.now(UTC) - timedelta(
        seconds=settings.scout_run_timeout_seconds + 60
    )
    scout_row.run_baseline_update_count = 3
    await db_session.commit()

    assert await scout_service.finish_run_if_complete(db_session) is True
    await db_session.refresh(scout_row)
    assert scout_row.run_state == "idle"


@pytest.mark.anyio
async def test_finish_run_does_nothing_while_a_run_is_genuinely_in_flight(
    db_session, scout_row, monkeypatch
):
    client = FakeClient(detail={"status": "active", "update_count": 3})
    _patch_client(monkeypatch, client)

    scout_row.run_state = "running"
    scout_row.run_started_at = datetime.now(UTC)
    scout_row.run_baseline_update_count = 3
    scout_row.detail_refreshed_at = None
    await db_session.commit()

    assert await scout_service.finish_run_if_complete(db_session) is False
    await db_session.refresh(scout_row)
    assert scout_row.run_state == "running"
    assert "mark_done" not in client.names()


@pytest.mark.anyio
async def test_pull_ingests_a_missed_update_once(db_session, scout_row, monkeypatch):
    """The recovery path: Yutori gives up after 3 attempts in ~30s, so an update
    can be lost for good. Pulling it back must not double-ingest."""
    update_id = f"pulled-{datetime.now(UTC).timestamp()}"
    client = FakeClient(
        updates=[
            {
                "id": update_id,
                "timestamp": int(datetime.now(UTC).timestamp()),
                "structured_result": {"questions": [{"url": "https://stackoverflow.com/questions/12345"}]},
                "structured_output_status": "succeeded",
            }
        ]
    )
    _patch_client(monkeypatch, client)

    try:
        first = await scout_service.pull_missed_updates(db_session)
        second = await scout_service.pull_missed_updates(db_session)

        assert first["ingested"] == 1
        assert second["ingested"] == 0
        assert second["duplicates"] == 1
    finally:
        await db_session.execute(delete(WebhookEvent).where(WebhookEvent.event_id == update_id))
        await db_session.commit()


def test_update_envelope_prefers_structured_result():
    """The updates API has no report_content, so pulled updates are reshaped to
    look like a webhook body — which keeps webhook parsing untouched."""
    from app.services.ingest_service import parse_candidates

    envelope = scout_service.update_to_webhook_envelope(
        {
            "id": "u1",
            "content": "prose that should be ignored",
            "structured_result": {"questions": [{"url": "https://stackoverflow.com/questions/999"}]},
        }
    )
    assert parse_candidates(envelope) == [{"url": "https://stackoverflow.com/questions/999"}]


def test_update_envelope_falls_back_to_prose_content():
    from app.services.ingest_service import parse_candidates

    envelope = scout_service.update_to_webhook_envelope(
        {"id": "u2", "content": "look at https://stackoverflow.com/questions/4242 today"}
    )
    assert parse_candidates(envelope) == [{"question_id": "4242"}]


def test_webhook_url_is_masked_before_leaving_the_backend():
    """The registered webhook URL carries YUTORI_WEBHOOK_SECRET, which is the
    only thing authenticating inbound candidate data."""
    masked = mask_webhook_url("https://api.example.com/webhooks/yutori?token=supersecret")

    assert masked == "https://api.example.com/webhooks/yutori"
    assert "supersecret" not in masked


def test_mask_handles_missing_and_malformed_urls():
    assert mask_webhook_url(None) is None
    assert mask_webhook_url("not-a-url?token=secret") == "(configured)"


@pytest.mark.anyio
async def test_research_run_creates_a_task_and_never_touches_the_scout(
    db_session, scout_row, profile_data, monkeypatch
):
    """The default mode. A research task needs no Scout lifecycle at all, which
    is the whole reason ADR 0004 prefers it."""
    client = FakeClient()
    _patch_client(monkeypatch, client)

    result = await scout_service.start_run(db_session, profile_data)

    assert result.action == "started"
    assert result.mechanism == "research_task"
    # Unlike restart, creating a research task genuinely starts it.
    assert result.started_immediately is True
    assert "create_research_task" in client.names()
    for scout_call in ("restart", "mark_done", "delete_scout", "create_scout"):
        assert scout_call not in client.names()

    await db_session.refresh(scout_row)
    assert scout_row.run_state == "running"
    assert scout_row.run_kind == "research_task"
    assert scout_row.run_external_id == "task-1"


@pytest.mark.anyio
async def test_research_run_is_left_alone_by_the_scout_finisher(
    db_session, scout_row, profile_data, monkeypatch
):
    """finish_run_if_complete parks Scouts. A research run has no Scout to park,
    so it must not be closed out from there."""
    client = FakeClient(detail={"status": "active", "update_count": 99})
    _patch_client(monkeypatch, client)

    scout_row.run_state = "running"
    scout_row.run_kind = "research_task"
    scout_row.run_external_id = "task-1"
    scout_row.run_started_at = datetime.now(UTC) - timedelta(days=1)
    scout_row.run_baseline_update_count = 1
    await db_session.commit()

    assert await scout_service.finish_run_if_complete(db_session) is False
    await db_session.refresh(scout_row)
    assert scout_row.run_state == "running"
    assert "mark_done" not in client.names()


@pytest.mark.anyio
async def test_polling_a_succeeded_research_task_ingests_its_result_once(
    db_session, scout_row, monkeypatch
):
    """The reason a research run cannot be lost: the result is fetched, not
    waited for. And the poll must not double-ingest what the webhook delivered."""
    task_id = f"task-{datetime.now(UTC).timestamp()}"
    client = FakeClient()
    client.research_task = {
        "task_id": task_id,
        "status": "succeeded",
        "structured_result": {
            "questions": [{"url": "https://stackoverflow.com/questions/777001"}]
        },
        "structured_output_status": "succeeded",
    }
    _patch_client(monkeypatch, client)

    scout_row.run_state = "running"
    scout_row.run_kind = "research_task"
    scout_row.run_external_id = task_id
    scout_row.run_started_at = datetime.now(UTC)
    await db_session.commit()

    try:
        first = await scout_service.poll_research_run(db_session)
        assert first["status"] == "succeeded"
        assert first["ingested"] == 1

        await db_session.refresh(scout_row)
        assert scout_row.run_state == "idle"

        # A second poll after the run closed does nothing at all.
        second = await scout_service.poll_research_run(db_session)
        assert second["status"] == "not_running"
    finally:
        await db_session.execute(
            delete(WebhookEvent).where(WebhookEvent.event_id == task_id)
        )
        await db_session.commit()


@pytest.mark.anyio
async def test_polling_leaves_an_unfinished_research_task_running(
    db_session, scout_row, monkeypatch
):
    client = FakeClient()
    client.research_task = {"task_id": "task-1", "status": "running"}
    _patch_client(monkeypatch, client)

    scout_row.run_state = "running"
    scout_row.run_kind = "research_task"
    scout_row.run_external_id = "task-1"
    scout_row.run_started_at = datetime.now(UTC)
    await db_session.commit()

    result = await scout_service.poll_research_run(db_session)

    assert result["status"] == "running"
    await db_session.refresh(scout_row)
    assert scout_row.run_state == "running"


@pytest.mark.anyio
async def test_a_failed_research_task_closes_the_run_and_records_why(
    db_session, scout_row, monkeypatch
):
    """A billing failure must not look like a run that found nothing."""
    client = FakeClient()
    client.research_task = {
        "task_id": "task-1",
        "status": "failed",
        "rejection_reason": "insufficient_prepaid_balance",
    }
    _patch_client(monkeypatch, client)

    scout_row.run_state = "running"
    scout_row.run_kind = "research_task"
    scout_row.run_external_id = "task-1"
    scout_row.run_started_at = datetime.now(UTC)
    await db_session.commit()

    result = await scout_service.poll_research_run(db_session)

    assert result["status"] == "failed"
    await db_session.refresh(scout_row)
    assert scout_row.run_state == "idle"

    event = await db_session.scalar(
        select(ScoutEvent)
        .where(ScoutEvent.type == "error")
        .order_by(ScoutEvent.created_at.desc())
    )
    assert event.detail["rejection_reason"] == "insufficient_prepaid_balance"


@pytest.mark.anyio
async def test_a_scout_from_another_account_is_not_edited(
    db_session, scout_row, profile_data, monkeypatch
):
    """Yutori answers 403 "Only the creator of a scout can edit it". Knowing the
    owner beforehand turns that into an explanation instead of a failure."""
    client = FakeClient()
    _patch_client(monkeypatch, client)
    # sync() reads the key itself rather than going through get_client, so both
    # have to be stubbed for the guard to be the thing under test.
    monkeypatch.setattr(scout_service, "get_api_key", lambda db, name: _async_value("key-b"))
    monkeypatch.setattr(
        scout_service, "current_fingerprint", lambda db: _async_value("bbbbbbbbbbbbbbbb")
    )

    scout_row.account_fingerprint = "aaaaaaaaaaaaaaaa"
    await db_session.commit()

    assert await scout_service.account_mismatch(db_session, scout_row) is True

    result = await scout_service.sync(db_session, profile_data, allow_create=True)

    assert result.action == "skipped"
    assert "different Yutori API key" in (result.error or "")
    # The point of knowing: no call is made that could only have failed.
    assert client.calls == []


@pytest.mark.anyio
async def test_an_unknown_owner_is_not_treated_as_a_mismatch(db_session, scout_row):
    """A NULL fingerprint predates the column. Unknown is not wrong — blocking
    on it would strand every Scout created before fingerprinting existed."""
    scout_row.account_fingerprint = None
    await db_session.commit()

    assert await scout_service.account_mismatch(db_session, scout_row) is False


@pytest.mark.anyio
async def test_forgetting_a_scout_keeps_every_discovered_question(
    db_session, scout_row, monkeypatch
):
    """ADR 0004: removing a link never removes what it found, or the user would
    rediscover and re-pay for questions they have already seen."""
    from app.models.question import Question

    before = await db_session.scalar(select(func.count()).select_from(Question))

    result = await scout_service.forget_remote_scout(db_session)

    assert result["action"] == "forgotten"
    await db_session.refresh(scout_row)
    assert scout_row.external_scout_id is None
    assert scout_row.account_fingerprint is None

    after = await db_session.scalar(select(func.count()).select_from(Question))
    assert after == before


def test_fingerprint_identifies_without_revealing():
    key = "yut_super_secret_key_value"
    printed = scout_service.fingerprint(key)

    assert len(printed) == 16
    assert printed == scout_service.fingerprint(key)
    assert printed != scout_service.fingerprint(key + "x")
    assert key not in printed
