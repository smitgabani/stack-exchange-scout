from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.services.credentials_service import has_api_key


async def require_yutori_key(db: AsyncSession = Depends(get_db)) -> None:
    if not await has_api_key(db, "yutori_api_key"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Yutori API key not configured")


async def require_gemini_key(db: AsyncSession = Depends(get_db)) -> None:
    if not await has_api_key(db, "gemini_api_key"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gemini API key not configured")
