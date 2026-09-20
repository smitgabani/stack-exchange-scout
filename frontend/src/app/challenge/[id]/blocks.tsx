"use client";

import { useState } from "react";
import { MermaidDiagram } from "./mermaid-diagram";
import styles from "./challenge.module.css";

/**
 * Renders a challenge from whatever blocks its format produced.
 *
 * The switch is on `kind`, not on the key, so adding a block to the backend
 * registry means adding a renderer here only when it introduces a new kind —
 * a new "list of strings" block needs no frontend change at all.
 *
 * Anything with no renderer is skipped rather than dumped as JSON. A block the
 * UI cannot draw properly is better absent than shown as debug output.
 */

export type Resource = { title: string; url: string; why?: string };
export type Hint = { label: string; text: string };
export type Step = { step: string; detail?: string };
export type Term = { term: string; definition: string };

/** Mirrors `challenge_blocks.BLOCKS`; the backend sends the order to render. */
const BLOCK_META: Record<string, { label: string; kind: string; gated?: boolean }> = {
  problem_summary: { label: "Problem", kind: "problem" },
  why_interesting: { label: "Why this one", kind: "card" },
  concepts: { label: "Concepts", kind: "chips" },
  starting_direction: { label: "Start here", kind: "prose" },
  hints: { label: "Hints", kind: "progressive_hints" },
  estimated_difficulty: { label: "Difficulty", kind: "rating" },
  prerequisites: { label: "You should know", kind: "chips" },
  glossary: { label: "Terms", kind: "definition_list" },
  visualisation: { label: "Picture it", kind: "diagram" },
  approach_outline: { label: "How to approach it", kind: "steps" },
  common_pitfalls: { label: "Common pitfalls", kind: "list" },
  self_check: { label: "Check yourself", kind: "checklist" },
  time_estimate: { label: "Time", kind: "stat" },
  learning_resources: { label: "Learn the concepts", kind: "resource_list" },
  solution_resources: { label: "If you're stuck", kind: "resource_list", gated: true },
};

/** Blocks rendered inside the page's own layout rather than as a generic section. */
export const SPECIAL_BLOCKS = new Set([
  "problem_summary",
  "why_interesting",
  "estimated_difficulty",
  "hints",
]);

function Chips({ values }: { values: unknown }) {
  if (!Array.isArray(values) || values.length === 0) return null;
  return (
    <div className={styles.chipRow}>
      {values.map((value) => (
        <span key={String(value)} className={styles.conceptChip}>
          {String(value)}
        </span>
      ))}
    </div>
  );
}

function Bullets({ values, check }: { values: unknown; check?: boolean }) {
  if (!Array.isArray(values) || values.length === 0) return null;
  return (
    <ul className={check ? styles.checklist : styles.bulletList}>
      {values.map((value, index) => (
        <li key={index}>{String(value)}</li>
      ))}
    </ul>
  );
}

function Steps({ values }: { values: unknown }) {
  if (!Array.isArray(values) || values.length === 0) return null;
  return (
    <ol className={styles.steps}>
      {(values as Step[]).map((item, index) => (
        <li key={index}>
          <span className={styles.stepText}>{item.step}</span>
          {item.detail && <span className={styles.stepDetail}>{item.detail}</span>}
        </li>
      ))}
    </ol>
  );
}

function Definitions({ values }: { values: unknown }) {
  if (!Array.isArray(values) || values.length === 0) return null;
  return (
    <dl className={styles.definitions}>
      {(values as Term[]).map((item) => (
        <div key={item.term} className={styles.definitionRow}>
          <dt>{item.term}</dt>
          <dd>{item.definition}</dd>
        </div>
      ))}
    </dl>
  );
}

function Resources({ values }: { values: unknown }) {
  if (!Array.isArray(values) || values.length === 0) return null;
  return (
    <div className={styles.resourceList}>
      {(values as Resource[]).map((item) => (
        <a
          key={item.url}
          className={styles.resource}
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
        >
          <span className={styles.resourceTitle}>{item.title} ↗</span>
          {item.why && <span className={styles.resourceWhy}>{item.why}</span>}
          {/* Shown because every URL here survived a reachability check at
              generation time — the host is worth seeing before clicking. */}
          <span className={styles.resourceHost}>{safeHost(item.url)}</span>
        </a>
      ))}
    </div>
  );
}

function safeHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function Stat({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return null;
  const stat = value as { value?: string; rationale?: string };
  if (!stat.value) return null;
  return (
    <div>
      <div className={styles.statBig}>{stat.value}</div>
      {stat.rationale && <div className={styles.blockBody}>{stat.rationale}</div>}
    </div>
  );
}

function Diagram({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return null;
  const diagram = value as { caption?: string; mermaid?: string };
  if (!diagram.mermaid) return null;

  return <MermaidDiagram source={diagram.mermaid} caption={diagram.caption} />;
}

export function ProgressiveHints({
  hints,
  onAllRevealed,
}: {
  hints: Hint[];
  onAllRevealed?: (revealed: boolean) => void;
}) {
  const [revealed, setRevealed] = useState(0);

  function reveal() {
    const next = Math.min(hints.length, revealed + 1);
    setRevealed(next);
    onAllRevealed?.(next >= hints.length);
  }

  return (
    <div className={styles.hints}>
      {hints.slice(0, revealed).map((hint) => (
        <div key={hint.label} className={styles.hintItem}>
          <div className={styles.hintLabel}>{hint.label}</div>
          <div className={styles.hintText}>{hint.text}</div>
        </div>
      ))}
      {revealed < hints.length && (
        <button type="button" className={styles.revealBtn} onClick={reveal}>
          Show hint {revealed + 1}
        </button>
      )}
    </div>
  );
}

export function Block({ blockKey, value }: { blockKey: string; value: unknown }) {
  const meta = BLOCK_META[blockKey];
  // Unknown block: skip it. The alternative is rendering raw JSON, which looks
  // like a bug to the reader and teaches them nothing.
  if (!meta) return null;

  let body: React.ReactNode = null;
  switch (meta.kind) {
    case "prose":
    case "card":
      body = <div className={styles.blockBody}>{String(value)}</div>;
      break;
    case "chips":
      body = <Chips values={value} />;
      break;
    case "list":
      body = <Bullets values={value} />;
      break;
    case "checklist":
      body = <Bullets values={value} check />;
      break;
    case "steps":
      body = <Steps values={value} />;
      break;
    case "definition_list":
      body = <Definitions values={value} />;
      break;
    case "resource_list":
      body = <Resources values={value} />;
      break;
    case "stat":
      body = <Stat value={value} />;
      break;
    case "diagram":
      body = <Diagram value={value} />;
      break;
    default:
      return null;
  }

  if (!body) return null;

  return (
    <div className={styles.block}>
      <div className={styles.blockLabel}>{meta.label}</div>
      {body}
    </div>
  );
}

export function isGated(blockKey: string): boolean {
  return Boolean(BLOCK_META[blockKey]?.gated);
}

export function labelFor(blockKey: string): string {
  return BLOCK_META[blockKey]?.label ?? blockKey;
}
