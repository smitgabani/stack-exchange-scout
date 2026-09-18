import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.yutori import YutoriClient, YutoriError, YutoriNotFound
from app.models.scout import Scout, ScoutEvent
from app.models.webhook_event import WebhookEvent
from app.repositories import scout_repository
from app.schemas.profile import ProfileData
from app.services import query_generator
from app.services.credentials_service import get_api_key

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 86400
# How long a mirrored copy of Yutori's scout detail is considered fresh. The
# page polls while a run is in flight, and without this every poll would be an
# outbound API call.
DETAIL_TTL_SECONDS = 60


@dataclass
class SyncResult:
    action: str  # created | updated | unchanged | failed | skipped
    scout_id: str | None = None
    error: str | None = None


@dataclass
class RunResult:
    action: str  # started | busy | failed | skipped
    scout_id: str | None = None
    # Which mechanism actually ran: restart, create, or recreate. Recorded
    # because Yutori documents none of their behaviour, so the first real press
    # is the experiment.
    mechanism: str | None = None
    # Read back from Yutori after starting. If this is roughly now, the run has
    # begun; if it is roughly now + interval, restart only resumed the schedule
    # and `scout_run_mechanism` should be switched to "recreate".
    next_run_at: datetime | None = None
    started_immediately: bool | None = None
    error: str | None = None


@dataclass
class ParkResult:
    action: str  # parked | already_parked | failed | skipped
    error: str | None = None


@dataclass
class UsageSummary:
    period: str
    scout_runs: int = 0
    estimated_spend_usd: float = 0.0
    num_active_scouts: int = 0
    active_scout_ids: list[str] = field(default_factory=list)
    error: str | None = None


