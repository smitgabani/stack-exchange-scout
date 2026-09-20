# Feature Ticket List — Implementation Roadmap

**Status:** Active backlog. Companion documents: `prd.md` (what/why), `tdd.md` (how), `engineering-log.md` (running narration of each session), `decisions/` (ADRs for significant calls).

This is a from-scratch build: no backend/frontend code exists yet. The roadmap is organized as **vertical slices** — each milestone ships a backend piece *and* its matching frontend page together, so there's always something real to click through at every checkpoint, rather than all backend first and all frontend at the end.

---

## How we work

1. Pick the next ticket(s) from the current milestone below.
2. Branch off `main`: `git checkout -b <ticket-id>-<short-slug>`.
3. Implement — Python/FastAPI concepts get explained as they diverge from Node.js equivalents (type hints vs. TS, Pydantic vs. Zod/Joi, `async def`/ASGI vs. Node's event loop, `Depends()` DI, SQLAlchemy vs. an ORM like Prisma). Anything a genuinely significant decision gets flagged for discussion before proceeding, or an ADR afterward.
4. Commit with [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
5. At a milestone boundary: merge that milestone's branches back to `main` (real merge/rebase practice), run the milestone's **TEST** checkpoint, log the session in `engineering-log.md`, write an ADR if warranted, then hand the milestone's frontend to the user for a click-through and feedback before moving on.
6. Each milestone kicks off with a short system-design framing for its core challenge (noted per milestone below) — that's where system-design concepts land, tied to real code rather than abstract lecture.

**Ticket IDs:** `M<n>-B<k>` (backend), `M<n>-F<k>` (frontend), `M<n>-TEST` (checkpoint).

**Test tags:** 🔒 security · ⚡ performance (lightweight — response-time sanity checks, no load-testing tooling, per the single-user scale of this app) · 🧩 business logic.

---

## Milestone overview

| # | Milestone | System-design theme |
|---|---|---|
| M0 | Foundations & scaffolding | Twelve-factor config, deploy pipelines |
| M1 | Access gate & credential storage | Session-cookie vs. JWT/OAuth tradeoffs |
| M2 | Profile + key onboarding | Encryption at rest, secrets vs. config |
| M3 | Topic & preference management | Server-side validation, never trust the client |
| M4 | Yutori Scout integration | Webhook idempotency, at-least-once delivery |
| M5 | Stack Exchange enrichment, dedup, filtering | Graceful degradation vs. hard failure |
| M6 | Candidate scoring | Deterministic scoring before ML |
| M7 | Digest generation + LLM curator + email | Prompt injection, sync-vs-async processing |
| M8 | Feedback | State machines (question status) |
| M9 | Scout usage tracking + Setup Mode | Cost-gating, safe defaults on timeout |
| M10 | **MVP checkpoint** | End-to-end review |
| M11 | *(post-MVP)* Scheduler | Cron vs. queue vs. event-driven; scale-to-zero vs. schedulers |

Not ticketed here (genuinely post-MVP, revisit after M10): Phase 5 Adaptive Personalization, §31 Interactive Challenge Mode.

---

## M0 — Foundations & Scaffolding

**Goal:** both apps deployed and talking to each other, nothing meaningful built yet.

**Backend**
- `M0-B1` Initialize `backend/` (venv, `pyproject.toml`/`requirements.txt`, FastAPI+SQLAlchemy+Alembic+Pydantic). AC: `uvicorn app.main:app` runs, root returns 200.
- `M0-B2` Folder structure per `tdd.md` §4.1 (`api/`, `services/`, `integrations/`, `models/`, `schemas/`, `repositories/`, `core/`).
- `M0-B3` `core/config.py` — env var loading via Pydantic Settings. AC: missing required var fails fast at startup with a clear error.
- `M0-B4` SQLAlchemy engine/session wired to Supabase (pooler URL). AC: a real `SELECT 1` succeeds against the dev project.
- `M0-B5` Alembic initialized, first (empty) migration. AC: `alembic upgrade head` runs clean.
- `M0-B6` `GET /health`, `GET /ready` (the latter actually checks DB connectivity).
- `M0-B7` Fly.io app + `fly.toml` with `auto_stop_machines`/`auto_start_machines` (`deployment-setup-guide.md` §3.2). AC: `flyctl deploy` succeeds, `/health` reachable publicly.
- `M0-B8` GitHub Actions skeleton (lint + test job only, no deploy yet).

**Frontend**
- `M0-F1` Initialize Next.js (App Router) + TypeScript + TanStack Query. AC: `npm run dev` serves a placeholder page.
- `M0-F2` Vercel project connected and deployed.
- `M0-F3` Placeholder page calls backend `GET /health`, displays the result.

**M0-TEST**
- Nothing to secure or reason about yet — no 🔒/🧩 tests this milestone.
- ⚡ Manual: note cold-start latency on the first request after Fly.io idles the machine — record it as a baseline, no threshold yet.
- Manual verification: `DATABASE_URL`/`APP_SECRET_KEY` etc. are Fly secrets, not committed anywhere; `.env` is gitignored.
- **Frontend click-through:** open the Vercel URL, see "backend: ok".
- ⚠️ Note: the app is public and *unauthenticated* at this point (harmless — nothing sensitive exists yet), but M1 should follow immediately, not be deferred.

---

## M1 — Access Gate & Credential Storage

**Goal:** the app can no longer be used by a stranger who finds the URL.

**Backend**
- `M1-B1` `APP_ACCESS_PASSWORD`/`APP_SECRET_KEY` env vars + config loading.
- `M1-B2` `credentials` table + Fernet encrypt/decrypt helper.
- `M1-B3` `POST /auth/login` — compare password, set signed `HttpOnly`/`Secure` cookie.
- `M1-B4` `POST /auth/logout`.
- `M1-B5` `GET /auth/session`.
- `M1-B6` Gate middleware/dependency applied to all routes except the exempt list (`prd.md` §27.1: `/feedback`, `/scout/confirm/{cycle_id}`, `/webhooks/yutori`, `/health`, `/ready`).

**Frontend**
- `M1-F1` Login page calls `/auth/login`, handles the error state.
- `M1-F2` App shell calls `/auth/session` on load; shows Login vs. app content.

**M1-TEST**
- 🔒 Wrong password rejected; cookie is `HttpOnly`+`Secure`+signed; a tampered cookie is rejected; each exempt route is reachable with no session; every other route 401s without one.
- Manual verification: inspect the real `Set-Cookie` header; confirm the password never appears in any response body or log line.
- **Frontend click-through:** fresh open → Login screen → wrong password shows inline error → correct password enters the app → reload → still logged in → log out → bounced back to Login.

---

## M2 — Profile + Key Onboarding

**Goal:** the single-JSON-document profile exists, and Yutori/Gemini/OpenAI keys are entered (and gated) from the frontend, not env vars.

**Backend**
- `M2-B1` `profile` table (single row, JSONB `data`, `version` int) + migration.
- `M2-B2` `GET /profile` (seeds defaults if none exists).
- `M2-B3` `PATCH /profile` (partial merge, increments `version`).
- `M2-B4` `POST /settings/yutori-key` + `GET /settings/yutori-key/status`.
- `M2-B5` `POST /settings/gemini-key` + `GET /settings/gemini-key/status`.
- `M2-B6` `POST /settings/openai-key` + `GET /settings/openai-key/status`.
- `M2-B7` Dependency: 403s discovery-related routes without a stored Yutori key.
- `M2-B8` Dependency: 403s digest/challenge routes without a stored Gemini key.
- `M2-B9` Reject switching `profile.llm.provider` to `"openai"` without a stored OpenAI key.

**Frontend**
- `M2-F1` Onboarding — Yutori step → `POST /settings/yutori-key`.
- `M2-F2` Onboarding — Gemini step → `POST /settings/gemini-key`.
- `M2-F3` Settings — API keys section reads real `/status` endpoints.
- `M2-F4` Settings — "Rotate"/"Add key" open an input and call the POST endpoints.

**M2-TEST**
- 🔒 Keys never appear in `GET /profile` or any response body in plaintext; `/status` endpoints return boolean only.
- 🧩 `PATCH /profile` version increments exactly once per call; a malformed update (e.g. weight out of 0–100) is 422; switching provider without a key returns a clear error, not a silent no-op.
- Manual verification: read the DB row directly, confirm `encrypted_value` is ciphertext.
- **Frontend click-through:** fresh onboarding, blocked until both keys entered, Settings then shows both connected; add an OpenAI key and switch the active provider.

---

## M3 — Topic & Preference Management

**Goal:** every profile field the PRD says is user-editable actually is, from the UI, with real server-side validation.

**Backend**
- `M3-B1` Topics array validation (name uniqueness, weight 0–100).
- `M3-B2` Preferred/excluded concepts validation.
- `M3-B3` Difficulty min/max validation (`min <= max`, both 1–5).
- `M3-B4` `digest.frequency_days`/`digest.questions` bounds.
- `M3-B5` `question_preferences` validation; `exclude_closed`/`exclude_duplicates` always coerced `true` server-side regardless of input (enforces `prd.md` §14's "always on" rule at the API, not just the UI).

**Frontend**
- `M3-F1` Topics — add/remove/weight wired.
- `M3-F2` Topics — preferred/excluded concept chips wired.
- `M3-F3` Topics — difficulty min/max steppers wired.
- `M3-F4` Topics — digest count/frequency wired.
- `M3-F5` Topics — question-preferences card wired; locked toggles confirmed to match server behavior.
- `M3-F6` Settings — digest frequency/count/difficulty section wired (second surface per `tdd.md` §3.6).

**M3-TEST**
- 🧩 Server rejects/coerces `exclude_closed`/`exclude_duplicates` attempts to turn them off; bounds enforced server-side even if the UI wouldn't send bad values.
- Manual verification: edit the same field from Topics and Settings in two tabs — confirm no silent data loss (last-write-wins is acceptable for MVP; good moment to discuss optimistic-concurrency vs. last-write-wins).
- **Frontend click-through:** full pass through every Topics control; confirm Settings' digest section matches after a save+reload.

---

## M4 — Yutori Scout Integration

**Goal:** real discovery starts flowing into the database.

**Backend**
- `M4-B1` `scouts` table + migration.
- `M4-B2` `integrations/yutori.py` — create/update/get Scout.
- `M4-B3` `query_generator.py` — pure function, profile → query text (unit-testable, no network).
- `M4-B4` `scout_sync` (internal) — fires whenever topics/concepts change; PATCHes the Scout.
- `M4-B5` `POST /scout/sync` — the same `scout_sync` logic, exposed as an explicit endpoint (`prd.md` §24) for manual re-trigger/debugging, not just the automatic on-change path.
- `M4-B6` `POST /webhooks/yutori` — signature verification.
- `M4-B7` `candidate_ingest` — webhook payload → `questions` rows (status=`candidate`), idempotent on question id + Yutori event id.

**Frontend**
- `M4-F1` Settings — "Scout last synced: `<timestamp>`" status line.

**M4-TEST**
- 🔒 Invalid/missing webhook signature → rejected, never processed.
- ⚡ Webhook handler responds fast (assert under ~1s) — acknowledge-then-process pattern discussed here: webhook consumers must not block the sender.
- 🧩 `query_generator` unit tests (topics/concepts/exclusions reflected in output); duplicate webhook delivery creates exactly one row.
- Manual verification: send a crafted test payload via curl, confirm a `candidate` row appears.
- **Frontend click-through:** change a topic, check Settings for an updated sync timestamp.

---

## M5 — Stack Exchange Enrichment, Dedup, Filtering

**Goal:** candidates carry real, verified metadata, and junk never reaches the pool.

**Backend**
- `M5-B1` `integrations/stackexchange.py` — question lookup by id.
- `M5-B2` Enrichment step merges SE fields (score, answer_count, accepted_answer_id, is_closed, tags, dates) into the candidate row.
- `M5-B3` `enrichment_pending` retry path (SE failure ≠ rejection).
- `M5-B4` Dedup on `stackoverflow_question_id` + canonical URL (semantic-similarity dedup stays deferred, per `prd.md` §35).
- `M5-B5` §14 auto-reject filters (closed, previously presented, outside topics, insufficient info).
- `M5-B6` `GET /questions`, `GET /questions/{id}`.

**Frontend**
- `M5-F1` Questions page wired to real `GET /questions` + filters.
- `M5-F2` Question cards reflect real enrichment data (votes, accepted-answer badge, dates).

**M5-TEST**
- 🧩 Dedup test (same id via two webhook events → one row); filter test (a closed question never reaches `GET /questions`); `enrichment_pending` test (mocked SE failure → kept, marked pending, not rejected).
- Manual verification: temporarily break the SE API key, confirm candidates queue as pending instead of vanishing.
- **Frontend click-through:** browse real candidates, spot-check accepted-answer badges/dates against actual Stack Overflow.

---

## M6 — Candidate Scoring

**Goal:** candidates are ranked by the documented weighted formula.

**Backend**
- `M6-B1` `ranking_service.py` — 6-factor weighted formula (`prd.md` §15), pure function.
- `M6-B2` `candidate_rank` endpoint — scores unscored/rescored candidates.
- `M6-B3` Quality-over-quantity guard, tested (not just documented).

**Frontend**
- `M6-F1` Questions page "Match %" reflects real `candidate_score`.

**M6-TEST**
- 🧩 Unit tests per scoring component; zero-topic-match candidate scores near-zero on topic relevance; re-ranking after a profile change updates existing rows, doesn't duplicate.
- Manual verification: eyeball 5–10 real scored candidates for plausibility (inherently a bit subjective).
- **Frontend click-through:** confirm higher Match % candidates intuitively look more relevant.

---

## M7 — Digest Generation + LLM Curator + Email

**Goal:** the core product moment — a real digest, with real challenges, delivered by email.

**Backend**
- `M7-B1` `integrations/gemini.py` behind a provider-agnostic interface.
- `M7-B2` `integrations/openai.py`, same interface, optional.
- `M7-B3` `challenge_service.py` — selects top N, builds the prompt (never includes accepted-answer text), calls the active provider, validates output against schema.
- `M7-B4` Prompt-injection guard (`tdd.md` §9.4).
- `M7-B5` `digests`, `digest_questions`, `challenges` tables + migrations.
- `M7-B6` `POST /digest/generate`.
- `M7-B7` `email_service.py` — Resend integration + template.
- `M7-B8` `POST /digest/send` — sends, marks `presented`.
- `M7-B9` Empty-digest handling (`prd.md` §26) — no threshold-lowering.

**Frontend**
- `M7-F1` Dashboard wired to real digests (cards + empty state).
- `M7-F2` Challenge Detail wired to real content (problem, why-selected, concepts, starting direction).
- `M7-F3` Challenge Detail hints wired to real generated hints (client-side progressive reveal unchanged).

**M7-TEST**
- 🔒 Feed a candidate whose body contains an embedded instruction ("ignore previous instructions...") through the real pipeline — assert the output doesn't comply and contains no solution code; assert accepted-answer text is never present in the outgoing LLM request (inspect the actual request payload).
- ⚡ `digest_generate` for 5 questions completes within an agreed budget (e.g. <30s) — this is the real reason a background worker (M11) eventually matters, since it's synchronous today.
- 🧩 Empty-digest path never lowers thresholds; `digest_send` marks exactly the sent questions `presented`.
- Manual verification: read 2–3 real generated challenges myself, confirm none reveal the solution (judgment call, not a pure assertion).
- **Frontend click-through:** trigger a digest, view the Dashboard, open a Challenge Detail page, reveal all three hints, confirm the SO link, check the actual inbox.

---

## M8 — Feedback

**Goal:** every piece of feedback the PRD defines is capturable and visible in history.

**Backend**
- `M8-B1` `feedback` table + migration.
- `M8-B2` `POST /feedback` — 7 types (`prd.md` §19), updates question `status` where implied.

**Frontend**
- `M8-F1` Questions — Interesting/Skip → `POST /feedback`.
- `M8-F2` Challenge Detail — feedback row → `POST /feedback`.
- `M8-F3` Challenges page wired to real feedback + status history.

**M8-TEST**
- 🧩 Each of the 7 types accepted and recorded; invalid type → 422; a status-implying type (e.g. "solved") updates `status` correctly.
- Manual verification: give feedback from both Questions and Challenge Detail for different questions, confirm both land correctly on Challenges history.
- **Frontend click-through:** mark a candidate Interesting on Questions, later Solved on its Challenge Detail page, confirm Challenges history reflects the final state.

---

## M9 — Scout Usage Tracking + Setup Mode

**Goal:** spend is tracked and gated exactly as designed, with a working Yes/No confirmation loop.

**Backend**
- `M9-B1` `scout_usage_log` table + migration.
- `M9-B2` `scout_confirmations` table + migration.
- `M9-B3` Usage Tracking Service — `should_run`, `record_run`, `estimated_spend`.
- `M9-B4` `request_confirmation` / `resolve_confirmation` / `expire_unanswered_confirmations`.
- `M9-B5` `scout_usage_gate` — Automatic Mode triggers directly; Setup Mode requests confirmation.
- `M9-B6` `POST /scout/confirm/{cycle_id}` (no-login).
- `M9-B7` `GET /scout/usage`.
- `M9-B8` Manual spend-correction (`prd.md` §7.2).
- `M9-B9` Confirmation email template + send.

**Frontend**
- `M9-F1` ScoutConfirm standalone page wired to the real endpoint.
- `M9-F2` Settings — scout mode toggle wired.
- `M9-F3` Settings — spend display + correction control wired.

**M9-TEST**
- 🔒 Regression-test that `/scout/confirm/{cycle_id}` stays reachable without a session (easy to accidentally gate later).
- 🧩 An unanswered confirmation past the next cycle resolves to "no", not stuck pending; switching to Automatic removes confirmation without changing the interval; a manual spend correction is what later estimates build from.
- Manual verification: let a confirmation go unanswered past a cycle boundary in a test scenario, confirm it resolves to skipped.
- **Frontend click-through:** toggle Setup/Automatic; answer a real confirmation link Yes on one cycle, No on another; correct the spend figure and confirm it sticks.

---

## M10 — MVP Checkpoint

Not new tickets — the combined pass:
- Run the full `prd.md` §33 workflow for real, start to finish, once.
- Full security-review pass across the app (SQL injection surface, XSS from untrusted SO content, SSRF surface, secrets handling end-to-end, session/cookie handling, credential encryption).
- Full regression click-through of every frontend page against real data.
- Score against `prd.md` §29 Success Criteria qualitatively (they're 2-week targets, not day-one pass/fail).

---

## M11 — *(Post-MVP)* Scheduler

**Goal:** the manually-triggered endpoints become real scheduled jobs.

**Backend**
- `M11-B1` ADR: resolve the Fly.io autostop-vs-in-process-scheduler conflict — an in-process APScheduler won't fire while the machine is stopped; likely either Fly.io Machines' own scheduled-run support or an external pinger hitting a trigger endpoint.
- `M11-B2` `scout_usage_gate` → real scheduled job.
- `M11-B3` `candidate_rank` → real scheduled job.
- `M11-B4` `digest_generate`/`digest_send` → real scheduled job.
- `M11-B5` Supabase inactivity-pause keep-alive decision + implementation (scheduled ping, or documented accept-the-manual-resume).

**Frontend**
- `M11-F1` Settings — remove/relabel anything implying manual triggering.

**M11-TEST**
- 🧩 Jobs fire unattended over a real multi-day observation window; no double-run if the trigger fires mid-run (idempotency/locking).
- ⚡ The chosen trigger mechanism reliably wakes a stopped Fly.io machine within an acceptable delay.
- Manual verification: wait for a real scheduled cycle, confirm a digest arrives with nobody pressing a button.

---

## M12 — Scout Definitions, Research Runs, and Multi-Account Keys

**Goal:** the Scout stops being one hidden remote object and becomes a managed
workspace — many saved queries, runs you choose the shape of, spend you can
attribute, and API keys you can add and remove without losing what they found.

Design: [ADR 0004](decisions/0004-discovery-primitives-and-multi-account.md).
Supersedes `tdd.md` Decision 2 and reshapes `prd.md` §9, §9.1, §12, §24.

**Backend — data**
- `M12-B1` Migration: `scout_definitions` (name, query_text, query_source `topics|freeform`, config, notes, status `draft|ready|archived`), `scout_instances` (kind `research_task|scout`, external id, `account_fingerprint`, state), `scout_runs` (definition, instance, key, cost, started/finished, outcome). Migrate today's single `scouts` row into one definition plus one instance.
- `M12-B2` `credentials` gains `label`, `is_active`, `account_fingerprint`; drop the one-row-per-provider assumption. Existing rows migrate to labelled, active keys.
- `M12-B3` Deletion is a tombstone: removing a key or definition leaves `questions`, `digests` and `challenges` untouched, and run history renders the removed link. Test asserts a deleted key loses no discovered questions.

**Backend — discovery**
- `M12-B4` Research client: `create_research_task`, `get_research_task`, `list_research_tasks` against `/v1/research/tasks`, with `output_schema` and `webhook_url`.
- `M12-B5` `run_definition(definition, mode)` — one seam, `mode` of `research` (default) or `scout`. Records a `scout_runs` row with cost and fingerprint.
- `M12-B6` Ingest accepts research results from both paths: the `scout_update` webhook (already shared) and polling `GET /v1/research/tasks/{id}`, deduped by the existing `(provider, event_id)` index.
- `M12-B7` Live monitor lifecycle for `kind='scout'`: activate, show schedule, pause, retire — using `mark_done` / `restart` / `delete_scout`, which remain correct for monitors even though they are not a run mechanism.
- `M12-B8` Fingerprint mismatch is surfaced, not swallowed: an instance created under a different key reads as unreachable with an explanation.

**Backend — API**
- `M12-B9` `GET/POST/PATCH/DELETE /scout-definitions[/{id}]`, plus `POST /scout-definitions/{id}/clone` and `/run`.
- `M12-B10` `GET/POST/DELETE /accounts[/{id}]` and `POST /accounts/{id}/activate`.
- `M12-B11` `GET /scout-definitions/{id}/runs` — history, yield and cost per run.

**Frontend**
- `M12-F1` Definitions list: create, clone, archive, delete; draft vs ready; per-definition spend and last run.
- `M12-F2` Definition detail: query builder (topics-derived or freeform) with a preview of exactly what gets sent, config, notes.
- `M12-F3` Run dialog: choose research (one-shot) or scout (monitor), with the cost named before confirming.
- `M12-F4` Run history per definition — cost, questions produced, candidates, how many cleared the digest bar.
- `M12-F5` Cost effectiveness view: definitions ranked by yield per dollar.
- `M12-F6` Accounts page: add, label, activate, delete keys; per-key spend; unreachable-instance warnings.

**M12-TEST**
- 🔒 Deleting a key removes the credential and nothing else — questions, digests and challenges survive, and no question is rediscovered.
- 🔒 No API key or webhook secret appears in any response; `account_fingerprint` is one-way.
- 💸 A run against a definition records exactly one `scout_runs` row with the right cost; a refused concurrent run records none.
- 🧩 An instance created under key A reads as unreachable once key B is active, rather than 404ing.
- 🧩 A research result arriving by webhook and by polling ingests once, not twice.
- Manual: create two definitions, run one as research and one as a monitor, confirm the history, yield and per-key spend read correctly; delete the key and confirm the candidate pool is intact.

**Open question for M12 — settled 2026-09-20**

The first real research task ran (`0d8944ee`, $0.35) and answered all three parts:

- **Result shape:** `structured_result` came back matching the registered `output_schema` exactly — `{"questions": [...]}`, 18 of them, `structured_output_status: succeeded`. The parser needed no changes; the envelope adapter was enough.
- **Duration:** ~19 minutes (04:57 → 05:16), longer than the ~12 a Scout run took. M11's scheduler and the dashboard should both expect twenty-minute latency rather than seconds.
- **Webhook:** never needed. The poll collected the result and `events_awaiting_ingest` never moved, so the webhook either did not arrive or arrived later. Building polling first turned what would have been a lost $0.35 into a non-event — which is the strongest argument for the research primitive, and now evidence rather than prediction.

Downstream, untouched: 38 candidates, all scored, top 71.0. Ingest, enrich and rank handled research output without knowing research tasks exist.
