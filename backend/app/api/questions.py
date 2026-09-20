import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.challenge import Challenge
from app.models.question import Question
from app.schemas.profile import ProfileData
from app.services import digest_service, enrichment_service, rank_stage
from app.services.profile_service import get_or_create_profile

router = APIRouter(tags=["questions"])

# What `rejection_reason` is set to when the user dismissed a question by hand,
# as opposed to the enrichment filters rejecting it (M5-B5).
USER_DISMISSED = "user_dismissed"


class QuestionOut(BaseModel):
    id: uuid.UUID
    stackoverflow_question_id: int | None
    url: str
    title: str | None
    tags: list[str]
    score: int | None
    answer_count: int | None
    has_accepted_answer: bool
    is_closed: bool
    difficulty: int | None
    problem_summary: str | None
    candidate_score: float | None
    status: str
    question_created_at: datetime | None
    last_activity_at: datetime | None
    rejection_reason: str | None
    # Whether a challenge already exists for this question, so the UI can show
    # a link to it instead of offering to spend another LLM call making one.
    challenge_id: uuid.UUID | None = None

    @classmethod
    def from_model(cls, question: Question, challenge_id: uuid.UUID | None = None) -> "QuestionOut":
        return cls(
            challenge_id=challenge_id,
            id=question.id,
            stackoverflow_question_id=question.stackoverflow_question_id,
            url=question.url,
            title=question.title,
            tags=question.tags or [],
            score=question.score,
            answer_count=question.answer_count,
            has_accepted_answer=question.accepted_answer_id is not None,
            is_closed=question.is_closed,
            difficulty=question.difficulty,
            problem_summary=question.problem_summary,
            candidate_score=float(question.candidate_score) if question.candidate_score is not None else None,
            status=question.status,
            question_created_at=question.question_created_at,
            last_activity_at=question.last_activity_at,
            rejection_reason=question.rejection_reason,
        )


# The question body is deliberately absent from this response. It is untrusted
# Stack Overflow HTML (tdd.md §9.6) and nothing in the UI renders it yet;
# shipping it would create an XSS surface for no current benefit.


