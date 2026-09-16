from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import Profile
from app.schemas.profile import ProfileData


async def get(db: AsyncSession) -> Profile | None:
    return await db.scalar(select(Profile).limit(1))


async def create_default(db: AsyncSession) -> Profile:
    profile = Profile(data=ProfileData().model_dump(mode="json"), version=1)
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def save(db: AsyncSession, profile: Profile, data: dict) -> Profile:
    profile.data = data
    profile.version += 1
    await db.commit()
    await db.refresh(profile)
    return profile
