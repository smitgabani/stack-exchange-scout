"use client";

import { useEffect, useState } from "react";

/**
 * A start/stop/resume timer for one challenge, persisted to localStorage.
 *
 * Per-viewer only, like every other use of localStorage in this app — it
 * survives a reload or an accidental tab close, but never reaches the
 * backend until the challenge is actually marked complete (`ChallengePage`
 * sends the final elapsed seconds then). `startedAt` is wall-clock time
 * rather than a running interval, so the elapsed time is still correct after
 * the tab was closed and reopened, not just after a re-render.
 *
 * `elapsedSeconds` is its own piece of state rather than computed inline
 * from `Date.now()` on every render — the latter is an impure render body,
 * which this app's React version now lints against. It is instead only ever
 * touched from event handlers (start/pause/reset) and from the interval
 * callback below, both of which run outside render.
 */

type Stored = { accumulatedSeconds: number; startedAt: number | null };

function key(challengeId: string): string {
  return `challenge-timer:${challengeId}`;
}

function load(challengeId: string): Stored {
  try {
    const raw = localStorage.getItem(key(challengeId));
    if (!raw) return { accumulatedSeconds: 0, startedAt: null };
    const parsed = JSON.parse(raw) as Partial<Stored>;
    return {
      accumulatedSeconds: typeof parsed.accumulatedSeconds === "number" ? parsed.accumulatedSeconds : 0,
      startedAt: typeof parsed.startedAt === "number" ? parsed.startedAt : null,
    };
  } catch {
    return { accumulatedSeconds: 0, startedAt: null };
  }
}

function save(challengeId: string, value: Stored) {
  try {
    if (value.accumulatedSeconds === 0 && value.startedAt === null) {
      localStorage.removeItem(key(challengeId));
    } else {
      localStorage.setItem(key(challengeId), JSON.stringify(value));
    }
  } catch {
    // Storage can be unavailable (private browsing, quota) — the timer still
    // works for the current tab session, it just won't survive a reload.
  }
}

export type TimerStatus = "idle" | "running" | "paused";

export function useTimer(challengeId: string) {
  const [state, setState] = useState<Stored>(() => load(challengeId));
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(() =>
    Math.floor(state.accumulatedSeconds),
  );

  // Ticks the display once a second while running. Corrects from wall-clock
  // time on every tick, so a slow or throttled background tab still catches
  // up rather than drifting — the display just doesn't move smoothly.
  useEffect(() => {
    if (state.startedAt === null) return;
    const startedAt = state.startedAt;
    const accumulated = state.accumulatedSeconds;
    const id = setInterval(() => {
      setElapsedSeconds(Math.floor(accumulated + (Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [state.startedAt, state.accumulatedSeconds]);

  function start() {
    const next: Stored = { ...state, startedAt: Date.now() };
    save(challengeId, next);
    setState(next);
  }

  function pause() {
    if (state.startedAt === null) return;
    const finalSeconds = state.accumulatedSeconds + (Date.now() - state.startedAt) / 1000;
    const next: Stored = { accumulatedSeconds: finalSeconds, startedAt: null };
    save(challengeId, next);
    setState(next);
    setElapsedSeconds(Math.floor(finalSeconds));
  }

  /** Clears the timer entirely — after the challenge is marked complete, or
   *  discarded from the confirm prompt. */
  function reset() {
    const next: Stored = { accumulatedSeconds: 0, startedAt: null };
    save(challengeId, next);
    setState(next);
    setElapsedSeconds(0);
  }

  const status: TimerStatus =
    state.startedAt !== null ? "running" : state.accumulatedSeconds > 0 ? "paused" : "idle";

  return { status, elapsedSeconds, start, pause, reset };
}

export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}
