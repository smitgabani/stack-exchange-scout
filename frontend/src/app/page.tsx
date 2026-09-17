"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { colorForTopic } from "@/lib/topic-color";
import styles from "./dashboard.module.css";

type DigestSummary = {
  id: string;
  status: string;
  question_count: number;
  generated_at: string;
  sent_at: string | null;
};

type ChallengeSummary = {
  id: string;
  question_title: string | null;
  question_tags: string[];
  estimated_difficulty: number | null;
  problem_summary: string;
};

type DigestDetail = DigestSummary & { challenges: ChallengeSummary[] };
type Profile = { data: { topics: { name: string; weight: number }[]; digest: { frequency_days: number } } };

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status}`);
  }
  return response.json();
}

export default function DashboardPage() {
  const queryClient = useQueryClient();
  const [running, setRunning] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const { data: profile } = useQuery({ queryKey: ["profile"], queryFn: () => getJson<Profile>("/api/profile") });
  const { data: digests } = useQuery({
    queryKey: ["digests"],
    queryFn: () => getJson<DigestSummary[]>("/api/digests"),
  });

  const latest = digests?.[0];
  const { data: latestDetail } = useQuery({
    queryKey: ["digest", latest?.id],
    queryFn: () => getJson<DigestDetail>(`/api/digests/${latest!.id}`),
    enabled: Boolean(latest?.id),
  });

  async function run(path: string, label: string) {
    setRunning(label);
    setMessage(null);
    try {
      const response = await fetch(path, { method: "POST" });
      const body = await response.json();
      if (!response.ok) {
        setMessage(`${label} failed: ${typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)}`);
        return;
      }
      setMessage(`${label} complete`);
      await queryClient.invalidateQueries({ queryKey: ["digests"] });
      await queryClient.invalidateQueries({ queryKey: ["digest"] });
    } finally {
      setRunning(null);
    }
  }

  const topics = profile?.data.topics ?? [];
  const frequency = profile?.data.digest.frequency_days ?? 3;
  const challenges = latestDetail?.challenges ?? [];
  const isEmptyDigest = latest?.status === "empty";

  return (
    <main className={styles.page}>
      <section className={styles.hero}>
        <div className={styles.eyebrow}>Every {frequency} days</div>
        <h1 className={styles.heroTitle}>Your challenges are on their way</h1>
        <p className={styles.heroSub}>
          The Scout is discovering candidates on your current interval. Questions are enriched, scored,
          and the best of them become challenges.
        </p>
      </section>

      {topics.length > 0 && (
        <section>
          <h2 className={styles.sectionTitle}>Your interests</h2>
          <div className={styles.chipRow}>
            {topics.map((topic) => (
              <span key={topic.name} className={styles.chip}>
                <span className={styles.chipDot} style={{ background: colorForTopic(topic.name) }} />
                {topic.name} — {Math.round(topic.weight)}%
              </span>
            ))}
          </div>
        </section>
      )}

      <section>
        <h2 className={styles.sectionTitle}>Latest challenges</h2>

        {isEmptyDigest ? (
          <div className={styles.emptyDigest}>
            <div className={styles.emptyTitle}>No great challenges were found this cycle</div>
            <div className={styles.emptySub}>
              Nothing met the quality bar — that&apos;s fine, we don&apos;t lower it just to fill a digest.
              Your next challenge arrives in {frequency} days.
            </div>
          </div>
        ) : challenges.length > 0 ? (
          <div className={styles.digestGrid}>
            {challenges.map((challenge, index) => (
              <Link
                key={challenge.id}
                href={`/challenge/${challenge.id}`}
                className={`${styles.digestCard} ${styles[`tone${index % 3}`]}`}
              >
                <div className={styles.difficultyBadge}>
                  Difficulty {challenge.estimated_difficulty ?? "—"}/5
                </div>
                <div className={styles.cardTitle}>{challenge.question_title ?? "Challenge"}</div>
                <div className={styles.cardTags}>{challenge.question_tags.join(" · ")}</div>
              </Link>
            ))}
          </div>
        ) : (
          <p className={styles.message}>
            No digest yet. Generate one once candidates have been scored.
          </p>
        )}
      </section>

      {/* Manual triggers until M11 turns these into scheduled jobs. */}
      <section>
        <div className={styles.actions}>
          <button
            className={styles.button}
            onClick={() => run("/api/digest/generate", "Digest generation")}
            disabled={running !== null}
            type="button"
          >
            {running === "Digest generation" ? "Generating…" : "Generate digest"}
          </button>
          <button
            className={styles.secondaryButton}
            onClick={() => run("/api/digest/send", "Digest send")}
            disabled={running !== null}
            type="button"
          >
            {running === "Digest send" ? "Sending…" : "Send latest digest"}
          </button>
          {message && <span className={styles.message}>{message}</span>}
        </div>
      </section>

      {digests && digests.length > 0 && (
        <section>
          <h2 className={styles.sectionTitle}>Digest history</h2>
          <div className={styles.digestList}>
            {digests.map((digest) => (
              <div key={digest.id} className={styles.digestRow}>
                <span>
                  {new Date(digest.generated_at).toLocaleDateString()} · {digest.question_count} question
                  {digest.question_count === 1 ? "" : "s"}
                </span>
                <span className={styles.statusPill}>{digest.status}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
