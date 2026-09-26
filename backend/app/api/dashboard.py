"""Everything the dashboard shows, in one request.

Assembled server-side rather than fetched as six queries from the browser.
Each of those would be a Vercel function proxying to Fly, and the page cannot
render until the slowest returns — the same argument that collapsed the three
startup calls into `/auth/bootstrap`.

What it returns is chosen by what the page is for: getting you into a
challenge. The counts and the streak are there to make progress visible, the
funnel to make the machinery legible, and everything else is secondary.
"""

import html
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models.challenge import Challenge
from app.models.digest import Digest
from app.models.question import Question
from app.models.scout_definition import ScoutRun
from app.services.profile_service import get_profile_data

router = APIRouter(tags=["dashboard"])

# How many challenges the page offers beyond the one it leads with.
UP_NEXT = 3
# Weeks of history behind the streak and the bar chart.
HISTORY_WEEKS = 12


def _week_start(when: datetime) -> date:
    """The Monday of that week, so a streak counts weeks rather than days.

    Daily would be the wrong unit: digests arrive every few days by default,
    so a day-based streak would break constantly through no fault of the
    user's and would punish them for the schedule they chose.
    """
    day = when.astimezone(UTC).date()
    return day - timedelta(days=day.weekday())


def _streak(weeks_with_a_solve: set[date], this_week: date) -> int:
    """Consecutive weeks ending now, counting back.

    The current week not having a solve *yet* does not break the streak —
    it has not finished. Anything else would show a broken streak every
    Monday morning.
    """
    streak = 0
    cursor = this_week
    if cursor not in weeks_with_a_solve:
        cursor -= timedelta(weeks=1)
    while cursor in weeks_with_a_solve:
        streak += 1
        cursor -= timedelta(weeks=1)
    return streak


def _card(challenge: Challenge, question: Question) -> dict:
    return {
        "id": str(challenge.id),
        # Stack Exchange returns titles HTML-encoded, and they are stored that
        # way — "Can&#39;t read the header". Decoded here because this is the
        # largest text on the page. React escapes whatever it renders, so the
        # decoded string is still displayed safely as text.
        "question_title": html.unescape(question.title) if question.title else None,
        "question_tags": (question.tags or [])[:4],
        "estimated_difficulty": challenge.estimated_difficulty,
        "created_at": challenge.created_at.isoformat() if challenge.created_at else None,
    }


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db)) -> dict:
    profile_data = await get_profile_data(db)

    # --- what there is to solve ---------------------------------------
    unsolved = (
        await db.execute(
            select(Challenge, Question)
            .join(Question, Question.id == Challenge.question_id)
            .where(Question.status != "solved")
            .order_by(Challenge.created_at.desc())
            .limit(UP_NEXT + 1)
        )
    ).all()
    cards = [_card(challenge, question) for challenge, question in unsolved]

    # --- momentum ------------------------------------------------------
    solved_rows = list(
        await db.scalars(
            select(Question.solved_at).where(
                Question.status == "solved", Question.solved_at.is_not(None)
            )
        )
    )
    solved_total = len(solved_rows)
    this_week = _week_start(datetime.now(UTC))
    weeks = {_week_start(s) for s in solved_rows}

    by_week: dict[str, int] = {}
    for offset in range(HISTORY_WEEKS - 1, -1, -1):
        start = this_week - timedelta(weeks=offset)
        by_week[start.isoformat()] = 0
    for solved in solved_rows:
        key = _week_start(solved).isoformat()
        if key in by_week:
            by_week[key] += 1

    # --- the funnel, so the machine is legible --------------------------
    async def count(*where) -> int:
        return await db.scalar(select(func.count()).select_from(Question).where(*where)) or 0

    awaiting = await count(Question.status == "enrichment_pending")
    candidates = await count(Question.status == "candidate")
    above_bar = await count(
        Question.status == "candidate",
        Question.candidate_score >= settings.digest_min_score,
    )
    challenges_made = (
        await db.scalar(select(func.count()).select_from(Challenge))
    ) or 0

    # --- context, cheap to add while we are here ------------------------
    latest_digest = await db.scalar(
        select(Digest).order_by(Digest.generated_at.desc()).limit(1)
    )
    last_run = await db.scalar(
        select(ScoutRun).where(ScoutRun.status == "succeeded")
        .order_by(ScoutRun.started_at.desc())
        .limit(1)
    )

    return {
        # The page leads with this one and offers the rest.
        "next_challenge": cards[0] if cards else None,
        "up_next": cards[1 : UP_NEXT + 1],
        "momentum": {
            "solved_total": solved_total,
            "solved_this_week": sum(1 for s in solved_rows if _week_start(s) == this_week),
            "week_streak": _streak(weeks, this_week),
            "by_week": [{"week": k, "count": v} for k, v in by_week.items()],
        },
        "pipeline": {
            "awaiting_enrichment": awaiting,
            "candidates": candidates,
            "above_bar": above_bar,
            "challenges": challenges_made,
            "solved": solved_total,
            # Surfaced so the funnel can say what "above the bar" means
            # rather than leaving it as a number with no scale.
            "bar": settings.digest_min_score,
        },
        "topics": [
            {"name": t.name, "weight": t.weight} for t in profile_data.topics
        ],
        "digest": {
            "frequency_days": profile_data.digest.frequency_days,
            "latest": (
                {
                    "id": str(latest_digest.id),
                    "status": latest_digest.status,
                    "question_count": latest_digest.question_count,
                    "generated_at": latest_digest.generated_at.isoformat()
                    if latest_digest.generated_at
                    else None,
                    "sent_at": latest_digest.sent_at.isoformat()
                    if latest_digest.sent_at
                    else None,
                }
                if latest_digest
                else None
            ),
        },
        "last_run": (
            {
                "at": last_run.started_at.isoformat() if last_run.started_at else None,
                # A Numeric column comes back as Decimal whatever the Mapped
                # annotation claims, and FastAPI serialises Decimal as a
                # string. The page called .toFixed() on "0.35" and the whole
                # dashboard failed to render.
                "cost_usd": float(last_run.cost_usd) if last_run.cost_usd is not None else None,
                "questions_found": last_run.questions_found,
            }
            if last_run
            else None
        ),
    }
