from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CustomBlock(Base):
    """A block the user defined, on top of the built-in registry (ADR 0005).

    It carries no schema. The `kind` names one of the renderers the frontend
    already has, and the shape follows from that — which is what keeps the
    guarantee in `challenge_blocks`'s docstring true for user-defined blocks:
    there is never a value on the page the UI has not been taught to draw.

    Mutable, unlike `prompt_templates`. Provenance is kept per generation on
    `challenges.generations` instead, because a challenge can be built by more
    than one call and the instruction differs between them.
    """

    __tablename__ = "custom_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The key the model returns and `challenges.content` is keyed by. Unique
    # across this table, and rejected at the service layer if it collides with
    # a built-in block.
    key: Mapped[str] = mapped_column(String(40), unique=True)
    label: Mapped[str] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32))
    instruction: Mapped[str] = mapped_column(Text)
    # Exempt from the spoiler scan and hidden until every hint is revealed —
    # the same bargain `solution_resources` makes.
    gated: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BlockInstruction(Base):
    """A reworded instruction for a block that ships in the code.

    Separate from `custom_blocks` rather than one table with nullable columns:
    a custom block must have a kind and a label, an override must not have
    either, and two tables can say so with NOT NULL instead of a CHECK that
    has to be read to be believed.

    Only the instruction is overridable. Kind, schema and the core/gated flags
    stay in code, so a reworded `concepts` can ask for different ideas but
    cannot start returning a string and failing `validate` on every run.
    """

    __tablename__ = "block_instructions"

    # The registry key this overrides. Not a foreign key — the registry lives
    # in code — so the service checks membership before storing.
    block_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    instruction: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
