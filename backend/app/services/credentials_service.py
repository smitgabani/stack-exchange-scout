import logging

from cryptography.fernet import InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_value, encrypt_value
from app.repositories import credential_repository

logger = logging.getLogger(__name__)


async def set_api_key(db: AsyncSession, key_name: str, plaintext_value: str) -> None:
    await credential_repository.upsert(db, key_name, encrypt_value(plaintext_value))


async def has_api_key(db: AsyncSession, key_name: str) -> bool:
    """Whether a *usable* key is stored.

    Deliberately decrypts rather than just checking the row exists: a key
    encrypted under a previous APP_SECRET_KEY is still a row, but it can't be
    used for anything. Reporting that as "connected" would leave the UI and
    the key gates insisting everything is fine while every API call fails.
    """
    return await get_api_key(db, key_name) is not None


async def get_api_key(db: AsyncSession, key_name: str) -> str | None:
    """Decrypt a stored key, or None if absent/undecryptable.

    Undecryptable is a real case, not a theoretical one: the ciphertext is tied
    to APP_SECRET_KEY, so a rotated key (or running against a database written
    by a different environment) makes existing rows unreadable. Returning None
    lets callers report "no usable key" instead of crashing — and the error is
    logged without ever logging the value itself (prd.md §27).
    """
    credential = await credential_repository.get(db, key_name)
    if credential is None:
        return None
    try:
        return decrypt_value(credential.encrypted_value)
    except InvalidToken:
        logger.error(
            "Stored credential %s could not be decrypted — it was likely encrypted "
            "with a different APP_SECRET_KEY. Re-enter the key via Settings.",
            key_name,
        )
        return None
