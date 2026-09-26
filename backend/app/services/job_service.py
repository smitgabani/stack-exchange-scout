"""Work that outlives the request that asked for it.

Every LLM call used to happen inside its HTTP request. A digest is up to ten
questions at two attempts each with a 60-second timeout — twenty minutes worst
case, seventy seconds typically — and the Vercel function proxying it stayed
alive for all of it. Fluid Compute bills for time alive, not work done, which
is what paused the deployment.

Now the request writes a row and returns in milliseconds, and the work happens
after the response. The row carries the answer when there is one and the reason
when there is not.

Two things about running this in-process rather than on a queue. It is enough
for one user, and it needs no new infrastructure. But it only works because the
machine stays up — `fly.toml` no longer scales to zero — and a deploy still
kills whatever is mid-flight, which `recover_interrupted` turns into an honest
failure rather than a job that says "running" forever.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session
from app.models.job import Job

logger = logging.getLogger(__name__)

# What a worker is: it gets its own session and the payload, and returns
# whatever the endpoint would have returned synchronously.
Worker = Callable[[AsyncSession, dict[str, Any]], Awaitable[dict[str, Any]]]

_WORKERS: dict[str, Worker] = {}


def register(kind: str) -> Callable[[Worker], Worker]:
    """Attach a worker to a job kind.

    A registry rather than a match statement so the job machinery does not
    import the services it runs — `digest_service` already imports enough.
    """

    def decorator(worker: Worker) -> Worker:
        _WORKERS[kind] = worker
        return worker

    return decorator


class JobError(RuntimeError):
    """A job could not be created."""


async def create(db: AsyncSession, *, kind: str, payload: dict[str, Any]) -> Job:
    if kind not in _WORKERS:
        raise JobError(f"No worker is registered for “{kind}”.")
    job = Job(kind=kind, status="queued", payload=payload)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def run(job_id: uuid.UUID) -> None:
    """Execute one job. Never raises — a job that fails records why.

    Its own session, not the request's: the request has already returned and
    its session is closed by the time this runs.
    """
    async with async_session() as db:
        job = await db.get(Job, job_id)
        if job is None or job.status != "queued":
            # Already claimed, already done, or gone. Not an error worth
            # raising into a background task nobody is awaiting.
            return

        job.status = "running"
        job.started_at = datetime.now(UTC)
        await db.commit()

    worker = _WORKERS.get(job.kind)
    result: dict[str, Any] | None = None
    error: str | None = None

    try:
        if worker is None:
            raise JobError(f"No worker is registered for “{job.kind}”.")
        async with async_session() as db:
            result = await worker(db, job.payload or {})
    except Exception as exc:  # a job must not take the process down with it
        # The message reaches the user, so it is the exception's own text
        # rather than a traceback. The traceback goes to the log.
        error = str(exc) or exc.__class__.__name__
        logger.exception("Job %s (%s) failed", job_id, job.kind)

    async with async_session() as db:
        await db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status="failed" if error else "succeeded",
                result=result,
                error=error,
                finished_at=datetime.now(UTC),
            )
        )
        await db.commit()


async def recover_interrupted() -> int:
    """Fail jobs that were mid-flight when the process last stopped.

    Called on startup. Without it a deploy leaves rows saying `running`
    forever, which the UI cannot tell from a job that is genuinely still
    working — the user waits for something that will never finish.
    """
    async with async_session() as db:
        stale = list(await db.scalars(select(Job).where(Job.status.in_(("queued", "running")))))
        if not stale:
            return 0
        await db.execute(
            update(Job)
            .where(Job.status.in_(("queued", "running")))
            .values(
                status="failed",
                error="Interrupted by a restart or deploy. Nothing was saved — start it again.",
                finished_at=datetime.now(UTC),
            )
        )
        await db.commit()
    logger.warning("Marked %d interrupted job(s) as failed on startup", len(stale))
    return len(stale)
