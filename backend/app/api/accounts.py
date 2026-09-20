"""Yutori API keys, which may belong to different accounts (ADR 0004)."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.repositories import credential_repository
from app.services import account_service
from app.services.credentials_service import get_api_key

router = APIRouter(tags=["accounts"])


class AccountIn(BaseModel):
    api_key: str = Field(min_length=8)
    label: str = Field(min_length=1, max_length=120)
    make_active: bool = True


@router.get("/accounts")
async def list_accounts(db: AsyncSession = Depends(get_db)) -> dict:
    accounts = await account_service.list_accounts(db)
    return {"accounts": [a.__dict__ for a in accounts]}


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
async def add_account(body: AccountIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Store another API key.

    The key is verified with a free call before being trusted, because an
    unusable key is otherwise indistinguishable from a working one until
    someone spends money with it.
    """
    try:
        summary = await account_service.add_account(
            db, api_key=body.api_key, label=body.label, make_active=body.make_active
        )
    except account_service.DuplicateAccount as exc:
        # 409, not 422: the request is well formed, the account is simply
        # already here. The message names the existing entry so the user can
        # find it rather than wondering which one clashed.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return summary.__dict__


class AccountPatch(BaseModel):
    label: str = Field(min_length=1, max_length=120)


@router.patch("/accounts/{credential_id}")
async def rename_account(
    credential_id: int, body: AccountPatch, db: AsyncSession = Depends(get_db)
) -> dict:
    """Rename an account. The name is how Scouts from different accounts are
    told apart, so it should never be stuck at whatever was typed first."""
    summary = await account_service.rename_account(db, credential_id, body.label)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such account")
    return summary.__dict__


class SpendPatch(BaseModel):
    # None clears the correction and goes back to the computed total. Capped to
    # keep a typo like 35 instead of 0.35 from silently becoming the record.
    spend_usd: float | None = Field(default=None, ge=0, le=100_000)


@router.put("/accounts/{credential_id}/spend")
async def set_account_spend(
    credential_id: int, body: SpendPatch, db: AsyncSession = Depends(get_db)
) -> dict:
    """Correct what this account actually cost.

    The computed total only counts runs recorded in `scout_runs`, which did not
    exist before M12 — earlier spend is invisible to it and cannot be
    recovered. The Yutori bill is the source of truth, and this is how it gets
    in. Sending null restores the computed figure.
    """
    summary = await account_service.set_spend_override(db, credential_id, body.spend_usd)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such account")
    return summary.__dict__


@router.post("/accounts/{credential_id}/activate")
async def activate_account(
    credential_id: int, db: AsyncSession = Depends(get_db)
) -> dict:
    summary = await account_service.activate_account(db, credential_id)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No such account"
        )
    return summary.__dict__


@router.delete("/accounts/{credential_id}")
async def remove_account(
    credential_id: int, db: AsyncSession = Depends(get_db)
) -> dict:
    """Remove a key. Everything it discovered stays."""
    result = await account_service.remove_account(db, credential_id)
    if not result.removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.error or "No such account",
        )
    return {"removed": True, "label": result.label, "kept": result.kept}


@router.get("/accounts/{credential_id}/objects")
async def account_objects(
    credential_id: int, db: AsyncSession = Depends(get_db)
) -> dict:
    """Everything that exists at Yutori under this key, read from Yutori."""
    credential = await credential_repository.get_by_id(db, credential_id)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No such account"
        )
    if not credential.is_active:
        # Only the active key is decryptable through the normal path, and
        # decrypting an inactive one just to list its objects would mean
        # handling the key outside the one place that owns that.
        return {"scouts": [], "error": "Activate this key to inspect its account"}

    api_key = await get_api_key(db, credential.key_name)
    if api_key is None:
        return {"scouts": [], "error": "This key could not be decrypted"}
    return await account_service.account_objects(db, api_key)
