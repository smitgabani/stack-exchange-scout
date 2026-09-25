"use client";

/**
 * The Scout workspace's data layer (ADR 0004).
 *
 * A *definition* is a saved query the user owns — free to create and edit. A
 * *run* spends about $0.35. Keeping that distinction visible in the types is
 * deliberate: everything that costs money goes through `runDefinition`, and
 * nothing else here can spend anything.
 */

export type RunMode = "research" | "scout";

export type DefinitionStats = {
  runs: number;
  spend_usd: number;
  questions: number;
  last_run: string | null;
  last_kind: "research_task" | "scout" | null;
  last_status: string | null;
  /** The account that paid for the most recent run. */
  last_account: string | null;
  /** Every account that has paid for a run of this scout. */
  accounts: string[];
};

/** A definition's preferred mechanism, kept in its free-form config. */
export function defaultMode(config: Record<string, unknown> | null | undefined): RunMode {
  return config?.default_mode === "scout" ? "scout" : "research";
}

export const MODE_LABEL: Record<RunMode, string> = {
  research: "Research task",
  scout: "Scout monitor",
};

export type Definition = {
  id: string;
  name: string;
  notes: string | null;
  query_source: "topics" | "freeform";
  /** What was last sent to Yutori. */
  query_text: string | null;
  /** What would be sent if it ran now — differs when topics have changed. */
  rendered_query: string | null;
  config: Record<string, unknown> | null;
  status: "draft" | "ready" | "archived";
  created_at: string | null;
  updated_at: string | null;
  stats?: DefinitionStats;
};

export type Run = {
  id: string;
  definition_id: string | null;
  kind: "research_task" | "scout";
  status: "running" | "succeeded" | "failed" | "timed_out";
  cost_usd: number | null;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  delivered_by: string | null;
  account_label: string | null;
  questions_found: number | null;
  error: string | null;
  questions?: number;
  candidates?: number;
  above_bar?: number;
};

/** What became of one question a run returned. */
export type RunQuestionFate =
  | "not_ingested"
  | "unparseable"
  | "awaiting_enrichment"
  | "filtered_out"
  | "dismissed"
  | "in_pool"
  | "made_a_challenge"
  | "solved"
  | "skipped";

export type RunQuestion = {
  stackoverflow_question_id: number;
  question_id: string | null;
  url: string;
  title: string | null;
  tags: string[];
  status: string | null;
  fate: RunQuestionFate;
  rejection_reason: string | null;
  candidate_score: number | null;
  difficulty: number | null;
  /** False = this run returned something the app already had. */
  first_seen_here: boolean;
  challenge_id: string | null;
};

export type RunDetail = {
  id: string;
  definition_id: string | null;
  kind: "research_task" | "scout";
  status: Run["status"];
  cost_usd: number | null;
  started_at: string | null;
  finished_at: string | null;
  delivered_by: string | null;
  account_label: string | null;
  error: string | null;
  returned: number;
  unique_questions: number;
  unparseable: number;
  new_here: number;
  already_known: number;
  above_bar: number;
  challenges: number;
  fates: Record<string, number>;
  event_status: string | null;
  has_payload: boolean;
  cost_per_new_question: number | null;
  questions: RunQuestion[];
};

export type Account = {
  id: number;
  label: string;
  key_name: string;
  is_active: boolean;
  account_fingerprint: string | null;
  created_at: string | null;
  /** What to display: the correction when set, the computed total otherwise. */
  spend_usd: number;
  /** What the run history adds up to — only as complete as what was recorded. */
  computed_spend_usd: number;
  /** What the user says it really cost. null = trust the calculation. */
  spend_override_usd: number | null;
  run_count: number;
  instance_count: number;
  reachable: boolean | null;
  error: string | null;
};

export type Instance = {
  id: string;
  definition_id: string | null;
  definition_name: string | null;
  kind: "research_task" | "scout";
  external_id: string;
  state: string | null;
  account_fingerprint: string | null;
  /** The name you gave the key that created this, when we know it. */
  account_label: string | null;
  /** true = the active key owns it, false = another account, null = unknown. */
  usable: boolean | null;
  created_at: string | null;
};

export type RemoteScout = {
  id: string;
  status: string | null;
  created_at: string | null;
  update_count: number | null;
  next_run: string | number | null;
  /** Whether this app has a record of it. Untracked + alive = billing unseen. */
  tracked: boolean;
  output_interval?: number | null;
  monthly_cost_usd?: number;
  definition_name?: string | null;
  /** A leftover: its scout has a newer monitor, and this one still bills. */
  superseded?: boolean;
};

