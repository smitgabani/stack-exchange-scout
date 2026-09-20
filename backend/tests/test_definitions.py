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

    # The in-flight guard is global — one paid run at a time across the whole
    # app — so a real unfinished run in the shared database would refuse this.
    # Safe to clear: conftest restores these tables after the session.
    await db_session.execute(
        ScoutRun.__table__.update().where(ScoutRun.status == "running").values(status="succeeded")
    )
    await db_session.commit()

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


@pytest.mark.anyio
async def test_instances_report_which_account_owns_them(db_session, definition, monkeypatch):
    """Ownership decides whether anything on the page can act on a Scout, so it
    has to be reported per row rather than inferred."""
    from app.models.scout_definition import ScoutInstance
    from app.repositories import credential_repository
    from app.services import definition_service as svc

    mine = ScoutInstance(
        definition_id=definition.id, kind="scout", external_id="mine", account_fingerprint="aaaa"
    )
    theirs = ScoutInstance(
        definition_id=definition.id, kind="scout", external_id="theirs", account_fingerprint="bbbb"
    )
    unknown = ScoutInstance(definition_id=definition.id, kind="scout", external_id="old")
    db_session.add_all([mine, theirs, unknown])
    await db_session.commit()

    class Cred:
        account_fingerprint = "aaaa"
        label = "My key"
        key_name = "yutori_api_key"

    async def active(db, key_name):
        return Cred()

    async def listing(db, key_name):
        return [Cred()]

    monkeypatch.setattr(credential_repository, "get", active)
    monkeypatch.setattr(credential_repository, "list_for", listing)

    try:
        rows = {i["external_id"]: i for i in await svc.list_instances(db_session)}

        assert rows["mine"]["usable"] is True
        assert rows["mine"]["account_label"] == "My key"
        assert rows["theirs"]["usable"] is False
        # Unknown is not the same as foreign — locking it would strand every
        # row created before fingerprinting existed.
        assert rows["old"]["usable"] is None
    finally:
        for row in (mine, theirs, unknown):
            await db_session.delete(row)
        await db_session.commit()


@pytest.mark.anyio
async def test_the_same_key_twice_is_refused(db_session, monkeypatch):
    """Cheap and certain: the fingerprint is a hash of the key itself."""
    from app.repositories import credential_repository
    from app.services import account_service

    key = "yut_same_key_value"

    class Existing:
        account_fingerprint = account_service.fingerprint(key)
        label = "My key"
        key_name = "yutori_api_key"

    async def listing(db, key_name):
        return [Existing()]

    monkeypatch.setattr(credential_repository, "list_for", listing)

    found = await account_service.find_duplicate(db_session, key)

    assert found == ("same_key", "My key")


@pytest.mark.anyio
async def test_a_different_key_from_the_same_account_is_caught_by_its_scouts(
    db_session, definition, monkeypatch
):
    """The fingerprint cannot see this — a different key hashes differently, and
    Yutori exposes no account id. Two keys on one account do see the same
    Scouts, which is the only available proof."""
    from app.models.scout_definition import ScoutInstance
    from app.repositories import credential_repository
    from app.services import account_service

    instance = ScoutInstance(
        definition_id=definition.id,
        kind="scout",
        external_id="shared-scout",
        account_fingerprint="fingerprint-of-first-key",
    )
    db_session.add(instance)
    await db_session.commit()

    class Existing:
        account_fingerprint = "fingerprint-of-first-key"
        label = "First key"
        key_name = "yutori_api_key"

    async def listing(db, key_name):
        return [Existing()]

    class Client:
        def __init__(self, *a, **k):
            pass

        async def list_scouts(self, status=None):
            return {"scouts": [{"id": "shared-scout"}]}

    monkeypatch.setattr(credential_repository, "list_for", listing)
    monkeypatch.setattr(account_service, "YutoriClient", Client)

    try:
        found = await account_service.find_duplicate(db_session, "a_completely_different_key")
        assert found == ("same_account", "First key")
    finally:
        await db_session.delete(instance)
        await db_session.commit()


@pytest.mark.anyio
async def test_an_account_with_no_scouts_is_not_guessed_at(db_session, monkeypatch):
    """Undetectable stays undetectable. A fresh account has no Scouts to
    compare, and refusing it on a hunch would block a legitimate key."""
    from app.repositories import credential_repository
    from app.services import account_service

    class Existing:
        account_fingerprint = "something-else"
        label = "First key"
        key_name = "yutori_api_key"

    async def listing(db, key_name):
        return [Existing()]

    class Client:
        def __init__(self, *a, **k):
            pass

        async def list_scouts(self, status=None):
            return {"scouts": []}

    monkeypatch.setattr(credential_repository, "list_for", listing)
    monkeypatch.setattr(account_service, "YutoriClient", Client)

    assert await account_service.find_duplicate(db_session, "brand_new_key") is None


@pytest.mark.anyio
async def test_switching_the_active_key_does_not_trip_the_unique_index(db_session):
    """Two active rows for one provider are rejected by a partial unique index.
    Assigning the flags as ORM attributes let SQLAlchemy order the UPDATEs
    freely, and it switched the new key on before the old one off — a 500 on
    every attempt to change account."""
    from app.models.credential import Credential
    from app.repositories import credential_repository

    first = Credential(key_name="test_provider_key", encrypted_value="a", label="A", is_active=True)
    second = Credential(
        key_name="test_provider_key", encrypted_value="b", label="B", is_active=False
    )
    db_session.add_all([first, second])
    await db_session.commit()
    await db_session.refresh(first)
    await db_session.refresh(second)

    try:
        await credential_repository.activate(db_session, second)

        await db_session.refresh(first)
        await db_session.refresh(second)
        assert second.is_active is True
        assert first.is_active is False

        # And back again, which is where the ordering bug actually bit.
        await credential_repository.activate(db_session, first)
        await db_session.refresh(first)
        await db_session.refresh(second)
        assert first.is_active is True
        assert second.is_active is False
    finally:
        await db_session.execute(
            delete(Credential).where(Credential.key_name == "test_provider_key")
        )
        await db_session.commit()
