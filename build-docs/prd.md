# PRD — Personal Stack Overflow Challenge Scout

**Product name:** Stack Overflow Challenge Scout

**Status:** MVP specification

**Version:** 1.0

**Primary user:** A developer who enjoys solving Stack Overflow questions but spends too much time finding worthwhile questions.

---

# 1. Product Summary

Build a personal AI-powered system that continuously discovers interesting Stack Overflow questions based on the user's current technical interests, filters and ranks them, and every three days presents a small set of high-quality questions as personalized programming challenges.

The system uses:

* **Yutori Scout** for continuous web discovery and monitoring
* **Stack Exchange API** for deterministic Stack Overflow metadata/filtering
* **A database** for deduplication, history, scoring, and user feedback
* **An LLM** for challenge curation and presentation (see §23 for the current provider)
* **Email** initially as the delivery mechanism

The system should make the user's workflow:

> **Open challenge → understand problem → solve it yourself → optionally compare/evaluate afterward**

rather than:

> Search Stack Overflow → browse hundreds of questions → decide what is interesting → finally solve something.

---

# 2. Problem

The user enjoys solving real-world programming problems from Stack Overflow.

The problem is not a lack of available questions. Stack Overflow contains millions of questions.

The problem is **discovery cost**.

The user currently has to:

1. Search Stack Overflow.
2. Try different keywords/tags.
3. Open individual questions.
4. Determine whether the question is interesting.
5. Determine whether it is too easy or too difficult.
6. Determine whether it already has a good answer.
7. Remember which questions have already been seen.
8. Repeat this process whenever they want another problem.

This creates enough friction that the user often spends more time **finding problems than solving them**.

---

# 3. Product Goal

Automatically provide the user with a small number of high-quality programming problems that they are likely to enjoy solving.

### Primary success criterion

The user should be able to spend almost all of their available time **solving questions**, rather than searching for questions.

### Secondary goals

* Allow the user to change their interests easily.
* Avoid repeatedly presenting the same question.
* Prefer questions that provide a genuine intellectual challenge.
* Avoid questions that are trivial, closed, duplicates, homework, or already completely solved.
* Learn from the user's feedback over time.
* Present questions without spoiling the solution.

---

# 4. Non-Goals

The MVP will **not**:

* Automatically answer Stack Overflow questions.
* Automatically post answers to Stack Overflow.
* Automatically generate answers for the user.
* Replace Stack Overflow.
* Build a general-purpose search engine.
* Attempt to monitor every Stack Overflow question.
* Automatically change the user's interests without explicit permission.
* Automatically browse private accounts in the MVP.
* Build a mobile app in the MVP.

---

# 5. Core User Experience

Every three days the user receives a digest by email, and can also see the questions for each 3-day span on the web application:

> **Your Stack Overflow Challenges**

with approximately 3–5 selected questions.

Each question contains:

* Title
* Stack Overflow link
* Tags
* Short problem description and how to aproach it
* Why it was selected
* Estimated difficulty
* Relevant concepts
* Optional hints
* Existing answer count
* Whether an accepted answer exists
* Date posted

The solution must **not** be revealed.

Example:

---

### Challenge #1 — Async Python

**Difficulty:** 4/5

**Problem**

A Python application uses `asyncio.gather()`, but operations that should run concurrently appear to execute sequentially.

**Why this was selected**

This looks like a genuine debugging problem involving concurrency rather than a syntax issue. There is currently no accepted answer.

**Concepts**

* asyncio
* event loop
* blocking operations
* concurrency

**Start here**

Inspect what happens inside each coroutine before assuming `gather()` itself is responsible.

**Hints**

<details>Hint 1</details>  
<details>Hint 2</details>  
<details>Hint 3</details>

**Stack Overflow:** Open question

**Feedback:** 👍 Interesting | 👎 Not interesting | Too easy | Too hard

---

# 6. System Architecture

```text
                       ┌───────────────────┐
                       │   User Profile    │
                       │                   │
                       │ Topics            │
                       │ Preferences       │
                       │ Difficulty        │
                       │ Exclusions        │
                       └─────────┬─────────┘
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Query Generator   │
                       └─────────┬─────────┘
                                 │
                                 ▼
                       ┌───────────────────┐
                       │   Yutori Scout    │
                       │                   │
                       │ Runs every        │
                       │ scout.interval_days│
                       └─────────┬─────────┘
                                 │
                              webhook
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Candidate Store   │
                       └─────────┬─────────┘
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Filtering/Scoring │
                       └─────────┬─────────┘
                                 │
                         every 3 days
                                 │
                                 ▼
                       ┌───────────────────┐
                       │  LLM Curator      │
                       │                   │
                       │ Challenge format  │
                       └─────────┬─────────┘
                                 │
                                 ▼
                       ┌───────────────────┐
                       │       Email or visible on frontend web application      │
                       └─────────┬─────────┘
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ User Feedback     │
                       └─────────┬─────────┘
                                 │
                                 └──────────► User Profile
```

---

# 7. Components

## 7.1 User Profile

The user profile is the **source of truth for preferences**.

Yutori should not be the canonical storage location for preferences.

### MVP schema

