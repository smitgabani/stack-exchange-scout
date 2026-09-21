"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ConfirmDialog } from "../confirm-dialog";
import { InfoButton } from "../info-button";
import styles from "./challenges.module.css";

type ChallengeRow = {
  id: string;
  question_id: string;
  digest_id: string | null;
  source: "digest" | "manual";
  created_at: string | null;
  question_title: string | null;
  question_url: string | null;
  question_tags: string[];
  estimated_difficulty: number | null;
  question_status: string | null;
  solved_at: string | null;
};

type SourceFilter = { label: string; value: "all" | "digest" | "manual" };

const FILTERS: SourceFilter[] = [
  { label: "All challenges", value: "all" },
  { label: "From digests", value: "digest" },
  { label: "Picked by you", value: "manual" },
];

async function fetchChallenges(source: string, completion: string): Promise<ChallengeRow[]> {
  const response = await fetch(`/api/challenges?source=${source}&completion=${completion}&limit=200`);
  if (!response.ok) {
    // A 404 here means the backend predates this page rather than that the
    // list is empty — worth saying, because the two look identical otherwise.
    if (response.status === 404) {
      throw new Error(
        "This page needs a newer backend than the one currently deployed — /challenges returned 404.",
      );
    }
    throw new Error(`Could not load challenges (HTTP ${response.status}).`);
  }
  return response.json();
}

