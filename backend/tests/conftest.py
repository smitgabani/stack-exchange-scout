from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import async_session
from app.main import app


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
