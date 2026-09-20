from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PromptTemplate(Base):
    """One version of the editable half of the curator prompt.

    Stores guidance only. The prompt-injection defences are composed around
    this in `challenge_service` and are not editable — see the migration for
    why a security control does not belong in a textarea.

    Rows are immutable: saving a change writes a new version rather than
    updating one, so `challenges.prompt_version` keeps pointing at the exact
    text that produced a given batch.
    """

    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)

    # Sent as the provider's system instruction, with the safety clause appended.
    system_instruction: Mapped[str] = mapped_column(Text)
    # Opens the user message, before the trusted metadata and the fenced question.
    user_preamble: Mapped[str] = mapped_column(Text)

    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
