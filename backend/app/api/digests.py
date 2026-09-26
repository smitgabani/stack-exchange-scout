import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models.challenge import Challenge
from app.models.digest import Digest
from app.models.question import Question
from app.services import block_service, digest_service, email_service
from app.services.profile_service import get_profile_data

router = APIRouter(tags=["digests"])


class ChallengeOut(BaseModel):
    id: uuid.UUID
    question_id: uuid.UUID
    digest_id: uuid.UUID | None = None
    source: str = "digest"
    created_at: datetime | None = None
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
    # What the format produced. Null on challenges made before formats
    # existed, which is why the frontend falls back to the fields above.
    content: dict | None = None
    format_name: str | None = None
    blocks: list[str] = []
    # How to draw each of those blocks: {key, label, kind, gated}, in the same
    # order. Added alongside `blocks` rather than replacing it — Vercel and Fly
    # deploy separately, so a frontend still expecting a list of strings has to
    # keep working while the two are out of step.
    block_meta: list[dict] = []
    # Threaded from the joined question so list/detail views can tell a
    # completed challenge apart without a second query.
    question_status: str | None = None
    solved_at: datetime | None = None


class ChallengeSummaryOut(BaseModel):
    """A challenge as a list renders it — which is not very much of one.

    The full `ChallengeOut` carries `content`, averaging 2.7KB, plus the five
    core fields duplicated out of it. At `limit=200` that is over half a
    megabyte of generated prose that neither the challenges list nor the
    dashboard ever displays: both show a title, tags, a difficulty and a date.

    Every byte of it crossed a Vercel function, which is billed by the second.
    """

    id: uuid.UUID
    question_id: uuid.UUID
    digest_id: uuid.UUID | None = None
    source: str = "digest"
    created_at: datetime | None = None
    question_title: str | None = None
    question_tags: list[str] = []
    estimated_difficulty: int | None = None
    question_status: str | None = None
    solved_at: datetime | None = None


def _challenge_summary(challenge: Challenge, question=None) -> ChallengeSummaryOut:
    return ChallengeSummaryOut(
        id=challenge.id,
        question_id=challenge.question_id,
        digest_id=challenge.digest_id,
        source=challenge.source,
        created_at=challenge.created_at,
        question_title=question.title if question else None,
        question_tags=(question.tags or []) if question else [],
        estimated_difficulty=challenge.estimated_difficulty,
        question_status=question.status if question else None,
        solved_at=question.solved_at if question else None,
    )


def _challenge_out(challenge: Challenge, question, meta: dict[str, dict]) -> ChallengeOut:
    """One challenge as the API returns it.

    `meta` is the block library, fetched once by the caller: this runs per row
    and the library is the same for all of them. Required rather than
    defaulting to empty — an empty library silently yields a challenge with no
    renderable blocks, which reads as "this challenge has no content" instead
    of as the mistake it is.
    """
    order = block_service.present_order(list((challenge.content or {}).keys()), set(meta))
    return ChallengeOut(
        id=challenge.id,
        question_id=challenge.question_id,
        digest_id=challenge.digest_id,
        source=challenge.source,
        created_at=challenge.created_at,
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
        content=challenge.content,
        format_name=challenge.format_name,
        question_status=question.status if question else None,
        solved_at=question.solved_at if question else None,
        # The order to render in, resolved against the library so a block
        # deleted from either half stops rendering everywhere at once.
        blocks=order,
        block_meta=[meta[key] for key in order],
    )


@router.get("/challenges", response_model=list[ChallengeSummaryOut])
async def list_challenges(
    db: AsyncSession = Depends(get_db),
    source: str = Query("all", pattern="^(all|digest|manual)$"),
    # "active" is the default so a completed challenge disappears from the
    # ordinary working views the moment it's marked done, without vanishing
    # from the app — "completed" is where it goes to be seen, not deleted.
    completion: str = Query("active", pattern="^(active|completed|all)$"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    before: datetime | None = Query(
        None,
        description="Keyset cursor: the `created_at` (or `solved_at`, when listing "
        "completed) of the last row you already have.",
    ),
) -> list[ChallengeSummaryOut]:
    """Every challenge ever generated, newest first, whatever digest it came from.

    Without this the only reachable challenges were those in whichever digest
    the dashboard happened to show — anything in an older digest, or promoted
    by hand and so belonging to no digest at all, had no route to it.

    Paged by cursor rather than offset. `OFFSET 200` makes Postgres walk two
    hundred rows and discard them, and the window shifts under you whenever a
    row is inserted — a challenge generated mid-scroll pushes one you have
    already seen onto the next page. A cursor uses the index and is stable.

    `offset` stays for the frontend deployed before this, which sends it.
    """
    statement = (
        select(Challenge, Question)
        .join(Question, Question.id == Challenge.question_id)
        .order_by(Challenge.created_at.desc())
    )
    if source == "manual":
        statement = statement.where(Challenge.digest_id.is_(None))
    elif source == "digest":
        statement = statement.where(Challenge.digest_id.is_not(None))

    if completion == "active":
        statement = statement.where(Question.status != "solved")
    elif completion == "completed":
        statement = statement.where(Question.status == "solved")
        # order_by() appends rather than replaces, so the default
        # created_at ordering above has to be cleared or this would sort
        # by created_at first and solved_at second, doing nothing visible.
        statement = statement.order_by(None).order_by(Question.solved_at.desc())

    if before is not None:
        # Compared against whichever column the ordering above actually used,
        # or the cursor would page through a different sequence than it reads.
        column = Question.solved_at if completion == "completed" else Challenge.created_at
        statement = statement.where(column < before)

    rows = (await db.execute(statement.limit(limit).offset(offset))).all()
    return [_challenge_summary(challenge, question) for challenge, question in rows]


@router.get("/challenges/{challenge_id}", response_model=ChallengeOut)
async def get_challenge(challenge_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ChallengeOut:
    challenge = await db.get(Challenge, challenge_id)
    if challenge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")

    question = await db.get(Question, challenge.question_id)
    return _challenge_out(challenge, question, await block_service.render_meta(db))


@router.delete("/challenges/{challenge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_challenge(challenge_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    """Delete one challenge, leaving its question and its digest alone.

    Deleting a challenge that shipped in a sent digest is allowed — the UI
    warns that the link in that email stops working — but the digest row
    survives, so the history stays honest about what was sent and when.
    """
    challenge = await db.get(Challenge, challenge_id)
    if challenge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")

    await db.delete(challenge)
    await db.commit()


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

    if digest.status == "empty":
        profile_data = await get_profile_data(db)
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
