"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { duration, money, scoutApi, when } from "@/lib/scout-api";
import styles from "../../../workspace.module.css";

/** Each stage is somewhere candidates are lost, so a run that returned plenty
 *  and delivered nothing looks different from one that found nothing. */
function Funnel({ found, candidates, aboveBar }: { found: number; candidates: number; aboveBar: number }) {
  const top = Math.max(found, 1);
  const steps = [
    { label: "Returned by Yutori", n: found, color: "var(--ink)" },
    { label: "Reached the pool", n: candidates, color: "var(--body-text)" },
    { label: "Above the digest bar", n: aboveBar, color: "var(--mint)" },
  ];
  return (
    <div className={styles.funnel}>
      {steps.map((s) => (
        <div className={styles.funnelStep} key={s.label}>
          <span>{s.label}</span>
          <span
            className={styles.funnelBar}
            style={{ width: `${Math.max((s.n / top) * 100, 1)}%`, background: s.color }}
          />
          <span className={styles.funnelCount}>{s.n}</span>
        </div>
      ))}
    </div>
  );
}

export default function RunPage() {
  const params = useParams<{ runId: string }>();
  const queryClient = useQueryClient();
  const [note, setNote] = useState<string | null>(null);
  const { data, isLoading } = useQuery({ queryKey: ["runs"], queryFn: () => scoutApi.listRuns() });

  const sync = useMutation({
    mutationFn: () => scoutApi.syncRun(params.runId),
    onSuccess: async (result) => {
      setNote(
        result.error
          ? `Yutori: ${result.error}`
          : result.status === "running"
            ? `Still ${result.remote_status ?? "running"} at Yutori. Nothing to collect yet.`
            : result.status === "succeeded"
              ? `Collected ${result.questions_found ?? 0} question${
                  result.questions_found === 1 ? "" : "s"
                } via ${result.delivered_by ?? "poll"}.`
              : `Yutori reported this run as ${result.status}.`,
      );
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      await queryClient.invalidateQueries({ queryKey: ["definitions"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  // A run left unfinished has results sitting uncollected at Yutori, so the
  // page fetches them on arrival rather than waiting to be asked.
  const runRow = data?.runs.find((r) => r.id === params.runId);
  const stillRunning = runRow?.status === "running";
  useEffect(() => {
    if (stillRunning && !sync.isPending && !sync.isSuccess) sync.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stillRunning]);

  if (isLoading || !data) return <main className={styles.page}>Loading…</main>;

  const run = runRow;
  if (!run) {
    return (
      <main className={styles.page}>
        <Link className={styles.back} href="/yutori/scouts">← All scouts</Link>
        <div className={styles.empty}>That run could not be found.</div>
      </main>
    );
  }

  const found = run.questions ?? run.questions_found ?? 0;

  return (
    <main className={styles.page}>
      <Link className={styles.back} href={run.definition_id ? `/yutori/scouts/${run.definition_id}` : "/yutori/scouts"}>
        ← Back
      </Link>

      <div className={styles.head}>
        <div>
          <div className={styles.title}>Run · {when(run.started_at)}</div>
          <div className={`${styles.sub} ${styles.mono}`}>
            {run.kind === "research_task" ? "research task" : "scout"} · {run.id}
          </div>
        </div>
        <div className={styles.actions}>
          <button
            className={styles.primary}
            onClick={() => sync.mutate()}
            disabled={sync.isPending}
          >
            {sync.isPending ? "Asking Yutori…" : "Fetch from Yutori"}
          </button>
        </div>
      </div>

      {note && <div className={styles.notice}>{note}</div>}

      {run.status === "running" && (
        <div className={styles.notice}>
          Still open. If Yutori shows this as finished, press <strong>Fetch from Yutori</strong> —
          the result is collected and the questions are ingested. It is free and can be pressed
          as often as you like.
        </div>
      )}

      {run.status === "failed" && run.error && (
        <div className={styles.alert}><strong>This run failed.</strong> {run.error}</div>
      )}
      {run.status === "timed_out" && (
        <div className={styles.alert}>
          <strong>This run produced nothing.</strong> It was closed after the timeout with no
          result — the money was spent and nothing came back.
        </div>
      )}

      <div className={styles.stats}>
        <div className={styles.stat}>
          <div className={styles.statKey}>Status</div>
          <div className={styles.statValue} style={{ fontSize: "20px" }}>{run.status}</div>
          <div className={styles.statMeta}>{run.kind === "research_task" ? "one-shot" : "monitor"}</div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statKey}>Cost</div>
          <div className={styles.statValue}>{money(run.cost_usd)}</div>
          <div className={styles.statMeta}>charged on creation</div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statKey}>Duration</div>
          <div className={styles.statValue}>{duration(run.duration_seconds)}</div>
          <div className={styles.statMeta}>{when(run.finished_at)}</div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statKey}>Collected by</div>
          <div className={styles.statValue} style={{ fontSize: "20px" }}>{run.delivered_by ?? "—"}</div>
          <div className={styles.statMeta}>
            {run.delivered_by === "poll" ? "webhook never arrived" : "delivery path"}
          </div>
        </div>
      </div>

      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Where the questions went</h2>
        <Funnel found={found} candidates={run.candidates ?? 0} aboveBar={run.above_bar ?? 0} />
        <p className={styles.hint}>
          {found === 0
            ? "This run returned nothing, so there was nothing to lose along the way."
            : `${found} returned, ${run.above_bar ?? 0} good enough to reach a digest — about ${money(
                (run.cost_usd ?? 0) / Math.max(run.above_bar ?? 0, 1),
              )} per usable question.`}
        </p>
      </div>

      <dl className={styles.dl}>
        <div><dt>Charged to</dt><dd>{run.account_label ?? "—"}</dd></div>
        <div><dt>Started</dt><dd>{when(run.started_at)}</dd></div>
        <div><dt>Finished</dt><dd>{when(run.finished_at)}</dd></div>
        <div><dt>Questions recorded</dt><dd>{run.questions_found ?? "—"}</dd></div>
      </dl>
    </main>
  );
}
