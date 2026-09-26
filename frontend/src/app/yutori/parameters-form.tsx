"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  type EffectiveSettings,
  type RunMode,
  type YutoriSettings,
  every,
  money,
  monthlyCost,
} from "@/lib/scout-api";
import { ConfirmDialog } from "../confirm-dialog";
import { InfoButton } from "../info-button";
import ws from "../workspace.module.css";
import styles from "./parameters.module.css";

/**
 * The settings a scout sends to Yutori, as a form (M13).
 *
 * Works on *overrides*: `saved` holds only the fields that differ from
 * `base` (the defaults), so a change to the defaults still reaches every
 * scout that hasn't said otherwise, and each overridden field can be reset on
 * its own. The same form edits the app-wide defaults, with the built-in
 * values as its base.
 *
 * Which groups show depends on how the scout runs: a research task runs once,
 * so it has no schedule, no visibility and no subscribers.
 */

const PRESETS: [string, number][] = [
  ["30 min", 1800],
  ["1 hour", 3600],
  ["6 hours", 21600],
  ["Daily", 86400],
  ["Weekly", 604800],
  ["30 days", 2592000],
];

// Suggestions only — the field accepts any IANA name. The list omits "UTC".
const TIMEZONES = [...Intl.supportedValuesOf("timeZone"), "UTC"];

type Schema = {
  properties?: { questions?: { items?: { properties?: Record<string, unknown> } } };
};

function schemaFields(schema: unknown): string[] {
  return Object.keys((schema as Schema)?.properties?.questions?.items?.properties ?? {});
}

/** The default schema, narrowed to the chosen fields. `url` always stays. */
function schemaWith(base: Record<string, unknown>, keep: string[]): Record<string, unknown> {
  const copy = structuredClone(base) as Schema & Record<string, unknown>;
  const items = copy.properties?.questions?.items;
  if (items?.properties) {
    items.properties = Object.fromEntries(
      Object.entries(items.properties).filter(([key]) => key === "url" || keep.includes(key)),
    );
  }
  return copy;
}

export function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

export type ParametersFormProps = {
  /** "scout" edits one scout's overrides; "defaults" edits the app-wide ones. */
  variant: "scout" | "defaults";
  /** Which groups to show. The defaults page shows everything. */
  mode: RunMode;
  /** What applies to a field nobody has set. */
  base: EffectiveSettings;
  /** Only the fields explicitly set here. */
  saved: YutoriSettings;
  defaultSchema: Record<string, unknown>;
  yutoriDefaultTimezone: string;
  runCost: number;
  /** The masked request bodies for the saved settings. */
  initialPreview?: { research: Record<string, unknown>; scout: Record<string, unknown> };
  /** Free: what a draft would send. Its errors are the server's validation. */
  previewFor?: (draft: YutoriSettings) => Promise<{
    preview: { research: Record<string, unknown>; scout: Record<string, unknown> };
  }>;
  /** A key that changes when a different scout (or the defaults) is shown. */
  scopeKey: string;
  saving?: boolean;
  onSave: (values: YutoriSettings) => void;
  onResetAll: () => void;
};

