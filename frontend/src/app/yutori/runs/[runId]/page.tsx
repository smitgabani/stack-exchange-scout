"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  type RunDetail,
  type RunQuestion,
  type RunQuestionFate,
  duration,
  money,
  scoutApi,
  when,
} from "@/lib/scout-api";
import styles from "../../../workspace.module.css";

/** Each stage is somewhere candidates are lost, so a run that returned plenty
 *  and delivered nothing looks different from one that found nothing. */
function Funnel({ run }: { run: RunDetail }) {
  const top = Math.max(run.unique_questions, 1);
  const steps = [
    { label: "Returned by Yutori", n: run.unique_questions, color: "var(--ink)" },
    { label: "New to the pool", n: run.new_here, color: "var(--body-text)" },
    { label: "Above the digest bar", n: run.above_bar, color: "var(--mint)" },
    { label: "Became a challenge", n: run.challenges, color: "var(--coral)" },
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

/** Plain words for each outcome — "rejected" alone does not say who rejected it. */
const FATE: Record<RunQuestionFate, { label: string; tone: string; why: string }> = {
  made_a_challenge: { label: "Became a challenge", tone: "pillOn", why: "Curated into a digest." },
  in_pool: { label: "In the pool", tone: "pillReady", why: "Scored and waiting for a digest." },
  awaiting_enrichment: {
    label: "Awaiting enrichment",
    tone: "pillDraft",
    why: "Not yet verified against Stack Overflow.",
  },
  filtered_out: {
    label: "Filtered out",
    tone: "pillBad",
    why: "Rejected automatically — closed, duplicate, or already well answered.",
  },
  dismissed: { label: "Dismissed by you", tone: "pill", why: "You took this out of the pool." },
  not_ingested: {
    label: "Never ingested",
    tone: "pillBad",
    why: "Returned by this run but never added to the pool.",
  },
  unparseable: {
    label: "Unreadable",
    tone: "pillBad",
    why: "No Stack Overflow id could be read from this result.",
  },
  solved: { label: "Solved", tone: "pillOn", why: "" },
  skipped: { label: "Skipped", tone: "pill", why: "" },
};

function QuestionRow({ question }: { question: RunQuestion }) {
  const fate = FATE[question.fate] ?? { label: question.fate, tone: "pill", why: "" };
  return (
    <tr>
      <td>
        <a href={question.url} target="_blank" rel="noopener noreferrer">
          {question.title ?? `Question ${question.stackoverflow_question_id}`}
        </a>
        {question.tags.length > 0 && (
          <div className={styles.hint}>{question.tags.slice(0, 5).join(" · ")}</div>
        )}
      </td>
      <td>
        {question.first_seen_here ? (
          <span className={`${styles.pill} ${styles.pillOn}`}>New</span>
        ) : (
          // The number that separates a sharp query from a stale one: this run
          // paid for a question the app already had.
          <span className={styles.pill} title="This run returned a question already in the pool">
            Already known
          </span>
        )}
      </td>
      <td className={styles.mono}>
        {question.candidate_score !== null ? question.candidate_score.toFixed(1) : "—"}
      </td>
      <td>
        <span className={`${styles.pill} ${styles[fate.tone] ?? ""}`} title={fate.why}>
          {fate.label}
        </span>
        {question.rejection_reason && question.fate === "filtered_out" && (
          <div className={styles.hint}>{question.rejection_reason.replace(/_/g, " ")}</div>
        )}
      </td>
      <td>
        {question.challenge_id ? (
          <Link className={styles.textButton} href={`/challenge/${question.challenge_id}`}>
            Open
          </Link>
        ) : (
          "—"
        )}
      </td>
    </tr>
  );
}

export default function RunPage() {
  const params = useParams<{ runId: string }>();
  const queryClient = useQueryClient();
  const [note, setNote] = useState<string | null>(null);

  const { data: run, isLoading, isError } = useQuery({
    queryKey: ["run", params.runId],
    queryFn: () => scoutApi.getRun(params.runId),
  });

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
      await queryClient.invalidateQueries({ queryKey: ["run"] });
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  const ingest = useMutation({
    mutationFn: async () => {
      const response = await fetch("/api/candidates/ingest", { method: "POST" });
      if (!response.ok) throw new Error(`ingest failed: ${response.status}`);
      return response.json();
    },
    onSuccess: async (body) => {
      setNote(`Ingest: ${body.succeeded} added, ${body.skipped} skipped, ${body.failed} failed.`);
      await queryClient.invalidateQueries({ queryKey: ["run"] });
      await queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  // A run left unfinished has results sitting uncollected at Yutori, so the
  // page fetches them on arrival rather than waiting to be asked.
  const stillRunning = run?.status === "running";
  useEffect(() => {
    if (stillRunning && !sync.isPending && !sync.isSuccess) sync.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stillRunning]);

  if (isLoading) return <main className={styles.page}>Loading…</main>;
  if (isError || !run) {
    return (
      <main className={styles.page}>
        <Link className={styles.back} href="/yutori/runs">← All runs</Link>
        <div className={styles.empty}>That run could not be found.</div>
      </main>
    );
  }

  const perNew = run.cost_per_new_question;

  return (
    <main className={styles.page}>
      <Link
        className={styles.back}
        href={run.definition_id ? `/yutori/scouts/${run.definition_id}` : "/yutori/runs"}
      >
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
          <button className={styles.primary} onClick={() => sync.mutate()} disabled={sync.isPending}>
            {sync.isPending ? "Asking Yutori…" : "Fetch from Yutori"}
          </button>
        </div>
      </div>

      {note && <div className={styles.notice}>{note}</div>}

      {/* A paid result sitting in the inbox is the most expensive thing this
          page can show, so it says so before anything else. */}
      {run.event_status === "received" && (
        <div className={styles.alert}>
          <strong>This run&apos;s results were never ingested.</strong> Yutori returned{" "}
          {run.returned} question{run.returned === 1 ? "" : "s"} and they are still sitting in the
          inbox, so they never reached the pool.{" "}
          <button
            className={`${styles.primary} ${styles.tiny}`}
            onClick={() => ingest.mutate()}
            disabled={ingest.isPending}
          >
            {ingest.isPending ? "Ingesting…" : "Ingest them now"}
          </button>
        </div>
      )}

      {!run.has_payload && run.status === "succeeded" && (
        <div className={styles.alert}>
          <strong>No stored result.</strong> This run is marked succeeded but no payload was ever
          recorded, so there is nothing to attribute to it.
        </div>
      )}

      {run.status === "running" && (
        <div className={styles.notice}>
          Still open. If Yutori shows this as finished, press <strong>Fetch from Yutori</strong> —
          it is free and can be pressed as often as you like.
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
          <div className={styles.statKey}>Cost</div>
          <div className={styles.statValue}>{money(run.cost_usd)}</div>
          <div className={styles.statMeta}>charged to {run.account_label ?? "—"}</div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statKey}>Returned</div>
          <div className={styles.statValue}>{run.unique_questions}</div>
          <div className={styles.statMeta}>
            {run.unparseable > 0 ? `${run.unparseable} unreadable` : "questions from Yutori"}
          </div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statKey}>New to you</div>
          <div className={styles.statValue}>{run.new_here}</div>
          <div className={styles.statMeta}>
            {run.already_known} already known
          </div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statKey}>Cost per new</div>
          <div className={styles.statValue}>{perNew === null ? "—" : money(perNew)}</div>
          <div className={styles.statMeta}>
            {perNew === null ? "nothing new was found" : "what discovery actually cost"}
          </div>
        </div>
      </div>

      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Where the questions went</h2>
        <Funnel run={run} />
        <p className={styles.hint}>
          {run.unique_questions === 0
            ? "This run returned nothing, so there was nothing to lose along the way."
            : run.new_here === 0
              ? `Every one of the ${run.unique_questions} questions returned was already in the pool. This run cost ${money(run.cost_usd)} and discovered nothing new — a sign the query is returning the same ground twice.`
              : `${run.new_here} of ${run.unique_questions} were new, ${run.above_bar} cleared the digest bar, ${run.challenges} became a challenge.`}
        </p>
      </div>

      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>
          Questions returned ({run.questions.length})
        </h2>
        <div className={styles.sub}>
          Best-scoring first. &ldquo;Already known&rdquo; means this run returned something the app
          had seen before — paid for, but not new.
        </div>
        {run.questions.length === 0 ? (
          <div className={styles.empty}>No questions recorded for this run.</div>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Question</th>
                  <th>Discovery</th>
                  <th>Score</th>
                  <th>What happened</th>
                  <th>Challenge</th>
                </tr>
              </thead>
              <tbody>
                {run.questions.map((question) => (
                  <QuestionRow key={question.stackoverflow_question_id} question={question} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <dl className={styles.dl}>
        <div><dt>Charged to</dt><dd>{run.account_label ?? "—"}</dd></div>
        <div><dt>Started</dt><dd>{when(run.started_at)}</dd></div>
        <div><dt>Finished</dt><dd>{when(run.finished_at)}</dd></div>
        <div>
          <dt>Took</dt>
          <dd>
            {run.started_at && run.finished_at
              ? duration(
                  Math.round(
                    (new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) /
                      1000,
                  ),
                )
              : "—"}
          </dd>
        </div>
        <div>
          <dt>Collected by</dt>
          <dd>
            {run.delivered_by ?? "—"}
            {run.delivered_by === "poll" && " (the webhook never arrived)"}
          </dd>
        </div>
        <div><dt>Result stored</dt><dd>{run.event_status ?? "nothing recorded"}</dd></div>
      </dl>
    </main>
  );
}
