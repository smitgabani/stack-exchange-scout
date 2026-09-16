from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credential import Credential


async def get(db: AsyncSession, key_name: str) -> Credential | None:
    return await db.scalar(select(Credential).where(Credential.key_name == key_name))


async def upsert(db: AsyncSession, key_name: str, encrypted_value: str) -> None:
    existing = await get(db, key_name)
    if existing is not None:
        existing.encrypted_value = encrypted_value
    else:
        db.add(Credential(key_name=key_name, encrypted_value=encrypted_value))
    await db.commit()
