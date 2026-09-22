"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { type Job, jobsApi } from "@/lib/jobs-api";
import styles from "./job-status.module.css";

/**
 * "Started — check back when you think it's done."
 *
 * Deliberately not a progress bar. Polling on a timer means an open tab keeps
 * billing Vercel function time for a job it is only watching, and the previous
 * version of that mistake is what got the deployment paused. One request per
 * click, and an idle tab costs nothing.
 */

export function useJob(onFinished?: (job: Job) => void | Promise<void>) {
  const [job, setJob] = useState<Job | null>(null);

  const check = useMutation({
    mutationFn: () => jobsApi.get(job!.id),
    onSuccess: async (fresh) => {
      setJob(fresh);
      if (fresh.status === "succeeded" || fresh.status === "failed") {
        await onFinished?.(fresh);
      }
    },
  });

  return {
    job,
    start: setJob,
    clear: () => setJob(null),
    check,
  };
}

export function JobStatus({
  job,
  onCheck,
  checking,
  /** What this job is, for the waiting line: "This usually takes {estimate}." */
  estimate = "about a minute",
  children,
}: {
  job: Job | null;
  onCheck: () => void;
  checking: boolean;
  estimate?: string;
  children?: React.ReactNode;
}) {
  if (!job) return null;

  if (job.status === "failed") {
    return (
      <div className={`${styles.panel} ${styles.failed}`}>
        <strong>That didn&apos;t work.</strong> {job.error ?? "No reason was recorded."}
      </div>
    );
  }

  if (job.status === "succeeded") {
    return (
      <div className={`${styles.panel} ${styles.done}`}>
        {children ?? <span>Done.</span>}
      </div>
    );
  }

  return (
    <div className={styles.panel}>
      <div>
        Started. This usually takes {estimate} — nothing is lost if you navigate away.
      </div>
      <button type="button" className={styles.check} onClick={onCheck} disabled={checking}>
        {checking ? "Checking…" : "Check status"}
      </button>
    </div>
  );
}
