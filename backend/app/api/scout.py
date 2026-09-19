from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_yutori_key
from app.core.config import settings
from app.core.db import get_db
from app.models.question import Question
from app.models.scout import ScoutEvent
from app.models.webhook_event import WebhookEvent
from app.schemas.profile import ProfileData
from app.services import ingest_service, query_generator, scout_service
from app.services.profile_service import get_or_create_profile

router = APIRouter(tags=["scout"])


class ScoutStatus(BaseModel):
    configured: bool
    external_scout_id: str | None = None
    sync_status: str | None = None
    last_synced_at: datetime | None = None
    last_sync_error: str | None = None

    # On-demand run state.
    run_state: str = "idle"
    run_started_at: datetime | None = None
    run_finished_at: datetime | None = None

    # Yutori's view, mirrored.
    external_status: str | None = None
    next_run_at: datetime | None = None
    update_count: int | None = None
    last_update_at: datetime | None = None
    rejection_reason: str | None = None

    # So the confirmation dialog's figure comes from config, not hardcoded copy.
    run_cost_usd: float = settings.yutori_run_cost_usd


class RunResponse(BaseModel):
    action: str
    scout_id: str | None = None
    mechanism: str | None = None
    next_run_at: datetime | None = None
    started_immediately: bool | None = None
    error: str | None = None


class SyncResponse(BaseModel):
    action: str
    scout_id: str | None = None
    error: str | None = None


def mask_webhook_url(url: str | None) -> str | None:
    """Strip the query string from a webhook URL before it leaves the backend.

    Yutori echoes back the `webhook_url` we registered, and ours carries
    YUTORI_WEBHOOK_SECRET as a query parameter — that secret is the only thing
    authenticating inbound candidate data, so it must never reach the browser.
    """
    if not url:
        return None
    parts = urlsplit(url)
    if not parts.scheme:
        return "(configured)"
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _status_from(scout: Any) -> ScoutStatus:
    if scout is None:
        return ScoutStatus(configured=False)
    return ScoutStatus(
        configured=scout.external_scout_id is not None,
        external_scout_id=scout.external_scout_id,
        sync_status=scout.sync_status,
        last_synced_at=scout.last_synced_at,
        last_sync_error=scout.last_sync_error,
        run_state=scout.run_state,
        run_started_at=scout.run_started_at,
        run_finished_at=scout.run_finished_at,
        external_status=scout.external_status,
        next_run_at=scout.next_run_at,
        update_count=scout.update_count,
        last_update_at=scout.last_update_at,
        rejection_reason=scout.rejection_reason,
    )


@router.get("/scout", response_model=ScoutStatus)
async def get_scout(db: AsyncSession = Depends(get_db)) -> ScoutStatus:
    """Current Scout state, refreshed from Yutori at most once a minute.

    Also finalizes a completed run: the frontend polls this while a run is in
    flight, which makes it the most reliable place for the Scout to get parked
    without waiting for someone to press Ingest.
    """
    await scout_service.refresh_detail(db)
    await scout_service.finish_run_if_complete(db)
    return _status_from(await scout_service.get_status(db))


@router.post(
    "/scout/sync",
    response_model=SyncResponse,
    dependencies=[Depends(require_yutori_key)],
)
async def sync_scout(db: AsyncSession = Depends(get_db)) -> SyncResponse:
    """Manual re-trigger of the same sync the profile save performs (prd.md §24)."""
    profile = await get_or_create_profile(db)
    result = await scout_service.sync(
        db, ProfileData.model_validate(profile.data), allow_create=True
    )
    return SyncResponse(
        action=result.action, scout_id=result.scout_id, error=result.error
    )


@router.post(
    "/scout/run", response_model=RunResponse, dependencies=[Depends(require_yutori_key)]
)
async def run_scout(db: AsyncSession = Depends(get_db)) -> RunResponse:
    """Start a Scout run now. **Billable** — roughly $0.35 per run.

    409 when a run is already in flight, which is what stops an impatient double
    press from buying two runs. The guard is checked before any outbound call.
    """
    profile = await get_or_create_profile(db)
    result = await scout_service.start_run(db, ProfileData.model_validate(profile.data))

    if result.action == "busy":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A Scout run is already in flight",
        )
    if result.action in ("failed", "skipped"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.error or "Could not start a Scout run",
        )

    return RunResponse(
        action=result.action,
        scout_id=result.scout_id,
        mechanism=result.mechanism,
        next_run_at=result.next_run_at,
        started_immediately=result.started_immediately,
    )


