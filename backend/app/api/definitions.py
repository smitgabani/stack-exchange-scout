"""Saved scout definitions: the workspace's CRUD and run surface (ADR 0004)."""

import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_yutori_key
from app.core.config import settings
from app.core.db import get_db
from app.integrations.yutori import CANDIDATE_OUTPUT_SCHEMA
from app.repositories import credential_repository
from app.schemas.profile import ProfileData
from app.schemas.yutori_settings import (
    MAX_SCHEMA_CHARS,
    MAX_SUBSCRIBERS,
    MIN_INTERVAL_SECONDS,
    YutoriSettings,
    plain_errors,
)
from app.services import definition_service, task_settings
from app.services.profile_service import get_or_create_profile

router = APIRouter(tags=["scout-definitions"])


class DefinitionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query_source: str = "topics"
    query_text: str | None = None
    notes: str | None = None
    config: dict[str, Any] | None = None


class DefinitionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    query_source: str | None = None
    query_text: str | None = None
    notes: str | None = None
    config: dict[str, Any] | None = None
    status: str | None = None


def _out(definition: Any, *, rendered: str | None = None) -> dict:
    return {
        "id": str(definition.id),
        "name": definition.name,
        "notes": definition.notes,
        "query_source": definition.query_source,
        "query_text": definition.query_text,
        # What would be sent if it ran right now. For a topics-based
        # definition that is recomputed from the profile, so an edit to topics
        # shows here before it costs anything to discover.
        "rendered_query": rendered,
        "config": definition.config,
        "status": definition.status,
        "created_at": definition.created_at.isoformat()
        if definition.created_at
        else None,
        "updated_at": definition.updated_at.isoformat()
        if definition.updated_at
        else None,
    }


async def _profile_data(db: AsyncSession) -> ProfileData:
    profile = await get_or_create_profile(db)
    return ProfileData.model_validate(profile.data)


@router.get("/scout-definitions")
async def list_definitions(
    include_archived: bool = False, db: AsyncSession = Depends(get_db)
) -> dict:
    definitions = await definition_service.list_definitions(
        db, include_archived=include_archived
    )
    profile_data = await _profile_data(db)
    history = await definition_service.run_history(db)

    stats: dict[str, dict] = {}
    for run in history:
        key = run["definition_id"] or ""
        entry = stats.setdefault(
            key,
            {
                "runs": 0,
                "spend_usd": 0.0,
                "questions": 0,
                "last_run": None,
                "last_kind": None,
                "last_status": None,
                "last_account": None,
                "accounts": [],
            },
        )
        entry["runs"] += 1
        entry["spend_usd"] = round(entry["spend_usd"] + (run["cost_usd"] or 0), 2)
        entry["questions"] += run.get("questions") or 0
        # History is newest-first, so the first one seen is the latest.
        if entry["last_run"] is None:
            entry["last_run"] = run["started_at"]
            entry["last_kind"] = run["kind"]
            entry["last_status"] = run["status"]
            entry["last_account"] = run["account_label"]
        # A definition is local and belongs to no account, but its runs were
        # each paid for by one — and comparing yield across definitions only
        # means something when you know which account footed the bill.
        if run["account_label"] and run["account_label"] not in entry["accounts"]:
            entry["accounts"].append(run["account_label"])

    template = await definition_service.active_template(db)

    # So the list can say which of these ran on the account currently in use.
    active = await credential_repository.get(db, "yutori_api_key")
    active_account = (active.label or active.key_name) if active else None

    return {
        "active_account": active_account,
        "definitions": [
            {
                **_out(d, rendered=definition_service.render_query(d, profile_data, template)),
                "stats": stats.get(
                    str(d.id),
                    {"runs": 0, "spend_usd": 0.0, "questions": 0, "last_run": None},
                ),
            }
            for d in definitions
        ],
        "run_cost_usd": settings.yutori_run_cost_usd,
        # How often a monitor started now would run, so the run dialog can say
        # what Scout mode costs per month rather than just per run.
        "monitor_interval_seconds": settings.scout_run_interval_seconds,
    }


@router.post("/scout-definitions", status_code=status.HTTP_201_CREATED)
async def create_definition(
    body: DefinitionIn, db: AsyncSession = Depends(get_db)
) -> dict:
    definition = await definition_service.create_definition(
        db,
        name=body.name,
        query_source=body.query_source,
        query_text=body.query_text,
        notes=body.notes,
        config=body.config,
    )
    return _out(definition, rendered=await _render(db, definition))


async def _render(db: AsyncSession, definition: Any) -> str:
    """What this definition would send right now, with the active template."""
    return definition_service.render_query(
        definition, await _profile_data(db), await definition_service.active_template(db)
    )


async def _require(db: AsyncSession, definition_id: uuid.UUID):
    definition = await definition_service.get_definition(db, definition_id)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No such scout"
        )
    return definition


