# Frontend pages and their action buttons

Every page below now also carries an inline "ⓘ" info button next to each
meaningful action button in the actual UI — this document is the same
information in reference form, plus the pages' overall purpose.

Buttons that are purely cosmetic navigation, filter chips, dialog
confirm/cancel, or stepper +/- controls are not listed individually — their
label already says what they do, and their consequence is either none
(filtering a view) or already spelled out in the confirmation dialog they
open.

## Dashboard (`/`)

The home screen. Shows whether the Scout is scheduled or idle, your
current topics, the latest digest's challenges, and digest history.

- **Find new questions** (`RunScoutButton`) — asks Yutori to search Stack
  Overflow using your current topics. **Costs ~$0.35 per run.** Does not
  run on a schedule; this is the only way to start a run from here.
- **Generate digest** — builds a digest from your best-scored,
  not-yet-used candidates and turns them into challenges. Does not send
  anything.
- **Send latest digest** — emails the most recent digest via Resend. Does
  not generate a new one first.

## Topics (`/topics`)

Your profile: topics (with relevance weight), preferred/avoided concepts,
difficulty range, question preferences, and digest frequency/size. Nothing
here takes effect until you press **Save**.

- **How topics work** — opens a guide dialog explaining the matching and
  scoring rules (literal tag/title matching, weight vs. filtering, etc.).
- **+ Add topic** — adds a topic locally at 50% weight; not sent until Save.
- **+ Add** (Preferred concepts / Avoid cards) — adds a concept locally;
  a Preferred concept nudges scoring up, an Avoid concept rejects any
  matching question outright. Neither takes effect until Save.
- **Save** — writes the whole form to your profile and re-aims the Scout's
  next query at your new topics. Already-discovered questions keep the
  profile version they were found under, so nothing already in your pool
  is silently re-scored retroactively by this alone (that's what Re-score,
  below, does explicitly).

## Candidate pool (`/questions`)

Every question the Scout has found, filterable by status. Also hosts the
three manual pipeline-stage triggers used before scheduling exists.

- **Ingest webhooks** — pulls in Yutori results delivered by webhook but
  not yet added to the pool.
- **Enrich pending** — fetches real Stack Exchange data (score, answers,
  tags, body) for candidates that only have bare metadata.
- **Re-score** — re-runs scoring against your *current* profile for every
  candidate, so a recent topic/concept change is reflected everywhere.
- **Make this a challenge** (per question) — generates a challenge from
  this question via your LLM provider, with a format picker. **Costs one
  LLM call.** Does not touch Yutori credit or start a new discovery run.
- **Dismiss** (per question) — removes it from the visible pool without
  deleting it; it will not be re-discovered by a future run either.
  Reversible via **Restore**.

## Challenge history (`/challenges`)

Every challenge ever generated, from a digest or picked manually.

- **Delete** (per row) — permanently deletes that challenge only. The
  source question stays in the candidate pool and can be turned into a new
  challenge again. If the challenge was part of an emailed digest, that
  email's link breaks.

## Challenge detail (`/challenge/[id]`)

The actual challenge: problem, why it was picked, concepts, a starting
direction, progressively-revealed hints, and (once all hints are shown) a
gated "I'm stuck" reveal for solution-adjacent content.

- **Add sections / Format: X** — adds whatever blocks the chosen format
  wants that this challenge doesn't already have, leaving existing
  content (including revealed hints) untouched. **Costs one LLM call**, or
  nothing if there's nothing new to add. The challenge keeps its address.

## LLM workspace (`/llm/*`)

Everything about how challenges get generated.

### Pipeline (`/llm/pipeline`)
Read-only walkthrough of exactly what gets sent to the model and the
output shape it's required to return — the section's front door
(`/llm` redirects here).

### Curator prompt (`/llm/prompt`)
Edit the system instruction and user preamble sent to the LLM, preview the
exact rendered prompt for a real question (free), and test it live.

- **Save as new version** — writes a new prompt version and activates it
  immediately; the previous version stays in history so past challenges
  remain traceable to the exact text that produced them.
- **Reset to default** — reverts to the prompt shipped in the code.
- **Test generate** — sends the current (possibly unsaved) prompt to the
  provider for a chosen question and shows the raw result. **Costs one
  real LLM call.** Saves nothing — no challenge is created.
- **Activate** (per version row) — reactivates an older version without
  deleting the one currently active.

### Providers (`/llm/providers`)
Shows and switches which LLM provider (Gemini/OpenAI) generates
challenges, and lets you edit provider-specific settings (e.g. model name).

