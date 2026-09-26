"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { json, send } from "@/lib/api";
import { jobsApi } from "@/lib/jobs-api";
import { llmApi } from "@/lib/llm-api";
import { ago } from "@/lib/scout-api";
import { JobStatus, useJob } from "../../job-status";
import { ConfirmDialog } from "../../confirm-dialog";
import { InfoButton } from "../../info-button";
import { Block, ProgressiveHints, SPECIAL_BLOCKS, indexBlocks } from "./blocks";
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
  /** How to draw each of those, in the same order. Absent on a backend older
   *  than ADR 0005, which is why the library is merged in behind it. */
  block_meta?: { key: string; label: string; kind: string; gated?: boolean }[];
  question_status: string | null;
  solved_at: string | null;
};

const post = (path: string) => json<unknown>(path, send("POST"));

export default function ChallengePage() {
  const params = useParams<{ id: string }>();
  const { data: challenge, isLoading, isError } = useQuery({
    queryKey: ["challenge", params.id],
    queryFn: () => json<ChallengeDetail>(`/api/challenges/${params.id}`),
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
  // Every block that exists. Needed for two things this challenge's own
  // metadata cannot supply: naming sections in a reformat result before they
  // have been generated, and the two core fields a pre-formats challenge
  // carries only in columns. Tiny and cached across every page that reads it.
  const { data: library } = useQuery({ queryKey: ["llm-blocks"], queryFn: llmApi.blocks });

  // The challenge's own metadata over the top of the whole library. Declared
  // before the early returns below, because hooks have to run unconditionally.
  const blockIndex = useMemo(
    () => indexBlocks(library?.blocks, challenge?.block_meta),
    [library, challenge],
  );
  const labelFor = useCallback(
    (key: string) => blockIndex.get(key)?.label ?? key,
    [blockIndex],
  );
  const isGated = useCallback(
    (key: string) => Boolean(blockIndex.get(key)?.gated),
    [blockIndex],
  );

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

  // One LLM call for the missing sections. A job now: the request used to be
  // held open for the whole generation.
  const topUp = useJob(async (job) => {
    const result = (job.result ?? {}) as {
      added?: string[];
      missing?: string[];
      dropped_links?: string[];
      format?: string;
      spent_call?: boolean;
    };
    const parts: string[] = [];
    if ((result.added?.length ?? 0) === 0 && (result.missing?.length ?? 0) === 0) {
      parts.push(`Already has everything ${result.format} asks for — no call was made.`);
    } else {
      const added = result.added ?? [];
      parts.push(
        `Added ${added.length} section${added.length === 1 ? "" : "s"}: ${added
          .map(labelFor)
          .join(", ")}.`,
      );
    }
    if ((result.missing?.length ?? 0) > 0) {
      parts.push(
        `The model did not produce ${(result.missing ?? [])
          .map(labelFor)
          .join(", ")} — press Add sections again to retry just those.`,
      );
    }
    const dropped = result.dropped_links ?? [];
    if (dropped.length > 0) {
      parts.push(
        `${dropped.length} link${dropped.length === 1 ? "" : "s"} did not resolve and ${
          dropped.length === 1 ? "was" : "were"
        } dropped.`,
      );
    }
    setNote(parts.join(" "));
    await queryClient.invalidateQueries({ queryKey: ["challenge"] });
    await queryClient.invalidateQueries({ queryKey: ["challenges"] });
  });

  const reformat = useMutation({
    mutationFn: () => jobsApi.reformat(params.id, chosenFormat),
    onSuccess: (job) => {
      setFormatOpen(false);
      setNote(null);
      topUp.start(job);
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

      <JobStatus
        job={topUp.job}
        onCheck={() => topUp.check.mutate()}
        checking={topUp.check.isPending}
        estimate="around half a minute"
      >
        <span>Sections added — they are on the page below.</span>
      </JobStatus>

      {challenge.question_status === "solved" && (
        <div className={styles.completedBanner}>
          <span>🎉 Completed {ago(challenge.solved_at)}</span>
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
            {challenge.question_created_at ? `posted ${ago(challenge.question_created_at)}` : "unknown date"}
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
        <Block key={key} meta={blockIndex.get(key)} value={content[key]} />
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
            gated.map((key) => <Block key={key} meta={blockIndex.get(key)} value={content[key]} />)
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
