"use client";

import { useState } from "react";
import { ConfirmDialog } from "./confirm-dialog";
import { useScout } from "./use-scout";
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
 * The backend refuses a second run while one is in flight (409); this disabled
 * state is convenience, not the guard.
 */
export function RunScoutButton({
  className,
  label = "Find new questions",
  allowModeChoice = true,
}: {
  className?: string;
  label?: string;
  allowModeChoice?: boolean;
}) {
  const { scout, isRunning, run } = useScout();
  const [asking, setAsking] = useState(false);
  const [mode, setMode] = useState<RunMode>("research");

  const cost = scout?.run_cost_usd ?? 0.35;

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
