from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scout import Scout


async def get(db: AsyncSession) -> Scout | None:
    """The app runs exactly one Scout, so this is a singleton lookup."""
    return await db.scalar(select(Scout).limit(1))


async def create(db: AsyncSession, **fields) -> Scout:
    scout = Scout(**fields)
    db.add(scout)
    await db.commit()
    await db.refresh(scout)
    return scout


async def save(db: AsyncSession, scout: Scout) -> Scout:
    await db.commit()
    await db.refresh(scout)
    return scout