@router.post("/scout/park")
async def park_scout(db: AsyncSession = Depends(get_db)) -> dict:
    """Stop the Scout running. Free and idempotent."""
    result = await scout_service.park(db)
    return {"action": result.action, "error": result.error}


@router.post("/scout/pull")
async def pull_scout_updates(db: AsyncSession = Depends(get_db)) -> dict:
    """Ingest updates Yutori produced that never reached our webhook. Free."""
    return await scout_service.pull_missed_updates(db)


@router.get("/scout/panel")
async def scout_panel(db: AsyncSession = Depends(get_db)) -> dict:
    """Everything the Scout page shows, in one call.

    Deliberately one endpoint rather than six: the page is a single view of one
    thing, and six round trips through the Vercel proxy to a scale-to-zero
    backend would each pay the same wake-up cost.
    """
    await scout_service.refresh_detail(db)
    await scout_service.finish_run_if_complete(db)
    scout = await scout_service.get_status(db)

    profile = await get_or_create_profile(db)
    usage = await scout_service.usage_summary(db)

    detail: dict[str, Any] = {}
    updates: list[dict[str, Any]] = []
    usage_raw: dict[str, Any] = {}
    if scout is not None and scout.external_scout_id is not None:
        client = await scout_service.get_client(db)
        if client is not None:
            try:
                detail = await client.get_scout(scout.external_scout_id)
            except Exception:  # noqa: BLE001 - the page must render without Yutori
                detail = {}
            try:
                response = await client.get_updates(
                    scout.external_scout_id, page_size=20
                )
                updates = response.get("updates") or []
            except Exception:  # noqa: BLE001
                updates = []
            try:
                usage_raw = await client.get_usage("30d")
            except Exception:  # noqa: BLE001
                usage_raw = {}

    # Per-update yield: how many questions each stored event actually produced,
    # which is what answers "did that $0.35 buy anything".
    yields = await _update_yields(db)
    received_ids = set(yields)

    # The stored query is whatever was last pushed to Yutori, which is not
    # necessarily what the current topics would produce — edit topics while
    # Yutori is unreachable and the two silently diverge. Saying so is the
    # difference between "the Scout found nothing" and "the Scout is looking
    # for the wrong thing".
    current_query = query_generator.generate(ProfileData.model_validate(profile.data))
    query_is_current = bool(scout and scout.query_text == current_query)

    return {
        "status": _status_from(scout).model_dump(mode="json"),
        "query_text": scout.query_text if scout else None,
        "current_query_text": None if query_is_current else current_query,
        "query_is_current": query_is_current,
        "query_synced_at": scout.last_synced_at.isoformat() if scout and scout.last_synced_at else None,
        "profile_version": profile.version,
        "configuration": {
            "output_interval": detail.get("output_interval"),
            "user_timezone": detail.get("user_timezone"),
            "webhook_format": detail.get("webhook_format"),
            "webhook_url": mask_webhook_url(detail.get("webhook_url")),
            "is_public": detail.get("is_public"),
            "created_at": detail.get("created_at"),
            "display_name": detail.get("display_name"),
            "has_output_schema": bool(detail.get("output_schema")),
            "run_mechanism": settings.scout_run_mechanism,
        },
        "usage": {
            "period": usage.period,
            "scout_runs": usage.scout_runs,
            "estimated_spend_usd": usage.estimated_spend_usd,
            "num_active_scouts": usage.num_active_scouts,
            "active_scout_ids": usage.active_scout_ids,
            "run_cost_usd": settings.yutori_run_cost_usd,
            "error": usage.error,
        },
        "updates": [
            {
                "id": str(update.get("id")),
                "timestamp": update.get("timestamp"),
                "structured_output_status": update.get("structured_output_status"),
                "pages_read": (update.get("stats") or {}).get("num_webpages_read"),
                "citations": len(update.get("citations") or []),
                # False means we paid for this update and never received it —
                # the case `POST /scout/pull` exists to repair.
                "received": str(update.get("id")) in received_ids,
                **yields.get(str(update.get("id")), {}),
            }
            for update in updates
        ],
        "events": await _recent_events(db),
        "health": await _health(db, scout, usage),
        "run_diagnostics": await _run_diagnostics(db, scout),
        # Yutori's responses verbatim. Their documentation says nothing about
        # what restart does, whether next_run_timestamp is meaningful, or why
        # /v1/usage disagrees with scout detail — so the raw payloads are the
        # only way to reason about it.
        "raw": {
            "scout_detail": _redact(detail),
            "usage": usage_raw,
            "latest_update": _redact(updates[0]) if updates else None,
        },
    }


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip anything carrying the webhook secret before it reaches a browser."""
    safe = dict(payload)
    if "webhook_url" in safe:
        safe["webhook_url"] = mask_webhook_url(safe.get("webhook_url"))
    # Update bodies can be very large; the page shows shape, not content.
    if "content" in safe and isinstance(safe["content"], str):
        safe["content"] = f"<{len(safe['content'])} chars>"
    return safe


async def _run_diagnostics(db: AsyncSession, scout: Any) -> dict[str, Any]:
    """Evidence about the run in flight, rather than a claim about it.

    Whether a Scout run actually started is not something Yutori will tell us —
    `next_run_timestamp` comes back as epoch 0 — so the honest answer is to show
    what has and has not changed since the run began and let it speak.
    """
    if scout is None or scout.run_started_at is None:
        return {"run_state": "idle", "has_run_record": False}

    now = datetime.now(UTC)
    elapsed = (now - scout.run_started_at).total_seconds()
    webhooks_since = await db.scalar(
        select(func.count())
        .select_from(WebhookEvent)
        .where(WebhookEvent.received_at > scout.run_started_at)
    )
    baseline = scout.run_baseline_update_count
    current = scout.update_count
    return {
        "run_state": scout.run_state,
        "has_run_record": True,
        "run_started_at": scout.run_started_at.isoformat(),
        "run_finished_at": scout.run_finished_at.isoformat() if scout.run_finished_at else None,
        "elapsed_seconds": int(elapsed),
        "timeout_seconds": settings.scout_run_timeout_seconds,
        "baseline_update_count": baseline,
        "current_update_count": current,
        # The single most informative line on the page: if this stays false for
        # the whole run window, whatever we did to Yutori did not cause a run.
        "update_count_moved": bool(
            current is not None and baseline is not None and current > baseline
        ),
        "webhooks_since_run_started": webhooks_since or 0,
        "run_mechanism": settings.scout_run_mechanism,
        "run_interval_seconds": settings.scout_run_interval_seconds,
    }


async def _update_yields(db: AsyncSession) -> dict[str, dict[str, int]]:
    """For each stored webhook event, how many questions it produced and how
    many of them survived to be worth reading.
    """
    rows = (
        await db.execute(
            select(
                WebhookEvent.event_id,
                func.count(Question.id),
                func.count(Question.id).filter(Question.status == "candidate"),
                # A subset of candidates, not of everything — a rejected
                # question scoring above the bar was never readable, so
                # counting it here would overstate what the run bought.
                func.count(Question.id).filter(
                    Question.status == "candidate",
                    Question.candidate_score >= settings.digest_min_score,
                ),
            )
            .select_from(WebhookEvent)
            .outerjoin(Question, Question.source_event_id == WebhookEvent.id)
            .group_by(WebhookEvent.event_id)
        )
    ).all()
    return {
        event_id: {
            "questions": total,
            "candidates": candidates,
            "above_threshold": scored,
        }
        for event_id, total, candidates, scored in rows
    }


async def _recent_events(db: AsyncSession, limit: int = 30) -> list[dict[str, Any]]:
    events = (
        await db.scalars(
            select(ScoutEvent).order_by(ScoutEvent.created_at.desc()).limit(limit)
        )
    ).all()
    return [
        {
            "id": str(event.id),
            "type": event.type,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "query_text": event.query_text,
            "cost_usd": float(event.cost_usd) if event.cost_usd is not None else None,
            "detail": event.detail,
        }
        for event in events
    ]


async def _health(
    db: AsyncSession, scout: Any, usage: scout_service.UsageSummary
) -> dict[str, Any]:
    pending = await db.scalar(
        select(func.count())
        .select_from(WebhookEvent)
        .where(WebhookEvent.status == "received")
    )
    ours = scout.external_scout_id if scout else None
    # Any active Scout that isn't ours is one nobody is tracking — and an
    # untracked Scout bills on its own interval forever.
    orphans = [i for i in usage.active_scout_ids if ours is None or i != ours]
    return {
        "events_awaiting_ingest": pending or 0,
        "orphan_scout_ids": orphans,
        "last_sync_error": scout.last_sync_error if scout else None,
    }


@router.post("/candidates/ingest")
async def ingest_candidates(db: AsyncSession = Depends(get_db)) -> dict:
    """Turn stored webhook events into question rows.

    Separate from the webhook itself so ingestion is re-runnable and survives
    the machine being stopped mid-flight; M11 will call the same stage on a
    schedule instead of by hand.
    """
    result = await ingest_service.ingest_pending(db)
    # A run whose update has just been ingested is definitively over, so this is
    # the second place the Scout gets parked.
    await scout_service.finish_run_if_complete(db)
    return result.as_dict()