```json
{
  "topics": [
    {
      "name": "python",
      "weight": 100
    },
    {
      "name": "fastapi",
      "weight": 100
    },
    {
      "name": "postgresql",
      "weight": 70
    }
  ],

  "preferred_concepts": [
    "debugging",
    "performance",
    "architecture",
    "async",
    "database design"
  ],

  "excluded_concepts": [
    "homework",
    "basic syntax",
    "installation-only problems"
  ],

  "difficulty": {
    "minimum": 3,
    "maximum": 5
  },

  "question_preferences": {
    "prefer_unanswered": true,
    "max_answers": 3,
    "prefer_recent": true,
    "exclude_closed": true,
    "exclude_duplicates": true
  },

  "digest": {
    "frequency_days": 3,
    "questions": 5
  },

  "scout": {
    "mode": "setup",
    "confirm_before_run": true,
    "interval_days": 3
  },

  "llm": {
    "provider": "gemini"
  }
}
```

`scout.mode` is either `"setup"` or `"automatic"`. See §9.1 for what each mode means and when the system should switch between them.

`llm.provider` is either `"gemini"` (default) or `"openai"`. See §7.3 for what each means and the key requirements behind switching.

---

## 7.2 Usage Tracker

Yutori's Scouting API is billed per run ($0.35/run at the time of writing) and starts from a **one-time** signup credit, not a recurring one. Yutori does not expose a live dollar credit balance through its API — its `GET /v1/usage` endpoint reports request/rate-limit counts (e.g. `scout_runs` per period), not remaining credit.

The system requires the user to supply their own Yutori API key through the frontend. On startup, if no valid key is stored, the application blocks all Scout-related functionality and prompts the user to enter their Yutori API key; discovery only becomes available once a key has been received and stored. See §27 (Security) for how this user-supplied key is stored safely, and §12 (`credentials` table) / §24 (`/settings/yutori-key`) for the mechanics.

The system must therefore track its own estimate of spend and should provide visual information through the frontend application.

* Maintain a persistent counter of every Scout run the application has triggered (it already needs to record each run for dedup/idempotency purposes — see §26).
* Estimate cumulative spend as `runs_triggered × $0.35`.
* Optionally cross-check against Yutori's `GET /v1/usage` activity figures for the current period as a sanity check, but treat the local counter as authoritative since Yutori's API does not return an all-time count or a dollar balance.
* Surface the estimate (e.g. "$2.45 of $5.00 free credit used") wherever the system asks the user whether to run the Scout (§9.1).
* The user can cross-check the estimate against the exact figure on the Yutori platform. If they differ, the user can manually correct the stored estimate through the frontend — the `runs_triggered × $0.35` calculation keeps running from the corrected baseline going forward.

---

## 7.3 LLM Provider & Key Management

Like the Yutori key (§7.2), the Gemini and OpenAI API keys are supplied by the user through the frontend rather than configured as environment variables — extending the same "enter your own key" pattern to every third-party API key the user might need to rotate or replace. This supersedes the original env-var-only plan for these two keys (§23, §27).

* **Gemini is required for the MVP.** On startup, if no Gemini key is stored, the application blocks all challenge-curation/digest functionality (`digest_generate`/`digest_send`, §25) and prompts the user to enter it — the same blocking pattern as the Yutori key (§7.2). The two keys can be entered in either order; discovery and curation are gated independently.
* **OpenAI is optional** — a documented, swappable alternative for a future version, not required for the MVP loop to function. Entering an OpenAI key does not by itself change which provider is active.
* `llm.provider` in the profile (§7.1) controls which provider is actually called — `"gemini"` (default) or `"openai"`. Switching it to `"openai"` requires an OpenAI key to already be stored; the system should reject the switch otherwise rather than silently falling back to Gemini (§26).
* Both keys are stored exactly like the Yutori key: encrypted at rest in the `credentials` table (§12), never in the `profile` document, never logged, never returned in plaintext by any API response. See §27 for the shared storage/encryption mechanics, which now cover all three user-supplied keys uniformly.
* Endpoints (§24): `POST /settings/gemini-key`, `GET /settings/gemini-key/status`, `POST /settings/openai-key`, `GET /settings/openai-key/status` — mirror the existing Yutori-key endpoints exactly.

---

# 8. Topic Management

The user must be able to modify topics without creating a new Scout.

### Example

Current:

```text
Python
FastAPI
PostgreSQL
```

User changes to:

```text
Python
LLMs
Redis
Kubernetes
```

The system must:

1. Save the new profile.
2. Increment the profile version.
3. Generate a new Yutori query.
4. PATCH the existing Scout.
5. Preserve historical questions.
6. Apply the new profile to future discovery.

Topic management has a dedicated frontend UI in the MVP scope, not a later add-on — see §22 (Topic Update UX) for the design and §30 Phase 6 for where it sits in the build sequence.

### Important

Changing topics should **not delete previously discovered questions**.

Questions already in the database retain their historical profile version.

---

# 9. Yutori Scout

Yutori is responsible for **web discovery**, not preference management.

The Scout runs on the cadence configured in `scout.interval_days` (§7.1) regardless of mode — every 3 days by default; setting `interval_days = 1` produces daily runs. Mode does not change the cadence, only whether a run requires confirmation: in **Automatic Mode** (§9.1) each cycle's run fires without confirmation, while during **Setup Mode** it still requires a user Yes/No before firing.

### Responsibilities

* Search Stack Overflow/web for relevant questions.
* Identify potentially interesting questions.
* Return structured candidate information.
* Avoid solving the questions.
* Detect newly discovered questions.

### Scout query

The query should be generated dynamically from the user profile.

Conceptual template:

```text
Monitor Stack Overflow for newly posted or recently active
questions that match my current technical interests.

Current topics:
{TOPICS}

Preferred concepts:
{PREFERRED_CONCEPTS}

Avoid:
{EXCLUDED_CONCEPTS}

Prefer:
- intermediate/advanced questions
- genuine debugging or reasoning problems
- questions with enough information to investigate
- questions with few existing answers
- questions without a clearly complete accepted solution
- recent questions

Avoid:
- homework
- trivial syntax questions
- installation-only questions
- duplicates
- closed questions
- opinion-only questions

Do not solve the questions.

Return only candidate questions and structured metadata.
```

