"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  type LiveMonitorConflict,
  every,
  liveMonitorConflict,
  money,
  monthlyCost,
  scoutApi,
} from "@/lib/scout-api";
import { ConfirmDialog } from "./confirm-dialog";
import { LiveMonitorDialog } from "./live-monitor-dialog";
import styles from "./run-scout-button.module.css";

export type RunMode = "research" | "scout";

/**
 * The one button in the app that spends money, so it always confirms first and
 * always names the price. The figure comes from the API rather than from copy
 * here, so it can't drift from `settings.yutori_run_cost_usd`.
 *
 * The dialog also picks the primitive (ADR 0004). Research is the default
 * because it is the one that actually runs when asked — restart was measured
 * not to — and because its result can be polled back if the webhook is missed.
 *
 * Runs a specific scout definition (`POST /scout-definitions/{id}/run`) rather
 * than the legacy singleton `/scout/run` — the caller resolves *which*
 * definition via `usePrimaryScout`, since that answer depends on how many
 * scouts exist and this component has no business guessing.
 *
 * Scout mode starts a *monitor*, which keeps running and billing on its own
 * interval, so the dialog prices it per month, not per run. If the scout
 * already has one, the run is refused and `LiveMonitorDialog` offers to
 * replace it rather than silently adding a second.
 */
export function RunScoutButton({
  definitionId,
  className,
  label = "Find new questions",
  cost = 0.35,
  monitorInterval = 30 * 86400,
  isRunning = false,
  allowModeChoice = true,
}: {
  definitionId: string;
  className?: string;
  label?: string;
  cost?: number;
  /** How often a monitor started now would run, from the API. */
  monitorInterval?: number;
  isRunning?: boolean;
  allowModeChoice?: boolean;
}) {
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [mode, setMode] = useState<RunMode>("research");
  const [conflict, setConflict] = useState<LiveMonitorConflict | null>(null);

  const run = useMutation({
    mutationFn: (args: { mode: RunMode; replace?: boolean }) =>
      scoutApi.runDefinition(definitionId, args.mode, { replace: args.replace }),
    onSuccess: async () => {
      setConflict(null);
      await queryClient.invalidateQueries({ queryKey: ["definitions"] });
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      await queryClient.invalidateQueries({ queryKey: ["monitors"] });
    },
    onError: (error) => setConflict(liveMonitorConflict(error)),
  });

  // The free alternative to replacing: push the scout's saved settings to
  // the monitor that's already running.
  const apply = useMutation({
    mutationFn: (instanceId: string) => scoutApi.applyToMonitor(instanceId),
    onSuccess: async () => {
      setConflict(null);
      run.reset();
      await queryClient.invalidateQueries({ queryKey: ["monitors"] });
    },
  });

  return (
    <>
      <button
        type="button"
        className={className}
        disabled={isRunning || run.isPending}
        onClick={() => setAsking(true)}
      >
        {isRunning ? "Scout running…" : label}
      </button>
      {run.isError && !conflict && (
        <span className={styles.error}>{(run.error as Error).message}</span>
      )}
      <ConfirmDialog
        open={asking}
        title="Start a discovery run?"
        body={
          <>
            <p>
              This asks Yutori to search Stack Overflow now, using your current
              topics. It costs about <strong>${cost.toFixed(2)}</strong>.
            </p>
            {allowModeChoice && (
              <div className={styles.modes}>
                <label className={`${styles.mode} ${mode === "research" ? styles.on : ""}`}>
                  <input
                    type="radio"
                    name="run-mode"
                    value="research"
                    checked={mode === "research"}
                    onChange={() => setMode("research")}
                  />
                  <span>
                    <strong>Research task</strong> — one-shot. Runs immediately and
                    leaves nothing behind. Recommended.
                  </span>
                </label>
                <label className={`${styles.mode} ${mode === "scout" ? styles.on : ""}`}>
                  <input
                    type="radio"
                    name="run-mode"
                    value="scout"
                    checked={mode === "scout"}
                    onChange={() => setMode("scout")}
                  />
                  <span>
                    <strong>Scout monitor</strong> — runs now, then again{" "}
                    {every(monitorInterval)} on its own until you stop it: about{" "}
                    {money(monthlyCost(monitorInterval, cost))} a month.
                  </span>
                </label>
              </div>
            )}
          </>
        }
        confirmLabel={allowModeChoice && mode === "scout" ? "Start monitor" : "Run now"}
        busy={run.isPending}
        onCancel={() => setAsking(false)}
        onConfirm={() => {
          setAsking(false);
          run.mutate({ mode: allowModeChoice ? mode : "research" });
        }}
      />
      {apply.isError && <span className={styles.error}>{(apply.error as Error).message}</span>}
      {apply.isSuccess && (
        <span className={styles.error} style={{ color: "var(--success)" }}>
          Settings applied to the live monitor — free, no new run.
        </span>
      )}
      <LiveMonitorDialog
        conflict={conflict}
        busy={run.isPending || apply.isPending}
        onApply={() => conflict && apply.mutate(conflict.monitor.id)}
        onKeep={() => {
          setConflict(null);
          run.reset();
        }}
        onReplace={() => run.mutate({ mode: "scout", replace: true })}
      />
    </>
  );
}
