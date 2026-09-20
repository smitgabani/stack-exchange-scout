"""Client for Yutori's Scouting API — the service that finds our candidates.

A **Scout** is an agent hosted by Yutori. You give it a natural-language query
("watch Stack Overflow for Rust questions that…"), and it browses the web on a
repeating schedule, POSTing what it finds to a webhook URL you registered. This
module is the only place in the app that talks to them; everything else goes
through `services/scout_service.py`.

Two facts shape nearly every decision in here:

1. **A run costs $0.35.** Yutori bills per scout-run, and creating a Scout
   starts one immediately. So "create" is never something to do casually, and
   methods that can trigger a run say so.
2. **There is no "run now" endpoint.** A Scout runs on its own
   `output_interval` and nothing else. The only ways to make one run are to
   create it, or to delete and recreate it. `restart` sounds like a third way
   but is not — see its docstring.

The Scout lifecycle, as far as we have been able to establish it:

        create ──────────────► active ──┐
                                 │      │ runs every output_interval,
        (billable run starts)    │      │ POSTing to our webhook
                                 │      │
                          mark_done     │
                                 │      ▼
                                 └───► done ──── restart ───► active
                                         │        (no run)
                                    delete_scout
                                         │
                                         ▼
                                       gone

Yutori's own documentation covers the request and response shapes but says
almost nothing about behaviour, so anything below marked "observed" was learned
by calling the live API and watching what happened.
"""

from typing import Any

import httpx

# Contract confirmed against Yutori's live API reference (docs.yutori.com).
# The repo's prd.md references a docs/yutori-api.md that was never committed,
# so these specifics are recorded here rather than left implicit.
BASE_URL = "https://api.yutori.com"
# Scouts are "scouting tasks" in their URL scheme. Every scout endpoint hangs
# off this path, either directly or as /{scout_id}/something.
SCOUTS_PATH = "/v1/scouting/tasks"
# One-shot deep research. Same $0.35 as a scout-run, but nothing persists
# afterwards — see ADR 0004 for why that makes it the better run primitive.
RESEARCH_PATH = "/v1/research/tasks"
USAGE_PATH = "/v1/usage"

# How often a Scout is allowed to run. Yutori enforces a floor so you cannot
# accidentally bill yourself every few seconds.
MIN_OUTPUT_INTERVAL_SECONDS = 1800
# The PATCH reference documents a 3600 floor while the OpenAPI schema says 1800.
# Using the higher number on update satisfies both readings.
MIN_PATCH_INTERVAL_SECONDS = 3600

# Yutori supports JSON Schema for structured output. Asking for exactly the
# candidate shape prd.md §10 specifies is what keeps us off prose parsing:
# without it the Scout replies with an article of prose, and we would be
# reduced to scraping question URLs out of English with a regex.
#
# Only `url` is required. The rest are best-effort — the model fills in what it
# can, and `enrichment_service` later replaces all of it with authoritative
# values from the Stack Exchange API anyway.
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


class YutoriForbidden(YutoriError):
    """The key is valid but does not own this object.

    Yutori answers `403 "Only the creator of a scout can edit it"` when a Scout
    was created under a different account. Distinct from YutoriError because it
    is not a failure to retry or report as an outage — it means the stored
    reference belongs to somebody else's account and never will resolve under
    this key.
    """


class YutoriNotFound(YutoriError):
    """The Scout is gone. For teardown that counts as success, not failure.

    Split out from YutoriError so callers can tell "you asked about something
    that does not exist" from "the request failed". Deleting or parking an
    already-deleted Scout should not be an error — the desired end state has
    simply been reached by other means.
    """


