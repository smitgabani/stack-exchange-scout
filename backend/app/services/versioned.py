"""Immutable, versioned templates: the curator prompt and the scout query.

Rows are never edited. A save writes the next version and makes it the only
active one; rolling back reactivates an old row without copying it forward;
reset deactivates everything so the built-in text in code applies again.
"""

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


async def list_versions(db: AsyncSession, *, model: Any) -> list:
    return list(await db.scalars(select(model).order_by(model.version.desc())))


async def save_active(db: AsyncSession, row: Any, *, floor: int) -> Any:
    """Store `row` as the next version above `floor` and activate it.

    `floor` is the built-in version, so a first stored edit never collides
    with the provenance already recorded against the code default.
    """
    model = type(row)
    highest = await db.scalar(select(model.version).order_by(model.version.desc()))
    row.version = max(highest or 0, floor) + 1
    row.is_active = True
    await _deactivate_all(db, model)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def activate(db: AsyncSession, version: int, *, model: Any) -> Any | None:
    row = await db.scalar(select(model).where(model.version == version))
    if row is None:
        return None
    await _deactivate_all(db, model)
    row.is_active = True
    await db.commit()
    await db.refresh(row)
    return row


async def reset(db: AsyncSession, *, model: Any) -> None:
    await _deactivate_all(db, model)
    await db.commit()


async def _deactivate_all(db: AsyncSession, model: Any) -> None:
    await db.execute(update(model).values(is_active=False).where(model.is_active))
