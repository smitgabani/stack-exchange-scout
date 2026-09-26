"use client";

/**
 * The Scout workspace's data layer (ADR 0004).
 *
 * A *definition* is a saved query the user owns — free to create and edit. A
 * *run* spends about $0.35. Keeping that distinction visible in the types is
 * deliberate: everything that costs money goes through `runDefinition`, and
 * nothing else here can spend anything.
 */

import { ApiError, json, send } from "./api";

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
  /** "manual" (someone pressed Run) or "schedule" (a monitor ran on its own). */
  trigger?: "manual" | "schedule" | null;
  /** The request's settings, webhook secret masked. Runs before M13 have none. */
  sent?: Record<string, unknown> | null;
  warnings?: string[];
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

/** What a scout may change about its Yutori request. Unset = inherit. */
export type YutoriSettings = {
  output_interval_seconds?: number;
  start?: "now" | "at";
  /** Wall-clock time in the scout's timezone, e.g. "2026-09-25T09:00". */
  start_at?: string | null;
  user_timezone?: string | null;
  user_location?: string | null;
  is_public?: boolean;
  email_from_yutori?: boolean;
  subscribers?: string[];
  output_schema?: Record<string, unknown>;
};

export type EffectiveSettings = Required<{
  [K in keyof YutoriSettings]: NonNullable<YutoriSettings[K]> | null;
}>;

export type SettingsView = {
  defaults: EffectiveSettings;
  overrides: YutoriSettings;
  effective: EffectiveSettings;
  /** The exact request bodies, webhook secret masked. */
  preview: { research: Record<string, unknown>; scout: Record<string, unknown> };
  cost: { per_run: number; monthly: number };
  run_cost_usd: number;
  default_output_schema: Record<string, unknown>;
  yutori_default_timezone: string;
  limits: { min_interval_seconds: number; max_subscribers: number; max_schema_chars: number };
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

/** A live monitor as Yutori reports it, and where it differs from its scout. */
export type MonitorRemote = {
  monitor: Monitor;
  remote: {
    status: string | null;
    query: string | null;
    output_interval: number | null;
    user_timezone: string | null;
    is_public: boolean | null;
    next_run: string | number | null;
    update_count: number | null;
    last_update: string | number | null;
    rejection_reason: string | null;
    paused_at: string | null;
    created_at: string | null;
    view_url: string | null;
    has_output_schema: boolean;
  };
  diff: { field: string; label: string; live: unknown; saved: unknown }[];
  /** The scout now asks for a different future start — only a replace can do that. */
  start_changed: boolean;
  /** Settings Yutori doesn't report back, so they can't be compared. */
  not_compared: string[];
};

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
    json<Definition>("/api/scout-definitions", send("POST", body)),

  patchDefinition: (id: string, body: Partial<Definition>) =>
    json<Definition>(`/api/scout-definitions/${id}`, send("PATCH", body)),

  /** Defaults, this scout's overrides, and the exact request each would send. */
  getSettings: (id: string) => json<SettingsView>(`/api/scout-definitions/${id}/settings`),

  /** Saves overrides. Free; takes effect on the next run. */
  putSettings: (id: string, body: YutoriSettings) =>
    json<SettingsView>(`/api/scout-definitions/${id}/settings`, send("PUT", body)),

  /** Drops every override, back to the defaults. */
  resetSettings: (id: string) =>
    json<SettingsView>(`/api/scout-definitions/${id}/settings`, { method: "DELETE" }),

  /** What unsaved settings would send. Free, stores nothing. */
  previewSettings: (id: string, body: YutoriSettings) =>
    json<SettingsView>(`/api/scout-definitions/${id}/settings/preview`, send("POST", body)),

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

  /** The monitor as Yutori has it, compared with its scout. Free (a read). */
  monitorRemote: (instanceId: string) =>
    json<MonitorRemote>(`/api/scout-instances/${instanceId}/remote`),

  /** Sends the scout's saved settings to its live monitor. Free — no run starts. */
  applyToMonitor: (instanceId: string) =>
    json<{ applied: boolean; warnings: string[] }>(`/api/scout-instances/${instanceId}/apply`, {
      method: "POST",
    }),

  /** Brings a stopped monitor back on its schedule. Doesn't run it now. */
  restartMonitor: (instanceId: string) =>
    json<{ restarted: boolean }>(`/api/scout-instances/${instanceId}/restart`, { method: "POST" }),

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

  listAccounts: () => json<{ accounts: Account[] }>("/api/accounts"),
  addAccount: (body: { api_key: string; label: string; make_active: boolean }) =>
    json<Account>("/api/accounts", send("POST", body)),
  renameAccount: (id: number, label: string) =>
    json<Account>(`/api/accounts/${id}`, send("PATCH", { label })),
  /** null restores the computed total. */
  setAccountSpend: (id: number, spend_usd: number | null) =>
    json<Account>(`/api/accounts/${id}/spend`, send("PUT", { spend_usd })),
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

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** "today", "yesterday", "3 days ago", "last month", "2 years ago"; "" for no date. */
export function ago(value: string | null | undefined): string {
  if (!value) return "";
  const days = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000));
  if (days < 30) return relative.format(-days, "day");
  if (days < 365) return relative.format(-Math.floor(days / 30), "month");
  return relative.format(-Math.floor(days / 365), "year");
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