def _hash(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()


# Anything past this is milliseconds, not seconds — as epoch seconds it would
# be the year 5138, which no Scout timestamp is going to be.
_MILLISECOND_THRESHOLD = 100_000_000_000


def _parse_timestamp(value: Any) -> datetime | None:
    """Yutori returns times as ISO strings on scout detail and as an epoch
    number on updates — in *milliseconds*, observed against the live API
    (1789618345787). Accept either rather than caring which endpoint it came
    from.
    """
    if value in (None, "", 0):
        return None
    if isinstance(value, int | float):
        seconds = value / 1000 if value > _MILLISECOND_THRESHOLD else value
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return None


async def record_event(
    db: AsyncSession,
    event_type: str,
    *,
    scout: Scout | None = None,
    query_text: str | None = None,
    query_hash: str | None = None,
    external_update_id: str | None = None,
    cost_usd: float | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append to the Scout's timeline. Never raises — a missing log line must
    not fail the operation it was describing.
    """
    try:
        db.add(
            ScoutEvent(
                scout_id=scout.id if scout else None,
                type=event_type,
                query_text=query_text,
                query_hash=query_hash,
                external_update_id=external_update_id,
                cost_usd=cost_usd,
                detail=detail,
            )
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - logging must not break the caller
        logger.warning("Failed to record scout event %s: %s", event_type, exc)


async def get_client(db: AsyncSession) -> YutoriClient | None:
    """A client built from the stored key, or None when there isn't a usable one.

    None rather than an exception because every caller here has to degrade
    gracefully: a Yutori outage or an unreadable key must never take down a
    profile save or leave a page unable to render.
    """
    api_key = await get_api_key(db, "yutori_api_key")
    return YutoriClient(api_key) if api_key else None


async def sync(
    db: AsyncSession, profile_data: ProfileData, *, allow_create: bool = False
) -> SyncResult:
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

    if (
        scout is not None
        and scout.query_hash == query_hash
        and scout.sync_status == "active"
    ):
        return SyncResult(action="unchanged", scout_id=scout.external_scout_id)

    if (scout is None or scout.external_scout_id is None) and not allow_create:
        return SyncResult(
            action="skipped",
            error="No Scout exists yet; create one via POST /scout/sync",
        )

    api_key = await get_api_key(db, "yutori_api_key")
    if api_key is None:
        return SyncResult(
            action="skipped",
            error="No usable Yutori API key — it is missing, or was encrypted under a "
            "previous APP_SECRET_KEY and must be re-entered in Settings.",
        )

    if not settings.public_base_url:
        return SyncResult(action="skipped", error="PUBLIC_BASE_URL is not configured")

    client = YutoriClient(api_key)
    interval_seconds = max(profile_data.scout.interval_days, 1) * SECONDS_PER_DAY

    if scout is None:
        scout = await scout_repository.create(
            db,
            provider="yutori",
            query_text=query,
            query_hash=query_hash,
            sync_status="pending",
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
        return SyncResult(
            action="failed", scout_id=scout.external_scout_id, error=str(exc)
        )

    scout.query_text = query
    scout.query_hash = query_hash
    scout.sync_status = "active"
    scout.last_sync_error = None
    scout.last_synced_at = datetime.now(UTC)
    await scout_repository.save(db, scout)
    # The full query is logged, not a diff, so that reading the timeline later
    # shows what was actually being searched at the time — which is how a change
    # in results gets traced back to the topic edit that caused it.
    await record_event(
        db,
        "query_synced",
        scout=scout,
        query_text=query,
        query_hash=query_hash,
        detail={"action": action},
    )
    return SyncResult(action=action, scout_id=scout.external_scout_id)


async def get_status(db: AsyncSession) -> Scout | None:
    return await scout_repository.get(db)


async def refresh_detail(db: AsyncSession, *, force: bool = False) -> Scout | None:
    """Mirror Yutori's view of the Scout onto our row.

    Rate-limited by `detail_refreshed_at`: the Scout page polls while a run is
    in flight, and every poll should not become an outbound call.
    """
    scout = await scout_repository.get(db)
    if scout is None or scout.external_scout_id is None:
        return scout

    fresh_until = (
        scout.detail_refreshed_at + timedelta(seconds=DETAIL_TTL_SECONDS)
        if scout.detail_refreshed_at
        else None
    )
    if not force and fresh_until and datetime.now(UTC) < fresh_until:
        return scout

    client = await get_client(db)
    if client is None:
        return scout

    try:
        detail = await client.get_scout(scout.external_scout_id)
    except YutoriNotFound:
        # Someone deleted it at Yutori's end. Forget the id so the next run
        # creates a fresh Scout rather than restarting one that isn't there.
        scout.external_scout_id = None
        scout.external_status = None
        scout.sync_status = "pending"
        scout.last_sync_error = "Scout no longer exists at Yutori"
        scout.detail_refreshed_at = datetime.now(UTC)
        return await scout_repository.save(db, scout)
    except YutoriError as exc:
        logger.warning("Scout detail refresh failed: %s", exc)
        return scout

    scout.external_status = detail.get("status")
    scout.next_run_at = _parse_timestamp(detail.get("next_run_timestamp"))
    scout.update_count = detail.get("update_count")
    scout.last_update_at = _parse_timestamp(detail.get("last_update_timestamp"))
    scout.rejection_reason = detail.get("rejection_reason")
    scout.detail_refreshed_at = datetime.now(UTC)
    return await scout_repository.save(db, scout)


async def start_run(db: AsyncSession, profile_data: ProfileData) -> RunResult:
    """Start a Scout run now. **This spends money** (~$0.35 per run).

    The single seam between "the app wants a run" and however Yutori is
    persuaded to produce one. Yutori has no run endpoint, so the mechanism is
    either restart (default: keeps the Scout's id, query and change-baseline) or
    delete-and-recreate, chosen by `settings.scout_run_mechanism`.

    Because Yutori documents neither behaviour, the result reports what was
    observed — `next_run_at` read back afterwards tells us whether a run
    actually started or the schedule merely resumed.
    """
    scout = await scout_repository.get(db)
    if scout is not None and scout.run_state == "running":
        # The guard that stops a double-click buying two runs. Checked before
        # any outbound call, so a refused attempt costs nothing.
        return RunResult(action="busy", scout_id=scout.external_scout_id)

    # Re-sync first so the run searches for current topics rather than whatever
    # the query was when the Scout was last touched.
    await sync(db, profile_data, allow_create=False)
    scout = await scout_repository.get(db)

    client = await get_client(db)
    if client is None:
        return RunResult(
            action="skipped",
            error="No usable Yutori API key — it is missing, or was encrypted under a "
            "previous APP_SECRET_KEY and must be re-entered in Settings.",
        )
    if not settings.public_base_url:
        return RunResult(action="skipped", error="PUBLIC_BASE_URL is not configured")

    query = query_generator.generate(profile_data)
    query_hash = _hash(query)
    baseline = scout.update_count if scout else None

    try:
        scout, mechanism = await _begin_run(db, client, scout, query, query_hash)
    except YutoriError as exc:
        logger.warning("Scout run failed to start: %s", exc)
        if scout is not None:
            scout.sync_status = "failed"
            scout.last_sync_error = str(exc)[:1000]
            await scout_repository.save(db, scout)
        await record_event(
            db, "error", scout=scout, detail={"stage": "start_run", "error": str(exc)}
        )
        return RunResult(action="failed", error=str(exc))

    started_at = datetime.now(UTC)
    scout.run_state = "running"
    scout.run_started_at = started_at
    scout.run_finished_at = None
    scout.run_baseline_update_count = baseline
    scout.query_text = query
    scout.query_hash = query_hash
    scout.sync_status = "active"
    scout.last_sync_error = None
    scout.last_synced_at = started_at
    await scout_repository.save(db, scout)

    # Read Yutori's own view back. This is the experiment: next_run_at ≈ now
    # means the run has begun; next_run_at ≈ now + interval means restart only
    # resumed the schedule and the mechanism should be switched to "recreate".
    scout = await refresh_detail(db, force=True) or scout
    next_run_at = scout.next_run_at
    started_immediately = None
    if next_run_at is not None:
        started_immediately = (next_run_at - started_at).total_seconds() < 300

    await record_event(
        db,
        "run_started",
        scout=scout,
        query_text=query,
        query_hash=query_hash,
        cost_usd=settings.yutori_run_cost_usd,
        detail={
            "mechanism": mechanism,
            "next_run_at": next_run_at.isoformat() if next_run_at else None,
            "started_immediately": started_immediately,
        },
    )
    return RunResult(
        action="started",
        scout_id=scout.external_scout_id,
        mechanism=mechanism,
        next_run_at=next_run_at,
        started_immediately=started_immediately,
    )


async def _begin_run(
    db: AsyncSession,
    client: YutoriClient,
    scout: Scout | None,
    query: str,
    query_hash: str,
) -> tuple[Scout, str]:
    """Persuade Yutori to run, and return the scout row plus which way it was done.

    The interval is set deliberately long: if parking later fails, this is what
    stops the Scout billing again before anyone notices.
    """
    interval = settings.scout_run_interval_seconds

    if scout is None:
        scout = await scout_repository.create(
            db,
            provider="yutori",
            query_text=query,
            query_hash=query_hash,
            sync_status="pending",
        )

    if scout.external_scout_id is None:
        response = await client.create_scout(
            query=query,
            webhook_url=settings.yutori_webhook_url,
            output_interval_seconds=interval,
        )
        scout.external_scout_id = str(response.get("id"))
        return scout, "create"

    if settings.scout_run_mechanism == "recreate":
        # The fallback: delete and create, which definitely starts a run,
        # at the cost of the Scout's id and its change-baseline.
        try:
            await client.delete_scout(scout.external_scout_id)
        except YutoriNotFound:
            pass
        response = await client.create_scout(
            query=query,
            webhook_url=settings.yutori_webhook_url,
            output_interval_seconds=interval,
        )
        scout.external_scout_id = str(response.get("id"))
        return scout, "recreate"

    # Default: make the query and interval current, stop the Scout, then
    # restart it.
    #
    # The stop is not optional. Yutori rejects restart on a live Scout with
    # 400 "Scout is not completed" — restart is the counterpart of done, not a
    # general "start it now". done → restart is therefore the whole mechanism,
    # and it is also why the parked posture and this button fit together: a
    # Scout that is already parked is exactly what restart expects.
    await client.update_scout(
        scout.external_scout_id,
        query=query,
        webhook_url=settings.yutori_webhook_url,
        output_interval_seconds=interval,
    )
    try:
        await client.mark_done(scout.external_scout_id)
    except YutoriNotFound:
        raise
    except YutoriError as exc:
        # Already done is the state we want, and Yutori may object to being
        # told twice. Let restart be the step that decides success.
        logger.info("mark_done before restart was rejected (continuing): %s", exc)
    await client.restart(scout.external_scout_id)
    return scout, "restart"


async def park(db: AsyncSession) -> ParkResult:
    """Stop the Scout running. Free, idempotent, and reversible.

    This is what keeps the on-demand posture honest: between runs the Scout sits
    in `done` where it cannot bill.
    """
    scout = await scout_repository.get(db)
    if scout is None or scout.external_scout_id is None:
        return ParkResult(action="skipped", error="No Scout exists")

    client = await get_client(db)
    if client is None:
        return ParkResult(action="skipped", error="No usable Yutori API key")

    try:
        await client.mark_done(scout.external_scout_id)
    except YutoriNotFound:
        # Already gone at Yutori's end, which is the state we wanted.
        pass
    except YutoriError as exc:
        logger.warning("Scout park failed: %s", exc)
        scout.last_sync_error = str(exc)[:1000]
        await scout_repository.save(db, scout)
        await record_event(
            db, "error", scout=scout, detail={"stage": "park", "error": str(exc)}
        )
        return ParkResult(action="failed", error=str(exc))

    scout.external_status = "done"
    scout.next_run_at = None
    scout.detail_refreshed_at = datetime.now(UTC)
    await scout_repository.save(db, scout)
    await record_event(db, "parked", scout=scout)
    return ParkResult(action="parked")


async def finish_run_if_complete(db: AsyncSession) -> bool:
    """Close out a finished run and park the Scout. Idempotent.

    A run is finished when any of three things is true:
      * a webhook event arrived after the run started;
      * Yutori's `update_count` moved past the baseline we recorded — which
        catches a run whose webhook was lost entirely;
      * the run is older than the timeout, meaning it found nothing and will
        never send a webhook at all.

    Deliberately not called from the webhook handler: ADR 0003 decision 1 keeps
    that handler to verify-persist-acknowledge, because Fly's 5s kill_timeout
    makes an extra outbound call there unsafe. The long run interval is what
    makes a late park harmless.
    """
    scout = await scout_repository.get(db)
    if scout is None or scout.run_state != "running" or scout.run_started_at is None:
        return False

    received = await db.scalar(
        select(func.count())
        .select_from(WebhookEvent)
        .where(WebhookEvent.received_at > scout.run_started_at)
    )
    reason = "webhook_received" if received else None

    if reason is None:
        scout = await refresh_detail(db) or scout
        baseline = scout.run_baseline_update_count
        if scout.update_count is not None and (
            baseline is None or scout.update_count > baseline
        ):
            reason = "update_count_increased"

    if reason is None:
        age = (datetime.now(UTC) - scout.run_started_at).total_seconds()
        if age > settings.scout_run_timeout_seconds:
            reason = "timed_out"

    if reason is None:
        return False

    scout.run_state = "idle"
    scout.run_finished_at = datetime.now(UTC)
    await scout_repository.save(db, scout)
    if reason != "timed_out":
        # Only log an update when one actually arrived — a timed-out run
        # produced nothing, and saying otherwise would make the timeline lie.
        await record_event(
            db, "update_received", scout=scout, detail={"reason": reason}
        )
    await park(db)
    if reason == "timed_out":
        await record_event(
            db,
            "error",
            scout=scout,
            detail={"stage": "run", "error": "timed out with no update"},
        )
    return True


def update_to_webhook_envelope(update: dict[str, Any]) -> dict[str, Any]:
    """Shape a `DeveloperUpdate` from GET /updates like a webhook body.

    The updates API has no `report_content` — it carries `structured_result`
    (our registered output_schema, when the model complied) and `content`
    (prose). Mapping here rather than teaching the parser a second shape means
    webhook parsing is untouched, and both paths still key on `update.id`, so
    the existing (provider, event_id) unique index dedupes across them.
    """
    structured = update.get("structured_result")
    return {
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


async def pull_missed_updates(
    db: AsyncSession, *, page_size: int = 20
) -> dict[str, Any]:
    """Fetch updates Yutori produced that never reached our webhook.

    Yutori tries 3 times over ~30 seconds and never redelivers, so on a
    scale-to-zero host a paid run can be lost for good. This is the recovery
    path: every update is still readable afterwards.
    """
    scout = await scout_repository.get(db)
    if scout is None or scout.external_scout_id is None:
        return {
            "fetched": 0,
            "ingested": 0,
            "duplicates": 0,
            "error": "No Scout exists",
        }

    client = await get_client(db)
    if client is None:
        return {
            "fetched": 0,
            "ingested": 0,
            "duplicates": 0,
            "error": "No usable Yutori API key",
        }

    from app.services import ingest_service  # local import: avoids a cycle

    try:
        response = await client.get_updates(
            scout.external_scout_id, page_size=page_size
        )
    except YutoriError as exc:
        logger.warning("Fetching scout updates failed: %s", exc)
        return {"fetched": 0, "ingested": 0, "duplicates": 0, "error": str(exc)}

    updates = response.get("updates") or []
    ingested = 0
    for update in updates:
        payload = update_to_webhook_envelope(update)
        event = await ingest_service.claim_event(db, payload)
        if event is not None:
            ingested += 1
            await record_event(
                db,
                "update_received",
                scout=scout,
                external_update_id=str(update.get("id")),
                detail={"source": "pull"},
            )

    return {
        "fetched": len(updates),
        "ingested": ingested,
        "duplicates": len(updates) - ingested,
        "error": None,
    }


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

    runs = int(usage.get("scout_runs") or 0)
    return UsageSummary(
        period=period,
        scout_runs=runs,
        estimated_spend_usd=round(runs * settings.yutori_run_cost_usd, 2),
        num_active_scouts=int(usage.get("num_active_scouts") or 0),
        active_scout_ids=[str(i) for i in (usage.get("active_scout_ids") or [])],
    )
