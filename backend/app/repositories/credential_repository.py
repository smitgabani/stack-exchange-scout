from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credential import Credential


async def get(db: AsyncSession, key_name: str) -> Credential | None:
    """The *active* key for a provider.

    The app can hold several Yutori keys belonging to different accounts
    (ADR 0004), so "the key" is always the active one. A partial unique index
    guarantees there is at most one, which is why this can order arbitrarily
    and still be deterministic.
    """
    return await db.scalar(
        select(Credential).where(Credential.key_name == key_name, Credential.is_active)
    )


async def list_for(db: AsyncSession, key_name: str) -> list[Credential]:
    """Every key stored for a provider, active first then newest."""
    rows = await db.scalars(
        select(Credential)
        .where(Credential.key_name == key_name)
        .order_by(Credential.is_active.desc(), Credential.id.desc())
    )
    return list(rows)


async def get_by_id(db: AsyncSession, credential_id: int) -> Credential | None:
    return await db.get(Credential, credential_id)


async def upsert(
    db: AsyncSession, key_name: str, encrypted_value: str, *, label: str | None = None
) -> None:
    """Replace the active key for a provider, or create it.

    Deliberately still an upsert: rotating a key in Settings should replace the
    one in use, not quietly accumulate another account alongside it. Adding a
    second account is an explicit action (`add`).
    """
    existing = await get(db, key_name)
    if existing is not None:
        existing.encrypted_value = encrypted_value
        if label:
            existing.label = label
        # The fingerprint belonged to the old key, so it must not survive a
        # replacement — a stale one would claim the wrong account owns things.
        existing.account_fingerprint = None
    else:
        db.add(
            Credential(
                key_name=key_name,
                encrypted_value=encrypted_value,
                label=label,
                is_active=True,
            )
        )
    await db.commit()


async def add(
    db: AsyncSession,
    key_name: str,
    encrypted_value: str,
    *,
    label: str,
    fingerprint: str | None,
    make_active: bool,
) -> Credential:
    """Store an additional key for a provider.

    Activation is exclusive: the partial unique index would reject a second
    active row, so any incumbent is stood down first, in the same transaction.
    """
    if make_active:
        for other in await list_for(db, key_name):
            other.is_active = False
        await db.flush()

    credential = Credential(
        key_name=key_name,
        encrypted_value=encrypted_value,
        label=label,
        account_fingerprint=fingerprint,
        is_active=make_active,
    )
    db.add(credential)
    await db.commit()
    await db.refresh(credential)
    return credential


async def activate(db: AsyncSession, credential: Credential) -> Credential:
    for other in await list_for(db, credential.key_name):
        other.is_active = other.id == credential.id
    await db.flush()
    await db.commit()
    await db.refresh(credential)
    return credential


async def delete(db: AsyncSession, credential: Credential) -> None:
    """Remove a stored key.

    Only the credential row. Nothing it discovered is touched — questions,
    digests and challenges are what stop the app rediscovering, and re-paying
    for, what the user has already seen (ADR 0004).
    """
    await db.delete(credential)
    await db.commit()
