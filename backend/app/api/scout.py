from datetime import UTC, datetime
from typing import Any

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
from app.services.task_settings import mask_webhook_url

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

    # True when the stored Scout was created under a different API key, so no
    # edit to it can succeed. Surfaced as a state rather than left to fail as a
    # 403 at the moment someone presses something.
    account_mismatch: bool = False

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


def _status_from(scout: Any, *, mismatch: bool = False) -> ScoutStatus:
    if scout is None:
        return ScoutStatus(configured=False)
    return ScoutStatus(
        account_mismatch=mismatch,
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
    # A research run finishes by being polled, not by waiting for a webhook —
    # so the same request that renders the status is what collects the result.
    await scout_service.poll_research_run(db)
    await scout_service.refresh_detail(db)
    await scout_service.finish_run_if_complete(db)
    scout = await scout_service.get_status(db)
    return _status_from(scout, mismatch=await scout_service.account_mismatch(db, scout))


@router.post(
    "/scout/sync",
    response_model=SyncResponse,
    dependencies=[Depends(require_yutori_key)],
)
async def sync_scout(db: AsyncSession = Depends(get_db)) -> SyncResponse:
    """Push the current query to an existing Scout (prd.md §24). Free.

    `allow_create=False` deliberately. Creating a Scout starts a billable run,
    and this endpoint is reached from a plain "Re-sync" link with no
    confirmation — so with no Scout present it now reports that instead of
    quietly spending $0.35. Creating one is what the Run button is for, behind
    a dialog that names the price.
    """
    profile = await get_or_create_profile(db)
    result = await scout_service.sync(
        db, ProfileData.model_validate(profile.data), allow_create=False
    )
    return SyncResponse(
        action=result.action, scout_id=result.scout_id, error=result.error
    )


@router.post(
    "/scout/run", response_model=RunResponse, dependencies=[Depends(require_yutori_key)]
)
async def run_scout(
    mode: str = "research", db: AsyncSession = Depends(get_db)
) -> RunResponse:
    """Start a discovery run now. **Billable** — roughly $0.35 per run.

    `mode` is `research` (default: a one-shot research task, which actually
    runs when asked) or `scout` (drive the long-lived monitor). See ADR 0004.

    409 when a run is already in flight, which is what stops an impatient double
    press from buying two runs. The guard is checked before any outbound call.
    """
    if mode not in ("research", "scout"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="mode must be 'research' or 'scout'",
        )
    profile = await get_or_create_profile(db)
    result = await scout_service.start_run(
        db, ProfileData.model_validate(profile.data), mode=mode
    )

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


@router.post("/scout/forget")
async def forget_scout(db: AsyncSession = Depends(get_db)) -> dict:
    """Drop the reference to a Scout this key cannot administer. Free, local.

    The escape hatch after changing to a key from another account: Yutori
    answers `403 "Only the creator of a scout can edit it"`, and nothing here
    can fix that. Forgetting clears the link so the next run starts fresh —
    and touches no discovered questions.
    """
    return await scout_service.forget_remote_scout(db)


@router.post("/scout/pull")
async def pull_scout_updates(db: AsyncSession = Depends(get_db)) -> dict:
    """Ingest updates Yutori produced that never reached our webhook. Free."""
    return await scout_service.pull_missed_updates(db)


@router.get("/scout/panel")
async def scout_panel(include_raw: bool = False, db: AsyncSession = Depends(get_db)) -> dict:
    """Everything the Scout page shows, in one call.

    Deliberately one endpoint rather than six: the page is a single view of one
    thing, and six round trips through the Vercel proxy to a scale-to-zero
    backend would each pay the same wake-up cost.
    """
    await scout_service.poll_research_run(db)
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

    mismatch = await scout_service.account_mismatch(db, scout)
    return {
        "status": _status_from(scout, mismatch=mismatch).model_dump(mode="json"),
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
        #
        # Off by default: this is the largest part of the response, and every
        # byte crosses a Vercel function on the way to the browser. Loaded
        # only when someone opens the debugging section.
        "raw": {
            "scout_detail": _redact(detail),
            "usage": usage_raw,
            "latest_update": _redact(updates[0]) if updates else None,
            # The in-flight research task verbatim. Yutori's own dashboard can
            # show a task as finished while our poll still reports running, and
            # this is the only way to see which of the two is wrong.
            "research_task": await _raw_research_task(db, scout),
        }
        if include_raw
        else None,
    }


async def _raw_research_task(db: AsyncSession, scout: Any) -> dict[str, Any] | None:
    if scout is None or scout.run_kind != "research_task" or not scout.run_external_id:
        return None
    client = await scout_service.get_client(db)
    if client is None:
        return None
    try:
        task = await client.get_research_task(scout.run_external_id)
    except Exception as exc:  # noqa: BLE001 - diagnostics must not break the page
        return {"error": str(exc)[:300]}
    # Trimmed: the findings themselves can be very long, and the shape is what
    # is being diagnosed here, not the content.
    return {
        "task_id": task.get("task_id"),
        "status": task.get("status"),
        "structured_output_status": task.get("structured_output_status"),
        "has_structured_result": bool(task.get("structured_result")),
        "structured_result_keys": sorted((task.get("structured_result") or {}).keys())
        if isinstance(task.get("structured_result"), dict)
        else None,
        "question_count": len((task.get("structured_result") or {}).get("questions") or [])
        if isinstance(task.get("structured_result"), dict)
        else None,
        "result_chars": len(task.get("result") or ""),
        "rejection_reason": task.get("rejection_reason"),
        "created_at": task.get("created_at"),
        "update_count": len(task.get("updates") or []),
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
        "run_kind": scout.run_kind,
        "run_external_id": scout.run_external_id,
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

    # Yutori's own list, not usage.active_scout_ids — that counts runs
    # executing right now, so it reports nothing for an idle Scout that is
    # nonetheless alive and will bill again on its interval.
    account_scouts: list[dict[str, Any]] = []
    listing_error: str | None = None
    client = await scout_service.get_client(db)
    if client is not None:
        try:
            listing = await client.list_scouts()
            for item in listing.get("scouts") or listing.get("items") or []:
                account_scouts.append(
                    {
                        "id": str(item.get("id")),
                        "status": item.get("status"),
                        "created_at": item.get("created_at"),
                        "update_count": item.get("update_count"),
                        "is_ours": str(item.get("id")) == ours,
                    }
                )
        except Exception as exc:  # noqa: BLE001 - the page must still render
            listing_error = str(exc)[:300]

    return {
        "events_awaiting_ingest": pending or 0,
        # Anything alive on the account this app is not tracking. An untracked
        # Scout bills on its own interval and nobody is watching it.
        "orphan_scout_ids": [
            item["id"]
            for item in account_scouts
            if not item["is_ours"] and item["status"] in ("active", "paused")
        ],
        "account_scouts": account_scouts,
        "account_scouts_error": listing_error,
        "runs_executing_now": usage.num_active_scouts,
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
