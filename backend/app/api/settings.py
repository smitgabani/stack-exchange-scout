from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.services.credentials_service import has_api_key, set_api_key

router = APIRouter(prefix="/settings", tags=["settings"])


class ApiKeyRequest(BaseModel):
    api_key: str


class ApiKeyStatus(BaseModel):
    connected: bool


@router.post("/yutori-key", response_model=ApiKeyStatus)
async def set_yutori_key(body: ApiKeyRequest, db: AsyncSession = Depends(get_db)) -> ApiKeyStatus:
    await set_api_key(db, "yutori_api_key", body.api_key)
    return ApiKeyStatus(connected=True)


@router.get("/yutori-key/status", response_model=ApiKeyStatus)
async def yutori_key_status(db: AsyncSession = Depends(get_db)) -> ApiKeyStatus:
    return ApiKeyStatus(connected=await has_api_key(db, "yutori_api_key"))


@router.post("/gemini-key", response_model=ApiKeyStatus)
async def set_gemini_key(body: ApiKeyRequest, db: AsyncSession = Depends(get_db)) -> ApiKeyStatus:
    await set_api_key(db, "gemini_api_key", body.api_key)
    return ApiKeyStatus(connected=True)


@router.get("/gemini-key/status", response_model=ApiKeyStatus)
async def gemini_key_status(db: AsyncSession = Depends(get_db)) -> ApiKeyStatus:
    return ApiKeyStatus(connected=await has_api_key(db, "gemini_api_key"))


@router.post("/openai-key", response_model=ApiKeyStatus)
async def set_openai_key(body: ApiKeyRequest, db: AsyncSession = Depends(get_db)) -> ApiKeyStatus:
    await set_api_key(db, "openai_api_key", body.api_key)
    return ApiKeyStatus(connected=True)


@router.get("/openai-key/status", response_model=ApiKeyStatus)
async def openai_key_status(db: AsyncSession = Depends(get_db)) -> ApiKeyStatus:
    return ApiKeyStatus(connected=await has_api_key(db, "openai_api_key"))
