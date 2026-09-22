"use client";

import { useState } from "react";
import { MermaidDiagram } from "./mermaid-diagram";
import styles from "./challenge.module.css";

/**
 * Renders a challenge from whatever blocks its format produced.
 *
 * The switch is on `kind`, and `kind` now arrives from the backend with the
 * challenge rather than being looked up in a table here. That is what lets a
 * block the user defined at runtime render at all: this file has never heard
 * of `review_checklist`, but it knows how to draw a `checklist`.
 *
 * Until ADR 0005 this held a hardcoded map of every block key, which meant a
 * user-defined block returned `null` — present in the data, invisible on the
 * page. The map also had to be kept in step with the Python registry by hand.
 *
 * Anything whose kind has no renderer is skipped rather than dumped as JSON. A
 * block the UI cannot draw properly is better absent than shown as debug
 * output.
 */

export type Resource = { title: string; url: string; why?: string };
export type Hint = { label: string; text: string };
export type Step = { step: string; detail?: string };
export type Term = { term: string; definition: string };

/** What the backend sends per block, in `ChallengeOut.block_meta`. */
export type BlockMeta = { key: string; label: string; kind: string; gated?: boolean };

/**
 * Blocks the page lays out itself instead of as a generic section.
 *
 * Still keyed by name, and correctly so: this is a statement about *this
 * page's layout* — the problem gets the full-width ink block, difficulty sits
 * in the metadata card — not about the blocks themselves. A custom block can
 * never join this set, which is why it is safe to keep here.
 */
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

export function Block({ meta, value }: { meta: BlockMeta | undefined; value: unknown }) {
  // No metadata: skip it. Happens when a block was deleted after this
  // challenge was made — the value is still stored, but nothing knows how to
  // draw it any more, and raw JSON reads as a bug rather than as content.
  if (!meta) return null;

  let body: React.ReactNode = null;
  switch (meta.kind) {
    case "prose":
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

/**
 * Index a challenge's blocks over the whole library.
 *
 * Two sources, deliberately. `library` is every block that exists, which is
 * what names a block the challenge does not carry — the labels in a "added
 * these sections" message, and the two core fields a pre-formats challenge
 * only has in columns. `blockMeta` is what this challenge actually has, and
 * wins where they overlap, because it was resolved alongside the content.
 */
export function indexBlocks(
  library: BlockMeta[] | undefined,
  blockMeta: BlockMeta[] | undefined,
): Map<string, BlockMeta> {
  const index = new Map<string, BlockMeta>();
  for (const meta of library ?? []) index.set(meta.key, meta);
  for (const meta of blockMeta ?? []) index.set(meta.key, meta);
  return index;
}
