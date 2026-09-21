"use client";

import { useState } from "react";
import styles from "./info-button.module.css";

/**
 * A small "ⓘ" button meant to sit next to an action button. Clicking it
 * opens a lightweight popover explaining exactly what the neighboring
 * action does — it never performs an action itself.
 */
export function InfoButton({ text }: { text: string }) {
  const [open, setOpen] = useState(false);

  return (
    <span className={styles.wrap}>
      <button
        type="button"
        className={styles.button}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label="What does this button do?"
      >
        i
      </button>
      {open && (
        <>
          <div className={styles.backdrop} onClick={() => setOpen(false)} />
          <div role="tooltip" className={styles.popover}>
            {text}
          </div>
        </>
      )}
    </span>
  );
}
