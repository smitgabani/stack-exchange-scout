import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Job(Base):
    """One piece of work that outlives the request that asked for it.

    Every LLM call in this app used to happen inside the HTTP request that
    triggered it. Generating a digest is up to ten questions with two attempts
    each at a 60-second timeout — twenty minutes in the worst case, seventy
    seconds typically — and the Vercel function proxying it stays alive for the
    whole thing. Fluid Compute bills for that time, which is what paused the
    deployment.

    So the request now writes a row here and returns immediately, and the work
    happens in the background. The row is the only thing the browser needs: it
    carries the answer when there is one, and the reason when there is not.
    """

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="queued")

    # What the worker needs to do the job — question id, format id and so on.
    # JSONB rather than columns because the four kinds want different things
    # and none of it is ever queried.
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    # What the endpoint would have returned had it been synchronous.
    result: Mapped[dict | None] = mapped_column(JSONB)
    # Why it failed, in the words the user should see. Not a traceback.
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_finished(self) -> bool:
        return self.status in ("succeeded", "failed")
