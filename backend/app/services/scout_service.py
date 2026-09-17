import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.yutori import YutoriClient, YutoriError
from app.models.scout import Scout
from app.repositories import scout_repository
from app.schemas.profile import ProfileData
from app.services import query_generator
from app.services.credentials_service import get_api_key

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 86400


@dataclass
class SyncResult:
    action: str  # created | updated | unchanged | failed | skipped
    scout_id: str | None = None
    error: str | None = None


def _hash(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()


async def sync(db: AsyncSession, profile_data: ProfileData, *, allow_create: bool = False) -> SyncResult:
    """Push the current profile's query to Yutori (prd.md §25 `scout_sync`).

    Only ever touches the Scout's *query*; deciding whether a paid run should
    happen is the usage gate's job (M9). Never raises: a Yutori outage must not
    cost the user their profile edit (tdd.md §8.2), so failures are recorded on
    the scout row and surfaced through the return value instead.

    `allow_create` is off by default because creating a Scout starts it running
    and bills for it. An incidental profile edit must never spend money — only
    an explicit POST /scout/sync may create. Once M9's confirmation gate exists,
    that decision moves there.
    """
    query = query_generator.generate(profile_data)
    query_hash = _hash(query)
    scout = await scout_repository.get(db)

    if scout is not None and scout.query_hash == query_hash and scout.sync_status == "active":
        return SyncResult(action="unchanged", scout_id=scout.external_scout_id)

    if (scout is None or scout.external_scout_id is None) and not allow_create:
        return SyncResult(action="skipped", error="No Scout exists yet; create one via POST /scout/sync")

    api_key = await get_api_key(db, "yutori_api_key")
    if api_key is None:
        return SyncResult(action="skipped", error="No Yutori API key stored")

    if not settings.public_base_url:
        return SyncResult(action="skipped", error="PUBLIC_BASE_URL is not configured")

    client = YutoriClient(api_key)
    interval_seconds = max(profile_data.scout.interval_days, 1) * SECONDS_PER_DAY

    if scout is None:
        scout = await scout_repository.create(
            db, provider="yutori", query_text=query, query_hash=query_hash, sync_status="pending"
        )

    try:
        if scout.external_scout_id is None:
            # Creating the Scout starts it immediately — a billable run.
            response = await client.create_scout(
                query=query,
                webhook_url=settings.yutori_webhook_url,
                output_interval_seconds=interval_seconds,
            )
            scout.external_scout_id = str(response.get("id"))
            action = "created"
        else:
            await client.update_scout(
                scout.external_scout_id,
                query=query,
                webhook_url=settings.yutori_webhook_url,
                output_interval_seconds=interval_seconds,
            )
            action = "updated"
    except YutoriError as exc:
        # Deliberately swallowed: the caller's profile save must still succeed.
        logger.warning("Scout sync failed: %s", exc)
        scout.sync_status = "failed"
        scout.last_sync_error = str(exc)[:1000]
        await scout_repository.save(db, scout)
        return SyncResult(action="failed", scout_id=scout.external_scout_id, error=str(exc))

    scout.query_text = query
    scout.query_hash = query_hash
    scout.sync_status = "active"
    scout.last_sync_error = None
    scout.last_synced_at = datetime.now(UTC)
    await scout_repository.save(db, scout)
    return SyncResult(action=action, scout_id=scout.external_scout_id)


async def get_status(db: AsyncSession) -> Scout | None:
    return await scout_repository.get(db)
