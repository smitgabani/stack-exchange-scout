import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question
from app.models.webhook_event import WebhookEvent

logger = logging.getLogger(__name__)

_QUESTION_URL_RE = re.compile(r"stackoverflow\.com/questions/(\d+)", re.IGNORECASE)


@dataclass
class StageResult:
    """Uniform return shape for every pipeline stage — also the assertion
    surface for tests and the debug payload for the frontend.
    """

    processed: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "processed": self.processed,
            "succeeded": self.succeeded,
            "skipped": self.skipped,
            "failed": self.failed,
            "errors": self.errors,
        }


def canonical_url(question_id: int) -> str:
    return f"https://stackoverflow.com/questions/{question_id}"


def extract_question_id(value: str | None) -> int | None:
    """Pull the numeric question id out of any Stack Overflow URL form."""
    if not value:
        return None
    match = _QUESTION_URL_RE.search(value)
    if match:
        return int(match.group(1))
    # Yutori may hand back a bare id in `question_id`.
    stripped = value.strip()
    return int(stripped) if stripped.isdigit() else None


def parse_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull candidate questions out of a Yutori webhook body.

    Yutori's structured output arrives in `update.report_content`, which is a
    string that may hold JSON matching the output_schema we registered — or, if
    the model didn't comply, prose. Both are handled: JSON is read properly, and
    prose falls back to scraping Stack Overflow URLs out of the text so a
    non-conforming run still yields candidates rather than nothing.
    """
    update = payload.get("update") or {}
    report = update.get("report_content")
    candidates: list[dict[str, Any]] = []

    if isinstance(report, dict):
        candidates = list(report.get("questions") or [])
    elif isinstance(report, str) and report.strip():
        try:
            parsed = json.loads(report)
            if isinstance(parsed, dict):
                candidates = list(parsed.get("questions") or [])
            elif isinstance(parsed, list):
                candidates = list(parsed)
        except json.JSONDecodeError:
            # Prose fallback: every distinct question URL mentioned.
            seen: set[int] = set()
            for match in _QUESTION_URL_RE.finditer(report):
                question_id = int(match.group(1))
                if question_id not in seen:
                    seen.add(question_id)
                    candidates.append({"question_id": str(question_id)})

    return [candidate for candidate in candidates if isinstance(candidate, dict)]


async def claim_event(db: AsyncSession, payload: dict[str, Any]) -> WebhookEvent | None:
    """Record the event, or return None if it was already recorded.

    The insert-on-conflict is the idempotency boundary: Yutori delivers
    at-least-once and a retry can arrive while the first attempt is still in
    flight, so "have we seen this?" has to be decided by the database, not by a
    read-then-write race.
    """
    update = payload.get("update") or {}
    delivery = payload.get("delivery") or {}
    event_id = str(update.get("id") or delivery.get("id") or "")
    if not event_id:
        return None

    statement = (
        pg_insert(WebhookEvent)
        .values(
            provider="yutori",
            event_id=event_id,
            delivery_id=str(delivery.get("id")) if delivery.get("id") else None,
            attempt=delivery.get("attempt"),
            event_type=payload.get("event_type"),
            payload=payload,
            status="received",
        )
        .on_conflict_do_nothing(index_elements=["provider", "event_id"])
        .returning(WebhookEvent.id)
    )
    inserted_id = await db.scalar(statement)
    await db.commit()

    if inserted_id is None:
        return None
    return await db.get(WebhookEvent, inserted_id)


async def ingest_event(db: AsyncSession, event: WebhookEvent) -> StageResult:
    """Turn one stored webhook event into `questions` rows.

    Rows land in `enrichment_pending`: nothing is a real `candidate` until
    Stack Exchange has verified it (M5).
    """
    result = StageResult()
    candidates = parse_candidates(event.payload)
    result.processed = len(candidates)

    for candidate in candidates:
        question_id = extract_question_id(candidate.get("question_id")) or extract_question_id(
            candidate.get("url")
        )
        if question_id is None:
            result.skipped += 1
            continue

        values = {
            "stackoverflow_question_id": question_id,
            "canonical_url": canonical_url(question_id),
            "url": candidate.get("url") or canonical_url(question_id),
            "title": candidate.get("title"),
            "tags": [str(tag) for tag in (candidate.get("tags") or [])],
            "problem_summary": candidate.get("problem_summary"),
            "difficulty": candidate.get("difficulty"),
            "interesting_reason": candidate.get("interesting_reason"),
            "status": "enrichment_pending",
            "source_event_id": event.id,
        }

        # A question legitimately reappears across Scout runs; that's a
        # re-sighting, not a new candidate, so only last_seen_at moves.
        statement = (
            pg_insert(Question)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["stackoverflow_question_id"],
                set_={"last_seen_at": datetime.now(UTC)},
            )
        )
        try:
            await db.execute(statement)
            result.succeeded += 1
        except Exception as exc:  # noqa: BLE001 - one bad row must not sink the batch
            result.failed += 1
            result.errors.append(f"question {question_id}: {exc}")

    event.status = "processed" if not result.failed else "failed"
    event.processed_at = datetime.now(UTC)
    if result.errors:
        event.error = "; ".join(result.errors)[:1000]
    await db.commit()
    return result


async def ingest_pending(db: AsyncSession, *, limit: int = 50) -> StageResult:
    """Ingest every received-but-unprocessed event (the `ingest` stage)."""
    total = StageResult()
    events = (
        await db.scalars(
            select(WebhookEvent)
            .where(WebhookEvent.status == "received")
            .order_by(WebhookEvent.received_at)
            .limit(limit)
        )
    ).all()

    for event in events:
        result = await ingest_event(db, event)
        total.processed += result.processed
        total.succeeded += result.succeeded
        total.skipped += result.skipped
        total.failed += result.failed
        total.errors.extend(result.errors)
    return total
