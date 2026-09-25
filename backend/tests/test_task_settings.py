"""Scout settings: validation, the request body they produce, and the routes (M13).

The preview a user sees and the body a run sends come from the same function,
so most of what matters is pinned here without any network or database.
"""

import copy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from sqlalchemy import delete

from app.core.config import settings
from app.integrations.yutori import CANDIDATE_OUTPUT_SCHEMA
from app.models.scout_definition import ScoutDefinition, ScoutInstance, ScoutRun
from app.schemas.profile import ProfileData
from app.schemas.yutori_settings import YutoriSettings, plain_errors
from app.services import definition_service, scout_service, task_settings

WEBHOOK = "https://example.test/webhooks/yutori?token=secret-token"


def _errors(body: dict) -> str:
    with pytest.raises(ValidationError) as caught:
        YutoriSettings.model_validate(body)
    return plain_errors(caught.value)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_an_interval_under_thirty_minutes_is_rejected_in_plain_words():
    assert "minimum is 30 minutes" in _errors({"output_interval_seconds": 600})


def test_an_unknown_timezone_is_rejected():
    assert "isn't a timezone name" in _errors({"user_timezone": "Mars/Olympus"})


def test_a_known_timezone_is_kept():
    assert YutoriSettings.model_validate({"user_timezone": "America/Toronto"}).user_timezone == (
        "America/Toronto"
    )


def test_an_output_format_without_a_required_url_is_rejected():
    schema = copy.deepcopy(CANDIDATE_OUTPUT_SCHEMA)
    schema["properties"]["questions"]["items"]["required"] = []
    assert 'must require "url"' in _errors({"output_schema": schema})


def test_an_output_format_without_a_questions_array_is_rejected():
    assert '"questions" array' in _errors({"output_schema": {"type": "object"}})


def test_start_at_needs_a_time_and_no_offset():
    assert "Choose a start time" in _errors({"start": "at"})
    assert "without a timezone" in _errors({"start": "at", "start_at": "2026-09-25T09:00+02:00"})


def test_subscribers_are_checked_and_deduplicated():
    assert "isn't an email address" in _errors({"subscribers": ["not-an-email"]})
    parsed = YutoriSettings.model_validate({"subscribers": ["A@Example.com", "a@example.com"]})
    assert parsed.subscribers == ["a@example.com"]


def test_the_webhook_cannot_be_set():
    assert "isn't a setting that can be changed" in _errors({"webhook_url": "https://evil.test"})


def test_only_set_fields_are_stored():
    assert YutoriSettings.model_validate({"is_public": False}).overrides() == {"is_public": False}


# ---------------------------------------------------------------------------
# The request body
# ---------------------------------------------------------------------------


def test_defaults_reproduce_what_the_app_sent_before_m13():
    eff = task_settings.built_in_defaults()
    payload = task_settings.build_payload("scout", "find rust questions", eff, WEBHOOK)
    assert payload == {
        "query": "find rust questions",
        "output_schema": CANDIDATE_OUTPUT_SCHEMA,
        "skip_email": True,
        "webhook_url": WEBHOOK,
        "webhook_format": "scout",
        "output_interval": settings.scout_run_interval_seconds,
        "is_public": False,
    }


def test_a_research_task_never_sends_scout_only_fields():
    eff = task_settings.effective(
        task_settings.built_in_defaults(),
        {"output_interval_seconds": 3600, "is_public": True, "start": "at", "start_at": "2026-09-25T09:00"},
    )
    payload = task_settings.build_payload("research_task", "q", eff, None)
    assert "output_interval" not in payload
    assert "is_public" not in payload
    assert "start_timestamp" not in payload
    assert "webhook_url" not in payload


def test_unset_timezone_and_location_are_left_out():
    payload = task_settings.build_payload("scout", "q", task_settings.built_in_defaults(), WEBHOOK)
    assert "user_timezone" not in payload
    assert "user_location" not in payload


def test_a_start_time_is_read_in_the_scouts_timezone():
    eff = task_settings.effective(
        task_settings.built_in_defaults(),
        {"start": "at", "start_at": "2026-09-25T09:00", "user_timezone": "America/Toronto"},
    )
    payload = task_settings.build_payload("scout", "q", eff, WEBHOOK)
    expected = datetime(2026, 9, 25, 9, 0, tzinfo=ZoneInfo("America/Toronto")).timestamp()
    assert payload["start_timestamp"] == int(expected)
    assert payload["user_timezone"] == "America/Toronto"


def test_email_from_yutori_turns_skip_email_off():
    eff = task_settings.effective(task_settings.built_in_defaults(), {"email_from_yutori": True})
    assert task_settings.build_payload("research_task", "q", eff, None)["skip_email"] is False


def test_the_webhook_secret_is_masked():
    payload = task_settings.build_payload("scout", "q", task_settings.built_in_defaults(), WEBHOOK)
    masked = task_settings.mask(payload)
    assert "secret-token" not in str(masked)
    assert masked["webhook_url"].startswith("https://example.test/webhooks/yutori")