The query should be regenerated whenever the user profile changes.

Yutori supports updating an existing Scout's query through its Scout PATCH API. ([docs.yutori.com](https://docs.yutori.com/reference/scouts-patch?utm_source=chatgpt.com))

## 9.1 Setup Mode — Usage-Gated Scout Runs

### Why

Yutori's Scouting API is billed per run and starts from a **one-time** signup credit (not a recurring monthly one — see `docs/yutori-api.md` §7). At the start of use, the user's topics and preferences are still being tuned, so unconfirmed automatic Scout runs — even at the default 3-day cadence — would burn through that one-time credit while the profile is still changing, before the system has proven it's finding useful questions.

### Behavior

The system starts in **Setup Mode** (`scout.mode = "setup"` in the profile, §7.1):

1. The Scout is triggered on the **digest cadence** (`scout.interval_days`, default 3 — matched to `digest.frequency_days`), the same cadence used in every mode (§9) — Setup Mode doesn't use a different interval, it adds a confirmation step.
2. Before each cycle's Scout run (create, or PATCH-and-run for an existing Scout), the system does **not** trigger it automatically. It first:
   * Checks estimated usage/spend (§7.2 Usage Tracker).
   * Sends the user a confirmation request — for the MVP, an email with **Yes / No** links, or on the frontend with a conformation request following the same no-login-required pattern as feedback links (§19): e.g. `https://yourapp.com/scout/confirm/{cycle_id}?value=yes`.
   * Only calls the Yutori API (create/PATCH the Scout, or otherwise trigger discovery for that cycle) if the user confirms **Yes**.
   * If the user does not respond or replies **No**, the system skips that cycle's Scout run and reuses whatever candidates are already in the database for the next digest.
3. Every confirmation email/response includes the current estimated spend (e.g. "$1.75 of $5.00 free credit used — run the Scout again this cycle?"), so the decision is informed.

### Switching to Automatic Mode

Once the user is satisfied with their profile/topics and no longer wants to confirm every cycle, they set `scout.mode = "automatic"` (via `PATCH /profile`, §24). or on the frontend application.

In Automatic Mode:

* The Scout continues to run on the same `scout.interval_days` cadence — Automatic Mode does not change *how often* the Scout runs, only that it no longer requires confirmation.
* Runs are triggered without a confirmation step, per the original always-on discovery model.
* The Usage Tracker keeps recording estimated spend regardless of mode, so the user can always see cumulative cost even after automation is turned on.

### Important

Setup Mode changes *when and whether* a Scout run happens — it does not change the Scout's query, filtering, or scoring logic. A skipped cycle is not an error; it simply means no new candidates are added to the pool for that cycle, per §26 ("Do not lower quality thresholds simply to fill the digest" applies here too — a skipped Scout run is preferable to spending free credit before the profile is ready).

---

# 10. Scout Output

Yutori should return structured candidate data.

### Candidate schema

```json
{
  "question_id": "123456",
  "title": "Example question",
  "url": "https://stackoverflow.com/questions/123456",
  "tags": [
    "python",
    "asyncio"
  ],
  "created_at": "2026-09-01T12:00:00Z",
  "answer_count": 1,
  "has_accepted_answer": false,
  "problem_summary": "...",
  "difficulty": 4,
  "interesting_reason": "..."
}
```

