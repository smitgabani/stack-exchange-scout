"""Saved scout definitions, and running them (ADR 0004).

A definition is local and free. Running one is the only thing that costs, and
every run is recorded against the definition and the account that paid for it,
so the question the dashboard exists to answer — which query earns its $0.35 —
stays answerable even after the remote object and the key are gone.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.yutori import YutoriError, YutoriForbidden, YutoriNotFound
from app.models.challenge import Challenge
from app.models.question import Question
from app.models.scout_definition import ScoutDefinition, ScoutInstance, ScoutRun
from app.models.webhook_event import WebhookEvent
from app.repositories import credential_repository
from app.schemas.profile import ProfileData
from app.services import ingest_service, query_generator, scout_service

logger = logging.getLogger(__name__)


@dataclass
class RunOutcome:
    started: bool
    run_id: str | None = None
    instance_id: str | None = None
    external_id: str | None = None
    kind: str | None = None
    error: str | None = None
    # Set when the run was refused because this scout already has a monitor
    # running at Yutori. The API turns it into a 409 the UI can act on.
    conflict: str | None = None
    live: dict[str, Any] | None = None


# A Scout is live until Yutori says it is done. An unknown state (None) counts
# as live on purpose: assuming a monitor is stopped when it isn't is the
# mistake that costs money.
DONE_STATES = ("done",)

# Arbitrary but fixed: serialises record_scheduled_runs across requests so two
# page loads can't both write a ledger row for the same webhook.
_SCHEDULED_RUNS_LOCK = 7_305_113


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def render_query(definition: ScoutDefinition, profile_data: ProfileData) -> str:
    """The text that will actually be sent.

    A `topics` definition is rendered from the profile at run time, so editing
    topics keeps it current. A `freeform` one is used exactly as written —
    which is the point of choosing freeform, and why topics must never quietly
    overwrite it.
    """
    if definition.query_source == "freeform":
        return definition.query_text or ""
    return query_generator.generate(profile_data)


def _live_clause():
    return or_(ScoutInstance.state.is_(None), ScoutInstance.state.notin_(DONE_STATES))


def monitor_interval(instance: ScoutInstance) -> int:
    """The interval a monitor was created with, or the app's run interval.

    Every monitor this app has created used `scout_run_interval_seconds`, so
    it is the right fallback for rows made before the interval was recorded.
    """
    recorded = (instance.detail or {}).get("output_interval")
    return int(recorded) if recorded else settings.scout_run_interval_seconds


def monthly_cost(interval_seconds: int | None) -> float:
    """What a monitor costs over a 30-day month at this interval."""
    if not interval_seconds or interval_seconds <= 0:
        return 0.0
    return round((30 * 24 * 3600 / interval_seconds) * settings.yutori_run_cost_usd, 2)


def monitor_view(instance: ScoutInstance) -> dict[str, Any]:
    interval = monitor_interval(instance)
    return {
        "id": str(instance.id),
        "definition_id": str(instance.definition_id) if instance.definition_id else None,
        "external_id": instance.external_id,
        "state": instance.state,
        "account_fingerprint": instance.account_fingerprint,
        "output_interval": interval,
        "monthly_cost_usd": monthly_cost(interval),
        "next_run": (instance.detail or {}).get("next_run"),
        "created_at": instance.created_at.isoformat() if instance.created_at else None,
    }


async def live_monitor(db: AsyncSession, definition_id: uuid.UUID) -> ScoutInstance | None:
    """The newest monitor still running at Yutori for this definition."""
    return await db.scalar(
        select(ScoutInstance)
        .where(
            ScoutInstance.definition_id == definition_id,
            ScoutInstance.kind == "scout",
            _live_clause(),
        )
        .order_by(ScoutInstance.created_at.desc())
    )


async def _stop_monitor(client, instance: ScoutInstance) -> str | None:
    """Mark a monitor done at Yutori. Returns an error, or None on success.

    404 is success — gone is the state wanted. A 403 is not: the monitor is
    still running under another account, and calling it stopped would be a
    lie that costs money.
    """
    try:
        await client.mark_done(instance.external_id)
    except YutoriNotFound:
        pass
    except YutoriForbidden:
        return (
            "This monitor was created with a different API key, so it can't be stopped "
            "from here. Switch to that key on the Accounts page, then try again."
        )
    except YutoriError as exc:
        return str(exc)[:300]
    instance.state = "done"
    instance.detail = {**(instance.detail or {}), "stopped_at": datetime.now(UTC).isoformat()}
    return None


async def list_definitions(
    db: AsyncSession, *, include_archived: bool = False
) -> list[ScoutDefinition]:
    statement = select(ScoutDefinition).order_by(ScoutDefinition.created_at.desc())
    if not include_archived:
        statement = statement.where(ScoutDefinition.status != "archived")
    return list(await db.scalars(statement))


async def get_definition(
    db: AsyncSession, definition_id: uuid.UUID
) -> ScoutDefinition | None:
    return await db.get(ScoutDefinition, definition_id)


async def create_definition(
    db: AsyncSession,
    *,
    name: str,
    query_source: str = "topics",
    query_text: str | None = None,
    notes: str | None = None,
    config: dict[str, Any] | None = None,
) -> ScoutDefinition:
    definition = ScoutDefinition(
        name=name,
        query_source=query_source,
        query_text=query_text,
        query_hash=_hash(query_text) if query_text else None,
        notes=notes,
        config=config,
        status="draft",
    )
    db.add(definition)
    await db.commit()
    await db.refresh(definition)
    return definition


async def update_definition(
    db: AsyncSession, definition: ScoutDefinition, changes: dict[str, Any]
) -> ScoutDefinition:
    for column in ("name", "notes", "query_source", "query_text", "config", "status"):
        if column in changes:
            setattr(definition, column, changes[column])
    if changes.get("query_text"):
        definition.query_hash = _hash(changes["query_text"])
    if definition.status == "archived" and definition.archived_at is None:
        definition.archived_at = datetime.now(UTC)
    if definition.status != "archived":
        definition.archived_at = None
    await db.commit()
    await db.refresh(definition)
    return definition


async def clone_definition(
    db: AsyncSession, definition: ScoutDefinition
) -> ScoutDefinition:
    """Copy a query without its history.

    Runs and instances stay with the original: the copy has spent nothing, and
    showing it someone else's yield would make the comparison the dashboard is
    built on meaningless.
    """
    return await create_definition(
        db,
        name=f"{definition.name} (copy)",
        query_source=definition.query_source,
        query_text=definition.query_text,
        notes=definition.notes,
        config=definition.config,
    )


async def delete_definition(
    db: AsyncSession, definition: ScoutDefinition
) -> dict[str, int]:
    """Delete a saved query. Its runs and its questions survive.

    The foreign keys are SET NULL, so the ledger keeps every row — deleting a
    query must not erase the record of money already spent, and must never
    touch the questions, which are what prevent paying to rediscover them.
    """
    kept = {
        "runs": await db.scalar(
            select(func.count())
            .select_from(ScoutRun)
            .where(ScoutRun.definition_id == definition.id)
        )
        or 0,
        "questions": await db.scalar(select(func.count()).select_from(Question)) or 0,
    }
    await db.delete(definition)
    await db.commit()
    return kept


async def run_definition(
    db: AsyncSession,
    definition: ScoutDefinition,
    profile_data: ProfileData,
    *,
    mode: str = "research",
    replace: bool = False,
) -> RunOutcome:
    """Spend $0.35 running one definition.

    Records the instance and the ledger row before returning, so a run is
    attributable even if the process dies immediately afterwards — the thing
    that must never happen is money spent with nothing to show it.

    In scout mode this creates a *monitor*, which keeps running at its interval
    until stopped. A definition may have only one: creating is the only way to
    make Yutori run now (restart just resumes the schedule), so a second press
    used to leave the first monitor billing forever. Now it is refused unless
    `replace` is set, and replacing stops the old monitor before creating the
    new one — if stopping fails, nothing is created.
    """
    in_flight = await db.scalar(
        select(func.count()).select_from(ScoutRun).where(ScoutRun.status == "running")
    )
    if in_flight:
        # One paid run at a time, checked before any outbound call so a refused
        # attempt costs nothing.
        return RunOutcome(started=False, error="A run is already in flight")

    kind = "research_task" if mode == "research" else "scout"

    live: ScoutInstance | None = None
    if kind == "scout":
        # Row lock on the definition: two presses at once must not both see
        # "no live monitor" and both create one.
        await db.execute(
            select(ScoutDefinition.id)
            .where(ScoutDefinition.id == definition.id)
            .with_for_update()
        )
        live = await live_monitor(db, definition.id)
        if live is not None and not replace:
            return RunOutcome(
                started=False,
                conflict="live_monitor",
                live=monitor_view(live),
                error="This scout already has a live monitor at Yutori. It keeps running "
                "on its own schedule, so starting another would pay for both.",
            )

    client = await scout_service.get_client(db)
    if client is None:
        return RunOutcome(started=False, error="No usable Yutori API key")

    credential = await credential_repository.get(db, "yutori_api_key")
    query = render_query(definition, profile_data)
    if not query.strip():
        return RunOutcome(started=False, error="This scout has no query yet")

    replaced: str | None = None
    if live is not None:
        active_print = credential.account_fingerprint if credential else None
        if live.account_fingerprint and active_print and live.account_fingerprint != active_print:
            return RunOutcome(
                started=False,
                error="The live monitor belongs to a different API key, so it can't be "
                "stopped from here. Switch to that key first, or stop it from its account.",
            )
        stop_error = await _stop_monitor(client, live)
        if stop_error:
            return RunOutcome(
                started=False,
                error=f"Couldn't stop the current monitor, so no new one was created: {stop_error}",
            )
        live.detail = {**(live.detail or {}), "superseded_at": datetime.now(UTC).isoformat()}
        replaced = live.external_id
        await db.flush()

    interval = settings.scout_run_interval_seconds
    try:
        if kind == "research_task":
            response = await client.create_research_task(
                query=query,
                webhook_url=settings.yutori_webhook_url
                if settings.public_base_url
                else None,
            )
            external_id = str(response.get("task_id") or response.get("id") or "")
            state = response.get("status")
        else:
            response = await client.create_scout(
                query=query,
                webhook_url=settings.yutori_webhook_url,
                output_interval_seconds=interval,
            )
            external_id = str(response.get("id") or "")
            state = "active"
    except YutoriError as exc:
        logger.warning("Run failed to start for %s: %s", definition.name, exc)
        # Keep the record that the old monitor was stopped, even though the
        # replacement failed — it is no longer billing either way.
        await db.commit()
        return RunOutcome(started=False, error=str(exc)[:300])

    detail: dict[str, Any] = {"view_url": response.get("view_url")}
    if kind == "scout":
        detail["output_interval"] = interval
        if replaced:
            detail["replaces"] = replaced
    instance = ScoutInstance(
        definition_id=definition.id,
        kind=kind,
        external_id=external_id,
        account_fingerprint=credential.account_fingerprint if credential else None,
        state=state,
        detail=detail,
    )
    db.add(instance)
    await db.flush()

    run = ScoutRun(
        definition_id=definition.id,
        instance_id=instance.id,
        kind=kind,
        account_fingerprint=credential.account_fingerprint if credential else None,
        # Copied, not joined: the label has to survive the key being removed.
        account_label=(credential.label or credential.key_name) if credential else None,
        cost_usd=settings.yutori_run_cost_usd,
        status="running",
        detail={"query_hash": _hash(query), "trigger": "manual"},
    )
    db.add(run)

    definition.query_text = query
    definition.query_hash = _hash(query)
    if definition.status == "draft":
        definition.status = "ready"
    await db.commit()
    await db.refresh(run)

    return RunOutcome(
        started=True,
        run_id=str(run.id),
        instance_id=str(instance.id),
        external_id=external_id,
        kind=kind,
    )


async def forget_instance(db: AsyncSession, instance_id: uuid.UUID) -> dict[str, Any]:
    """Drop the local record without touching Yutori.

    `delete_instance` refuses on a 403 — the instance is still out there
    running under another account, and saying "deleted" would be a lie. That
    is correct, but it also means an instance pointing at another account's
    key has no way to leave this app's list at all: not deletable (wrong key),
    and until now not forgettable either. This is that second door: it clears
    the reference this app holds and nothing else, mirroring the legacy
    Scout's `/scout/forget` for the one case it existed to solve.
    """
    instance = await db.get(ScoutInstance, instance_id)
    if instance is None:
        return {"forgotten": False, "error": "No such instance"}

    external_id = instance.external_id
    await db.delete(instance)
    await db.commit()
    return {"forgotten": True, "external_id": external_id}


async def delete_instance(db: AsyncSession, instance_id: uuid.UUID) -> dict[str, Any]:
    """Delete a Scout at Yutori and drop our record of it.

    The only destructive action in the workspace that reaches outside this app,
    and the only one that stops something billing: a live Scout runs on its own
    interval until it is deleted. Ordered deliberately — Yutori first, our row
    second — so a failure there leaves the reference intact rather than
    orphaning a Scout nobody is tracking any more.

    A 404 counts as success: already gone is the desired end state. A 403 does
    not, because the Scout is still out there running under another account and
    saying otherwise would be a lie.
    """
    instance = await db.get(ScoutInstance, instance_id)
    if instance is None:
        return {"deleted": False, "error": "No such instance"}

    if instance.kind == "research_task":
        # One-shot and already over; there is nothing at Yutori to delete.
        await db.delete(instance)
        await db.commit()
        return {"deleted": True, "note": "Research tasks leave nothing behind"}

    client = await scout_service.get_client(db)
    if client is None:
        return {"deleted": False, "error": "No usable Yutori API key"}

    try:
        await client.delete_scout(instance.external_id)
    except YutoriNotFound:
        pass
    except YutoriForbidden:
        return {
            "deleted": False,
            "error": "This Scout was created with a different API key, so it cannot be "
            "deleted from here. It keeps running until its own account deletes it.",
        }
    except YutoriError as exc:
        return {"deleted": False, "error": str(exc)[:300]}

    external_id = instance.external_id
    await db.delete(instance)
    await db.commit()
    return {"deleted": True, "external_id": external_id}


async def list_instances(db: AsyncSession) -> list[dict[str, Any]]:
    """Every remote object we know about, and who owns it.

    Ownership is the important column. A Scout created under a different key
    cannot be read, edited or deleted from here — Yutori answers 403 — so
    saying which account each one belongs to, and which of those is the active
    key, is the difference between a list you can act on and a list you cannot.
    """
    rows = list(
        await db.scalars(select(ScoutInstance).order_by(ScoutInstance.created_at.desc()))
    )
    names = {d.id: d.name for d in await list_definitions(db, include_archived=True)}

    # Fingerprint → the label the user gave that key. Covers inactive keys too,
    # so an object belonging to a stored-but-not-active account still reads as
    # "Friend's key" rather than an anonymous hash.
    labels: dict[str, str] = {}
    for credential in await credential_repository.list_for(db, "yutori_api_key"):
        if credential.account_fingerprint:
            labels[credential.account_fingerprint] = credential.label or credential.key_name

    active = await credential_repository.get(db, "yutori_api_key")
    active_print = active.account_fingerprint if active else None

    return [
        {
            "id": str(i.id),
            "definition_id": str(i.definition_id) if i.definition_id else None,
            "definition_name": names.get(i.definition_id),
            "kind": i.kind,
            "external_id": i.external_id,
            "state": i.state,
            "account_fingerprint": i.account_fingerprint,
            "account_label": labels.get(i.account_fingerprint or "")
            if i.account_fingerprint
            else None,
            # Unknown ownership (a row predating fingerprints) is not the same
            # as foreign ownership, so it is reported as null rather than false
            # and the page says "unknown" instead of locking the row.
            "usable": None
            if not i.account_fingerprint or not active_print
            else i.account_fingerprint == active_print,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in rows
    ]


def _superseded_ids(monitors: list[ScoutInstance]) -> set[uuid.UUID]:
    """Live monitors that aren't their scout's newest one.

    Each is a leftover from a run that created a new monitor without stopping
    the previous one — still billing, and doing nothing the newest one isn't.
    """
    newest: dict[uuid.UUID | None, ScoutInstance] = {}
    for monitor in monitors:
        if monitor.definition_id is None:
            continue
        current = newest.get(monitor.definition_id)
        if current is None or monitor.created_at > current.created_at:
            newest[monitor.definition_id] = monitor
    return {
        m.id
        for m in monitors
        if m.definition_id is not None and newest[m.definition_id].id != m.id
    }


async def _live_monitors(db: AsyncSession) -> list[ScoutInstance]:
    return list(
        await db.scalars(
            select(ScoutInstance)
            .where(ScoutInstance.kind == "scout", _live_clause())
            .order_by(ScoutInstance.created_at.desc())
        )
    )


async def monitors_summary(db: AsyncSession) -> dict[str, Any]:
    """Every monitor this app believes is still running, and what they cost.

    Local only — no call to Yutori — so the dashboard can show it on every
    load. The state is as fresh as the last Monitors visit or run sync, which
    is why the Monitors page refreshes it from Yutori.
    """
    monitors = await _live_monitors(db)
    superseded = _superseded_ids(monitors)
    names = {d.id: d.name for d in await list_definitions(db, include_archived=True)}
    rows = [
        {
            **monitor_view(m),
            "definition_name": names.get(m.definition_id),
            "superseded": m.id in superseded,
        }
        for m in monitors
    ]
    return {
        "live_count": len(rows),
        "superseded_count": len(superseded),
        "monthly_cost_usd": round(sum(r["monthly_cost_usd"] for r in rows), 2),
        "monitors": rows,
    }


async def stop_superseded(db: AsyncSession) -> dict[str, Any]:
    """Stop every superseded monitor the active key owns. Free.

    Monitors owned by another key are reported, not attempted: Yutori would
    refuse, and the answer is to switch keys, not to retry.
    """
    client = await scout_service.get_client(db)
    if client is None:
        return {"stopped": [], "failed": [], "error": "No usable Yutori API key"}

    active = await credential_repository.get(db, "yutori_api_key")
    active_print = active.account_fingerprint if active else None

    monitors = await _live_monitors(db)
    superseded = _superseded_ids(monitors)
    stopped: list[str] = []
    failed: list[dict[str, str]] = []
    for monitor in monitors:
        if monitor.id not in superseded:
            continue
        if monitor.account_fingerprint and active_print and monitor.account_fingerprint != active_print:
            failed.append(
                {"external_id": monitor.external_id, "error": "Owned by a different API key"}
            )
            continue
        error = await _stop_monitor(client, monitor)
        if error:
            failed.append({"external_id": monitor.external_id, "error": error})
        else:
            stopped.append(monitor.external_id)
    await db.commit()
    return {"stopped": stopped, "failed": failed, "error": None}


async def stop_remote(db: AsyncSession, external_id: str) -> dict[str, Any]:
    """Stop one monitor by its Yutori id, whether or not this app tracks it.

    Untracked monitors matter most here: one this app lost track of is exactly
    the kind that bills unnoticed.
    """
    client = await scout_service.get_client(db)
    if client is None:
        return {"stopped": False, "error": "No usable Yutori API key"}

    instance = await db.scalar(
        select(ScoutInstance).where(
            ScoutInstance.kind == "scout", ScoutInstance.external_id == external_id
        )
    )
    if instance is None:
        # Not ours on record; stop it directly. A throwaway instance keeps the
        # error handling in one place without inserting a row.
        instance = ScoutInstance(kind="scout", external_id=external_id)
        error = await _stop_monitor(client, instance)
        return {"stopped": error is None, "error": error, "tracked": False}

    error = await _stop_monitor(client, instance)
    await db.commit()
    return {"stopped": error is None, "error": error, "tracked": True}


async def remote_inventory(db: AsyncSession) -> dict[str, Any]:
    """Everything that exists at Yutori under the active key.

    Read from Yutori, not from our tables — that is the whole point. An object
    this app never created, or created and then lost track of, is invisible in
    `scout_instances` and is exactly the one that can keep billing unnoticed.

    Scouts and research tasks are listed separately because they mean different
    things: a Scout can still run, a research task is finished and merely
    history.

    Also brings our records up to date: each tracked monitor's state is copied
    from Yutori (so "live" means live), and any updates a monitor produced
    while no webhook got through are pulled in and entered in the ledger.
    """
    client = await scout_service.get_client(db)
    if client is None:
        return {
            "scouts": [],
            "research_tasks": [],
            "error": "No usable Yutori API key — add or re-enter one in Settings.",
        }

    tracked_rows = list(await db.scalars(select(ScoutInstance)))
    tracked = {row.external_id for row in tracked_rows}
    monitors_by_id = {row.external_id: row for row in tracked_rows if row.kind == "scout"}
    names = {d.id: d.name for d in await list_definitions(db, include_archived=True)}

    result: dict[str, Any] = {"scouts": [], "research_tasks": [], "error": None}

    try:
        listing = await client.list_scouts()
        for item in listing.get("scouts") or listing.get("items") or []:
            scout_id = str(item.get("id"))
            status_ = item.get("status")
            interval = item.get("output_interval")
            if interval is None and status_ == "active":
                # The list doesn't always carry the interval; the cost figure
                # needs it, and only active monitors cost anything.
                try:
                    interval = (await client.get_scout(scout_id)).get("output_interval")
                except YutoriError:
                    interval = None
            instance = monitors_by_id.get(scout_id)
            if instance is not None:
                instance.state = status_
                instance.detail = {
                    **(instance.detail or {}),
                    **({"output_interval": int(interval)} if interval else {}),
                    "next_run": item.get("next_run_timestamp"),
                }
            result["scouts"].append(
                {
                    "id": scout_id,
                    "status": status_,
                    "created_at": item.get("created_at"),
                    "update_count": item.get("update_count"),
                    "next_run": item.get("next_run_timestamp"),
                    "output_interval": interval,
                    "monthly_cost_usd": monthly_cost(int(interval))
                    if interval and status_ == "active"
                    else 0.0,
                    "tracked": scout_id in tracked,
                    "definition_name": names.get(instance.definition_id)
                    if instance is not None
                    else None,
                }
            )
        await db.commit()
    except YutoriError as exc:
        result["error"] = str(exc)[:300]

    try:
        listing = await client.list_research_tasks()
        # Their list endpoints have used two different envelope keys, so accept
        # either rather than silently returning nothing.
        items = listing.get("tasks") or listing.get("research_tasks") or listing.get("items") or []
        for item in items:
            task_id = str(item.get("task_id") or item.get("id") or "")
            result["research_tasks"].append(
                {
                    "id": task_id,
                    "status": item.get("status"),
                    "created_at": item.get("created_at"),
                    "tracked": task_id in tracked,
                }
            )
    except YutoriError as exc:
        result["research_error"] = str(exc)[:300]

    # Superseded is judged on local records, now refreshed from Yutori above.
    live_now = await _live_monitors(db)
    superseded_ids = _superseded_ids(live_now)
    superseded = {m.external_id for m in live_now if m.id in superseded_ids}
    for scout in result["scouts"]:
        scout["superseded"] = scout["id"] in superseded and scout["status"] != "done"

    result["untracked_scouts"] = [
        s["id"] for s in result["scouts"] if not s["tracked"] and s["status"] in ("active", "paused")
    ]
    active_scouts = [s for s in result["scouts"] if s["status"] == "active"]
    result["live_count"] = len(active_scouts)
    result["monthly_cost_usd"] = round(sum(s["monthly_cost_usd"] for s in active_scouts), 2)
    result["pulled"] = await pull_monitor_updates(db)
    result["usage"] = await _usage_vs_ledger(db)
    return result


async def _usage_vs_ledger(db: AsyncSession) -> dict[str, Any]:
    """Yutori's own 30-day run count next to the ledger's, for the active key.

    Yutori's number includes runs this app never saw — a scheduled run that
    found nothing sends no update — so a gap between the two is the signal
    that something is billing out of sight.
    """
    usage = await scout_service.usage_summary(db, period="30d")
    active = await credential_repository.get(db, "yutori_api_key")
    statement = select(func.count()).select_from(ScoutRun).where(
        ScoutRun.started_at >= datetime.now(UTC) - timedelta(days=30)
    )
    if active is not None and active.account_fingerprint:
        statement = statement.where(ScoutRun.account_fingerprint == active.account_fingerprint)
    recorded = await db.scalar(statement) or 0
    return {
        "period": usage.period,
        "yutori_runs": usage.scout_runs if usage.error is None else None,
        "recorded_runs": recorded,
        "error": usage.error,
    }


async def run_history(
    db: AsyncSession, definition_id: uuid.UUID | None = None
) -> list[dict]:
    """Runs with what each one actually produced.

    Yield is counted by joining the run's stored payload to the questions that
    came out of it, which is the only honest measure: a run that returned
    twenty questions the app already had bought nothing.
    """
    statement = select(ScoutRun).order_by(ScoutRun.started_at.desc()).limit(50)
    if definition_id is not None:
        statement = statement.where(ScoutRun.definition_id == definition_id)
    runs = list(await db.scalars(statement))

    yields: dict[uuid.UUID, dict[str, int]] = {}
    event_ids = [r.webhook_event_id for r in runs if r.webhook_event_id]
    if event_ids:
        rows = (
            await db.execute(
                select(
                    Question.source_event_id,
                    func.count(Question.id),
                    func.count(Question.id).filter(Question.status == "candidate"),
                    func.count(Question.id).filter(
                        Question.status == "candidate",
                        Question.candidate_score >= settings.digest_min_score,
                    ),
                )
                .where(Question.source_event_id.in_(event_ids))
                .group_by(Question.source_event_id)
            )
        ).all()
        yields = {
            row[0]: {"questions": row[1], "candidates": row[2], "above_bar": row[3]}
            for row in rows
        }

    return [
        {
            "id": str(run.id),
            "definition_id": str(run.definition_id) if run.definition_id else None,
            "kind": run.kind,
            "status": run.status,
            "cost_usd": float(run.cost_usd) if run.cost_usd is not None else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "duration_seconds": int((run.finished_at - run.started_at).total_seconds())
            if run.finished_at and run.started_at
            else None,
            "delivered_by": run.delivered_by,
            "account_label": run.account_label,
            "questions_found": run.questions_found,
            "error": run.error,
            **(yields.get(run.webhook_event_id) or {}),
        }
        for run in runs
    ]


async def sync_run(db: AsyncSession, run_id: uuid.UUID) -> dict[str, Any]:
    """Ask Yutori what happened to a run, and collect the result if it is ready.

    Runs started through a definition were recorded but never finalised —
    nothing polled them — so a task that succeeded at Yutori sat here as
    "running" forever with its questions uncollected. This is that missing
    half, and it is safe to call repeatedly: ingestion is keyed on the
    update id, so a result already stored is recognised rather than duplicated.
    """
    run = await db.get(ScoutRun, run_id)
    if run is None:
        return {"status": "not_found"}
    if run.status != "running":
        return {"status": run.status, "note": "Already finished"}

    instance = await db.get(ScoutInstance, run.instance_id) if run.instance_id else None
    if instance is None:
        return {"status": "running", "error": "This run has no remote object recorded"}

    client = await scout_service.get_client(db)
    if client is None:
        return {"status": "running", "error": "No usable Yutori API key"}

    if instance.kind == "research_task":
        return await _sync_research_run(db, run, instance, client)
    return await _sync_scout_run(db, run, instance, client)


async def _sync_research_run(db, run, instance, client) -> dict[str, Any]:
    try:
        task = await client.get_research_task(instance.external_id)
    except YutoriError as exc:
        return {"status": "running", "error": str(exc)[:300]}

    state = str(task.get("status") or "")
    instance.state = state
    await db.commit()

    if state in ("queued", "running"):
        return {"status": "running", "remote_status": state}

    if state != "succeeded":
        await finish_run(
            db,
            run,
            status="failed",
            error=task.get("rejection_reason") or f"Yutori reported {state}",
        )
        return {"status": "failed", "remote_status": state}

    from app.services import ingest_service

    envelope = scout_service.update_to_webhook_envelope(
        {
            "id": task.get("task_id") or instance.external_id,
            "timestamp": task.get("created_at"),
            "structured_result": task.get("structured_result"),
            "content": task.get("result"),
            "structured_output_status": task.get("structured_output_status"),
        }
    )
    event = await ingest_service.claim_event(db, envelope)

    # claim_event returns None when the webhook already delivered this, which
    # is not a failure — it tells us how the result arrived.
    delivered_by = "poll" if event is not None else "webhook"
    if event is None:
        event = await db.scalar(
            select(WebhookEvent).where(
                WebhookEvent.event_id == str(task.get("task_id") or instance.external_id)
            )
        )

    found = len((task.get("structured_result") or {}).get("questions") or []) or None
    await finish_run(
        db,
        run,
        status="succeeded",
        delivered_by=delivered_by,
        event=event,
        questions_found=found,
    )
    return {
        "status": "succeeded",
        "delivered_by": delivered_by,
        "questions_found": found,
        "ingested": event is not None,
    }


async def _sync_scout_run(db, run, instance, client) -> dict[str, Any]:
    """A monitor's run finishes when Yutori's update count moves, or it times out."""
    try:
        detail = await client.get_scout(instance.external_id)
    except YutoriError as exc:
        return {"status": "running", "error": str(exc)[:300]}

    instance.state = detail.get("status")
    await db.commit()

    # Only this monitor's own update counts. Yutori's webhook body names the
    # Scout it came from; before this was checked, any update arriving after
    # the run started — another monitor's scheduled run included — was taken
    # as this run's result. An event with no scout id (older payloads) keeps
    # the old time-only rule rather than never matching.
    event_scout = _event_scout_id()
    received = await db.scalar(
        select(WebhookEvent)
        .where(
            WebhookEvent.received_at > run.started_at,
            or_(event_scout == instance.external_id, event_scout.is_(None)),
            ~exists().where(ScoutRun.webhook_event_id == WebhookEvent.id),
        )
        .order_by(WebhookEvent.received_at.desc())
    )
    if received is not None:
        await finish_run(db, run, status="succeeded", delivered_by="webhook", event=received)
        return {"status": "succeeded", "delivered_by": "webhook"}

    age = (datetime.now(UTC) - run.started_at).total_seconds()
    if age > settings.scout_run_timeout_seconds:
        await finish_run(
            db, run, status="timed_out", error="No update arrived before the timeout"
        )
        return {"status": "timed_out"}
    return {"status": "running", "remote_status": detail.get("status")}


async def sync_in_flight(db: AsyncSession) -> list[dict[str, Any]]:
    """Advance every unfinished run. Cheap, and safe to call on page load.

    Scheduled monitor runs are recorded afterwards, so a manual run claims its
    own update first and is never double-counted as a scheduled one.
    """
    runs = list(await db.scalars(select(ScoutRun).where(ScoutRun.status == "running")))
    synced = [{"run_id": str(r.id), **(await sync_run(db, r.id))} for r in runs]
    await record_scheduled_runs(db)
    return synced


def _event_scout_id():
    """The Scout a stored webhook came from: `payload.scout.id`."""
    return WebhookEvent.payload["scout"]["id"].astext


async def record_scheduled_runs(db: AsyncSession) -> int:
    """Put every run a monitor did on its own schedule into the ledger.

    A monitor bills $0.35 each time its interval comes round, with nobody
    pressing anything, and none of those runs used to be recorded — so the
    app's spend figures were quietly wrong in the reassuring direction. Each
    update Yutori sends names its Scout, which is enough to attribute it.

    Counted only when all of these hold, so nothing is recorded twice:
      * the update is newer than our record of the monitor (older ones were
        handled by the legacy single-Scout path);
      * no ledger row already points at it;
      * the monitor has no run still `running` — that run claims its own
        update when it syncs, and this runs after syncing for that reason.

    A scheduled run that finds nothing sends no update and so can't be seen
    here; the Yutori-vs-ledger count on Monitors is the check for that.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SCHEDULED_RUNS_LOCK})

    running_for_instance = exists().where(
        ScoutRun.instance_id == ScoutInstance.id, ScoutRun.status == "running"
    )
    rows = (
        await db.execute(
            select(WebhookEvent, ScoutInstance)
            .join(
                ScoutInstance,
                and_(
                    ScoutInstance.kind == "scout",
                    ScoutInstance.external_id == _event_scout_id(),
                ),
            )
            .where(
                WebhookEvent.received_at > ScoutInstance.created_at,
                ~exists().where(ScoutRun.webhook_event_id == WebhookEvent.id),
                ~running_for_instance,
            )
            .order_by(WebhookEvent.received_at)
        )
    ).all()

    if not rows:
        await db.commit()
        return 0

    labels: dict[str, str] = {}
    for credential in await credential_repository.list_for(db, "yutori_api_key"):
        if credential.account_fingerprint:
            labels[credential.account_fingerprint] = credential.label or credential.key_name

    for event, instance in rows:
        found = len(ingest_service.parse_candidates(event.payload)) or None
        delivered_by = "poll" if event.payload.get("source") == "pull" else "webhook"

        # A manual run that timed out before its update came is the likelier
        # owner of a late update than a scheduled run is — and it was already
        # charged. Completing it avoids billing the same $0.35 twice.
        orphan = await db.scalar(
            select(ScoutRun)
            .where(
                ScoutRun.instance_id == instance.id,
                ScoutRun.status == "timed_out",
                ScoutRun.webhook_event_id.is_(None),
                ScoutRun.started_at < event.received_at,
            )
            .order_by(ScoutRun.started_at.desc())
        )
        if orphan is not None:
            orphan.status = "succeeded"
            orphan.error = None
            orphan.delivered_by = delivered_by
            orphan.webhook_event_id = event.id
            orphan.questions_found = found
            continue

        db.add(
            ScoutRun(
                definition_id=instance.definition_id,
                instance_id=instance.id,
                kind="scout",
                account_fingerprint=instance.account_fingerprint,
                account_label=labels.get(instance.account_fingerprint or ""),
                cost_usd=settings.yutori_run_cost_usd,
                status="succeeded",
                started_at=event.received_at,
                finished_at=event.received_at,
                delivered_by=delivered_by,
                webhook_event_id=event.id,
                questions_found=found,
                detail={"trigger": "schedule"},
            )
        )
    await db.commit()
    logger.info("Recorded %d scheduled monitor run(s)", len(rows))
    return len(rows)