@router.get("/scout-definitions/{definition_id}")
async def get_definition(
    definition_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    definition = await _require(db, definition_id)
    return {
        **_out(definition, rendered=await _render(db, definition)),
        "runs": await definition_service.run_history(db, definition_id),
        "run_cost_usd": settings.yutori_run_cost_usd,
        "monitor_interval_seconds": settings.scout_run_interval_seconds,
    }


@router.patch("/scout-definitions/{definition_id}")
async def patch_definition(
    definition_id: uuid.UUID, body: DefinitionPatch, db: AsyncSession = Depends(get_db)
) -> dict:
    definition = await _require(db, definition_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("query_source") not in (None, "topics", "freeform"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="query_source must be 'topics' or 'freeform'",
        )
    if changes.get("status") not in (None, "draft", "ready", "archived"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="status must be 'draft', 'ready' or 'archived'",
        )
    definition = await definition_service.update_definition(db, definition, changes)
    return _out(definition, rendered=await _render(db, definition))


def _parse_settings(body: dict[str, Any]) -> YutoriSettings:
    """Validate settings, answering 422 in sentences rather than error objects."""
    try:
        return YutoriSettings.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=plain_errors(exc)
        ) from None


async def _settings_out(
    db: AsyncSession, definition: Any, *, overrides: dict[str, Any] | None = None
) -> dict:
    view = await definition_service.settings_view(
        db, definition, await _profile_data(db), overrides=overrides
    )
    return {
        **view,
        "run_cost_usd": settings.yutori_run_cost_usd,
        "default_output_schema": CANDIDATE_OUTPUT_SCHEMA,
        # What Yutori assumes when no timezone is sent, so the form can say so.
        "yutori_default_timezone": task_settings.YUTORI_DEFAULT_TIMEZONE,
        "limits": {
            "min_interval_seconds": MIN_INTERVAL_SECONDS,
            "max_subscribers": MAX_SUBSCRIBERS,
            "max_schema_chars": MAX_SCHEMA_CHARS,
        },
    }


@router.get("/scout-definitions/{definition_id}/settings")
async def get_settings(definition_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """What this scout sends to Yutori: defaults, its overrides, and a preview.

    Free — nothing here calls Yutori.
    """
    return await _settings_out(db, await _require(db, definition_id))


@router.put("/scout-definitions/{definition_id}/settings")
async def put_settings(
    definition_id: uuid.UUID,
    body: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Save this scout's overrides. Takes effect on its next run. Free."""
    definition = await _require(db, definition_id)
    parsed = _parse_settings(body)
    definition = await definition_service.set_yutori_overrides(db, definition, parsed.overrides())
    return await _settings_out(db, definition)


@router.delete("/scout-definitions/{definition_id}/settings")
async def reset_settings(definition_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Drop every override, so the scout follows the defaults again."""
    definition = await _require(db, definition_id)
    definition = await definition_service.set_yutori_overrides(db, definition, None)
    return await _settings_out(db, definition)


@router.post("/scout-definitions/{definition_id}/settings/preview")
async def preview_settings(
    definition_id: uuid.UUID,
    body: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """What unsaved settings would send, and cost. Free, and stores nothing."""
    definition = await _require(db, definition_id)
    parsed = _parse_settings(body)
    return await _settings_out(db, definition, overrides=parsed.overrides())


@router.post(
    "/scout-definitions/{definition_id}/clone", status_code=status.HTTP_201_CREATED
)
async def clone_definition(
    definition_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    definition = await _require(db, definition_id)
    clone = await definition_service.clone_definition(db, definition)
    return _out(clone, rendered=await _render(db, clone))


@router.delete("/scout-definitions/{definition_id}")
async def delete_definition(
    definition_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete a saved query. Its runs and every discovered question survive."""
    definition = await _require(db, definition_id)
    kept = await definition_service.delete_definition(db, definition)
    return {"deleted": True, "kept": kept}


@router.post(
    "/scout-definitions/{definition_id}/run", dependencies=[Depends(require_yutori_key)]
)
async def run_definition(
    definition_id: uuid.UUID,
    mode: str = "research",
    replace: bool = False,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run this scout now. **Billable** — about $0.35.

    In scout mode this starts a monitor that keeps running on its own. If the
    scout already has one, the answer is a 409 describing it; pass
    `replace=true` to stop that monitor and start a new one.
    """
    if mode not in ("research", "scout"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="mode must be 'research' or 'scout'",
        )
    definition = await _require(db, definition_id)
    outcome = await definition_service.run_definition(
        db, definition, await _profile_data(db), mode=mode, replace=replace
    )
    if outcome.conflict == "live_monitor":
        # Structured, so the UI can show the monitor and offer to replace it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "live_monitor",
                "message": outcome.error,
                "monitor": outcome.live,
                "run_cost_usd": settings.yutori_run_cost_usd,
            },
        )
    if not outcome.started:
        # 409 for "already running", 502 for anything Yutori refused.
        code = (
            status.HTTP_409_CONFLICT
            if outcome.error and "in flight" in outcome.error
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=code, detail=outcome.error or "Could not start the run"
        )
    return {
        "started": True,
        "run_id": outcome.run_id,
        "external_id": outcome.external_id,
        "kind": outcome.kind,
        "cost_usd": settings.yutori_run_cost_usd,
    }


@router.get("/scout-remote")
async def remote_inventory(db: AsyncSession = Depends(get_db)) -> dict:
    """Every Scout and research task that exists at Yutori under the active key.

    Free — these are reads. Deliberately not merged into the instances list:
    one answers "what did this app create", the other "what is actually out
    there", and the gap between them is the interesting part.
    """
    return await definition_service.remote_inventory(db)


@router.get("/scout-monitors")
async def monitors(db: AsyncSession = Depends(get_db)) -> dict:
    """Monitors this app believes are still running, and their monthly cost.

    Local only, so it is cheap enough for the dashboard. Runs the ledger sync
    first, so scheduled runs that arrived since the last visit are counted.
    """
    await definition_service.record_scheduled_runs(db)
    return {
        **await definition_service.monitors_summary(db),
        "run_cost_usd": settings.yutori_run_cost_usd,
    }


@router.post("/scout-monitors/stop-superseded", dependencies=[Depends(require_yutori_key)])
async def stop_superseded(db: AsyncSession = Depends(get_db)) -> dict:
    """Stop every monitor that isn't its scout's newest. Free."""
    result = await definition_service.stop_superseded(db)
    if result.get("error"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=result["error"])
    return result


@router.post("/scout-remote/{external_id}/done", dependencies=[Depends(require_yutori_key)])
async def stop_remote(external_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Stop one monitor at Yutori, tracked or not. Free.

    502 rather than a silent success when Yutori refuses — a monitor that is
    still running must never be reported as stopped.
    """
    result = await definition_service.stop_remote(db, external_id)
    if not result.get("stopped"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.get("error") or "Could not stop the monitor",
        )
    return result


@router.get("/scout-instances/{instance_id}/remote")
async def monitor_remote(instance_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """A live monitor as Yutori reports it, and where it differs from its scout. Free."""
    result = await definition_service.monitor_remote(db, instance_id, await _profile_data(db))
    if result.get("error"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result["error"])
    return result


@router.post("/scout-instances/{instance_id}/apply", dependencies=[Depends(require_yutori_key)])
async def apply_to_monitor(instance_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Send the scout's saved settings to its live monitor. Free — no run starts."""
    result = await definition_service.apply_to_monitor(db, instance_id, await _profile_data(db))
    if not result.get("applied"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result["error"])
    return result


@router.post("/scout-instances/{instance_id}/restart", dependencies=[Depends(require_yutori_key)])
async def restart_monitor(instance_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Bring a stopped monitor back on its schedule. Doesn't run it now."""
    result = await definition_service.restart_monitor(db, instance_id)
    if not result.get("restarted"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result["error"])
    return result


@router.get("/scout-instances")
async def list_instances(db: AsyncSession = Depends(get_db)) -> dict:
    """Remote objects this app knows about — Scouts and research tasks."""
    return {"instances": await definition_service.list_instances(db)}


@router.delete("/scout-instances/{instance_id}")
async def delete_instance(
    instance_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete a Scout at Yutori. The only action here that stops something billing.

    502 rather than a silent success when Yutori refuses — a Scout that is
    still running must never be reported as deleted.
    """
    result = await definition_service.delete_instance(db, instance_id)
    if not result.get("deleted"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.get("error") or "Could not delete",
        )
    return result


@router.post("/scout-instances/{instance_id}/forget")
async def forget_instance(instance_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Drop this app's record of an instance without touching Yutori.

    For the one case `DELETE` cannot handle: an instance created under a
    different account's key. Yutori answers 403 to a delete from any other
    key, so the row would otherwise be permanently stuck in the list with no
    way off it.
    """
    result = await definition_service.forget_instance(db, instance_id)
    if not result.get("forgotten"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=result.get("error") or "No such instance"
        )
    return result


@router.get("/scout-runs")
async def list_runs(db: AsyncSession = Depends(get_db)) -> dict:
    return {"runs": await definition_service.run_history(db)}


@router.get("/scout-runs/{run_id}")
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """One run, and what became of every question it returned.

    The point is to make a good query distinguishable from a lucky one: how
    many results were new rather than already known, how many cleared the
    digest bar, and where the rest were lost.
    """
    detail = await definition_service.run_detail(db, run_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such run")
    return detail


@router.post("/scout-runs/{run_id}/sync")
async def sync_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Ask Yutori what happened to this run and collect the result if ready.

    Free, and safe to press repeatedly — ingestion is keyed on the update id,
    so a result already stored is recognised rather than duplicated.
    """
    return await definition_service.sync_run(db, run_id)


@router.post("/scout-runs/sync")
async def sync_all_runs(db: AsyncSession = Depends(get_db)) -> dict:
    """Advance every unfinished run."""
    return {"synced": await definition_service.sync_in_flight(db)}


@router.get("/scout-effectiveness")
async def effectiveness(db: AsyncSession = Depends(get_db)) -> dict:
    """Definitions ranked by questions per dollar."""
    return {"rows": await definition_service.effectiveness(db)}
