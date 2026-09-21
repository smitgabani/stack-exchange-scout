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
| GET | `/auth/session` | Current session status |

## Profile (`profile.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/profile` | The single profile document + its version |
| PATCH | `/profile` | Update topics/concepts/difficulty/preferences/digest settings; validates weights, dedups concepts, bumps the version |

## Settings (`settings.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/settings/yutori-key` | Store/replace the Yutori API key (encrypted) |
| GET | `/settings/yutori-key/status` | Whether a Yutori key is set |
| POST | `/settings/gemini-key` | Store/replace the Gemini API key |
| GET | `/settings/gemini-key/status` | Whether a Gemini key is set |
| POST | `/settings/openai-key` | Store/replace the OpenAI API key |
| GET | `/settings/openai-key/status` | Whether an OpenAI key is set |

## Scout status & pipeline stages (`scout.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/scout` | Current Scout status summary (used by the dashboard hero); also polls/finalizes an in-flight run |
| POST | `/scout/sync` | Free. Push the current profile-derived query to an existing Scout. Never creates one (`allow_create=False`) — creating a Scout is what `/scout/run` is for, behind a priced confirmation |
| POST | `/scout/run?mode=research\|scout` | **Spends ~$0.35.** Starts a discovery run now. 409 if one is already in flight |
| POST | `/scout/park` | Pause the Scout at Yutori. Free, idempotent |
| POST | `/scout/forget` | Drop this app's local reference to a Scout it can no longer administer (e.g. after switching accounts). Free, local only — touches no discovered questions |
| POST | `/scout/pull` | Ingest Yutori updates that never reached the webhook. Free |
| GET | `/scout/panel` | Combined status data for the Yutori monitors panel, in one call |
| POST | `/candidates/ingest` | Turn pending webhook payloads into candidate `question` rows (idempotent per Stack Overflow ID) |

## Scout definitions, runs, accounts (`definitions.py`, `accounts.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/scout-definitions` | List saved definitions (+ run cost, active account) |
| POST | `/scout-definitions` | Create a definition (free) |
| GET | `/scout-definitions/{id}` | One definition + its run history |
| PATCH | `/scout-definitions/{id}` | Edit a definition (free) |
| POST | `/scout-definitions/{id}/clone` | Duplicate a definition (free) |
| DELETE | `/scout-definitions/{id}` | Delete a definition (runs/challenges made from it are kept) |
| POST | `/scout-definitions/{id}/run?mode=research\|scout` | **Spends ~$0.35.** Starts a Yutori run |
| GET | `/scout-remote` | What actually exists at Yutori right now |
| GET | `/scout-instances` | Locally tracked Yutori instances |
| DELETE | `/scout-instances/{id}` | Delete the instance at Yutori (stops billing) |
| GET | `/scout-runs` | List runs |
| GET | `/scout-runs/{id}` | One run's detail, including per-question fate |
| POST | `/scout-runs/{id}/sync` | Ask Yutori for this run's status; collect result if ready |
| POST | `/scout-runs/sync` | Sync all outstanding runs |
| GET | `/scout-effectiveness` | Cost-per-question rollup, per definition |
| GET | `/accounts` | List stored Yutori API keys |
| POST | `/accounts` | Add a key |
| PATCH | `/accounts/{id}` | Rename a key |
| PUT | `/accounts/{id}/spend` | Set/clear a manual spend override |
| POST | `/accounts/{id}/activate` | Make this key the one new runs bill to |
| DELETE | `/accounts/{id}` | Remove a stored key (does not revoke it at Yutori) |
| GET | `/accounts/{id}/objects` | Yutori-side objects owned by this key |

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
| POST | `/questions/{id}/challenge` | **Spends 1 LLM call.** Generate a challenge from this question |
| POST | `/candidates/enrich` | Fetch real Stack Exchange data for pending candidates |
| POST | `/candidates/rank` | Re-score all candidates against the current profile |

## Digests & challenges (`digests.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/digests` | List digests |
| GET | `/digests/{id}` | One digest + its challenges |
| GET | `/challenges` | List challenges, filterable by source (digest/manual) |
| GET | `/challenges/{id}` | One challenge's full content |
| POST | `/challenges/{id}/reformat` | **Spends 0 or 1 LLM call.** Add any blocks a chosen format wants that this challenge lacks, keeping its ID and existing content |
| DELETE | `/challenges/{id}` | Delete a challenge only; source question and digest membership elsewhere are unaffected |
| POST | `/digest/generate` | **Spends N LLM calls.** Bundle best-scoring unused candidates into new challenges. Requires a Gemini key |
| POST | `/digest/send` | Email the most recent digest via Resend |

## LLM configuration (`llm.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/llm/config` | Active provider, prompt, limits, format, schema |
| GET | `/llm/prompts` | Prompt version history |
| POST | `/llm/prompts` | Save a new prompt version and activate it |
| POST | `/llm/prompts/{version}/activate` | Reactivate an older version |
| POST | `/llm/prompts/reset` | Revert to the default prompt shipped in code |
| GET | `/llm/preview` | Render the exact prompt for a question, free (no model call) |
| POST | `/llm/test` | **Spends 1 LLM call.** Run a real generation without saving anything |
| GET | `/llm/generations` | Log of past generations (provider/model/prompt version/format) |
| GET | `/llm/blocks` | The registry of challenge content blocks (core + optional) |
| GET | `/llm/formats` | List saved formats + the active one |
| POST | `/llm/formats` | Create a format |
| PATCH | `/llm/formats/{id}` | Edit a format |
| POST | `/llm/formats/{id}/default` | Make a format the default |
| DELETE | `/llm/formats/{id}` | Delete a format (existing challenges keep their content) |

## Cost-bearing endpoints, at a glance

- `POST /scout-definitions/{id}/run` — ~$0.35 per call (Yutori)
- `POST /questions/{id}/challenge` — 1 LLM call
- `POST /digest/generate` — N LLM calls (one per challenge generated)
- `POST /challenges/{id}/reformat` — 0 or 1 LLM call
- `POST /llm/test` — 1 LLM call

Every other endpoint is free to call as often as needed.
