"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Block, ProgressiveHints, SPECIAL_BLOCKS, isGated, labelFor } from "./blocks";
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
  /** Everything the format produced. Null on challenges made before formats. */
  content: Record<string, unknown> | null;
  format_name: string | null;
  /** Render order, resolved against the backend's block registry. */
  blocks: string[];
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

  // Progressive reveal, and a further gate on solution-adjacent blocks. All
  // client-side — everything is already loaded; the gate is self-discipline
  // rather than secrecy.
  const [allHintsShown, setAllHintsShown] = useState(false);
  const [stuckOpen, setStuckOpen] = useState(false);

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
  // Challenges made before formats existed have no `content`, so the six
  // original fields are assembled into the same shape and render identically.
  const content: Record<string, unknown> = challenge.content ?? {
    concepts: challenge.concepts,
    starting_direction: challenge.starting_direction,
  };
  const order = challenge.blocks?.length
    ? challenge.blocks
    : ["concepts", "starting_direction"];
  const renderable = order.filter((key) => !SPECIAL_BLOCKS.has(key));
  const ungated = renderable.filter((key) => !isGated(key));
  const gated = renderable.filter(isGated);
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

      {/* Ungated blocks, in the order the format defines. Concepts, Start here
          and anything the format added all come through here. */}
      {ungated.map((key) => (
        <Block key={key} blockKey={key} value={content[key]} />
      ))}

      <div className={styles.block}>
        <div className={styles.blockLabel}>Hints</div>
        <ProgressiveHints hints={hints} onAllRevealed={setAllHintsShown} />
      </div>

      {/* Solution-adjacent material sits behind one more click than the
          strongest hint, so it is never revealed by accident. */}
      {gated.length > 0 && (
        <div className={styles.block}>
          {!allHintsShown ? (
            <div className={styles.gatedNotice}>
              {gated.map(labelFor).join(" and ")} unlocks once you have read every hint.
            </div>
          ) : !stuckOpen ? (
            <button type="button" className={styles.revealBtn} onClick={() => setStuckOpen(true)}>
              I&apos;m stuck — show {gated.map(labelFor).join(" and ").toLowerCase()}
            </button>
          ) : (
            gated.map((key) => <Block key={key} blockKey={key} value={content[key]} />)
          )}
        </div>
      )}

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
