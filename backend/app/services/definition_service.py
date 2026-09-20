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
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.yutori import YutoriError, YutoriForbidden, YutoriNotFound
from app.models.question import Question
from app.models.scout_definition import ScoutDefinition, ScoutInstance, ScoutRun
from app.models.webhook_event import WebhookEvent
from app.repositories import credential_repository
from app.schemas.profile import ProfileData
from app.services import query_generator, scout_service

logger = logging.getLogger(__name__)


@dataclass
class RunOutcome:
    started: bool
    run_id: str | None = None
    instance_id: str | None = None
    external_id: str | None = None
    kind: str | None = None
    error: str | None = None


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
) -> RunOutcome:
    """Spend $0.35 running one definition.

    Records the instance and the ledger row before returning, so a run is
    attributable even if the process dies immediately afterwards — the thing
    that must never happen is money spent with nothing to show it.
    """
    in_flight = await db.scalar(
        select(func.count()).select_from(ScoutRun).where(ScoutRun.status == "running")
    )
    if in_flight:
        # One paid run at a time, checked before any outbound call so a refused
        # attempt costs nothing.
        return RunOutcome(started=False, error="A run is already in flight")

    client = await scout_service.get_client(db)
    if client is None:
        return RunOutcome(started=False, error="No usable Yutori API key")

    credential = await credential_repository.get(db, "yutori_api_key")
    query = render_query(definition, profile_data)
    if not query.strip():
        return RunOutcome(started=False, error="This scout has no query yet")

    kind = "research_task" if mode == "research" else "scout"
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
                output_interval_seconds=settings.scout_run_interval_seconds,
            )
            external_id = str(response.get("id") or "")
            state = "active"
    except YutoriError as exc:
        logger.warning("Run failed to start for %s: %s", definition.name, exc)
        return RunOutcome(started=False, error=str(exc)[:300])

    instance = ScoutInstance(
        definition_id=definition.id,
        kind=kind,
        external_id=external_id,
        account_fingerprint=credential.account_fingerprint if credential else None,
        state=state,
        detail={"view_url": response.get("view_url")},
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
        detail={"query_hash": _hash(query)},
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
    """Every remote object we know about, and which definition it came from."""
    rows = list(
        await db.scalars(select(ScoutInstance).order_by(ScoutInstance.created_at.desc()))
    )
    names = {
        d.id: d.name for d in await list_definitions(db, include_archived=True)
    }
    return [
        {
            "id": str(i.id),
            "definition_id": str(i.definition_id) if i.definition_id else None,
            "definition_name": names.get(i.definition_id),
            "kind": i.kind,
            "external_id": i.external_id,
            "state": i.state,
            "account_fingerprint": i.account_fingerprint,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in rows
    ]


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
