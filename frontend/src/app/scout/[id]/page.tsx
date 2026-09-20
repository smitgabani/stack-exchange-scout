"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ConfirmDialog } from "../../confirm-dialog";
import { type Definition, duration, money, scoutApi, when } from "@/lib/scout-api";
import styles from "../../workspace.module.css";

type Tab = "query" | "runs" | "settings";

export default function DefinitionPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("query");
  const [message, setMessage] = useState<string | null>(null);
  const [asking, setAsking] = useState<"run" | "delete" | null>(null);
  const [mode, setMode] = useState<"research" | "scout">("research");
  const [draft, setDraft] = useState<Partial<Definition> | null>(null);

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
    mutationFn: () => scoutApi.runDefinition(params.id, mode),
    onSuccess: async (r) => {
      setMessage(`Started ${r.kind === "research_task" ? "research task" : "scout"} ${r.external_id}.`);
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const remove = useMutation({
    mutationFn: () => scoutApi.deleteDefinition(params.id),
    onSuccess: (r) => {
      setMessage(`Deleted. ${r.kept.questions} questions and ${r.kept.runs} runs were kept.`);
      router.push("/scout");
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
  const drifted =
    data.query_source === "topics" && data.query_text && data.rendered_query !== data.query_text;

  return (
    <main className={styles.page}>
      <Link className={styles.back} href="/scout">← All scouts</Link>

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
          <button className={styles.primary} onClick={() => setAsking("run")}>
            Run · $0.35
          </button>
        </div>
      </div>

      {message && <div className={styles.notice}>{message}</div>}

      <div className={styles.seg}>
        {(["query", "runs", "settings"] as Tab[]).map((t) => (
          <button
            key={t}
            className={`${styles.segItem} ${tab === t ? styles.on : ""}`}
            onClick={() => setTab(t)}
          >
            {t === "query" ? "Query" : t === "runs" ? `Runs (${runs.length})` : "Settings"}
          </button>
        ))}
      </div>

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
            <div className={styles.empty}>No runs yet. Running this scout costs about $0.35.</div>
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
                      <td><Link className={styles.textButton} href={`/scout/runs/${r.id}`}>Open</Link></td>
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
          </div>
          <div className={styles.dangerZone}>
            <h2>Delete this scout</h2>
            <p>
              Removes the saved query. Its runs stay in the ledger and every question it found
              stays in your pool — that history is what stops the app rediscovering, and
              re-paying for, questions you have already seen.
            </p>
            <div className={styles.actions} style={{ marginTop: "14px" }}>
              <button className={styles.danger} onClick={() => setAsking("delete")}>Delete scout</button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={asking === "run"}
        title={`Run “${data.name}”?`}
        body={
          <>
            <p>This searches Stack Overflow now. It costs about <strong>$0.35</strong>.</p>
            <div className={styles.seg} style={{ marginTop: "14px" }}>
              <button
                type="button"
                className={`${styles.segItem} ${mode === "research" ? styles.on : ""}`}
                onClick={() => setMode("research")}
              >
                Research task — one-shot
              </button>
              <button
                type="button"
                className={`${styles.segItem} ${mode === "scout" ? styles.on : ""}`}
                onClick={() => setMode("scout")}
              >
                Scout — keeps monitoring
              </button>
            </div>
          </>
        }
        confirmLabel="Run now"
        busy={run.isPending}
        onCancel={() => setAsking(null)}
        onConfirm={() => { setAsking(null); run.mutate(); }}
      />

      <ConfirmDialog
        open={asking === "delete"}
        title={`Delete “${data.name}”?`}
        body={
          <p>
            The saved query goes. Its {runs.length} run{runs.length === 1 ? "" : "s"} and every
            question it found stay.
          </p>
        }
        confirmLabel="Delete"
        busy={remove.isPending}
        onCancel={() => setAsking(null)}
        onConfirm={() => { setAsking(null); remove.mutate(); }}
      />
    </main>
  );
}