@router.get("/questions", response_model=list[QuestionOut])
async def list_questions(
    db: AsyncSession = Depends(get_db),
    status_filter: str = Query("candidate", alias="status"),
    rejection_reason: str | None = None,
    topic: str | None = None,
    difficulty_min: int | None = Query(None, ge=1, le=5),
    difficulty_max: int | None = Query(None, ge=1, le=5),
    min_score: int | None = None,
    max_answers: int | None = None,
    has_accepted_answer: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[QuestionOut]:
    statement = select(Question)

    if status_filter != "all":
        statement = statement.where(Question.status == status_filter)
    # Separates the questions the user dismissed from the ones the enrichment
    # filters rejected — both are `rejected`, but only one was a decision.
    if rejection_reason == USER_DISMISSED:
        statement = statement.where(Question.rejection_reason == USER_DISMISSED)
    elif rejection_reason == "automatic":
        statement = statement.where(
            Question.rejection_reason.is_not(None), Question.rejection_reason != USER_DISMISSED
        )
    if topic:
        statement = statement.where(Question.tags.any(topic.lower()))
    if difficulty_min is not None:
        statement = statement.where(Question.difficulty >= difficulty_min)
    if difficulty_max is not None:
        statement = statement.where(Question.difficulty <= difficulty_max)
    if min_score is not None:
        statement = statement.where(Question.score >= min_score)
    if max_answers is not None:
        statement = statement.where(Question.answer_count <= max_answers)
    if has_accepted_answer is True:
        statement = statement.where(Question.accepted_answer_id.is_not(None))
    if has_accepted_answer is False:
        statement = statement.where(Question.accepted_answer_id.is_(None))

    # Best candidates first; the partial index on (status, candidate_score)
    # covers exactly this.
    statement = statement.order_by(
        Question.candidate_score.desc().nullslast(), Question.first_seen_at.desc()
    ).limit(limit).offset(offset)

    questions = (await db.scalars(statement)).all()

    # One query for the whole page rather than one per row.
    challenge_ids = await _challenge_ids_for(db, [question.id for question in questions])
    return [
        QuestionOut.from_model(question, challenge_ids.get(question.id)) for question in questions
    ]


async def _challenge_ids_for(db: AsyncSession, question_ids: list[uuid.UUID]) -> dict:
    if not question_ids:
        return {}
    rows = (
        await db.execute(
            select(Challenge.question_id, Challenge.id).where(
                Challenge.question_id.in_(question_ids)
            )
        )
    ).all()
    return {question_id: challenge_id for question_id, challenge_id in rows}


@router.get("/questions/{question_id}", response_model=QuestionOut)
async def get_question(question_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> QuestionOut:
    question = await db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    challenge_ids = await _challenge_ids_for(db, [question.id])
    return QuestionOut.from_model(question, challenge_ids.get(question.id))


@router.post("/questions/{question_id}/dismiss", response_model=QuestionOut)
async def dismiss_question(question_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> QuestionOut:
    """Take a question out of the pool without deleting it.

    Deliberately not a DELETE. Ingest dedupes on `canonical_url`, so a deleted
    row is simply an unknown URL the next time a run sees it — the question
    would come back, possibly having been paid for twice. Keeping the row is
    what makes the dismissal stick.
    """
    question = await db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")

    question.status = "rejected"
    question.rejection_reason = USER_DISMISSED
    await db.commit()
    await db.refresh(question)
    challenge_ids = await _challenge_ids_for(db, [question.id])
    return QuestionOut.from_model(question, challenge_ids.get(question.id))


@router.post("/questions/{question_id}/restore", response_model=QuestionOut)
async def restore_question(question_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> QuestionOut:
    """Undo a dismissal, putting the question back in the candidate pool.

    Only undoes the user's own dismissal — a question the enrichment filters
    rejected is left alone, since restoring it would just be re-rejected by the
    same rule on the next run.
    """
    question = await db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    if question.rejection_reason != USER_DISMISSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This question was not dismissed by hand, so there is nothing to restore.",
        )

    question.status = "candidate"
    question.rejection_reason = None
    await db.commit()
    await db.refresh(question)
    challenge_ids = await _challenge_ids_for(db, [question.id])
    return QuestionOut.from_model(question, challenge_ids.get(question.id))


@router.post("/questions/{question_id}/challenge", status_code=status.HTTP_201_CREATED)
async def promote_question(question_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Turn a question into a challenge regardless of what it scored.

    The scoring formula decides what a digest contains; this is the escape
    hatch for when the formula and the user disagree. Costs one LLM call and no
    Yutori credit.

    No `require_gemini_key` guard, unlike `/digest/generate`: the profile may
    select OpenAI, and that dependency would refuse a perfectly usable OpenAI
    setup for want of a Gemini key. `resolve_provider` checks the key belonging
    to the provider actually chosen, and its failure is surfaced as the 403
    below.
    """
    question = await db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")

    profile = await get_or_create_profile(db)
    profile_data = ProfileData.model_validate(profile.data)

    try:
        challenge = await digest_service.promote_question(db, profile_data, question)
    except digest_service.PromotionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except digest_service.DigestError as exc:
        # resolve_provider only raises for a missing/unusable key.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return {"challenge_id": str(challenge.id), "question_id": str(question.id)}


@router.post("/candidates/enrich")
async def enrich_candidates(db: AsyncSession = Depends(get_db)) -> dict:
    """Run the enrichment stage over everything currently pending.

    A separate trigger rather than a step inside ingest, so it is re-runnable
    and so a Stack Exchange outage is recoverable by simply running it again.
    M11 will call this on a schedule.
    """
    profile = await get_or_create_profile(db)
    result = await enrichment_service.run(db, ProfileData.model_validate(profile.data))
    return result.as_dict()


@router.post("/candidates/rank")
async def rank_candidates(force: bool = False, db: AsyncSession = Depends(get_db)) -> dict:
    """Score candidates against the current profile (prd.md §25 `candidate_rank`).

    Skips rows already scored under this profile version unless `force`, and
    updates in place so re-ranking never duplicates a question.
    """
    profile = await get_or_create_profile(db)
    result = await rank_stage.run(
        db, ProfileData.model_validate(profile.data), profile.version, force=force
    )
    return result.as_dict()