async def pull_monitor_updates(db: AsyncSession, *, page_size: int = 20) -> dict[str, Any]:
    """Fetch updates from every live monitor, for webhooks that never arrived.

    Yutori tries a webhook 3 times over ~30 seconds and never again, and this
    app runs on a scale-to-zero host — so a scheduled run can land while
    nothing is listening. Every update stays readable at Yutori, and claiming
    it here (keyed on the update id, like the webhook) makes it count.
    """
    client = await scout_service.get_client(db)
    if client is None:
        return {"fetched": 0, "new": 0, "error": "No usable Yutori API key"}

    active = await credential_repository.get(db, "yutori_api_key")
    active_print = active.account_fingerprint if active else None

    monitors = list(
        await db.scalars(
            select(ScoutInstance).where(ScoutInstance.kind == "scout", _live_clause())
        )
    )
    fetched = new = 0
    errors: list[str] = []
    for monitor in monitors:
        if monitor.account_fingerprint and active_print and monitor.account_fingerprint != active_print:
            continue  # another account's monitor: Yutori would answer 403
        try:
            response = await client.get_updates(monitor.external_id, page_size=page_size)
        except YutoriError as exc:
            errors.append(f"{monitor.external_id}: {str(exc)[:120]}")
            continue
        for update in response.get("updates") or []:
            fetched += 1
            envelope = scout_service.update_to_webhook_envelope(
                update, scout_id=monitor.external_id
            )
            if await ingest_service.claim_event(db, envelope) is not None:
                new += 1

    recorded = await record_scheduled_runs(db)
    return {
        "fetched": fetched,
        "new": new,
        "recorded": recorded,
        "error": "; ".join(errors) or None,
    }