def test_monthly_cost_is_runs_per_thirty_days_times_the_run_price():
    assert task_settings.monthly_cost(86400) == round(30 * settings.yutori_run_cost_usd, 2)
    assert task_settings.monthly_cost(30 * 86400) == settings.yutori_run_cost_usd


# ---------------------------------------------------------------------------
# Runs send the settings, and routes store them
# ---------------------------------------------------------------------------


@pytest.fixture
def profile_data() -> ProfileData:
    return ProfileData.model_validate(
        {"topics": [{"name": "rust", "weight": 80}], "preferred_concepts": [], "excluded_concepts": []}
    )


@pytest.fixture
async def definition(db_session):
    made = await definition_service.create_definition(
        db_session, name="Settings test", config={"default_mode": "scout"}
    )
    try:
        yield made
    finally:
        await db_session.execute(delete(ScoutRun).where(ScoutRun.definition_id == made.id))
        await db_session.execute(delete(ScoutInstance).where(ScoutInstance.definition_id == made.id))
        await db_session.execute(delete(ScoutDefinition).where(ScoutDefinition.id == made.id))
        await db_session.commit()


class RecordingClient:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def create_scout(self, **kwargs):
        self.calls.append(("create_scout", kwargs))
        return {"id": f"settings-test-{len(self.calls)}"}

    async def create_research_task(self, **kwargs):
        self.calls.append(("create_research_task", kwargs))
        return {"task_id": f"settings-task-{len(self.calls)}", "status": "queued"}

    async def update_email_settings(self, scout_id, **kwargs):
        self.calls.append(("update_email_settings", {"scout_id": scout_id, **kwargs}))
        return {}


def _patch(monkeypatch, client):
    async def fake(db):
        return client

    monkeypatch.setattr(scout_service, "get_client", fake)
    monkeypatch.setattr(settings, "public_base_url", "https://example.test")


async def _settle(db):
    await db.execute(
        ScoutRun.__table__.update().where(ScoutRun.status == "running").values(status="succeeded")
    )
    await db.commit()


@pytest.mark.anyio
async def test_a_scout_run_sends_the_scouts_settings_and_records_them(
    db_session, definition, profile_data, monkeypatch
):
    await definition_service.set_yutori_overrides(
        db_session,
        definition,
        {
            "output_interval_seconds": 86400,
            "user_timezone": "America/Toronto",
            "subscribers": ["me@example.com"],
        },
    )
    client = RecordingClient()
    _patch(monkeypatch, client)
    await _settle(db_session)

    outcome = await definition_service.run_definition(
        db_session, definition, profile_data, mode="scout"
    )

    assert outcome.started is True
    name, sent = client.calls[0]
    assert name == "create_scout"
    assert sent["output_interval_seconds"] == 86400
    assert sent["user_timezone"] == "America/Toronto"
    assert sent["is_public"] is False
    assert client.calls[1] == (
        "update_email_settings",
        {"scout_id": outcome.external_id, "add": ["me@example.com"]},
    )

    run = await db_session.get(ScoutRun, outcome.run_id)
    assert run.detail["sent"]["output_interval"] == 86400
    assert "query" not in run.detail["sent"]
    assert "token=secret" not in str(run.detail["sent"])
    instance = await db_session.get(ScoutInstance, outcome.instance_id)
    assert instance.detail["output_interval"] == 86400


@pytest.mark.anyio
async def test_saving_the_mode_keeps_the_yutori_settings(db_session, definition):
    """The run-mode toggle and the settings share one config column."""
    await definition_service.set_yutori_overrides(db_session, definition, {"is_public": False})
    await definition_service.update_definition(
        db_session, definition, {"config": {"default_mode": "research"}}
    )
    await db_session.refresh(definition)
    assert definition.config == {"default_mode": "research", "yutori": {"is_public": False}}


@pytest.mark.anyio
async def test_settings_routes_round_trip(client, auth_cookies, db_session, definition):
    base = f"/scout-definitions/{definition.id}/settings"

    fresh = client.get(base, cookies=auth_cookies).json()
    assert fresh["overrides"] == {}
    assert fresh["effective"]["output_interval_seconds"] == settings.scout_run_interval_seconds

    saved = client.put(
        base, json={"output_interval_seconds": 86400, "is_public": False}, cookies=auth_cookies
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["overrides"] == {"output_interval_seconds": 86400, "is_public": False}
    assert body["preview"]["scout"]["output_interval"] == 86400
    assert "output_interval" not in body["preview"]["research"]
    assert body["cost"]["monthly"] == round(30 * settings.yutori_run_cost_usd, 2)

    bad = client.put(base, json={"output_interval_seconds": 60}, cookies=auth_cookies)
    assert bad.status_code == 422
    assert "minimum is 30 minutes" in bad.json()["detail"]

    preview = client.post(
        f"{base}/preview", json={"output_interval_seconds": 3600}, cookies=auth_cookies
    ).json()
    assert preview["preview"]["scout"]["output_interval"] == 3600
    # A preview stores nothing.
    assert client.get(base, cookies=auth_cookies).json()["overrides"]["output_interval_seconds"] == 86400

    reset = client.delete(base, cookies=auth_cookies).json()
    assert reset["overrides"] == {}
