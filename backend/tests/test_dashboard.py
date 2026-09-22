"""The dashboard: one request, and a streak that is honest.

The streak is the part worth testing hardest. It is the number on the page
most likely to make someone feel bad, so it must never report a broken streak
that is not broken — in particular, not every Monday morning, when the new
week has simply not had a solve yet.
"""

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from app.api.dashboard import _streak, _week_start

MONDAY = date(2026, 9, 21)  # a Monday


def _weeks(*offsets: int) -> set[date]:
    """Week starts `offsets` weeks before MONDAY (0 = this week)."""
    return {MONDAY - timedelta(weeks=n) for n in offsets}


# --- 🔒 the streak never lies about being broken ---


def test_no_solves_is_no_streak() -> None:
    assert _streak(set(), MONDAY) == 0


def test_a_solve_this_week_starts_a_streak() -> None:
    assert _streak(_weeks(0), MONDAY) == 1


def test_an_unfinished_week_does_not_break_the_streak() -> None:
    """The case that matters most.

    Solved every week until last week, nothing yet this week. It is Monday —
    the week has barely started. Reporting a streak of 0 here would tell the
    user they failed when they have not had the chance to try.
    """
    assert _streak(_weeks(1, 2, 3), MONDAY) == 3


def test_consecutive_weeks_accumulate() -> None:
    assert _streak(_weeks(0, 1, 2, 3), MONDAY) == 4


def test_a_skipped_week_ends_the_streak() -> None:
    """Two weeks ago with nothing last week: genuinely broken."""
    assert _streak(_weeks(2, 3, 4), MONDAY) == 0


def test_only_the_run_ending_now_counts() -> None:
    """An older, longer run does not count — only the current one."""
    assert _streak(_weeks(0, 1, 5, 6, 7, 8), MONDAY) == 2


# --- 🔒 weeks are weeks, whatever the day ---


def test_every_day_of_a_week_maps_to_its_monday() -> None:
    """A streak counted in weeks must not split a week across two buckets."""
    for day in range(7):
        moment = datetime(2026, 9, 21 + day, 15, 30, tzinfo=UTC)
        assert _week_start(moment) == MONDAY, moment


def test_sunday_night_belongs_to_the_week_it_ends() -> None:
    assert _week_start(datetime(2026, 9, 27, 23, 59, tzinfo=UTC)) == MONDAY
    assert _week_start(datetime(2026, 9, 28, 0, 0, tzinfo=UTC)) == MONDAY + timedelta(weeks=1)


# --- 🧩 one request carries the whole page ---


def test_the_dashboard_returns_everything_in_one_response(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    """Six fetches would each be a billed Vercel function, and the page could
    not render until the slowest returned.
    """
    body = client.get("/dashboard", cookies=auth_cookies).json()

    for key in ("next_challenge", "up_next", "momentum", "pipeline", "topics", "digest"):
        assert key in body, key
    for key in ("solved_total", "solved_this_week", "week_streak", "by_week"):
        assert key in body["momentum"], key
    for key in ("awaiting_enrichment", "candidates", "above_bar", "challenges", "solved", "bar"):
        assert key in body["pipeline"], key


def test_the_weekly_history_always_has_twelve_bars(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    """The bar chart is laid out from this, so a quiet stretch must still
    produce empty weeks rather than a shorter, misleading chart.
    """
    body = client.get("/dashboard", cookies=auth_cookies).json()
    assert len(body["momentum"]["by_week"]) == 12


def test_up_next_never_repeats_the_lead_challenge(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    body = client.get("/dashboard", cookies=auth_cookies).json()
    lead = body["next_challenge"]
    if lead:
        assert lead["id"] not in {c["id"] for c in body["up_next"]}


def test_the_dashboard_requires_a_session(client: TestClient) -> None:
    assert client.get("/dashboard").status_code == 401


# --- 🔒 the response carries real types, not what the fixtures assumed ---


def test_a_run_cost_is_serialised_as_a_number(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    """The bug that broke the live page.

    `scout_runs.cost_usd` is Numeric, so it comes back as Decimal whatever its
    annotation says, and FastAPI serialises Decimal as the string "0.35". The
    frontend called .toFixed() on it and the whole dashboard failed to render.
    Stubbed tests used the number 0.35 and could never have seen it.
    """
    import asyncio
    from decimal import Decimal

    from sqlalchemy import delete

    from app.core.db import async_session
    from app.models.scout_definition import ScoutRun

    async def plant() -> object:
        async with async_session() as session:
            run = ScoutRun(
                kind="research_task",
                status="succeeded",
                cost_usd=Decimal("0.3500"),
                questions_found=12,
            )
            session.add(run)
            await session.commit()
            return run.id

    async def remove(run_id) -> None:
        async with async_session() as session:
            await session.execute(delete(ScoutRun).where(ScoutRun.id == run_id))
            await session.commit()

    run_id = asyncio.run(plant())
    try:
        body = client.get("/dashboard", cookies=auth_cookies).json()
        cost = body["last_run"]["cost_usd"]
        assert isinstance(cost, int | float), f"cost_usd came back as {type(cost).__name__}: {cost!r}"
        assert cost == 0.35
    finally:
        asyncio.run(remove(run_id))


def test_card_titles_are_decoded_from_stack_exchange_html() -> None:
    """Stack Exchange stores titles HTML-encoded; the hero showed them raw."""
    import uuid

    from app.api.dashboard import _card
    from app.models.challenge import Challenge
    from app.models.question import Question

    question = Question(title="Can&#39;t read the &quot;Set-Cookie&quot; header", tags=["axios"])
    challenge = Challenge(id=uuid.uuid4(), estimated_difficulty=3)

    assert _card(challenge, question)["question_title"] == "Can't read the \"Set-Cookie\" header"
