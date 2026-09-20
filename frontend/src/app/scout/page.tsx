"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { RunScoutButton } from "../run-scout-button";
import { type ScoutStatus, useScout } from "../use-scout";
import styles from "./scout.module.css";

type PanelUpdate = {
  id: string;
  timestamp: number | string | null;
  structured_output_status: string | null;
  pages_read: number | null;
  citations: number;
  received: boolean;
  questions?: number;
  candidates?: number;
  above_threshold?: number;
};

type PanelEvent = {
  id: string;
  type: string;
  created_at: string | null;
  query_text: string | null;
  cost_usd: number | null;
  detail: Record<string, unknown> | null;
};

type Panel = {
  status: ScoutStatus;
  query_text: string | null;
  current_query_text: string | null;
  query_is_current: boolean;
  query_synced_at: string | null;
  profile_version: number;
  configuration: {
    output_interval: number | null;
    user_timezone: string | null;
    webhook_format: string | null;
    webhook_url: string | null;
    is_public: boolean | null;
    created_at: string | null;
    display_name: string | null;
    has_output_schema: boolean;
    run_mechanism: string;
  };
  usage: {
    period: string;
    scout_runs: number;
    estimated_spend_usd: number;
    num_active_scouts: number;
    active_scout_ids: string[];
    run_cost_usd: number;
    error: string | null;
  };
  updates: PanelUpdate[];
  events: PanelEvent[];
  health: {
    events_awaiting_ingest: number;
    orphan_scout_ids: string[];
    last_sync_error: string | null;
  };
  run_diagnostics: {
    run_state: string;
    has_run_record: boolean;
    run_started_at?: string;
    run_finished_at?: string | null;
    elapsed_seconds?: number;
    timeout_seconds?: number;
    baseline_update_count?: number | null;
    current_update_count?: number | null;
    update_count_moved?: boolean;
    webhooks_since_run_started?: number;
    run_mechanism?: string;
    run_interval_seconds?: number;
    run_kind?: "research_task" | "scout" | null;
    run_external_id?: string | null;
  };
  raw: {
    scout_detail: Record<string, unknown> | null;
    usage: Record<string, unknown> | null;
    latest_update: Record<string, unknown> | null;
  };
};

