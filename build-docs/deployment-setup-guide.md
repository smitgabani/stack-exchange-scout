# Deployment & Setup Guide — Stack Overflow Challenge Scout

**Status:** Draft — infrastructure not yet provisioned

**Companion to:** `prd.md` §23 (Tech Stack), §27 (Security), §34 (Hosting & Deployment), §35 (Open Questions)

**Decided hosting architecture (see `prd.md` §34/§35):** the backend runs on **Fly.io** as a stateless app, and the database is **PostgreSQL hosted on Supabase** — not SQLite. This replaces the earlier SQLite-on-a-persistent-volume plan: moving the database off the backend instance removes the one thing that forced a paid Fly.io volume, so the backend can now run on Fly.io's pay-as-you-go autostop machines at close to $0 for light single-user traffic. No message queue/worker, no scheduler yet (§23) — every recurring job is still a manually-triggered API endpoint for now; that part is unchanged.

---

# 1. Component Map

| Component | Technology | Hosting | Needs persistent storage | Needs a public URL | Paid / Free |
|---|---|---|---|---|---|
| Backend | Python + FastAPI | Fly.io | No — stateless, DB lives on Supabase | Yes — Yutori webhook target | Card required, usage-based — see note below |
| Database | PostgreSQL | Supabase (managed) | Handled entirely by Supabase | No (only the backend connects to it) | Free tier — no card required, but see inactivity-pause caveat below |
| Frontend | Next.js (App Router) | Vercel | No | Yes — the app itself | Free (Hobby plan is enough for a single-user app) |
| Email | Resend | Hosted API | No | No | Free (usage fits comfortably in the free tier's monthly email allowance) |
| LLM | Gemini (OpenAI swappable) | Hosted API | No | No | Free (Gemini free tier, per `prd.md` §23) — the OpenAI alternative is paid, no meaningful free tier |
| Discovery | Yutori Scout | Hosted API | No | No (it calls *your* webhook) | Paid — per-run billing ($0.35/run), starts from a one-time signup credit (`prd.md` §7.2) |

Because the database now lives on Supabase instead of on the backend's own disk, the backend is fully stateless — it no longer needs a persistent volume, and can in principle run as multiple instances (not that this app needs to).

**Note on backend cost:** Fly.io requires a credit card on file for every account, with no permanent free tier for new signups (just a short trial) — see `prd.md` §35. However, because the backend is stateless, it can use Fly's **autostop/autostart machines**, which scale to zero and only bill for actual running time. For a personal, single-user app that's mostly idle between scout/digest cycles, realistic cost is low — likely single-digit dollars a month or less — but it is **not guaranteed $0**, since you're billed for whatever compute time the app actually uses (including cold starts triggered by the Yutori webhook).

**Note on database cost:** Supabase's free project tier is genuinely free, no card required. The trade-off: a free project **pauses automatically after 7 days with no activity**, requiring a manual resume in the dashboard (or an API call) before the app works again. Given this app queries the database at least every `digest.frequency_days` (default 3, §7.1) during normal use, this is unlikely to trigger — but worth knowing about before a long gap in usage (e.g., a vacation).

---

# 2. Prerequisites

Accounts to create before starting:

* Fly.io (backend hosting)
* Supabase (managed Postgres)
* Vercel (frontend hosting)
* Resend (transactional email)
* Google AI Studio (Gemini key — required for the MVP, entered via the frontend post-deploy, §7); OpenAI account optional
* Yutori (Scout API)

Tools:

* `flyctl`
* `git`, and this repo pushed to a GitHub remote (needed for both Vercel and CD in §11)

---

# 3. Backend (FastAPI) — Hosting Setup

## 3.1 Why Fly.io, and why stateless now

The backend needs a stable public HTTPS URL, because Yutori delivers results via webhook (`prd.md` §9, §25 `candidate_ingest`) — that rules out anything without a reachable address. It does **not** need its own persistent disk anymore, because the database moved to Supabase (§4). That's the key change from the original plan: without a volume requirement, the backend can run on Fly's autostop/autostart machines, which stop when idle and start again on the next incoming request (including a Yutori webhook) — this is what gets cost down close to $0 for light usage.

## 3.2 Fly.io walkthrough

```bash
# from the backend/ directory, once a Dockerfile exists
flyctl launch --no-deploy        # generates fly.toml, pick a region close to you
```

In `fly.toml`, enable scale-to-zero so you're not billed for idle time:

```toml
[http_service]
  internal_port = 8000
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 0
```

Set secrets (never commit these — see §9). `DATABASE_URL` here is the connection string from your Supabase project (§4.2), not a local file path:

```bash
flyctl secrets set \
  DATABASE_URL="postgresql://postgres.[project-ref]:[password]@[pooler-host]:6543/postgres" \
  APP_SECRET_KEY="$(openssl rand -hex 32)" \
  APP_ACCESS_PASSWORD="choose-a-password" \
  DIGEST_RECIPIENT_EMAIL="you@example.com" \
  RESEND_API_KEY="..."
```

Note what's *not* here: `GEMINI_API_KEY`/`OPENAI_API_KEY` and the Yutori key are **not** environment variables — like the Yutori key, they're entered through the frontend after deploy and stored encrypted in the database (§7, §8).

Deploy and verify:

```bash
flyctl deploy
flyctl status
curl https://<your-app>.fly.dev/health
```

Your Yutori webhook target is now `https://<your-app>.fly.dev/webhooks/yutori` — register this with Yutori (§8). The first request after a period of idleness will trigger a cold start (Fly's autostart); this includes the first webhook delivery after a quiet stretch, so a slightly slower first response is expected and normal.

## 3.3 Required backend environment variables

See the consolidated table in §9 — do not set the Yutori API key here; it is handled differently (§8).

---

# 4. Database (PostgreSQL on Supabase) — Setup

## 4.1 Create the project

1. Create a Supabase account and a new project (free tier, no card required).
2. Choose a region close to your Fly.io backend region (§3.2) to minimize latency between them.
3. Set and store the database password Supabase asks for at creation time — you'll need it for the connection string.

## 4.2 Get the connection string — use the pooler, not the direct connection

Supabase exposes two connection modes: a **direct connection** and a **connection pooler** (PgBouncer, transaction mode). Because Fly's autostop/autostart machines start and stop the backend process (§3.2), the app can't rely on a small number of long-lived direct connections the way an always-on server would — use the **pooler connection string** (found in Supabase's Project Settings → Database → Connection string → "Transaction" mode, typically on port `6543`) as `DATABASE_URL`. This avoids exhausting Postgres's connection limit as the backend starts and stops.

## 4.3 Run migrations

Run schema migrations (Alembic, per `tdd.md`) against the Supabase connection string as a release step before the new app version starts serving traffic — e.g. as a Fly `release_command` in `fly.toml`, so migrations run once per deploy rather than on every request/instance start.

## 4.4 Backups

This is the one part that gets **simpler** than the old SQLite plan: Supabase manages backups itself, so the manual backup script or Litestream setup the SQLite plan would have needed is no longer necessary. The free tier's backup retention window is short, so for anything beyond routine safety, taking a manual `pg_dump` before a risky schema migration is still good practice (§11.4) — but there's no bespoke backup infrastructure to build.

## 4.5 Storage limits

The free tier caps storage at 500MB, which comfortably covers this app's `questions` / `scout_usage_log` / `credentials` tables (§12) at personal-tool scale.

---

# 5. Frontend (Next.js) — Vercel Setup

1. Import the repo into Vercel (vercel.com/new), set the project root to `frontend/` if this is a monorepo.
2. Set the environment variable:

```text
NEXT_PUBLIC_API_BASE_URL=https://<your-backend>.fly.dev
```

3. Deploy. Vercel builds and hosts the Next.js app, and automatically gives you a preview deployment on every pull request — useful even without a formal staging environment (see §11.3).
4. Optional: attach a custom domain in Vercel's Domains settings.

No shared filesystem or special networking is needed between frontend and backend — it's a plain HTTPS API client relationship. The frontend never talks to Supabase directly; all database access goes through the backend.

---

# 6. Email Service (Resend) Setup

1. Create a Resend account.
2. For MVP, Resend's shared test domain works without DNS setup; for a real "from" address, verify a domain you own (Domains → Add Domain → add the DNS records Resend gives you).
3. Generate an API key (API Keys → Create), set it as `RESEND_API_KEY` on the backend (§9).
4. No hosting needed — it's a REST API the backend calls when sending digest emails and Setup Mode confirmation emails (`prd.md` §21, §9.1).

---

# 7. LLM Provider Setup

Like the Yutori key (§8), **the Gemini and OpenAI keys are entered through the frontend, not set as backend environment variables** (`prd.md` §7.3, §27). No separate hosting is required either way — both are hosted API calls from the backend.

### Gemini — required for the MVP

1. Create a key in Google AI Studio.
2. Deploy the backend and frontend first (§3, §5) — challenge/digest generation won't work until this key is supplied.
3. Open the frontend and enter the Gemini key when prompted (or via Settings) — this calls `POST /settings/gemini-key`, which encrypts and stores it in Supabase, the same way the Yutori key is stored.
4. Model: `gemini-3.1-flash-lite` per `docs/gemini-api.md`. `profile.llm.provider` defaults to `"gemini"`.

### OpenAI — optional, for a future version

1. Create a key at platform.openai.com.
2. Enter it via Settings → `POST /settings/openai-key`, same pattern as Gemini.
3. Switching the active provider requires setting `profile.llm.provider` to `"openai"` (via `PATCH /profile`) — the app should reject this if no OpenAI key is stored yet.

---

# 8. Yutori Scout Setup

This one is different from every other credential in this guide: **the Yutori API key is not an environment variable.** Per `prd.md` §7.2/§27, the user enters it through the frontend at runtime, and the backend stores it encrypted in the `credentials` table — a table in the same Supabase Postgres database as everything else (keyed by `APP_SECRET_KEY`, which *is* an env var — see §9).

Setup sequence:

1. Create a Yutori account and confirm the one-time signup credit (`prd.md` §7.2).
2. Deploy the backend and frontend first (§3, §5) — the app will not allow Scout discovery to start until a key is supplied.
3. Open the frontend. It should prompt for the Yutori API key (blocking discovery until one is entered, per §7.2). Enter it — this calls `POST /settings/yutori-key`, which encrypts and stores it in Supabase.
4. Register the webhook target with Yutori when creating/configuring the Scout: `https://<your-backend-url>/webhooks/yutori`. This must be the backend's real public Fly.io URL from §3, not `localhost`.
5. If Yutori signs webhook payloads, store that signing secret as `YUTORI_WEBHOOK_SECRET` (an env var, not user-supplied) so `candidate_ingest` (§25) can validate authenticity per §27/`tdd.md` §9.3.

---

# 9. Secrets & Environment Variables — Consolidated Reference

| Variable | Set on | Required | Notes |
|---|---|---|---|
| `DATABASE_URL` | Fly.io (backend) | Yes | Supabase **pooler** connection string (§4.2), e.g. `postgresql://postgres.[ref]:[password]@[pooler-host]:6543/postgres` |
| `APP_SECRET_KEY` | Fly.io (backend) | Yes | Encrypts every user-supplied key at rest (Yutori, Gemini, OpenAI — §27) and signs the access-gate session cookie (§9.1) — generate with `openssl rand -hex 32`, never reuse across environments |
| `APP_ACCESS_PASSWORD` | Fly.io (backend) | Yes | The single shared password protecting the app (§9.1) — not a user account, just one password |
| `DIGEST_RECIPIENT_EMAIL` | Fly.io (backend) | Yes | Where the digest email gets sent — there's only one user, so this is a deploy-time setting, not a database field (`prd.md` §21) |
| `RESEND_API_KEY` | Fly.io (backend) | Yes | Email sending |
| `YUTORI_WEBHOOK_SECRET` | Fly.io (backend) | If Yutori supports webhook signing | Validates inbound webhook authenticity |
| `NEXT_PUBLIC_API_BASE_URL` | Vercel (frontend) | Yes | Points the frontend at the backend's public Fly.io URL |

Explicitly **not** in this table: the Yutori, Gemini, and OpenAI API keys, and the Supabase database password on its own. All three API keys live encrypted in the `credentials` table, entered via the frontend (§7, §8), never as env vars and never in a `.env` file. The Supabase password only ever appears embedded in the `DATABASE_URL` secret above — don't additionally store it as its own variable.

All backend secrets should be set through Fly's secrets mechanism (`flyctl secrets set`), never committed to git, per `prd.md` §27.

## 9.1 Application Access Gate

The app has no multi-user login, but it does sit behind a single shared password so a stranger who finds the URL can't use it (`prd.md` §27.1). `APP_ACCESS_PASSWORD` is the only credential involved — there's no separate user database. On the frontend, a lock screen calls `POST /auth/login`; on success the backend sets a signed session cookie (using `APP_SECRET_KEY`) and the frontend proceeds normally. `POST /feedback`, `POST /scout/confirm/{cycle_id}`, `POST /webhooks/yutori`, `GET /health`, and `GET /ready` are the only routes exempt from this gate.

---

# 10. Local Development Setup

Brief version, since this guide's focus is hosting:

**Backend:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in the vars from §9
uvicorn app.main:app --reload
```

For `DATABASE_URL` locally, either option works:
* **Simplest:** create a second, free Supabase project for development and point local `DATABASE_URL` at it — keeps dev and prod schemas easy to compare, no local Postgres install needed.
* **Fully offline:** run Postgres locally via Docker (`docker run -p 5432:5432 -e POSTGRES_PASSWORD=dev postgres:16`) and point `DATABASE_URL` at `postgresql://postgres:dev@localhost:5432/postgres`. Better if you're iterating heavily and don't want to consume Supabase free-tier limits or risk touching a shared project.

**Frontend:**
```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" > .env.local
npm run dev
```

**Gotcha:** Yutori can't reach `localhost`. To test webhook delivery locally, tunnel the backend with `ngrok http 8000` (or `cloudflared`) and register the tunnel's HTTPS URL as the webhook target for the duration of the test.

---

# 11. Continuous Deployment

Every production deploy goes through `.github/workflows/deploy.yml`. The decision is [ADR 0007](decisions/0007-continuous-delivery-pipeline.md), the tickets are M14 in `featuresticketlist.md`, and the reasoning is in the [CD Pipeline Report](https://claude.ai/code/artifact/ab72538a-f3f6-4bf5-94f5-c5e5bf6e03ba).

## 11.1 How a release happens

1. **Open a pull request.** `ci.yml` runs `lint`, `test`, `production-imports` and `frontend`. The `test` job takes every migration down to `base` and back up. The `main` ruleset won't allow a merge until all four pass.
2. **Merge it.** The Deploy workflow runs CI again, then compares `HEAD` with the last successful deploy (the newest `prod-*` tag). If nothing that ends up in the backend image changed (for example tests, docs or CI), nothing deploys.
3. **Approve it.** The run pauses at **Review deployments**. Open Actions → the run → Review deployments → tick `production` → Approve. If the run shows a *Migration* warning, read §11.3 first.
4. **It deploys.**
   1. `flyctl deploy` builds the image with this commit baked in, and runs `alembic upgrade head` as the release step.
   2. The smoke test waits for `/health` to report this commit, which decides success even if `flyctl` wrongly reports failure.
   3. The site's `/api` proxy is checked.
5. **It's tagged.** A green run creates the GitHub Release `prod-<run number>` and its tag, listing the merged pull requests.

The frontend moves in two phases:
- **Now:** Vercel's GitHub integration deploys every push to `main`, as before. Each page's `<meta name="app-version">` names its commit.
- **Phase 2 (needs a Vercel token):** the pipeline builds and deploys the frontend too (`vercel build`, then `vercel deploy --prebuilt --prod`), and `frontend/vercel.json` turns the GitHub integration off.

## 11.2 One-time setup

Do these in this order, before the pull request that adds `deploy.yml` is merged.

1. **Fly deploy token.** Run `fly tokens create deploy -a backend-soft-headland-5023 -x 8760h`. It creates a one-year token that can deploy this app and nothing else. Store it as the `FLY_API_TOKEN` secret on the `production` environment.
2. **The `production` environment.**
   - GitHub → Settings → Environments → New environment → `production`.
   - Required reviewers: yourself. Leave "Prevent self-review" off, since you trigger every run.
   - Deployment branches: `main` only.
   - Do this before the merge. A workflow that names a missing environment makes GitHub create it with no approval step.
3. **The `main` ruleset:**
   - Settings → Rules → a branch ruleset on `main`.
   - Require a pull request, with 0 approvals because this is a solo repo.
   - Require the status checks `lint`, `test`, `production-imports` and `frontend`.

For phase 2, the frontend:
1. Create a Vercel token under Account Settings → Tokens.
2. Run `vercel link` at the repository root and choose the existing project. `.vercel/project.json` now holds `orgId` and `projectId`; the root `.gitignore` keeps it out of git.
3. Add `VERCEL_TOKEN`, `VERCEL_ORG_ID` and `VERCEL_PROJECT_ID` to the `production` environment.

The project stays linked to the repository. Domains, the `BACKEND_URL` environment variable and Vercel's rollback are unchanged.

## 11.3 Releases that change the schema

Migrations run while the old machine is still serving, so each one must be safe for the old code. Use expand/contract:
- **Expand:** add new columns and tables in the release that starts using them.
- **Contract:** drop old ones only in a later release, once nothing deployed reads them.

Before approving any release that drops or rewrites data, back up Supabase:

```bash
pg_dump "<session-pooler connection string, port 5432>" --format=custom --file=backup-$(date +%F).dump
```

- Take the session-pooler string from Supabase → Connect. The transaction pooler on port 6543 won't work for `pg_dump`.
- The local `pg_dump` major version must be at least the server's.
- A migration downgrade restores the schema, never the rows. To get data back, use `pg_restore` from this dump.

The first pipeline deploy (2026-09-26) shipped migration `f6b2e9d40c17`, which drops `scouts`, `scout_events` and `scout_definitions.query_hash`. It ran without a backup because the data up to then was test data. Real usage starts there, so from now on every release that drops data gets the backup above.

## 11.4 Rollback

**Roll forward.** `git revert` the bad merge on a branch, open a pull request and merge it. The pipeline deploys the result like any other release, and a reverted migration's `downgrade()` runs only if you add a new migration that performs it.

Two things look like rollbacks but can't cross a migration:
- Re-running an old Deploy run.
- `fly deploy --image <old image>`.

Both run the old code's release step, `alembic upgrade head`, against a database already at a newer revision. Alembic stops with "Can't locate revision" and the deploy fails. GitHub also stops allowing re-runs after 30 days.

- **The backend, when no migration is involved:** `fly releases --image` lists past images. Then run `fly deploy --image <that image>` from `backend/`. The image still reports its own commit on `/health`.
- **The frontend:** Vercel dashboard → Deployments → the previous production deployment → Promote to Production.

## 11.5 Break-glass manual deploy

If GitHub Actions itself is down:
- Backend: `fly deploy` from `backend/`.
- Frontend: `vercel deploy --prod` from the repository root.

A manual backend deploy without `--build-arg GIT_SHA=<commit>` reports `"version": "dev"` on `/health`, which marks it as off-pipeline. The next pipeline run replaces it.

`fly deploy` has exited 1 after a successful release before. When that happens, trust `fly status` and `/health` over the exit code.

## 11.6 Deliberately not handled

Not handled yet: a staging environment, pull-request preview URLs (Vercel's automatic ones stop with Git deploys), automatic rollback, continuous deployment without approval, blue/green releases, infrastructure as code, and semantic version numbers. ADR 0007 and the report give the point at which each becomes worth adding.

---

# 12. Pre-Deploy Checklist

Before the first real deploy, have ready:

* [ ] Fly.io account + `flyctl`, with a credit card on file
* [ ] Supabase account + project created, pooler connection string copied (§4.2)
* [ ] Vercel account, repo imported
* [ ] Resend account + API key (domain verification optional for MVP)
* [ ] Gemini API key ready to enter via the frontend post-deploy (required, §7); OpenAI key optional
* [ ] Yutori account created (API key itself is entered post-deploy via the frontend, §8)
* [ ] `APP_SECRET_KEY` generated (`openssl rand -hex 32`) and stored as a Fly.io secret
* [ ] `APP_ACCESS_PASSWORD` chosen and stored as a Fly.io secret (§9.1)
* [ ] `DIGEST_RECIPIENT_EMAIL` set as a Fly.io secret (§9)
* [ ] `fly.toml` configured with `auto_stop_machines`/`auto_start_machines` (§3.2)
* [ ] Backend webhook URL known and ready to register with Yutori
