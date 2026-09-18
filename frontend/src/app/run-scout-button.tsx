"use client";

import { useState } from "react";
import { ConfirmDialog } from "./confirm-dialog";
import { useScout } from "./use-scout";

/**
 * The one button in the app that spends money, so it always confirms first and
 * always names the price. The figure comes from the API rather than from copy
 * here, so it can't drift from `settings.yutori_run_cost_usd`.
 *
 * The backend also refuses a second run while one is in flight (409) — this
 * disabled state is convenience, not the guard.
 */
export function RunScoutButton({
  className,
  label = "Find new questions",
}: {
  className?: string;
  label?: string;
}) {
  const { scout, isRunning, run } = useScout();
  const [asking, setAsking] = useState(false);

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
        title="Start a Scout run?"
        body={
          <>
            This asks Yutori to search Stack Overflow now, using your current
            topics. It costs about <strong>${cost.toFixed(2)}</strong>.
          </>
        }
        confirmLabel="Run now"
        busy={run.isPending}
        onCancel={() => setAsking(false)}
        onConfirm={() => {
          setAsking(false);
          run.mutate();
        }}
      />
    </>
  );
}
