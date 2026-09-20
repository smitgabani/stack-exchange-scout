"use client";

import { useEffect, useId, useState } from "react";
import styles from "./challenge.module.css";

/**
 * Renders model-authored Mermaid source as a diagram.
 *
 * Two hazards, handled rather than avoided:
 *
 * The source is written by an LLM, so it is untrusted input that ends up as
 * SVG in the document. Mermaid's `securityLevel: "strict"` runs its output
 * through DOMPurify, drops click handlers and refuses inline HTML in labels,
 * which is what makes inserting the result acceptable.
 *
 * It also fails: models produce syntax Mermaid rejects. A parse failure falls
 * back to the source, which is exactly what this block showed before it could
 * render at all — worse than a picture, better than an error.
 *
 * Mermaid is ~500KB, so it is imported dynamically and only by this component.
 * A challenge with no diagram block never loads it.
 */
export function MermaidDiagram({ source, caption }: { source: string; caption?: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [showSource, setShowSource] = useState(false);
  // Mermaid needs a unique, stable id per instance. useId gives one without
  // the impurity of randomising during render; its colons are stripped because
  // Mermaid looks the element up with a CSS selector, where they break.
  const reactId = useId();
  const id = `mermaid-${reactId.replace(/:/g, "")}`;

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          // Strict is the default; set explicitly because it is a security
          // control here, not a preference.
          securityLevel: "strict",
          // The app is forced light (see M3's dark-mode incident).
          theme: "neutral",
          fontFamily: "var(--font-archivo), sans-serif",
        });
        const { svg: rendered } = await mermaid.render(id, source);
        if (!cancelled) {
          setSvg(rendered);
          setFailed(false);
        }
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [source, id]);

  if (failed) {
    return (
      <div>
        {caption && <div className={styles.blockBody}>{caption}</div>}
        <div className={styles.diagramFailed}>
          This diagram could not be drawn — the source below is what the model produced.
        </div>
        <pre className={styles.mermaid}>{source}</pre>
      </div>
    );
  }

  return (
    <div>
      {caption && <div className={styles.blockBody}>{caption}</div>}
      {svg === null ? (
        <div className={styles.diagramLoading}>Drawing…</div>
      ) : (
        <>
          {/* Safe to insert: Mermaid sanitised this under securityLevel strict. */}
          <div className={styles.diagram} dangerouslySetInnerHTML={{ __html: svg }} />
          <button
            type="button"
            className={styles.diagramToggle}
            onClick={() => setShowSource((v) => !v)}
          >
            {showSource ? "Hide source" : "View source"}
          </button>
          {showSource && <pre className={styles.mermaid}>{source}</pre>}
        </>
      )}
    </div>
  );
}
