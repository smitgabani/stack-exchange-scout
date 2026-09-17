from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_yutori_key
from app.core.db import get_db
from app.schemas.profile import ProfileData
from app.services import ingest_service, scout_service
from app.services.profile_service import get_or_create_profile

router = APIRouter(tags=["scout"])


class ScoutStatus(BaseModel):
    configured: bool
    external_scout_id: str | None = None
    sync_status: str | None = None
    last_synced_at: datetime | None = None
    last_sync_error: str | None = None


class SyncResponse(BaseModel):
    action: str
    scout_id: str | None = None
    error: str | None = None


@router.get("/scout", response_model=ScoutStatus)
async def get_scout(db: AsyncSession = Depends(get_db)) -> ScoutStatus:
    scout = await scout_service.get_status(db)
    if scout is None:
        return ScoutStatus(configured=False)
    return ScoutStatus(
        configured=scout.external_scout_id is not None,
        external_scout_id=scout.external_scout_id,
        sync_status=scout.sync_status,
        last_synced_at=scout.last_synced_at,
        last_sync_error=scout.last_sync_error,
    )


@router.post("/scout/sync", response_model=SyncResponse, dependencies=[Depends(require_yutori_key)])
async def sync_scout(db: AsyncSession = Depends(get_db)) -> SyncResponse:
    """Manual re-trigger of the same sync the profile save performs (prd.md §24)."""
    profile = await get_or_create_profile(db)
    result = await scout_service.sync(db, ProfileData.model_validate(profile.data), allow_create=True)
    return SyncResponse(action=result.action, scout_id=result.scout_id, error=result.error)


@router.post("/candidates/ingest")
async def ingest_candidates(db: AsyncSession = Depends(get_db)) -> dict:
    """Turn stored webhook events into question rows.

    Separate from the webhook itself so ingestion is re-runnable and survives
    the machine being stopped mid-flight; M11 will call the same stage on a
    schedule instead of by hand.
    """
    result = await ingest_service.ingest_pending(db)
    return result.as_dict()
