"""Start a long job, and ask how it is going.

These sit alongside the synchronous endpoints they replace rather than
replacing them, because the backend and the frontend do not deploy together —
removing an endpoint the deployed frontend still calls takes the app down, as
it did once already. The synchronous versions go once the frontend has moved.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_gemini_key
from app.core.db import get_db
from app.models.job import Job
from app.services import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _out(job: Job) -> dict:
    return {
        "id": str(job.id),
        "kind": job.kind,
        "status": job.status,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


async def _start(
    db: AsyncSession, background: BackgroundTasks, *, kind: str, payload: dict
) -> dict:
    """Queue a job and hand it to the background, returning at once.

    `BackgroundTasks` runs the work after the response is sent, in this
    process. That is only safe because the machine no longer scales to zero;
    anything still running when it does stop is failed honestly on next
    startup by `recover_interrupted`.
    """
    try:
        job = await job_service.create(db, kind=kind, payload=payload)
    except job_service.JobError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    background.add_task(job_service.run, job.id)
    return _out(job)


class ChallengeJobIn(BaseModel):
    question_id: uuid.UUID
    format_id: int | None = None


class ReformatJobIn(BaseModel):
    challenge_id: uuid.UUID
    format_id: int | None = None


@router.post(
    "/digest-generate",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_gemini_key)],
)
async def start_digest(
    background: BackgroundTasks, db: AsyncSession = Depends(get_db)
) -> dict:
    """Up to ten LLM calls. Synchronously this held a request for minutes."""
    return await _start(db, background, kind="digest_generate", payload={})


@router.post(
    "/challenge-create",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_gemini_key)],
)
async def start_challenge(
    body: ChallengeJobIn, background: BackgroundTasks, db: AsyncSession = Depends(get_db)
) -> dict:
    return await _start(
        db,
        background,
        kind="challenge_create",
        payload={"question_id": str(body.question_id), "format_id": body.format_id},
    )


@router.post(
    "/reformat",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_gemini_key)],
)
async def start_reformat(
    body: ReformatJobIn, background: BackgroundTasks, db: AsyncSession = Depends(get_db)
) -> dict:
    return await _start(
        db,
        background,
        kind="reformat",
        payload={"challenge_id": str(body.challenge_id), "format_id": body.format_id},
    )


@router.post(
    "/llm-test",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_gemini_key)],
)
async def start_llm_test(
    body: ChallengeJobIn, background: BackgroundTasks, db: AsyncSession = Depends(get_db)
) -> dict:
    return await _start(
        db,
        background,
        kind="llm_test",
        payload={"question_id": str(body.question_id), "format_id": body.format_id},
    )


@router.get("/{job_id}")
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Cheap by design — this is what the Check status button calls."""
    job = await job_service.get(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such job")
    return _out(job)