async def finish_run(
    db: AsyncSession,
    run: ScoutRun,
    *,
    status: str,
    delivered_by: str | None = None,
    event: WebhookEvent | None = None,
    questions_found: int | None = None,
    error: str | None = None,
) -> ScoutRun:
    run.status = status
    run.finished_at = datetime.now(UTC)
    run.delivered_by = delivered_by
    run.questions_found = questions_found
    run.error = error
    if event is not None:
        run.webhook_event_id = event.id
    await db.commit()
    await db.refresh(run)
    return run


async def active_run(db: AsyncSession) -> ScoutRun | None:
    return await db.scalar(
        select(ScoutRun)
        .where(ScoutRun.status == "running")
        .order_by(ScoutRun.started_at.desc())
    )


async def effectiveness(db: AsyncSession) -> list[dict]:
    """Definitions ranked by what they return per dollar.

    The page's reason for existing: at a flat $0.35 a run, cost tells you
    nothing on its own and run count tells you less.
    """
    definitions = await list_definitions(db, include_archived=True)
    history = await run_history(db)

    by_definition: dict[str, list[dict]] = {}
    for run in history:
        by_definition.setdefault(run["definition_id"] or "", []).append(run)

    rows = []
    for definition in definitions:
        runs = by_definition.get(str(definition.id), [])
        spend = sum(r["cost_usd"] or 0 for r in runs)
        questions = sum(r.get("questions") or 0 for r in runs)
        rows.append(
            {
                "id": str(definition.id),
                "name": definition.name,
                "status": definition.status,
                "runs": len(runs),
                "spend_usd": round(spend, 2),
                "questions": questions,
                "per_dollar": round(questions / spend, 1) if spend else None,
            }
        )
    return sorted(
        rows, key=lambda r: (r["per_dollar"] is None, -(r["per_dollar"] or 0))
    )


