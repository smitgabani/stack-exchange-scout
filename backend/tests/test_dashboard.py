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
