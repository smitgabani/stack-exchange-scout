# Feature list

Candidate features to review and pick from before they become milestone tickets in
[featuresticketlist.md](featuresticketlist.md). Nothing here is built yet.

- [1. Yutori task settings editor](#1-yutori-task-settings-editor)
- [2. Topic management](#2-topic-management) (placeholder)

Clickable mockup: [design-mockups/ScoutParameters.html](../design-mockups/ScoutParameters.html)

---

## 1. Yutori task settings editor

### Why

LLM prompts can already be edited in the app: saved versions, reset to default, and a free
preview. Yutori has nothing like that. Every setting sent to Yutori is fixed in code:

| What | Where it's fixed | Value today |
|---|---|---|
| How often a Scout runs | `settings.scout_run_interval_seconds` ([config.py:63](../backend/app/core/config.py)) | 30 days |
| Output shape | `CANDIDATE_OUTPUT_SCHEMA` ([yutori.py:70](../backend/app/integrations/yutori.py)) | fixed schema |
| Public or private | `create_scout(is_public=False)` | always private |
| Yutori's own email | `skip_email=True` | always off |
| Webhook | `settings.yutori_webhook_url` | the app's own |
| Start time, timezone, location | never sent | Yutori's defaults: start now, `America/Los_Angeles`, `San Francisco, CA, US` |
| Query wording | `_TEMPLATE` ([query_generator.py:5](../backend/app/services/query_generator.py)) | fixed template |

`ScoutDefinition.config` (JSONB) was meant to hold per-scout overrides ("interval, timezone"),
but nothing on the server reads it. Only `default_mode` is stored there, and only the frontend
reads that.

### Priority key

- **P1:** the core of what was asked. Build first.
- **P2:** makes P1 safe or complete.
- **P3:** nice to have.

---

### 1.1 Settings for each task type (reference)

Checked against the Yutori docs: [scouts-create](https://docs.yutori.com/reference/scouts-create),
[scouts-patch](https://docs.yutori.com/reference/scouts-patch.md),
[research-create](https://docs.yutori.com/reference/research-create.md) and
[email-settings](https://docs.yutori.com/reference/scouts-email-settings-update.md).

| Label in app | Yutori field | Scout | Research | Sent today | Proposed control | Validation / notes |
|---|---|:-:|:-:|---|---|---|
| Query | `query` | ✅ | ✅ | template from topics, or your own text | already editable (Query tab) | not empty. Can be changed on a live Scout (PATCH). |
| How often | `output_interval` (s) | ✅ | — | 30 days | presets (30 min · 1 h · 6 h · daily · weekly · 30 days) + custom | at least 1800 s on create. The app uses at least 3600 s on PATCH because the docs disagree. Shows a monthly cost estimate. |
| Start time | `start_timestamp` (unix) | ✅ | — | not sent (starts now) | "Now" or a date and time, in the chosen timezone | **Create only.** PATCH doesn't accept it, so changing it on a live Scout means recreating it (billable). |
| Timezone | `user_timezone` | ✅ | ✅ | not sent (LA) | searchable timezone list; defaults to the browser's timezone | Affects how Yutori reads "recent questions". The client already accepts it for research but no code passes it. |
| Location | `user_location` | ✅ | ✅ | not sent (SF) | text, `City, Region, Country` | optional; blank uses Yutori's default |
| Visibility | `is_public` | ✅ | — | `false` (forced) | Private / Public switch | **Public needs confirmation.** Public reports can be read by anyone with the Scout's ID, and the query contains your interests (ADR 0004, engineering-log). |
| Output format ("task spec") | `output_schema` (`task_spec` is deprecated) | ✅ | ✅ | `CANDIDATE_OUTPUT_SCHEMA` | Simple mode: checklist of per-question fields. Advanced mode: raw JSON editor. | Must be a JSON object with `questions` as an array whose items require `url`, because [ingest_service.py:58-89](../backend/app/services/ingest_service.py) reads exactly that. Has a reset to default. `output_schema` wins over `task_spec`, so the app only ever sends `output_schema`. |
| Yutori email | `skip_email` | ✅ | ✅ | `true` | "Also email me from Yutori" toggle | off by default because the app sends its own digest |
| Email subscribers | `PUT …/email-settings` `subscribers_to_add/remove` | ✅ | — | — | list of addresses | max 200 per request. Only applies to a live Scout. |
| Delivery | `webhook_url`, `webhook_format` | ✅ | ✅ | the app's `/webhooks/yutori?token=…`, format `scout` | **read-only**, masked | The URL carries the webhook secret, and ingestion depends on it. Yutori takes only one webhook, so pointing it anywhere else (e.g. Slack) would stop questions reaching the app. |

---

### 1.2 Features

#### F0 · Stop paying for Scouts nobody asked to keep (P0, build before anything else)

**The problem.** A Scout isn't a single run. It's a monitor that runs again at its interval
until it's stopped, and each of those runs costs $0.35.

- Every Scout-mode run of a scout calls `create_scout` (`definition_service.run_definition`),
  which makes a **new** monitor.
- `_sync_scout_run` marks the run finished but never stops the monitor.
- So each press adds another monitor. They all keep running every 30 days (the interval is
  hardcoded), and none of those later runs appear in the ledger (`scout_runs`), so the spend is
  invisible in the app.

**Why "just reuse the old one" doesn't work.** Creating a Scout is the only thing that starts a
run straight away. `restart` only brings a monitor out of `done` and waits for the next interval.
We checked this against the live API ([yutori.py `restart`](../backend/app/integrations/yutori.py),
engineering-log 2026-09-17). So "run now" on a monitor that already exists can't be done without
replacing it.

**The fix, in four parts:**

1. **One live monitor per scout, enforced on the server.**
   - A Scout-mode run of a scout that already has a live monitor (an instance of kind `scout`
     whose state isn't `done`) is **refused with 409**. The message says "This scout already has
     a live monitor", with its next run and interval.
   - The UI then offers two choices:
     - **Apply settings to the live monitor:** free. A PATCH, no new run; it runs at its next
       interval.
     - **Replace it:** billable, needs confirmation. It stops the old monitor first and only then
       creates the new one. If stopping fails for any reason other than "already gone" (404), the
       create is **not** attempted, so there are never two.
   - It locks the scout's row (`SELECT … FOR UPDATE`) so two clicks at once can't both create
     a monitor.
   - This is enforced in the service, not with a unique index, because the existing pile-up
     would make a unique-index migration fail.
2. **Every billed run gets a ledger row, including scheduled ones.**
   - Yutori's webhook body carries `scout.id`. When an update arrives for a known monitor and no
     `running` ledger row is waiting for it, the app records a `scout_runs` row:
     - `kind = scout`
     - `status = succeeded`
     - `delivered_by = webhook`
     - `cost_usd = run_cost_usd`
     - `detail.trigger = "schedule"`
   - A backup check compares Yutori's `update_count` for each monitor with the ledger, to catch
     scheduled runs whose webhook never arrived. It runs when Monitors loads and when runs are
     synced, and records the gap as `detail.trigger = "schedule_reconciled"`.
   - `_sync_scout_run` today counts **any** webhook received after a run started as that run's
     result. It is narrowed to the matching `scout.id`.
3. **Make the pile-up visible and easy to clear.**
   - Monitors shows, for the active key:
     - every live monitor, whether this app tracks it or not (`remote_inventory` already lists
       them)
     - which scout each belongs to
     - "superseded" on any older monitor that isn't that scout's newest
     - the **expected monthly cost** of all live monitors (30 days ÷ interval × $0.35 each)
   - One button, **Stop older monitors**, marks every superseded one `done` after confirmation.
   - The dashboard shows a warning while any live monitor exists: "N monitors running · ≈ $X a
     month".
4. **Make the choice clear at the moment of pressing Run.** In Scout mode the Run button reads
   **Start monitor**. The confirmation says it will keep running every *interval*, costing about
   *$X a month*, until stopped. Research mode keeps "Run once · $0.35".

*Touches:*
- Backend:
  - `definition_service.run_definition` (guard, replace, lock)
  - `definition_service._sync_scout_run` (scope to the monitor's ID)
  - a new `record_scheduled_runs` / reconcile step
  - `api/definitions.py` (409 + `?replace=true`, stop-older route)
  - `remote_inventory` (superseded flag, monthly cost)
- Frontend: `run-scout-button.tsx`, the run dialog in `yutori/scouts/*`, `yutori/monitors/page.tsx`,
  the dashboard warning.
- Tests: the refuse, replace and replace-failure paths; a scheduled webhook creating a ledger row;
  a redelivery not creating a second row; the reconcile step.

#### F1 · A separate form for each task type (P1)

The "How it runs" switch (Research / Scout) on a scout's page already exists. A new
**Parameters** tab next to Query, Runs and Settings shows a different form depending on that choice:

- **Research form:** Timezone, Location, Output format, Yutori email. Cost: "$0.35 per run".
- **Scout form:** everything in the research form, plus **Schedule** (how often, start time),
  **Visibility**, **Email subscribers**, and a **monthly cost estimate**.

Switching modes keeps both sets of values. Scout-only fields are kept but not sent when
running as research.

*Touches:*
- Frontend: `yutori/scouts/[id]/page.tsx` (new tab), `lib/scout-api.ts` (a typed `config`).
- Backend: `api/definitions.py` (validates `config`).

#### F2 · Settings saved per scout and used when it runs (P1)

- Store settings in `definition.config` under a typed key (e.g. `config.yutori`), checked on
  the server by a Pydantic model. Bad values return a plain-language **422**, the same way
  `prompt_service` does.
- `run_definition` reads them and passes them to `create_research_task` / `create_scout`.
- Extend `YutoriClient.create_scout` / `create_research_task` / `update_scout` to accept every
  field in 1.1. Only send the fields that are set, the same way `update_scout` already builds
  its payload.
- PATCH merges into `config` instead of replacing it. Today `update_definition` replaces the
  whole object.

*Touches:* `definition_service.py`, `integrations/yutori.py`, `api/definitions.py`, and new
tests that check the **request bodies** sent. No existing test does this; use
`httpx.MockTransport`, which is part of `httpx` already, so no new dependency.

#### F3 · Payload preview (P1)

A read-only JSON panel titled "What gets sent to Yutori" showing exactly the request body the
next run will send, with the webhook token masked by the existing `mask_webhook_url`. It
extends the existing "What gets sent to Yutori" query preview.

#### F4 · App-wide defaults tab (P2)

A new **Yutori → Defaults** tab holds the default for every field in 1.1. Each scout starts from
these defaults and can override single fields. An overridden field shows an "Overridden · Reset"
chip. This is the same override-and-reset pattern as block instructions
([block_service.py:372-395](../backend/app/services/block_service.py)), so there's no version
history, just one row.

#### F5 · Query template editor, the "Yutori prompt" (P1)

This is the "yutori scout prompt modifier" from the old stub. It works like the LLM prompt page:

- Edit the template that builds the query from your topics. Placeholders: `{topics}`,
  `{preferred_concepts}`, `{excluded_concepts}`, `{difficulty_min}`, `{difficulty_max}`.
- Every save is a new version. You can switch back to an older version, or reset to the
  built-in default.
- Free preview filled with your current topics.
- Rejects a template that is empty, too long, or uses an unknown placeholder.
- Backend: a `query_templates` table copying `prompt_templates` (partial unique index on
  `is_active`, fallback to `_TEMPLATE` when no row is active). `query_generator.generate`
  takes the active template.
- Lives on the Defaults tab (F4), or as its own "Query template" tab.

#### F6 · Push saved settings to a live Scout (P2)

When a Scout-mode scout has a live monitor at Yutori, compare what's saved with what Yutori
reports (`GET /scouting/tasks/{id}`):

- Banner: "Your live Scout is using older settings", listing the differences.
- **Apply to live Scout** is free: a PATCH of `query`, `output_interval`, `user_timezone`,
  `user_location`, `is_public`, `skip_email` and `output_schema`, plus email-settings for
  subscribers.
- A changed **start time** can't be patched. It offers **Recreate** instead (billable,
  needs confirmation).
- Checks ownership first (`list_instances.usable`), because Yutori answers 403 for another
  account's Scout.
- New route: `PATCH /scout-instances/{id}`.

#### F7 · Live Scout panel on Monitors (P2)

For each live Scout, show what Yutori currently has: status (active / paused / done), how often,
next run, timezone, visibility, update count, last update, rejection reason (e.g.
`insufficient_prepaid_balance`), and a link to view it on Yutori.

Actions:
- **Edit** (opens F6)
- **Restart**
- **Mark done**: archives it, can't be undone, needs confirmation
- **Delete**

The Yutori API has no pause, so the panel says so instead of showing a fake Pause button.

#### F8 · Record what each run sent (P2)

`run.detail` stores the exact settings used, secrets masked. The run detail page shows a
"Sent with" block, so you can tell when changing a setting changed the results.

#### F9 · Cost and safety checks (P1 for the estimate, P2 for the rest)

- **Monthly cost estimate** that updates as you change the interval: runs per month × cost per
  run from `run_cost_usd`. For example, every 30 min is about 1,440 runs, roughly **$504 a month**;
  daily is about $10.50; 30 days is $0.35.
- Confirmation dialog when choosing an interval under 1 day, making a Scout public, or
  recreating a Scout.
- "Reset to defaults" on the form. "Discard" throws away unsaved edits.
- Replace the hardcoded "$0.35" in the UI with `run_cost_usd`.

#### F10 · Yutori-side presets (P3)

One-click presets, e.g. "Cheap weekly check" (7 days, private, no email) or "Daily watch"
(1 day). These are just named bundles of F2 values.

---

### 1.3 Problems found while reviewing (to decide on, not fixed yet)

1. **Paid Scouts can pile up.** Each Scout-mode run of a scout creates another recurring
   Scout that is never stopped, and its later runs don't show up in the ledger. **Fix: F0.**
2. `update_scout(is_public=False)` sends `is_public: false` on every PATCH. Once visibility can
   be edited, this default would silently undo your choice.
3. Saving the profile still calls the old single-Scout `scout_service.sync`, which PATCHes that
   Scout's interval to `profile.scout.interval_days` (3 days) while runs set 30 days.
4. "$0.35" is hardcoded in `yutori/scouts/[id]/page.tsx` instead of `run_cost_usd`.

---

### 1.4 Screen sketches

These screens can be clicked through in the HTML mockup.

**Scout detail → Parameters (Scout mode)**

```
Yutori ▸ Scouts ▸ My interests
[ Query ] [ Parameters ] [ Runs (4) ] [ Settings ]

How it runs   ( Research | ●Scout )
┌ Live Scout is using older settings: interval 30 days → 1 day ─ [Apply to live Scout] ┐

SCHEDULE ────────────────────────────────────────────────────────────────
How often    [30 min][1 h][6 h][●Daily][Weekly][30 days][Custom…]
Starts       (●Now  ○At a time)  [2026-09-25 09:00]      Timezone [America/Toronto ▾]
             ≈ 30 runs/month · ≈ $10.50/month

WHERE YOU ARE ───────────────────────────────────────────────────────────
Location     [Toronto, ON, Canada          ]  blank = Yutori default

VISIBILITY ──────────────────────────────────────────────────────────────
             (●Private  ○Public)   Public reports can be read by anyone with the ID

EMAIL FROM YUTORI ───────────────────────────────────────────────────────
             [ ] Also email me          Subscribers: you@example.com  [+ Add]

OUTPUT FORMAT (task spec) ───────────────────── ( ●Fields | Raw JSON ) [Reset]
             [x] url (required)  [x] title  [x] tags  [x] answer_count  [ ] created_at …

DELIVERY ────────────────────────────────────────────────────────────────
Webhook      https://backend…fly.dev/webhooks/yutori?token=••••  (format: scout)  🔒

┌ What gets sent to Yutori ──────────────┐
│ { "query": "…", "output_interval": 86400, "start_timestamp": 0, … }              │
└────────────────────────────────────────┘
                                   [Reset to defaults] [Discard] [■ Save]
```

**Scout detail → Parameters (Research mode)**

```
How it runs   ( ●Research | Scout )     One run · $0.35

WHERE YOU ARE     Timezone [America/Toronto ▾]   Location [Toronto, ON, Canada]
EMAIL FROM YUTORI [ ] Also email me
OUTPUT FORMAT     ( ●Fields | Raw JSON )  …
DELIVERY          Webhook (read-only)
What gets sent to Yutori { … }                       [Discard] [■ Save]
```

**Yutori → Defaults**

```
[ Scouts ] [ Monitors ] [ Runs ] [ Accounts ] [ Defaults ]

QUERY TEMPLATE  v3 · active                        [Preview with my topics]
┌───────────────────────────────────────────────────────────────┐
│ Monitor Stack Overflow for newly posted or recently active … │
│ Current topics:                                               │
│ {topics}                                                      │
└───────────────────────────────────────────────────────────────┘
Placeholders: {topics} {preferred_concepts} {excluded_concepts} {difficulty_min} {difficulty_max}
Versions:  v3 active · v2 [Activate] · v1 [Activate]      [Reset to built-in] [■ Save as v4]

DEFAULT SETTINGS   How often [30 days]  Timezone [America/Toronto]  Visibility [Private] …
```

**Monitors → live Scout card**

```
My interests · Scout ● active                                  [View on Yutori ↗]
Every 1 day · next run Sep 25, 09:00 EDT · 12 updates · last Sep 24
Timezone America/Toronto · Private · Email off · Rejection: none
[Edit settings] [Restart] [Mark done…] [Delete…]      Pause isn't available in Yutori's API
```

---

## 2. Topic management

_Placeholder. Not scoped yet._
