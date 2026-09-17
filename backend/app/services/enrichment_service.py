import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.stackexchange import (
    StackExchangeBadRequest,
    StackExchangeClient,
    StackExchangeError,
    is_plausible_question_id,
)
from app.models.question import Question
from app.schemas.profile import ProfileData
from app.services import filter_service
from app.services.ingest_service import StageResult

logger = logging.getLogger(__name__)

# Exponential-ish backoff between enrichment attempts, capped so a question
# never stops being retried entirely — the API being down is temporary.
_RETRY_BACKOFF_MINUTES = (5, 30, 120, 360)
MAX_BATCH = 100


def _next_retry_delay(attempts: int) -> timedelta:
    index = min(attempts, len(_RETRY_BACKOFF_MINUTES) - 1)
    return timedelta(minutes=_RETRY_BACKOFF_MINUTES[index])


async def run(
    db: AsyncSession,
    profile_data: ProfileData,
    *,
    limit: int = MAX_BATCH,
    now: datetime | None = None,
    client: StackExchangeClient | None = None,
) -> StageResult:
    """Enrich pending questions with authoritative Stack Exchange metadata,
    then apply the §14 reject filters.

    The central rule (tdd.md §8.4): a Stack Exchange outage must never reject a
    candidate. Transport failures leave the row in `enrichment_pending` with a
    later `next_retry_at`; only a question the API affirmatively doesn't know
    about is rejected.
    """
    now = now or datetime.now(UTC)
    client = client or StackExchangeClient()
    result = StageResult()

    pending = (
        await db.scalars(
            select(Question)
            .where(
                Question.status == "enrichment_pending",
                Question.stackoverflow_question_id.is_not(None),
                or_(Question.next_retry_at.is_(None), Question.next_retry_at <= now),
            )
            .order_by(Question.first_seen_at)
            .limit(limit)
        )
    ).all()

    if not pending:
        return result

    result.processed = len(pending)
    by_id: dict[int, Question] = {}

    for question in pending:
        question_id = question.stackoverflow_question_id
        if not is_plausible_question_id(question_id):
            # Sending this would 400 the whole batch, so it never reaches the
            # API. A nonsense id is a parse failure, not a transient one.
            question.status = "rejected"
            question.rejection_reason = "invalid_question_id"
            question.fetched_at = now
            result.skipped += 1
            continue
        by_id[question_id] = question

    if not by_id:
        await db.commit()
        return result

    try:
        found = await client.fetch_questions(list(by_id.keys()))
    except StackExchangeBadRequest as exc:
        # Permanent: retrying an identical malformed request is pointless, so
        # surface it loudly rather than parking the batch in a retry loop.
        logger.error("Stack Exchange rejected the enrichment batch outright: %s", exc)
        for question in by_id.values():
            question.enrichment_attempts += 1
            question.enrichment_error = str(exc)[:500]
        await db.commit()
        result.failed = len(by_id)
        result.errors.append(str(exc))
        return result
    except StackExchangeError as exc:
        # Whole batch stays pending — this is the graceful-degradation path.
        logger.warning("Stack Exchange enrichment failed for %d questions: %s", len(by_id), exc)
        for question in by_id.values():
            question.enrichment_attempts += 1
            question.enrichment_error = str(exc)[:500]
            question.next_retry_at = now + _next_retry_delay(question.enrichment_attempts)
        await db.commit()
        result.failed = len(by_id)
        result.errors.append(str(exc))
        return result

    for question_id, question in by_id.items():
        metadata = found.get(question_id)

        if metadata is None:
            # The API answered and simply doesn't have it: deleted or never
            # existed. This is the one genuinely permanent failure.
            question.status = "rejected"
            question.rejection_reason = "not_found_on_stack_overflow"
            question.fetched_at = now
            result.skipped += 1
            continue

        question.title = metadata.title
        question.body = metadata.body
        question.tags = metadata.tags
        question.score = metadata.score
        question.answer_count = metadata.answer_count
        question.accepted_answer_id = metadata.accepted_answer_id
        question.is_closed = metadata.is_closed
        question.question_created_at = metadata.question_created_at
        question.last_activity_at = metadata.last_activity_at
        question.url = metadata.link or question.url
        question.fetched_at = now
        question.enrichment_error = None
        question.next_retry_at = None

        rejection = filter_service.evaluate(question, profile_data)
        if rejection is not None:
            question.status = "rejected"
            question.rejection_reason = rejection.reason
        else:
            question.status = "candidate"
            question.rejection_reason = None
        result.succeeded += 1

    await db.commit()
    return result
