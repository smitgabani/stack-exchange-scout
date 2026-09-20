"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
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
  const { data, isLoading } = useQuery({ queryKey: ["runs"], queryFn: () => scoutApi.listRuns() });

  if (isLoading || !data) return <main className={styles.page}>Loading…</main>;

  const run = data.runs.find((r) => r.id === params.runId);
  if (!run) {
    return (
      <main className={styles.page}>
        <Link className={styles.back} href="/scout">← All scouts</Link>
        <div className={styles.empty}>That run could not be found.</div>
      </main>
    );
  }

  const found = run.questions ?? run.questions_found ?? 0;

  return (
    <main className={styles.page}>
      <Link className={styles.back} href={run.definition_id ? `/scout/${run.definition_id}` : "/scout"}>
        ← Back
      </Link>

      <div className={styles.head}>
        <div>
          <div className={styles.title}>Run · {when(run.started_at)}</div>
          <div className={`${styles.sub} ${styles.mono}`}>
            {run.kind === "research_task" ? "research task" : "scout"} · {run.id}
          </div>
        </div>
      </div>

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
