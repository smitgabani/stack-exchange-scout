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
