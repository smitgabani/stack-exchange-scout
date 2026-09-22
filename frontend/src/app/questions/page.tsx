"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { jobsApi } from "@/lib/jobs-api";
import { llmApi } from "@/lib/llm-api";
import { JobStatus, useJob } from "../job-status";
import { colorForTopic } from "@/lib/topic-color";
import { ConfirmDialog } from "../confirm-dialog";
import { InfoButton } from "../info-button";
import styles from "./questions.module.css";

type QuestionRow = {
  id: string;
  stackoverflow_question_id: number | null;
  url: string;
  title: string | null;
  tags: string[];
  score: number | null;
  answer_count: number | null;
  has_accepted_answer: boolean;
  is_closed: boolean;
  difficulty: number | null;
  problem_summary: string | null;
  candidate_score: number | null;
  status: string;
  question_created_at: string | null;
  last_activity_at: string | null;
  rejection_reason: string | null;
  challenge_id: string | null;
};

type Filter = { label: string; params: Record<string, string> };

const FILTERS: Filter[] = [
  { label: "All candidates", params: {} },
  { label: "Unanswered", params: { max_answers: "0" } },
  { label: "No accepted answer", params: { has_accepted_answer: "false" } },
  { label: "Difficulty 4+", params: { difficulty_min: "4" } },
  // Split apart: a question the filters threw out and one the user dismissed
  // are both `rejected`, but only one of them was a decision worth reviewing.
  { label: "Rejected", params: { status: "rejected", rejection_reason: "automatic" } },
  { label: "Dismissed", params: { status: "rejected", rejection_reason: "user_dismissed" } },
  { label: "Awaiting enrichment", params: { status: "enrichment_pending" } },
];

async function fetchQuestions(filter: Filter): Promise<QuestionRow[]> {
  const params = new URLSearchParams({ status: "candidate", limit: "60", ...filter.params });
  const response = await fetch(`/api/questions?${params}`);
  if (!response.ok) {
    throw new Error(`failed to load questions: ${response.status}`);
  }
  return response.json();
}

async function postTo(path: string): Promise<void> {
  const response = await fetch(path, { method: "POST" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `request failed: ${response.status}`);
  }
}

