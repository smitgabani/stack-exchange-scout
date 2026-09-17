import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.stackexchange.com/2.3"
SITE = "stackoverflow"
# `withbody` is the stock filter that adds question body to the default fields;
# the body is needed for difficulty/quality scoring and for the LLM prompt.
FILTER = "withbody"
# The API accepts up to 100 semicolon-delimited ids per call.
MAX_IDS_PER_REQUEST = 100


class StackExchangeError(RuntimeError):
    """Transport failure or non-success response. Callers treat this as
    *temporary* — a question is never rejected because the API had a bad day
    (tdd.md §8.4).
    """


class StackExchangeBadRequest(StackExchangeError):
    """The request itself is wrong and will never succeed as-is.

    Distinct from the transient case because retrying is pointless: a malformed
    id returns 400 for the whole batch forever, which would otherwise leave
    every question in it stuck in enrichment_pending being retried on a loop.
    """


# Stack Overflow question ids comfortably fit in a signed 32-bit int; anything
# outside that is a parse artefact, and sending one 400s the entire batch.
MAX_QUESTION_ID = 2_147_483_647


def is_plausible_question_id(question_id: int) -> bool:
    return 0 < question_id <= MAX_QUESTION_ID


@dataclass
class QuestionMetadata:
    """Authoritative Stack Overflow metadata for one question.

    This is the source of truth over anything Yutori claimed (tdd.md Decision 5):
    Yutori may say "1 answer, none accepted" while the API says otherwise.
    """

    question_id: int
    title: str | None
    body: str | None
    tags: list[str]
    score: int
    answer_count: int
    accepted_answer_id: int | None
    is_closed: bool
    question_created_at: datetime | None
    last_activity_at: datetime | None
    link: str | None


def _to_datetime(epoch: int | None) -> datetime | None:
    return datetime.fromtimestamp(epoch, tz=UTC) if epoch else None


def parse_question(item: dict[str, Any]) -> QuestionMetadata:
    return QuestionMetadata(
        question_id=int(item["question_id"]),
        title=item.get("title"),
        body=item.get("body"),
        tags=list(item.get("tags") or []),
        score=int(item.get("score") or 0),
        answer_count=int(item.get("answer_count") or 0),
        accepted_answer_id=item.get("accepted_answer_id"),
        # closed_date is only present when the question is actually closed.
        is_closed=item.get("closed_date") is not None,
        question_created_at=_to_datetime(item.get("creation_date")),
        last_activity_at=_to_datetime(item.get("last_activity_date")),
        link=item.get("link"),
    )


class StackExchangeClient:
    """Read-only Stack Exchange client.

    Unauthenticated on purpose: the documented design has no Stack Exchange key
    anywhere (not in `credentials`, not in the env table), and the keyless quota
    of 300 requests/day is far beyond what a single-user tool ingesting a
    handful of questions per Scout cycle needs. Batching keeps it well clear.
    """

    def __init__(self, *, base_url: str = BASE_URL, timeout: float = 20.0) -> None:
        self._base_url = base_url
        self._timeout = timeout

    async def fetch_questions(self, question_ids: list[int]) -> dict[int, QuestionMetadata]:
        """Look up questions by id, batching to stay within the API's limits.

        Returns only the questions the API knows about — an id missing from the
        result genuinely does not exist (deleted, or never did), which is the
        one case that justifies rejecting rather than retrying.
        """
        found: dict[int, QuestionMetadata] = {}

        for start in range(0, len(question_ids), MAX_IDS_PER_REQUEST):
            batch = question_ids[start : start + MAX_IDS_PER_REQUEST]
            payload = await self._get(f"/questions/{';'.join(str(i) for i in batch)}")

            for item in payload.get("items", []):
                metadata = parse_question(item)
                found[metadata.question_id] = metadata

            # The API asks callers to pause when it sets `backoff`; ignoring it
            # earns a throttle violation.
            backoff = payload.get("backoff")
            if backoff:
                logger.info("Stack Exchange requested a %ss backoff", backoff)
                await asyncio.sleep(float(backoff))

        return found

    async def _get(self, path: str) -> dict[str, Any]:
        params = {"site": SITE, "filter": FILTER}
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
                response = await client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise StackExchangeError(f"Stack Exchange request failed: {exc}") from exc

        # 429 is a throttle — genuinely worth retrying. Other 4xx mean the
        # request is malformed and will fail identically next time.
        if 400 <= response.status_code < 500 and response.status_code != 429:
            raise StackExchangeBadRequest(
                f"Stack Exchange rejected the request ({response.status_code}): {response.text[:300]}"
            )
        if response.status_code >= 400:
            raise StackExchangeError(f"Stack Exchange returned {response.status_code}: {response.text[:300]}")

        try:
            return response.json()
        except ValueError as exc:
            raise StackExchangeError("Stack Exchange returned a non-JSON body") from exc
