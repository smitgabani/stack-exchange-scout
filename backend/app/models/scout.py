import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

RUN_STATES = ("idle", "running")
RUN_KINDS = ("research_task", "scout")

SCOUT_EVENT_TYPES = (
    "query_synced",
    "run_started",
    "update_received",
    "parked",
    "error",
)


class Scout(Base):
    """The single active Yutori Scout for the whole app (prd.md §9).

    One row, like `profile` — the app never runs more than one Scout.
    """

    __tablename__ = "scouts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(32), default="yutori")
    external_scout_id: Mapped[str | None] = mapped_column(String(128))

    # query_text as well as the hash: the hash decides whether a PATCH is
    # needed, the text is what makes a bad Yutori result debuggable.
    query_text: Mapped[str | None] = mapped_column(Text)
    query_hash: Mapped[str | None] = mapped_column(String(64))

    sync_status: Mapped[str] = mapped_column(String(16), default="pending")
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- on-demand run state -------------------------------------------------
    # Our own view of whether a run we started is still outstanding. Separate
    # from `external_status` below, which is Yutori's view: a run can be over at
    # Yutori while we have yet to notice and park the Scout.
    run_state: Mapped[str] = mapped_column(String(16), default="idle")
    run_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # `update_count` as it stood when the run started. A run has produced
    # something when Yutori's count moves past this, which is how a run that
    # never reaches our webhook is still detected.
    run_baseline_update_count: Mapped[int | None] = mapped_column(Integer)
    # Which primitive the in-flight run used: a one-shot research task, or the
    # Scout itself (ADR 0004). They finish differently — a research task is
    # polled at its own endpoint and leaves nothing to park.
    run_kind: Mapped[str | None] = mapped_column(String(16))
    # The research task id, when run_kind is research_task.
    run_external_id: Mapped[str | None] = mapped_column(String(128))

    # --- mirrored from Yutori's scout detail, for display --------------------
    external_status: Mapped[str | None] = mapped_column(String(16))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    update_count: Mapped[int | None] = mapped_column(Integer)
    last_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # insufficient_prepaid_balance, budget_exceeded, subscription_inactive, …
    # Without surfacing this, an out-of-credit Scout is indistinguishable from
    # one that simply found nothing — and the app would claim the latter.
    rejection_reason: Mapped[str | None] = mapped_column(String(64))
    detail_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "run_state IN ('idle', 'running')",
            name="ck_scouts_run_state",
        ),
    )


class ScoutEvent(Base):
    """Append-only log of everything that happens to the Scout.

    One table serves three purposes that would otherwise need three: the
    timeline shown on the Scout page, the history of what the query was at any
    point (so a change in results can be traced to the topic edit that caused
    it), and the spend ledger, since `run_started` rows carry their cost.
    """

    __tablename__ = "scout_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scout_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(String(32))

    # Set on query_synced: the full rendered query as it was sent. Stored in
    # full rather than as a diff so old queries stay readable on their own.
    query_text: Mapped[str | None] = mapped_column(Text)
    query_hash: Mapped[str | None] = mapped_column(String(64))

    # Set on update_received: joins to webhook_events.event_id.
    external_update_id: Mapped[str | None] = mapped_column(String(128))
    # Set on run_started. Nullable because most events cost nothing.
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 4))

    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('query_synced', 'run_started', 'update_received', 'parked', 'error')",
            name="ck_scout_events_type",
        ),
    )
