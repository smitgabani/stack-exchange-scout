from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question
from app.schemas.profile import ProfileData
from app.services import ranking_service
from app.services.ingest_service import StageResult

# How many recently-presented questions feed the novelty penalty.
RECENT_HISTORY_SIZE = 20


async def recent_tag_history(db: AsyncSession, *, limit: int = RECENT_HISTORY_SIZE) -> Counter[str]:
    """Tags from the questions most recently shown to the user.

    Fetched once per stage run and passed into the pure scorer, so scoring
    itself stays free of database access.
    """
    rows = (
        await db.scalars(
            select(Question)
            .where(Question.status.in_(("presented", "solved", "skipped")))
            .order_by(Question.last_seen_at.desc())
            .limit(limit)
        )
    ).all()

    counter: Counter[str] = Counter()
    for row in rows:
        counter.update(tag.lower() for tag in (row.tags or []))
    return counter


async def run(
    db: AsyncSession,
    profile_data: ProfileData,
    profile_version: int,
    *,
    limit: int = 500,
    now: datetime | None = None,
    force: bool = False,
) -> StageResult:
    """Score candidates against the current profile.

    Only rescores rows whose `profile_version` is stale, so a repeated run is
    cheap; `force` rescores regardless. Updates rows in place — re-ranking must
    never duplicate a question (M6-TEST).
    """
    now = now or datetime.now(UTC)
    result = StageResult()

    statement = select(Question).where(Question.status == "candidate")
    if not force:
        statement = statement.where(
            or_(Question.profile_version.is_(None), Question.profile_version != profile_version)
        )

    candidates = (await db.scalars(statement.limit(limit))).all()
    if not candidates:
        return result

    result.processed = len(candidates)
    history = await recent_tag_history(db)

    for question in candidates:
        scores = ranking_service.score(question, profile_data, recent_tags=history, now=now)
        question.topic_relevance = scores.topic_relevance
        question.technical_depth = scores.technical_depth
        question.solve_opportunity = scores.solve_opportunity
        question.recency_score = scores.recency
        question.quality_score = scores.quality
        question.novelty_score = scores.novelty
        question.candidate_score = scores.total
        question.profile_version = profile_version
        question.scored_at = now
        result.succeeded += 1

    await db.commit()
    return result
