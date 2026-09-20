"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { ConfirmDialog } from "../confirm-dialog";
import {
  type Definition,
  MODE_LABEL,
  type RunMode,
  defaultMode,
  money,
  scoutApi,
  when,
} from "@/lib/scout-api";
import styles from "../workspace.module.css";

function statusPill(status: Definition["status"]) {
  if (status === "ready") return <span className={`${styles.pill} ${styles.pillReady}`}>Ready</span>;
  if (status === "draft") return <span className={`${styles.pill} ${styles.pillDraft}`}>Draft</span>;
  return <span className={styles.pill}>Archived</span>;
}

export default function ScoutsPage() {
  const queryClient = useQueryClient();
  const [showArchived, setShowArchived] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [runTarget, setRunTarget] = useState<Definition | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Definition | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newMode, setNewMode] = useState<RunMode>("research");
  const [renameTarget, setRenameTarget] = useState<Definition | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [mode, setMode] = useState<"research" | "scout">("research");

  const { data, isLoading } = useQuery({
    queryKey: ["definitions", showArchived],
    queryFn: () => scoutApi.listDefinitions(showArchived),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["definitions"] });

  const create = useMutation({
    mutationFn: () =>
      scoutApi.createDefinition({
        name: newName.trim() || "Untitled scout",
        query_source: "topics",
        config: { default_mode: newMode },
      }),
    onSuccess: async (made) => {
      setMessage(`Created “${made.name}”. It has not run, so it has cost nothing.`);
      setCreating(false);
      setNewName("");
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      scoutApi.patchDefinition(id, { name }),
    onSuccess: async (updated) => {
      setMessage(`Renamed to “${updated.name}”.`);
      setRenameTarget(null);
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const clone = useMutation({
    mutationFn: (id: string) => scoutApi.cloneDefinition(id),
    onSuccess: async (made) => {
      setMessage(`Copied to “${made.name}” — the copy starts with no runs and no spend.`);
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => scoutApi.deleteDefinition(id),
    onSuccess: async (result) => {
      setMessage(
        `Deleted. ${result.kept.questions} question${result.kept.questions === 1 ? "" : "s"} and ` +
          `${result.kept.runs} run${result.kept.runs === 1 ? "" : "s"} were kept — deleting a saved ` +
          `query never removes what it found.`,
      );
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const run = useMutation({
    mutationFn: ({ id, mode }: { id: string; mode: "research" | "scout" }) =>
      scoutApi.runDefinition(id, mode),
    onSuccess: async (result) => {
      setMessage(
        result.kind === "research_task"
          ? `Research task started (${result.external_id}). Results are polled, so a missed webhook cannot lose it.`
          : `Scout created (${result.external_id}). It will run on its interval until retired.`,
      );
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const definitions = data?.definitions ?? [];
  const cost = data?.run_cost_usd ?? 0.35;
  const totalSpend = definitions.reduce((sum, d) => sum + (d.stats?.spend_usd ?? 0), 0);
  const totalRuns = definitions.reduce((sum, d) => sum + (d.stats?.runs ?? 0), 0);
  const totalQuestions = definitions.reduce((sum, d) => sum + (d.stats?.questions ?? 0), 0);
  const best = definitions
    .map((d) => ({ d, per: d.stats?.spend_usd ? (d.stats.questions ?? 0) / d.stats.spend_usd : null }))
    .filter((r) => r.per !== null)
    .sort((a, b) => (b.per ?? 0) - (a.per ?? 0))[0];

  if (isLoading) return <main className={styles.page}>Loading…</main>;

  return (
    <main className={styles.page}>
      <div className={styles.head}>
        <div>
          <div className={styles.title}>Scouts</div>
          <div className={styles.sub}>
            Saved searches. Creating and editing them is free — only running one costs money.
          </div>
        </div>
        <div className={styles.actions}>
          <Link className={styles.secondary} href="/scout/monitors">Monitors</Link>
          <button className={styles.primary} onClick={() => setCreating(true)}>
            New scout
          </button>
        </div>
      </div>

      {message && <div className={styles.notice}>{message}</div>}

      <div className={styles.stats}>
        <div className={styles.stat}>
          <div className={styles.statKey}>Spend, all time</div>
          <div className={styles.statValue}>{money(totalSpend)}</div>
          <div className={styles.statMeta}>{totalRuns} run{totalRuns === 1 ? "" : "s"} · {money(cost)} each</div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statKey}>Questions found</div>
          <div className={styles.statValue}>{totalQuestions}</div>
          <div className={styles.statMeta}>across every run</div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statKey}>Best yield</div>
          <div className={styles.statValue}>{best?.per ? best.per.toFixed(1) : "—"}</div>
          <div className={styles.statMeta}>{best ? `per $ · ${best.d.name}` : "no runs yet"}</div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statKey}>Saved scouts</div>
          <div className={styles.statValue}>{definitions.length}</div>
          <div className={styles.statMeta}>free to keep</div>
        </div>
      </div>

      <div className={styles.sectionHead}>
        <h2 className={styles.sectionTitle}>Your scouts</h2>
        <button className={styles.textButton} onClick={() => setShowArchived((v) => !v)}>
          {showArchived ? "Hide archived" : "Show archived"}
        </button>
      </div>

      {definitions.length === 0 ? (
        <div className={styles.empty}>
          No scouts yet. Create one — it costs nothing until you run it.
        </div>
      ) : (
        <div className={styles.list}>
          {definitions.map((definition) => {
            const stats = definition.stats;
            const per = stats?.spend_usd ? (stats.questions ?? 0) / stats.spend_usd : null;
            const drifted =
              definition.query_source === "topics" &&
              definition.query_text !== null &&
              definition.rendered_query !== null &&
              definition.query_text !== definition.rendered_query;
            return (
              <div
                key={definition.id}
                className={`${styles.item} ${definition.status === "draft" ? styles.itemDraft : ""} ${
                  definition.status === "archived" ? styles.itemArchived : ""
                }`}
              >
                <div>
                  <div className={styles.itemName}>
                    <Link href={`/scout/${definition.id}`}>{definition.name}</Link>
                    {statusPill(definition.status)}
                    <span className={styles.pill}>
                      {definition.query_source === "topics" ? "Topics" : "Freeform"}
                    </span>
                    {/* Which mechanism this scout runs as. They cost the same
                        but behave very differently: a monitor keeps billing. */}
                    <span
                      className={`${styles.pill} ${
                        defaultMode(definition.config) === "scout" ? styles.pillLive : ""
                      }`}
                    >
                      {MODE_LABEL[defaultMode(definition.config)]}
                    </span>
                    {/* Worth saying before a run, not after: the query on file
                        is not what the current topics would send. */}
                    {drifted && <span className={`${styles.pill} ${styles.pillBad}`}>Topics changed</span>}
                  </div>
                  <div className={styles.itemMeta}>
                    {stats?.runs
                      ? `Last run ${when(stats.last_run)} as a ${
                          stats.last_kind === "scout" ? "Scout monitor" : "research task"
                        } · ${stats.runs} run${stats.runs === 1 ? "" : "s"} · ${money(
                          stats.spend_usd,
                        )} · ${stats.questions} questions`
                      : "Never run · costs nothing so far"}
                  </div>
                  <div className={styles.itemQuery}>
                    {definition.rendered_query || definition.query_text || "No query yet"}
                  </div>
                </div>
                <div className={styles.itemSide}>
                  <div className={styles.yield}>
                    {per !== null ? (
                      <><b>{per.toFixed(1)}</b> questions per $</>
                    ) : (
                      <span className={styles.hint}>no runs yet</span>
                    )}
                  </div>
                  <div className={styles.actions}>
                    <button
                      className={`${styles.secondary} ${styles.tiny}`}
                      onClick={() => { setRenameValue(definition.name); setRenameTarget(definition); }}
                    >
                      Rename
                    </button>
                    <button
                      className={`${styles.secondary} ${styles.tiny}`}
                      onClick={() => clone.mutate(definition.id)}
                      disabled={clone.isPending}
                    >
                      Clone
                    </button>
                    <Link className={`${styles.secondary} ${styles.tiny}`} href={`/scout/${definition.id}`}>
                      Edit
                    </Link>
                    <button
                      className={`${styles.danger} ${styles.tiny}`}
                      onClick={() => setDeleteTarget(definition)}
                      disabled={remove.isPending}
                    >
                      Delete
                    </button>
                    <button
                      className={`${styles.primary} ${styles.tiny}`}
                      onClick={() => { setMode(defaultMode(definition.config)); setRunTarget(definition); }}
                      disabled={run.isPending || definition.status === "archived"}
                    >
                      Run · {money(cost)}
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <ConfirmDialog
        open={creating}
        title="New scout"
        body={
          <>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="new-name">Name</label>
              <input
                id="new-name"
                className={styles.input}
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Rust concurrency bugs"
              />
            </div>
            <div className={styles.field} style={{ marginTop: "14px" }}>
              <span className={styles.label}>How it runs</span>
              <div className={styles.seg}>
                <button
                  type="button"
                  className={`${styles.segItem} ${newMode === "research" ? styles.on : ""}`}
                  onClick={() => setNewMode("research")}
                >
                  Research task
                </button>
                <button
                  type="button"
                  className={`${styles.segItem} ${newMode === "scout" ? styles.on : ""}`}
                  onClick={() => setNewMode("scout")}
                >
                  Scout monitor
                </button>
              </div>
            </div>
            <p className={styles.hint} style={{ marginTop: "10px" }}>
              {newMode === "research"
                ? "One-shot. Runs when you ask, leaves nothing behind at Yutori."
                : "Keeps running on its own interval until you delete it — the only kind that bills without you pressing anything."}
            </p>
            <p className={styles.hint} style={{ marginTop: "10px" }}>
              Creating costs nothing. You can change all of this later.
            </p>
          </>
        }
        confirmLabel="Create"
        busy={create.isPending}
        onCancel={() => setCreating(false)}
        onConfirm={() => create.mutate()}
      />

      <ConfirmDialog
        open={renameTarget !== null}
        title="Rename scout"
        body={
          <div className={styles.field}>
            <label className={styles.label} htmlFor="rename-name">Name</label>
            <input
              id="rename-name"
              className={styles.input}
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
            />
          </div>
        }
        confirmLabel="Rename"
        busy={rename.isPending}
        onCancel={() => setRenameTarget(null)}
        onConfirm={() => {
          if (renameTarget && renameValue.trim()) {
            rename.mutate({ id: renameTarget.id, name: renameValue.trim() });
          }
        }}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title={`Delete “${deleteTarget?.name ?? ""}”?`}
        body={
          <>
            <p>
              This removes the saved query from this app only. <strong>It does not delete
              anything at Yutori</strong> — any Scout monitor created from it keeps running, and
              keeps billing, until it is deleted on the Monitors page.
            </p>
            <p className={styles.hint} style={{ marginTop: "10px" }}>
              Its {deleteTarget?.stats?.runs ?? 0} run
              {deleteTarget?.stats?.runs === 1 ? "" : "s"} stay in the ledger, so the{" "}
              {money(deleteTarget?.stats?.spend_usd ?? 0)} already spent is still accounted for,
              and every question it found stays in your pool — that history is what stops the app
              rediscovering, and re-paying for, questions you have already seen.
            </p>
            {deleteTarget?.status !== "archived" && (
              <p className={styles.hint} style={{ marginTop: "10px" }}>
                If you only want it out of the way, archive it instead — that keeps the query.
              </p>
            )}
          </>
        }
        confirmLabel="Delete scout"
        busy={remove.isPending}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) remove.mutate(deleteTarget.id);
          setDeleteTarget(null);
        }}
      />

      <ConfirmDialog
        open={runTarget !== null}
        title={`Run “${runTarget?.name ?? ""}”?`}
        body={
          <>
            <p>
              This searches Stack Overflow now, using this scout&apos;s query. It costs about{" "}
              <strong>{money(cost)}</strong>.
            </p>
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
            <p className={styles.hint} style={{ marginTop: "10px" }}>
              {mode === "research"
                ? "Runs immediately and leaves nothing behind at Yutori."
                : "Creates a monitor that keeps running on its own interval until you retire it."}
            </p>
          </>
        }
        confirmLabel="Run now"
        busy={run.isPending}
        onCancel={() => setRunTarget(null)}
        onConfirm={() => {
          if (runTarget) run.mutate({ id: runTarget.id, mode });
          setRunTarget(null);
        }}
      />
    </main>
  );
}
