# 0007: Continuous Delivery Through One GitHub Actions Pipeline

**Status:** Accepted
**Date:** 2026-09-26
**Scope:** Replaces the deploy sketch in `deployment-setup-guide.md` §11. The reasoning and the industry comparison are in the [CD Pipeline Report](https://claude.ai/code/artifact/ab72538a-f3f6-4bf5-94f5-c5e5bf6e03ba). Tickets are in M14 of `featuresticketlist.md`.

## Context

Code reached production by three routes, and only one was automatic:

- **Vercel** deployed the frontend on every push through its GitHub integration. It started at the same moment as CI and didn't wait for it. It also built pushes that changed no frontend file: 42 of the first 97 commits were backend-only, docs or CI.
- **The backend** reached Fly only when someone ran `fly deploy` from a laptop. After the 2026-09-25 cleanup, the frontend went live on push while the backend stayed on old code.
- **Migrations** ran as Fly's `release_command` inside that manual deploy.

Nothing enforced the order between the two apps. On 2026-09-22, removing a live endpoint and renaming a table while old code ran each took the app down. CI checked only the backend, and `main` had no branch protection.

## Decision

1. **GitHub Actions is the only path to production.** `.github/workflows/deploy.yml` runs on every push to `main`. `fly deploy` from a laptop remains possible, but only as a break-glass step.
2. **Continuous delivery, not continuous deployment.** The deploy job targets a GitHub environment, `production`, with the owner as required reviewer and `main` as the only allowed branch. Every release waits for one approval. The repository is public, so this costs nothing.
3. **Gated stages.** `ci.yml` becomes a reusable workflow (`workflow_call`). The deploy workflow calls it first, and nothing deploys unless it passes. CI gains a frontend job (`npm ci`, lint, build) and a migration round-trip (`downgrade -1`, then `upgrade head`).
4. **Change detection against the last successful deploy.** A plain `git diff` between `HEAD` and the newest `prod-*` tag decides what to deploy. It doesn't compare with the previous push, so a rejected, failed or cancelled deploy's changes ship with the next run. Only files that end up in the running image count (`backend/app`, `alembic`, `Dockerfile`, `fly.toml`, the lockfile), so tests and docs deploy nothing. When there's no tag yet, everything counts as changed. A change under `backend/alembic/versions/` shows a warning before the approval.
5. **One deploy job, backend first.**
   1. Deploy the backend with `flyctl deploy --remote-only`, then smoke-test it.
   2. Deploy the frontend, then smoke-test the site.

   The smoke test, not `flyctl`'s exit code, decides whether the backend release worked. `flyctl` has reported failure after a good release, so that step doesn't stop the job. Any failed smoke test stops everything after it. A release that removes an API ships the frontend change first and the removal in a later release. `concurrency` sits on the deploy job, so CI never waits behind a pending approval.
6. **Vercel builds in the pipeline, not from Git.** This is phase 2, which needs a Vercel token:
   - `frontend/vercel.json` sets `git.deploymentEnabled: false`.
   - The pipeline runs `vercel pull`, `vercel build --prod` and `vercel deploy --prebuilt --prod`, so the frontend that goes live is the build the pipeline made.
   - The project stays linked, so domains, environment variables and Vercel's own rollback are unchanged.

   Until then, Vercel's GitHub integration keeps deploying the frontend on every push, and the pipeline smoke-tests the site's `/api` proxy after each backend release.
7. **Every release is stamped and tagged.**
   - The backend image is built with a `GIT_SHA` build argument, so the image itself names its commit, even after a rollback, and `/health` reports it.
   - The frontend inlines its commit at build time through `next.config.ts` `env` into `<meta name="app-version">`. That covers static pages and pages rendered on request, and it falls back to `VERCEL_GIT_COMMIT_SHA` in builds Vercel runs from Git.
   - The smoke test requires the backend commit just deployed.
   - A successful run creates the GitHub Release `prod-<run number>` and its tag, with generated notes.
   - Third-party code in the privileged job is pinned: `setup-flyctl` to a commit and `flyctl` to a version.
8. **Migrations follow expand/contract.** Drop a column or table one release after the code stops reading it. Back up Supabase with `pg_dump` before approving a release that drops or rewrites data.

## Consequences

- Four deploy secrets live on the `production` environment: `FLY_API_TOKEN` (a deploy token scoped to the one app), `VERCEL_TOKEN`, `VERCEL_ORG_ID` and `VERCEL_PROJECT_ID`. Jobs can read them only after the approval.
- Pull requests lose Vercel's automatic preview URLs. A preview job can bring them back if they're missed.
- CI no longer runs on its own for pushes to `main`. The deploy workflow runs it instead, so a failing check shows up on the Deploy run.
- The environment must exist, with its reviewer, **before** `deploy.yml` reaches `main`. GitHub creates a missing environment on first use, and without protection rules.
- The first pipeline deploy (2026-09-26) shipped migration `f6b2e9d40c17`, which drops `scouts`, `scout_events` and `scout_definitions.query_hash`. The owner declared the production data up to then to be test data, so no backup was taken. Real usage starts from that deploy, and §11.3's backup rule applies from then on.
- **Rolling back is rolling forward.** `git revert` the bad merge and let the pipeline deploy the result. Neither re-running an old run nor `fly deploy --image` can cross a migration: the old code's release step runs `alembic upgrade head` against a database that is already at a newer revision, and fails.
- Deliberately left out, with the trigger for revisiting each in the report: a staging environment, automatic rollback, continuous deployment without approval, blue/green releases, infrastructure as code, and semantic version numbers.
