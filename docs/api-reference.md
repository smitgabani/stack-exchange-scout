# Backend API reference

Base path in production is proxied through the frontend's `/api/*` →
`BACKEND_URL` rewrite. Routes below are grouped by the router module that
defines them (`backend/app/api/*.py`). All routes except `/auth/login` and
the Yutori webhook require a valid session cookie.

## Auth (`auth.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/login` | Check the shared password, set the session cookie |
| POST | `/auth/logout` | Clear the session cookie |
| GET | `/auth/bootstrap` | Session status plus whether the Yutori and Gemini keys are stored, in one call |

## Profile (`profile.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/profile` | The single profile document + its version |
| PATCH | `/profile` | Update topics/concepts/difficulty/preferences/digest settings; validates weights, dedups concepts, bumps the version |

## Settings (`settings.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/settings/{provider}-key` | Store/replace the API key for `yutori`, `gemini` or `openai` (encrypted) |
| GET | `/settings/{provider}-key/status` | Whether that provider's key is set |

## Scout definitions, runs, accounts (`definitions.py`, `accounts.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/scout-definitions` | List saved definitions (+ run cost, active account) |
| POST | `/scout-definitions` | Create a definition (free) |
| GET | `/scout-definitions/{id}` | One definition + its run history |
| PATCH | `/scout-definitions/{id}` | Edit a definition (free) |
| POST | `/scout-definitions/{id}/clone` | Duplicate a definition (free) |
| DELETE | `/scout-definitions/{id}` | Delete a definition (runs/challenges made from it are kept) |
| POST | `/scout-definitions/{id}/run?mode=research\|scout&replace=` | **Spends ~$0.35.** Starts a Yutori run. In scout mode, a scout that already has a live monitor gets **409** `{code: "live_monitor", message, monitor, run_cost_usd}`; `replace=true` stops that monitor first and creates nothing if stopping fails |
| GET | `/scout-definitions/{id}/settings` | This scout's Yutori settings: `defaults`, its `overrides`, the `effective` result, the exact masked request bodies (`preview.research` / `preview.scout`) and the cost. Free |
| PUT | `/scout-definitions/{id}/settings` | Save overrides (interval, start, timezone, location, visibility, Yutori email, subscribers, output schema). 422 with a plain-sentence `detail` when invalid. Free |
| DELETE | `/scout-definitions/{id}/settings` | Drop every override; the scout follows the defaults again |
| POST | `/scout-definitions/{id}/settings/preview` | What unsaved settings would send and cost. Free, stores nothing |
| GET | `/scout-remote` | What actually exists at Yutori right now, with each monitor's interval, monthly cost and whether it's a leftover (`superseded`). Also refreshes local monitor state, pulls missed updates and compares Yutori's 30-day run count with the ledger (`usage`) |
| POST | `/scout-remote/{external_id}/done` | Stop one monitor at Yutori, tracked or not. Free |
| GET | `/scout-monitors` | Monitors this app believes are live, their monthly cost and leftovers. Local only — no Yutori call — and records scheduled runs first |
| POST | `/scout-monitors/stop-superseded` | Stop every live monitor that isn't its scout's newest. Free |
| GET | `/scout-instances` | Locally tracked Yutori instances |
| GET | `/scout-instances/{id}/remote` | A live monitor as Yutori reports it, plus a `diff` against its scout's saved settings and `start_changed`. Free |
| POST | `/scout-instances/{id}/apply` | PATCH the scout's saved settings onto its live monitor (everything but the start time) and sync subscribers. Free — no run starts |
| POST | `/scout-instances/{id}/restart` | Bring a stopped monitor back on its schedule (doesn't run it now). Refused while the scout has another live monitor |
| POST | `/scout-instances/{id}/forget` | Drop the local record only, for an instance another key owns |
| DELETE | `/scout-instances/{id}` | Delete the instance at Yutori (stops billing) |
| GET | `/scout-runs` | List runs |
| GET | `/scout-runs/{id}` | One run's detail, including per-question fate |
| POST | `/scout-runs/{id}/sync` | Ask Yutori for this run's status; collect result if ready |
| POST | `/scout-runs/sync` | Sync all outstanding runs |
| GET | `/accounts` | List stored Yutori API keys |
| POST | `/accounts` | Add a key |
| PATCH | `/accounts/{id}` | Rename a key |
| PUT | `/accounts/{id}/spend` | Set/clear a manual spend override |
| POST | `/accounts/{id}/activate` | Make this key the one new runs bill to |
| DELETE | `/accounts/{id}` | Remove a stored key (does not revoke it at Yutori) |
| GET | `/accounts/{id}/objects` | Yutori-side objects owned by this key |

## Yutori template & defaults (`yutori.py`)

Nothing here calls Yutori or spends anything — these change what the next run sends.

| Method | Path | Purpose |
|---|---|---|
| GET | `/yutori/query-template` | The active query template, the built-in one, the placeholders, and the active one rendered with the current profile |
| GET | `/yutori/query-templates` | Every stored version |
| POST | `/yutori/query-templates` | Save a new version and activate it. 422 if empty, too long, an unknown placeholder, an unmatched brace, or no `{topics}` |
| POST | `/yutori/query-templates/{version}/activate` | Roll back to a stored version |
| POST | `/yutori/query-templates/reset` | Back to the built-in template |
| POST | `/yutori/query-template/preview` | Render a draft with the current profile. Stores nothing |
| GET | `/yutori/defaults` | The settings every scout inherits: `built_in`, what's been changed (`stored`), and the `effective` result |
| PUT | `/yutori/defaults` | Change the defaults (same fields and validation as a scout's settings) |
| DELETE | `/yutori/defaults` | Back to the built-in defaults |

## Webhooks (`webhooks.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/webhooks/yutori` | Receives Yutori's async run results. At-least-once delivery — payloads are stored for `/candidates/ingest` to process idempotently, not processed inline |

## Questions / candidates (`questions.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/questions` | List, filterable by status/answers/difficulty/rejection reason |
| GET | `/questions/{id}` | One question |
| POST | `/questions/{id}/dismiss` | Mark as user-dismissed (reversible, not re-discovered) |
| POST | `/questions/{id}/restore` | Undo a dismissal |
| POST | `/questions/{id}/complete` | Mark a challenged question solved |
| POST | `/questions/{id}/reopen` | Undo a completion |
| POST | `/candidates/ingest` | Turn pending webhook payloads into candidate `question` rows (idempotent per Stack Overflow ID) |
| POST | `/candidates/enrich` | Fetch real Stack Exchange data for pending candidates |
| POST | `/candidates/rank` | Re-score all candidates against the current profile |

## Digests & challenges (`digests.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/challenges` | List challenges, filterable by source (digest/manual) |
| GET | `/challenges/{id}` | One challenge's full content |
| DELETE | `/challenges/{id}` | Delete a challenge only; source question and digest membership elsewhere are unaffected |
| POST | `/digest/send` | Email the most recent digest via Resend |

## Background jobs (`jobs.py`)

Anything that calls a model runs as a job: the request returns at once with a
job row, and `GET /jobs/{id}` reports how it went. Each start requires a Gemini
key and is rate-limited.

| Method | Path | Purpose |
|---|---|---|
| POST | `/jobs/digest-generate` | **Spends N LLM calls.** Bundle best-scoring unused candidates into new challenges |
| POST | `/jobs/challenge-create` | **Spends 1 LLM call.** Generate a challenge from one question |
| POST | `/jobs/reformat` | **Spends 0 or 1 LLM call.** Add any blocks a chosen format wants that a challenge lacks, keeping its ID and existing content |
| POST | `/jobs/llm-test` | **Spends 1 LLM call.** Run a real generation without saving anything |
| GET | `/jobs/{id}` | A job's status, and its result or error once finished |

## LLM configuration (`llm.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/llm/config` | Active provider, prompt, limits, format, schema |
| GET | `/llm/prompts` | Prompt version history |
| POST | `/llm/prompts` | Save a new prompt version and activate it |
| POST | `/llm/prompts/{version}/activate` | Reactivate an older version |
| POST | `/llm/prompts/reset` | Revert to the default prompt shipped in code |
| GET | `/llm/preview` | Render the exact prompt for a question, free (no model call) |
| GET | `/llm/generations` | Log of past generations (provider/model/prompt version/format) |
| GET | `/llm/blocks` | The registry of challenge content blocks (core + optional) |
| GET | `/llm/formats` | List saved formats + the active one |
| POST | `/llm/formats` | Create a format |
| PATCH | `/llm/formats/{id}` | Edit a format |
| POST | `/llm/formats/{id}/default` | Make a format the default |
| DELETE | `/llm/formats/{id}` | Delete a format (existing challenges keep their content) |

## Cost-bearing endpoints, at a glance

- `POST /scout-definitions/{id}/run` — ~$0.35 per call (Yutori)
- `POST /jobs/challenge-create` — 1 LLM call
- `POST /jobs/digest-generate` — N LLM calls (one per challenge generated)
- `POST /jobs/reformat` — 0 or 1 LLM call
- `POST /jobs/llm-test` — 1 LLM call

Every other endpoint is free to call as often as needed.
