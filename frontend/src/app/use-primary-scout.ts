"use client";

import { useQuery } from "@tanstack/react-query";
import { type Definition, scoutApi } from "@/lib/scout-api";

/**
 * Which scout definition "Find new questions" on the dashboard runs.
 *
 * Replaces the legacy singleton `scouts` row (`/scout`, `useScout`), which
 * predates multi-account entirely — its own model docstring called it "the
 * single active Yutori Scout for the whole app." `scout_definitions` is the
 * account-aware replacement (ADR 0004), but nothing on the dashboard read
 * from it; this is that connection.
 *
 * Most installs have exactly one ready definition — M12 migrated the one
 * legacy Scout row into exactly one on introduction — so the common case is
 * silent and automatic. Zero or several are both real states the button has
 * to say something honest about rather than guessing.
 */
export function usePrimaryScout() {
  const { data, isLoading } = useQuery({
    queryKey: ["definitions"],
    queryFn: () => scoutApi.listDefinitions(),
  });

  const ready = (data?.definitions ?? []).filter((d) => d.status !== "archived");
  const definition: Definition | null = ready.length === 1 ? ready[0] : null;
  const isRunning = definition?.stats?.last_status === "running";

  return {
    isLoading,
    definition,
    isRunning,
    costUsd: data?.run_cost_usd ?? 0.35,
    monitorInterval: data?.monitor_interval_seconds ?? 30 * 86400,
    /** Why there is no single definition to run, when there isn't one. */
    ambiguity:
      ready.length === 0 ? ("none" as const) : ready.length > 1 ? ("many" as const) : null,
  };
}
