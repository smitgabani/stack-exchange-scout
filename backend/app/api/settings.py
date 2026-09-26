from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.services.credentials_service import has_api_key, set_api_key

router = APIRouter(prefix="/settings", tags=["settings"])

Provider = Literal["yutori", "gemini", "openai"]


class ApiKeyRequest(BaseModel):
    api_key: str
    # Only meaningful for Yutori, where several accounts can be stored and the
    # list has to say whose is whose.
    label: str | None = None


class ApiKeyStatus(BaseModel):
    connected: bool


@router.post("/{provider}-key", response_model=ApiKeyStatus)
async def set_key(
    provider: Provider, body: ApiKeyRequest, db: AsyncSession = Depends(get_db)
) -> ApiKeyStatus:
    await set_api_key(db, f"{provider}_api_key", body.api_key, label=body.label)
    return ApiKeyStatus(connected=True)


@router.get("/{provider}-key/status", response_model=ApiKeyStatus)
async def key_status(provider: Provider, db: AsyncSession = Depends(get_db)) -> ApiKeyStatus:
    return ApiKeyStatus(connected=await has_api_key(db, f"{provider}_api_key"))
