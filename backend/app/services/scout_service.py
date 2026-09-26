import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.yutori import YutoriClient, YutoriError
from app.services.credentials_service import get_api_key

logger = logging.getLogger(__name__)


@dataclass
class UsageSummary:
    period: str
    scout_runs: int = 0
    error: str | None = None


def fingerprint(api_key: str) -> str:
    """Identify the account behind a key without storing the key twice.

    Yutori exposes no account id, so this is the only way to tell "created by
    the key you have now" from "created by someone else's". One-way and
    truncated: it identifies, it does not reveal.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


async def get_client(db: AsyncSession) -> YutoriClient | None:
    """A client built from the stored key, or None when there isn't a usable one.

    None rather than an exception because every caller here has to degrade
    gracefully: a Yutori outage or an unreadable key must never take down a
    profile save or leave a page unable to render.
    """
    api_key = await get_api_key(db, "yutori_api_key")
    return YutoriClient(api_key) if api_key else None


def update_to_webhook_envelope(
    update: dict[str, Any], *, scout_id: str | None = None
) -> dict[str, Any]:
    """Shape a `DeveloperUpdate` from GET /updates like a webhook body.

    The updates API has no `report_content` — it carries `structured_result`
    (our registered output_schema, when the model complied) and `content`
    (prose). Mapping here rather than teaching the parser a second shape means
    webhook parsing is untouched, and both paths still key on `update.id`, so
    the existing (provider, event_id) unique index dedupes across them.

    `scout_id` is carried as `scout.id`, where a real webhook puts it, so a
    pulled update is attributed to its monitor exactly like a delivered one.
    """
    structured = update.get("structured_result")
    envelope: dict[str, Any] = {
        "event_type": "scout.update",
        "update": {
            "id": update.get("id"),
            "timestamp": update.get("timestamp"),
            "report_content": structured if structured else update.get("content"),
            "structured_output_status": update.get("structured_output_status"),
            "citations": update.get("citations") or [],
            "stats": update.get("stats"),
        },
        "source": "pull",
    }
    if scout_id:
        envelope["scout"] = {"id": scout_id}
    return envelope


async def usage_summary(db: AsyncSession, *, period: str = "30d") -> UsageSummary:
    """Spend and activity, from Yutori's own run count rather than ours.

    Their count includes runs we failed to record, which is exactly the case
    where our own number would be wrong and reassuring.
    """
    client = await get_client(db)
    if client is None:
        return UsageSummary(period=period, error="No usable Yutori API key")

    try:
        usage = await client.get_usage(period)
    except YutoriError as exc:
        logger.warning("Fetching usage failed: %s", exc)
        return UsageSummary(period=period, error=str(exc))

    # scout_runs lives under `activity`, not at the top level — confirmed
    # against the live response. Read from the top level it is always None,
    # which silently reports zero runs and zero spend.
    activity = usage.get("activity") or {}
    return UsageSummary(
        period=str(activity.get("period") or period),
        scout_runs=int(activity.get("scout_runs") or usage.get("scout_runs") or 0),
    )
