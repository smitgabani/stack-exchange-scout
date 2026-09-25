"""Versioned, editable query template for topics-based scouts (M13).

The same shape as `prompt_service`, for the other prompt this app writes: the
text a scout sends Yutori. Templates are immutable — a save writes a new
version and activates it, so a run's results can always be read against the
exact wording that produced them, and rolling back is reactivating a row.

With no active row the built-in template in `query_generator` applies, so a
fresh install and one whose templates were all reset behave identically.
"""

import logging
import string
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.query_template import QueryTemplate
from app.services import query_generator

logger = logging.getLogger(__name__)

MAX_TEMPLATE_CHARS = 4000
# The built-in template counts as version 1, so a first stored edit is v2.
BUILT_IN_VERSION = 1

# Stand-ins for a trial render: proves a template formats before it is stored.
_SAMPLE = {
    "topics": "- Rust (weight 80/100)",
    "preferred_concepts": "- concurrency",
    "excluded_concepts": "- (none specified)",
    "difficulty_min": 3,
    "difficulty_max": 5,
}


class QueryTemplateError(RuntimeError):
    """A template was rejected before it could be stored."""


@dataclass
class ActiveTemplate:
    body: str
    version: int
    is_default: bool


def validate(body: str) -> str:
    """Reject templates that can't be filled, or can't follow the topics.

    Unknown placeholders are refused rather than left in: Yutori would receive
    a literal "{favourite_language}", and the run would still cost $0.35.
    """
    body = (body or "").strip()
    if not body:
        raise QueryTemplateError("The template can't be empty.")
    if len(body) > MAX_TEMPLATE_CHARS:
        raise QueryTemplateError(
            f"The template is too long — keep it under {MAX_TEMPLATE_CHARS:,} characters."
        )
    try:
        names = [field for _, field, _, _ in string.Formatter().parse(body) if field is not None]
    except ValueError:
        raise QueryTemplateError(
            "A brace isn't matched. Placeholders look like {topics}; for a literal brace "
            "write {{ or }}."
        ) from None
    unknown = sorted({name for name in names if name not in query_generator.PLACEHOLDERS})
    if unknown:
        shown = ", ".join("{" + name + "}" if name else "{}" for name in unknown)
        allowed = ", ".join("{" + name + "}" for name in query_generator.PLACEHOLDERS)
        raise QueryTemplateError(f"Unknown placeholder {shown}. Use only {allowed}.")
    if "topics" not in names:
        raise QueryTemplateError(
            "The template must include {topics} — it's what makes a topics-based scout "
            "follow your topics."
        )
    try:
        body.format(**_SAMPLE)
    except (KeyError, IndexError, ValueError) as exc:
        raise QueryTemplateError(f"The template can't be filled in: {exc}") from None
    return body


async def get_active(db: AsyncSession) -> ActiveTemplate:
    row = await db.scalar(select(QueryTemplate).where(QueryTemplate.is_active))
    if row is None:
        return ActiveTemplate(
            body=query_generator.DEFAULT_TEMPLATE, version=BUILT_IN_VERSION, is_default=True
        )
    return ActiveTemplate(body=row.body, version=row.version, is_default=False)


async def list_versions(db: AsyncSession) -> list[QueryTemplate]:
    return list(await db.scalars(select(QueryTemplate).order_by(QueryTemplate.version.desc())))


async def save_version(db: AsyncSession, *, body: str, notes: str | None = None) -> QueryTemplate:
    """Store a new version and make it active."""
    body = validate(body)
    highest = await db.scalar(select(QueryTemplate.version).order_by(QueryTemplate.version.desc()))
    next_version = max(highest or 0, BUILT_IN_VERSION) + 1

    await db.execute(update(QueryTemplate).values(is_active=False).where(QueryTemplate.is_active))
    row = QueryTemplate(version=next_version, body=body, notes=notes, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info("Query template v%d activated", row.version)
    return row


async def activate(db: AsyncSession, version: int) -> QueryTemplate | None:
    """Roll back to a stored version without copying it forward."""
    row = await db.scalar(select(QueryTemplate).where(QueryTemplate.version == version))
    if row is None:
        return None
    await db.execute(update(QueryTemplate).values(is_active=False).where(QueryTemplate.is_active))
    row.is_active = True
    await db.commit()
    await db.refresh(row)
    return row


async def reset_to_default(db: AsyncSession) -> None:
    """Deactivate every stored template, returning to the built-in one."""
    await db.execute(update(QueryTemplate).values(is_active=False).where(QueryTemplate.is_active))
    await db.commit()
