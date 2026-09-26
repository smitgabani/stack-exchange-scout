import uuid
from datetime import datetime

from sqlalchemy import DateTime, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WebhookEvent(Base):
    """Durable inbox for inbound provider webhooks.

    The webhook handler does nothing but verify, insert here, and return 200 —
    Yutori retries only 3 times over ~30s and never redelivers afterwards, and
    this app runs on a scale-to-zero host, so durability has to come from
    Postgres rather than from the process staying alive long enough to finish.

    Storing the raw payload also makes ingestion replayable, which matters
    while the shape of Yutori's structured output is still being pinned down.
    """

    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_webhook_events_provider_event"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), default="yutori")

    # Yutori's `update.id` — stable across delivery retries, so it's the
    # idempotency key. `delivery.id` changes per attempt: debugging only.
    event_id: Mapped[str] = mapped_column(String(128))
    delivery_id: Mapped[str | None] = mapped_column(String(128))
    attempt: Mapped[int | None] = mapped_column(SmallInteger)
    event_type: Mapped[str | None] = mapped_column(String(64))

    payload: Mapped[dict] = mapped_column(JSONB)

    status: Mapped[str] = mapped_column(String(16), default="received")
    error: Mapped[str | None] = mapped_column(Text)

    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