# What a question's current state means for the run that found it. Grouped
# rather than shown raw, because "rejected" alone does not say whether the
# filters threw it out or the user did.
def _fate(question: Question | None, ingested: bool) -> str:
    if question is None:
        return "not_ingested" if not ingested else "unparseable"
    if question.status == "enrichment_pending":
        return "awaiting_enrichment"
    if question.status == "rejected":
        return "dismissed" if question.rejection_reason == "user_dismissed" else "filtered_out"
    if question.status in ("selected", "presented"):
        return "made_a_challenge"
    if question.status == "solved":
        return "solved"
    if question.status == "skipped":
        return "skipped"
    return "in_pool"


async def run_detail(db: AsyncSession, run_id: uuid.UUID) -> dict | None:
    """One run, and the fate of every question it returned.

    Reads the run's stored payload rather than querying `questions` by
    `source_event_id`. That join answers a different question than it appears
    to: ingest dedupes on `canonical_url` and only moves `last_seen_at` on a
    re-sighting, so a question this run returned but that was already known
    still points at the event that first saw it. Counting by the join makes a
    run that returned twenty known questions look like it returned nothing —
    true about its *new* yield, misleading about what it actually did.

    So the payload says what came back, and `questions` says what became of
    each one. The gap between the two is the rediscovery rate, which is the
    number that tells a sharp query from a stale one.
    """
    run = await db.get(ScoutRun, run_id)
    if run is None:
        return None

    event = (
        await db.get(WebhookEvent, run.webhook_event_id) if run.webhook_event_id else None
    )
    ingested = bool(event and event.status == "processed")

    returned: list[dict[str, Any]] = []
    if event is not None:
        returned = ingest_service.parse_candidates(event.payload)

    wanted: dict[int, dict[str, Any]] = {}
    unparseable = 0
    for candidate in returned:
        question_id = ingest_service.extract_question_id(
            candidate.get("question_id")
        ) or ingest_service.extract_question_id(candidate.get("url"))
        if question_id is None:
            unparseable += 1
            continue
        # A run can return the same question twice; the pool holds it once.
        wanted.setdefault(question_id, candidate)

    rows: list[dict[str, Any]] = []
    if wanted:
        found = (
            await db.scalars(
                select(Question).where(Question.stackoverflow_question_id.in_(wanted))
            )
        ).all()
        by_id = {q.stackoverflow_question_id: q for q in found}

        challenge_rows = (
            await db.execute(
                select(Challenge.question_id, Challenge.id).where(
                    Challenge.question_id.in_([q.id for q in found])
                )
            )
        ).all()
        challenges = {question_id: cid for question_id, cid in challenge_rows}

        for question_id, candidate in wanted.items():
            question = by_id.get(question_id)
            rows.append(
                {
                    "stackoverflow_question_id": question_id,
                    "question_id": str(question.id) if question else None,
                    "url": (question.url if question else None)
                    or candidate.get("url")
                    or f"https://stackoverflow.com/questions/{question_id}",
                    "title": (question.title if question else None) or candidate.get("title"),
                    "tags": (question.tags if question else None)
                    or [str(t) for t in (candidate.get("tags") or [])],
                    "status": question.status if question else None,
                    "fate": _fate(question, ingested),
                    "rejection_reason": question.rejection_reason if question else None,
                    "candidate_score": float(question.candidate_score)
                    if question is not None and question.candidate_score is not None
                    else None,
                    "difficulty": (question.difficulty if question else None)
                    or candidate.get("difficulty"),
                    # False means this run returned a question the app already
                    # had — paid for, but bought nothing new.
                    "first_seen_here": bool(
                        question is not None
                        and event is not None
                        and question.source_event_id == event.id
                    ),
                    "challenge_id": str(challenges[question.id])
                    if question is not None and question.id in challenges
                    else None,
                }
            )

    rows.sort(
        key=lambda r: (r["candidate_score"] is None, -(r["candidate_score"] or 0), r["title"] or "")
    )

    new_here = sum(1 for r in rows if r["first_seen_here"])
    above_bar = sum(
        1
        for r in rows
        if r["candidate_score"] is not None and r["candidate_score"] >= settings.digest_min_score
    )
    tally: dict[str, int] = {}
    for row in rows:
        tally[row["fate"]] = tally.get(row["fate"], 0) + 1

    return {
        "id": str(run.id),
        "definition_id": str(run.definition_id) if run.definition_id else None,
        "kind": run.kind,
        "status": run.status,
        "cost_usd": float(run.cost_usd) if run.cost_usd is not None else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "delivered_by": run.delivered_by,
        "account_label": run.account_label,
        "error": run.error,
        "returned": len(returned),
        "unique_questions": len(wanted),
        "unparseable": unparseable,
        "new_here": new_here,
        "already_known": len(rows) - new_here,
        "above_bar": above_bar,
        "challenges": sum(1 for r in rows if r["challenge_id"]),
        "fates": tally,
        # The page has to be able to say "this run's results are still sitting
        # in the inbox" — that is a $0.35 result not yet in the pool.
        "event_status": event.status if event else None,
        "has_payload": event is not None,
        "cost_per_new_question": round(float(run.cost_usd) / new_here, 4)
        if run.cost_usd and new_here
        else None,
        "questions": rows,
    }
