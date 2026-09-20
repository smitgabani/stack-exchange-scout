"""Managing the Yutori API keys the app runs against (ADR 0004).

The app can hold several keys belonging to different accounts — the user's own
and a friend's, say — with exactly one active at a time. Two things make that
workable:

* **Fingerprints.** Yutori exposes no account identifier, so every remote
  object records `sha256(key)[:16]`. That is enough to recognise which account
  created what, without keeping a second copy of the key anywhere.
* **Tombstones.** Removing a key removes the credential and nothing else. The
  questions it found stay, because that history is exactly what stops the app
  rediscovering — and re-paying for — what the user has already seen.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt_value
from app.integrations.yutori import YutoriClient, YutoriError
from app.models.scout_definition import ScoutInstance, ScoutRun
from app.repositories import credential_repository
from app.services.credentials_service import get_api_key
from app.services.scout_service import fingerprint

logger = logging.getLogger(__name__)

YUTORI = "yutori_api_key"


@dataclass
class AccountSummary:
    id: int
    label: str
    key_name: str
    is_active: bool
    account_fingerprint: str | None
    created_at: str | None
    spend_usd: float = 0.0
    run_count: int = 0
    instance_count: int = 0
    # None when we have not checked, True/False once we have. Checking costs a
    # free GET, so it is only done when the page asks for it.
    reachable: bool | None = None
    error: str | None = None


@dataclass
class RemovalResult:
    removed: bool
    label: str | None = None
    kept: dict[str, int] = field(default_factory=dict)
    error: str | None = None


async def list_accounts(
    db: AsyncSession, key_name: str = YUTORI
) -> list[AccountSummary]:
    """Every stored key for a provider, with what it has spent.

    Spend is attributed by fingerprint rather than by a foreign key, so a run
    charged to a key that has since been deleted still reports against the
    right account instead of vanishing from the totals.
    """
    await backfill_active_fingerprint(db, key_name)
    credentials = await credential_repository.list_for(db, key_name)

    spend_rows = (
        await db.execute(
            select(
                ScoutRun.account_fingerprint,
                func.coalesce(func.sum(ScoutRun.cost_usd), 0),
                func.count(ScoutRun.id),
            ).group_by(ScoutRun.account_fingerprint)
        )
    ).all()
    spend = {row[0]: (float(row[1]), row[2]) for row in spend_rows}

    instance_rows = (
        await db.execute(
            select(
                ScoutInstance.account_fingerprint, func.count(ScoutInstance.id)
            ).group_by(ScoutInstance.account_fingerprint)
        )
    ).all()
    instances = {row[0]: row[1] for row in instance_rows}

    summaries = []
    for credential in credentials:
        printed = credential.account_fingerprint
        total, runs = spend.get(printed, (0.0, 0))
        summaries.append(
            AccountSummary(
                id=credential.id,
                label=credential.label or credential.key_name,
                key_name=credential.key_name,
                is_active=credential.is_active,
                account_fingerprint=printed,
                created_at=credential.created_at.isoformat()
                if credential.created_at
                else None,
                spend_usd=round(total, 2),
                run_count=runs,
                instance_count=instances.get(printed, 0),
            )
        )
    return summaries


async def backfill_active_fingerprint(db: AsyncSession, key_name: str = YUTORI) -> None:
    """Fill in the fingerprint of the active key if it predates the column.

    Without it, a key stored before fingerprinting can never be matched to the
    runs and instances it created — they would show as belonging to nobody, and
    the spend column would read zero for an account that has spent money. Only
    the active key can be decrypted, which is fine: the inactive ones get
    theirs when they are next activated.
    """
    credential = await credential_repository.get(db, key_name)
    if credential is None or credential.account_fingerprint:
        return
    api_key = await get_api_key(db, key_name)
    if api_key is None:
        return
    credential.account_fingerprint = fingerprint(api_key)
    await db.commit()


async def add_account(
    db: AsyncSession,
    *,
    api_key: str,
    label: str,
    make_active: bool = True,
    key_name: str = YUTORI,
) -> AccountSummary:
    """Store an additional key, verifying it before trusting it.

    The check is a free GET. It matters because an unusable key is otherwise
    indistinguishable from a working one until the moment someone spends money
    with it — which is exactly how an 18-character key sat in this app for two
    days answering 401 to everything.
    """
    printed = fingerprint(api_key)
    reachable, error = await verify_key(api_key)

    credential = await credential_repository.add(
        db,
        key_name,
        encrypt_value(api_key),
        label=label,
        fingerprint=printed,
        make_active=make_active,
    )
    return AccountSummary(
        id=credential.id,
        label=credential.label or key_name,
        key_name=key_name,
        is_active=credential.is_active,
        account_fingerprint=printed,
        created_at=credential.created_at.isoformat() if credential.created_at else None,
        reachable=reachable,
        error=error,
    )


async def verify_key(api_key: str) -> tuple[bool, str | None]:
    """Is this key usable? A free call, so there is no reason not to ask."""
    try:
        await YutoriClient(api_key).get_usage("24h")
    except YutoriError as exc:
        return False, str(exc)[:300]
    return True, None


async def rename_account(
    db: AsyncSession, credential_id: int, label: str
) -> AccountSummary | None:
    """Rename a stored account. Local only — Yutori has no concept of this."""
    credential = await credential_repository.get_by_id(db, credential_id)
    if credential is None:
        return None
    credential.label = label
    await db.commit()
    accounts = await list_accounts(db, credential.key_name)
    return next((a for a in accounts if a.id == credential_id), None)


async def activate_account(
    db: AsyncSession, credential_id: int
) -> AccountSummary | None:
    credential = await credential_repository.get_by_id(db, credential_id)
    if credential is None:
        return None
    await credential_repository.activate(db, credential)
    accounts = await list_accounts(db, credential.key_name)
    return next((a for a in accounts if a.id == credential_id), None)


async def remove_account(db: AsyncSession, credential_id: int) -> RemovalResult:
    """Delete a stored key. A tombstone, never a cascade.

    What survives is deliberate and worth stating in the return value, because
    it is the question a user actually has when deleting: the discovered
    questions, the run history (which keeps the account's label so it still
    reads), and the saved definitions, which were never remote in the first
    place.
    """
    credential = await credential_repository.get_by_id(db, credential_id)
    if credential is None:
        return RemovalResult(removed=False, error="No such account")

    from app.models.question import Question

    kept = {
        "questions": await db.scalar(select(func.count()).select_from(Question)) or 0,
        "runs": await db.scalar(
            select(func.count())
            .select_from(ScoutRun)
            .where(ScoutRun.account_fingerprint == credential.account_fingerprint)
        )
        or 0,
    }
    label = credential.label or credential.key_name
    await credential_repository.delete(db, credential)
    logger.info("Removed Yutori account %s; kept %s", label, kept)
    return RemovalResult(removed=True, label=label, kept=kept)


async def account_objects(db: AsyncSession, api_key: str) -> dict[str, Any]:
    """Everything that exists at Yutori under a key.

    Read from Yutori rather than from our own records on purpose: an object we
    never created, or created and then lost track of, is precisely the one that
    would otherwise keep billing unnoticed.
    """
    client = YutoriClient(api_key)
    result: dict[str, Any] = {"scouts": [], "usage": None, "error": None}
    try:
        listing = await client.list_scouts()
        result["scouts"] = [
            {
                "id": str(item.get("id")),
                "status": item.get("status"),
                "created_at": item.get("created_at"),
                "update_count": item.get("update_count"),
            }
            for item in (listing.get("scouts") or listing.get("items") or [])
        ]
    except YutoriError as exc:
        result["error"] = str(exc)[:300]

    try:
        usage = await client.get_usage("30d")
        result["usage"] = usage.get("activity") or {}
        result["rate_limits"] = usage.get("rate_limits")
    except YutoriError:
        pass

    tracked = {
        row[0] for row in (await db.execute(select(ScoutInstance.external_id))).all()
    }
    for scout in result["scouts"]:
        scout["tracked"] = scout["id"] in tracked
    return result
