"""The durable half of the Scout model (ADR 0004).

A *definition* is a saved query the user owns: free to create, clone and edit,
and never touched by an API outage or a key change. An *instance* is whatever
was created at Yutori to carry out one run — a research task or a Scout — and
is disposable by design. A *run* is the ledger entry joining the two, and it
outlives both, because "what did this cost and what did it buy" has to be
answerable after the remote object and even the account are gone.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ScoutDefinition(Base):
    """A saved query. Local, free, and the thing the dashboard is built around."""

    __tablename__ = "scout_definitions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)

    # "topics" renders the query from the profile's topic/concept model at run
    # time; "freeform" uses query_text as authored. Kept explicit so editing
    # topics doesn't silently rewrite a query somebody hand-tuned.
    query_source: Mapped[str] = mapped_column(String(16), default="topics")
    query_text: Mapped[str | None] = mapped_column(Text)

    # Per-definition overrides (interval, timezone). Free-form because Yutori's
    # accepted fields have changed twice already.
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # draft: never run. ready: has run, or the user says it's finished.
    # archived: kept for its history, hidden from the working list.
    status: Mapped[str] = mapped_column(String(16), default="draft")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'ready', 'archived')", name="ck_scout_definitions_status"
        ),
        CheckConstraint(
            "query_source IN ('topics', 'freeform')", name="ck_scout_definitions_query_source"
        ),
    )


class ScoutInstance(Base):
    """Something that exists at Yutori. Disposable, and owned by one account."""

    __tablename__ = "scout_instances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # SET NULL rather than CASCADE: deleting a saved query must not erase the
    # record of money already spent under it.
    definition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scout_definitions.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(128))

    # Which API key created it. Yutori has no account id, so this is the only
    # way to know an object is unreachable before trying to touch it.
    account_fingerprint: Mapped[str | None] = mapped_column(String(32))

    # Provider-reported: queued/running/succeeded/failed for a research task,
    # active/paused/done for a Scout. Stored verbatim rather than normalised —
    # the vocabularies genuinely differ and flattening them loses meaning.
    state: Mapped[str | None] = mapped_column(String(24))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("kind", "external_id", name="uq_scout_instances_kind_external"),
        CheckConstraint("kind IN ('research_task', 'scout')", name="ck_scout_instances_kind"),
    )


class ScoutRun(Base):
    """One paid run, and what it bought.

    The spend ledger. Deliberately denormalised on the account: `account_label`
    is copied in rather than joined, so history still reads after a key is
    removed — which is the whole point of tombstoning rather than cascading.
    """

    __tablename__ = "scout_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    definition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scout_definitions.id", ondelete="SET NULL")
    )
    instance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scout_instances.id", ondelete="SET NULL")
    )

    kind: Mapped[str] = mapped_column(String(16))
    account_fingerprint: Mapped[str | None] = mapped_column(String(32))
    account_label: Mapped[str | None] = mapped_column(String(120))

    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 4))
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # How the result actually reached us: 'webhook', 'poll', or NULL when
    # nothing ever arrived. Worth recording — on the first real research task
    # the webhook never came, and only the poll saved the $0.35.
    delivered_by: Mapped[str | None] = mapped_column(String(16))
    # The stored payload this run produced, so per-run yield can be counted by
    # joining through questions.source_event_id.
    webhook_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    questions_found: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'timed_out')", name="ck_scout_runs_status"
        ),
        CheckConstraint("kind IN ('research_task', 'scout')", name="ck_scout_runs_kind"),
    )