function duration(seconds: number | undefined): string {
  if (seconds === undefined) return "—";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

async function fetchPanel(includeRaw: boolean): Promise<Panel> {
  // The raw payloads are the biggest part of this response and every byte
  // crosses a Vercel function, so they are fetched only when the debugging
  // section is actually open.
  const response = await fetch(`/api/scout/panel?include_raw=${includeRaw}`);
  if (!response.ok) {
    throw new Error(`scout panel failed: ${response.status}`);
  }
  return response.json();
}

// Yutori's update timestamps are epoch milliseconds (observed: 1789618345787),
// while anything smaller would be seconds. Treating one as the other puts the
// date in the year 58,000.
const MILLISECOND_THRESHOLD = 100_000_000_000;

function when(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const date =
    typeof value === "number"
      ? new Date(value > MILLISECOND_THRESHOLD ? value : value * 1000)
      : new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function interval(seconds: number | null): string {
  if (!seconds) return "—";
  if (seconds >= 86400) return `${Math.round(seconds / 86400)} days`;
  if (seconds >= 3600) return `${Math.round(seconds / 3600)} hours`;
  return `${Math.round(seconds / 60)} minutes`;
}

const EVENT_LABELS: Record<string, string> = {
  query_synced: "Query updated",
  run_started: "Run started",
  update_received: "Update received",
  parked: "Scout parked",
  error: "Error",
};

function StatusCard({ status }: { status: ScoutStatus }) {
  if (status.run_state === "running") {
    return (
      <div className={`${styles.block} ${styles.running}`}>
        <div className={styles.blockLabel}>Status</div>
        <div className={styles.blockValue}>Running now</div>
        <div className={styles.blockNote}>Started {when(status.run_started_at)}</div>
      </div>
    );
  }
  if (!status.configured) {
    return (
      <div className={`${styles.block} ${styles.idle}`}>
        <div className={styles.blockLabel}>Status</div>
        <div className={styles.blockValue}>No Scout yet</div>
        <div className={styles.blockNote}>The first run will create one.</div>
      </div>
    );
  }
  // Never assert a state we couldn't actually read. A null external_status
  // means Yutori didn't answer, which is not the same as "Active".
  if (!status.external_status) {
    return (
      <div className={`${styles.block} ${styles.idle}`}>
        <div className={styles.blockLabel}>Status</div>
        <div className={styles.blockValue}>Unknown</div>
        <div className={styles.blockNote}>
          Yutori hasn&apos;t reported this Scout&apos;s state — usually an API key problem.
        </div>
      </div>
    );
  }
  const parked = status.external_status === "done" || status.external_status === "paused";
  return (
    <div className={`${styles.block} ${parked ? styles.parked : styles.active}`}>
      <div className={styles.blockLabel}>Status</div>
      <div className={styles.blockValue}>{parked ? "Parked" : "Active"}</div>
      <div className={styles.blockNote}>
        {parked
          ? "Runs only when you ask"
          : status.next_run_at
            ? `Next run ${when(status.next_run_at)}`
            : "Awake, but no run scheduled"}
        {status.last_update_at && ` · last update ${when(status.last_update_at)}`}
      </div>
    </div>
  );
}

export default function ScoutPage() {
  // The one page where someone is watching a run, so the only one that polls.
  const { scout, message, park, sync, pull, forget, isRunning } = useScout({ poll: true });
  const [showRaw, setShowRaw] = useState(false);
  const { data: panel, isLoading } = useQuery({
    queryKey: ["scout-panel", showRaw],
    queryFn: () => fetchPanel(showRaw),
    refetchInterval: isRunning ? 30_000 : false,
    staleTime: 15_000,
  });

  if (isLoading || !panel) {
    return <main className={styles.page}>Loading…</main>;
  }

  const status = scout ?? panel.status;
  const { configuration: config, usage, health } = panel;
  // Vercel and Fly deploy separately, so the frontend is routinely newer than
  // the backend it talks to. Default anything the older API won't send.
  const diag = panel.run_diagnostics ?? { run_state: "idle", has_run_record: false };
  const raw = panel.raw ?? { scout_detail: null, usage: null, latest_update: null };
  const busy = park.isPending || sync.isPending || pull.isPending || forget.isPending;

  return (
    <main className={styles.page}>
      <div className={styles.header}>
        <div>
          <div className={styles.pageTitle}>Discovery Scout</div>
          <div className={styles.pageSub}>
            The Yutori agent that finds Stack Overflow questions matching your interests.
          </div>
        </div>
        <div className={styles.headerActions}>
          <button
            type="button"
            className={styles.secondary}
            onClick={() => park.mutate()}
            disabled={busy || isRunning}
          >
            Park
          </button>
          <RunScoutButton className={styles.primary} label="Run now" />
        </div>
      </div>

      {/* A Scout created under another account cannot be edited by this key —
          Yutori answers 403. Nothing here can fix that, so the page explains it
          and offers the only real action: stop pointing at it. */}
      {status.account_mismatch && (
        <div className={styles.alert}>
          <strong>This Scout belongs to a different Yutori account.</strong> It was
          created with another API key, so the key you are using now cannot read,
          edit, run or delete it — Yutori refuses with &ldquo;Only the creator of a
          scout can edit it&rdquo;. The Scout itself keeps existing in whichever
          account made it; only its owner can stop it.
          <div className={styles.alertActions}>
            <button
              type="button"
              className={styles.alertButton}
              onClick={() => forget.mutate()}
              disabled={busy}
            >
              Forget this Scout
            </button>
            <span>
              Clears the link only. No discovered questions are removed, and a
              research run works regardless.
            </span>
          </div>
        </div>
      )}

      {/* An out-of-credit Scout looks exactly like one that found nothing, and
          the dashboard would claim the latter. This says which it is. */}
      {status.rejection_reason && (
        <div className={styles.alert}>
          Yutori stopped this Scout: <strong>{status.rejection_reason.replace(/_/g, " ")}</strong>
        </div>
      )}

      {message && <div className={styles.notice}>{message}</div>}

      <div className={styles.blocks}>
        <StatusCard status={status} />
        {/* Zero runs and zero spend are a real, reassuring claim — so don't
            make it when the usage call actually failed. */}
        <div className={`${styles.block} ${styles.spend}`}>
          <div className={styles.blockLabel}>Spend</div>
          <div className={styles.blockValue}>
            {usage.error ? "—" : `$${usage.estimated_spend_usd.toFixed(2)}`}
          </div>
          <div className={styles.blockNote}>
            {usage.error
              ? `Yutori didn't report usage · $${usage.run_cost_usd.toFixed(2)} per run`
              : `${usage.scout_runs} run${usage.scout_runs === 1 ? "" : "s"} in the last ${usage.period} · $${usage.run_cost_usd.toFixed(2)} per run`}
          </div>
        </div>
      </div>

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>Query being searched</h2>
          <button
            type="button"
            className={styles.textButton}
            onClick={() => sync.mutate()}
            disabled={busy}
          >
            Re-sync
          </button>
        </div>
        <div className={styles.pageSub}>
          Last pushed to Yutori {when(panel.query_synced_at)}. This is exactly what Yutori
          searches for — the first thing to check when results look wrong.
        </div>
        {!panel.query_is_current && (
          <div className={styles.alert}>
            Your topics have changed since this was last sent. The Scout is still searching for the
            query below — press Re-sync to bring it up to date before running it.
          </div>
        )}
        <pre className={styles.query}>{panel.query_text ?? "No query generated yet."}</pre>
        {panel.current_query_text && (
          <>
            <div className={styles.sectionTitle}>What your current topics would send</div>
            <pre className={styles.query}>{panel.current_query_text}</pre>
          </>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Configuration</h2>
        <dl className={styles.config}>
          <div><dt>Run interval</dt><dd>{interval(config.output_interval)}</dd></div>
          <div><dt>Timezone</dt><dd>{config.user_timezone ?? "—"}</dd></div>
          <div><dt>Webhook</dt><dd>{config.webhook_url ?? "—"}</dd></div>
          <div><dt>Webhook format</dt><dd>{config.webhook_format ?? "—"}</dd></div>
          <div><dt>Structured output</dt><dd>{config.has_output_schema ? "Schema registered" : "None"}</dd></div>
          <div>
            <dt>Visibility</dt>
            {/* Yutori defaults new Scouts to public, meaning anyone with the
                UUID can read the reports. Flagged loudly if that's the case. */}
            <dd className={config.is_public ? styles.missed : undefined}>
              {config.is_public === null
                ? "—"
                : config.is_public
                  ? "Public — readable by UUID"
                  : "Private"}
            </dd>
          </div>
          <div><dt>Run mechanism</dt><dd>{config.run_mechanism}</dd></div>
          <div><dt>Created</dt><dd>{when(config.created_at)}</dd></div>
          <div>
            <dt>Scout ID</dt>
            <dd className={styles.mono}>{status.external_scout_id ?? "—"}</dd>
          </div>
          {status.external_scout_id && (
            <div>
              {/* Always offered, not only when a mismatch is detected: the
                  detection can be wrong or absent, and being unable to
                  unstick a dead reference is worse than an extra button. */}
              <dt>Link</dt>
              <dd>
                <button
                  type="button"
                  className={styles.textButton}
                  onClick={() => forget.mutate()}
                  disabled={busy}
                >
                  Forget this Scout
                </button>
              </dd>
            </div>
          )}
        </dl>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>Updates</h2>
          <button
            type="button"
            className={styles.textButton}
            onClick={() => pull.mutate()}
            disabled={busy}
          >
            Fetch missed updates
          </button>
        </div>
        <div className={styles.pageSub}>
          What each run produced. Yutori retries a webhook only three times over about
          thirty seconds, so an update marked missed was paid for but never delivered.
        </div>
        {panel.updates.length === 0 ? (
          <div className={styles.empty}>No updates yet.</div>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Output</th>
                  <th>Questions</th>
                  <th>Candidates</th>
                  <th>Above bar</th>
                  <th>Pages read</th>
                  <th>Delivered</th>
                </tr>
              </thead>
              <tbody>
                {panel.updates.map((update) => (
                  <tr key={update.id}>
                    <td>{when(update.timestamp)}</td>
                    <td>{update.structured_output_status ?? "—"}</td>
                    <td>{update.questions ?? 0}</td>
                    <td>{update.candidates ?? 0}</td>
                    <td>{update.above_threshold ?? 0}</td>
                    <td>{update.pages_read ?? "—"}</td>
                    <td className={update.received ? styles.ok : styles.missed}>
                      {update.received ? "yes" : "missed"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Last run</h2>
        <div className={styles.pageSub}>
          Yutori won&apos;t say whether a run actually started — its
          next_run_timestamp comes back as epoch 0. So this shows what changed
          after the run began and lets that answer the question.
        </div>
        {!diag.has_run_record ? (
          <div className={styles.empty}>No run has been started yet.</div>
        ) : (
          <>
            <dl className={styles.config}>
              <div><dt>Run state</dt><dd>{diag.run_state}</dd></div>
              <div>
                <dt>Kind</dt>
                <dd>
                  {diag.run_kind === "research_task"
                    ? "Research task (one-shot)"
                    : diag.run_kind === "scout"
                      ? "Scout (monitor)"
                      : "—"}
                  {diag.run_external_id ? ` · ${diag.run_external_id}` : ""}
                </dd>
              </div>
              <div><dt>Started</dt><dd>{when(diag.run_started_at ?? null)}</dd></div>
              <div>
                <dt>Elapsed</dt>
                <dd>
                  {duration(diag.elapsed_seconds)} of {duration(diag.timeout_seconds)} before timeout
                </dd>
              </div>
              <div><dt>Finished</dt><dd>{when(diag.run_finished_at ?? null)}</dd></div>
              <div>
                <dt>Yutori update count</dt>
                <dd>
                  {diag.baseline_update_count ?? "—"} at start → {diag.current_update_count ?? "—"} now
                </dd>
              </div>
              <div>
                <dt>Did a run happen?</dt>
                {/* The whole question, in one field. */}
                <dd className={diag.update_count_moved ? styles.ok : styles.missed}>
                  {diag.update_count_moved
                    ? "yes — Yutori produced a new update"
                    : "no new update from Yutori yet"}
                </dd>
              </div>
              <div>
                <dt>Webhooks since start</dt>
                <dd>{diag.webhooks_since_run_started ?? 0}</dd>
              </div>
              <div>
                <dt>Mechanism · interval</dt>
                <dd>
                  {diag.run_mechanism} · {duration(diag.run_interval_seconds)}
                </dd>
              </div>
            </dl>
            {diag.run_kind === "scout" &&
              diag.run_mechanism === "restart" &&
              diag.update_count_moved === false &&
              (diag.elapsed_seconds ?? 0) > 1800 && (
                <div className={styles.alert}>
                  Half an hour with no new update. Restart appears to resume the Scout&apos;s
                  schedule rather than run it — and the run interval is{" "}
                  {duration(diag.run_interval_seconds)}, so the next scheduled run is a long way
                  off. Switching SCOUT_RUN_MECHANISM to &ldquo;recreate&rdquo; would delete and
                  recreate the Scout, which does start a run immediately.
                </div>
              )}
          </>
        )}
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>Raw Yutori responses</h2>
          <button
            type="button"
            className={styles.textButton}
            onClick={() => setShowRaw((on) => !on)}
          >
            {showRaw ? "Hide" : "Load"}
          </button>
        </div>
        <div className={styles.pageSub}>
          Exactly what their API returned, webhook secret removed. Their docs
          don&apos;t describe most of this behaviour, so the payloads are the evidence.
          Loaded on demand — they are large, and every byte crosses the proxy.
        </div>
        {showRaw && (
          <>
            <details className={styles.details}>
              <summary className={styles.summary}>Scout detail</summary>
              <pre className={styles.query}>{JSON.stringify(raw.scout_detail, null, 2)}</pre>
            </details>
            <details className={styles.details}>
              <summary className={styles.summary}>Usage (/v1/usage)</summary>
              <pre className={styles.query}>{JSON.stringify(raw.usage, null, 2)}</pre>
            </details>
            <details className={styles.details}>
              <summary className={styles.summary}>Latest update</summary>
              <pre className={styles.query}>{JSON.stringify(raw.latest_update, null, 2)}</pre>
            </details>
          </>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Timeline</h2>
        {panel.events.length === 0 ? (
          <div className={styles.empty}>Nothing recorded yet.</div>
        ) : (
          <ol className={styles.timeline}>
            {panel.events.map((event) => (
              <li key={event.id} className={styles.event}>
                <div className={styles.eventHead}>
                  <span className={styles.eventType}>{EVENT_LABELS[event.type] ?? event.type}</span>
                  <span className={styles.eventTime}>{when(event.created_at)}</span>
                  {event.cost_usd ? <span className={styles.eventCost}>${event.cost_usd.toFixed(2)}</span> : null}
                </div>
                {event.detail && (
                  <div className={styles.eventDetail}>
                    {Object.entries(event.detail)
                      .filter(([, value]) => value !== null && value !== undefined)
                      .map(([key, value]) => `${key.replace(/_/g, " ")}: ${value}`)
                      .join(" · ")}
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Health</h2>
        <dl className={styles.config}>
          <div><dt>Events awaiting ingest</dt><dd>{health.events_awaiting_ingest}</dd></div>
          <div>
            {/* Observed to mean "runs executing right now" rather than
                "scouts whose status is active" — so it doubles as a liveness
                check while a run is supposed to be in progress. */}
            <dt>Runs executing now</dt>
            <dd>{usage.error ? "—" : usage.num_active_scouts}</dd>
          </div>
          <div>
            <dt>Untracked Scouts</dt>
            {/* "none" is a claim we can only make if Yutori actually answered. */}
            <dd className={health.orphan_scout_ids.length ? styles.missed : undefined}>
              {usage.error
                ? "unknown"
                : health.orphan_scout_ids.length
                  ? health.orphan_scout_ids.join(", ")
                  : "none"}
            </dd>
          </div>
          <div>
            <dt>Yutori API</dt>
            <dd className={usage.error ? styles.missed : styles.ok}>
              {usage.error ? usage.error : "reachable"}
            </dd>
          </div>
          <div><dt>Last sync error</dt><dd>{health.last_sync_error ?? "none"}</dd></div>
        </dl>
        {health.orphan_scout_ids.length > 0 && (
          <div className={styles.alert}>
            A Scout is running at Yutori that this app does not track. It will keep billing on its
            own interval until it is stopped.
          </div>
        )}
      </section>
    </main>
  );
}
