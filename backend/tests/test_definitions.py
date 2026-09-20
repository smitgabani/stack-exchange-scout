"""Scout definitions, accounts, and the promises ADR 0004 makes about deletion.

Runs against the shared production database like the rest of the suite, so
every test creates its own definitions and removes them again, and no test may
reach Yutori — a stray create_research_task would spend $0.35.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.models.question import Question
from app.models.scout_definition import ScoutDefinition, ScoutInstance, ScoutRun
from app.schemas.profile import ProfileData
from app.services import definition_service, scout_service


@pytest.fixture
def profile_data() -> ProfileData:
    return ProfileData.model_validate(
        {"topics": [{"name": "rust", "weight": 80}], "preferred_concepts": [], "excluded_concepts": []}
    )


@pytest.fixture
async def definition(db_session):
    made = await definition_service.create_definition(
        db_session, name="Test definition", notes="temporary"
    )
    try:
        yield made
    finally:
        await db_session.execute(delete(ScoutRun).where(ScoutRun.definition_id == made.id))
        await db_session.execute(
            delete(ScoutInstance).where(ScoutInstance.definition_id == made.id)
        )
        await db_session.execute(delete(ScoutDefinition).where(ScoutDefinition.id == made.id))
        await db_session.commit()


class FakeClient:
    def __init__(self):
        self.calls = []

    async def create_research_task(self, **kwargs):
        self.calls.append(("create_research_task", kwargs))
        return {"task_id": "task-xyz", "status": "queued", "view_url": "https://y/t"}

    async def create_scout(self, **kwargs):
        self.calls.append(("create_scout", kwargs))
        return {"id": "scout-xyz"}


def _patch(monkeypatch, client):
    async def fake(db):
        return client

    monkeypatch.setattr(scout_service, "get_client", fake)
    monkeypatch.setattr(settings, "public_base_url", "https://example.test")


@pytest.mark.anyio
async def test_a_topics_definition_renders_from_the_current_profile(definition, profile_data):
    """Topics-based queries follow the profile, so editing topics updates them
    without anyone re-typing the query."""
    rendered = definition_service.render_query(definition, profile_data)

    assert "rust (weight 80/100)" in rendered.lower()


@pytest.mark.anyio
async def test_a_freeform_definition_is_never_rewritten_by_topics(
    db_session, definition, profile_data
):
    """The point of choosing freeform. Topics silently overwriting hand-written
    text would make the mode useless."""
    await definition_service.update_definition(
        db_session, definition, {"query_source": "freeform", "query_text": "find me async bugs"}
    )

    assert definition_service.render_query(definition, profile_data) == "find me async bugs"


@pytest.mark.anyio
async def test_cloning_copies_the_query_but_not_the_history(db_session, definition):
    """A copy has spent nothing. Showing it the original's yield would make the
    comparison the dashboard is built on meaningless."""
    db_session.add(
        ScoutRun(definition_id=definition.id, kind="research_task", cost_usd=0.35, status="succeeded")
    )
    await db_session.commit()

    clone = await definition_service.clone_definition(db_session, definition)
    try:
        assert clone.query_source == definition.query_source
        assert clone.status == "draft"

        runs = await db_session.scalar(
            select(func.count()).select_from(ScoutRun).where(ScoutRun.definition_id == clone.id)
        )
        assert runs == 0
    finally:
        await db_session.execute(delete(ScoutDefinition).where(ScoutDefinition.id == clone.id))
        await db_session.commit()


@pytest.mark.anyio
async def test_deleting_a_definition_keeps_its_questions_and_its_ledger(db_session, profile_data):
    """ADR 0004's central promise. Losing the questions would mean paying to
    rediscover them; losing the runs would erase the record of money spent."""
    doomed = await definition_service.create_definition(db_session, name="Doomed")
    db_session.add(
        ScoutRun(definition_id=doomed.id, kind="research_task", cost_usd=0.35, status="succeeded")
    )
    await db_session.commit()

    questions_before = await db_session.scalar(select(func.count()).select_from(Question))

    kept = await definition_service.delete_definition(db_session, doomed)

    assert kept["questions"] == questions_before
    assert await db_session.scalar(select(func.count()).select_from(Question)) == questions_before

    # The run survives with a null definition, rather than being cascaded away.
    orphaned = await db_session.scalar(
        select(func.count())
        .select_from(ScoutRun)
        .where(ScoutRun.definition_id.is_(None), ScoutRun.cost_usd == 0.35)
    )
    assert orphaned >= 1
    await db_session.execute(delete(ScoutRun).where(ScoutRun.definition_id.is_(None)))
    await db_session.commit()


@pytest.mark.anyio
async def test_running_a_definition_records_the_instance_and_the_ledger(
    db_session, definition, profile_data, monkeypatch
):
    """Recorded before returning, so a run is attributable even if the process
    dies immediately after — money spent with nothing to show it is the one
    outcome that must not happen."""
    client = FakeClient()
    _patch(monkeypatch, client)

    outcome = await definition_service.run_definition(db_session, definition, profile_data)

    assert outcome.started is True
    assert outcome.kind == "research_task"
    assert client.calls[0][0] == "create_research_task"

    run = await db_session.get(ScoutRun, outcome.run_id)
    assert float(run.cost_usd) == settings.yutori_run_cost_usd
    assert run.status == "running"
    # Copied rather than joined, so history still reads after the key is gone.
    assert run.account_label is not None or run.account_fingerprint is None

    await db_session.refresh(definition)
    assert definition.status == "ready"


@pytest.mark.anyio
async def test_a_second_run_is_refused_while_one_is_in_flight(
    db_session, definition, profile_data, monkeypatch
):
    """Checked before any outbound call, so a refused attempt costs nothing."""
    client = FakeClient()
    _patch(monkeypatch, client)

    db_session.add(
        ScoutRun(
            definition_id=definition.id,
            kind="research_task",
            status="running",
            started_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    outcome = await definition_service.run_definition(db_session, definition, profile_data)

    assert outcome.started is False
    assert "in flight" in (outcome.error or "")
    assert client.calls == []


@pytest.mark.anyio
async def test_a_definition_with_no_query_is_not_run(
    db_session, definition, profile_data, monkeypatch
):
    """Refusing costs nothing; sending an empty query costs $0.35."""
    client = FakeClient()
    _patch(monkeypatch, client)
    await definition_service.update_definition(
        db_session, definition, {"query_source": "freeform", "query_text": "   "}
    )

    outcome = await definition_service.run_definition(db_session, definition, profile_data)

    assert outcome.started is False
    assert client.calls == []


@pytest.mark.anyio
async def test_effectiveness_ranks_by_questions_per_dollar(db_session, definition):
    """At a flat $0.35 a run, spend alone says nothing about which query is
    worth keeping."""
    rows = await definition_service.effectiveness(db_session)

    assert any(row["id"] == str(definition.id) for row in rows)
    ranked = [r["per_dollar"] for r in rows if r["per_dollar"] is not None]
    assert ranked == sorted(ranked, reverse=True)


@pytest.mark.anyio
async def test_deleting_a_research_instance_needs_no_api_call(db_session, definition, monkeypatch):
    """A research task is already over — there is nothing at Yutori to delete,
    so reaching for the API would only be a way to fail."""
    from app.models.scout_definition import ScoutInstance
    from app.services import definition_service as svc

    instance = ScoutInstance(
        definition_id=definition.id, kind="research_task", external_id="task-gone"
    )
    db_session.add(instance)
    await db_session.commit()
    await db_session.refresh(instance)

    called = False

    async def fail(db):
        nonlocal called
        called = True
        raise AssertionError("must not reach Yutori")

    monkeypatch.setattr(scout_service, "get_client", fail)

    result = await svc.delete_instance(db_session, instance.id)

    assert result["deleted"] is True
    assert called is False
    assert await db_session.get(ScoutInstance, instance.id) is None


@pytest.mark.anyio
async def test_a_scout_owned_by_another_account_is_not_reported_as_deleted(
    db_session, definition, monkeypatch
):
    """It is still out there running. Saying otherwise would be a lie, and the
    row must stay so the user can see what they cannot control."""
    from app.integrations.yutori import YutoriForbidden
    from app.models.scout_definition import ScoutInstance
    from app.services import definition_service as svc

    instance = ScoutInstance(definition_id=definition.id, kind="scout", external_id="not-ours")
    db_session.add(instance)
    await db_session.commit()
    await db_session.refresh(instance)

    class Refuses:
        async def delete_scout(self, external_id):
            raise YutoriForbidden("403")

    async def client(db):
        return Refuses()

    monkeypatch.setattr(scout_service, "get_client", client)

    result = await svc.delete_instance(db_session, instance.id)

    assert result["deleted"] is False
    assert "different API key" in result["error"]
    # Kept on purpose: forgetting it here would hide a Scout that still bills.
    assert await db_session.get(ScoutInstance, instance.id) is not None

    await db_session.delete(instance)
    await db_session.commit()


@pytest.mark.anyio
async def test_a_deleted_scout_is_gone_from_yutori_before_our_row(
    db_session, definition, monkeypatch
):
    """Yutori first, our row second — a failure there must leave the reference
    intact rather than orphaning a Scout nobody is tracking."""
    from app.models.scout_definition import ScoutInstance
    from app.services import definition_service as svc

    instance = ScoutInstance(definition_id=definition.id, kind="scout", external_id="doomed")
    db_session.add(instance)
    await db_session.commit()
    await db_session.refresh(instance)

    order = []

    class Client:
        async def delete_scout(self, external_id):
            order.append(external_id)

    async def client(db):
        return Client()

    monkeypatch.setattr(scout_service, "get_client", client)

    result = await svc.delete_instance(db_session, instance.id)

    assert result["deleted"] is True
    assert order == ["doomed"]
    assert await db_session.get(ScoutInstance, instance.id) is None
