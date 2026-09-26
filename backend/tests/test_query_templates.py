"""The editable query template and the Yutori defaults (M13).

The template is the other prompt this app writes — the one sent to Yutori —
so it gets the same guarantees as the LLM prompt: versions are immutable,
rollback reactivates a row, and a template that can't be filled is refused
before it can cost a run.

Rows are created and removed by fixtures; nothing that was already in the
tables is touched.
"""

import pytest

from app.core.db import async_session
from app.models.query_template import QueryTemplate, YutoriDefaults
from app.schemas.profile import ProfileData
from app.schemas.yutori_settings import YutoriSettings
from app.services import (
    definition_service,
    query_generator,
    query_template_service,
    yutori_defaults_service,
)
from app.services.query_template_service import QueryTemplateError
from tests.conftest import delete_rows_added_since, existing_ids

PROFILE = ProfileData.model_validate(
    {"topics": [{"name": "rust", "weight": 80}], "preferred_concepts": [], "excluded_concepts": []}
)


@pytest.fixture
async def clean_templates():
    """Start from the built-in template; afterwards remove new rows and put
    back whichever version was active."""
    before = await existing_ids(QueryTemplate)
    async with async_session() as session:
        was = await query_template_service.get_active(session)
        await query_template_service.reset_to_default(session)
    yield
    await delete_rows_added_since(QueryTemplate, before)
    async with async_session() as session:
        await query_template_service.reset_to_default(session)
        if not was.is_default:
            await query_template_service.activate(session, was.version)


@pytest.fixture
async def clean_defaults():
    """Put back whatever defaults existed, so the suite never changes them."""
    async with async_session() as session:
        row = await session.get(YutoriDefaults, 1)
        saved = dict(row.settings) if row else None
        await yutori_defaults_service.reset(session)
    yield
    async with async_session() as session:
        await yutori_defaults_service.reset(session)
        if saved is not None:
            session.add(YutoriDefaults(id=1, settings=saved))
            await session.commit()


# --- validation ---


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("", "can't be empty"),
        ("Find {topics} about {favourite_language}", "Unknown placeholder {favourite_language}"),
        ("Find questions about Rust", "must include {topics}"),
        ("Find {topics} and {", "brace isn't matched"),
        ("Find {topics} and {}", "Unknown placeholder {}"),
        ("{topics}" + "x" * 5000, "too long"),
    ],
)
def test_a_template_that_cannot_be_filled_is_refused(body, message):
    with pytest.raises(QueryTemplateError, match=message.replace("{", r"\{").replace("}", r"\}")):
        query_template_service.validate(body)


def test_literal_braces_are_allowed_when_doubled():
    assert query_template_service.validate("Return {{json}} for {topics}")


# --- versions ---


@pytest.mark.anyio
async def test_with_nothing_stored_the_built_in_template_applies(clean_templates):
    async with async_session() as session:
        active = await query_template_service.get_active(session)
    assert active.is_default is True
    assert active.body == query_generator.DEFAULT_TEMPLATE


@pytest.mark.anyio
async def test_saving_creates_a_new_active_version(clean_templates):
    async with async_session() as session:
        first = await query_template_service.save_version(session, body="First {topics}")
        second = await query_template_service.save_version(session, body="Second {topics}")
        assert second.version > first.version > query_template_service.BUILT_IN_VERSION
        versions = await query_template_service.list_versions(session)
        assert [v.is_active for v in versions].count(True) == 1
        assert (await query_template_service.get_active(session)).body == "Second {topics}"


@pytest.mark.anyio
async def test_activating_rolls_back_and_reset_returns_to_built_in(clean_templates):
    async with async_session() as session:
        first = await query_template_service.save_version(session, body="First {topics}")
        await query_template_service.save_version(session, body="Second {topics}")
        await query_template_service.activate(session, first.version)
        assert (await query_template_service.get_active(session)).body == "First {topics}"
        await query_template_service.reset_to_default(session)
        assert (await query_template_service.get_active(session)).is_default is True


@pytest.mark.anyio
async def test_a_topics_scout_renders_with_the_active_template(clean_templates):
    async with async_session() as session:
        await query_template_service.save_version(session, body="Watch for:\n{topics}")
        template = await definition_service.active_template(session)
    definition = type("D", (), {"query_source": "topics", "query_text": None})()
    assert definition_service.render_query(definition, PROFILE, template) == (
        "Watch for:\n- rust (weight 80/100)"
    )


@pytest.mark.anyio
async def test_the_template_routes_round_trip(client, auth_cookies, clean_templates):
    bad = client.post("/yutori/query-templates", json={"body": "no placeholder"}, cookies=auth_cookies)
    assert bad.status_code == 422
    assert "must include {topics}" in bad.json()["detail"]

    saved = client.post(
        "/yutori/query-templates", json={"body": "Rust please: {topics}"}, cookies=auth_cookies
    )
    assert saved.status_code == 201

    current = client.get("/yutori/query-template", cookies=auth_cookies).json()
    assert current["template"]["body"] == "Rust please: {topics}"
    assert current["template"]["is_default"] is False
    assert "topics" in current["placeholders"]

    preview = client.post(
        "/yutori/query-template/preview", json={"body": "Draft: {topics}"}, cookies=auth_cookies
    ).json()
    assert preview["rendered"].startswith("Draft: ")
    # The preview stored nothing.
    assert client.get("/yutori/query-template", cookies=auth_cookies).json()["template"]["body"] == (
        "Rust please: {topics}"
    )

    reset = client.post("/yutori/query-templates/reset", cookies=auth_cookies).json()
    assert reset["is_default"] is True


# --- defaults ---


@pytest.mark.anyio
async def test_stored_defaults_are_inherited_by_scouts(clean_defaults):
    async with async_session() as session:
        await yutori_defaults_service.put(
            session, YutoriSettings.model_validate({"user_timezone": "America/Toronto"})
        )
        inherited = await yutori_defaults_service.effective(session)
    assert inherited["user_timezone"] == "America/Toronto"
    # Everything not changed keeps its built-in value.
    assert inherited["is_public"] is False


@pytest.mark.anyio
async def test_the_defaults_routes_round_trip(client, auth_cookies, clean_defaults):
    bad = client.put("/yutori/defaults", json={"user_timezone": "Nowhere/Land"}, cookies=auth_cookies)
    assert bad.status_code == 422
    assert "isn't a timezone name" in bad.json()["detail"]

    saved = client.put(
        "/yutori/defaults", json={"output_interval_seconds": 604800}, cookies=auth_cookies
    ).json()
    assert saved["stored"] == {"output_interval_seconds": 604800}
    assert saved["effective"]["output_interval_seconds"] == 604800

    reset = client.delete("/yutori/defaults", cookies=auth_cookies).json()
    assert reset["stored"] == {}