Yutori supports structured output schemas for Scouts. ([docs.yutori.com](https://docs.yutori.com/reference/scouts-create?utm_source=chatgpt.com))

---

# 11. Stack Exchange API Integration

Yutori should not be the only source of truth for objective Stack Overflow metadata.

The system should retrieve/verify:

* Question ID
* Title
* URL
* Tags
* Creation date
* Last activity
* Answer count
* Accepted answer
* Score
* Closed status
* Duplicate status where available

The Stack Exchange API provides question-specific endpoints and filtering capabilities. ([api.stackexchange.com](https://api.stackexchange.com/docs/questions?utm_source=chatgpt.com))

### Reason

Use:

**Yutori → semantic discovery**

and:

**Stack Exchange API → deterministic metadata/filtering**

This improves reliability.

---

# 12. Candidate Database

The MVP uses PostgreSQL, hosted on Supabase (§34) — chosen over the original SQLite plan once hosting research (§34/§35) showed that keeping the database off the backend's own disk lets the backend run stateless, which avoids the paid persistent-volume requirement SQLite would have forced. This also brings the PRD in line with `tdd.md`, which already specified PostgreSQL.

## `questions`

```text
id
stackoverflow_question_id
url
title
tags
created_at
last_activity_at
answer_count
accepted_answer
score

problem_summary
difficulty
interesting_reason

first_seen_at
last_seen_at

profile_version
candidate_score

status
```

### Status values

```text
candidate
enrichment_pending
selected
presented
solved
skipped
rejected
```

`enrichment_pending` was added after the fact (T6/T14): a transient state for when Stack Exchange enrichment temporarily fails and needs a retry, rather than the candidate being wrongly rejected. It was implemented in code before being documented here — this entry closes that gap.

## `scout_usage_log`

Backs the Usage Tracker (§7.2). One row per Scout run the application actually triggers (not per Yutori API call in general — just Scout create/PATCH-and-run events).

```text
id
triggered_at
mode              -- "setup" | "automatic", the mode active at trigger time
estimated_cost    -- always 0.35 at current pricing; stored per-row rather than hardcoded so a future price change doesn't require backfilling history
```

Cumulative estimated spend is `SUM(estimated_cost)` over this table. This is the authoritative spend figure (§7.2) since Yutori's API does not expose an all-time dollar balance.

## `scout_confirmations`

Backs Setup Mode's Yes/No gate (§9.1). One row per digest cycle while `scout.mode = "setup"`. This row's `id` **is** the `cycle_id` referenced by `POST /scout/confirm/{cycle_id}` (§24) — this table closes a gap in earlier drafts, which referenced a `cycle_id` without ever specifying where it was stored.

```text
id
requested_at
responded_at        -- nullable
response            -- "yes" | "no" | null (no response yet)
scout_usage_log_id  -- nullable FK, set only once a "yes" actually results in a triggered run
```

An unanswered row by the time the next cycle's `scout_usage_gate` check runs (§25) is treated as `"no"` — the cycle is skipped, not retried indefinitely.

## `credentials`

Stores every user-supplied API key: Yutori (§7.2), Gemini, and OpenAI (§7.3, §27). Deliberately kept out of the `profile` JSON so none of them are ever returned by `GET /profile`.

```text
id
key_name          -- "yutori_api_key" | "gemini_api_key" | "openai_api_key"
encrypted_value   -- ciphertext, encrypted with APP_SECRET_KEY (env var, never stored here)
created_at
updated_at
```

---

# 13. Deduplication

A question must never appear twice in a digest.

Primary deduplication key:

```text
stackoverflow_question_id
```

Secondary protection:

* canonical URL
* semantic similarity of title/question text

If a question has already been presented, it should not be selected again unless the user explicitly requests it. 

---

# 14. Candidate Filtering

Before scoring, remove obvious bad candidates.

### Automatically reject

* Closed questions
* Duplicates
* Questions previously presented
* Questions outside selected topics
* Homework
* Questions with insufficient information
* Spam
* Opinion-only questions

### Penalize

* Existing accepted answer
* Many answers
* Very old question
* Very low question quality
* Extremely easy problem

---

# 15. Candidate Scoring

Each candidate receives a score from 0–100.

### Initial scoring model

| Criterion            |  Weight |
| -------------------- | ------: |
| Topic relevance      |      30 |
| Technical depth      |      25 |
| Opportunity to solve |      20 |
| Recency              |      10 |
| Question quality     |      10 |
| Personal novelty     |       5 |
| **Total**            | **100** |

The exact algorithm can initially be simple.

The system should prioritize **quality over quantity**.

If only two excellent questions are found, send two rather than five poor questions.

---

# 16. Three-Day Digest

Every three days:

1. Retrieve all eligible candidates.
2. Remove previously presented questions.
3. Score candidates.
4. Select the top N.
5. Send selected candidates to the LLM.
6. Generate challenge presentations.
7. Save the digest.
8. Send email.
9. The frontend should be modified with a new entry for the time period with all the previous digests.
10. Mark questions as `presented`.

Default:

```text
5 questions / digest
```

Already configurable in the MVP via `digest.questions` in the user profile (§7.1) and the Settings/Topics UI (§22) — not deferred to a later phase. Per §15, quality still takes priority over hitting this number exactly: fewer questions may be sent if fewer meet the bar.

---

# 17. LLM Challenge Curator

The LLM's job is to **transform a selected question into a challenge**, not solve it.

### System instruction

```text
You are a programming challenge curator.

The user wants to solve real Stack Overflow problems themselves.

For each supplied question:

1. Explain the problem concisely.
2. Identify the technical concepts involved.
3. Explain why the question is interesting.
4. Estimate difficulty.
5. Give the user a useful starting direction.
6. Provide progressive hints.
7. Never reveal the solution.
8. Never provide solution code.
9. Never summarize or reproduce existing Stack Overflow answers.
10. Preserve the original Stack Overflow URL.

The purpose is to help the user solve the problem,
not to solve it for them.
```

---

# 18. Hint System

Each challenge should have three levels.

### Hint 1 — Direction

Points toward the relevant area.

### Hint 2 — Concept

Identifies the important technical concept.

### Hint 3 — Strong hint

Gets close to the solution without actually providing it.

The initial email should hide the hints behind expandable sections where possible.

---

# 19. User Feedback

Each presented question should support:

```text
👍 Interesting
👎 Not interesting
⭐ Loved it
⏭ Too easy
🧠 Too hard
✓ Solved
⏹ Skipped
```

For MVP, email links can point to simple feedback endpoints and the frontend should be able to present those links and user should be able to interect. 

Example:

```text
https://yourapp.com/feedback/question/123?value=interesting
```


---

# 20. Personalization Engine — Phase 2

The system should eventually learn from feedback.

Example:

The user repeatedly likes:

* concurrency
* performance
* distributed systems

and repeatedly skips:

* CSS
* basic Python
* installation problems

The system gradually modifies topic/concept weights.

### Important constraint

Automatic personalization should **adjust ranking**, not silently change explicit user topics in the MVP.

For example:

```text
Explicit topics:
Python
PostgreSQL
Redis
```

can remain unchanged while the system learns:

```text
Likes:
Performance +++
Debugging +++
Architecture ++

Dislikes:
Syntax ---
Installation ---
```

---

# 21. Email

The digest is sent to a single recipient address, configured via the `DIGEST_RECIPIENT_EMAIL` environment variable (§27) — since there's only ever one user, this is a deploy-time setting, not a database field or profile setting.

### Subject

```text
Your Stack Overflow Challenges — September 5
```

### Structure

```text
Your Stack Overflow Challenges

5 questions selected for you.

────────────────────────

#1 Async Python
Difficulty: 4/5
Tags: python, asyncio

Problem
...

Why it's interesting
...

Start here
...

[Open Question]

👍 Interesting   👎 Skip   Too Easy   Too Hard

────────────────────────

#2 PostgreSQL
...

────────────────────────

#3 ...
```

The email should be concise.

The user should be able to understand the challenge in under 60 seconds and then immediately start solving.

---

# 22. Topic Update UX

**Update (Phase 6, `frontend/`):** the web UI described below has now been built — a Next.js app with the `/topics` page implementing exactly this, plus the rest of `design.md` §3's page set (`/`, `/questions`, `/challenges`, `/challenge/:id`, `/settings`). Direct `PATCH /profile` calls (or the original config-file idea) still work identically underneath; the UI is a client of the same API, not a replacement for it. See `frontend/README.md` for what's implemented versus deliberately simplified (notably: no multi-user accounts, since the backend has no multi-user concept to authenticate against — though the app does sit behind the shared-password access gate, §27.1).

MVP originally used a simple configuration file, or direct API calls.

That's what "later" meant — the web UI below.

### Desired UI

```text
MY INTERESTS

Topics

[x] Python        100%
[x] FastAPI        80%
[x] PostgreSQL     60%
[ ] Kubernetes
[ ] Redis

Preferred concepts

[x] Debugging
[x] Performance
[x] Architecture
[x] Async

Avoid

[x] Homework
[x] Beginner syntax
[x] Installation

Difficulty

[3 ────────●── 5]

Questions per digest

[ 5 ]

Frequency

[ Every 3 days ]

             SAVE
```

Saving triggers:

```text
Profile update
      ↓
New profile version
      ↓
Generate Scout query
      ↓
PATCH Scout
```

---

# 23. MVP Technology Stack

### Backend

Python + FastAPI

### Frontend (Phase 6)

Next.js (App Router) + TypeScript + TanStack Query. No user accounts/multi-user login — the backend has no multi-user concept at all (this is a personal, single-user tool per this document's own framing throughout) — but the app is protected by a single shared-password access gate (§27.1), not left fully open. See `frontend/README.md` for the no-multi-user rationale.

### Database

**PostgreSQL, hosted on Supabase** (§34) — the MVP originally planned SQLite; that decision was superseded once hosting research showed a stateless backend + managed Postgres avoids the paid persistent-volume Fly.io/Render would otherwise require for a SQLite file (§34, §35). This also matches `tdd.md`, which specified PostgreSQL from the start.

### Discovery

Yutori Scout

### Metadata

Stack Exchange API

### LLM

**Gemini (`gemini-3.1-flash-lite`) is required for the MVP** — see `docs/gemini-api.md` for why (Gemini's free tier let the whole system run at effectively $0 during initial development). **OpenAI is an optional, swappable alternative** for a future version (`docs/openai-api.md`), not required for the MVP loop — the curator's integration layer was deliberately kept isolated for exactly this kind of provider swap. Both keys are entered by the user through the frontend rather than set as environment variables (§7.3, §27) — this is a change from the original env-var-only plan.

### Email

**Implemented with:** Resend, chosen for its simple REST API matching the integration style already used for Yutori/Stack Exchange. Any transactional email provider was originally left open, and remains swappable.

### Scheduling

**Not yet implemented.** Cron/Celery/APScheduler/managed-scheduler all remain future work — every recurring job in this system (`scout_usage_gate`, `digest_generate`, `digest_send`) is currently a manually-triggered API endpoint, not something that runs on its own. Tracked in `build-docs/featuresticketlist.md`'s known gaps.

### Hosting

The MVP should not require Kubernetes or complex infrastructure. Hosting is broken out per component in §34 (Hosting & Deployment): Fly.io for the backend and Supabase for the database, chosen together specifically so the backend can stay stateless (§34/§35).

---

# 24. API Endpoints

The application should expose approximately:

```text
POST   /webhooks/yutori

GET    /profile
PATCH  /profile

POST   /scout/sync
GET    /scout/usage
POST   /scout/confirm/{cycle_id}

POST   /settings/yutori-key
GET    /settings/yutori-key/status

POST   /settings/gemini-key
GET    /settings/gemini-key/status

POST   /settings/openai-key
GET    /settings/openai-key/status

POST   /auth/login
POST   /auth/logout
GET    /auth/session

GET    /questions
GET    /questions/{id}

POST   /digest/generate
POST   /digest/send

POST   /feedback

GET    /health
GET    /ready
```

`GET /scout/usage` returns the current estimated spend (§7.2). `POST /scout/confirm/{cycle_id}` is the no-login endpoint the Setup Mode confirmation email links to (§9.1) — takes a `value=yes|no` query param, same pattern as `/feedback`.

`POST /settings/yutori-key`, `/settings/gemini-key`, and `/settings/openai-key` each accept the corresponding user-supplied API key, encrypt it, and store it in the `credentials` table (§12, §7.3, §27) — none of them go through `PATCH /profile`. The matching `GET .../status` endpoints return only whether a key is currently set (boolean), never the key itself; the frontend uses these to decide whether to show the startup key-entry prompts (§7.2, §7.3).

`POST /auth/login` accepts the shared access password and, on success, sets a signed session cookie (§27); `POST /auth/logout` clears it; `GET /auth/session` reports whether the current request is authenticated, so the frontend knows whether to show the lock screen or the app. These three, along with `/feedback`, `/scout/confirm/{cycle_id}`, `/webhooks/yutori`, `/health`, and `/ready`, are the only endpoints that don't require a valid session (§27) — everything else does.

`GET /health` and `GET /ready` are unauthenticated liveness/readiness checks, used by the hosting platform and by `build-docs/deployment-setup-guide.md`'s deploy verification step.

---

# 25. Core Internal Jobs

The jobs below describe the system's logical recurring behavior. Per §23 (Scheduling), none of them currently run on an actual scheduler — each is invoked via its corresponding manually-triggered API endpoint (§24) until a scheduler is implemented. "Runs daily" / "runs every three days" describes the intended cadence once scheduling exists, not current behavior.

### `scout_sync`

Runs when the profile changes.

```text
Load profile
→ Generate Scout query
→ PATCH Yutori Scout
```

`scout_sync` only updates the Scout's *query* — it does not decide whether/when the Scout should actually run next. That decision belongs to `scout_usage_gate` below.

### `scout_usage_gate`

Runs on `scout.interval_days` (§9.1) in **both** modes — every 3 days by default (set `interval_days = 1` for daily runs) — independent of `digest_generate`'s own timer even though they usually share the same cadence. Mode changes only whether confirmation is required, not how often this job runs.

```text
Load profile
→ Compute estimated spend (§7.2)
→ If mode == "automatic": trigger Scout run directly
→ If mode == "setup": send confirmation email, wait for /scout/confirm response
    → "yes": trigger Scout run
    → "no" or no response by the next cycle: skip this cycle, log it, do nothing
```

### `candidate_ingest`

Triggered by Yutori webhook.

```text
Receive results
→ Validate
→ Enrich with Stack Exchange API
→ Filter
→ Store
```

### `candidate_rank`

Runs daily.

```text
Find candidates
→ Score
→ Update scores
```

### `digest_generate`

Runs every three days.

```text
Get top candidates
→ LLM curator
→ Generate challenges
→ Save digest
```

### `digest_send`

```text
Render email
→ Send email
→ Create frontend digest entry for this period (§16 step 9)
→ Mark questions presented
```

---

# 26. Error Handling

## Yutori unavailable

Do not modify the current Scout configuration.

Retry with exponential backoff.

## Webhook duplicated

Use Yutori update ID + question ID to make ingestion idempotent.

## Stack Exchange API unavailable

Keep the candidate but mark metadata as pending.

Retry later.

## LLM failure

Do not send a partially generated digest.

Retry.

## No good questions

Send:

> No great challenges were found this cycle. Your next challenge will arrive in three days.

Do **not** lower quality thresholds simply to fill the digest.

---

# 27. Security

Store API keys in environment variables.

Never place:

* email provider credentials
* `APP_SECRET_KEY` (see below)
* `APP_ACCESS_PASSWORD` (see §27.1 below)

in the user profile or database.

Webhook endpoints should validate incoming requests according to the provider's supported authentication/signature mechanism.

### Exception: user-supplied API keys (Yutori, Gemini, OpenAI)

The Yutori, Gemini, and OpenAI API keys are the credentials the user enters through the frontend at runtime (§7.2, §7.3) rather than at deploy time, so none of them can live only in an environment variable — they must be persisted so they survive restarts. All three are handled identically, differently from every other credential above:

* Encrypted at rest using a symmetric cipher (e.g. Fernet) keyed by a server-side `APP_SECRET_KEY` environment variable. `APP_SECRET_KEY` itself follows the normal rule — env var only, never in the DB.
* Stored in the `credentials` table (§12), separate from the `profile` JSON — never stored in plaintext, and never included in the `profile` document.
* Never returned in plaintext by any API response. The `GET /settings/{provider}-key/status` endpoints (§24) report only whether a key is set, not its value.
* Never logged, including in error messages or stack traces.
* Each replaceable only via its own endpoint (`POST /settings/yutori-key`, `/settings/gemini-key`, `/settings/openai-key`, §24), not through the general `PATCH /profile`.

The email provider key and `APP_SECRET_KEY` itself remain env-var-only, exactly as originally specified — they are not user-editable and never touch the database.

## 27.1 Application Access Gate

There is no multi-user login system — the app has no concept of separate accounts, and §23 deliberately keeps it that way. But the app is reachable at a public URL (Fly.io backend, Vercel frontend), so it still needs *some* protection against a stranger who finds that URL. The mechanism is a single shared password, not a user system:

* `APP_ACCESS_PASSWORD` is set once as a backend environment variable — never stored in the database, never derived from anything user-editable.
* `POST /auth/login` (§24) accepts a password and compares it against `APP_ACCESS_PASSWORD`. On success, it sets a signed, `HttpOnly`, `Secure` session cookie (signed using `APP_SECRET_KEY`, the same key already used to encrypt API keys — no second signing secret needed). The session is long-lived (e.g. 30–90 days) since there's only ever one legitimate user; `POST /auth/logout` clears it.
* Every API route requires a valid session cookie **except**: `POST /feedback`, `POST /scout/confirm/{cycle_id}` (both are meant to be clickable from an email without logging in, §19/§9.1), `POST /webhooks/yutori` (secured separately by webhook signature verification, not by this gate), and `GET /health` / `GET /ready` (needed for uptime checks and deploy verification, §24).
* The frontend calls `GET /auth/session` on load; if unauthenticated, it shows a password entry screen instead of any real page content, rather than relying solely on the backend to reject unauthorized requests.
* This is intentionally not a user-accounts system — there's exactly one password, no username, no per-user data, matching the single-user framing throughout this document (§23).

---

# 28. Metrics

The product's most important metric is **challenge usefulness**, not number of questions found.

### Primary metrics

**Challenge acceptance rate**

```text
questions marked Interesting / questions presented
```

**Solve rate**

```text
questions marked Solved / questions presented
```

**Skip rate**

```text
questions skipped / questions presented
```

**Search time saved**

User-reported estimate of how long they previously spent finding questions.

### Secondary

* Candidates discovered per day
* Candidates rejected
* Duplicate rate
* Digest open rate
* Average difficulty
* Topic distribution
* Feedback by topic

---

# 29. Success Criteria for MVP

The MVP is successful if, after using it for two weeks:

1. The user receives a useful digest every three days.
2. At least 50% of presented questions are considered interesting.
3. At least 25% of presented questions are attempted.
4. Duplicate questions are extremely rare.
5. The user can change topics without rebuilding the system.
6. The user spends substantially less time searching for questions.
7. The presentation does not spoil the solution.

The exact percentages should be treated as initial targets rather than hard product requirements.

---

# 30. Development Phases

## Phase 1 — Discovery MVP

Build:

* User profile
* Yutori Scout
* Scout query generator
* Yutori webhook
* PostgreSQL (Supabase)
* Stack Exchange metadata enrichment
* Deduplication

**Goal:** reliably build a pool of interesting questions.

---

## Phase 2 — Personal Digest

Add:

* Ranking
* Three-day scheduler
* LLM challenge formatting
* Email
* Question status

**Goal:** automatically deliver useful challenges.

---

## Phase 3 — Topic Management

Add:

* Topic editing
* Profile versions
* Automatic Scout PATCH
* Difficulty preferences
* Include/exclude concepts

**Goal:** make changing interests effortless.

---

## Phase 4 — Feedback

Add:

* Interesting
* Not interesting
* Too easy
* Too hard
* Solved
* Loved it

**Goal:** collect personalization data.

---

## Phase 5 — Adaptive Personalization

Add:

* Learned topic weights
* Learned difficulty preferences
* Learned concept preferences
* Personalized ranking

**Goal:** make the system increasingly good at predicting what the user will enjoy.

---

## Phase 6 — Web Frontend

Add:

* Next.js web app: `/`, `/questions`, `/challenges`, `/challenge/:id`, `/topics`, `/settings`
* Topic management UI (§22)
* Frontend consumption of `/profile`, `/questions`, `/feedback`, `/scout/usage` endpoints
* No multi-user accounts (single-user personal tool, §23); protected by the shared-password access gate (§27.1)

**Goal:** give the user a persistent, always-available surface for viewing digests and managing topics, alongside email.

**Status:** Implemented — see `frontend/README.md` and §22/§23.

---

# 31. Future Version — Interactive Challenge Mode

Eventually, email can become secondary.

Instead, the user opens:

```text
YOUR CHALLENGE

┌─────────────────────────────────────┐
│                                     │
│   FastAPI dependency injection      │
│                                     │
│   Difficulty: ★★★★☆                │
│                                     │
│   [ Start Challenge ]               │
│                                     │
└─────────────────────────────────────┘
```

The user can interact with the LLM:

> "I think the problem is caused by..."

The LLM responds:

> "That's a reasonable hypothesis. What evidence would you look for?"

It should behave like a **Socratic programming tutor**, rather than an answer engine.

Eventually:

```text
Challenge
   ↓
User hypothesis
   ↓
Investigation
   ↓
User solution
   ↓
LLM critique
   ↓
Compare against actual Stack Overflow answers
   ↓
Reflection
   ↓
Skill profile
```

This transforms the product from a **question finder** into a **personal programming practice system**.

---

# 32. Product Principle

The central product principle is:

> **Optimize for solving time, not searching time.**

The system should aggressively remove discovery friction while preserving the intellectual work for the user.

Yutori should find the problems.

The ranking system should decide which ones are promising.

The LLM curator should frame the challenge.

**The user should do the solving.**

---

# 33. MVP Definition of Done

The MVP is complete when the following workflow works end-to-end:

```text
User changes topic
        ↓
Profile saved
        ↓
Yutori Scout query updated
        ↓
Scout discovers Stack Overflow questions
        ↓
Webhook receives candidates
        ↓
Stack Exchange API verifies metadata
        ↓
Candidates stored and deduplicated
        ↓
Candidates scored
        ↓
Every 3 days top questions selected
        ↓
LLM turns them into challenges
        ↓
Email sent
        ↓
User solves questions
        ↓
User provides feedback
        ↓
Feedback stored
```

At that point, the core product exists.

Everything after that—adaptive learning, dashboards, interactive tutoring, richer integrations—is an optimization around the same core loop.

---

# 34. Hosting & Deployment

This section answers the hosting questions raised in earlier drafts of §23. **Decided architecture:** Fly.io for the backend and Supabase for the database — chosen as a pair specifically because moving the database off the backend's own disk lets the backend run stateless, which removes the persistent-volume requirement a SQLite-based plan would have forced. Full step-by-step setup lives in `build-docs/deployment-setup-guide.md`; this section records the decision and the reasoning.

### Backend (FastAPI) — Fly.io

Fly.io, running the backend as a **stateless** app (no attached volume). Because the database lives on Supabase instead of on local disk, the backend can use Fly's autostop/autostart machines — they scale to zero when idle and only bill for actual running time, which keeps cost low for a personal tool that's mostly idle between scout/digest cycles. Fly.io requires a credit card on file for every account (no ongoing free tier for new signups, per §35 item 2) — this is a paid-but-usage-based service, not a free one, though usage-based billing on an idle-most-of-the-time app should stay low. The backend still needs a stable public HTTPS URL regardless of hosting choice, since Yutori delivers results via webhook (§9, §25 `candidate_ingest`).

### Database (PostgreSQL) — Supabase

Supabase's free project tier (no card required) hosts the Postgres database. Use the **connection pooler** (transaction mode) connection string, not the direct connection — this matters specifically because Fly's autostop/autostart machines start and stop the backend process, and pooled connections handle that churn without exhausting Postgres's connection limit. Two things to know about the free tier: it caps storage at 500MB (comfortably enough for this app's tables), and a project **pauses after 7 days of no activity**, needing a manual resume — unlikely to trigger given the app's normal `digest.frequency_days` cadence (§7.1), but worth knowing about after a long gap in usage. Supabase also manages backups itself, which is simpler than the manual backup/replication story a SQLite-on-a-volume plan would have needed.

### Frontend (Next.js)

**Vercel** — first-party Next.js hosting, zero-config for the App Router, generous free tier for a single-user tool. It talks to the backend purely over HTTPS API calls; no shared filesystem is needed between frontend and backend, and the frontend never talks to Supabase directly.

### Email (Resend), LLM (Gemini/OpenAI), Yutori Scout

No separate hosting needed — all three are hosted third-party APIs the backend calls.

### Summary

| Component | Where | Notes |
|---|---|---|
| Backend (FastAPI) | Fly.io | Stateless, autostop/autostart machines; public HTTPS URL for the Yutori webhook; card required |
| Database (PostgreSQL) | Supabase | Free tier, no card required; use the pooler connection string; pauses after 7 days idle |
| Frontend (Next.js) | Vercel | Calls backend over HTTPS |
| Email / LLM / Yutori | N/A (hosted APIs) | No hosting decision needed |

This is the decided direction, not necessarily final forever — confirm cost and limits hold up in practice; specific provider swaps remain low-risk since nothing in the architecture is locked to one vendor (tracked in §35).

---

# 35. Open Questions & Decisions Log

Tracks unresolved questions and decisions raised during PRD review that don't have a final answer yet, so they don't get silently lost in prose again the way earlier drafting notes were.

| # | Question / Decision | Status | Notes |
|---|---|---|---|
| 1 | Origin/intent of the original "- new" annotation near the Yutori-key-gating requirement (formerly §7.2) | Open — flagged for later | The underlying feature (block the app until the user supplies a Yutori key on startup) is confirmed final; only the stray annotation's own intent is unresolved. |
| 2 | Hosting provider for backend + database | **Decided:** Fly.io + Supabase (§34) | Superseded the earlier SQLite + Fly.io/Render-either plan. Considered and rejected: a raw Always-Free VM (Oracle/GCP — free but self-managed, more ops burden) and Heroku (no free tier at all, $5/mo floor, sleeps on the cheapest plan). Revisit only if Fly.io's card-required, usage-based billing or Supabase's inactivity-pause behavior become a real problem in practice. |
| 3 | Concrete implementation of user-supplied-key encryption at rest (cipher choice, exact `credentials` table shape) | **Decided:** Fernet keyed by `APP_SECRET_KEY` (§27), covering Yutori, Gemini, and OpenAI keys uniformly (§7.3) | Storage engine is Postgres (§12); the encryption approach is unaffected by engine choice. |
| 4 | Mitigate Supabase free-tier 7-day inactivity pause | Open | Not a problem under normal use (digest cadence keeps the DB active), but worth a decision if long idle gaps are expected — options include a trivial scheduled keep-alive ping or simply accepting the manual-resume step. |
| 5 | Access control for a single-user app on a public URL | **Decided:** shared-password + session-cookie gate (§27.1), not a multi-user login system | Considered and rejected: static bearer token with no UI (less discoverable if the token is lost), hosting-layer Basic Auth (Vercel's is a paid-plan feature and doesn't cover the backend). |
| 6 | Which LLM provider is required vs. optional, and how are its keys managed | **Decided:** Gemini required for MVP, OpenAI optional/future; both keys user-supplied via frontend, same pattern as Yutori (§7.3) | Startup blocks digest functionality until a Gemini key is entered; switching `llm.provider` to `"openai"` requires an OpenAI key already stored. |
| 7 | Are `questions` and a user's evaluation of a question the same database row, or two separate tables? | **Decided:** kept merged — one `questions` table (§12), matching the PRD's original approach | Considered: splitting into `questions` + `candidates` tables (as `tdd.md` originally did) for cleaner re-scoring across profile versions — rejected as unnecessary complexity for a single-user MVP; `profile_version` on the merged table covers the same need. `tdd.md` updated to match. |
| 8 | Is the user profile one JSON document or several normalized tables? | **Decided:** single JSON document (§7.1), matching the PRD's original approach | Considered: normalizing into separate `profiles`/`topics`/`preferred_concepts`/`excluded_concepts` tables (as `tdd.md` originally did) — rejected as more structure than a single-user MVP needs. `tdd.md` updated to match. |
| 9 | Exact formulas behind candidate scoring (§15), duplicate detection (§13's "semantic similarity"), and where difficulty estimates come from (Yutori vs. backend-computed) | Deliberately left unspecified for now | §15 explicitly says "the exact algorithm can initially be simple" — treating these as implementation details to settle during build rather than product decisions to lock in now. Revisit if early results are poor enough to need a documented method. |
| 10 | Valid state transitions for `questions.status` (§12) | Deliberately left unspecified for now | Low-risk implementation detail (e.g., can a `presented` question return to `candidate`); resolve during implementation rather than forcing a premature decision. |

Add new rows here as new open questions come up during implementation, instead of leaving inline notes in the main spec sections.
