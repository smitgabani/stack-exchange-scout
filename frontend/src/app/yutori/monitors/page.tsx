"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import {
  type Instance,
  type Monitor,
  every,
  money,
  scoutApi,
  when as fmt,
} from "@/lib/scout-api";
import { ConfirmDialog } from "../../confirm-dialog";
import { InfoButton } from "../../info-button";
import { MonitorDetails } from "../live-monitor";
import ws from "../../workspace.module.css";
import styles from "../scout.module.css";

/**
 * The raw ownership/inventory view: what this app has created at Yutori
 * (`instances`, multi-account), and what actually exists there right now
 * under whichever key is active (`remote`).
 *
 * This page used to also carry a single Scout's live status — query,
 * config, updates, timeline, health — built entirely on the legacy `scouts`
 * table, whose own model docstring called it "the single active Yutori Scout
 * for the whole app." That assumption broke the moment a second account
 * existed: the page had no way to show, or even ask about, more than one
 * Scout. It was removed rather than patched, because everything it showed
 * already exists correctly per-account elsewhere — query and config on a
 * definition's own page (`/yutori/scouts/[id]`), updates and timeline on a
 * run's own page (`/yutori/runs/[runId]`) — both of which carry their own
 * `account_fingerprint`, which the legacy Panel never did.
 */
