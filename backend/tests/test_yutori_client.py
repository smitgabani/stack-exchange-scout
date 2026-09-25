"""The exact bodies YutoriClient sends (M13).

Every other test swaps the whole client for a fake, so until now nothing
checked what actually goes over the wire. An httpx.MockTransport stands in
for Yutori here: requests are captured, never sent.
"""

import json

import httpx
import pytest

from app.integrations.yutori import CANDIDATE_OUTPUT_SCHEMA, YutoriClient
from app.services import task_settings

WEBHOOK = "https://example.test/webhooks/yutori?token=t"


def _client() -> tuple[YutoriClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "scout-1", "task_id": "task-1"})

    return YutoriClient("key", transport=httpx.MockTransport(handler)), seen


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


@pytest.mark.anyio
async def test_create_scout_sends_what_the_preview_shows():
    """The preview and the real request must never disagree."""
    eff = task_settings.effective(
        task_settings.built_in_defaults(),
        {
            "output_interval_seconds": 7200,
            "user_timezone": "America/Toronto",
            "user_location": "Toronto, ON, Canada",
            "start": "at",
            "start_at": "2026-09-25T09:00",
            "email_from_yutori": True,
        },
    )
    expected = task_settings.build_payload("scout", "q", eff, WEBHOOK)
    client, seen = _client()

    await client.create_scout(
        query="q",
        webhook_url=expected["webhook_url"],
        output_interval_seconds=expected["output_interval"],
        skip_email=expected["skip_email"],
        is_public=expected["is_public"],
        output_schema=expected["output_schema"],
        start_timestamp=expected["start_timestamp"],
        user_timezone=expected["user_timezone"],
        user_location=expected["user_location"],
    )

    assert seen[0].method == "POST"
    assert seen[0].url.path == "/v1/scouting/tasks"
    assert _body(seen[0]) == expected


@pytest.mark.anyio
async def test_create_research_task_sends_location_and_schema():
    client, seen = _client()
    await client.create_research_task(
        query="q", user_location="Toronto, ON, Canada", output_schema=CANDIDATE_OUTPUT_SCHEMA
    )
    body = _body(seen[0])
    assert seen[0].url.path == "/v1/research/tasks"
    assert body["user_location"] == "Toronto, ON, Canada"
    assert body["output_schema"] == CANDIDATE_OUTPUT_SCHEMA
    assert "output_interval" not in body


@pytest.mark.anyio
async def test_update_scout_leaves_visibility_alone_unless_asked():
    """Before M13 every PATCH sent is_public: false, which would undo a choice."""
    client, seen = _client()
    await client.update_scout("scout-1", user_timezone="America/Toronto")
    body = _body(seen[0])
    assert seen[0].method == "PATCH"
    assert body == {"user_timezone": "America/Toronto"}


@pytest.mark.anyio
async def test_update_scout_never_sends_a_start_time_and_floors_the_interval():
    client, seen = _client()
    await client.update_scout("scout-1", output_interval_seconds=1800, is_public=True)
    body = _body(seen[0])
    assert body == {"output_interval": 3600, "is_public": True}


@pytest.mark.anyio
async def test_email_settings_add_and_remove_subscribers():
    client, seen = _client()
    await client.update_email_settings("scout-1", add=["a@example.com"], remove=["b@example.com"])
    assert seen[0].method == "PUT"
    assert seen[0].url.path == "/v1/scouting/tasks/scout-1/email-settings"
    assert _body(seen[0]) == {
        "subscribers_to_add": ["a@example.com"],
        "subscribers_to_remove": ["b@example.com"],
    }
