"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { llmApi } from "@/lib/llm-api";
import { ConfirmDialog } from "../../confirm-dialog";
import { InfoButton } from "../../info-button";
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
  digest_id: string | null;
  content: Record<string, unknown> | null;
  format_name: string | null;
  /** Render order, resolved against the backend's block registry. */
  blocks: string[];
  question_status: string | null;
  solved_at: string | null;
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

function solvedAgo(value: string | null): string {
  if (!value) return "";
  const days = Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  return `${Math.floor(days / 30)} months ago`;
}

async function post(path: string): Promise<void> {
  const response = await fetch(path, { method: "POST" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `request failed: ${response.status}`);
  }
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
  const [formatOpen, setFormatOpen] = useState(false);
  const [chosenFormat, setChosenFormat] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const { data: formats } = useQuery({ queryKey: ["llm-formats"], queryFn: llmApi.formats });

  async function refreshAfterStatusChange() {
    await queryClient.invalidateQueries({ queryKey: ["challenge"] });
    await queryClient.invalidateQueries({ queryKey: ["challenges"] });
    await queryClient.invalidateQueries({ queryKey: ["digest"] });
    await queryClient.invalidateQueries({ queryKey: ["questions"] });
  }

  const complete = useMutation({
    mutationFn: () => post(`/api/questions/${challenge!.question_id}/complete`),
    onSuccess: refreshAfterStatusChange,
    onError: (e: Error) => setNote(e.message),
  });

  const reopen = useMutation({
    mutationFn: () => post(`/api/questions/${challenge!.question_id}/reopen`),
    onSuccess: refreshAfterStatusChange,
    onError: (e: Error) => setNote(e.message),
  });

  const reformat = useMutation({
    mutationFn: () => llmApi.reformatChallenge(params.id, chosenFormat),
    onSuccess: async (result) => {
      setFormatOpen(false);
      // A short result has to explain itself: "I asked for nine and got two"
      // was previously something you had to work out from the page.
      const parts: string[] = [];
      if (result.added.length === 0 && result.missing.length === 0) {
        parts.push(`Already has everything ${result.format} asks for — no call was made.`);
      } else {
        parts.push(
          `Added ${result.added.length} section${result.added.length === 1 ? "" : "s"}: ${result.added
            .map(labelFor)
            .join(", ")}.`,
        );
      }
      if (result.missing.length > 0) {
        parts.push(
          `The model did not produce ${result.missing.map(labelFor).join(", ")} — press Add sections again to retry just those.`,
        );
      }
      if (result.dropped_links.length > 0) {
        parts.push(
          `${result.dropped_links.length} link${result.dropped_links.length === 1 ? "" : "s"} did not resolve and ${result.dropped_links.length === 1 ? "was" : "were"} dropped.`,
        );
      }
      setNote(parts.join(" "));
      await queryClient.invalidateQueries({ queryKey: ["challenge"] });
      await queryClient.invalidateQueries({ queryKey: ["challenges"] });
    },
    onError: (e: Error) => {
      setFormatOpen(false);
      setNote(e.message);
    },
  });

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

      <div className={styles.titleRow}>
        <h1 className={styles.title}>{challenge.question_title ?? "Challenge"}</h1>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <button type="button" className={styles.formatButton} onClick={() => setFormatOpen(true)}>
            {challenge.format_name ? `Format: ${challenge.format_name}` : "Add sections"}
          </button>
          <InfoButton text="Adds any blocks from the format you pick that this challenge doesn't already have. Sections you've already revealed, like hints, are left untouched. Costs one LLM call, or nothing if there's nothing new to add — and the challenge keeps its existing link." />
        </span>
      </div>

      {note && <div className={styles.notice}>{note}</div>}

      {challenge.question_status === "solved" && (
        <div className={styles.completedBanner}>
          <span>🎉 Completed {solvedAgo(challenge.solved_at)}</span>
          <button
            type="button"
            className={styles.reopenLink}
            onClick={() => reopen.mutate()}
            disabled={reopen.isPending}
          >
            Reopen
          </button>
        </div>
      )}

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

      {challenge.question_status !== "solved" && (
        <button
          type="button"
          className={styles.completeButton}
          onClick={() => complete.mutate()}
          disabled={complete.isPending}
        >
          {complete.isPending ? "Marking complete…" : "✓ Mark as complete"}
        </button>
      )}

      {challenge.question_url && <hr className={styles.hr} />}

      <ConfirmDialog
        open={formatOpen}
        title="Add sections to this challenge?"
        body={
          <>
            <p>
              Sections this challenge already has are left exactly as they are — including hints
              you have revealed. Only what the chosen format adds is generated.
            </p>
            <p>
              This costs <strong>one LLM call</strong>, or nothing at all if there is nothing to
              add. The challenge keeps its address, so any link to it keeps working.
            </p>
            {/* The archive and the inbox can diverge, and that is worth saying. */}
            {challenge.digest_id && (
              <p className={styles.warnText}>
                This challenge was part of a digest. If that digest was emailed to you, this page
                will no longer match what you received.
              </p>
            )}
            <label className={styles.dialogField}>
              <span className={styles.dialogLabel}>Format</span>
              <select
                className={styles.dialogSelect}
                value={chosenFormat ?? ""}
                onChange={(e) => setChosenFormat(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">Default — {formats?.active.name ?? "Standard"}</option>
                {(formats?.formats ?? [])
                  .filter((f) => !f.is_default)
                  .map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name} ({f.blocks.length} blocks)
                    </option>
                  ))}
              </select>
            </label>
          </>
        }
        confirmLabel="Add sections"
        busy={reformat.isPending}
        onConfirm={() => reformat.mutate()}
        onCancel={() => setFormatOpen(false)}
      />

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
