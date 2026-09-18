"""Scout lifecycle tests.

`conftest.py` points at the real (shared) database, so every test here
monkeypatches `YutoriClient`. Nothing in this file may reach Yutori's API: a
stray `create_scout` would start a billable run, and a stray `delete_scout`
would destroy the live Scout.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.api.scout import mask_webhook_url
from app.core.config import settings
from app.integrations.yutori import YutoriNotFound
from app.models.scout import Scout, ScoutEvent
from app.models.webhook_event import WebhookEvent
from app.schemas.profile import ProfileData
from app.services import scout_service


class FakeClient:
    """Records calls instead of making them."""

    def __init__(self, *, detail: dict | None = None, updates: list | None = None) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.detail = detail or {}
        self.updates = updates or []
        self.raise_not_found_on: set[str] = set()

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

    result = await scout_service.start_run(db_session, profile_data)

    assert result.action == "busy"
    assert client.calls == []


@pytest.mark.anyio
async def test_start_run_restarts_an_existing_scout(
    db_session, scout_row, profile_data, monkeypatch
):
    client = FakeClient(detail={"status": "active", "update_count": 3})
    _patch_client(monkeypatch, client)

    result = await scout_service.start_run(db_session, profile_data)

    assert result.action == "started"
    assert result.mechanism == "restart"
    assert "restart" in client.names()
    assert "create_scout" not in client.names()

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
        result = await scout_service.start_run(db_session, profile_data)

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

    result = await scout_service.start_run(db_session, profile_data)

    assert result.mechanism == "recreate"
    assert client.names().index("delete_scout") < client.names().index("create_scout")


@pytest.mark.anyio
async def test_start_run_records_cost_and_mechanism(
    db_session, scout_row, profile_data, monkeypatch
):
    client = FakeClient(detail={"status": "active"})
    _patch_client(monkeypatch, client)

    await scout_service.start_run(db_session, profile_data)

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

    result = await scout_service.start_run(db_session, profile_data)

    assert result.started_immediately is False


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