export type RemoteTask = {
  id: string;
  status: string | null;
  created_at: string | null;
  tracked: boolean;
};

export type EffectivenessRow = {
  id: string;
  name: string;
  status: string;
  runs: number;
  spend_usd: number;
  questions: number;
  per_dollar: number | null;
};

/** A monitor this app believes is still running at Yutori. */
export type Monitor = {
  id: string;
  definition_id: string | null;
  definition_name?: string | null;
  external_id: string;
  state: string | null;
  account_fingerprint: string | null;
  output_interval: number;
  monthly_cost_usd: number;
  next_run: string | number | null;
  created_at: string | null;
  /** Live, but not its scout's newest monitor: a leftover still billing. */
  superseded?: boolean;
};

/**
 * Thrown for any non-2xx answer. `message` is still the backend's plain
 * `detail` (or `detail.message` when the detail is structured), so existing
 * `(error as Error).message` callers read the same text as before; `status`
 * and `detail` are there for the few that need to act on the answer.
 */
export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

/** The 409 a Scout-mode run gets when its scout already has a live monitor. */
export type LiveMonitorConflict = {
  code: "live_monitor";
  message: string;
  monitor: Monitor;
  run_cost_usd: number;
};

export function liveMonitorConflict(error: unknown): LiveMonitorConflict | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const detail = error.detail as Partial<LiveMonitorConflict> | null;
  return detail && detail.code === "live_monitor" ? (detail as LiveMonitorConflict) : null;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = (body as { detail?: unknown }).detail;
    const message =
      typeof detail === "string"
        ? detail
        : typeof (detail as { message?: unknown } | null)?.message === "string"
          ? (detail as { message: string }).message
          : `${path} failed (${response.status})`;
    throw new ApiError(message, response.status, detail);
  }
  return body as T;
}

