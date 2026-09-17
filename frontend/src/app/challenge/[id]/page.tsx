"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import styles from "./challenge.module.css";

type Hint = { label: string; text: string };

type ChallengeDetail = {
  id: string;
  question_id: string;
  question_title: string | null;
  question_url: string | null;
  question_tags: string[];
  answer_count: number | null;
  has_accepted_answer: boolean;
  question_created_at: string | null;
  problem_summary: string;
  why_interesting: string;
  concepts: string[];
  starting_direction: string;
  hints: Hint[];
  estimated_difficulty: number | null;
};

async function fetchChallenge(id: string): Promise<ChallengeDetail> {
  const response = await fetch(`/api/challenges/${id}`);
  if (!response.ok) {
    throw new Error(`failed to load challenge: ${response.status}`);
  }
  return response.json();
}

function postedAgo(value: string | null): string {
  if (!value) return "unknown date";
  const days = Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000);
  if (days <= 0) return "posted today";
  if (days === 1) return "posted yesterday";
  if (days < 30) return `posted ${days} days ago`;
  return `posted ${Math.floor(days / 30)} months ago`;
}

export default function ChallengePage() {
  const params = useParams<{ id: string }>();
  const { data: challenge, isLoading, isError } = useQuery({
    queryKey: ["challenge", params.id],
    queryFn: () => fetchChallenge(params.id),
  });

  // Progressive reveal: one hint per click, no collapsing back. Purely
  // client-side — all three hints are already loaded, the gate is a matter of
  // self-discipline rather than secrecy.
  const [revealed, setRevealed] = useState(0);

  if (isLoading) {
    return <main className={styles.page}><div className={styles.notice}>Loading…</div></main>;
  }
  if (isError || !challenge) {
    return (
      <main className={styles.page}>
        <div className={styles.notice}>That challenge could not be found.</div>
      </main>
    );
  }

  const hints = challenge.hints ?? [];
  const revealedHints = hints.slice(0, revealed);
  const answerText =
    challenge.answer_count === 1 ? "1 answer" : `${challenge.answer_count ?? 0} answers`;

  return (
    <main className={styles.page}>
      <Link className={styles.back} href="/">
        ← Back to dashboard
      </Link>

      <h1 className={styles.title}>{challenge.question_title ?? "Challenge"}</h1>

      <div className={styles.headerGrid}>
        <div className={styles.whyCard}>
          <div className={styles.cardLabel}>Why this was selected</div>
          <div className={styles.cardBody}>{challenge.why_interesting}</div>
        </div>
        <div className={styles.metaCard}>
          <div className={styles.cardLabel}>At a glance</div>
          <div className={styles.diffRow}>
            <span className={styles.difficultyNumber}>{challenge.estimated_difficulty ?? "—"}</span>
            <span className={styles.difficultySuffix}>/ 5 difficulty</span>
          </div>
          <div className={styles.chipRow}>
            {challenge.question_tags.map((tag) => (
              <span key={tag} className={styles.chipTag}>
                {tag}
              </span>
            ))}
          </div>
          <div className={styles.metaLine}>
            {answerText} · {challenge.has_accepted_answer ? "accepted answer" : "no accepted answer"} ·{" "}
            {postedAgo(challenge.question_created_at)}
          </div>
        </div>
      </div>

      <div className={styles.problemBlock}>
        <div className={styles.problemLabel}>Problem</div>
        <div className={styles.problemText}>{challenge.problem_summary}</div>
      </div>

      <div className={styles.block}>
        <div className={styles.blockLabel}>Concepts</div>
        <div className={styles.chipRow}>
          {challenge.concepts.map((concept) => (
            <span key={concept} className={styles.conceptChip}>
              {concept}
            </span>
          ))}
        </div>
      </div>

      <div className={styles.block}>
        <div className={styles.blockLabel}>Start here</div>
        <div className={styles.blockBody}>{challenge.starting_direction}</div>
      </div>

      <div className={styles.block}>
        <div className={styles.blockLabel}>Hints</div>
        <div className={styles.hints}>
          {revealedHints.map((hint) => (
            <div key={hint.label} className={styles.hintItem}>
              <div className={styles.hintLabel}>{hint.label}</div>
              <div className={styles.hintText}>{hint.text}</div>
            </div>
          ))}
          {revealed < hints.length && (
            <button
              type="button"
              className={styles.revealBtn}
              onClick={() => setRevealed((count) => Math.min(hints.length, count + 1))}
            >
              Show hint {revealed + 1}
            </button>
          )}
        </div>
      </div>

      {challenge.question_url && <hr className={styles.hr} />}

      {challenge.question_url && (
        <a
          className={styles.soButton}
          href={challenge.question_url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Open on Stack Overflow ↗
        </a>
      )}
    </main>
  );
}
