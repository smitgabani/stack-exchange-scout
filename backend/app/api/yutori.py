"""Yutori-wide settings: the query template and the defaults every scout inherits (M13).

The counterpart of `/llm` for the discovery side. Nothing here calls Yutori or
spends anything — these only change what the next run will send.
"""

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.integrations.yutori import CANDIDATE_OUTPUT_SCHEMA
from app.schemas.profile import ProfileData
from app.schemas.yutori_settings import (
    MAX_SCHEMA_CHARS,
    MAX_SUBSCRIBERS,
    MIN_INTERVAL_SECONDS,
    YutoriSettings,
    plain_errors,
)
from app.services import (
    query_generator,
    query_template_service,
    task_settings,
    yutori_defaults_service,
)
from app.services.profile_service import get_or_create_profile
from app.services.query_template_service import QueryTemplateError

router = APIRouter(prefix="/yutori", tags=["yutori"])


async def _profile_data(db: AsyncSession) -> ProfileData:
    profile = await get_or_create_profile(db)
    return ProfileData.model_validate(profile.data)


# ---------------------------------------------------------------------------
# Query template
# ---------------------------------------------------------------------------


class TemplateIn(BaseModel):
    body: str = Field(min_length=1)
    notes: str | None = None


class PreviewIn(BaseModel):
    body: str | None = None


@router.get("/query-template")
async def get_query_template(db: AsyncSession = Depends(get_db)) -> dict:
    """The template in force, the built-in one, and what it renders to now."""
    active = await query_template_service.get_active(db)
    return {
        "template": {
            "body": active.body,
            "version": active.version,
            "is_default": active.is_default,
        },
        "default_body": query_generator.DEFAULT_TEMPLATE,
        "placeholders": list(query_generator.PLACEHOLDERS),
        "rendered": query_generator.generate(await _profile_data(db), active.body),
        "limits": {"max_template_chars": query_template_service.MAX_TEMPLATE_CHARS},
    }


@router.get("/query-templates")
async def list_query_templates(db: AsyncSession = Depends(get_db)) -> dict:
    return {
        "versions": [
            {
                "id": row.id,
                "version": row.version,
                "body": row.body,
                "notes": row.notes,
                "is_active": row.is_active,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in await query_template_service.list_versions(db)
        ]
    }


@router.post("/query-templates", status_code=status.HTTP_201_CREATED)
async def save_query_template(body: TemplateIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Save a new version and make it active. Used by the next topics-based run."""
    try:
        row = await query_template_service.save_version(db, body=body.body, notes=body.notes)
    except QueryTemplateError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None
    return {"version": row.version, "is_active": row.is_active}


@router.post("/query-templates/{version}/activate")
async def activate_query_template(version: int, db: AsyncSession = Depends(get_db)) -> dict:
    row = await query_template_service.activate(db, version)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such version")
    return {"version": row.version, "is_active": row.is_active}


@router.post("/query-templates/reset")
async def reset_query_template(db: AsyncSession = Depends(get_db)) -> dict:
    await query_template_service.reset_to_default(db)
    return {"version": query_template_service.BUILT_IN_VERSION, "is_default": True}


@router.post("/query-template/preview")
async def preview_query_template(body: PreviewIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Render a draft with the current profile. Free, and stores nothing."""
    try:
        text = (
            query_template_service.validate(body.body)
            if body.body is not None
            else (await query_template_service.get_active(db)).body
        )
    except QueryTemplateError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None
    return {"rendered": query_generator.generate(await _profile_data(db), text)}


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


async def _defaults_out(db: AsyncSession) -> dict:
    return {
        "built_in": task_settings.built_in_defaults(),
        "stored": await yutori_defaults_service.stored(db),
        "effective": await yutori_defaults_service.effective(db),
        "run_cost_usd": settings.yutori_run_cost_usd,
        "default_output_schema": CANDIDATE_OUTPUT_SCHEMA,
        "yutori_default_timezone": task_settings.YUTORI_DEFAULT_TIMEZONE,
        "limits": {
            "min_interval_seconds": MIN_INTERVAL_SECONDS,
            "max_subscribers": MAX_SUBSCRIBERS,
            "max_schema_chars": MAX_SCHEMA_CHARS,
        },
    }


@router.get("/defaults")
async def get_defaults(db: AsyncSession = Depends(get_db)) -> dict:
    """What every scout inherits unless it overrides a field."""
    return await _defaults_out(db)


@router.put("/defaults")
async def put_defaults(body: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)) -> dict:
    try:
        parsed = YutoriSettings.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=plain_errors(exc)
        ) from None
    await yutori_defaults_service.put(db, parsed)
    return await _defaults_out(db)


@router.delete("/defaults")
async def reset_defaults(db: AsyncSession = Depends(get_db)) -> dict:
    """Back to the built-in defaults."""
    await yutori_defaults_service.reset(db)
    return await _defaults_out(db)
