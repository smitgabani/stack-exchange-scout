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

---

## 2026-09-16/17 — M3 complete: server-side validation, Topics page, a dark-mode bug, and a real production scare

**Milestone / tickets:** M3-B1..B5, M3-F1..F6, M3-TEST, plus one unplanned fix (forced light theme)

**Decisions made:**

- The user extended the M1-M2 autonomy exception (Claude running git/devops/flyctl/vercel/npm commands directly, not handing them off) through M3, after explicitly being asked whether to revert. Pattern now established: each extension is its own explicit ask, never assumed to persist or lapse — see the memory note on this.
- Numeric bounds prd.md/tdd.md didn't specify were taken from the Topics mockup's own JS clamping logic instead of invented from scratch: topic weight 0–100, digest.questions and question_preferences.max_answers capped at 10, difficulty 1–5. digest.frequency_days bounded 1–30 on the backend even though the UI only exposes three presets (1/3/7 days) — the mockup's stepper limits are a UI choice, not necessarily the full valid backend range.
- exclude_closed/exclude_duplicates are silently coerced to `true` server-side (M3-B5) rather than rejected when a client sends `false` — matches the ticket's own wording ("always coerced," not "rejected").
- Topics page saves the whole form in one PATCH on an explicit "Save" click (matching the mockup's sticky save bar + toast), not per-field autosave — Settings' digest/difficulty card is a second, independently-saved surface per M3-F6, so last-write-wins between the two tabs is accepted for MVP exactly as the ticket specifies.

**What got built:**

- **M3-B1..B5:** Pydantic field/model validators on `ProfileData` — topic name uniqueness + weight bounds, concept dedup within each list and no overlap between preferred/excluded, difficulty min<=max within 1-5, digest bounds, and the forced-true exclusion coercion.
- **M3-F1..F6:** full Topics page (add/remove topics with a weight slider, concept chips, difficulty steppers, question-preference toggles with the two locked always-on rows, digest count stepper, frequency presets, Save + toast) and a second digest/difficulty card on Settings.
- **Unplanned fix:** the user reported black text on a black background on the live Settings page. Root cause: `globals.css` honored `prefers-color-scheme: dark`, flipping `body`'s background to near-black, but every mockup-matched page (login/onboarding/settings/topics) uses hardcoded light-theme colors with no dark variant. Forced light theme site-wide instead of half-supporting dark mode — verified by reproducing the exact bug locally first (Playwright with `colorScheme: "dark"`), then confirming the fix.

**A real production incident, and a real process gap it exposed:**

Mid-M3, a Playwright verification run against the real deployed backend unexpectedly failed at the onboarding step — investigation found the user had, in parallel, been manually using the actual deployed app in their own browser (that's how the dark-mode bug got reported at all): real login, real onboarding, a real Yutori/Gemini key, a real (default-valued) profile. Automated testing and real usage were hitting the *same* Supabase database at the same time. Until now, the standing rule (see M2's entry) was "clean up after test runs" on the assumption everything in `profile`/`credentials` was test-created — that assumption was simply wrong the moment real usage began. Recovered by snapshotting the real profile row before further testing and restoring it exactly (a targeted DB write, not a reset to defaults) once done; credentials were never touched. Escalated the standing rule in `rules.md`: **never wipe `profile`/`credentials` wholesale again** — snapshot first, test additively or restore exactly, treat the database as shared with a live user rather than disposable scratch space.

Separately, mid-session, `flyctl status` started failing with "trial has ended, please add a credit card" — Fly.io's free trial period expired, taking the backend offline (this was flagged as a real risk all the way back in the M0 deployment guide). Not something Claude could resolve; the user added a card and things resumed normally within minutes.

**Bugs found and fixed:**

1. Pydantic's `exc.errors()` includes a `ctx.error` field holding the raw exception object when a custom validator raises a plain `ValueError` — not JSON-serializable, so the first real validation failure crashed the response instead of returning a clean 422. Fixed with `include_context=False`; later also added `include_input=False` once testing showed the error responses, while no longer crashing, were dumping the entire validated document back at the client.
2. React's newer `react-hooks/set-state-in-effect` lint rule caught a real anti-pattern in both new pages: calling `setState` inside a `useEffect` to seed local editable state from a TanStack Query result. Fixed using React's documented alternative — adjusting state during render, keyed on a `loadedVersion` guard so it only re-syncs when the server's profile version actually changes, not on every render.
3. The dark-mode black-on-black bug above, caught by the user in production rather than by any of this session's own testing — a reminder that Playwright verification against one fixed browser context (light mode, as it happened) doesn't substitute for a real user on a real device.

**Git:** `m3-backend-validation`, `m3-frontend-topics`, `fix-forced-light-theme`, `fix-profile-error-detail` — four branches, four PRs (#8-#11, plus #9 for the backend validation itself), all merged via `gh pr merge --merge` after CI + Vercel preview checks passed, each redeployed to Fly/Vercel immediately after merging rather than batching deploys.

**Concepts introduced:**

- `prefers-color-scheme: dark` is opt-in per app, not automatic safety — a design system built for one theme needs either a real dark variant or an explicit `color-scheme` override forcing the theme it actually supports.
- React's "adjust state during render" pattern (a plain conditional in the component body, not a `useEffect`) for syncing local state to an async data source without an extra render or a lint violation — documented at react.dev's "you might not need an effect."
- Pydantic v2's `ValidationError.errors()` has `include_context`/`include_url`/`include_input` flags specifically because the full error object is often unsafe or unwieldy to hand to a client as-is.
- Why "clean up test data" is a fundamentally different, harder problem once a database is shared with real usage instead of only tests — snapshot-and-restore instead of reset-to-empty.

**Next up:** M3 fully closed out. No ADR warranted — the shared-database escalation is process, not architecture (already captured in `rules.md`), and every bug fixed here was tactical. Command-execution boundary status for M4 needs to be explicitly re-asked, per the standing pattern. Next: M4 (Yutori Scout Integration) — real discovery starts flowing into the database; system-design theme is webhook idempotency and at-least-once delivery.

---

## 2026-09-17 — M4–M7 built: the whole product loop, stopped one step before first light

**Milestone / tickets:** M4-B1..B7/F1, M5-B1..B6/F1-F2, M6-B1..B3/F1, M7-B1..B9/F1-F3. All merged and deployed. **Live verification of M4's Scout and all of M7 is still outstanding** — see "Resume here".

**Decisions made:** captured properly in `decisions/0003-pipeline-architecture-and-scoring.md` rather than repeated here — durable-inbox webhook, secret-in-URL authenticity (Yutori doesn't sign), event-table idempotency, DB-state stage boundaries, and the scoring formulas. Two process decisions also worth recording: the user extended the ADR-0002 autonomy exception through M7, and planning happened in plan mode with the approved plan at `.claude/plans/parsed-sauteeing-sonnet.md`.

**What got built:** the entire discover → enrich → score → curate → email loop. Yutori client against a contract recovered from their live docs (the `docs/yutori-api.md` the PRD cites was never committed); keyless Stack Exchange enrichment with a retry path that never rejects on an outage; six-factor scoring as pure functions; Gemini/OpenAI behind one interface; Resend email with hints behind `<details>`. Frontend gained `/questions`, `/challenge/[id]`, and a real Dashboard replacing the M0 placeholder. 103 backend tests.

**Four bugs that only real execution could have found:**

1. **`httpx` was a dev-only dependency** while M4's Yutori client imported it at module scope. The container builds with `--no-dev`, so production crash-looped on startup while CI stayed green. Fixed, and CI gained a `production-imports` job that installs `--no-dev` and imports `app.main` — reproducing what the container actually does.
2. **A single out-of-range question id 400s an entire Stack Exchange batch.** The transient-failure path would have retried that forever. Implausible ids are now filtered before the call, and 4xx (bar 429) is permanent rather than queued for retry.
3. **The digest quality guard let through exactly what the product exists to avoid.** Topic + depth + quality total 65, so a 2008 question with 51 answers and an accepted one cleared the 55 threshold with nothing left to solve. Found by scoring real Stack Overflow data, not by any unit test. Added a solve-opportunity floor; calibration now separates cleanly (0/7 ancient-or-off-topic eligible, 8/8 recent on-topic eligible).
4. **`has_api_key` reported "connected" for credentials that cannot be decrypted.** Every stored key was encrypted under a previous `APP_SECRET_KEY`, so the UI and the key gates insisted all was well while every outbound call would fail. "Connected" now means "usable", which also makes the condition self-healing: the UI drops to "Not set" and prompts for re-entry.

**Concepts introduced:** why a scale-to-zero host plus an at-least-once webhook with no redelivery forces durability into the database rather than the process; the difference between transient and permanent upstream failures, and why conflating them creates infinite retry loops; deriving a secret-in-URL scheme when a provider offers no payload signing; structural versus advisory safety — the LLM cannot leak an accepted answer because the answer is never in the request, which the test asserts by inspecting the real payload rather than trusting the prompt.

**Git:** branches `m4-scout-integration`, `m5-enrichment-filtering`, `m7-digest-llm-email`, plus fixes `fix-httpx-runtime-dep` and `fix-unusable-credential-reporting`. PRs #12–#16, all merged after CI.

### Resume here

Everything is built, merged, deployed, and green. What remains is **live verification only**, and it is blocked on one thing.

**The blocker:** `POST /scout/sync` will create a real Scout from `profile.topics`, and that profile currently contains exactly one topic — `{"name": "Rust", "weight": 75}` — which is **test pollution from `test_patch_profile_topics_valid_round_trip` running against the shared production database**. Creating the Scout now would spend a billable run (~$0.35) hunting Rust questions nobody asked for. **The user needs to set their real topics on the Topics page first.**

Ready and waiting: Yutori and Gemini keys are stored and decrypt correctly; `RESEND_API_KEY`, `DIGEST_RECIPIENT_EMAIL`, `APP_BASE_URL`, `YUTORI_WEBHOOK_SECRET` and `PUBLIC_BASE_URL` are all set on Fly; Resend delivery is confirmed working with a real test email.

Note `DIGEST_RECIPIENT_EMAIL` is `dmodee111@gmail.com`, not the requested `gabanismit11@gmail.com` — Resend's free tier only delivers to the account's own address until a domain is verified at resend.com/domains. Also: the Resend API key was pasted into a chat transcript and is worth rotating.

**Then, in order:** set real topics → `POST /scout/sync` (billable) → wait for the first webhook → `POST /candidates/ingest` → `/candidates/enrich` → `/candidates/rank` → `/digest/generate` → `/digest/send` → check the inbox → the four click-throughs (M4/M5/M6/M7-TEST) → record actual Yutori spend.

**Next up:** the user is taking a deliberate detour before finishing this. The strongly recommended detour is giving dev/test its own database — the shared one has now caused three separate problems, escalating from junk rows, to unreadable credentials, to nearly spending money on the wrong topics.

---

## 2026-09-19 — On-demand runs, and what the Yutori API actually does

Built the Scout control panel and the "Run now" button, then spent the session
discovering that the mechanism underneath it does not work — and that a better
one existed the whole time.

**What shipped:** `/scout` page (status, spend, the rendered query, per-update
yield, timeline, health), Run now on three surfaces behind a cost dialog, a
`scout_events` timeline/ledger table, run-state columns on `scouts`, and a
missed-update recovery path via `GET /updates`. Commits `799ccc4` → `6b9d5fe`.

**What we learned by calling the live API**, none of it documented:

- `POST /{id}/restart` rejects a live Scout (`400 "Scout is not completed"`) —
  it is the counterpart of `/done`, not a general start.
- Once parked and restarted, it **does not trigger a run.** Two attempts, two
  hours, `update_count` unmoved, no webhook.
- `next_run_timestamp` is epoch `0`, not null, when nothing is scheduled. That
  broke a "did the run start?" heuristic: 1970 minus now is a large negative
  number, which passed a "less than five minutes" test as `true`.
- Update timestamps are epoch **milliseconds**; scout detail uses ISO strings.
- `/v1/usage` nests `scout_runs` under `activity`, so reading the top level
  silently reported zero runs and zero spend.
- `num_active_scouts` counts runs *executing*, not scouts whose status is
  active.
- Scouts are created **public** by default; `GET /updates` returned data with
  an invalid API key. Now forced to `is_public: false` on create and re-asserted
  on every sync.
- The webhook deadline is **10 seconds** per attempt, three attempts — tighter
  than the ~30s previously recorded, and awkward against a cold Fly machine.

**Two self-inflicted problems worth remembering:**

- The stored Yutori key was 18 characters and 401'd everywhere. It decrypted
  cleanly, so this was a bad key, not a bad `APP_SECRET_KEY` — worth checking
  before blaming encryption.
- **Vercel paused the account**: Fluid Active CPU 4h25m against a 4h limit. Every
  `/api/*` call is a function proxying to Fly, and three defaults compounded —
  TanStack's `staleTime: 0`, refetch-on-focus and three retries, plus a 15s poll
  that ran on every page whenever a run was stuck `running`, which happened
  twice for over two hours. Fixed by `staleTime: 60s`, no refetch on focus, one
  retry, opt-in polling at 30s on the Scout page only, and a 45-minute run
  timeout instead of two hours.

**Where it landed:** a session of API archaeology produced
[ADR 0004](decisions/0004-discovery-primitives-and-multi-account.md). The
Research API (`POST /v1/research/tasks`) is one-shot, costs the same $0.35,
takes the same `output_schema` and webhook, and leaves nothing behind — so it,
not a Scout, is what an on-demand run should use. Combined with the need to
support API keys from more than one account, that reshapes the model: scout
*definitions* are local and durable, remote objects are disposable and
fingerprinted, and deleting a key never deletes what it found. Tickets are
M12.

**Resume here:** M12-B1. Before building, run one real research task as an
experiment — nobody has called that endpoint yet, and its result shape, latency
and webhook behaviour are assumptions until they aren't.

---

## 2026-09-20 — The research primitive works, and two bugs found by using it

First live research task: **succeeded, 18 questions, $0.35**, ~19 minutes
(04:57 → 05:16). `structured_result` matched the registered `output_schema`
exactly, so the parser needed no changes — the envelope adapter from ADR 0004
was sufficient, and ingest/enrich/rank processed it without knowing research
tasks exist. Pool afterwards: 38 candidates, all scored, top 71.0.

**The webhook was never needed.** `events_awaiting_ingest` never moved; the
poll collected the result. That is the clearest vindication of ADR 0004:
under the Scout model this would have been a paid run lost to the 10-second
delivery deadline.

**Two bugs surfaced by doing it for real:**

- **Re-sync created Scouts silently.** `POST /scout/sync` passed
  `allow_create=True`, a leftover from M4 when creating was the only way to
  get a Scout. It is reached from a plain text link with no confirmation, so
  after Forget cleared the reference, pressing it created a Scout — a
  billable run — from what looks like a free action. Now `allow_create=False`;
  creating is the Run button's job, behind a dialog that names the price.
- **The orphan check was watching the wrong field.** It used
  `usage.active_scout_ids`, which counts runs *executing right now* — so an
  idle-but-alive Scout, exactly the kind that bills unattended, showed as no
  orphan. Health now lists every Scout on the account from
  `GET /v1/scouting/tasks` with its status and whether we track it.

**Account switching, resolved.** Using a key from another account produced
`403 "Only the creator of a scout can edit it"`. Remote objects now record
`sha256(key)[:16]`; a proven 403 (`sync_status = "unreachable"`) also counts
as a mismatch, because a row created before fingerprinting has nothing to
compare and would otherwise show the error with no way out. `POST
/scout/forget` clears the link without touching a single discovered question.

**Resume here:** M4–M7 is two clicks from closed — Generate digest, then Send
latest digest. The newest digest (04:54) predates the research results
(05:16) and holds 2 stale questions. After that, M12-B1.

One thing to look at while reading the first real challenges: all 38
candidates scored between 69 and 71. That is a suspiciously narrow band and
suggests one sub-score is dominating. §26 forbids lowering the threshold to
fill a digest; it says nothing about fixing a formula that is not
discriminating.

## 2026-09-24 — M13: Yutori task settings, and the monitors that billed forever

**Milestone / tickets:** M13-B1..B9, M13-F1..F5 (feature list §1, F0–F9)

**Decisions made:** [ADR 0006](decisions/0006-one-live-monitor-and-task-settings.md).
- One live monitor per scout, enforced in the service with a row lock rather than a unique index, because the existing pile-up would have failed the migration.
- Settings are overrides in layers (built-in → defaults → scout).
- The query template is versioned like the curator prompt.
- The webhook stays locked.
- Saving the profile no longer touches Yutori.
- Command autonomy was granted for M13 only: local git, tests and migrations. Push, merge, deploy and production DB stay user-run.

**What got built:**

It started as "let me edit the Scout parameters" and turned up a billing bug on the way. A Scout isn't a run; it's a monitor that runs again every interval until stopped, and every Scout-mode press created a new one while leaving the last one running. None of their later runs reached the ledger. The fix (F0) came first:
- a second Scout-mode run is refused with a 409 describing the live monitor;
- Replace stops the old monitor before creating anything;
- scheduled runs are attributed to their monitor through the `scout.id` in each webhook and recorded once;
- Monitors shows monthly cost, leftovers and Yutori's own run count against the ledger, with Stop and **Stop older monitors**.

Then the settings:
- a **Parameters** tab per scout, with a different form for Research and for Scout;
- a live preview of the exact request (built by the same function the run uses);
- monthly cost;
- a **Defaults** tab with the editable query template and app-wide default settings;
- a live-monitor comparison with a free **Apply**.

The run page shows what each run sent.

Tests went from 314 to 372. The new files are `test_monitors.py`, `test_task_settings.py`, `test_yutori_client.py` and `test_query_templates.py`. `test_yutori_client.py` is the first test that checks real request bodies, using an `httpx.MockTransport` passed through a new `transport=` argument on `YutoriClient`. It needed no new dependency.

**Git:**
- Branches: `M13-0-featurelist` (feature list and mockup), then `M13-A-monitor-pileup`, `M13-B-task-settings`, `M13-C-defaults-template`, `M13-D-live-monitors` and `M13-E-docs`. Each is branched from the one before, so they merge in order.
- Conventional Commits: `fix:` for the pile-up, `feat:` for each settings phase, `docs:` for this.
- The one migration (`e4a7c2d91b60`) was cycled upgrade → downgrade → upgrade against the **local** `scout_test` database, with `DATABASE_URL` overridden on the command line. `backend/.env` still points at production Supabase, so nothing here ran against it.

**Concepts introduced:**
- *Row locks vs unique indexes* for "at most one" rules: an index can't be added over data that already breaks it.
- *Advisory locks* (`pg_advisory_xact_lock`) to serialise a job without a table to lock.
- *Layered configuration*: store only overrides, so a default change propagates.
- *Dependency injection for tests*: an optional transport rather than monkeypatching httpx.
- *Structured error bodies*: a 409 whose `detail` is an object the UI can act on, behind an `ApiError` that keeps `message` readable for every existing caller.

**Next up:**
1. Push and merge the six branches in order.
2. Deploy the backend, then the frontend. The migration is additive, so it's safe before the code.
3. Open **Monitors → List scouts and research tasks → Stop older monitors** to clear the pile-up that already exists.
4. Do the M13-TEST click-through.
5. F10 (presets) and §2 topic management are next in `featurelist.md`.
