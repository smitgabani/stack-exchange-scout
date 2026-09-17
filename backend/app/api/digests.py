import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_gemini_key
from app.core.config import settings
from app.core.db import get_db
from app.models.challenge import Challenge
from app.models.digest import Digest
from app.schemas.profile import ProfileData
from app.services import digest_service, email_service
from app.services.profile_service import get_or_create_profile

router = APIRouter(tags=["digests"])


class ChallengeOut(BaseModel):
    id: uuid.UUID
    question_id: uuid.UUID
    question_title: str | None = None
    question_url: str | None = None
    question_tags: list[str] = []
    answer_count: int | None = None
    has_accepted_answer: bool = False
    question_created_at: datetime | None = None
    problem_summary: str
    why_interesting: str
    concepts: list
    starting_direction: str
    hints: list
    estimated_difficulty: int | None


class DigestOut(BaseModel):
    id: uuid.UUID
    status: str
    question_count: int
    generated_at: datetime
    sent_at: datetime | None
    challenges: list[ChallengeOut] = []


def _challenge_out(challenge: Challenge, question=None) -> ChallengeOut:
    return ChallengeOut(
        id=challenge.id,
        question_id=challenge.question_id,
        question_title=question.title if question else None,
        question_url=question.url if question else None,
        question_tags=(question.tags or []) if question else [],
        answer_count=question.answer_count if question else None,
        has_accepted_answer=bool(question and question.accepted_answer_id is not None),
        question_created_at=question.question_created_at if question else None,
        problem_summary=challenge.problem_summary,
        why_interesting=challenge.why_interesting,
        concepts=challenge.concepts or [],
        starting_direction=challenge.starting_direction,
        hints=challenge.hints or [],
        estimated_difficulty=challenge.estimated_difficulty,
    )


@router.get("/digests", response_model=list[DigestOut])
async def list_digests(db: AsyncSession = Depends(get_db), limit: int = 20) -> list[DigestOut]:
    digests = (
        await db.scalars(select(Digest).order_by(Digest.generated_at.desc()).limit(limit))
    ).all()
    return [
        DigestOut(
            id=d.id,
            status=d.status,
            question_count=d.question_count,
            generated_at=d.generated_at,
            sent_at=d.sent_at,
        )
        for d in digests
    ]


@router.get("/digests/{digest_id}", response_model=DigestOut)
async def get_digest(digest_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> DigestOut:
    digest = await db.get(Digest, digest_id)
    if digest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Digest not found")

    pairs = await digest_service.load_digest_questions(db, digest.id)
    return DigestOut(
        id=digest.id,
        status=digest.status,
        question_count=digest.question_count,
        generated_at=digest.generated_at,
        sent_at=digest.sent_at,
        challenges=[_challenge_out(challenge, question) for question, challenge in pairs],
    )


@router.get("/challenges/{challenge_id}", response_model=ChallengeOut)
async def get_challenge(challenge_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ChallengeOut:
    challenge = await db.get(Challenge, challenge_id)
    if challenge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")

    from app.models.question import Question

    question = await db.get(Question, challenge.question_id)
    return _challenge_out(challenge, question)


@router.post("/digest/generate", response_model=DigestOut, dependencies=[Depends(require_gemini_key)])
async def generate_digest(db: AsyncSession = Depends(get_db)) -> DigestOut:
    """Select the top candidates and curate them into challenges.

    Synchronous for now — M7-TEST budgets 30s for five questions, and the
    stage boundary is where M11's worker will slot in.
    """
    profile = await get_or_create_profile(db)
    profile_data = ProfileData.model_validate(profile.data)

    try:
        digest = await digest_service.generate(db, profile_data, profile.version)
    except digest_service.DigestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    pairs = await digest_service.load_digest_questions(db, digest.id)
    return DigestOut(
        id=digest.id,
        status=digest.status,
        question_count=digest.question_count,
        generated_at=digest.generated_at,
        sent_at=digest.sent_at,
        challenges=[_challenge_out(challenge, question) for question, challenge in pairs],
    )


@router.post("/digest/send")
async def send_digest(digest_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)) -> dict:
    """Email a generated digest and mark exactly its questions as presented."""
    if digest_id is not None:
        digest = await db.get(Digest, digest_id)
    else:
        digest = await db.scalar(
            select(Digest)
            .where(Digest.status.in_(("generated", "empty")))
            .order_by(Digest.generated_at.desc())
            .limit(1)
        )

    if digest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No digest ready to send")
    if digest.status == "sent":
        return {"status": "already_sent", "digest_id": str(digest.id)}

    profile = await get_or_create_profile(db)
    profile_data = ProfileData.model_validate(profile.data)

    if digest.status == "empty":
        subject, body = email_service.render_empty_digest(profile_data.digest.frequency_days)
    else:
        pairs = await digest_service.load_digest_questions(db, digest.id)
        subject, body = email_service.render_digest(pairs, app_base_url=settings.app_base_url)

    digest.email_attempts += 1
    try:
        message_id = await email_service.send_email(subject=subject, html_body=body)
    except email_service.EmailError as exc:
        digest.status = "send_failed"
        digest.email_error = str(exc)[:500]
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await digest_service.mark_sent(db, digest)
    return {"status": "sent", "digest_id": str(digest.id), "message_id": message_id}
