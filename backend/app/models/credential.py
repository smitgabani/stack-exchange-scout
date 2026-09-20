from datetime import datetime

from sqlalchemy import Boolean, DateTime, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Credential(Base):
    """A single user-supplied API key (Yutori, Gemini, or OpenAI), encrypted at rest.

    Deliberately kept out of the `profile` JSON (prd.md §12) so none of
    these are ever returned by GET /profile.
    """

    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    # No longer unique: the app holds several Yutori keys, which may belong to
    # different accounts (ADR 0004). Exactly one per provider is active, and a
    # partial unique index enforces that in the database rather than leaving it
    # to whichever service happens to write next.
    key_name: Mapped[str] = mapped_column(String, index=True)
    encrypted_value: Mapped[str] = mapped_column(Text)

    # A name the user recognises — "My personal key", "Friend's key".
    label: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # sha256(key)[:16]. Identifies the account without storing the key twice,
    # and is what tells an unreachable remote object from a broken one.
    account_fingerprint: Mapped[str | None] = mapped_column(String(32))
    # What the user says this account really cost, when the run history cannot
    # know. NULL means the computed total is trusted, which is the default.
    spend_override_usd: Mapped[float | None] = mapped_column(Numeric(10, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