function relativeDate(value: string | null): string {
  if (!value) return "unknown";
  const days = Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

function QuestionCard({
  question,
  onPromote,
  onDismiss,
  onRestore,
  busy,
}: {
  question: QuestionRow;
  onPromote: (question: QuestionRow) => void;
  onDismiss: (question: QuestionRow) => void;
  onRestore: (question: QuestionRow) => void;
  busy: boolean;
}) {
  const match = question.candidate_score;
  const dismissed = question.rejection_reason === "user_dismissed";

  return (
    <div className={styles.qcard}>
      <div className={styles.qtitle}>{question.title ?? "Awaiting Stack Exchange metadata"}</div>

      {question.tags.length > 0 && (
        <div className={styles.qtagRow}>
          {question.tags.slice(0, 5).map((tag) => (
            <span key={tag} className={styles.qtag} style={{ background: colorForTopic(tag) }}>
              {tag}
            </span>
          ))}
        </div>
      )}

      <div className={styles.qstatRow}>
        <span>▲ {question.score ?? 0}</span>
        <span>
          {question.answer_count ?? 0} {question.answer_count === 1 ? "answer" : "answers"}
        </span>
        <span className={question.has_accepted_answer ? styles.qstatAccepted : styles.qstatNoAccepted}>
          {question.has_accepted_answer ? "✓ accepted" : "no accepted answer"}
        </span>
        {question.difficulty && <span>difficulty {question.difficulty}/5</span>}
      </div>

      <div className={styles.qdateRow}>
        Posted {relativeDate(question.question_created_at)} · last active{" "}
        {relativeDate(question.last_activity_at)}
      </div>

      {match !== null ? (
        <div className={styles.qscore}>
          <span>Match {Math.round(match)}%</span>
          <span className={styles.qscoreBar}>
            <span className={styles.qscoreFill} style={{ width: `${Math.min(100, match)}%` }} />
          </span>
        </div>
      ) : (
        <div className={styles.qscore}>
          <span>Not scored yet</span>
        </div>
      )}

      {question.rejection_reason && (
        <div className={styles.qdateRow}>
          {dismissed ? "Dismissed by you" : `Rejected: ${question.rejection_reason.replace(/_/g, " ")}`}
        </div>
      )}

      <a className={styles.qsoLink} href={question.url} target="_blank" rel="noopener noreferrer">
        Open on Stack Overflow ↗
      </a>

      <div className={styles.qactions}>
        {question.challenge_id ? (
          <Link href={`/challenge/${question.challenge_id}`} className={styles.qactionPrimary}>
            View challenge →
          </Link>
        ) : (
          <button
            type="button"
            className={styles.qactionPrimary}
            onClick={() => onPromote(question)}
            disabled={busy || question.status === "enrichment_pending"}
            // Enrichment fills in the body the curator needs; without it the
            // prompt would be empty and the call would be wasted.
            title={
              question.status === "enrichment_pending"
                ? "Enrich this question first — there is no content to build a challenge from yet."
                : "Generate a challenge from this question"
            }
          >
            Make this a challenge
          </button>
        )}
        {!question.challenge_id && (
          <InfoButton text="Generates a coding challenge from this question using your LLM provider. Costs one LLM call. Does not spend Yutori credit and does not start a new discovery run." />
        )}

        {dismissed ? (
          <>
            <button
              type="button"
              className={styles.qactionGhost}
              onClick={() => onRestore(question)}
              disabled={busy}
            >
              Restore
            </button>
            <InfoButton text="Returns this dismissed question to your active candidate pool." />
          </>
        ) : (
          <>
            <button
              type="button"
              className={styles.qactionDanger}
              onClick={() => onDismiss(question)}
              disabled={busy}
            >
              Dismiss
            </button>
            <InfoButton text="Removes this question from your candidate pool without deleting it, so it stops appearing here. It also won't be re-discovered by a future Scout run. You can bring it back anytime from the Dismissed filter." />
          </>
        )}
      </div>
    </div>
  );
}

export default function QuestionsPage() {
  const queryClient = useQueryClient();
  const [activeFilter, setActiveFilter] = useState(FILTERS[0]);
  const [running, setRunning] = useState<string | null>(null);
  const [stageMessage, setStageMessage] = useState<string | null>(null);
  const [pendingDismiss, setPendingDismiss] = useState<QuestionRow | null>(null);
  const [pendingPromote, setPendingPromote] = useState<QuestionRow | null>(null);
  // Null means "use the default". Kept per-dialog rather than persisted: the
  // format is a property of this generation, not a setting.
  const [promoteFormat, setPromoteFormat] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data: questions, isLoading } = useQuery({
    queryKey: ["questions", activeFilter.label],
    queryFn: () => fetchQuestions(activeFilter),
  });
  // Only needed when the dialog is open, but formats are a tiny list and
  // TanStack caches it across both pages that read it.
  const { data: formats } = useQuery({ queryKey: ["llm-formats"], queryFn: llmApi.formats });

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["questions"] });
    await queryClient.invalidateQueries({ queryKey: ["challenges"] });
  }

  // One LLM call, 15-30 seconds. Held the request open synchronously; now a
  // job, so the button returns at once and the result is asked for.
  const challengeJob = useJob(refresh);

  const promote = useMutation({
    mutationFn: (question: QuestionRow) => jobsApi.createChallenge(question.id, promoteFormat),
    onSuccess: (job) => {
      setPendingPromote(null);
      setPromoteFormat(null);
      setActionError(null);
      challengeJob.start(job);
    },
    onError: (error: Error) => {
      setPendingPromote(null);
      setActionError(error.message);
    },
  });

  const dismiss = useMutation({
    mutationFn: (question: QuestionRow) => postTo(`/api/questions/${question.id}/dismiss`),
    onSuccess: async () => {
      setPendingDismiss(null);
      setActionError(null);
      await refresh();
    },
    onError: (error: Error) => {
      setPendingDismiss(null);
      setActionError(error.message);
    },
  });

  const restore = useMutation({
    mutationFn: (question: QuestionRow) => postTo(`/api/questions/${question.id}/restore`),
    onSuccess: refresh,
    onError: (error: Error) => setActionError(error.message),
  });

  const busy = promote.isPending || dismiss.isPending || restore.isPending;

  async function runStage(path: string, label: string) {
    setRunning(label);
    setStageMessage(null);
    try {
      const response = await fetch(path, { method: "POST" });
      const body = await response.json();
      if (!response.ok) {
        setStageMessage(`${label} failed: ${JSON.stringify(body.detail ?? body)}`);
        return;
      }
      setStageMessage(
        `${label}: ${body.succeeded} succeeded, ${body.skipped} skipped, ${body.failed} failed`,
      );
      await queryClient.invalidateQueries({ queryKey: ["questions"] });
    } finally {
      setRunning(null);
    }
  }

  return (
    <main className={styles.page}>
      <div>
        <div className={styles.pageTitle}>Candidate pool</div>
        <div className={styles.pageSub}>
          Questions the Scout found, verified against Stack Overflow and scored against your profile.
        </div>
      </div>

      <nav className={styles.tabs}>
        {FILTERS.map((filter) => {
          const active = filter.label === activeFilter.label;
          return (
            <button
              key={filter.label}
              type="button"
              className={`${styles.tab} ${active ? styles.tabActive : ""}`}
              aria-current={active ? "page" : undefined}
              onClick={() => setActiveFilter(filter)}
            >
              {filter.label}
            </button>
          );
        })}
      </nav>

      {/* Manual stage triggers. These become scheduled jobs in M11; until then
          running the pipeline by hand is the only way to advance candidates. */}
      <div className={styles.actions}>
        <button
          className={styles.actionButton}
          onClick={() => runStage("/api/candidates/ingest", "Ingest")}
          disabled={running !== null}
          type="button"
        >
          {running === "Ingest" ? "Ingesting…" : "Ingest webhooks"}
        </button>
        <InfoButton text="Pulls in Yutori discovery results that arrived via webhook but haven't been added to your candidate pool yet." />
        <button
          className={styles.actionButton}
          onClick={() => runStage("/api/candidates/enrich", "Enrich")}
          disabled={running !== null}
          type="button"
        >
          {running === "Enrich" ? "Enriching…" : "Enrich pending"}
        </button>
        <InfoButton text="Fetches full Stack Overflow data (score, answers, tags, body) for candidates that currently only have bare metadata." />
        <button
          className={styles.actionButton}
          onClick={() => runStage("/api/candidates/rank", "Rank")}
          disabled={running !== null}
          type="button"
        >
          {running === "Rank" ? "Ranking…" : "Re-score"}
        </button>
        <InfoButton text="Re-runs scoring against your current profile for every candidate, picking up any recent changes to your topics or concepts." />
        {stageMessage && <span className={styles.stageResult}>{stageMessage}</span>}
      </div>

      {actionError && <div className={styles.stageResult}>{actionError}</div>}

      <JobStatus
        job={challengeJob.job}
        onCheck={() => challengeJob.check.mutate()}
        checking={challengeJob.check.isPending}
        estimate="around half a minute"
      >
        <span>Challenge ready — the card below now links to it.</span>
      </JobStatus>

      {isLoading ? (
        <div className={styles.empty}>Loading…</div>
      ) : !questions || questions.length === 0 ? (
        <div className={styles.empty}>
          <div className={styles.emptyTitle}>Nothing here yet</div>
          Once the Scout runs and its candidates are enriched, they&apos;ll appear here.
        </div>
      ) : (
        <div className={styles.grid}>
          {questions.map((question) => (
            <QuestionCard
              key={question.id}
              question={question}
              onPromote={setPendingPromote}
              onDismiss={setPendingDismiss}
              onRestore={(q) => restore.mutate(q)}
              busy={busy}
            />
          ))}
        </div>
      )}

      <ConfirmDialog
        open={pendingPromote !== null}
        title="Make this a challenge?"
        body={
          <>
            <p>
              A challenge will be generated from “{pendingPromote?.title ?? "this question"}”,
              whatever it scored.
            </p>
            {/* Named explicitly because the Scout's Run button spends $0.35 and
                this button looks similar — the difference is worth stating. */}
            <p>
              This costs one call to your LLM provider. It does not spend any Yutori credit and does
              not start a discovery run.
            </p>

            <label className={styles.dialogField}>
              <span className={styles.dialogLabel}>Format</span>
              <select
                className={styles.dialogSelect}
                value={promoteFormat ?? ""}
                onChange={(e) => setPromoteFormat(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">
                  Default — {formats?.active.name ?? "Standard"}
                </option>
                {(formats?.formats ?? [])
                  .filter((f) => !f.is_default)
                  .map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name} ({f.blocks.length} blocks)
                    </option>
                  ))}
              </select>
              <span className={styles.dialogHint}>
                Which blocks the challenge is built from. Manage these under LLM → Formats.
              </span>
            </label>
          </>
        }
        confirmLabel="Generate challenge"
        busy={promote.isPending}
        onConfirm={() => pendingPromote && promote.mutate(pendingPromote)}
        onCancel={() => {
          setPendingPromote(null);
          setPromoteFormat(null);
        }}
      />

      <ConfirmDialog
        open={pendingDismiss !== null}
        title="Dismiss this question?"
        body={
          <>
            <p>
              “{pendingDismiss?.title ?? "This question"}” will be taken out of your candidate pool.
            </p>
            <p>
              Nothing is deleted. The record is kept so a future run recognises the question and
              does not discover it again — and you can restore it from the Dismissed filter.
            </p>
          </>
        }
        confirmLabel="Dismiss"
        busy={dismiss.isPending}
        onConfirm={() => pendingDismiss && dismiss.mutate(pendingDismiss)}
        onCancel={() => setPendingDismiss(null)}
      />
    </main>
  );
}
