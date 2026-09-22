"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { colorForTopic } from "@/lib/topic-color";
import { jobsApi } from "@/lib/jobs-api";
import { JobStatus, useJob } from "./job-status";
import { RunScoutButton } from "./run-scout-button";
import { useScout } from "./use-scout";
import { InfoButton } from "./info-button";
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
  question_status: string | null;
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
  const { scout, isRunning, message: scoutMessage } = useScout();

  const { data: profile } = useQuery({ queryKey: ["profile"], queryFn: () => getJson<Profile>("/api/profile") });
  const { data: digests } = useQuery({
    queryKey: ["digests"],
    queryFn: () => getJson<DigestSummary[]>("/api/digests"),
  });
  // Cheap enough to always fetch: a small, indexed query, and it's what makes
  // the completed count feel present rather than something you have to go
  // looking for.
  const { data: completed } = useQuery({
    queryKey: ["challenges", "completed"],
    queryFn: () => getJson<ChallengeSummary[]>("/api/challenges?completion=completed&limit=200"),
  });
  const completedCount = completed?.length ?? 0;

  const latest = digests?.[0];
  const { data: latestDetail } = useQuery({
    queryKey: ["digest", latest?.id],
    queryFn: () => getJson<DigestDetail>(`/api/digests/${latest!.id}`),
    enabled: Boolean(latest?.id),
  });

  // Digest generation is up to ten LLM calls. Run inside the request it held
  // a Vercel function open for over a minute, billed by the second; it is a
  // background job now, and this page asks how it went only when told to.
  const digestJob = useJob(async () => {
    await queryClient.invalidateQueries({ queryKey: ["digests"] });
    await queryClient.invalidateQueries({ queryKey: ["digest"] });
    await queryClient.invalidateQueries({ queryKey: ["challenges"] });
  });

  const startDigest = useMutation({
    mutationFn: jobsApi.generateDigest,
    onSuccess: (job) => {
      setMessage(null);
      digestJob.start(job);
    },
    onError: (e: Error) => setMessage(e.message),
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
  // Completed challenges leave the working views the moment they're marked
  // done — they still exist, just under Challenges → Completed, so finishing
  // one shrinks the homepage instead of it accumulating solved cards forever.
  const challenges = (latestDetail?.challenges ?? []).filter((c) => c.question_status !== "solved");
  const isEmptyDigest = latest?.status === "empty";
  const parked =
    !scout?.configured || scout.external_status === "done" || scout.external_status === "paused";
  // Only claim a schedule when Yutori actually told us there is one — an
  // unknown status is not evidence that challenges are on their way.
  const scheduled = scout?.external_status === "active" && Boolean(scout.next_run_at);

  return (
    <main className={styles.page}>
      {/* Nothing is scheduled while the Scout is parked, so claiming challenges
          are "on their way" would be false. The hero says which it is. */}
      <section className={styles.hero}>
        <div className={styles.eyebrow}>
          {isRunning
            ? "Scout running now"
            : parked
              ? "On demand"
              : scheduled
                ? `Next run ${new Date(scout!.next_run_at!).toLocaleString()}`
                : "Discovery Scout"}
        </div>
        <h1 className={styles.heroTitle}>
          {isRunning
            ? "The Scout is searching"
            : scheduled
              ? "Your challenges are on their way"
              : "Ready when you are"}
        </h1>
        <p className={styles.heroSub}>
          {scheduled || isRunning
            ? "The Scout is discovering candidates. Questions are enriched, scored, and the best of them become challenges."
            : `The Scout runs when you ask it to. Start a run to find new questions, then enrich and score them into challenges. Digests are set to every ${frequency} days once scheduling exists.`}
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
        <div className={styles.sectionHeadRow}>
          <h2 className={styles.sectionTitle}>Latest challenges</h2>
          {completedCount > 0 && (
            <Link href="/challenges?view=completed" className={styles.completedLink}>
              🎉 {completedCount} completed — see them
            </Link>
          )}
        </div>

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
          <RunScoutButton className={styles.button} />
          <InfoButton text="Asks Yutori to search Stack Overflow for new questions matching your current topics. Costs about $0.35 per run. It does not run on a schedule — you have to start it here." />
          <button
            className={styles.secondaryButton}
            onClick={() => startDigest.mutate()}
            disabled={running !== null || startDigest.isPending}
            type="button"
          >
            {startDigest.isPending ? "Starting…" : "Generate digest"}
          </button>
          <InfoButton text='Builds a digest from your best-scored candidate questions and turns them into challenges. This does not send anything — use "Send latest digest" separately for that.' />
          <button
            className={styles.secondaryButton}
            onClick={() => run("/api/digest/send", "Digest send")}
            disabled={running !== null}
            type="button"
          >
            {running === "Digest send" ? "Sending…" : "Send latest digest"}
          </button>
          <InfoButton text='Emails the most recently generated digest to your inbox via Resend. This does not create a new digest first — run "Generate digest" beforehand if you want fresh challenges included.' />
          {message && <span className={styles.message}>{message}</span>}
          {scoutMessage && <span className={styles.message}>{scoutMessage}</span>}
        </div>

        <JobStatus
          job={digestJob.job}
          onCheck={() => digestJob.check.mutate()}
          checking={digestJob.check.isPending}
          estimate="a minute or two"
        >
          <span>
            Digest ready —{" "}
            {String((digestJob.job?.result as { question_count?: number })?.question_count ?? 0)}{" "}
            challenges. It is below.
          </span>
        </JobStatus>
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
