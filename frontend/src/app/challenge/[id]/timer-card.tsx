"use client";

import { useState } from "react";
import { ConfirmDialog } from "../../confirm-dialog";
import { formatDuration, useTimer } from "./use-timer";
import styles from "./challenge.module.css";

type Timer = ReturnType<typeof useTimer>;

/**
 * The timer, as one self-contained card: state (idle/running/paused) reads
 * from the card's own look rather than from a label alone, and every action
 * available in that state — including resetting it — lives here rather than
 * scattered across the page.
 */
export function TimerCard({
  timer,
  onStop,
  onComplete,
  completing,
}: {
  timer: Timer;
  /** Pauses and opens the "mark as done?" prompt — the page owns that dialog
   *  because it also needs to know the answer was yes. */
  onStop: () => void;
  onComplete: (seconds?: number) => void;
  completing: boolean;
}) {
  const [confirmReset, setConfirmReset] = useState(false);

  return (
    <div className={`${styles.timerCard} ${styles[`timerCard_${timer.status}`]}`}>
      <div className={styles.timerHeader}>
        <span className={styles.timerStatusPill}>
          {timer.status === "running" && <span className={styles.timerDot} />}
          {timer.status === "running"
            ? "Recording"
            : timer.status === "paused"
              ? "Paused"
              : "Not started"}
        </span>
        {timer.status !== "idle" && (
          <button
            type="button"
            className={styles.timerReset}
            onClick={() => setConfirmReset(true)}
          >
            Reset
          </button>
        )}
      </div>

      <div className={styles.timerBig}>{formatDuration(timer.elapsedSeconds)}</div>

      <div className={styles.timerActions}>
        {timer.status === "idle" && (
          <>
            <button type="button" className={styles.timerPrimary} onClick={timer.start}>
              ▶ Start timer
            </button>
            <button
              type="button"
              className={styles.timerGhost}
              onClick={() => onComplete(undefined)}
              disabled={completing}
            >
              Mark complete without timing
            </button>
          </>
        )}
        {timer.status === "running" && (
          <>
            <button type="button" className={styles.timerSecondary} onClick={timer.pause}>
              ⏸ Pause
            </button>
            <button type="button" className={styles.timerPrimary} onClick={onStop}>
              ⏹ Stop &amp; finish
            </button>
          </>
        )}
        {timer.status === "paused" && (
          <>
            <button type="button" className={styles.timerSecondary} onClick={timer.start}>
              ▶ Resume
            </button>
            <button
              type="button"
              className={styles.timerComplete}
              onClick={() => onComplete(timer.elapsedSeconds)}
              disabled={completing}
            >
              {completing ? "Marking complete…" : "✓ Mark as complete"}
            </button>
          </>
        )}
      </div>

      <ConfirmDialog
        open={confirmReset}
        title="Reset the timer?"
        body={
          <p>
            This discards <strong>{formatDuration(timer.elapsedSeconds)}</strong> of recorded time
            for this challenge. This can&apos;t be undone.
          </p>
        }
        confirmLabel="Reset timer"
        cancelLabel="Keep it"
        onConfirm={() => {
          timer.reset();
          setConfirmReset(false);
        }}
        onCancel={() => setConfirmReset(false)}
      />
    </div>
  );
}
