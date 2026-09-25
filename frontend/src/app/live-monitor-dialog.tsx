"use client";

import { type LiveMonitorConflict, every, money, when } from "@/lib/scout-api";
import { ConfirmDialog } from "./confirm-dialog";

/**
 * Shown when a Scout-mode run is refused because the scout already has a
 * monitor running at Yutori (a 409 `live_monitor`).
 *
 * The choice it offers is the whole fix for monitors piling up: before M13
 * each press created another monitor and left the previous one billing
 * forever. Creating is the only way to make Yutori run now — restart only
 * resumes the schedule — so "run again" can only mean *replace*, and
 * replacing stops the old monitor before the new one exists.
 */
export function LiveMonitorDialog({
  conflict,
  scoutName,
  busy = false,
  onReplace,
  onKeep,
  onApply,
}: {
  conflict: LiveMonitorConflict | null;
  scoutName?: string;
  busy?: boolean;
  onReplace: () => void;
  onKeep: () => void;
  /** Send the scout's saved settings to the live monitor instead. Free. */
  onApply?: () => void;
}) {
  const monitor = conflict?.monitor;
  const cost = conflict?.run_cost_usd ?? 0.35;

  return (
    <ConfirmDialog
      open={conflict !== null}
      title={scoutName ? `“${scoutName}” already has a live monitor` : "This scout already has a live monitor"}
      body={
        monitor ? (
          <>
            <p>
              It runs {every(monitor.output_interval)} on its own, about{" "}
              <strong>{money(monitor.monthly_cost_usd)} a month</strong>
              {monitor.next_run ? <>, next run {when(monitor.next_run)}</> : null}. Starting
              another would pay for both.
            </p>
            <p style={{ marginTop: "10px" }}>
              <strong>Replace it</strong> stops this monitor first, then creates a new one that
              runs now for <strong>{money(cost)}</strong>. If the old one can&apos;t be stopped,
              nothing new is created.
            </p>
            <p style={{ marginTop: "10px", fontSize: "13px", color: "var(--muted)" }}>
              <strong>Keep it</strong> leaves it running; its next result arrives on schedule.
            </p>
            {onApply && (
              <p style={{ marginTop: "10px", fontSize: "13px" }}>
                Changed its settings?{" "}
                <button
                  type="button"
                  onClick={onApply}
                  disabled={busy}
                  style={{
                    border: "none",
                    background: "none",
                    padding: 0,
                    color: "var(--link)",
                    cursor: "pointer",
                    font: "inherit",
                  }}
                >
                  Apply them to this monitor instead — free
                </button>
                , no new run.
              </p>
            )}
          </>
        ) : null
      }
      confirmLabel={`Replace it · ${money(cost)}`}
      cancelLabel="Keep it"
      busy={busy}
      onConfirm={onReplace}
      onCancel={onKeep}
    />
  );
}
