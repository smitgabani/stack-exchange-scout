"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ConfirmDialog } from "../../../confirm-dialog";
import { InfoButton } from "../../../info-button";
import { LiveMonitorDialog } from "../../../live-monitor-dialog";
import { ParametersForm } from "../../parameters-form";
import {
  type Definition,
  type LiveMonitorConflict,
  type YutoriSettings,
  MODE_LABEL,
  type RunMode,
  defaultMode,
  duration,
  every,
  liveMonitorConflict,
  money,
  monthlyCost,
  scoutApi,
  when,
} from "@/lib/scout-api";
import styles from "../../../workspace.module.css";

type Tab = "query" | "parameters" | "runs" | "settings";

export default function DefinitionPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("query");
  const [message, setMessage] = useState<string | null>(null);
  const [asking, setAsking] = useState<"run" | "delete" | null>(null);
  const [mode, setMode] = useState<RunMode | null>(null);
  const [draft, setDraft] = useState<Partial<Definition> | null>(null);
  const [conflict, setConflict] = useState<LiveMonitorConflict | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["definition", params.id],
    queryFn: () => scoutApi.getDefinition(params.id),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["definition", params.id] });
    await queryClient.invalidateQueries({ queryKey: ["definitions"] });
  };

  const save = useMutation({
    mutationFn: (body: Partial<Definition>) => scoutApi.patchDefinition(params.id, body),
    onSuccess: async () => {
      setMessage("Saved. Nothing was sent to Yutori — editing is free.");
      setDraft(null);
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const run = useMutation({
    mutationFn: (replace: boolean = false) =>
      scoutApi.runDefinition(params.id, runMode, { replace }),
    onSuccess: async (r, replace) => {
      setConflict(null);
      setMessage(
        r.kind === "research_task"
          ? `Started research task ${r.external_id}.`
          : replace
            ? `Monitor replaced: the old one was stopped and ${r.external_id} is running now.`
            : `Monitor ${r.external_id} started. It keeps running on its interval until you stop it on Monitors.`,
      );
      await refresh();
      await queryClient.invalidateQueries({ queryKey: ["monitors"] });
    },
    onError: (e: Error) => {
      const detail = liveMonitorConflict(e);
      if (detail) setConflict(detail);
      else setMessage(e.message);
    },
  });

  const remove = useMutation({
    mutationFn: () => scoutApi.deleteDefinition(params.id),
    onSuccess: (r) => {
      setMessage(`Deleted. ${r.kept.questions} questions and ${r.kept.runs} runs were kept.`);
      router.push("/yutori/scouts");
    },
    onError: (e: Error) => setMessage(e.message),
  });

  if (isLoading || !data) return <main className={styles.page}>Loading…</main>;

  const value = <K extends keyof Definition>(key: K): Definition[K] =>
    (draft?.[key] ?? data[key]) as Definition[K];
  const edit = (patch: Partial<Definition>) => setDraft({ ...(draft ?? {}), ...patch });
  const dirty = draft !== null;
  const runs = data.runs ?? [];
  const spend = runs.reduce((s, r) => s + (r.cost_usd ?? 0), 0);
  const questions = runs.reduce((s, r) => s + (r.questions ?? 0), 0);
  // The definition's own setting, unless the run dialog has overridden it.
  const currentMode: RunMode = defaultMode(
    (draft?.config ?? data.config) as Record<string, unknown> | null,
  );
  const runMode: RunMode = mode ?? currentMode;
  const drifted =
    data.query_source === "topics" && data.query_text && data.rendered_query !== data.query_text;
  const cost = data.run_cost_usd ?? 0.35;
  const monitorInterval = data.monitor_interval_seconds ?? 30 * 86400;

  return (
    <main className={styles.page}>
      <Link className={styles.back} href="/yutori/scouts">← All scouts</Link>

      <div className={styles.head}>
        <div>
          <div className={styles.title}>{data.name}</div>
          <div className={styles.sub}>
            {runs.length
              ? `${runs.length} run${runs.length === 1 ? "" : "s"} · ${money(spend)} spent · ${questions} questions found`
              : "Never run. It has cost nothing so far."}
          </div>
        </div>
        <div className={styles.actions}>
          {dirty && (
            <button className={styles.secondary} onClick={() => setDraft(null)}>Discard</button>
          )}
          <button
            className={dirty ? styles.primary : styles.secondary}
            onClick={() => save.mutate(draft ?? {})}
            disabled={!dirty || save.isPending}
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
          <InfoButton text="Writes your edits to this saved query. Nothing is sent to Yutori and nothing is billed — editing is always free." />
          <button className={styles.primary} onClick={() => setAsking("run")}>
            {runMode === "scout" ? "Start monitor" : "Run"} · {money(cost)}
          </button>
          <InfoButton text={`Asks Yutori to search Stack Overflow now, using this scout's query. Costs about ${money(cost)}. Choose Scout monitor if you want it to keep running on its own interval afterward — that mode keeps billing until you stop it.`} />
        </div>
      </div>

      {message && <div className={styles.notice}>{message}</div>}

      {/* How it runs decides which Parameters form applies, so it sits above
          the tabs rather than inside one. Saved with the page's Save. */}
      <div className={styles.field}>
        <span className={styles.label}>How it runs</span>
        <div className={styles.seg}>
          {(["research", "scout"] as RunMode[]).map((m) => (
            <button
              key={m}
              type="button"
              className={`${styles.segItem} ${currentMode === m ? styles.on : ""}`}
              // Only the key being changed: the backend merges config, so the
              // Yutori settings saved from the Parameters tab are left alone.
              onClick={() => edit({ config: { default_mode: m } })}
            >
              {MODE_LABEL[m]}
            </button>
          ))}
        </div>
        <p className={styles.hint}>
          {currentMode === "research"
            ? "One-shot. Runs when you ask and leaves nothing behind at Yutori."
            : "Creates a monitor that keeps running on its own interval — the only kind that bills without you pressing anything."}
        </p>
      </div>

      <div className={styles.seg}>
        {(["query", "parameters", "runs", "settings"] as Tab[]).map((t) => (
          <button
            key={t}
            className={`${styles.segItem} ${tab === t ? styles.on : ""}`}
            onClick={() => setTab(t)}
          >
            {t === "query"
              ? "Query"
              : t === "parameters"
                ? "Parameters"
                : t === "runs"
                  ? `Runs (${runs.length})`
                  : "Settings"}
          </button>
        ))}
      </div>

      {tab === "parameters" && (
        <ScoutParameters definitionId={params.id} mode={currentMode} onSaved={refresh} />
      )}

      {tab === "query" && (
        <div className={styles.grid2}>
          <div className={styles.card}>
            <div className={styles.cardTitle}>Build the query</div>
            <div className={styles.seg}>
              <button
                className={`${styles.segItem} ${value("query_source") === "topics" ? styles.on : ""}`}
                onClick={() => edit({ query_source: "topics" })}
              >
                From my topics
              </button>
              <button
                className={`${styles.segItem} ${value("query_source") === "freeform" ? styles.on : ""}`}
                onClick={() => edit({ query_source: "freeform" })}
              >
                Write it myself
              </button>
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="def-name">Name</label>
              <input
                id="def-name"
                className={styles.input}
                value={value("name") ?? ""}
                onChange={(e) => edit({ name: e.target.value })}
              />
            </div>
            {value("query_source") === "freeform" ? (
              <div className={styles.field}>
                <label className={styles.label} htmlFor="def-query">Query</label>
                <textarea
                  id="def-query"
                  className={styles.textarea}
                  value={value("query_text") ?? ""}
                  onChange={(e) => edit({ query_text: e.target.value })}
                  placeholder="Describe what the Scout should look for…"
                />
              </div>
            ) : (
              <p className={styles.hint}>
                Built from your topics and weights on the{" "}
                <Link className={styles.textButton} href="/topics">Topics page</Link>, and rebuilt
                every time it runs — so changing topics updates it without editing anything here.
              </p>
            )}
            <div className={styles.field}>
              <label className={styles.label} htmlFor="def-notes">Notes to yourself</label>
              <textarea
                id="def-notes"
                className={styles.textarea}
                style={{ minHeight: "80px" }}
                value={value("notes") ?? ""}
                onChange={(e) => edit({ notes: e.target.value })}
                placeholder="What is this scout for? What did you learn from its results?"
              />
            </div>
          </div>

          <div className={styles.card}>
            <div className={styles.cardTitle}>What gets sent to Yutori</div>
            <p className={styles.hint}>
              Exactly this text, verbatim. The first thing to check when results look wrong.
            </p>
            <pre className={styles.query}>
              {value("query_source") === "freeform"
                ? value("query_text") || "Nothing yet — write a query on the left."
                : data.rendered_query || "No topics set yet."}
            </pre>
            {drifted && value("query_source") === "topics" && (
              <div className={styles.alert}>
                <strong>Your topics have changed since this last ran.</strong> The next run will use
                the query above, not the one the previous results came from.
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "runs" && (
        <div className={styles.section}>
          {runs.length === 0 ? (
            <div className={styles.empty}>No runs yet. Running this scout costs about {money(cost)}.</div>
          ) : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Started</th><th>Kind</th><th>Status</th><th>Took</th><th>Cost</th>
                    <th>Questions</th><th>Candidates</th><th>Above bar</th><th>Delivered by</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.id}>
                      <td>{when(r.started_at)}</td>
                      <td>{r.kind === "research_task" ? "Research" : "Scout"}</td>
                      <td className={r.status === "succeeded" ? styles.ok : r.status === "running" ? "" : styles.bad}>
                        {r.status}
                      </td>
                      <td className={styles.num}>{duration(r.duration_seconds)}</td>
                      <td className={styles.num}>{money(r.cost_usd)}</td>
                      <td className={styles.num}>{r.questions ?? 0}</td>
                      <td className={styles.num}>{r.candidates ?? 0}</td>
                      <td className={styles.num}>{r.above_bar ?? 0}</td>
                      <td>{r.delivered_by ?? "—"}</td>
                      <td><Link className={styles.textButton} href={`/yutori/runs/${r.id}`}>Open</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "settings" && (
        <div className={styles.section}>
          <dl className={styles.dl}>
            <div><dt>Status</dt><dd>{data.status}</dd></div>
            <div><dt>Query source</dt><dd>{data.query_source}</dd></div>
            <div><dt>Created</dt><dd>{when(data.created_at)}</dd></div>
            <div><dt>Last edited</dt><dd>{when(data.updated_at)}</dd></div>
          </dl>
          <div className={styles.actions}>
            <button
              className={styles.secondary}
              onClick={() => save.mutate({ status: data.status === "archived" ? "ready" : "archived" })}
            >
              {data.status === "archived" ? "Restore from archive" : "Archive"}
            </button>
            <InfoButton
              text={
                data.status === "archived"
                  ? "Makes this scout runnable again and shows it in the default scouts list."
                  : "Hides this scout from the default scouts list and blocks running it, without deleting it or any of its history. Restore it anytime."
              }
            />
          </div>
          <div className={styles.dangerZone}>
            <h2>Delete this scout</h2>
            <p>
              Removes the saved query <strong>from this app only</strong>. It does not delete
              anything at Yutori — a Scout monitor created from it keeps running, and keeps
              billing, until it is deleted on the{" "}
              <Link className={styles.textButton} href="/yutori/monitors">Monitors page</Link>.
            </p>
            <p>
              Its runs stay in the ledger and every question it found stays in your pool — that
              history is what stops the app rediscovering, and re-paying for, questions you have
              already seen.
            </p>
            <div className={styles.actions} style={{ marginTop: "14px" }}>
              <button className={styles.danger} onClick={() => setAsking("delete")}>Delete scout</button>
              <InfoButton text="Removes this saved query from the app only. It does not delete anything at Yutori — a Scout monitor created from it keeps running and billing until deleted on the Monitors page. Its run history and every question it found are kept." />
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={asking === "run"}
        title={`Run “${data.name}”?`}
        body={
          <>
            <p>This searches Stack Overflow now. It costs about <strong>{money(cost)}</strong>.</p>
            <div className={styles.seg} style={{ marginTop: "14px" }}>
              <button
                type="button"
                className={`${styles.segItem} ${runMode === "research" ? styles.on : ""}`}
                onClick={() => setMode("research")}
              >
                Research task — one-shot
              </button>
              <button
                type="button"
                className={`${styles.segItem} ${runMode === "scout" ? styles.on : ""}`}
                onClick={() => setMode("scout")}
              >
                Scout — keeps monitoring
              </button>
            </div>
            {runMode === "scout" && (
              <p className={styles.hint} style={{ marginTop: "10px" }}>
                Creates a monitor that runs now, then again {every(monitorInterval)} on its own
                until you stop it — about {money(monthlyCost(monitorInterval, cost))} a month.
              </p>
            )}
          </>
        }
        confirmLabel={runMode === "scout" ? "Start monitor" : "Run now"}
        busy={run.isPending}
        onCancel={() => setAsking(null)}
        onConfirm={() => { setAsking(null); run.mutate(false); }}
      />

      <LiveMonitorDialog
        conflict={conflict}
        scoutName={data.name}
        busy={run.isPending}
        onKeep={() => setConflict(null)}
        onReplace={() => run.mutate(true)}
      />

      <ConfirmDialog
        open={asking === "delete"}
        title={`Delete “${data.name}”?`}
        body={
          <>
            <p>
              The saved query goes. Its {runs.length} run{runs.length === 1 ? "" : "s"} and every
              question it found stay.
            </p>
            <p className={styles.hint} style={{ marginTop: "10px" }}>
              Nothing is deleted at Yutori.
            </p>
          </>
        }
        confirmLabel="Delete"
        busy={remove.isPending}
        onCancel={() => setAsking(null)}
        onConfirm={() => { setAsking(null); remove.mutate(); }}
      />
    </main>
  );
}

/**
 * The Parameters tab: this scout's Yutori settings, with a free preview of
 * the exact request. Loads its own data so the rest of the page doesn't wait.
 */
function ScoutParameters({
  definitionId,
  mode,
  onSaved,
}: {
  definitionId: string;
  mode: RunMode;
  onSaved: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const { data, isLoading, error } = useQuery({
    queryKey: ["definition-settings", definitionId],
    queryFn: () => scoutApi.getSettings(definitionId),
  });

  const after = async (text: string) => {
    setMessage(text);
    await queryClient.invalidateQueries({ queryKey: ["definition-settings", definitionId] });
    await onSaved();
  };
  const save = useMutation({
    mutationFn: (values: YutoriSettings) => scoutApi.putSettings(definitionId, values),
    onSuccess: () => after("Saved. Nothing was sent to Yutori — the next run uses these settings."),
    onError: (e: Error) => setMessage(e.message),
  });
  const reset = useMutation({
    mutationFn: () => scoutApi.resetSettings(definitionId),
    onSuccess: () => after("Back to the defaults."),
    onError: (e: Error) => setMessage(e.message),
  });

  if (isLoading) return <div className={styles.empty}>Loading settings…</div>;
  if (error || !data) return <div className={styles.alert}>{(error as Error)?.message ?? "Couldn't load settings."}</div>;

  return (
    <>
      {message && <div className={styles.notice}>{message}</div>}
      <ParametersForm
        variant="scout"
        mode={mode}
        base={data.defaults}
        saved={data.overrides}
        defaultSchema={data.default_output_schema}
        yutoriDefaultTimezone={data.yutori_default_timezone}
        runCost={data.run_cost_usd}
        initialPreview={data.preview}
        previewFor={(draft) => scoutApi.previewSettings(definitionId, draft)}
        scopeKey={definitionId}
        saving={save.isPending || reset.isPending}
        onSave={(values) => save.mutate(values)}
        onResetAll={() => reset.mutate()}
      />
    </>
  );
}
