# Architecture

## Stack

| Layer    | Technology                                              |
|----------|----------------------------------------------------------|
| Frontend | Next.js (App Router) + TypeScript + TanStack Query, on Vercel |
| Backend  | Python, FastAPI, SQLAlchemy, Alembic migrations, on Fly.io |
| Database | Postgres, hosted on Supabase                             |
| Discovery| [Yutori Scout](https://yutori.com) — web-search agents that return structured results via webhook |
| Enrichment | Stack Exchange API                                     |
| Challenge generation | An LLM provider — Gemini or OpenAI, switchable per deployment |
| Email delivery | [Resend](https://resend.com)                        |

The frontend never calls the Fly.io backend directly from the browser. It
calls its own Next.js server at `/api/*`, which Vercel rewrites to the
backend's `BACKEND_URL`. This keeps the backend origin out of client code
and lets the two be deployed independently.

## Access control

There are no user accounts. A single shared password gates the whole app
behind a session cookie (`POST /auth/login`, checked on every request via
`AuthGate` in the frontend). This is intentional — the product is scoped to
one person.

## Data model, in one paragraph

A single **profile** row holds your topics, preferred/excluded concepts,
difficulty range, question preferences, and digest settings — there is
exactly one, versioned on every save so already-discovered **questions**
can record which profile version they were scored against. A **scout
definition** is a saved, reusable search built from that profile (or a
free-form query); running one creates a **run**, which Yutori answers by
POSTing results to a **webhook**. Ingesting a run's payload creates
**question** rows in `candidate` status; enrichment fills in real Stack
Exchange data; ranking scores each one against the current profile.
Promoting a question creates a **challenge** (via one LLM call). A
**digest** bundles several challenges together and can be **sent** as one
email.

## Why discovery is manual, for now

Every pipeline stage — run the Scout, ingest webhooks, enrich, re-score,
generate a digest, send a digest — is triggered by a button in the UI
rather than a scheduled job. This is a deliberate, temporary state (see the
roadmap in `build-docs/`): running things by hand kept each stage
independently testable while the pipeline was being built, and every
button that costs money or an LLM call says so before it runs.

## Cost-bearing operations

Two things in this app cost real money, and the UI is built to make that
visible rather than hide it behind a generic "Run" button:

1. **Running a Scout or research task** (`POST /scout-definitions/{id}/run`)
   — costs about **$0.35** per run, charged by Yutori. The exact figure
   comes from the backend (`settings.yutori_run_cost_usd`) rather than
   being hardcoded in the frontend, so it can't drift.
2. **Generating or reformatting a challenge** — costs **one LLM call** to
   whichever provider (Gemini/OpenAI) is configured. Previewing a prompt or
   testing it against a question without saving is always free except for
   the explicit "Test generate" action, which does spend one real call.

Every button that triggers either of these confirms first via a dialog
that names the cost, and the frontend additionally now shows an inline
"ⓘ" info button next to it explaining the consequence in full (see
`frontend-pages.md`).

## Idempotency and delivery

Yutori delivers results **at least once**, so ingestion is written to be
safe to run repeatedly on the same webhook payload: a question already
known by its Stack Overflow ID is recognized rather than duplicated. This
is the reason `POST /candidates/ingest` exists as its own manual step
rather than acting automatically inside the webhook handler — it can be
re-run safely if a batch is only partially processed.