async function post(path: string): Promise<void> {
  const response = await fetch(path, { method: "POST" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `request failed: ${response.status}`);
  }
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function timeAgo(value: string | null): string {
  if (!value) return "";
  const days = Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

export default function ChallengesPage() {
  // useSearchParams bails a prerendered route to client rendering up to the
  // nearest Suspense boundary, so the part of the page that reads it is
  // split out rather than left at the top level.
  return (
    <Suspense fallback={<main className={styles.page}>Loading…</main>}>
      <ChallengesPageInner />
    </Suspense>
  );
}

function ChallengesPageInner() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  // Completion is a separate axis from source: "which challenges came from
  // where" and "which are done" are independent questions, and the tab bar
  // asks the second one directly rather than nesting it inside the first.
  // The dashboard's completed-count link deep-links here with ?view=completed.
  const [showCompleted, setShowCompleted] = useState(
    () => searchParams.get("view") === "completed",
  );
  const [activeFilter, setActiveFilter] = useState(FILTERS[0]);
  const [pendingDelete, setPendingDelete] = useState<ChallengeRow | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const completion = showCompleted ? "completed" : "active";
  const {
    data: challenges,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["challenges", activeFilter.value, completion],
    queryFn: () => fetchChallenges(activeFilter.value, completion),
  });

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["challenges"] });
    // The dashboard reads the same rows through the digest it shows.
    await queryClient.invalidateQueries({ queryKey: ["digest"] });
    await queryClient.invalidateQueries({ queryKey: ["questions"] });
  }

  const remove = useMutation({
    mutationFn: async (challenge: ChallengeRow) => {
      const response = await fetch(`/api/challenges/${challenge.id}`, { method: "DELETE" });
      if (!response.ok) {
        throw new Error(`delete failed: ${response.status}`);
      }
    },
    onSuccess: async () => {
      setPendingDelete(null);
      await refresh();
    },
  });

  const complete = useMutation({
    mutationFn: (challenge: ChallengeRow) => post(`/api/questions/${challenge.question_id}/complete`),
    onSuccess: refresh,
    onError: (e: Error) => setActionError(e.message),
  });

  const reopen = useMutation({
    mutationFn: (challenge: ChallengeRow) => post(`/api/questions/${challenge.question_id}/reopen`),
    onSuccess: refresh,
    onError: (e: Error) => setActionError(e.message),
  });

  return (
    <main className={styles.page}>
      <div>
        <div className={styles.pageTitle}>{showCompleted ? "Completed challenges" : "Challenge history"}</div>
        <div className={styles.pageSub}>
          {showCompleted
            ? "Every challenge you've finished. Nothing here is deleted — it's kept exactly so you can look back at it."
            : "Every challenge ever generated, from any digest — plus the ones you picked yourself."}
        </div>
      </div>

      {/* The motivational element the user asked for: a plain count, not a
          streak or a badge system — those need day-boundary and timezone
          logic worth its own design pass, not bolted on here. */}
      {showCompleted && challenges && challenges.length > 0 && (
        <div className={styles.completedBanner}>
          🎉 You&apos;ve completed {challenges.length} challenge{challenges.length === 1 ? "" : "s"}.
        </div>
      )}

      <div className={styles.filters}>
        {!showCompleted &&
          FILTERS.map((filter) => (
            <button
              key={filter.value}
              type="button"
              className={`${styles.filterChip} ${filter.value === activeFilter.value ? styles.on : ""}`}
              onClick={() => setActiveFilter(filter)}
            >
              {filter.label}
            </button>
          ))}
        <button
          type="button"
          className={`${styles.filterChip} ${styles.completedChip} ${showCompleted ? styles.on : ""}`}
          onClick={() => setShowCompleted((v) => !v)}
        >
          {showCompleted ? "← Back to active" : "✓ Completed"}
        </button>
      </div>

      {actionError && <div className={styles.message}>{actionError}</div>}

      {isLoading ? (
        <div className={styles.empty}>Loading…</div>
      ) : isError ? (
        /* Distinct from the empty state on purpose: "we could not ask" and
           "the answer was none" are different facts, and showing the second
           when the first is true sends you looking in the wrong place. */
        <div className={styles.empty}>
          <div className={styles.emptyTitle}>Could not load your challenges</div>
          <div className={styles.warning}>{(error as Error).message}</div>
        </div>
      ) : !challenges || challenges.length === 0 ? (
        <div className={styles.empty}>
          <div className={styles.emptyTitle}>
            {showCompleted ? "Nothing completed yet" : "No challenges yet"}
          </div>
          {showCompleted
            ? "Solve one and mark it complete — it'll show up here."
            : "Generate a digest, or pick a question yourself from the candidate pool."}
        </div>
      ) : (
        <div className={styles.list}>
          {/* Feedback, which the mockup also shows, arrives with M8 — there is
              no feedback table yet, so it is left out rather than stubbed. */}
          <div className={`${styles.row} ${styles.head}`}>
            <span>{showCompleted ? "Completed" : "Date"}</span>
            <span>Question</span>
            <span>Difficulty</span>
            <span>{showCompleted ? "" : "Source"}</span>
            <span />
          </div>

          {challenges.map((challenge) => (
            <div key={challenge.id} className={styles.row}>
              <span className={styles.date}>
                {showCompleted ? timeAgo(challenge.solved_at) : formatDate(challenge.created_at)}
              </span>
              <span>
                <Link href={`/challenge/${challenge.id}`} className={styles.qtitle}>
                  {challenge.question_title ?? "Untitled question"}
                </Link>
                {challenge.question_tags.length > 0 && (
                  <div className={styles.qtags}>{challenge.question_tags.slice(0, 4).join(" · ")}</div>
                )}
              </span>
              <span className={styles.diff}>
                {challenge.estimated_difficulty ? `${challenge.estimated_difficulty}/5` : "—"}
              </span>
              <span>
                {!showCompleted && (
                  <span
                    className={`${styles.sourcePill} ${
                      challenge.source === "manual" ? styles.sourceManual : styles.sourceDigest
                    }`}
                  >
                    {challenge.source === "manual" ? "Your pick" : "Digest"}
                  </span>
                )}
              </span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                {showCompleted ? (
                  <button
                    type="button"
                    className={styles.reopenButton}
                    onClick={() => reopen.mutate(challenge)}
                    disabled={reopen.isPending}
                  >
                    Reopen
                  </button>
                ) : (
                  <button
                    type="button"
                    className={styles.completeButton}
                    onClick={() => complete.mutate(challenge)}
                    disabled={complete.isPending}
                  >
                    ✓ Mark complete
                  </button>
                )}
                <button
                  type="button"
                  className={styles.deleteButton}
                  onClick={() => setPendingDelete(challenge)}
                  disabled={remove.isPending}
                >
                  Delete
                </button>
                <InfoButton text="Permanently deletes this challenge. The underlying question stays in your candidate pool and can be turned into a new challenge again later. If this challenge was emailed to you as part of a digest, that email's link will stop working." />
              </span>
            </div>
          ))}
        </div>
      )}

      {remove.isError && (
        <div className={styles.message}>That challenge could not be deleted. Try again.</div>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete this challenge?"
        body={
          <>
            <p>
              “{pendingDelete?.question_title ?? "This challenge"}” will be deleted. The question
              itself stays in your pool, and the digest it belonged to is unaffected.
            </p>
            {/* The user asked to be warned about this specifically. */}
            {pendingDelete?.source === "digest" && (
              <p className={styles.warning}>
                This challenge was part of a digest. If that digest was emailed to you, the link to
                it in your inbox will stop working.
              </p>
            )}
          </>
        }
        confirmLabel="Delete challenge"
        busy={remove.isPending}
        onConfirm={() => pendingDelete && remove.mutate(pendingDelete)}
        onCancel={() => setPendingDelete(null)}
      />
    </main>
  );
}