- **Save** — writes provider-specific configuration edits.
- Switching the active provider — changes which provider future
  generations use; does not retroactively change already-generated
  challenges.

### Formats (`/llm/formats`)
A format is a named set of blocks (some core/always-on, some optional).
Turning a block on changes both what the model is asked for and what the
challenge page renders, since both read the same block registry.

- **New format** — opens a blank draft; nothing is saved until Save format.
- **Save format** — creates or updates the format. Existing challenges
  made under a different format are unaffected.
- **Make default** — makes this format the one used automatically for new
  challenges (including from digests). Existing challenges are unaffected.
- **Delete** (per row) — deletes the format definition only; challenges
  already made with it keep their content and keep showing its name.

### Generations (`/llm/generations`)
A read-only log of every challenge-generating LLM call: which provider,
model, prompt version, and format produced it.

## Yutori workspace (`/yutori/*`)

Manages the underlying Yutori objects: scout/research-task *definitions*
(saved, free queries), the *runs* they produce (which cost money), the raw
*monitors* view, and the *accounts* (API keys) that pay for runs.

### Scouts (`/yutori/scouts`, `/yutori/scouts/[id]`)
Definitions are free to create/edit/clone; running one is the one action
here that spends money.

- **New scout** — opens a blank definition draft (free).
- **Save** (definition edit) — saves query/config edits (free).
- **Discard** — discards unsaved edits.
- **Clone** (per row) — duplicates a definition (free).
- **Run** (per row, opens a mode-choice dialog) — starts a run against
  Yutori. **Costs ~$0.35.** The dialog lets you pick "Research task"
  (recommended — runs immediately, one-shot) vs. "Scout" (a long-lived
  monitor; restarting one was measured *not* to reliably trigger a run, so
  it can cost the same and produce nothing).
- **Delete scout** — deletes the definition. Its runs and any challenges
  already produced from it are kept.
- **Archive / Unarchive** (status toggle) — hides a definition from the
  default list without deleting it.

### Runs (`/yutori/runs`, `/yutori/runs/[runId]`)
Read-only history plus two reconciliation actions per run:

- **Sync** — asks Yutori for this run's current status and collects the
  result if it has finished. Free.
- **Ingest** — same as the Questions page's "Ingest webhooks," scoped to
  this run's payload.

### Monitors (`/yutori/monitors`)
Ownership and raw inventory, across every account you've used — not a
status dashboard for one scout. (It used to be: a "Query being
searched / Configuration / Updates / Last run / Timeline / Health"
section here was built entirely on a legacy single-Scout model that
predated multi-account keys. That content was removed rather than fixed,
because it already exists correctly, per account, on a scout's own page
under Scouts and a run's own page under Runs. "Find new questions" on
the dashboard was on the same legacy path and now runs through a scout
definition too, the same way the Scouts page always has.)

**Remote objects** — every Scout/research task this app has created,
grouped by the account that owns it.
- **Delete at Yutori** (Scout, active-key rows only) — deletes the Scout
  at Yutori itself. The one action here that stops something from
  billing further.
- **Forget** (research task rows) — removes the local record of an
  already-finished task; nothing exists at Yutori to touch.
- **Forget** (rows owned by another account) — removes only this app's
  reference. Yutori is never contacted, so the Scout keeps running and
  billing under whichever account created it — this is for clearing a
  dead local link, not for stopping it.

**Everything at Yutori** — read live from Yutori for the currently
active account (Yutori has no way to list another account's Scouts
without switching keys to it).
- **List scouts and research tasks** — fetches this account's live
  inventory. Free, and useful for finding a Scout that's running (and
  billing) with no matching local record.

### Accounts (`/yutori/accounts`, `/yutori/accounts/[id]`)
Manages Yutori API keys ("accounts") that pay for runs.

- **Add a key** — stores a new Yutori API key.
- **Activate** (per row) — makes this the account new runs are billed to.
  Does not affect runs already made under a different key.
- **Rename** — relabels an account for your own reference.
- **Save** (spend override) — manually corrects the displayed spend total
  for an account when you know the computed total (sum of recorded run
  costs) is wrong or incomplete.
- **Remove** (per row) — deletes the stored key from this app. Does not
  revoke or delete anything at Yutori itself.

## Onboarding and login

These are single-path guided flows rather than dashboards, so they're not
covered button-by-button here:

- **`/login`** — the one shared password gate.
- **`/onboarding`** — first-run flow to save your Yutori and Gemini API
  keys before the rest of the app is usable.
