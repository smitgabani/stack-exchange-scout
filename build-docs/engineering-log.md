# Engineering Log

A running, dated narration of each work session: what we decided, what got built, the git mechanics used (as a teaching trail), and the concepts introduced along the way. Significant architecture decisions get pulled out into their own ADR in `decisions/` and cross-referenced from here — this log is the day-to-day story, not the formal record of *why* for the big calls.

**Entry template** (copy this for each new session):

```
## <date> — <short title>

**Milestone / tickets:** <e.g. M1-B1..B6, M1-F1..F2>
**Decisions made:** <anything decided this session, even small ones — link an ADR if one was written>
**What got built:** <plain-language summary, not a diff>
**Git:** <branches created/merged, notable commands, anything taught (rebase, conflict resolution, etc.)>
**Concepts introduced:** <Python/FastAPI/Git/DevOps/system-design concepts explained this session, esp. Node.js comparisons>
**Next up:** <what the next session picks up>
```

---

## 2026-09-11 — Team workflow setup

**Milestone / tickets:** Pre-M0 (repo + process setup, not a ticket itself)

**Decisions made:**

- Reframed the engagement: I (Claude) act as the senior engineer executing implementation; the user — a Node.js developer learning Python/FastAPI, advanced Git, DevOps, and system design — reviews, decides, and learns by doing rather than writing most of the code themselves. See `decisions/0001-team-workflow-and-collaboration-model.md` for the full reasoning.
- Backlog lives in `featuresticketlist.md`, organized as vertical-slice milestones (M0–M11) rather than the backend-first/frontend-last phase order in `prd.md` §30 — every milestone ships a backend piece and its matching frontend page together.
- Git workflow: real feature-branch-per-ticket, merged back to `main`, Conventional Commits — chosen specifically as the vehicle for hands-on branching/merging/rebasing practice, not commits straight to `main`.
- Test checkpoints at each milestone combine three things: automated tests I write (tagged 🔒 security / ⚡ performance-lite / 🧩 business logic), manual verification I run myself, and a concrete frontend click-through list for the user.
- Performance testing stays lightweight (response-time sanity checks) given this is a single-user personal tool — no Locust/k6.
- The scheduler (closing the "no scheduler yet" gap) is deliberately placed *after* the MVP checkpoint (M11, post-M10), not interleaved into MVP work.

**What got built:**

- Git repository initialized; existing `build-docs/` and `design-mockups/` content committed as the root commit.
- `.gitignore` added (Python + Node + editor + macOS junk).
- `featuresticketlist.md` populated with the full M0–M11 backlog.
- `decisions/0001-team-workflow-and-collaboration-model.md` — the first ADR.
- This log, seeded with its template and this entry.

**Git:**

```
git init
git add .gitignore build-docs design-mockups
git commit -m "chore: initial project docs and design mockups"
```

This first commit went straight to `main` deliberately — it's a snapshot of pre-existing work, not a ticket. Starting with M0, every ticket gets its own branch (`git checkout -b <ticket-id>-<slug>`), and merging that branch back is where branching/merging/rebasing gets taught for real, on real history.

**Concepts introduced:**

- Conventional Commits (`feat:`/`fix:`/`test:`/`docs:`/`chore:`) as the commit message convention going forward.
- ADRs (Architecture Decision Records) as a real industry pattern for documenting significant technical decisions — lightweight, one file per decision, used sparingly (not for every small choice).

**Next up:** M0 — Foundations & scaffolding (backend skeleton, frontend skeleton, both deployed and talking to each other).

---

## 2026-09-11 — Correction: command execution boundary

**Milestone / tickets:** Pre-M0 (process correction, not a ticket)

**Decisions made:** Claude ran `git checkout -b ...` directly at the start of M0. Corrected immediately: Git and DevOps/infra commands are user-run from here on (Claude instructs one command at a time with an explanation, user executes and reports back); Claude continues writing application code directly. See `decisions/0002-command-execution-boundary.md`.

**What got built:** ADR 0002; ADR 0001 marked as amended by it.

