from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt_value
from app.repositories import credential_repository


async def set_api_key(db: AsyncSession, key_name: str, plaintext_value: str) -> None:
    await credential_repository.upsert(db, key_name, encrypt_value(plaintext_value))


async def has_api_key(db: AsyncSession, key_name: str) -> bool:
    return await credential_repository.get(db, key_name) is not None
