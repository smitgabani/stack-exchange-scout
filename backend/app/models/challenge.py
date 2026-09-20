import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Challenge(Base):
    """An LLM-generated challenge derived from a question (prd.md §17).

    Deliberately never stores or receives accepted-answer text — the whole
    point is that it doesn't spoil the solution (tdd.md §9.5).
    """

    __tablename__ = "challenges"
    __table_args__ = (UniqueConstraint("digest_id", "question_id", name="uq_challenges_digest_question"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Nullable: a challenge promoted by hand from the candidate pool belongs to
    # no digest. `uq_challenges_manual_question` (partial, WHERE digest_id IS
    # NULL) is what stops the same question being promoted twice — the
    # composite constraint below cannot, since NULLs compare as distinct.
    digest_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("digests.id", ondelete="CASCADE"), nullable=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE")
    )

    # The five fields the LLM must return (tdd.md §8.7).
    problem_summary: Mapped[str] = mapped_column(Text)
    why_interesting: Mapped[str] = mapped_column(Text)
    concepts: Mapped[list] = mapped_column(JSONB, default=list)
    starting_direction: Mapped[str] = mapped_column(Text)
    hints: Mapped[list] = mapped_column(JSONB, default=list)

    # The LLM's own difficulty guess, distinct from Yutori's questions.difficulty.
    estimated_difficulty: Mapped[int | None] = mapped_column(SmallInteger)

    # Provenance — which provider/model/prompt produced this, so a bad batch
    # can be identified after a prompt or model change.
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[int | None] = mapped_column(SmallInteger)

    # The whole structured result, including blocks that have no column of
    # their own. Null on challenges generated before formats existed, which is
    # why every reader falls back to the columns above.
    content: Mapped[dict | None] = mapped_column(JSONB)
    # Denormalised like scout_runs.account_label: what produced this has to
    # survive the format being renamed or deleted.
    format_name: Mapped[str | None] = mapped_column(String(80))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def source(self) -> str:
        """Where this challenge came from, for the UI to label it.

        Derived rather than stored — `digest_id IS NULL` already carries the
        fact, and a second column could disagree with it.
        """
        return "digest" if self.digest_id is not None else "manual"
