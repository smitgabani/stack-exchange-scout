from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Credential(Base):
    """A single user-supplied API key (Yutori, Gemini, or OpenAI), encrypted at rest.

    Deliberately kept out of the `profile` JSON (prd.md §12) so none of
    these are ever returned by GET /profile.
    """

    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_name: Mapped[str] = mapped_column(String, unique=True, index=True)
    encrypted_value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