export default function ScoutPage() {
  const [deleteTarget, setDeleteTarget] = useState<Instance | null>(null);
  const [forgetTarget, setForgetTarget] = useState<Instance | null>(null);
  const [showRemote, setShowRemote] = useState(false);
  const [stopTarget, setStopTarget] = useState<{ externalId: string; label: string } | null>(null);
  const [confirmStopOlder, setConfirmStopOlder] = useState(false);
  const [stopMessage, setStopMessage] = useState<string | null>(null);
  const [restartTarget, setRestartTarget] = useState<Instance | null>(null);
  const queryClient = useQueryClient();

  const { data: instances } = useQuery({
    queryKey: ["instances"],
    queryFn: scoutApi.listInstances,
  });

  // Local and free: what this app believes is still running. Syncing runs
  // first records any scheduled runs whose updates arrived since last time.
  const { data: live } = useQuery({
    queryKey: ["monitors"],
    queryFn: async () => {
      await scoutApi.syncAllRuns().catch(() => undefined);
      return scoutApi.monitors();
    },
  });

  const refreshMonitors = async () => {
    await queryClient.invalidateQueries({ queryKey: ["monitors"] });
    await queryClient.invalidateQueries({ queryKey: ["instances"] });
    await queryClient.invalidateQueries({ queryKey: ["remote-inventory"] });
  };

  // Stopping is free and is what actually ends the billing: a monitor runs
  // on its own interval until Yutori is told it is done.
  const stopOne = useMutation({
    mutationFn: (externalId: string) => scoutApi.stopRemote(externalId),
    onSuccess: async (_, externalId) => {
      setStopMessage(`Stopped ${externalId}. It won't run or bill again.`);
      await refreshMonitors();
    },
    onError: (e: Error) => setStopMessage(e.message),
  });

  // Brings a stopped monitor back on its schedule. It doesn't run now, and it
  // bills again every interval — so it asks first.
  const restart = useMutation({
    mutationFn: (id: string) => scoutApi.restartMonitor(id),
    onSuccess: async () => {
      setStopMessage("Restarted. It runs again at its next interval — not now.");
      await refreshMonitors();
    },
    onError: (e: Error) => setStopMessage(e.message),
  });

  const stopOlder = useMutation({
    mutationFn: scoutApi.stopSuperseded,
    onSuccess: async (result) => {
      setStopMessage(
        result.failed.length
          ? `Stopped ${result.stopped.length}. ${result.failed.length} could not be stopped: ${result.failed
              .map((f) => `${f.external_id} (${f.error})`)
              .join("; ")}`
          : `Stopped ${result.stopped.length} older monitor${result.stopped.length === 1 ? "" : "s"}.`,
      );
      await refreshMonitors();
    },
    onError: (e: Error) => setStopMessage(e.message),
  });

  // Only fetched when asked for: two calls out to Yutori, and the page has to
  // render fine without them.
  const { data: remote, isFetching: remoteLoading } = useQuery({
    queryKey: ["remote-inventory"],
    queryFn: scoutApi.remoteInventory,
    enabled: showRemote,
  });

  // The only action in the app that stops something billing: a live Scout runs
  // on its own interval until it is deleted.
  const removeInstance = useMutation({
    mutationFn: (id: string) => scoutApi.deleteInstance(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["instances"] });
    },
  });

  // The escape hatch delete cannot be: an instance under a different
  // account's key. Yutori refuses to delete it from here (403), so without
  // this it would sit in the list forever with no way off it.
  const forgetInstance = useMutation({
    mutationFn: (id: string) => scoutApi.forgetInstance(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["instances"] });
    },
  });

  return (
    <main className={styles.page}>
      <div className={styles.header}>
        <div>
          <div className={styles.pageTitle}>Monitors</div>
          <div className={styles.pageSub}>
            What this app has created at Yutori, across every account you&apos;ve used, and what
            actually exists there right now. For a scout&apos;s own query and configuration, see
            its page under Scouts; for a run&apos;s timeline and yield, see it under Runs.
          </div>
        </div>
      </div>

      {stopMessage && <div className={styles.notice}>{stopMessage}</div>}

      <LiveMonitors
        data={live}
        busy={stopOne.isPending || stopOlder.isPending}
        onStop={(m) =>
          setStopTarget({ externalId: m.external_id, label: m.definition_name ?? m.external_id })
        }
        onStopOlder={() => setConfirmStopOlder(true)}
      />

      {removeInstance.isError && (
        <div className={styles.alert}>{(removeInstance.error as Error).message}</div>
      )}
      {forgetInstance.isError && (
        <div className={styles.alert}>{(forgetInstance.error as Error).message}</div>
      )}

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Remote objects</h2>
        <div className={styles.pageSub}>
          What this app has created at Yutori. A Scout keeps running on its interval until it is
          deleted; a research task is already over and leaves nothing behind.
        </div>
        {!instances?.instances.length ? (
          <div className={styles.empty}>Nothing exists at Yutori from this app.</div>
        ) : (
          (() => {
            // Grouped by owning account, the active one first. Which account
            // owns a Scout decides whether anything on this page can touch it,
            // so it is the grouping rather than a column to squint at.
            const groups = new Map<string, typeof instances.instances>();
            for (const instance of instances.instances) {
              const key = instance.account_label ?? (instance.account_fingerprint ?? "unknown");
              groups.set(key, [...(groups.get(key) ?? []), instance]);
            }
            const ordered = [...groups.entries()].sort((a, b) => {
              const aMine = a[1].some((i) => i.usable === true) ? 0 : 1;
              const bMine = b[1].some((i) => i.usable === true) ? 0 : 1;
              return aMine - bMine;
            });

            return ordered.map(([account, rows]) => {
              const mine = rows.some((i) => i.usable === true);
              const unknown = rows.every((i) => i.usable === null);
              return (
                <div key={account} className={ws.section} style={{ marginTop: "18px" }}>
                  <div className={ws.sectionHead}>
                    <h3 className={ws.sectionTitle} style={{ fontSize: "16px" }}>
                      {account === "unknown" ? "Owner not recorded" : account}{" "}
                      {mine ? (
                        <span className={`${ws.pill} ${ws.pillOn}`}>Active key — you can manage these</span>
                      ) : unknown ? (
                        <span className={`${ws.pill} ${ws.pillDraft}`}>Unknown owner</span>
                      ) : (
                        <span className={`${ws.pill} ${ws.pillBad}`}>Another account — read only</span>
                      )}
                    </h3>
                  </div>
                  {!mine && !unknown && (
                    <p className={ws.hint}>
                      Created with a key you are not using now. Yutori refuses any change to these,
                      so they cannot be stopped or deleted from here — only the account that made
                      them can. You can still Forget the record below, which only removes this
                      app&apos;s reference and leaves the Scout running at Yutori untouched.
                    </p>
                  )}
                  <div
                    className={styles.tableWrap}
                    style={
                      mine
                        ? {
                            borderLeft: "3px solid var(--forest)",
                            paddingLeft: "14px",
                            background: "var(--surface-soft)",
                            borderRadius: "0 10px 10px 0",
                          }
                        : { opacity: 0.72, paddingLeft: "17px" }
                    }
                  >
                    <table className={styles.table}>
                      <thead>
                        <tr><th>Kind</th><th>ID</th><th>From</th><th>State</th><th>Created</th><th></th></tr>
                      </thead>
                      <tbody>
                        {rows.map((instance) => (
                          <tr key={instance.id}>
                            <td>{instance.kind === "scout" ? "Scout (monitor)" : "Research task"}</td>
                            <td className={styles.mono}>{instance.external_id}</td>
                            <td>{instance.definition_name ?? "—"}</td>
                            <td>{instance.state ?? "—"}</td>
                            <td>
                              {instance.created_at
                                ? new Date(instance.created_at).toLocaleString()
                                : "—"}
                            </td>
                            <td>
                              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                                {/* Forget only applies to a Scout: delete_instance's
                                    research-task branch never calls Yutori or checks
                                    ownership, so it already handles usable === false
                                    for one correctly and for free. Routing it through
                                    Forget too would show "keeps running and billing"
                                    for a task that is already finished and never was. */}
                                {instance.usable === false && instance.kind === "scout" ? (
                                  <>
                                    <button
                                      type="button"
                                      className={styles.textButton}
                                      onClick={() => setForgetTarget(instance)}
                                      disabled={forgetInstance.isPending}
                                    >
                                      Forget
                                    </button>
                                    <InfoButton text="Removes this app's record only. Yutori is never contacted — the Scout keeps running (and billing) at Yutori under whichever account created it, unchanged. Use this to clear a reference you have no other way to remove." />
                                  </>
                                ) : (
                                  <>
                                    {instance.kind === "scout" && instance.state === "done" && (
                                      <button
                                        type="button"
                                        className={styles.textButton}
                                        onClick={() => setRestartTarget(instance)}
                                        disabled={restart.isPending}
                                      >
                                        Restart
                                      </button>
                                    )}
                                    <button
                                      type="button"
                                      className={styles.textButton}
                                      onClick={() => setDeleteTarget(instance)}
                                      disabled={removeInstance.isPending}
                                    >
                                      {instance.kind === "scout" ? "Delete at Yutori" : "Forget"}
                                    </button>
                                    <InfoButton
                                      text={
                                        instance.kind === "scout"
                                          ? "Permanently deletes this Scout at Yutori, stopping it from running or billing again. Cannot be undone — questions it already found stay in your pool."
                                          : "Removes this app's record of a finished research task. The task is already over at Yutori, so nothing there changes."
                                      }
                                    />
                                  </>
                                )}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            });
          })()
        )}
      </section>

      <ConfirmDialog
        open={deleteTarget !== null}
        title={
          deleteTarget?.kind === "scout" ? "Delete this Scout at Yutori?" : "Forget this record?"
        }
        body={
          deleteTarget?.kind === "scout" ? (
            <>
              <p>
                This permanently removes the Scout from Yutori, so it stops running and stops
                billing. It cannot be undone — a new run would create a fresh Scout.
              </p>
              <p className={ws.hint} style={{ marginTop: "10px" }}>
                Every question it already found stays in your pool.
              </p>
            </>
          ) : (
            <p>
              A research task is already finished, so there is nothing at Yutori to delete. This
              just removes our record of it.
            </p>
          )
        }
        confirmLabel={deleteTarget?.kind === "scout" ? "Delete at Yutori" : "Forget"}
        busy={removeInstance.isPending}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) removeInstance.mutate(deleteTarget.id);
          setDeleteTarget(null);
        }}
      />

      <ConfirmDialog
        open={forgetTarget !== null}
        title="Forget this record?"
        body={
          <p>
            This removes only this app&apos;s reference to it. Yutori is never contacted, and the
            Scout — created under a different account&apos;s key — keeps running and billing
            exactly as it was. Only that account can actually stop it.
          </p>
        }
        confirmLabel="Forget"
        busy={forgetInstance.isPending}
        onCancel={() => setForgetTarget(null)}
        onConfirm={() => {
          if (forgetTarget) forgetInstance.mutate(forgetTarget.id);
          setForgetTarget(null);
        }}
      />

      <ConfirmDialog
        open={restartTarget !== null}
        title="Restart this monitor?"
        body={
          <p>
            Brings it back on its schedule: it runs again at its next interval and bills each time
            until you stop it. Yutori doesn&apos;t run it now — to search right away, start a monitor
            from the scout instead.
          </p>
        }
        confirmLabel="Restart"
        busy={restart.isPending}
        onCancel={() => setRestartTarget(null)}
        onConfirm={() => {
          if (restartTarget) restart.mutate(restartTarget.id);
          setRestartTarget(null);
        }}
      />

      <ConfirmDialog
        open={stopTarget !== null}
        title={`Stop “${stopTarget?.label ?? ""}”?`}
        body={
          <p>
            Marks this monitor done at Yutori, so it stops running and stops billing. It&apos;s
            free. Questions it already found stay in your pool, and a new run can start a fresh
            monitor later.
          </p>
        }
        confirmLabel="Stop monitor"
        busy={stopOne.isPending}
        onCancel={() => setStopTarget(null)}
        onConfirm={() => {
          if (stopTarget) stopOne.mutate(stopTarget.externalId);
          setStopTarget(null);
        }}
      />

      <ConfirmDialog
        open={confirmStopOlder}
        title="Stop the older monitors?"
        body={
          <p>
            Stops the {live?.superseded_count ?? 0} monitor
            {live?.superseded_count === 1 ? "" : "s"} left behind by earlier runs. Each scout keeps
            its newest monitor. Free, and it ends about{" "}
            {money(
              (live?.monitors ?? [])
                .filter((m) => m.superseded)
                .reduce((sum, m) => sum + m.monthly_cost_usd, 0),
            )}{" "}
            a month of spending.
          </p>
        }
        confirmLabel="Stop older monitors"
        busy={stopOlder.isPending}
        onCancel={() => setConfirmStopOlder(false)}
        onConfirm={() => {
          setConfirmStopOlder(false);
          stopOlder.mutate();
        }}
      />

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>Everything at Yutori</h2>
          <button
            type="button"
            className={styles.textButton}
            onClick={() => setShowRemote((on) => !on)}
          >
            {showRemote ? "Hide" : "List scouts and research tasks"}
          </button>
        </div>
        <div className={styles.pageSub}>
          Read from Yutori rather than from this app&apos;s records, for whichever account is
          currently active — Yutori has no way to list another account&apos;s Scouts without
          switching keys to it. Anything alive here that the app does not track is billing on its
          own schedule with nobody watching it.
        </div>

        {showRemote &&
          (remoteLoading ? (
            <div className={styles.empty}>Asking Yutori…</div>
          ) : remote?.error ? (
            <div className={styles.alert}>
              <strong>Could not read the account.</strong> {remote.error}
            </div>
          ) : (
            <>
              {remote?.usage && (
                <div className={styles.notice}>
                  <strong>Last {remote.usage.period}:</strong>{" "}
                  {remote.usage.yutori_runs === null
                    ? `Yutori's own count isn't available (${remote.usage.error ?? "unknown error"}).`
                    : `Yutori counted ${remote.usage.yutori_runs} run${remote.usage.yutori_runs === 1 ? "" : "s"} on this key; this app recorded ${remote.usage.recorded_runs}.`}
                  {remote.usage.yutori_runs !== null &&
                    remote.usage.yutori_runs > remote.usage.recorded_runs &&
                    " The difference ran without this app seeing a result — usually a scheduled monitor run that found nothing."}
                  {remote.pulled && remote.pulled.new > 0 && (
                    <> Recovered {remote.pulled.new} missed update{remote.pulled.new === 1 ? "" : "s"} just now.</>
                  )}
                </div>
              )}

              {remote && remote.untracked_scouts.length > 0 && (
                <div className={styles.alert}>
                  <strong>
                    {remote.untracked_scouts.length} Scout
                    {remote.untracked_scouts.length === 1 ? "" : "s"} here{" "}
                    {remote.untracked_scouts.length === 1 ? "is" : "are"} not tracked by this app.
                  </strong>{" "}
                  They keep running on their own interval. Nothing in this app is watching them.
                </div>
              )}

              <h3 className={ws.sectionTitle} style={{ fontSize: "16px" }}>
                Scouts ({remote?.scouts.length ?? 0})
              </h3>
              {!remote?.scouts.length ? (
                <div className={styles.empty}>No Scouts exist under this key.</div>
              ) : (
                <div className={styles.tableWrap}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>ID</th><th>Scout</th><th>Status</th><th>How often</th>
                        <th>≈ a month</th><th>Created</th><th>Updates</th>
                        <th>Next run</th><th>Tracked</th><th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {remote.scouts.map((scout) => (
                        <tr key={scout.id}>
                          <td className={styles.mono}>{scout.id}</td>
                          <td>
                            {scout.definition_name ?? "—"}
                            {scout.superseded && (
                              <>
                                {" "}
                                <span className={`${ws.pill} ${ws.pillBad}`}>Leftover</span>
                              </>
                            )}
                          </td>
                          <td>{scout.status ?? "—"}</td>
                          <td>{scout.output_interval ? every(scout.output_interval) : "—"}</td>
                          <td className={styles.num}>
                            {scout.status === "active" ? money(scout.monthly_cost_usd ?? 0) : "—"}
                          </td>
                          <td>{fmt(scout.created_at)}</td>
                          <td className={styles.num}>{scout.update_count ?? "—"}</td>
                          <td>{scout.next_run ? fmt(scout.next_run) : "not scheduled"}</td>
                          <td className={scout.tracked ? styles.ok : styles.missed}>
                            {scout.tracked ? "yes" : "untracked"}
                          </td>
                          <td>
                            {scout.status === "active" || scout.status === "paused" ? (
                              <button
                                type="button"
                                className={styles.textButton}
                                disabled={stopOne.isPending}
                                onClick={() =>
                                  setStopTarget({
                                    externalId: scout.id,
                                    label: scout.definition_name ?? scout.id,
                                  })
                                }
                              >
                                Stop
                              </button>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <h3 className={ws.sectionTitle} style={{ fontSize: "16px", marginTop: "10px" }}>
                Research tasks ({remote?.research_tasks.length ?? 0})
              </h3>
              {remote?.research_error ? (
                <div className={styles.notice}>{remote.research_error}</div>
              ) : !remote?.research_tasks.length ? (
                <div className={styles.empty}>No research tasks under this key.</div>
              ) : (
                <div className={styles.tableWrap}>
                  <table className={styles.table}>
                    <thead>
                      <tr><th>ID</th><th>Status</th><th>Created</th><th>Tracked</th></tr>
                    </thead>
                    <tbody>
                      {remote.research_tasks.map((task) => (
                        <tr key={task.id}>
                          <td className={styles.mono}>{task.id}</td>
                          <td className={task.status === "succeeded" ? styles.ok : ""}>
                            {task.status ?? "—"}
                          </td>
                          <td>{fmt(task.created_at)}</td>
                          <td className={task.tracked ? styles.ok : ""}>
                            {task.tracked ? "yes" : "not ours"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className={ws.hint}>
                An untracked research task is harmless — it is already finished. An untracked
                Scout is not.
              </p>
            </>
          ))}
      </section>
    </main>
  );
}

/**
 * Monitors this app believes are running — the part of the page that answers
 * "what is billing me on its own right now?". A leftover is a live monitor
 * that isn't its scout's newest: before M13 every Scout-mode run created one
 * and nothing stopped the last.
 */
function LiveMonitors({
  data,
  busy,
  onStop,
  onStopOlder,
}: {
  data:
    | { live_count: number; superseded_count: number; monthly_cost_usd: number; monitors: Monitor[] }
    | undefined;
  busy: boolean;
  onStop: (monitor: Monitor) => void;
  onStopOlder: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <section className={styles.section}>
      <div className={styles.sectionHead}>
        <h2 className={styles.sectionTitle}>Live monitors</h2>
        {data && data.superseded_count > 0 && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <button type="button" className={ws.primary} disabled={busy} onClick={onStopOlder}>
              Stop older monitors ({data.superseded_count})
            </button>
            <InfoButton text="Stops every monitor that isn't its scout's newest. Each scout keeps one. Free — stopping never costs anything." />
          </span>
        )}
      </div>
      <div className={styles.pageSub}>
        {data === undefined
          ? "Loading…"
          : data.live_count === 0
            ? "None. Nothing is running or billing on its own schedule."
            : `${data.live_count} running on their own schedule · about ${money(data.monthly_cost_usd)} a month. As recorded here — list what's at Yutori below to refresh from the source.`}
      </div>
      {data && data.monitors.length > 0 && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Scout</th><th>ID</th><th>How often</th><th>≈ a month</th>
                <th>Next run</th><th>Started</th><th></th>
              </tr>
            </thead>
            <tbody>
              {data.monitors.map((monitor) => [
                <tr key={monitor.id}>
                  <td>
                    {monitor.definition_id ? (
                      <Link className={styles.textButton} href={`/yutori/scouts/${monitor.definition_id}`}>
                        {monitor.definition_name ?? "Untitled"}
                      </Link>
                    ) : (
                      "—"
                    )}
                    {monitor.superseded && (
                      <>
                        {" "}
                        <span className={`${ws.pill} ${ws.pillBad}`}>Leftover</span>
                      </>
                    )}
                  </td>
                  <td className={styles.mono}>{monitor.external_id}</td>
                  <td>{every(monitor.output_interval)}</td>
                  <td className={styles.num}>{money(monitor.monthly_cost_usd)}</td>
                  <td>{monitor.next_run ? fmt(monitor.next_run) : "—"}</td>
                  <td>{fmt(monitor.created_at)}</td>
                  <td>
                    <span style={{ display: "inline-flex", gap: 10 }}>
                      <button
                        type="button"
                        className={styles.textButton}
                        onClick={() => setOpen(open === monitor.id ? null : monitor.id)}
                        aria-expanded={open === monitor.id}
                      >
                        {open === monitor.id ? "Hide" : "Details"}
                      </button>
                      <button
                        type="button"
                        className={styles.textButton}
                        disabled={busy}
                        onClick={() => onStop(monitor)}
                      >
                        Stop
                      </button>
                    </span>
                  </td>
                </tr>,
                open === monitor.id ? (
                  <tr key={`${monitor.id}-details`}>
                    <td colSpan={7}>
                      <MonitorDetails instanceId={monitor.id} />
                    </td>
                  </tr>
                ) : null,
              ])}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
