import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.question import Question
from app.schemas.profile import ProfileData
from app.services import enrichment_service, rank_stage
from app.services.profile_service import get_or_create_profile

router = APIRouter(tags=["questions"])


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

    @classmethod
    def from_model(cls, question: Question) -> "QuestionOut":
        return cls(
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
    return [QuestionOut.from_model(question) for question in questions]


@router.get("/questions/{question_id}", response_model=QuestionOut)
async def get_question(question_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> QuestionOut:
    question = await db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    return QuestionOut.from_model(question)


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
