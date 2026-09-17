# Standing Rules

Small, durable collaboration rules that apply across every session — narrower than an ADR (`decisions/`), more permanent than a one-off note in `engineering-log.md`. Add to this list whenever the user states a rule that should hold from then on.

---

## New dependencies must be explained

Whenever a new package/library is added to either `backend/` or `frontend/` (e.g. `uv add`, `npm install`), explain in-chat what it is and why it's needed before or as it's added — not just that it's being installed.

**Why:** the user is learning as we go and wants to understand what's entering the codebase, not just see it appear in a lockfile.

**Added:** 2026-09-15, during M0-F1 (adding `@tanstack/react-query`).

---

## Local `pytest` runs hit the real Supabase project — clean up after DB-touching tests

`backend/.env`'s `DATABASE_URL` points at the same Supabase project the deployed app uses — there's no separate local/test database. CI is safe (an ephemeral Postgres service container, destroyed after each run), but running `uv run pytest` **locally** writes real rows into `profile`/`credentials` and leaves them there.

**Why:** M2 introduced the first tests that actually touch the database (profile/credential CRUD). Running them locally silently overwrote the live app's `profile` row with test values (`digest.frequency_days: 9`, `llm.provider: openai`) and left three fake API keys in `credentials` — caught only by manually checking `/profile` against production afterward.

**How to apply:** After running the backend test suite locally, if the app has any real user-entered data worth keeping, check `GET /profile` and the `/settings/*/status` endpoints against the deployed app before treating it as trustworthy — don't assume local test runs are isolated. Before M3+ adds more DB-touching tests, consider setting up a genuinely separate test database (a second Supabase project, or local Postgres via Docker) rather than continuing to share one DB between tests and production — flagged here rather than decided unilaterally, since it's an infra choice.

**Escalation (2026-09-16, M3):** this stopped being just "my tests leave junk behind." Mid-M3, a Playwright verification run discovered the user had been manually using the real deployed app in their own browser (that's how they found the dark-mode bug) — real onboarding, real API keys, a real profile — concurrently with automated testing hitting the same database. **From here on: never wipe `profile`/`credentials` wholesale.** Before any test run that touches them, read and snapshot the current state first; if it looks like real usage (non-default values, keys already connected), don't assume it's safe to overwrite — test additively or restore the exact prior values afterward (a targeted DB write of the snapshot, not a blind reset to empty/defaults). Treat this database as a shared resource with a live user, not a disposable scratch space, until a real separate test database exists.
