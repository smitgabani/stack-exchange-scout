import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Scout(Base):
    """The single active Yutori Scout for the whole app (prd.md §9).

    One row, like `profile` — the app never runs more than one Scout.
    """

    __tablename__ = "scouts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), default="yutori")
    external_scout_id: Mapped[str | None] = mapped_column(String(128))

    # query_text as well as the hash: the hash decides whether a PATCH is
    # needed, the text is what makes a bad Yutori result debuggable.
    query_text: Mapped[str | None] = mapped_column(Text)
    query_hash: Mapped[str | None] = mapped_column(String(64))

    sync_status: Mapped[str] = mapped_column(String(16), default="pending")
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
