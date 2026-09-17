from typing import Any

import httpx

# Contract confirmed against Yutori's live API reference (docs.yutori.com).
# The repo's prd.md references a docs/yutori-api.md that was never committed,
# so these specifics are recorded here rather than left implicit.
BASE_URL = "https://api.yutori.com"
SCOUTS_PATH = "/v1/scouting/tasks"
MIN_OUTPUT_INTERVAL_SECONDS = 1800

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

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(base_url=BASE_URL, timeout=self._timeout) as client:
                response = await client.request(method, path, json=payload, headers=self._headers)
        except httpx.HTTPError as exc:
            raise YutoriError(f"Yutori request failed: {exc}") from exc

        if response.status_code >= 400:
            # Never include headers here — they carry the API key.
            raise YutoriError(f"Yutori returned {response.status_code}: {response.text[:500]}")
        return response.json()

    async def create_scout(
        self,
        *,
        query: str,
        webhook_url: str,
        output_interval_seconds: int,
        skip_email: bool = True,
    ) -> dict[str, Any]:
        """Create the Scout. Note this starts it running immediately, which is
        a billable run — callers are responsible for meaning it.
        """
        payload = {
            "query": query,
            "webhook_url": webhook_url,
            "webhook_format": "scout",
            "output_interval": max(output_interval_seconds, MIN_OUTPUT_INTERVAL_SECONDS),
            "output_schema": CANDIDATE_OUTPUT_SCHEMA,
            "skip_email": skip_email,
        }
        return await self._request("POST", SCOUTS_PATH, payload)

    async def update_scout(
        self,
        scout_id: str,
        *,
        query: str | None = None,
        webhook_url: str | None = None,
        output_interval_seconds: int | None = None,
    ) -> dict[str, Any]:
        """PATCH an existing Scout. Omitted fields are left unchanged, and this
        does not itself trigger a billable run (prd.md §25).
        """
        payload: dict[str, Any] = {}
        if query is not None:
            payload["query"] = query
        if webhook_url is not None:
            payload["webhook_url"] = webhook_url
        if output_interval_seconds is not None:
            payload["output_interval"] = max(output_interval_seconds, MIN_OUTPUT_INTERVAL_SECONDS)
        return await self._request("PATCH", f"{SCOUTS_PATH}/{scout_id}", payload)

    async def get_scout(self, scout_id: str) -> dict[str, Any]:
        return await self._request("GET", f"{SCOUTS_PATH}/{scout_id}")
