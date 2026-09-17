import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# prd.md §12 / tdd.md §5.2. A CHECK constraint rather than a PG ENUM — altering
# an enum in Postgres is painful, and M8 will add transitions to this list.
QUESTION_STATUSES = (
    "enrichment_pending",
    "candidate",
    "selected",
    "presented",
    "solved",
    "skipped",
    "rejected",
)


class Question(Base):
    """A Stack Overflow question and this system's evaluation of it, merged into
    one row (prd.md §12) — re-scoring updates the row rather than inserting.
    """

    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('" + "', '".join(QUESTION_STATUSES) + "')",
            name="ck_questions_status",
        ),
        Index("idx_questions_tags", "tags", postgresql_using="gin"),
        Index("idx_questions_status_score", "status", "candidate_score"),
        Index("idx_questions_question_created_at", "question_created_at"),
        # Only enrichment_pending rows are ever polled for retry.
        Index(
            "idx_questions_next_retry_at",
            "next_retry_at",
            postgresql_where=text("status = 'enrichment_pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Identity / dedupe. canonical_url is the ingest-time key: Yutori gives URLs,
    # and the numeric id is extracted from them.
    stackoverflow_question_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    canonical_url: Mapped[str] = mapped_column(Text, unique=True)
    url: Mapped[str] = mapped_column(Text)

    # Stack Exchange metadata (written by M5 enrichment).
    title: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    score: Mapped[int | None] = mapped_column(Integer)
    answer_count: Mapped[int | None] = mapped_column(Integer)
    accepted_answer_id: Mapped[int | None] = mapped_column(BigInteger)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    question_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Yutori-supplied judgement.
    problem_summary: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[int | None] = mapped_column(SmallInteger)
    interesting_reason: Mapped[str | None] = mapped_column(Text)

    # Enrichment retry state (M5-B3) — without these the retry path either
    # hammers a dead API forever or can't be tested.
    enrichment_attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrichment_error: Mapped[str | None] = mapped_column(Text)

    # Why a row was auto-rejected (M5-B5) — also answers "why was my digest empty".
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    # Scoring (M6). Sub-scores persisted separately so they can later be
    # replaced by a learned model (tdd.md §4.6).
    profile_version: Mapped[int | None] = mapped_column(Integer)
    topic_relevance: Mapped[int | None] = mapped_column(SmallInteger)
    technical_depth: Mapped[int | None] = mapped_column(SmallInteger)
    solve_opportunity: Mapped[int | None] = mapped_column(SmallInteger)
    recency_score: Mapped[int | None] = mapped_column(SmallInteger)
    quality_score: Mapped[int | None] = mapped_column(SmallInteger)
    novelty_score: Mapped[int | None] = mapped_column(SmallInteger)
    candidate_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[str] = mapped_column(String(32), default="enrichment_pending")
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhook_events.id", ondelete="SET NULL")
    )

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
