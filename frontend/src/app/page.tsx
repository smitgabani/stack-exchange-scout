"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { colorForTopic } from "@/lib/topic-color";
import { jobsApi } from "@/lib/jobs-api";
import { JobStatus, useJob } from "./job-status";
import { RunScoutButton } from "./run-scout-button";
import { usePrimaryScout } from "./use-primary-scout";
import { InfoButton } from "./info-button";
import styles from "./dashboard.module.css";

/**
 * The dashboard is organised around one question: what should I do now?
 *
 * The core loop of this app is solving a challenge. Everything else —
 * discovery, scoring, digests — exists to feed it. So the page leads with a
 * single challenge and a single action, shows progress second, and demotes
 * the machinery to the bottom where it is available but not in the way.
 *
 * Motivation here is deliberately honest: a streak that counts weeks rather
 * than days (so the digest schedule cannot break it), no countdown, no guilt.
 * A tool you use to learn should be one you want to open, not one you feel
 * obliged to.
 */

type Card = {
  id: string;
  question_title: string | null;
  question_tags: string[];
  estimated_difficulty: number | null;
  created_at: string | null;
};

type Dashboard = {
  next_challenge: Card | null;
  up_next: Card[];
  momentum: {
    solved_total: number;
    solved_this_week: number;
    week_streak: number;
    by_week: { week: string; count: number }[];
  };
  pipeline: {
    awaiting_enrichment: number;
    candidates: number;
    above_bar: number;
    challenges: number;
    solved: number;
    bar: number;
  };
  topics: { name: string; weight: number }[];
  digest: {
    frequency_days: number;
    latest: {
      id: string;
      status: string;
      question_count: number;
      generated_at: string | null;
      sent_at: string | null;
    } | null;
  };
  last_run: { at: string | null; cost_usd: number | null; questions_found: number | null } | null;
};

async function fetchDashboard(): Promise<Dashboard> {
  const response = await fetch("/api/dashboard");
  if (!response.ok) {
    // Vercel and Fly deploy separately. If this frontend lands first, the
    // endpoint does not exist yet — say that, rather than "loading" forever.
    throw new Error(
      response.status === 404
        ? "This page needs a newer backend than the one deployed — /dashboard returned 404."
        : `Could not load the dashboard (HTTP ${response.status}).`,
    );
  }
  return response.json();
}

function ago(value: string | null): string {
  if (!value) return "";
  const days = Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  return `${Math.floor(days / 30)} months ago`;
}

function difficulty(value: number | null): string {
  return value ? `Difficulty ${value}/5` : "Difficulty not rated";
}