**Git:** none yet on this branch — `uv` was installed via Homebrew (a one-time local tool install, not part of the app's own git history) before the correction landed. The actual first git commands of the session (staging/committing this correction, then branching for M0) are next, and will be user-run.

**Concepts introduced:** ADRs get *amended* by a new ADR rather than rewritten in place — same principle as not rewriting git history that's already shared: the record of "we used to think X, then learned Y" is itself valuable.

**Next up:** commit this correction, then start M0-B1 for real, with the user running every git/devops command.

---

## 2026-09-15 — M0 complete: Fly.io, CI, Next.js frontend, Vercel, both apps talking

**Milestone / tickets:** M0-B7, M0-B8, M0-F1..F3, M0-TEST (M0-B1..B6 and B5 had already landed in an earlier, unlogged session)

**Decisions made:**

- Frontend styling: plain CSS, not Tailwind — the design mockups (`design-mockups/*.dc.html`) use hand-written CSS classes, not Tailwind utilities, so matching that makes porting mockups into real components later closer to a direct copy.
- Fly.io machine count: scaled down from the default 2 (Fly's automatic HA setup) to 1 — this is a single-user app where `min_machines_running = 0` already means the machine scales to zero when idle, so a second machine was pure overhead, not resilience that matters here.
- `CORS_ORIGINS` added as an env var (default `http://localhost:3000`) rather than a hardcoded allow-list — keeps it twelve-factor (M0's own system-design theme) and meant we could add the Vercel production URL later without a code change, just a Fly secret update.
- GitHub + PR-based merges: created a real GitHub remote (`smitgabani/stack-exchange-scout`, private, via `gh repo create`) and did the M0 milestone-boundary merge as two real pull requests (backend branch, then frontend branch) rather than local `git merge` + push — both get the same result and both trigger the M0-B8 CI workflow, but the PR path is real practice with the review/merge-button flow the user wanted exposure to.
- New standing rule recorded in `build-docs/rules.md` (new file, previously empty): explain any new dependency (`uv add`, `npm install`) before/as it's added, not just let it appear in the lockfile. Added mid-session when the user asked for it explicitly.

**What got built:**

- **M0-B7:** `backend/Dockerfile` (`uv sync --frozen` based image) + `fly.toml` (autostop/autostart, `min_machines_running = 0`, `release_command = alembic upgrade head`). Deployed to Fly.io as `backend-soft-headland-5023`, scaled to 1 machine. `/health` publicly reachable.
- **M0-B8:** `pytest`/`httpx`/`ruff` added as dev dependencies; a ruff config (`extend-immutable-calls`) so FastAPI's `Depends()`-as-default pattern isn't flagged as bugbear B008; a smoke test for `/health`; `.github/workflows/ci.yml` with separate `lint` and `test` jobs (no deploy step). Also cleaned up ruff findings in the Alembic-generated boilerplate (import order, old-style `Union` typing, unused imports, unnecessary `pass`).
- **Mid-session fix (filed under B7):** discovered the deployed backend had no CORS headers, which would silently break any browser-based frontend call even though `curl`/server-to-server calls worked fine. Added `CORSMiddleware` + the `CORS_ORIGINS` setting, redeployed.
- **M0-F1/F3:** Next.js (App Router, TypeScript, plain CSS) scaffolded in `frontend/`. `Providers` wraps the tree in a `QueryClientProvider`; the placeholder page uses `useQuery` to call the real backend's `GET /health` and renders the live result.
- **M0-F2:** GitHub repo created; all three branches pushed; Vercel project imported and deployed.
- **M0-TEST:** secrets-hygiene check passed (`backend/.env`/`frontend/.env.local` never in git history, both gitignored). Cold-start latency baseline recorded: confirmed the machine was `stopped` via `flyctl machines list`, then timed two consecutive requests — **~2.86s cold** vs. **~0.20s warm** (~2.67s of pure cold-start overhead), machine confirmed `started` immediately after. No threshold yet, just a real number on record — relevant later for M4's webhook-response-time budget. Frontend click-through done: `stack-exchange-scout.vercel.app` shows "backend: ok" against the live Fly backend.

**Debugging, for the record (two real production issues, not just a happy-path deploy):**

1. Vercel deploy returned a platform-level 404 (`x-vercel-error: NOT_FOUND`) on `/` despite a successful build log showing the route generated. Root cause: **Framework Preset was stuck on "Other"** in Vercel's project settings (even after Root Directory was correctly set to `frontend`), so Vercel served `frontend/public/` (just the default SVGs) as a static site instead of the real `next build` output. Fixed by manually setting Framework Preset to Next.js and redeploying.
2. After that fix, the page loaded but showed `backend: error (Failed to fetch)` — the browser silently blocking a cross-origin call the server itself was answering fine (confirmed via `curl` with a matching `Origin` header showing no `access-control-allow-origin` in the response). Fixed by adding the Vercel production URL to the `CORS_ORIGINS` Fly secret.

**Git:**

- Branched `m0-frontend-scaffolding` off `main` (not off `m0-backend-scaffolding`) — two independent lines of history from the same point, merged separately later. Learned along the way: uncommitted changes travel with you across `git checkout`; only *committed* changes are branch-specific, so switching branches mid-session doesn't lose in-progress work.
- `gh repo create stack-exchange-scout --private --source=. --remote=origin`, then pushed `main`, `m0-backend-scaffolding`, and `m0-frontend-scaffolding`.
- Two PRs opened (`gh pr create`) and merged (`gh pr merge --merge`) into `main` — first backend, then frontend, syncing local `main` with `git pull` after each. Discussed the actual difference between a PR and a plain local `git merge` + push (mostly the same end state; PR adds the diff-review UI, comments, and CI-gating a local merge doesn't force you through) before choosing PR for the practice rep.
- Caught and cleaned up two off-branch mistakes: `npm install @tanstack/react-query` run from the repo root instead of `frontend/` (stray root `package.json`/`node_modules`, deleted), and two unintended packages (`install`, `npm`) that ended up in `frontend/package.json` from an unrelated command, removed via `npm uninstall`.

**Concepts introduced:**

- Docker layer caching via a two-step `uv sync` (deps before source copy) so code-only changes don't reinstall dependencies.
- Fly.io `release_command` — a one-shot step (here, `alembic upgrade head`) that runs once per deploy before new machines take traffic, instead of every instance running migrations on its own boot.
- `ruff`'s flake8-bugbear B008 and why FastAPI's `Depends()` is a legitimate exception to "no function calls in argument defaults," configured via `extend-immutable-calls` rather than suppressed or worked around.
- GitHub Actions trigger semantics: `push: branches: [main]` + `pull_request` means a plain push to a feature branch does *not* run CI — only a push to `main` or opening/updating a PR does. This is why the workflow sat unverified until the first real PR.
- TanStack Query (React Query) as the client-side data-fetching/caching layer for a frontend that's a pure API client with no backend of its own (Next.js API routes/Server Actions deliberately unused here — FastAPI is the only backend).
- CORS as a browser-enforced restriction: the backend can respond correctly to `curl` while a browser blocks the same response from reaching JavaScript — the fix lives in server response headers (`Access-Control-Allow-Origin`), not in anything the frontend can do.
- What a pull request actually is on top of plain git (diff review, comments, CI gating, a merge button) versus a bare `git merge` + push doing the same underlying merge.
- Vercel's Framework Preset controls how the platform *serves* build output, independent of whether the build command itself (`next build`) succeeds — a successful build log doesn't guarantee a working deployment.

**Next up:** M0 is fully closed out (all backend/frontend tickets + M0-TEST done). No ADR warranted for this session — tactical execution/debugging, not a new architectural direction. Move to M1 (Access Gate & Credential Storage): app-wide password gate, credential encryption at rest.

---

## 2026-09-16 — M1 complete, M2 complete: session cookie, profile document, API key onboarding

**Milestone / tickets:** M1-B1..B6, M1-F1,F2, M1-TEST; M2-B1..B9, M2-F1..F4, M2-TEST

**Decisions made:**

- Session-cookie vs. JWT/OAuth framing (M1's system-design kickoff): a plain signed cookie is the right-sized tool for a single-shared-password app — JWT's stateless-verification value and OAuth's delegated-identity value both solve problems this app doesn't have (multiple services, multiple real users).
- Discovered mid-M1 that the Fly.io backend and Vercel frontend are genuinely different domains, so a cross-site session cookie would need `SameSite=None` and risk Safari's third-party-cookie blocking. Fixed by proxying frontend API calls through Vercel (`next.config.ts` rewrites, `/api/* -> BACKEND_URL`) so the browser only ever talks to its own origin — cookie is same-site, and CORS becomes mostly moot for these calls.
- Signed cookie built with `itsdangerous` (`URLSafeTimedSerializer`), not a JWT library — no standardized claims/interop needed, just a signed+timestamped opaque value.
- **Mid-M1, the user granted a temporary, explicit exception to ADR 0002**: asked Claude to run all commands directly (git/flyctl/vercel/npm included) through the rest of M1 and all of M2, rather than handing them off one at a time. This is a scoped exception, not a standing change — ADR 0002's default (user runs git/devops commands) resumes after M2 unless re-granted. Recorded in memory so a future session doesn't assume it persists.
- Once running commands directly, moved the actual git work back onto proper ticket branches after initially drifting onto `main` — the autonomy grant was about *who* runs commands, not about abandoning the branch-per-ticket workflow.
- PATCH /profile uses JSON-Merge-Patch semantics (RFC 7396: only keys present in the request are touched, at any nesting level) rather than requiring the full document — necessary because Pydantic sub-models with defaults would otherwise silently overwrite untouched sibling fields on a partial nested update.
- Bounds validation (topic weight ranges, difficulty min<=max, etc.) deliberately deferred to M3 per the ticket list's own split — M2's profile schema validates structure/types only.

**What got built:**

- **M1-B1..B6:** `APP_ACCESS_PASSWORD`/`APP_SECRET_KEY` config; `credentials` table + Fernet encrypt/decrypt helper (key derived from `APP_SECRET_KEY` via SHA-256 + urlsafe-base64, since Fernet needs a 32-byte key and the secret is an arbitrary-length hex string); `POST /auth/login|logout` + `GET /auth/session`; an app-wide `require_session` dependency that no-ops for the exact exempt list from `prd.md` §27.1.
- **M1-F1,F2:** mockup-matched login page; `AuthGate` checking `/auth/session` on load, redirecting unauthenticated visitors to `/login` and back.
- **M2-B1..B9:** `profile` table (single JSONB row + version); `GET`/`PATCH /profile` with the merge-then-validate-then-save flow above; six `/settings/{provider}-key(+status)` endpoints for Yutori/Gemini/OpenAI; `require_yutori_key`/`require_gemini_key` dependencies built now for M4/M7 to attach later; switching `llm.provider` to `"openai"` rejected without a stored key.
- **M2-F1..F4:** two-step onboarding wizard (Yutori, then Gemini) gated by a new `OnboardingGate`; Settings page with per-provider Connected/Not-set status, Rotate/Add-key inline editing, and (added after catching the gap against M2-TEST's own click-through spec) a Gemini/OpenAI active-provider toggle.
- GitHub Actions `test` job gained a real ephemeral Postgres service container — M2 is the first milestone with tests that actually touch the database.

**Bugs found and fixed this session (not just happy-path building):**

1. **Async engine connection pooling across event loops.** The first DB-touching tests failed with `InterfaceError: cannot perform operation: another operation is in progress` — the app's `engine` had no `poolclass` override, so a pooled asyncpg connection (bound to the event loop it was created on) could outlive that loop. Each fresh `TestClient` spins up its own loop; production has the same latent risk from Fly's start/stop cycle. Fixed with `poolclass=NullPool`, matching what `alembic/env.py` already did for the same reason.
2. **Shared database, no test isolation locally.** `backend/.env`'s `DATABASE_URL` points at the same Supabase project the deployed app uses — CI is safe (fresh Postgres container per run), but running `pytest` locally silently wrote real rows into `profile`/`credentials`, later confirmed by diffing `GET /profile` against production and finding test values (`digest.frequency_days: 9`, `llm.provider: openai`, three fake keys) instead of real defaults. Cleaned up manually (safe to do with certainty — no real onboarding UI existed yet, so every row was traceably test-created); documented as a standing risk in `rules.md` rather than silently building an auto-wipe mechanism, since blindly deleting `profile`/`credentials` after every test run would itself be dangerous once real user data exists. A genuinely separate test database is flagged as a future infra decision, not decided unilaterally.
3. **`OnboardingGate` auto-redirect race.** Verified the onboarding flow end-to-end with a headless-Chromium script (Playwright) against the real deployed backend and caught a real bug: the gate redirected away from `/onboarding` the instant both keys became connected, firing mid-flow right after the Gemini key saved — the user was yanked to the dashboard before ever seeing the "All set" confirmation screen the mockup calls for. Fixed by removing that redirect direction entirely; the onboarding page's own "Go to dashboard" button is now the only way to leave.
4. **M2-F3/F4 under-scoped against M2-TEST.** The ticket list's own click-through step ("add an OpenAI key and switch the active provider") requires a working provider toggle, which the initial Settings pass didn't include (scoped out as "not explicitly in M2-F1..F4's text"). Added it as a follow-up PR once the gap was noticed by actually walking the click-through instead of just reading the ticket bullets.

**Git:**

- `m1-frontend-access-gate` (Vercel proxy fix, then login/AuthGate), `m1-backend-access-gate`, `m2-backend-profile-onboarding`, `m2-frontend-onboarding-settings`, `m2-frontend-provider-toggle` — five branches, five PRs (#3-#7), all merged via `gh pr merge --merge` after CI (and, from M2 on, a real Vercel preview deployment check) passed.
- Root-caused a `git status` mismatch where a branch showed the *previous* branch's files: `git checkout` had happened, but the working tree still reflected the old branch's content because the switch hadn't actually landed as expected — resolved by re-verifying with `git branch --show-current` before trusting file state, a good habit anytime branch state feels surprising.

**Concepts introduced:**

- Why a signed opaque cookie beats JWT/OAuth for a single-password app, and the separate, real problem of cross-site cookies when frontend and backend are genuinely different domains (`SameSite=None` + browser third-party-cookie blocking) — solved by proxying rather than by loosening cookie attributes.
- JSON Merge Patch (RFC 7396) as the standard shape for "partial update" semantics, and why naively re-validating a partial payload through a Pydantic model with field defaults silently destroys untouched sibling data.
- asyncpg connections are bound to the event loop that created them; a connection pool that outlives its loop breaks in a way that looks like a database problem but is a concurrency/lifecycle problem. `NullPool` trades a small per-checkout cost for eliminating that entire bug class — reasonable here since Supabase's PgBouncer already pools upstream.
- Why testing against a shared, persistent database is a real hazard distinct from "did the test pass" — a green test suite can still mean real data got overwritten, and the only way to know is to check.
- Using a real headless-browser script (Playwright driving Chromium) to verify a multi-step frontend flow end-to-end, rather than trusting `npm run build` succeeding or reading the code and assuming it's right — this is what actually caught the `OnboardingGate` race and the missing provider toggle.

**Next up:** M1 and M2 are both fully closed out, including M2-TEST. No ADR warranted — the cookie/proxy decision was tactical (already covered by the M1 commit history and this log entry), and the test-database question is explicitly left open for the user rather than decided. The command-execution boundary (ADR 0002) resumes as the default for M3 unless the user grants another explicit exception. Next: M3 (Topic & Preference Management) — server-side validation for topics/concepts/difficulty/digest settings, including the weight/bounds checks this session deliberately deferred.
