from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.services.credentials_service import has_api_key

# These aren't attached to any route yet — the discovery/digest routes they'll
# guard (M4, M7) don't exist yet. Built now per M2-B7/B8 so those milestones
# just add `Depends(require_yutori_key)` / `Depends(require_gemini_key)`.


async def require_yutori_key(db: AsyncSession = Depends(get_db)) -> None:
    if not await has_api_key(db, "yutori_api_key"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Yutori API key not configured")


async def require_gemini_key(db: AsyncSession = Depends(get_db)) -> None:
    if not await has_api_key(db, "gemini_api_key"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gemini API key not configured")
