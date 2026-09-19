"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

export type ScoutStatus = {
  configured: boolean;
  external_scout_id: string | null;
  sync_status: string | null;
  last_synced_at: string | null;
  last_sync_error: string | null;
  run_state: "idle" | "running";
  run_started_at: string | null;
  run_finished_at: string | null;
  external_status: string | null;
  next_run_at: string | null;
  update_count: number | null;
  last_update_at: string | null;
  rejection_reason: string | null;
  run_cost_usd: number;
};

// Slightly longer than the backend's run timeout, so polling outlives a run
// that is going to be finalized but not one that never will be.
const RUN_POLL_CEILING_MS = 50 * 60 * 1000;

async function fetchScout(): Promise<ScoutStatus> {
  const response = await fetch("/api/scout");
  if (!response.ok) {
    throw new Error(`scout status failed: ${response.status}`);
  }
  return response.json();
}

/**
 * One source of truth for Scout state, shared by the Scout page, the dashboard
 * and settings — all three can start a run, so all three must agree on whether
 * one is already in flight.
 *
 * Polling is opt-in and off by default. Every poll is a Vercel function
 * proxying to a scale-to-zero Fly machine, and this hook is mounted on three
 * pages — polling unconditionally meant a run stuck in `running` quietly
 * generated hundreds of billed requests from any open tab. Only the Scout
 * page, where someone is actually watching a run, asks for it.
 */
export function useScout({ poll = false }: { poll?: boolean } = {}) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["scout"],
    queryFn: fetchScout,
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!poll || data?.run_state !== "running") return false;
      // Give up once the run is past the point where the backend would have
      // timed it out anyway. Without this, a run that never finalizes polls
      // forever.
      if (data.run_started_at) {
        const elapsed = Date.now() - new Date(data.run_started_at).getTime();
        if (elapsed > RUN_POLL_CEILING_MS) return false;
      }
      return 30_000;
    },
  });

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["scout"] });
    await queryClient.invalidateQueries({ queryKey: ["scout-panel"] });
  };

  const run = useMutation({
    mutationFn: async () => {
      const response = await fetch("/api/scout/run", { method: "POST" });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Could not start a run");
      }
      return body as {
        mechanism: string | null;
        next_run_at: string | null;
        started_immediately: boolean | null;
      };
    },
    onSuccess: async (body) => {
      // Surfaced because Yutori documents neither behaviour: this is how we
      // find out whether restart fires a run or only resumes the schedule.
      setMessage(
        body.started_immediately === false
          ? `Started via ${body.mechanism}, but Yutori's next run is ${
              body.next_run_at ? new Date(body.next_run_at).toLocaleString() : "not scheduled"
            } — restart resumed the schedule rather than running now.`
          : `Run started via ${body.mechanism ?? "restart"}.`,
      );
      await invalidate();
    },
    onError: (error: Error) => setMessage(error.message),
  });

  const park = useMutation({
    mutationFn: async () => {
      const response = await fetch("/api/scout/park", { method: "POST" });
      return response.json();
    },
    onSuccess: async (body) => {
      setMessage(body.error ? `Park failed: ${body.error}` : "Scout parked.");
      await invalidate();
    },
  });

  const sync = useMutation({
    mutationFn: async () => {
      const response = await fetch("/api/scout/sync", { method: "POST" });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Sync failed");
      }
      return body;
    },
    onSuccess: async (body) => {
      setMessage(body.error ? `${body.action}: ${body.error}` : `Scout ${body.action}.`);
      await invalidate();
    },
    onError: (error: Error) => setMessage(error.message),
  });

  const pull = useMutation({
    mutationFn: async () => {
      const response = await fetch("/api/scout/pull", { method: "POST" });
      return response.json();
    },
    onSuccess: async (body) => {
      setMessage(
        body.error
          ? `Fetch failed: ${body.error}`
          : `Fetched ${body.fetched} update(s): ${body.ingested} new, ${body.duplicates} already had.`,
      );
      await invalidate();
    },
  });

  return {
    scout: query.data,
    isLoading: query.isLoading,
    isRunning: query.data?.run_state === "running",
    message,
    setMessage,
    run,
    park,
    sync,
    pull,
  };
}
