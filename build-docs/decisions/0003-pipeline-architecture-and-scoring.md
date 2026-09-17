# 0003 — Pipeline Architecture, Webhook Durability, and Scoring Formulas

**Status:** Accepted
**Scope:** M4–M7 (discovery → enrichment → scoring → digest)

## Context

M4–M7 build the entire product loop, and the design docs deliberately leave several things open: `prd.md` §15 fixes the scoring *weights* but calls the sub-formulas "deliberately unspecified"; §35 defers duplicate detection and difficulty estimation as implementation details; and `tdd.md` §10.3 describes a worker/queue that does not exist and is explicitly out of scope until M11. Two further problems surfaced during implementation that the docs could not have anticipated:

- **`docs/yutori-api.md` does not exist.** Six places across `prd.md` and `tdd.md` reference it for Yutori's API contract, pricing, and usage endpoint. The file was never committed. The contract was recovered from Yutori's live reference and is recorded here so the next person doesn't have to.
- **Yutori does not sign its webhooks.** `deployment-setup-guide.md` hedges with "if Yutori supports webhook signing"; their documentation confirms no signature mechanism exists, while `tdd.md` §9.3 requires that the webhook not accept arbitrary candidate data.

This ADR records the five decisions that shape M4–M7, so that the reasoning survives beyond the commit messages.

## Decision

### 1. The webhook is a durable inbox, never a place where work happens

`POST /webhooks/yutori` verifies, inserts the raw payload into `webhook_events`, and returns 200. Nothing is enriched in-request.

The obvious alternative — FastAPI `BackgroundTasks` — is unsafe here specifically. Fly's `kill_timeout` defaults to **5 seconds**, `auto_stop_machines = 'stop'` with `min_machines_running = 0` means the idle timer starts the instant the response flushes, and Yutori retries only 3 times across ~30 seconds and **never redelivers afterwards**. A machine stopping mid-enrichment would lose those candidates permanently and silently. Durability has to come from Postgres, not from the process happening to stay alive.

A useful side effect: stored payloads are replayable, which matters because the shape of Yutori's structured output is still partly unknown.

### 2. Webhook authenticity is a secret in the URL

Since Yutori cannot sign payloads, we generate `YUTORI_WEBHOOK_SECRET`, embed it in the URL registered with them, and compare it with `hmac.compare_digest`. Unconfigured means the endpoint rejects everything — failing closed, because an open candidate-injection endpoint is precisely what `tdd.md` §9.3 warns against. If Yutori ever adds signing, `_verify_token` is the single place to change.

### 3. Idempotency belongs in its own table

`webhook_events` is keyed `UNIQUE (provider, event_id)` on Yutori's `update.id`, claimed with `INSERT … ON CONFLICT DO NOTHING RETURNING id`. `delivery.id` changes per retry attempt and is stored for debugging only.

A `yutori_event_id` column on `questions` was rejected: one update legitimately carries many questions, and the same question legitimately recurs across updates, so a single column cannot express event-level idempotency. Claiming in the database also makes concurrent retries safe, which a read-then-write check would not.

### 4. Pipeline stages communicate only through database state

There is no orchestrator. `questions.status` is the queue:

```
ingest   webhook_events(received)      → questions(enrichment_pending)
enrich   questions(enrichment_pending) → questions(candidate | rejected)
rank     questions(candidate)          → six sub-scores + candidate_score
digest   questions(candidate)          → digests + challenges
send     digests(generated)            → email, questions(presented)
```

Each stage is a `run()` function behind a thin endpoint, returning a uniform `StageResult`. Two rules hold it together: no in-memory handoff between stages (each is independently re-runnable and survives the machine stopping), and decision logic stays pure — `filter_service.evaluate` and `ranking_service.score` take no database and no clock, which is what makes them directly unit-testable. M11 will call the same `run()` functions from a scheduler; that is the whole migration.

**Deviation from the ticket text:** `M4-B7` specifies that ingest writes `status='candidate'`. It writes `enrichment_pending` instead, so that `candidate` means "verified by Stack Exchange and past the filters" and `GET /questions?status=candidate` never returns unverified rows.

### 5. Scoring formulas, and a third guard added after seeing real data

`prd.md` §15's weights are honoured exactly (topic 30, depth 25, opportunity 20, recency 10, quality 10, novelty 5). Each sub-score returns 0–100 and is persisted in its own column so it can later be replaced by a learned model. The formulas are in `ranking_service.py`; the notable choices are that topic relevance returns **0** when nothing matches, and that recency uses a 30-day half-life (90-day on last activity when `prefer_recent` is off).

The digest threshold is `DIGEST_MIN_SCORE = 55`, in config rather than the profile because `prd.md` §26 forbids lowering it to fill a digest — it must not be user-tunable.

Scoring real Stack Overflow data then changed the guard's design. Topic + depth + quality alone total 65, so a famous 2008 question with 51 answers and an accepted answer cleared the threshold despite having nothing left to solve — the exact opposite of what this product is for. Two floors were therefore added alongside the total:

- `topic_relevance >= 40` — stops a deep, well-written, off-topic question riding depth and quality into the inbox.
- `solve_opportunity >= 30` — stops thoroughly-answered questions, regardless of how good they otherwise look.

Calibration against real data now separates cleanly: 0 of 7 ancient-or-off-topic questions eligible (scores 37–66), 8 of 8 recent on-topic ones eligible (74–90).

## Recovered Yutori API contract

Recorded here because `docs/yutori-api.md` does not exist:

- Base `https://api.yutori.com`; create `POST /v1/scouting/tasks`, update `PATCH /v1/scouting/tasks/{id}`.
- Auth is **`X-API-Key`**, not a Bearer token.
- `output_interval` is seconds, minimum 1800. `webhook_url` must be HTTPS. `output_schema` accepts JSON Schema.
- Creating a Scout starts it immediately, which is a **billable run** (~$0.35).
- Webhook body: `{event_type, scout:{id,…}, update:{id, timestamp, has_changes, summary, details_url, report_content}, delivery:{id, attempt}}`.
- Delivery is at-least-once: 3 attempts over ~30s, no later redelivery.

## Consequences

- Candidates survive a machine stop, a crash, or a bad parser, because the raw payload is already committed and replayable.
- Every stage is separately triggerable, which is what makes the manual era workable and the M11 migration small.
- Scoring is deterministic and explainable: six persisted sub-scores mean "why was this chosen?" is answerable from the row.
- The cost of no in-request processing is that candidates do not appear until the enrich stage runs. Until M11 that means pressing a button. Accepted deliberately over the alternative of losing candidates silently.
- The three-part digest guard can produce an empty digest, which is a correct outcome under §26 rather than a bug to fix.
