"""Shared fixtures — and the guard that keeps the suite out of real data.

`DATABASE_URL` points at the same Supabase project production uses. There is no
separate test database, so these tests write to the live profile and the live
credentials table. Several of them do exactly that by design: the profile tests
PATCH topics, the settings tests store API keys.

Left unguarded, that is destructive in a way that is easy to miss. Over one
day's work it silently replaced the user's topics with `Rust`, set their digest
to every 9 days, switched their LLM provider to OpenAI, inflated the profile
version past 130, and overwrote all three real API keys with
`super-secret-value` — which then read as "could not be decrypted" and looked
for hours like an encryption-key problem.

So the whole suite runs inside a snapshot: the profile and credentials rows are
copied out before the first test and restored exactly afterwards, whether the
run passes, fails, or errors.
"""

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


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


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

    async def put_back() -> None:
        await _restore(Profile, saved["profile"])
        await _restore(Credential, saved["credentials"])

    anyio.run(capture)
    try:
        yield
    finally:
        anyio.run(put_back)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
