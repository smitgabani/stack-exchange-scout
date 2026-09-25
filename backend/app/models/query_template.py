from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class QueryTemplate(Base):
    """One version of the text a topics-based scout sends Yutori (M13).

    Placeholders (`{topics}`, `{preferred_concepts}`, …) are filled from the
    profile at run time by `query_generator`. Rows are immutable, like
    `PromptTemplate`: saving writes a new version, rolling back reactivates an
    old one, and with no active row the built-in template applies.
    """

    __tablename__ = "query_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    body: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class YutoriDefaults(Base):
    """The settings every scout starts from. Always a single row, id 1.

    Holds only what differs from the built-in defaults, in the same shape a
    scout's overrides use (`schemas.yutori_settings.YutoriSettings`).
    """

    __tablename__ = "yutori_defaults"
    __table_args__ = (CheckConstraint("id = 1", name="ck_yutori_defaults_singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
