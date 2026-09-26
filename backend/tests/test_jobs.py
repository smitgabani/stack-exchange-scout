"""Background jobs: the request returns, the work happens afterwards.

The property that matters is not that jobs run — it is that they always reach
a terminal state. A job that fails must say why, and a job interrupted by a
deploy must stop claiming to be running, because the UI cannot tell that apart
from work still in progress and the user waits forever.

Rows in `jobs` are removed by the fixture.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.db import async_session
from app.models.job import Job
from app.services import job_service


@pytest.fixture
async def clean_jobs():
    yield
    async with async_session() as session:
        await session.execute(delete(Job))
        await session.commit()


@pytest.fixture
def registered_kinds():
    """Register throwaway workers, and take them out again afterwards."""
    calls: list[dict] = []

    @job_service.register("test_ok")
    async def _ok(db, payload):
        calls.append(payload)
        return {"echoed": payload}

    @job_service.register("test_boom")
    async def _boom(db, payload):
        raise ValueError("the model refused")

    yield calls

    job_service._WORKERS.pop("test_ok", None)
    job_service._WORKERS.pop("test_boom", None)


# --- 🔒 a job always reaches a terminal state ---


@pytest.mark.anyio
async def test_a_successful_job_records_its_result(clean_jobs, registered_kinds) -> None:
    async with async_session() as db:
        job = await job_service.create(db, kind="test_ok", payload={"n": 1})

    await job_service.run(job.id)

    async with async_session() as db:
        done = await db.get(Job, job.id)
        assert done.status == "succeeded"
        assert done.result == {"echoed": {"n": 1}}
        assert done.error is None
        assert done.finished_at is not None


@pytest.mark.anyio
async def test_a_failing_job_records_why_and_does_not_raise(clean_jobs, registered_kinds) -> None:
    """A background task nobody awaits must not throw — the failure has to be
    readable from the row, which is the only thing the browser will see.
    """
    async with async_session() as db:
        job = await job_service.create(db, kind="test_boom", payload={})

    await job_service.run(job.id)  # must not raise

    async with async_session() as db:
        done = await db.get(Job, job.id)
        assert done.status == "failed"
        assert "the model refused" in done.error
        assert done.finished_at is not None


@pytest.mark.anyio
async def test_a_job_is_not_run_twice(clean_jobs, registered_kinds) -> None:
    """Two deliveries of the same task must not mean two LLM bills."""
    async with async_session() as db:
        job = await job_service.create(db, kind="test_ok", payload={"n": 1})

    await job_service.run(job.id)
    await job_service.run(job.id)

    assert len(registered_kinds) == 1


@pytest.mark.anyio
async def test_an_unknown_kind_is_refused_at_creation(clean_jobs) -> None:
    """Better to refuse the request than to queue work nothing can perform."""
    async with async_session() as db:
        with pytest.raises(job_service.JobError, match="No worker"):
            await job_service.create(db, kind="not_a_real_kind", payload={})


# --- 🔒 a deploy must not leave a job claiming to be running ---


@pytest.mark.anyio
async def test_interrupted_jobs_are_failed_on_startup(clean_jobs, registered_kinds) -> None:
    """Without this, a row says `running` forever and the user waits for
    something that will never finish.
    """
    async with async_session() as db:
        queued = await job_service.create(db, kind="test_ok", payload={})
        running = await job_service.create(db, kind="test_ok", payload={})
        running.status = "running"
        await db.commit()

    recovered = await job_service.recover_interrupted()
    assert recovered == 2

    async with async_session() as db:
        for job_id in (queued.id, running.id):
            job = await db.get(Job, job_id)
            assert job.status == "failed"
            assert "Interrupted" in job.error


@pytest.mark.anyio
async def test_recovery_leaves_finished_jobs_alone(clean_jobs, registered_kinds) -> None:
    async with async_session() as db:
        job = await job_service.create(db, kind="test_ok", payload={})
    await job_service.run(job.id)

    await job_service.recover_interrupted()

    async with async_session() as db:
        assert (await db.get(Job, job.id)).status == "succeeded"


# --- 🧩 the API returns immediately ---


@pytest.mark.anyio
async def test_starting_a_job_returns_202_without_doing_the_work(
    client: TestClient, auth_cookies: dict[str, str], clean_jobs, gemini_key_stored
) -> None:
    """The whole point: the request does not wait for the LLM.

    `BackgroundTasks` runs after the response, but TestClient drains them
    before returning — so this asserts the shape of the response, and the
    tests above cover what the work does.
    """
    response = client.post(
        "/jobs/challenge-create",
        cookies=auth_cookies,
        json={"question_id": str(uuid.uuid4())},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["kind"] == "challenge_create"
    assert body["id"]


@pytest.mark.anyio
async def test_a_job_can_be_polled_by_id(
    client: TestClient, auth_cookies: dict[str, str], clean_jobs, registered_kinds
) -> None:
    async with async_session() as db:
        job = await job_service.create(db, kind="test_ok", payload={})

    body = client.get(f"/jobs/{job.id}", cookies=auth_cookies).json()

    assert body["id"] == str(job.id)
    assert body["status"] in ("queued", "running", "succeeded")


def test_an_unknown_job_is_a_404(client: TestClient, auth_cookies: dict[str, str]) -> None:
    assert client.get(f"/jobs/{uuid.uuid4()}", cookies=auth_cookies).status_code == 404


def test_jobs_require_a_session(client: TestClient) -> None:
    assert client.get(f"/jobs/{uuid.uuid4()}").status_code == 401
    assert client.post("/jobs/digest-generate").status_code == 401


# --- 🔒 a job that fails at creation leaves no orphan row ---


@pytest.mark.anyio
async def test_a_refused_kind_writes_no_row(clean_jobs) -> None:
    async with async_session() as db:
        with pytest.raises(job_service.JobError):
            await job_service.create(db, kind="nope", payload={})
        assert list(await db.scalars(select(Job))) == []
