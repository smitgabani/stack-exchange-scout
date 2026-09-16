from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas.profile import ProfileResponse
from app.services.profile_service import apply_patch, get_or_create_profile

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileResponse)
async def get_profile(db: AsyncSession = Depends(get_db)) -> ProfileResponse:
    profile = await get_or_create_profile(db)
    return ProfileResponse(data=profile.data, version=profile.version)


@router.patch("", response_model=ProfileResponse)
async def patch_profile(
    patch: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    profile = await apply_patch(db, patch)
    return ProfileResponse(data=profile.data, version=profile.version)
