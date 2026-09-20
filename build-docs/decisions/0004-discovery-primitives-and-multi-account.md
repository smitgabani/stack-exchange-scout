# 0004 — Discovery Primitives, Scout Definitions, and Multi-Account Keys

**Status:** Accepted
**Date:** 2026-09-19
**Scope:** Supersedes `tdd.md` Decision 2 ("Keep one persistent Scout") and reshapes `prd.md` §9, §9.1, §12 and §24.

## Context

The app was built on one assumption, stated in `prd.md` §9 and `tdd.md` Decision 2: **one user, one persistent Yutori Scout, PATCHed whenever topics change.** Building the on-demand run button (`0003`'s successor work) established that this assumption fails in four separate ways.

**1. A Scout is account-owned state, and the key can change.** `credentials` holds a single `yutori_api_key`. The app stores `scouts.external_scout_id` and assumes it will keep resolving. It will not: keys belong to accounts, and a key from a different account — a friend's, say — cannot see, modify or delete a Scout created under the previous one. The failure is a confusing 404, not a clear "that isn't yours".

**2. `restart` does not start a run.** Yutori has no "run now" endpoint. `POST /{id}/restart` looked like one. Measured against the live API, it:
  - rejects a live Scout with `400 "Scout is not completed"`, so it is strictly the counterpart of `/done`; and
  - returns the Scout to `active` with **nothing scheduled** — two attempts produced no update at all, `update_count` unmoved, across two hours.

  `done → restart` is therefore not a run mechanism, and the entire lifecycle built on it is dead code for that purpose.

**3. Creating a Scout to force a run is a bad trade.** It works — it is how the only real update so far was produced — but it churns the Scout's identity on every run, loses the change-baseline that makes a monitor report only *new* things, and leaves a live billable object behind whenever teardown fails.

**4. There is a better primitive, at the same price.** The **Research API** (`POST /v1/research/tasks`) is one-shot by design, costs **$0.35 — identical to a scout-run**, accepts the same `output_schema` and `webhook_url`, emits the same `scout_update` webhook payload, and exposes results by polling (`GET /v1/research/tasks/{id}`) so a lost webhook cannot waste a paid run. Nothing persists at Yutori afterwards, so none of problems 1–3 apply to it.

## Decision

### 1. Two discovery primitives, chosen per run

| | Research task | Scout |
|---|---|---|
| Shape | one-shot | recurring monitor |
| Cost | $0.35 per task | $0.35 per run |
| Lifetime at Yutori | none after completion | until deleted |
| Result retrieval | webhook **and** polling | webhook, or `/updates` |
| Used for | "find me questions now" | unattended background discovery |

A run picks one. Research is the default for anything the user triggers; a Scout is created only when the user explicitly wants continuous monitoring.

### 2. A "Scout" in this product is a local definition, not a remote object

The dashboard's unit is a **scout definition** — a saved, named record holding a query (built from topics or written freeform), configuration and notes. Creating, editing, cloning and deleting definitions is free and touches no external API.

Remote objects are *derived* from a definition and are disposable:

```text
scout_definition  (local, free, durable)
   │
   ├── run once      → research task   → results → deleted by Yutori's own lifecycle
   └── activate      → live Scout      → runs on interval until retired
```

This is what makes multiple saved queries possible, and what decouples "the thing I designed" from "the thing currently costing money".

### 3. Multiple named API keys, with account fingerprinting

`credentials` stops being one row per provider. The app holds any number of named Yutori keys — the user's, a friend's — one of which is active.

Yutori exposes no account identifier, so every remote object we create records an **account fingerprint**: `sha256(api_key)[:16]`. A definition whose live Scout was created under a different fingerprint is shown as unreachable, with an explanation, instead of failing later as a 404. The fingerprint is derived, never reversible, and is not a second copy of the key.

### 4. Deleting a key never deletes what it discovered

Removing a key is a **tombstone**, not a cascade:

- `questions`, `digests` and `challenges` are untouched. They are globally deduplicated by `canonical_url`, and that history is exactly what stops the app rediscovering — and re-paying for — a question the user has already seen.
- Run history is kept and renders the key as deleted.
- Only the stored credential and the app's ability to reach that account's remote objects go away.

Cascade-deleting discovered data would degrade the product every time a key is rotated, which is the opposite of what key management is for.

### 5. Dashboard scope

The Scout dashboard commits to:

- **Definitions CRUD** — create, edit, clone, delete, without running anything.
- **Run history and per-run yield** — per definition: each run, its cost, what it returned, how many became candidates, how many cleared the digest bar.
- **Cost effectiveness** — definitions ranked by yield per dollar, so a query that does not earn its $0.35 is visible.
- **Query builder** — compose from the topic/weight/concept model or write freeform, with a preview of exactly what gets sent.
- **Account management** — add, name, activate and delete API keys, with per-key spend.
- **Live monitor management** — activate a definition as a real Scout, see its schedule and next run, pause or retire it.

## Recovered API facts

Measured against the live API; Yutori documents request and response shapes but almost none of this behaviour.

| Fact | Detail |
|---|---|
| Research task cost | $0.35 — same as a scout-run |
| Free credit | $5 one-time per account |
| Browsing API | $0.015/step (n1.5); no use here, the Stack Exchange API is free and better |
| `restart` preconditions | 400 `"Scout is not completed"` on a live Scout |
| `restart` effect | resumes `active`; **does not run** |
| `next_run_timestamp` | epoch `0`, not null, when nothing is scheduled |
| Update `timestamp` | epoch **milliseconds** (ISO strings elsewhere) |
| `/v1/usage` shape | `scout_runs` nested under `activity`; `num_active_scouts` counts runs *executing*, not scouts whose status is active |
| Webhook deadline | **10 seconds** per attempt, 3 attempts, exponential backoff |
| Webhook event type | `scout_update` for Scouting, Research **and** Browsing alike |
| `is_public` | defaults to **true**; a public Scout's `/updates` is readable with no valid key |

## Consequences

- **`done` / `restart` leave the run path.** The client methods stay for lifecycle management of live monitors, where they are the correct tools.
- **The webhook stops being load-bearing for research runs.** Polling can always recover a result, which matters on a scale-to-zero host against a 10-second delivery deadline.
- **`scouts` becomes two tables** — definitions (local, durable) and remote instances (disposable, fingerprinted) — replacing today's single-row assumption. See the tickets for the migration.
- **Spend becomes attributable.** Every run belongs to a definition and a key, so "what did this query cost me" and "what did this account spend" are both answerable. `/v1/usage` is a cross-check, not the source of truth, given its nesting quirk and its disagreement with scout detail.
- **`prd.md` §9.1's Setup Mode still applies**, but gates *any* paid run rather than a Scout run specifically.