export function ParametersForm({
  variant,
  mode,
  base,
  saved,
  defaultSchema,
  yutoriDefaultTimezone,
  runCost,
  initialPreview,
  previewFor,
  scopeKey,
  saving = false,
  onSave,
  onResetAll,
}: ParametersFormProps) {
  // null = no edits: show what's saved. Same pattern as the LLM prompt editor.
  const [draft, setDraft] = useState<YutoriSettings | null>(null);
  const [schemaMode, setSchemaMode] = useState<"fields" | "raw">("fields");
  const [rawSchema, setRawSchema] = useState<string | null>(null);
  const [newSubscriber, setNewSubscriber] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [asking, setAsking] = useState<"public" | "often" | "reset" | null>(null);

  const values: YutoriSettings = draft ?? saved;
  const dirty = draft !== null;
  const scout = mode === "scout";

  function value<K extends keyof YutoriSettings>(key: K): EffectiveSettings[K] {
    const own = values[key];
    return (own !== undefined && own !== null ? own : base[key]) as EffectiveSettings[K];
  }
  const isSet = (key: keyof YutoriSettings) => values[key] !== undefined && values[key] !== null;
  const edit = (patch: YutoriSettings) => setDraft({ ...values, ...patch });
  const unset = (key: keyof YutoriSettings) => {
    const next = { ...values };
    delete next[key];
    setDraft(next);
  };

  const interval = value("output_interval_seconds") ?? 2592000;
  const isPreset = PRESETS.some(([, seconds]) => seconds === interval);
  // Shown in the largest unit that divides it exactly, so 90 minutes reads
  // as 90 minutes rather than a rounded 2 hours.
  const customUnit = interval % 86400 === 0 ? 86400 : interval % 3600 === 0 ? 3600 : 60;
  const monthly = monthlyCost(interval, runCost);
  const schema = (value("output_schema") ?? defaultSchema) as Record<string, unknown>;
  const chosenFields = schemaFields(schema);
  const allFields = Array.from(new Set([...schemaFields(defaultSchema), ...chosenFields]));
  const subscribers = (value("subscribers") ?? []) as string[];
  const browserZone =
    typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : null;

  const debouncedDraft = useDebounced(draft, 400);
  const livePreview = useQuery({
    queryKey: ["settings-preview", scopeKey, JSON.stringify(debouncedDraft)],
    queryFn: () => previewFor!(debouncedDraft ?? {}),
    enabled: Boolean(previewFor && debouncedDraft),
    retry: false,
    staleTime: Infinity,
  });
  const preview = dirty ? livePreview.data?.preview : initialPreview;
  const serverError = dirty && livePreview.isError ? (livePreview.error as Error).message : null;
  const shown = preview ? (scout ? preview.scout : preview.research) : null;

  const override = (field: keyof YutoriSettings) => {
    if (!isSet(field)) return null;
    return (
      <span className={styles.override}>
        {variant === "scout" ? "Overridden" : "Changed"}
        <button type="button" onClick={() => unset(field)}>
          Reset
        </button>
      </span>
    );
  };

  function save() {
    if (scout && interval < 86400 && variant === "scout") {
      setAsking("often");
      return;
    }
    onSave(values);
    setDraft(null);
  }

  return (
    <div className={styles.layout}>
      <div className={styles.form}>
        {scout && (
          <div className={styles.group}>
            <div className={styles.groupName}>
              <span className={styles.groupTitle}>Schedule</span>
              <span className={styles.api}>output_interval · start_timestamp</span>
            </div>
            <div className={styles.groupBody}>
              <span className={ws.label}>How often</span>
              <div className={ws.seg}>
                {PRESETS.map(([label, seconds]) => (
                  <button
                    key={seconds}
                    type="button"
                    className={`${ws.segItem} ${interval === seconds ? ws.on : ""}`}
                    onClick={() => edit({ output_interval_seconds: seconds })}
                  >
                    {label}
                  </button>
                ))}
                <button
                  type="button"
                  className={`${ws.segItem} ${!isPreset ? ws.on : ""}`}
                  onClick={() => edit({ output_interval_seconds: 12 * 3600 })}
                >
                  Custom…
                </button>
              </div>
              {!isPreset && (
                <div className={styles.row}>
                  <input
                    id="interval-amount"
                    className={`${ws.input} ${styles.narrow}`}
                    type="number"
                    min={1}
                    aria-label="Interval amount"
                    value={interval / customUnit}
                    onChange={(e) =>
                      edit({ output_interval_seconds: Math.max(1, Number(e.target.value)) * customUnit })
                    }
                  />
                  <select
                    id="interval-unit"
                    className={`${ws.input} ${styles.narrow}`}
                    aria-label="Interval unit"
                    value={customUnit}
                    onChange={(e) =>
                      edit({ output_interval_seconds: (interval / customUnit) * Number(e.target.value) })
                    }
                  >
                    <option value={60}>minutes</option>
                    <option value={3600}>hours</option>
                    <option value={86400}>days</option>
                  </select>
                </div>
              )}
              {interval < 1800 && <span className={styles.error}>Yutori&apos;s minimum is 30 minutes.</span>}
              <div className={`${styles.cost} ${interval < 86400 ? styles.hot : ""}`}>
                <strong>≈ {money(monthly)} a month</strong>
                <span className={ws.hint}>
                  runs {every(interval)} × {money(runCost)}, plus {money(runCost)} for the run when
                  it&apos;s created
                </span>
              </div>
              {override("output_interval_seconds")}

              <span className={ws.label}>Starts</span>
              <div className={styles.row}>
                <label className={styles.check}>
                  <input
                    type="radio"
                    name={`start-${scopeKey}`}
                    checked={value("start") !== "at"}
                    onChange={() => edit({ start: "now", start_at: null })}
                  />
                  Now
                </label>
                <label className={styles.check}>
                  <input
                    type="radio"
                    name={`start-${scopeKey}`}
                    checked={value("start") === "at"}
                    onChange={() =>
                      edit({
                        start: "at",
                        start_at: value("start_at") ?? new Date(Date.now() + 86400000).toISOString().slice(0, 11) + "09:00",
                      })
                    }
                  />
                  At a time
                </label>
                <input
                  id="start-at"
                  className={ws.input}
                  type="datetime-local"
                  aria-label="Start time"
                  disabled={value("start") !== "at"}
                  value={(value("start_at") as string | null) ?? ""}
                  onChange={(e) => edit({ start: "at", start_at: e.target.value })}
                />
              </div>
              <p className={ws.hint}>
                In the timezone below. Only used when the monitor is created — Yutori can&apos;t move
                a live monitor&apos;s start, so changing it later means replacing the monitor.
              </p>
              {override("start")}
            </div>
          </div>
        )}

        <div className={styles.group}>
          <div className={styles.groupName}>
            <span className={styles.groupTitle}>Where you are</span>
            <span className={styles.api}>user_timezone · user_location</span>
          </div>
          <div className={styles.groupBody}>
            <label className={ws.label} htmlFor={`tz-${scopeKey}`}>Timezone</label>
            <div className={styles.row}>
              <input
                id={`tz-${scopeKey}`}
                className={ws.input}
                list="timezones"
                placeholder={`Yutori's default (${yutoriDefaultTimezone})`}
                value={(value("user_timezone") as string | null) ?? ""}
                onChange={(e) => edit({ user_timezone: e.target.value || null })}
              />
              <datalist id="timezones">
                {TIMEZONES.map((zone) => (
                  <option key={zone} value={zone} />
                ))}
              </datalist>
              {browserZone && value("user_timezone") !== browserZone && (
                <button
                  type="button"
                  className={`${ws.secondary} ${ws.tiny}`}
                  onClick={() => edit({ user_timezone: browserZone })}
                >
                  Use mine ({browserZone})
                </button>
              )}
            </div>
            <p className={ws.hint}>
              Yutori reads &ldquo;recent questions&rdquo; in this timezone. Left blank, it assumes{" "}
              {yutoriDefaultTimezone}.
            </p>
            {override("user_timezone")}
            <label className={ws.label} htmlFor={`loc-${scopeKey}`}>Location</label>
            <input
              id={`loc-${scopeKey}`}
              className={ws.input}
              placeholder="City, Region, Country — blank uses Yutori's default"
              value={(value("user_location") as string | null) ?? ""}
              onChange={(e) => edit({ user_location: e.target.value || null })}
            />
            {override("user_location")}
          </div>
        </div>

        {scout && (
          <div className={styles.group}>
            <div className={styles.groupName}>
              <span className={styles.groupTitle}>Visibility</span>
              <span className={styles.api}>is_public</span>
            </div>
            <div className={styles.groupBody}>
              <div className={ws.seg}>
                <button
                  type="button"
                  className={`${ws.segItem} ${!value("is_public") ? ws.on : ""}`}
                  onClick={() => edit({ is_public: false })}
                >
                  Private
                </button>
                <button
                  type="button"
                  className={`${ws.segItem} ${value("is_public") ? ws.on : ""}`}
                  onClick={() => !value("is_public") && setAsking("public")}
                >
                  Public
                </button>
              </div>
              <p className={ws.hint}>
                {value("is_public")
                  ? "Anyone with this monitor's id can read its reports — and they include your interests."
                  : "Only your API key can read this monitor's reports."}
              </p>
              {override("is_public")}
            </div>
          </div>
        )}

        <div className={styles.group}>
          <div className={styles.groupName}>
            <span className={styles.groupTitle}>Email from Yutori</span>
            <span className={styles.api}>skip_email{scout ? " · email-settings" : ""}</span>
          </div>
          <div className={styles.groupBody}>
            <label className={styles.check}>
              <input
                type="checkbox"
                checked={Boolean(value("email_from_yutori"))}
                onChange={(e) => edit({ email_from_yutori: e.target.checked })}
              />
              Also email me from Yutori
            </label>
            <p className={ws.hint}>
              Off by default: this app already sends its own digest, so Yutori&apos;s email would be a
              duplicate.
            </p>
            {override("email_from_yutori")}
            {scout && (
              <>
                <span className={ws.label}>Subscribers</span>
                <div className={styles.chips}>
                  {subscribers.length === 0 && <span className={ws.hint}>No subscribers.</span>}
                  {subscribers.map((email) => (
                    <span key={email} className={styles.chip}>
                      {email}
                      <button
                        type="button"
                        aria-label={`Remove ${email}`}
                        onClick={() => edit({ subscribers: subscribers.filter((s) => s !== email) })}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
                {/* A form so the browser handles Enter and validates the address. */}
                <form
                  className={styles.row}
                  onSubmit={(e) => {
                    e.preventDefault();
                    const email = newSubscriber.trim().toLowerCase();
                    if (!subscribers.includes(email)) edit({ subscribers: [...subscribers, email] });
                    setNewSubscriber("");
                  }}
                >
                  <input
                    id={`sub-${scopeKey}`}
                    className={ws.input}
                    type="email"
                    required
                    aria-label="Add a subscriber"
                    placeholder="name@example.com"
                    value={newSubscriber}
                    onChange={(e) => setNewSubscriber(e.target.value)}
                  />
                  <button type="submit" className={`${ws.secondary} ${ws.tiny}`}>
                    Add
                  </button>
                </form>
                <p className={ws.hint}>Added when the monitor is created.</p>
                {override("subscribers")}
              </>
            )}
          </div>
        </div>

        <div className={styles.group}>
          <div className={styles.groupName}>
            <span className={styles.groupTitle}>Output format</span>
            <span className={styles.api}>output_schema (was task_spec)</span>
          </div>
          <div className={styles.groupBody}>
            <div className={styles.row} style={{ justifyContent: "space-between" }}>
              <div className={ws.seg}>
                <button
                  type="button"
                  className={`${ws.segItem} ${schemaMode === "fields" ? ws.on : ""}`}
                  onClick={() => {
                    setSchemaMode("fields");
                    setRawSchema(null);
                  }}
                >
                  Fields
                </button>
                <button
                  type="button"
                  className={`${ws.segItem} ${schemaMode === "raw" ? ws.on : ""}`}
                  onClick={() => {
                    setSchemaMode("raw");
                    setRawSchema(JSON.stringify(schema, null, 2));
                  }}
                >
                  Raw JSON
                </button>
              </div>
              {override("output_schema")}
            </div>
            {schemaMode === "fields" ? (
              <>
                <p className={ws.hint}>
                  What Yutori should report for each question it finds. <code>url</code> is always
                  required — it&apos;s how a result becomes a question.
                </p>
                <div className={styles.fields}>
                  {allFields.map((field) => (
                    <label key={field} className={styles.check}>
                      <input
                        type="checkbox"
                        disabled={field === "url"}
                        checked={field === "url" || chosenFields.includes(field)}
                        onChange={(e) => {
                          const keep = e.target.checked
                            ? [...chosenFields, field]
                            : chosenFields.filter((f) => f !== field);
                          edit({ output_schema: schemaWith(defaultSchema, keep) });
                        }}
                      />
                      {field}
                    </label>
                  ))}
                </div>
              </>
            ) : (
              <textarea
                id={`schema-${scopeKey}`}
                className={ws.textarea}
                style={{ fontFamily: "var(--font-geist-mono), monospace", fontSize: 12.5, minHeight: 260 }}
                spellCheck={false}
                aria-label="Output schema JSON"
                value={rawSchema ?? ""}
                onChange={(e) => {
                  setRawSchema(e.target.value);
                  try {
                    edit({ output_schema: JSON.parse(e.target.value) });
                    setLocalError(null);
                  } catch (error) {
                    setLocalError(`Not valid JSON yet: ${(error as Error).message}`);
                  }
                }}
              />
            )}
          </div>
        </div>

        <div className={styles.group}>
          <div className={styles.groupName}>
            <span className={styles.groupTitle}>Delivery</span>
            <span className={styles.api}>webhook_url · webhook_format</span>
          </div>
          <div className={styles.groupBody}>
            <div className={styles.locked}>
              🔒 {String(shown?.webhook_url ?? "This app's webhook")} · format: scout
            </div>
            <p className={ws.hint}>
              Can&apos;t be changed. Results have to come back to this app to become questions, and
              Yutori delivers to only one webhook.
            </p>
          </div>
        </div>

        <div className={styles.footer}>
          <span className={`${ws.hint} ${localError || serverError ? styles.error : ""}`}>
            {localError ?? serverError ?? (dirty ? "Unsaved changes" : "Saved · used on the next run")}
          </span>
          <button type="button" className={`${ws.secondary} ${ws.tiny}`} onClick={() => setAsking("reset")}>
            Reset to {variant === "scout" ? "defaults" : "built-in"}
          </button>
          <button
            type="button"
            className={ws.secondary}
            disabled={!dirty}
            onClick={() => {
              setDraft(null);
              setRawSchema(null);
              setSchemaMode("fields");
              setLocalError(null);
            }}
          >
            Discard
          </button>
          <button
            type="button"
            className={ws.primary}
            disabled={!dirty || saving || Boolean(localError) || Boolean(serverError) || interval < 1800}
            onClick={save}
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <InfoButton text="Saves these settings. Nothing is sent to Yutori and nothing is billed — they're used the next time this runs." />
        </div>
      </div>

      <aside className={styles.side}>
        {previewFor && (
          <div className={ws.card}>
            <div className={ws.cardTitle}>What gets sent to Yutori</div>
            <p className={ws.hint}>
              {scout ? (
                <>
                  <code>POST /v1/scouting/tasks</code> when a monitor is started.
                </>
              ) : (
                <>
                  <code>POST /v1/research/tasks</code> each time you press Run.
                </>
              )}{" "}
              The webhook secret is hidden.
            </p>
            <pre className={styles.payload}>
              {dirty && livePreview.isFetching && !livePreview.data
                ? "Updating…"
                : shown
                  ? JSON.stringify(shown, null, 2)
                  : serverError
                    ? "Fix the settings to see the request."
                    : "—"}
            </pre>
          </div>
        )}
        <div className={ws.card}>
          <div className={ws.cardTitle}>Cost</div>
          {scout ? (
            <div className={`${styles.cost} ${interval < 86400 ? styles.hot : ""}`}>
              <strong>≈ {money(monthly)} a month</strong>
              <span className={ws.hint}>
                while the monitor runs {every(interval)}, until you stop it
              </span>
            </div>
          ) : (
            <div className={styles.cost}>
              <strong>{money(runCost)}</strong>
              <span className={ws.hint}>per run, charged when you press Run. Nothing recurs.</span>
            </div>
          )}
        </div>
      </aside>

      <ConfirmDialog
        open={asking === "public"}
        title="Make this monitor public?"
        body={
          <p>
            Anyone who has this monitor&apos;s id will be able to read its reports without an API
            key. The query includes your topics and interests.
          </p>
        }
        confirmLabel="Make public"
        onCancel={() => setAsking(null)}
        onConfirm={() => {
          setAsking(null);
          edit({ is_public: true });
        }}
      />
      <ConfirmDialog
        open={asking === "often"}
        title="Run this often?"
        body={
          <p>
            {every(interval)[0].toUpperCase() + every(interval).slice(1)} is about{" "}
            {Math.round((30 * 86400) / interval).toLocaleString()} runs a month — roughly{" "}
            <strong>{money(monthly)}</strong>, billed automatically while the monitor runs.
          </p>
        }
        confirmLabel="Save anyway"
        busy={saving}
        onCancel={() => setAsking(null)}
        onConfirm={() => {
          setAsking(null);
          onSave(values);
          setDraft(null);
        }}
      />
      <ConfirmDialog
        open={asking === "reset"}
        title={variant === "scout" ? "Reset this scout to the defaults?" : "Reset to the built-in settings?"}
        body={
          <p>
            {variant === "scout"
              ? "Drops every setting changed here, so this scout follows the app-wide defaults again."
              : "Drops every default you changed, back to how the app behaves out of the box."}
          </p>
        }
        confirmLabel="Reset"
        busy={saving}
        onCancel={() => setAsking(null)}
        onConfirm={() => {
          setAsking(null);
          setDraft(null);
          setRawSchema(null);
          setSchemaMode("fields");
          onResetAll();
        }}
      />
    </div>
  );
}