class YutoriClient:
    """Thin wrapper over the Yutori Scouting API.

    Deliberately not a singleton — the API key is user-supplied and read from
    the database per call site, so the caller constructs this with whatever key
    is currently stored. (Rotating the key in Settings therefore takes effect
    on the next call, with nothing to restart or invalidate.)

    Every method returns Yutori's parsed JSON as a plain dict and raises
    YutoriError on failure. No retries here on purpose: the pipeline stages
    above decide what is worth retrying, and a blind retry on a call that
    creates a Scout would mean paying twice.
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
        """One place where every HTTP call, error and odd response shape lands.

        A fresh httpx client per call rather than a shared one: these calls are
        occasional, and a long-lived pooled connection is a liability on a host
        that gets stopped between requests.
        """
        try:
            async with httpx.AsyncClient(
                base_url=BASE_URL, timeout=self._timeout
            ) as client:
                response = await client.request(
                    method, path, json=payload, headers=self._headers
                )
        except httpx.HTTPError as exc:
            # Connection refused, DNS failure, timeout — no response to inspect.
            raise YutoriError(f"Yutori request failed: {exc}") from exc

        if response.status_code == 404:
            raise YutoriNotFound(f"Yutori returned 404 for {path}")
        if response.status_code == 403:
            raise YutoriForbidden(f"Yutori returned 403: {response.text[:300]}")
        if response.status_code >= 400:
            # Truncated, and never including headers — they carry the API key.
            # The body is kept because Yutori puts the useful part there: it is
            # how we learned restart rejects a live Scout with 400 "Scout is
            # not completed".
            raise YutoriError(
                f"Yutori returned {response.status_code}: {response.text[:500]}"
            )
        if not response.content:
            # DELETE returns an empty body.
            return {}
        try:
            return response.json()
        except ValueError:
            # A 2xx that is not JSON. Nothing useful to hand back, but not a
            # failure either — the operation succeeded.
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

        Observed: the run does not finish instantly. In the one run measured end
        to end, the Scout was created at 04:00 and the update arrived at 04:12.

        Returns the new Scout, whose `id` is what every other method here needs.
        """
        payload = {
            "query": query,
            "webhook_url": webhook_url,
            # "scout" is their generic JSON shape. The alternatives are "slack"
            # and "zapier", which wrap the payload for those products.
            "webhook_format": "scout",
            "output_interval": max(
                output_interval_seconds, MIN_OUTPUT_INTERVAL_SECONDS
            ),
            "output_schema": CANDIDATE_OUTPUT_SCHEMA,
            # We deliver via webhook; Yutori's own email would be a duplicate
            # of the digest this app sends.
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

        This is what keeps the Scout's query in step with the user's topics, and
        it is free — which is why an ordinary profile save can call it but must
        never call `create_scout`.

        `is_public` defaults to False rather than None so that every sync also
        re-asserts privacy — a Scout created before that was enforced gets
        corrected the next time its query is pushed.
        """
        # Built key by key rather than sent wholesale: Yutori treats an absent
        # field as "leave alone", so sending None would be a different request
        # from sending nothing.
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
        """One Scout's current state.

        The useful fields: `status` (active / paused / done),
        `next_run_timestamp`, `update_count`, `last_update_timestamp`, and
        `rejection_reason` — the last being how an out-of-credit account
        becomes visible instead of looking like a Scout that found nothing.

        Observed: `next_run_timestamp` comes back as epoch 0 rather than null
        when nothing is scheduled, so callers must not read it as a real date.
        """
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

        This is how the app keeps costs to what was asked for: between runs the
        Scout sits in `done`, where its schedule cannot fire.
        """
        return await self._request("POST", f"{SCOUTS_PATH}/{scout_id}/done")

    async def restart(self, scout_id: str) -> dict[str, Any]:
        """Bring a Scout back out of `done`.

        Two things learned by calling this, neither of them documented:

        * It only accepts a Scout that is already `done`. On a live one it
          fails with 400 "Scout is not completed", so `mark_done` has to come
          first — restart is the counterpart of done, not a general "start".
        * **It does not trigger a run.** It returns the Scout to `active` with
          nothing scheduled, so the next run is whenever `output_interval` next
          comes round. A run started this way produced no update at all.

        Which means this is not, on its own, a "run now" button. Delete and
        recreate is — see `settings.scout_run_mechanism`.
        """
        return await self._request("POST", f"{SCOUTS_PATH}/{scout_id}/restart")

    async def delete_scout(self, scout_id: str) -> dict[str, Any]:
        """Permanently remove the Scout, along with its update history at
        Yutori's end.

        Used by the "recreate" run mechanism, where delete-then-create is the
        only reliable way to force an immediate run. The cost is that the new
        Scout has no memory of what it reported before, so it reports
        everything it finds rather than only what changed. Our own
        `canonical_url` unique index absorbs the repeats.
        """
        return await self._request("DELETE", f"{SCOUTS_PATH}/{scout_id}")

    async def get_updates(
        self, scout_id: str, *, page_size: int = 20, cursor: str | None = None
    ) -> dict[str, Any]:
        """Every update the Scout has produced.

        The recovery path for the webhook: Yutori delivers at-least-once with 3
        attempts over ~30s and never retries later, so on a scale-to-zero host
        an update can be lost for good. This endpoint can always fetch it back.

        Each update carries `structured_result` (our output_schema, when the
        model complied), `content` (the same thing as prose), `citations` (URLs
        actually visited) and `stats`. Note `timestamp` is epoch
        **milliseconds** here, unlike the ISO strings on scout detail.
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

        Two traps, both observed: `scout_runs` is nested under an `activity`
        object rather than sitting at the top level, and `num_active_scouts`
        counts runs *executing right now*, not Scouts whose status is active —
        it reads 0 for an idle but active Scout.
        """
        return await self._request("GET", f"{USAGE_PATH}?period={period}")

    # ------------------------------------------------------------------
    # Research tasks
    #
    # A research task is the one-shot counterpart to a Scout: you give it the
    # same kind of query and the same output_schema, it investigates once, and
    # then it is over. No lifecycle to manage, nothing left owning the
    # account's money, and nothing that breaks when the API key changes.
    # ------------------------------------------------------------------

    async def create_research_task(
        self,
        *,
        query: str,
        webhook_url: str | None = None,
        skip_email: bool = True,
        user_timezone: str | None = None,
    ) -> dict[str, Any]:
        """Launch a one-time research task. **Billable** — $0.35, same as a
        scout-run.

        Returns `task_id`, a `view_url` for watching it on Yutori's own site,
        and a `status` of queued/running/succeeded/failed. Unlike a Scout, the
        result can always be fetched back with `get_research_task`, so the
        webhook is a convenience rather than the only way to collect what was
        paid for.
        """
        payload: dict[str, Any] = {
            "query": query,
            "output_schema": CANDIDATE_OUTPUT_SCHEMA,
            "skip_email": skip_email,
        }
        if webhook_url:
            payload["webhook_url"] = webhook_url
            payload["webhook_format"] = "scout"
        if user_timezone:
            # Yutori defaults to America/Los_Angeles, and the query asks for
            # "recent" questions — which it resolves in its own timezone.
            payload["user_timezone"] = user_timezone
        return await self._request("POST", RESEARCH_PATH, payload)

    async def get_research_task(self, task_id: str) -> dict[str, Any]:
        """Status and, once finished, results.

        `status` is queued | running | succeeded | failed. `structured_result`
        holds our schema when the model complied, `result` the same findings as
        markdown, and `updates[]` carries citations and stats. This is the
        polling path that makes a lost webhook survivable.
        """
        return await self._request("GET", f"{RESEARCH_PATH}/{task_id}")

    async def list_research_tasks(self) -> dict[str, Any]:
        """Every research task on the account — the orphan check for research,
        equivalent to `list_scouts` for monitors.
        """
        return await self._request("GET", RESEARCH_PATH)
