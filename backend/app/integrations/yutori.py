from typing import Any

import httpx

# Contract confirmed against Yutori's live API reference (docs.yutori.com).
# The repo's prd.md references a docs/yutori-api.md that was never committed,
# so these specifics are recorded here rather than left implicit.
BASE_URL = "https://api.yutori.com"
SCOUTS_PATH = "/v1/scouting/tasks"
USAGE_PATH = "/v1/usage"
MIN_OUTPUT_INTERVAL_SECONDS = 1800
# The PATCH reference documents a 3600 floor while the OpenAPI schema says 1800.
# Using the higher number on update satisfies both readings.
MIN_PATCH_INTERVAL_SECONDS = 3600

# Yutori supports JSON Schema for structured output. Asking for exactly the
# candidate shape prd.md §10 specifies is what keeps us off prose parsing.
CANDIDATE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string"},
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "created_at": {"type": "string"},
                    "answer_count": {"type": "integer"},
                    "has_accepted_answer": {"type": "boolean"},
                    "problem_summary": {"type": "string"},
                    "difficulty": {"type": "integer"},
                    "interesting_reason": {"type": "string"},
                },
                "required": ["url"],
            },
        }
    },
    "required": ["questions"],
}


class YutoriError(RuntimeError):
    """Any non-success response or transport failure from Yutori."""


class YutoriNotFound(YutoriError):
    """The Scout is gone. For teardown that counts as success, not failure."""


class YutoriClient:
    """Thin wrapper over the Yutori Scouting API.

    Deliberately not a singleton — the API key is user-supplied and read from
    the database per call site, so the caller constructs this with whatever key
    is currently stored.
    """

    def __init__(self, api_key: str, *, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        # X-API-Key, not Bearer.
        return {"X-API-Key": self._api_key, "Content-Type": "application/json"}

    async def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=BASE_URL, timeout=self._timeout
            ) as client:
                response = await client.request(
                    method, path, json=payload, headers=self._headers
                )
        except httpx.HTTPError as exc:
            raise YutoriError(f"Yutori request failed: {exc}") from exc

        if response.status_code == 404:
            raise YutoriNotFound(f"Yutori returned 404 for {path}")
        if response.status_code >= 400:
            # Never include headers here — they carry the API key.
            raise YutoriError(
                f"Yutori returned {response.status_code}: {response.text[:500]}"
            )
        if not response.content:
            # DELETE returns an empty body.
            return {}
        try:
            return response.json()
        except ValueError:
            return {}

    async def create_scout(
        self,
        *,
        query: str,
        webhook_url: str,
        output_interval_seconds: int,
        skip_email: bool = True,
        is_public: bool = False,
    ) -> dict[str, Any]:
        """Create the Scout. Note this starts it running immediately, which is
        a billable run — callers are responsible for meaning it.
        """
        payload = {
            "query": query,
            "webhook_url": webhook_url,
            "webhook_format": "scout",
            "output_interval": max(
                output_interval_seconds, MIN_OUTPUT_INTERVAL_SECONDS
            ),
            "output_schema": CANDIDATE_OUTPUT_SCHEMA,
            "skip_email": skip_email,
            # Yutori defaults this to true, which makes the Scout's reports
            # readable by anyone holding its UUID — confirmed against the live
            # API, where GET /updates returned data with no valid key at all.
            # The query embeds the user's interests, so it stays private.
            "is_public": is_public,
        }
        return await self._request("POST", SCOUTS_PATH, payload)

    async def update_scout(
        self,
        scout_id: str,
        *,
        query: str | None = None,
        webhook_url: str | None = None,
        output_interval_seconds: int | None = None,
        is_public: bool | None = False,
    ) -> dict[str, Any]:
        """PATCH an existing Scout. Omitted fields are left unchanged, and this
        does not itself trigger a billable run (prd.md §25).

        `is_public` defaults to False rather than None so that every sync also
        re-asserts privacy — a Scout created before that was enforced gets
        corrected the next time its query is pushed.
        """
        payload: dict[str, Any] = {}
        if query is not None:
            payload["query"] = query
        if webhook_url is not None:
            payload["webhook_url"] = webhook_url
        if is_public is not None:
            payload["is_public"] = is_public
        if output_interval_seconds is not None:
            payload["output_interval"] = max(
                output_interval_seconds, MIN_PATCH_INTERVAL_SECONDS
            )
        return await self._request("PATCH", f"{SCOUTS_PATH}/{scout_id}", payload)

    async def get_scout(self, scout_id: str) -> dict[str, Any]:
        return await self._request("GET", f"{SCOUTS_PATH}/{scout_id}")

    async def list_scouts(self, status: str | None = None) -> dict[str, Any]:
        """All Scouts on the account. Used to spot any we didn't create — an
        orphan left running is the one failure mode that silently costs money.
        """
        suffix = f"?status={status}" if status else ""
        return await self._request("GET", f"{SCOUTS_PATH}{suffix}")

    async def mark_done(self, scout_id: str) -> dict[str, Any]:
        """Archive the Scout and stop it running. Free, and reversible via
        `restart`. A 404 means it is already gone, which is the desired end
        state, so callers treat that as success.
        """
        return await self._request("POST", f"{SCOUTS_PATH}/{scout_id}/done")

    async def restart(self, scout_id: str) -> dict[str, Any]:
        """Bring a stopped Scout back.

        Yutori documents that this endpoint exists and nothing about what it
        does — specifically, not whether it triggers a run immediately or only
        resumes the schedule. Callers read `next_run_timestamp` back from
        `get_scout` afterwards rather than assuming either.
        """
        return await self._request("POST", f"{SCOUTS_PATH}/{scout_id}/restart")

    async def delete_scout(self, scout_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"{SCOUTS_PATH}/{scout_id}")

    async def get_updates(
        self, scout_id: str, *, page_size: int = 20, cursor: str | None = None
    ) -> dict[str, Any]:
        """Every update the Scout has produced.

        The recovery path for the webhook: Yutori delivers at-least-once with 3
        attempts over ~30s and never retries later, so on a scale-to-zero host
        an update can be lost for good. This endpoint can always fetch it back.
        """
        query = f"?page_size={page_size}"
        if cursor:
            query += f"&cursor={cursor}"
        return await self._request("GET", f"{SCOUTS_PATH}/{scout_id}/updates{query}")

    async def get_usage(self, period: str = "30d") -> dict[str, Any]:
        """Account activity for a period: 24h, 7d, 30d or 90d.

        Reports `scout_runs` — Yutori's own count, which is a better basis for
        spend than counting our own requests, since a run we failed to record
        still appears here.
        """
        return await self._request("GET", f"{USAGE_PATH}?period={period}")
