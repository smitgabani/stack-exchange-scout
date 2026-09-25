/** Client for the /yutori endpoints: the query template and the defaults (M13).
 *
 * Nothing here calls Yutori or spends anything — these only change what the
 * next run will send.
 */

import type { EffectiveSettings, YutoriSettings } from "./scout-api";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string" ? body.detail : `${path} failed: ${response.status}`,
    );
  }
  return response.json();
}

const send = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export type QueryTemplateConfig = {
  template: { body: string; version: number; is_default: boolean };
  default_body: string;
  placeholders: string[];
  /** The active template filled in with the current profile. */
  rendered: string;
  limits: { max_template_chars: number };
};

export type QueryTemplateVersion = {
  id: number;
  version: number;
  body: string;
  notes: string | null;
  is_active: boolean;
  created_at: string | null;
};

export type DefaultsView = {
  built_in: EffectiveSettings;
  /** Only what has been changed from the built-in defaults. */
  stored: YutoriSettings;
  effective: EffectiveSettings;
  run_cost_usd: number;
  default_output_schema: Record<string, unknown>;
  yutori_default_timezone: string;
  limits: { min_interval_seconds: number; max_subscribers: number; max_schema_chars: number };
};

export const yutoriApi = {
  queryTemplate: () => json<QueryTemplateConfig>("/api/yutori/query-template"),
  queryTemplates: () => json<{ versions: QueryTemplateVersion[] }>("/api/yutori/query-templates"),
  saveQueryTemplate: (body: string, notes?: string) =>
    json<{ version: number; is_active: boolean }>(
      "/api/yutori/query-templates",
      send("POST", { body, notes: notes || null }),
    ),
  activateQueryTemplate: (version: number) =>
    json<{ version: number }>(`/api/yutori/query-templates/${version}/activate`, send("POST")),
  resetQueryTemplate: () => json<{ version: number }>("/api/yutori/query-templates/reset", send("POST")),
  /** Renders a draft with the current profile. Free, stores nothing. */
  previewQueryTemplate: (body: string) =>
    json<{ rendered: string }>("/api/yutori/query-template/preview", send("POST", { body })),

  defaults: () => json<DefaultsView>("/api/yutori/defaults"),
  putDefaults: (body: YutoriSettings) => json<DefaultsView>("/api/yutori/defaults", send("PUT", body)),
  resetDefaults: () => json<DefaultsView>("/api/yutori/defaults", send("DELETE")),
};
