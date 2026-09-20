"use client";

/**
 * The Scout workspace's data layer (ADR 0004).
 *
 * A *definition* is a saved query the user owns — free to create and edit. A
 * *run* spends about $0.35. Keeping that distinction visible in the types is
 * deliberate: everything that costs money goes through `runDefinition`, and
 * nothing else here can spend anything.
 */

export type DefinitionStats = {
  runs: number;
  spend_usd: number;
  questions: number;
  last_run: string | null;
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

export type Account = {
  id: number;
  label: string;
  key_name: string;
  is_active: boolean;
  account_fingerprint: string | null;
  created_at: string | null;
  spend_usd: number;
  run_count: number;
  instance_count: number;
  reachable: boolean | null;
  error: string | null;
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

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = (body as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : `${path} failed (${response.status})`);
  }
  return body as T;
}

export const scoutApi = {
  listDefinitions: (includeArchived = false) =>
    json<{ definitions: Definition[]; run_cost_usd: number }>(
      `/api/scout-definitions?include_archived=${includeArchived}`,
    ),

  getDefinition: (id: string) => json<Definition & { runs: Run[] }>(`/api/scout-definitions/${id}`),

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

  /** The only call here that spends money. */
  runDefinition: (id: string, mode: "research" | "scout") =>
    json<{ started: boolean; run_id: string; external_id: string; kind: string; cost_usd: number }>(
      `/api/scout-definitions/${id}/run?mode=${mode}`,
      { method: "POST" },
    ),

  listRuns: () => json<{ runs: Run[] }>("/api/scout-runs"),
  effectiveness: () => json<{ rows: EffectivenessRow[] }>("/api/scout-effectiveness"),

  listAccounts: () => json<{ accounts: Account[] }>("/api/accounts"),
  addAccount: (body: { api_key: string; label: string; make_active: boolean }) =>
    json<Account>("/api/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
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

export function money(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `$${value.toFixed(2)}`;
}
