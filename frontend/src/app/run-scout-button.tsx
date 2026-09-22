"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { scoutApi } from "@/lib/scout-api";
import { ConfirmDialog } from "./confirm-dialog";
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
 */
export function RunScoutButton({
  definitionId,
  className,
  label = "Find new questions",
  cost = 0.35,
  isRunning = false,
  allowModeChoice = true,
}: {
  definitionId: string;
  className?: string;
  label?: string;
  cost?: number;
  isRunning?: boolean;
  allowModeChoice?: boolean;
}) {
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [mode, setMode] = useState<RunMode>("research");

  const run = useMutation({
    mutationFn: (m: RunMode) => scoutApi.runDefinition(definitionId, m),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["definitions"] });
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
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
      {run.isError && (
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
                    <strong>Scout</strong> — the long-lived monitor. Restarting it was
                    measured not to trigger a run, so this may cost $
                    {cost.toFixed(2)} and produce nothing.
                  </span>
                </label>
              </div>
            )}
          </>
        }
        confirmLabel="Run now"
        busy={run.isPending}
        onCancel={() => setAsking(false)}
        onConfirm={() => {
          setAsking(false);
          run.mutate(allowModeChoice ? mode : "research");
        }}
      />
    </>
  );
}
