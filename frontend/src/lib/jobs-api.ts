/**
 * Long jobs: start one, then ask how it went.
 *
 * Generating a digest is up to ten LLM calls. Done synchronously it held an
 * HTTP request — and the Vercel function proxying it — for over a minute,
 * which is billed by the second and is what paused the deployment.
 *
 * Nothing here polls on a timer. The user presses "Check status" when they
 * think it is ready, so an idle tab costs nothing at all.
 */

import { json, send } from "./api";

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export type Job = {
  id: string;
  kind: string;
  status: JobStatus;
  /** What the synchronous endpoint would have returned. Null until finished. */
  result: Record<string, unknown> | null;
  /** Why it failed, in words meant for the reader. */
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
};

const post = (path: string, body?: unknown) => json<Job>(path, send("POST", body));

export const jobsApi = {
  generateDigest: () => post("/api/jobs/digest-generate"),

  createChallenge: (questionId: string, formatId?: number | null) =>
    post("/api/jobs/challenge-create", { question_id: questionId, format_id: formatId ?? null }),

  reformat: (challengeId: string, formatId?: number | null) =>
    post("/api/jobs/reformat", { challenge_id: challengeId, format_id: formatId ?? null }),

  test: (questionId: string, formatId?: number | null) =>
    post("/api/jobs/llm-test", { question_id: questionId, format_id: formatId ?? null }),

  get: (jobId: string) => json<Job>(`/api/jobs/${jobId}`),
};
