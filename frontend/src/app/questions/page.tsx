"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
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
};

type Filter = { label: string; params: Record<string, string> };

const FILTERS: Filter[] = [
  { label: "All candidates", params: {} },
  { label: "Unanswered", params: { max_answers: "0" } },
  { label: "No accepted answer", params: { has_accepted_answer: "false" } },
  { label: "Difficulty 4+", params: { difficulty_min: "4" } },
  { label: "Rejected", params: { status: "rejected" } },
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

function relativeDate(value: string | null): string {
  if (!value) return "unknown";
  const days = Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

function QuestionCard({ question }: { question: QuestionRow }) {
  const match = question.candidate_score;

  return (
    <div className={styles.qcard}>
      <div className={styles.qtitle}>{question.title ?? "Awaiting Stack Exchange metadata"}</div>

      {question.tags.length > 0 && (
        <div className={styles.qtagRow}>
          {question.tags.slice(0, 5).map((tag) => (
            <span key={tag} className={styles.qtag}>
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
        <div className={styles.qdateRow}>Rejected: {question.rejection_reason.replace(/_/g, " ")}</div>
      )}

      <a className={styles.qsoLink} href={question.url} target="_blank" rel="noopener noreferrer">
        Open on Stack Overflow ↗
      </a>
    </div>
  );
}

export default function QuestionsPage() {
  const queryClient = useQueryClient();
  const [activeFilter, setActiveFilter] = useState(FILTERS[0]);
  const [running, setRunning] = useState<string | null>(null);
  const [stageMessage, setStageMessage] = useState<string | null>(null);

  const { data: questions, isLoading } = useQuery({
    queryKey: ["questions", activeFilter.label],
    queryFn: () => fetchQuestions(activeFilter),
  });

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
        <button
          className={styles.actionButton}
          onClick={() => runStage("/api/candidates/enrich", "Enrich")}
          disabled={running !== null}
          type="button"
        >
          {running === "Enrich" ? "Enriching…" : "Enrich pending"}
        </button>
        <button
          className={styles.actionButton}
          onClick={() => runStage("/api/candidates/rank", "Rank")}
          disabled={running !== null}
          type="button"
        >
          {running === "Rank" ? "Ranking…" : "Re-score"}
        </button>
        {stageMessage && <span className={styles.stageResult}>{stageMessage}</span>}
      </div>

      <div className={styles.filters}>
        {FILTERS.map((filter) => (
          <button
            key={filter.label}
            type="button"
            className={`${styles.filterChip} ${filter.label === activeFilter.label ? styles.on : ""}`}
            onClick={() => setActiveFilter(filter)}
          >
            {filter.label}
          </button>
        ))}
      </div>

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
            <QuestionCard key={question.id} question={question} />
          ))}
        </div>
      )}
    </main>
  );
}
