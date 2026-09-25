import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.yutori import (
    YutoriClient,
    YutoriError,
    YutoriForbidden,
    YutoriNotFound,
)
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
        parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        return _reject_epoch_zero(parsed)
    if isinstance(value, datetime):
        value = value if value.tzinfo else value.replace(tzinfo=UTC)
        return _reject_epoch_zero(value)
    return None


def _reject_epoch_zero(value: datetime) -> datetime | None:
    """Yutori signals "nothing scheduled" with epoch 0, which arrives as
    1970-01-01 rather than null. Displayed literally it reads as a real date,
    and compared arithmetically it makes any "is this soon?" test come out true.
    """
    return None if value.year < 1980 else value


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


def fingerprint(api_key: str) -> str:
    """Identify the account behind a key without storing the key twice.

    Yutori exposes no account id, so this is the only way to tell "created by
    the key you have now" from "created by someone else's". One-way and
    truncated: it identifies, it does not reveal.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


async def current_fingerprint(db: AsyncSession) -> str | None:
    api_key = await get_api_key(db, "yutori_api_key")
    return fingerprint(api_key) if api_key else None


async def account_mismatch(db: AsyncSession, scout: Scout | None) -> bool:
    """True when the stored Scout was created by a different API key.

    Two ways to know. The cheap one is the recorded fingerprint. The other is
    that Yutori already told us: a 403 sets `sync_status = "unreachable"`, and
    that is proof, not a guess — it matters because a row created before
    fingerprinting has no fingerprint to compare, and without this the app
    would describe the problem in an error message while showing no way out
    of it.

    A NULL fingerprint on its own is "created before we recorded this", which
    is unknown rather than mismatched — the first successful edit repairs it.
    """
    if scout is None or scout.external_scout_id is None:
        return False
    if scout.sync_status == "unreachable":
        return True
    if not scout.account_fingerprint:
        return False
    current = await current_fingerprint(db)
    return current is not None and current != scout.account_fingerprint


async def forget_remote_scout(db: AsyncSession) -> dict[str, Any]:
    """Drop our reference to a Scout we can no longer administer.

    The escape hatch for a key change: the Scout still exists in whichever
    account created it, and nothing here can stop or delete it — but this app
    should stop pretending it owns it. Local only, and it touches no discovered
    data (ADR 0004: removing a link never removes what it found).
    """
    scout = await scout_repository.get(db)
    if scout is None:
        return {"action": "skipped", "error": "No Scout exists"}

    previous = scout.external_scout_id
    scout.external_scout_id = None
    scout.account_fingerprint = None
    scout.external_status = None
    scout.next_run_at = None
    scout.update_count = None
    scout.run_state = "idle"
    scout.run_kind = None
    scout.run_external_id = None
    scout.sync_status = "pending"
    scout.last_sync_error = None
    await scout_repository.save(db, scout)
    await record_event(
        db,
        "parked",
        scout=scout,
        detail={"action": "forgotten", "external_scout_id": previous},
    )
    return {"action": "forgotten", "external_scout_id": previous}


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

    if await account_mismatch(db, scout):
        # Calling anyway would just earn a 403. Say what is actually wrong.
        return SyncResult(
            action="skipped",
            scout_id=scout.external_scout_id if scout else None,
            error="This Scout was created with a different Yutori API key, so this "
            "key cannot edit it. Forget it to start fresh under the current key.",
        )

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
                # The legacy path re-asserts privacy on every push.
                is_public=False,
            )
            action = "updated"
    except YutoriForbidden:
        # Valid key, someone else's Scout. Recorded so the UI can offer the fix
        # rather than showing a raw 403.
        logger.warning("Scout belongs to another Yutori account")
        scout.sync_status = "unreachable"
        scout.last_sync_error = (
            "This Scout was created with a different Yutori API key, so this key "
            "cannot edit it. Forget it to start fresh under the current key."
        )
        await scout_repository.save(db, scout)
        await record_event(
            db,
            "error",
            scout=scout,
            detail={"stage": "sync", "error": "account_mismatch"},
        )
        return SyncResult(
            action="failed",
            scout_id=scout.external_scout_id,
            error=scout.last_sync_error,
        )
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
    # A successful edit proves this key owns the Scout — which records the owner
    # for a newly created one, and repairs a NULL left by rows that predate
    # fingerprinting.
    scout.account_fingerprint = fingerprint(api_key)
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
    except YutoriForbidden:
        # Valid key, someone else's Scout. Keep the reference so the UI can
        # explain and offer to forget it, but stop claiming to know its state.
        scout.external_status = None
        scout.next_run_at = None
        scout.sync_status = "unreachable"
        scout.last_sync_error = (
            "This Scout was created with a different Yutori API key, so this key "
            "cannot read or edit it. Forget it to start fresh under the current key."
        )
        scout.detail_refreshed_at = datetime.now(UTC)
        return await scout_repository.save(db, scout)
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


async def start_run(
    db: AsyncSession, profile_data: ProfileData, *, mode: str = "research"
) -> RunResult:
    """Start a discovery run now. **This spends money** (~$0.35 per run).

    `mode` picks the primitive (ADR 0004):

    * ``research`` — a one-shot research task. The default, because it actually
      runs when asked, leaves nothing behind at Yutori, and its result can be
      polled back if the webhook is missed.
    * ``scout`` — drive the long-lived Scout instead. Kept for monitors, and
      known not to start a run on its own via restart, so it relies on
      `settings.scout_run_mechanism` (restart, or delete-and-recreate).

    Either way this is the single seam between "the app wants a run" and
    whatever produces one, so the rest of the app never has to know which
    primitive was used.
    """
    scout = await scout_repository.get(db)
    if scout is not None and scout.run_state == "running":
        # The guard that stops a double-click buying two runs. Checked before
        # any outbound call, so a refused attempt costs nothing.
        return RunResult(action="busy", scout_id=scout.external_scout_id)

    if mode == "research":
        return await _start_research_run(db, profile_data, scout)

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
    scout.run_kind = "scout"
    scout.run_external_id = scout.external_scout_id
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
    # Only a next run in the near *future* is evidence a run just began. An
    # absent one (Yutori sends epoch 0) proves nothing either way, so this stays
    # None rather than guessing — the real answer comes from whether
    # update_count moves, which the Scout page now tracks live.
    started_immediately = None
    if next_run_at is not None:
        delta = (next_run_at - started_at).total_seconds()
        started_immediately = -60 <= delta <= 300

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


async def _start_research_run(
    db: AsyncSession, profile_data: ProfileData, scout: Scout | None
) -> RunResult:
    """Launch a one-shot research task (ADR 0004).

    Simpler than the Scout path in every respect: there is no lifecycle to
    manipulate, no interval to neutralise, and nothing to park afterwards. The
    task id is kept so the result can be polled back — which is what makes this
    safe on a scale-to-zero host against a 10-second webhook deadline.
    """
    client = await get_client(db)
    if client is None:
        return RunResult(
            action="skipped",
            error="No usable Yutori API key — it is missing, or was encrypted under a "
            "previous APP_SECRET_KEY and must be re-entered in Settings.",
        )

    query = query_generator.generate(profile_data)
    query_hash = _hash(query)

    if scout is None:
        scout = await scout_repository.create(
            db,
            provider="yutori",
            query_text=query,
            query_hash=query_hash,
            sync_status="pending",
        )

    try:
        # The webhook is registered when we have a public URL, but it is an
        # optimisation here rather than the only way to collect the result.
        response = await client.create_research_task(
            query=query,
            webhook_url=settings.yutori_webhook_url
            if settings.public_base_url
            else None,
        )
    except YutoriError as exc:
        logger.warning("Research task failed to start: %s", exc)
        scout.last_sync_error = str(exc)[:1000]
        await scout_repository.save(db, scout)
        await record_event(
            db,
            "error",
            scout=scout,
            detail={"stage": "research_run", "error": str(exc)},
        )
        return RunResult(action="failed", error=str(exc))

    task_id = str(response.get("task_id") or response.get("id") or "")
    started_at = datetime.now(UTC)
    scout.run_state = "running"
    scout.run_kind = "research_task"
    scout.run_external_id = task_id or None
    scout.run_started_at = started_at
    scout.run_finished_at = None
    scout.run_baseline_update_count = scout.update_count
    scout.query_text = query
    scout.query_hash = query_hash
    scout.last_sync_error = None
    await scout_repository.save(db, scout)

    await record_event(
        db,
        "run_started",
        scout=scout,
        query_text=query,
        query_hash=query_hash,
        cost_usd=settings.yutori_run_cost_usd,
        detail={
            "mechanism": "research_task",
            "task_id": task_id,
            "status": response.get("status"),
            "view_url": response.get("view_url"),
        },
    )
    return RunResult(
        action="started",
        scout_id=task_id or None,
        mechanism="research_task",
        # A research task genuinely starts on creation, which is the whole
        # reason for preferring it — unlike restart, this needs no hedging.
        started_immediately=True,
    )


async def poll_research_run(db: AsyncSession) -> dict[str, Any]:
    """Check an in-flight research task and ingest it once it succeeds.

    This is the research equivalent of `finish_run_if_complete`, and it is the
    reason a research run cannot be lost: the result is fetched rather than
    waited for, so a webhook that never arrives costs nothing.
    """
    scout = await scout_repository.get(db)
    if (
        scout is None
        or scout.run_kind != "research_task"
        or scout.run_state != "running"
        or not scout.run_external_id
    ):
        return {"status": "not_running", "ingested": 0}

    client = await get_client(db)
    if client is None:
        return {"status": "no_key", "ingested": 0}

    try:
        task = await client.get_research_task(scout.run_external_id)
    except YutoriError as exc:
        logger.warning("Polling research task failed: %s", exc)
        return {"status": "error", "error": str(exc), "ingested": 0}

    status = str(task.get("status") or "")
    if status in ("queued", "running"):
        return {"status": status, "ingested": 0}

    ingested = 0
    if status == "succeeded":
        ingested = await _ingest_research_result(db, scout, task)
    else:
        await record_event(
            db,
            "error",
            scout=scout,
            detail={
                "stage": "research_run",
                "status": status,
                # Billing failures surface here rather than as an empty result.
                "rejection_reason": task.get("rejection_reason"),
            },
        )

    scout.run_state = "idle"
    scout.run_finished_at = datetime.now(UTC)
    await scout_repository.save(db, scout)
    return {"status": status, "ingested": ingested}


async def _ingest_research_result(
    db: AsyncSession, scout: Scout, task: dict[str, Any]
) -> int:
    """Feed a finished research task into the existing candidate pipeline.

    Reshaped into the webhook envelope so it lands in `webhook_events` exactly
    as a Scout update would — which means the same idempotency index dedupes a
    polled result against the webhook copy of the same task, and the ingest,
    enrich, rank and digest stages need no knowledge of research tasks at all.
    """
    from app.services import ingest_service  # local import: avoids a cycle

    envelope = update_to_webhook_envelope(
        {
            "id": task.get("task_id") or scout.run_external_id,
            "timestamp": task.get("created_at"),
            "structured_result": task.get("structured_result"),
            "content": task.get("result"),
            "structured_output_status": task.get("structured_output_status"),
        }
    )
    envelope["source"] = "research_task"

    event = await ingest_service.claim_event(db, envelope)
    if event is None:
        # Already stored — the webhook beat the poll to it.
        return 0

    await record_event(
        db,
        "update_received",
        scout=scout,
        external_update_id=str(task.get("task_id") or ""),
        detail={"source": "research_task_poll"},
    )
    return 1


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
        is_public=False,
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
    if scout.run_kind == "research_task":
        # Research runs are finished by `poll_research_run`, which fetches the
        # result. Letting this function also close them out would park a Scout
        # that was never started and record a misleading reason.
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
        payload = update_to_webhook_envelope(update, scout_id=scout.external_scout_id)
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

    # scout_runs lives under `activity`, not at the top level — confirmed
    # against the live response. Read from the top level it is always None,
    # which silently reports zero runs and zero spend.
    activity = usage.get("activity") or {}
    runs = int(activity.get("scout_runs") or usage.get("scout_runs") or 0)
    return UsageSummary(
        period=str(activity.get("period") or period),
        scout_runs=runs,
        estimated_spend_usd=round(runs * settings.yutori_run_cost_usd, 2),
        # Observed to mean "scouts executing right now", not "scouts whose
        # status is active" — it reads 0 for a Scout sitting in `active` with
        # no run in progress, which makes it a useful liveness signal.
        num_active_scouts=int(usage.get("num_active_scouts") or 0),
        active_scout_ids=[str(i) for i in (usage.get("active_scout_ids") or [])],
    )
