import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# One status column covering both generation and delivery. tdd.md §8.6 wanted a
# separate email_status, but two parallel state machines on one row invite
# contradictory states.
DIGEST_STATUSES = (
    "generating",
    "generated",
    "generation_failed",
    "empty",
    "sending",
    "sent",
    "send_failed",
)


class Digest(Base):
    __tablename__ = "digests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('" + "', '".join(DIGEST_STATUSES) + "')",
            name="ck_digests_status",
        ),
        Index("idx_digests_generated_at", "generated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(24), default="generating")
    profile_version: Mapped[int | None] = mapped_column(Integer)
    question_count: Mapped[int] = mapped_column(Integer, default=0)

    email_error: Mapped[str | None] = mapped_column(Text)
    email_attempts: Mapped[int] = mapped_column(SmallInteger, default=0)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DigestQuestion(Base):
    """Ordered membership of questions in a digest."""

    __tablename__ = "digest_questions"
    __table_args__ = (
        PrimaryKeyConstraint("digest_id", "question_id"),
        UniqueConstraint("digest_id", "position", name="uq_digest_questions_position"),
    )

    digest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("digests.id", ondelete="CASCADE")
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
