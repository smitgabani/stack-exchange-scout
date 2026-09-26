"""Shared fixtures, and the guard that keeps the suite off the real database.

Tests used to run against the same Supabase project production uses, because
there was no other database to run them against. Over one day that cost four
incidents: twelve scratch questions left in the real candidate pool, nine
shipped library blocks deleted by an over-broad fixture, and a profile
overwritten with test values.

They now run against Postgres on localhost. The important part is not the
connection string — it is the check below, which aborts the run rather than
touching anything remote. A guard that catches damage afterwards is worth
much less than one that makes it impossible to start.

`DATABASE_URL` is set here, before any app import, because `app.core.db`
builds its engine at import time from whatever is set then.
"""

import os

# Overridden rather than defaulted: a DATABASE_URL already in the environment
# or in backend/.env points at production, and setdefault would quietly use it.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://localhost:5432/scout_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
# pytest-anyio gives each test its own event loop, and a pooled asyncpg
# connection cannot cross loops. Local connections are sub-millisecond, so the
# suite gives up pooling for free.
os.environ["DB_POOL"] = "null"

_HOST_IS_LOCAL = any(
    marker in TEST_DATABASE_URL for marker in ("localhost", "127.0.0.1", "@db:", "host.docker.internal")
)
if not _HOST_IS_LOCAL:
    raise RuntimeError(
        "Refusing to run the suite: DATABASE_URL is not a local database.\n"
        f"  got: {TEST_DATABASE_URL}\n"
        "These tests create, overwrite and delete rows. Point TEST_DATABASE_URL at a "
        "local Postgres (see docker-compose.yml or `brew services start postgresql@16`)."
    )

from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import async_session
from app.main import app
from app.models.credential import Credential
from app.models.profile import Profile
from app.models.scout_definition import (
    ScoutDefinition,
    ScoutInstance,
    ScoutRun,
)


@pytest.fixture(scope="session", autouse=True)
def migrate_test_database() -> None:
    """Bring the local database up to head once per run.

    Cheap because it is local, and it means a new checkout needs no setup step
    that someone has to remember: start Postgres, run pytest.
    """
    from alembic.config import Config

    from alembic import command

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")


async def existing_ids(model) -> set:
    """The primary keys already in a table before a test runs."""
    async with async_session() as session:
        return set(await session.scalars(select(model.id)))


async def delete_rows_added_since(model, before: set) -> None:
    """Remove only what the test added, never what was already there.

    `delete(Model)` with no WHERE is the shape that cost real data: fixtures
    doing it wiped every challenge format and every saved prompt version out
    of the live database on each run, because the suite used to point at
    production. The local-database guard at the top of this file is the real
    protection; this is the second layer, so a fixture is not one
    misconfigured environment variable away from being destructive again.
    """
    async with async_session() as session:
        statement = delete(model)
        if before:
            statement = statement.where(model.id.not_in(before))
        await session.execute(statement)
        await session.commit()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def gemini_key_stored(client: TestClient):
    """Pass the "is a Gemini key stored?" check without storing one.

    Routes that spend LLM calls refuse with 403 when no key is stored. Tests
    that exercise those routes' own behaviour (202, rate limits) used to pass
    only because a real key happened to be left in the local database — so
    they failed in CI, whose database starts empty. No LLM is called either
    way: these tests never reach the provider.
    """
    from app.api import deps

    async def stored() -> None:
        return None

    client.app.dependency_overrides[deps.require_gemini_key] = stored
    yield
    client.app.dependency_overrides.pop(deps.require_gemini_key, None)


@pytest.fixture
def auth_cookies(client: TestClient) -> dict[str, str]:
    response = client.post("/auth/login", json={"password": settings.app_access_password})
    return {"session": response.cookies["session"]}


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def _snapshot(model) -> list[dict]:
    async with async_session() as session:
        rows = (await session.scalars(select(model))).all()
        return [
            {column.name: getattr(row, column.name) for column in model.__table__.columns}
            for row in rows
        ]


async def _restore(model, snapshot: list[dict]) -> None:
    async with async_session() as session:
        await session.execute(delete(model))
        for values in snapshot:
            await session.execute(model.__table__.insert().values(**values))
        await session.commit()


@pytest.fixture(scope="session", autouse=True)
def protect_real_data() -> AsyncGenerator[None, None]:
    """Copy the user's profile and credentials out, and put them back.

    Session-scoped and autouse so it cannot be forgotten by a new test file.
    Restoration writes the rows back verbatim, primary keys included, so the
    version number and the encrypted key values are exactly as they were —
    anything less would leave the app looking subtly wrong afterwards.
    """
    import anyio

    saved: dict[str, list[dict]] = {}

    async def capture() -> None:
        saved["profile"] = await _snapshot(Profile)
        saved["credentials"] = await _snapshot(Credential)
        saved["definitions"] = await _snapshot(ScoutDefinition)
        saved["instances"] = await _snapshot(ScoutInstance)
        saved["runs"] = await _snapshot(ScoutRun)

    async def put_back() -> None:
        await _restore(Profile, saved["profile"])
        await _restore(Credential, saved["credentials"])
        # Foreign keys point runs → instances → definitions, so rows come back
        # parents first and are cleared children first.
        async with async_session() as session:
            await session.execute(delete(ScoutRun))
            await session.execute(delete(ScoutInstance))
            await session.execute(delete(ScoutDefinition))
            for values in saved["definitions"]:
                await session.execute(ScoutDefinition.__table__.insert().values(**values))
            for values in saved["instances"]:
                await session.execute(ScoutInstance.__table__.insert().values(**values))
            for values in saved["runs"]:
                await session.execute(ScoutRun.__table__.insert().values(**values))
            await session.commit()

    anyio.run(capture)
    try:
        yield
    finally:
        anyio.run(put_back)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