export const scoutApi = {
  listDefinitions: (includeArchived = false) =>
    json<{
      definitions: Definition[];
      run_cost_usd: number;
      monitor_interval_seconds: number;
      active_account: string | null;
    }>(`/api/scout-definitions?include_archived=${includeArchived}`),

  getDefinition: (id: string) =>
    json<Definition & { runs: Run[]; run_cost_usd: number; monitor_interval_seconds: number }>(
      `/api/scout-definitions/${id}`,
    ),

  createDefinition: (body: Partial<Definition>) =>
    json<Definition>("/api/scout-definitions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  patchDefinition: (id: string, body: Partial<Definition>) =>
    json<Definition>(`/api/scout-definitions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  cloneDefinition: (id: string) =>
    json<Definition>(`/api/scout-definitions/${id}/clone`, { method: "POST" }),

  deleteDefinition: (id: string) =>
    json<{ deleted: boolean; kept: Record<string, number> }>(`/api/scout-definitions/${id}`, {
      method: "DELETE",
    }),

  /** The only call here that spends money. In scout mode a scout with a
   *  live monitor answers 409 (see `liveMonitorConflict`) unless `replace`
   *  is set, which stops that monitor before creating the new one. */
  runDefinition: (id: string, mode: "research" | "scout", options: { replace?: boolean } = {}) =>
    json<{ started: boolean; run_id: string; external_id: string; kind: string; cost_usd: number }>(
      `/api/scout-definitions/${id}/run?mode=${mode}${options.replace ? "&replace=true" : ""}`,
      { method: "POST" },
    ),

  /** Monitors this app believes are running, and what they cost a month.
   *  Local only — no call to Yutori — so cheap enough for the dashboard. */
  monitors: () =>
    json<{
      live_count: number;
      superseded_count: number;
      monthly_cost_usd: number;
      monitors: Monitor[];
      run_cost_usd: number;
    }>("/api/scout-monitors"),

  /** Stops every monitor that isn't its scout's newest. Free. */
  stopSuperseded: () =>
    json<{ stopped: string[]; failed: { external_id: string; error: string }[] }>(
      "/api/scout-monitors/stop-superseded",
      { method: "POST" },
    ),

  /** Stops one monitor at Yutori by its id, tracked or not. Free. */
  stopRemote: (externalId: string) =>
    json<{ stopped: boolean; tracked: boolean }>(
      `/api/scout-remote/${encodeURIComponent(externalId)}/done`,
      { method: "POST" },
    ),

  listRuns: () => json<{ runs: Run[] }>("/api/scout-runs"),

  getRun: (id: string) => json<RunDetail>(`/api/scout-runs/${id}`),

  /** Ask Yutori what happened to a run and collect the result if it is ready. */
  syncRun: (id: string) =>
    json<{
      status: string;
      remote_status?: string;
      delivered_by?: string;
      questions_found?: number | null;
      error?: string;
      note?: string;
    }>(`/api/scout-runs/${id}/sync`, { method: "POST" }),

  syncAllRuns: () => json<{ synced: { run_id: string; status: string }[] }>(
    "/api/scout-runs/sync",
    { method: "POST" },
  ),

  listInstances: () => json<{ instances: Instance[] }>("/api/scout-instances"),

  /** What actually exists at Yutori, as opposed to what this app recorded. */
  remoteInventory: () =>
    json<{
      scouts: RemoteScout[];
      research_tasks: RemoteTask[];
      untracked_scouts: string[];
      error: string | null;
      research_error?: string;
      live_count?: number;
      monthly_cost_usd?: number;
      /** Updates fetched for webhooks that never arrived, and ledger rows added. */
      pulled?: { fetched: number; new: number; recorded: number; error: string | null };
      /** Yutori's own 30-day run count next to this app's, for the active key. */
      usage?: {
        period: string;
        yutori_runs: number | null;
        recorded_runs: number;
        error: string | null;
      };
    }>("/api/scout-remote"),
  /** Deletes the Scout at Yutori. The only call here that stops something billing. */
  deleteInstance: (id: string) =>
    json<{ deleted: boolean; external_id?: string; note?: string }>(
      `/api/scout-instances/${id}`,
      { method: "DELETE" },
    ),
  /** Drops the local record only, for an instance a different account owns —
   *  `deleteInstance` refuses those with a 403 from Yutori. */
  forgetInstance: (id: string) =>
    json<{ forgotten: boolean; external_id?: string }>(
      `/api/scout-instances/${id}/forget`,
      { method: "POST" },
    ),
  effectiveness: () => json<{ rows: EffectivenessRow[] }>("/api/scout-effectiveness"),

  listAccounts: () => json<{ accounts: Account[] }>("/api/accounts"),
  addAccount: (body: { api_key: string; label: string; make_active: boolean }) =>
    json<Account>("/api/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  renameAccount: (id: number, label: string) =>
    json<Account>(`/api/accounts/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label }),
    }),
  /** null restores the computed total. */
  setAccountSpend: (id: number, spend_usd: number | null) =>
    json<Account>(`/api/accounts/${id}/spend`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spend_usd }),
    }),
  activateAccount: (id: number) => json<Account>(`/api/accounts/${id}/activate`, { method: "POST" }),
  removeAccount: (id: number) =>
    json<{ removed: boolean; label: string; kept: Record<string, number> }>(`/api/accounts/${id}`, {
      method: "DELETE",
    }),
  accountObjects: (id: number) =>
    json<{
      scouts: { id: string; status: string; created_at: string; update_count: number | null; tracked: boolean }[];
      usage?: Record<string, number> | null;
      rate_limits?: Record<string, unknown> | null;
      error: string | null;
    }>(`/api/accounts/${id}/objects`),
};

// Yutori sends epoch milliseconds on updates and ISO strings elsewhere; a
// number below this is seconds. Getting it wrong puts dates in the year 58,000.
const MS_THRESHOLD = 100_000_000_000;

export function when(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const date =
    typeof value === "number"
      ? new Date(value > MS_THRESHOLD ? value : value * 1000)
      : new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/** "every 30 days", "every 6 hours", "every 30 min". */
export function every(seconds: number | null | undefined): string {
  if (!seconds) return "—";
  if (seconds % 86400 === 0) {
    const days = seconds / 86400;
    return days === 1 ? "every day" : `every ${days} days`;
  }
  if (seconds % 3600 === 0) {
    const hours = seconds / 3600;
    return hours === 1 ? "every hour" : `every ${hours} hours`;
  }
  return `every ${Math.round(seconds / 60)} min`;
}

/** What a monitor at this interval costs over a 30-day month. */
export function monthlyCost(intervalSeconds: number, runCost: number): number {
  return intervalSeconds > 0 ? ((30 * 86400) / intervalSeconds) * runCost : 0;
}

export function money(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `$${value.toFixed(2)}`;
}
