"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { ConfirmDialog } from "../confirm-dialog";
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
};

type SourceFilter = { label: string; value: "all" | "digest" | "manual" };

const FILTERS: SourceFilter[] = [
  { label: "All challenges", value: "all" },
  { label: "From digests", value: "digest" },
  { label: "Picked by you", value: "manual" },
];

async function fetchChallenges(source: string): Promise<ChallengeRow[]> {
  const response = await fetch(`/api/challenges?source=${source}&limit=200`);
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

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function ChallengesPage() {
  const queryClient = useQueryClient();
  const [activeFilter, setActiveFilter] = useState(FILTERS[0]);
  const [pendingDelete, setPendingDelete] = useState<ChallengeRow | null>(null);

  const {
    data: challenges,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["challenges", activeFilter.value],
    queryFn: () => fetchChallenges(activeFilter.value),
  });

  const remove = useMutation({
    mutationFn: async (challenge: ChallengeRow) => {
      const response = await fetch(`/api/challenges/${challenge.id}`, { method: "DELETE" });
      if (!response.ok) {
        throw new Error(`delete failed: ${response.status}`);
      }
    },
    onSuccess: async () => {
      setPendingDelete(null);
      // The dashboard reads the same rows through the digest it shows.
      await queryClient.invalidateQueries({ queryKey: ["challenges"] });
      await queryClient.invalidateQueries({ queryKey: ["digest"] });
      await queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
  });

  return (
    <main className={styles.page}>
      <div>
        <div className={styles.pageTitle}>Challenge history</div>
        <div className={styles.pageSub}>
          Every challenge ever generated, from any digest — plus the ones you picked yourself.
        </div>
      </div>

      <div className={styles.filters}>
        {FILTERS.map((filter) => (
          <button
            key={filter.value}
            type="button"
            className={`${styles.filterChip} ${filter.value === activeFilter.value ? styles.on : ""}`}
            onClick={() => setActiveFilter(filter)}
          >
            {filter.label}
          </button>
        ))}
      </div>

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
          <div className={styles.emptyTitle}>No challenges yet</div>
          Generate a digest, or pick a question yourself from the candidate pool.
        </div>
      ) : (
        <div className={styles.list}>
          {/* Status and Feedback, which the mockup also shows, arrive with M8 —
              there is no feedback table yet, so they are left out rather than
              rendered as placeholders. */}
          <div className={`${styles.row} ${styles.head}`}>
            <span>Date</span>
            <span>Question</span>
            <span>Difficulty</span>
            <span>Source</span>
            <span />
          </div>

          {challenges.map((challenge) => (
            <div key={challenge.id} className={styles.row}>
              <span className={styles.date}>{formatDate(challenge.created_at)}</span>
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
              <span
                className={`${styles.sourcePill} ${
                  challenge.source === "manual" ? styles.sourceManual : styles.sourceDigest
                }`}
              >
                {challenge.source === "manual" ? "Your pick" : "Digest"}
              </span>
              <button
                type="button"
                className={styles.deleteButton}
                onClick={() => setPendingDelete(challenge)}
                disabled={remove.isPending}
              >
                Delete
              </button>
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