export default function DashboardPage() {
  const queryClient = useQueryClient();
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const { definition, isRunning, costUsd, ambiguity } = usePrimaryScout();

  // One request for the whole page. Six separate fetches would each be a
  // Vercel function proxying to Fly, and the page could not render until the
  // slowest of them returned.
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: fetchDashboard,
  });

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    await queryClient.invalidateQueries({ queryKey: ["challenges"] });
    await queryClient.invalidateQueries({ queryKey: ["digests"] });
  }

  // Up to ten LLM calls, so a background job: the button returns at once and
  // the result is asked for, rather than holding a billed function open.
  const digestJob = useJob(refresh);
  const startDigest = useMutation({
    mutationFn: jobsApi.generateDigest,
    onSuccess: (job) => {
      setMessage(null);
      digestJob.start(job);
    },
    onError: (e: Error) => setMessage(e.message),
  });

  async function sendDigest() {
    setSending(true);
    setMessage(null);
    try {
      const response = await fetch("/api/digest/send", { method: "POST" });
      const body = await response.json();
      setMessage(
        response.ok
          ? "Sent — check your inbox."
          : `Could not send: ${typeof body.detail === "string" ? body.detail : "unknown error"}`,
      );
      await refresh();
    } finally {
      setSending(false);
    }
  }

  if (isError) {
    return (
      <main className={styles.page}>
        <div className={styles.loading}>{(error as Error).message}</div>
      </main>
    );
  }

  if (isLoading || !data) {
    return (
      <main className={styles.page}>
        <div className={styles.loading}>Loading…</div>
      </main>
    );
  }

  const { next_challenge: next, up_next, momentum, pipeline, topics, digest, last_run } = data;
  const peak = Math.max(...momentum.by_week.map((w) => w.count), 1);

  return (
    <main className={styles.page}>
      {/* ─── 1. Today ───────────────────────────────────────────────────
          One thing to do. When there is a challenge, that is it; when there
          is not, the block says what would produce one, so the page is never
          a dead end. */}
      {next ? (
        <section className={styles.today}>
          <div className={styles.eyebrow}>Your next challenge</div>
          <div className={styles.todayChallenge}>{next.question_title ?? "Untitled challenge"}</div>
          <div className={styles.todayMeta}>
            <span>{difficulty(next.estimated_difficulty)}</span>
            {next.question_tags.map((tag) => (
              <span key={tag} className={styles.todayTag}>
                {tag}
              </span>
            ))}
          </div>
          <div className={styles.todayActions}>
            <Link href={`/challenge/${next.id}`} className={styles.cta}>
              Start solving →
            </Link>
            {up_next.length > 0 && (
              <a href="#up-next" className={styles.ctaQuiet}>
                or pick another
              </a>
            )}
          </div>
        </section>
      ) : pipeline.above_bar > 0 ? (
        <section className={`${styles.today} ${styles.todayEmpty}`}>
          <div className={styles.eyebrow}>Nothing to solve yet</div>
          <h1 className={styles.todayTitle}>
            {pipeline.above_bar} question{pipeline.above_bar === 1 ? " is" : "s are"} ready to become
            challenges
          </h1>
          <div className={styles.todayActions}>
            <button
              type="button"
              className={styles.cta}
              onClick={() => startDigest.mutate()}
              disabled={startDigest.isPending}
            >
              {startDigest.isPending ? "Starting…" : "Make me a digest"}
            </button>
            <Link href="/questions" className={styles.ctaQuiet}>
              or choose one yourself →
            </Link>
          </div>
        </section>
      ) : (
        <section className={`${styles.today} ${styles.todayEmpty}`}>
          <div className={styles.eyebrow}>Nothing to solve yet</div>
          <h1 className={styles.todayTitle}>
            {pipeline.candidates > 0
              ? "Your candidates are below the bar"
              : "Let’s find you some questions"}
          </h1>
          <div className={styles.todayActions}>
            {definition ? (
              <RunScoutButton
                definitionId={definition.id}
                className={styles.cta}
                cost={costUsd}
                isRunning={isRunning}
              />
            ) : (
              <Link href="/yutori/scouts" className={styles.cta}>
                {ambiguity === "none" ? "Set up a scout →" : "Choose a scout →"}
              </Link>
            )}
            {pipeline.candidates > 0 && (
              <Link href="/questions" className={styles.ctaQuiet}>
                or browse the {pipeline.candidates} you have →
              </Link>
            )}
          </div>
        </section>
      )}

      <JobStatus
        job={digestJob.job}
        onCheck={() => digestJob.check.mutate()}
        checking={digestJob.check.isPending}
        estimate="a minute or two"
      >
        <span>
          Digest ready —{" "}
          {String((digestJob.job?.result as { question_count?: number })?.question_count ?? 0)}{" "}
          challenges waiting for you.
        </span>
      </JobStatus>

      {/* ─── 2. Momentum ────────────────────────────────────────────────
          Progress made visible. Weeks, not days — a daily streak would break
          on the digest schedule the user chose, and punish them for it. */}
      <section className={styles.momentum}>
        <div className={`${styles.stat} ${styles.statMint} ${styles.statTall}`}>
          <div className={styles.statLabel}>Week streak</div>
          <div className={styles.statValue}>{momentum.week_streak}</div>
          <div className={styles.statNote}>
            {momentum.week_streak === 0
              ? "Solve one this week to start one."
              : momentum.solved_this_week === 0
                ? "This week is still open — one solve keeps it going."
                : `Consecutive weeks with at least one solve.`}
          </div>
        </div>

        <div className={`${styles.stat} ${styles.statPeach}`}>
          <div className={styles.statLabel}>This week</div>
          <div className={styles.statValue}>{momentum.solved_this_week}</div>
          <div className={styles.statNote}>
            {momentum.solved_this_week === 1 ? "challenge solved" : "challenges solved"}
          </div>
        </div>

        <Link href="/challenges?view=completed" className={`${styles.stat} ${styles.statSoft}`}>
          <div className={styles.statLabel}>Solved, all time</div>
          <div className={styles.statValue}>{momentum.solved_total}</div>
          <div className={styles.spark} aria-label="Challenges solved per week, last 12 weeks">
            {momentum.by_week.map((week) => (
              <span
                key={week.week}
                className={`${styles.sparkBar} ${week.count > 0 ? styles.sparkBarOn : ""}`}
                style={{ height: `${Math.max((week.count / peak) * 100, 6)}%` }}
                title={`Week of ${week.week}: ${week.count}`}
              />
            ))}
          </div>
        </Link>
      </section>

      {/* ─── 3. Up next ─────────────────────────────────────────────────
          The rest of what is open. Staggered, per design.md §3. */}
      {up_next.length > 0 && (
        <section id="up-next">
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>Up next</h2>
            <Link href="/challenges" className={styles.sectionLink}>
              All challenges →
            </Link>
          </div>
          <div className={styles.upNext}>
            {up_next.map((card) => (
              <Link key={card.id} href={`/challenge/${card.id}`} className={styles.upNextCard}>
                <div className={styles.upNextTitle}>{card.question_title ?? "Untitled challenge"}</div>
                <div className={styles.upNextMeta}>
                  {difficulty(card.estimated_difficulty)}
                  {card.question_tags.length > 0 && ` · ${card.question_tags.join(" · ")}`}
                </div>
                <div className={styles.upNextMeta}>Added {ago(card.created_at)}</div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* ─── 4. Your pipeline ──────────────────────────────────────────
          The machinery, made legible. Without this, "why do I have nothing
          to solve?" has no answer on the page. */}
      <section>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>Your pipeline</h2>
          <Link href="/questions" className={styles.sectionLink}>
            Candidate pool →
          </Link>
        </div>
        {/* Two groups, not one funnel. The first is the pool as it stands
            now; the second is cumulative. Drawn as a single funnel they read
            as a bug — nine above the bar, then eighteen challenges — because
            they count different things over different spans of time. */}
        <div className={styles.funnel}>
          <div className={styles.funnelGroup}>
            <div className={styles.funnelGroupTitle}>In the pool now</div>
            {[
              { label: "Awaiting details", n: pipeline.awaiting_enrichment, tone: "" },
              { label: "Candidates", n: pipeline.candidates, tone: styles.funnelBarMid },
              { label: `Above the bar (${pipeline.bar})`, n: pipeline.above_bar, tone: styles.funnelBarInk },
            ].map((row, _i, all) => {
              const max = Math.max(...all.map((r) => r.n), 1);
              return (
                <div key={row.label} className={styles.funnelRow}>
                  <span>{row.label}</span>
                  <span
                    className={`${styles.funnelBar} ${row.tone}`}
                    style={{ width: `${Math.max((row.n / max) * 100, 1)}%` }}
                  />
                  <span className={styles.funnelCount}>{row.n}</span>
                </div>
              );
            })}
          </div>
          <div className={styles.funnelGroup}>
            <div className={styles.funnelGroupTitle}>All time</div>
            {[
              { label: "Challenges made", n: pipeline.challenges, tone: styles.funnelBarMid },
              { label: "Solved", n: pipeline.solved, tone: styles.funnelBarInk },
            ].map((row, _i, all) => {
              const max = Math.max(...all.map((r) => r.n), 1);
              return (
                <div key={row.label} className={styles.funnelRow}>
                  <span>{row.label}</span>
                  <span
                    className={`${styles.funnelBar} ${row.tone}`}
                    style={{ width: `${Math.max((row.n / max) * 100, 1)}%` }}
                  />
                  <span className={styles.funnelCount}>{row.n}</span>
                </div>
              );
            })}
          </div>
        </div>

        <p className={styles.funnelNote}>
          Questions are found by a scout, filled in from Stack Overflow, then scored against your
          topics. Only those scoring {pipeline.bar} or more go into a digest — the bar is not lowered
          to fill one.
        </p>
      </section>

      {/* ─── 5. Actions ────────────────────────────────────────────────
          The maintenance controls. Still here, no longer in the way. */}
      <section>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>Keep it going</h2>
        </div>
        <div className={styles.actions}>
          {definition ? (
            <>
              <RunScoutButton
                definitionId={definition.id}
                className={styles.button}
                cost={costUsd}
                isRunning={isRunning}
              />
              <InfoButton text="Asks Yutori to search Stack Overflow for new questions matching your current topics. Costs about $0.35 per run. It does not run on a schedule — you have to start it here." />
            </>
          ) : (
            <Link href="/yutori/scouts" className={styles.secondaryButton}>
              {ambiguity === "none" ? "Create a scout to get started →" : "Choose which scout to run →"}
            </Link>
          )}
          <button
            className={styles.secondaryButton}
            onClick={() => startDigest.mutate()}
            disabled={startDigest.isPending}
            type="button"
          >
            {startDigest.isPending ? "Starting…" : "Generate digest"}
          </button>
          <InfoButton text='Builds a digest from your best-scored candidate questions and turns them into challenges. This does not send anything — use "Send latest digest" separately for that.' />
          <button
            className={styles.secondaryButton}
            onClick={sendDigest}
            disabled={sending || !digest.latest}
            type="button"
          >
            {sending ? "Sending…" : "Send latest digest"}
          </button>
          <InfoButton text='Emails the most recently generated digest to your inbox via Resend. This does not create a new digest first — run "Generate digest" beforehand if you want fresh challenges included.' />
          {message && <span className={styles.message}>{message}</span>}
        </div>
      </section>

      {/* ─── 6. Context ────────────────────────────────────────────────── */}
      {topics.length > 0 && (
        <section>
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>Tuned to</h2>
            <Link href="/topics" className={styles.sectionLink}>
              Edit topics →
            </Link>
          </div>
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

      <div className={styles.footerRow}>
        <span>
          {digest.latest
            ? `Last digest ${ago(digest.latest.generated_at)} · ${digest.latest.question_count} question${
                digest.latest.question_count === 1 ? "" : "s"
              } · ${digest.latest.sent_at ? "sent" : digest.latest.status}`
            : "No digest yet"}
        </span>
        <span>
          {last_run
            ? `Last scout run ${ago(last_run.at)}${
                last_run.questions_found != null ? ` · ${last_run.questions_found} found` : ""
              }${last_run.cost_usd != null ? ` · $${Number(last_run.cost_usd).toFixed(2)}` : ""}`
            : "No scout run yet"}
        </span>
      </div>
    </main>
  );
}
