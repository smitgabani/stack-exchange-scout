# 0006: One Live Monitor per Scout, and Editable Yutori Settings

**Status:** Accepted
**Date:** 2026-09-24
**Scope:** Amends ADR 0004 (discovery primitives), in particular its run-a-definition flow in scout mode. Implements `build-docs/featurelist.md` §1 (F0–F9).

## Context

ADR 0004 made a *definition* the thing the user owns and runs, with two primitives: a one-shot research task, and a Scout monitor. Two things were wrong once it was in use.

**1. Scout-mode runs piled up monitors that billed forever.** A Yutori Scout is not a run; it is a monitor that runs again at its `output_interval` until it is stopped, at $0.35 each time. `run_definition` created a new Scout on every Scout-mode press. `_sync_scout_run` marked the run finished but never stopped the monitor. So every press added another monitor, each running every 30 days, none stopped, and none of their later runs reached `scout_runs`. The app's spend figures were wrong in the reassuring direction.

"Reuse the existing monitor" is not available. Creating a Scout is the only thing that makes Yutori run now. `restart` only brings a `done` monitor back to `active` and waits for the next interval; this was measured against the live API (engineering-log 2026-09-19).

**2. Everything sent to Yutori was fixed in code.** The interval (30 days), visibility (private), Yutori email (off), output schema (`CANDIDATE_OUTPUT_SCHEMA`), webhook, and the query template were all fixed in code. Start time, timezone and location were never sent, so Yutori read "recent questions" in Los Angeles time. The user can edit the LLM prompt and wanted the same for Yutori.

## Decision

### 1. A definition has at most one live monitor, enforced in the service

- A Scout-mode run of a definition with a live monitor is refused with a structured **409** (`code: "live_monitor"`) that describes the monitor. "Live" means `state` is not `done`; an unknown state counts as live, because the expensive mistake is assuming a monitor stopped.
- `replace=true` stops the old monitor (`mark_done`) **before** creating the new one. If stopping fails for any reason except 404, nothing is created.
- A monitor owned by another key is never touched: Yutori answers 403, and the answer is to switch keys, not to retry.
- The definition row is locked (`SELECT … FOR UPDATE`) so two presses at once can't both see "no live monitor".

**Why a service check rather than a partial unique index.** The existing pile-up would violate one, so the migration would fail on the very database it's meant to fix. The index also couldn't see Yutori's view of whether a monitor is done. The row lock covers the race the index would have covered.

### 2. Every billed monitor run reaches the ledger

Yutori's webhook body carries `scout.id`. `record_scheduled_runs` writes one `scout_runs` row (`trigger = schedule`) for each webhook event that meets all of these:

- it names a tracked monitor;
- it arrived after that monitor's record was created;
- no ledger row already points at it;
- the monitor has no `running` manual run, which claims its own update first.

A late update for a manual run that already timed out completes that run instead of creating a second $0.35 row. An advisory lock serialises concurrent calls. Missed webhooks are pulled back through `GET …/updates` when Monitors lists what's at Yutori. `_sync_scout_run` now only accepts its own monitor's update, where before it accepted any update that arrived after it started.

A scheduled run that finds nothing sends no update, so it can't be seen per-run. Monitors compares Yutori's own 30-day run count (`/v1/usage`) with the ledger as the check for that.

There's no scheduler: ledger rows appear the next time the app is opened. That is acceptable, because the money has already been spent either way. The point is that the record becomes complete.

### 3. Settings are overrides in layers: built-in → defaults → scout

- A scout stores only what it overrides, in `scout_definitions.config["yutori"]`, validated by `YutoriSettings` with `extra="forbid"`.
- App-wide defaults are one row in `yutori_defaults`, stored the same way as overrides of the built-in values.
- So a change to the defaults reaches every scout that hasn't said otherwise, and each field can be reset on its own. This is the same shape as block instructions (ADR 0005), not versioned: settings are configuration, not text whose provenance matters.
- `task_settings.build_payload` is the single function that turns effective settings into a request body. The free preview and the real run both call it, and a `MockTransport` test pins the client's actual body to it.
- `start_at` is stored as wall-clock time and converted in the scout's timezone at send time, so changing the timezone moves the start with it.

### 4. The query template is versioned like the curator prompt

`query_templates` copies `prompt_templates`:

- rows are immutable, and one is active (enforced by a partial unique index);
- rollback is reactivation;
- the built-in template applies when nothing is active;
- a run records the template version it used.

A template is refused before it can cost a run if it:

- is empty or too long;
- uses an unknown placeholder;
- has an unmatched brace;
- leaves out `{topics}`.

### 5. Some things deliberately stay fixed

- **The webhook.** Its URL carries the secret that authenticates inbound results. Yutori delivers to exactly one URL, so pointing it anywhere else (Slack, Zapier) would stop questions reaching the app.
- **The output schema's core.** It is editable, but must keep `questions` as an array of objects requiring `url`, because that is what ingest reads.
- **`is_public`** is editable, but only behind a confirmation. Public reports are readable by anyone holding the Scout's id, and the query carries the user's interests. `update_scout` no longer defaults it to `false`, since that would silently undo the choice; the legacy path passes `false` explicitly.

### 6. Live monitors are updated deliberately, never implicitly

- Saving settings changes the next monitor created, not the one already running.
- The Parameters tab compares the live monitor with the saved settings and offers **Apply** (a free PATCH of everything except the start time) or **Replace** (when the start time changed, which Yutori can't patch; this is a paid run).
- Saving the profile **no longer** PATCHes anything. It used to reset the legacy Scout's interval to 3 days on every save.

## Consequences

- The user can see and stop every monitor, and the ledger records what they cost.
- A second Scout-mode press is now a decision (replace, keep, or apply) rather than a silent second subscription.
- Yutori's own interval floor differs between create (1800 s) and PATCH (3600 s in their docs). Applying a 30-minute interval to a live monitor sets an hour and says so; replacing gets 30 minutes.
- Location, Yutori email and subscribers aren't reported back by Yutori's detail endpoint, so the live comparison can't include them. Apply always sends them.
- F10 (presets) is deferred.
