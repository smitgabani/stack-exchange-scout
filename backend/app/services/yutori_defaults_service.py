"""The settings every scout starts from (M13).

Stored as overrides of the built-in defaults, in one row. A scout layers its
own overrides on top, so the order is: built-in → these → the scout's.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.query_template import YutoriDefaults
from app.schemas.yutori_settings import YutoriSettings
from app.services import task_settings


async def stored(db: AsyncSession) -> dict[str, Any]:
    """Only what has been changed from the built-in defaults."""
    row = await db.get(YutoriDefaults, 1)
    return dict(row.settings or {}) if row else {}


async def effective(db: AsyncSession) -> dict[str, Any]:
    """The defaults a scout inherits: built-in, with the stored changes on top."""
    return task_settings.effective(task_settings.built_in_defaults(), await stored(db))


async def put(db: AsyncSession, settings: YutoriSettings) -> dict[str, Any]:
    row = await db.get(YutoriDefaults, 1)
    if row is None:
        row = YutoriDefaults(id=1, settings={})
        db.add(row)
    row.settings = settings.overrides()
    await db.commit()
    return dict(row.settings)


async def reset(db: AsyncSession) -> None:
    row = await db.get(YutoriDefaults, 1)
    if row is not None:
        await db.delete(row)
        await db.commit()
