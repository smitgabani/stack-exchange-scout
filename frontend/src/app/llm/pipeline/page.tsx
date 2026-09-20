"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { llmApi } from "@/lib/llm-api";
import ws from "../../workspace.module.css";
import styles from "../llm.module.css";

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className={styles.stepRow}>
      <div className={styles.stepNum}>{n}</div>
      <div>
        <div className={styles.stepTitle}>{title}</div>
        <div className={styles.stepBody}>{children}</div>
      </div>
    </div>
  );
}

export default function PipelinePage() {
  const { data, isLoading, isError } = useQuery({ queryKey: ["llm-config"], queryFn: llmApi.config });

  if (isLoading) return <div className={ws.empty}>Loading…</div>;
  if (isError || !data) return <div className={ws.empty}>Could not load the LLM configuration.</div>;

  const { prompt, limits, validation, withheld } = data;

  return (
    <>
      <div className={ws.section}>
        <h2 className={ws.sectionTitle}>From question to challenge</h2>
        <div className={ws.sub}>
          Every value on this page is read from the code that actually runs. Nothing here is a
          restatement, so it cannot fall out of date.
        </div>

        <Step n={1} title="Pick the question">
          Either the scoring formula chooses it, as the top N eligible candidates for a digest, or
          you choose it yourself with <strong>Make this a challenge</strong> on the Questions page.
          Both paths run identical code from here on — only the reason given to the model differs.
        </Step>

        <Step n={2} title="Build the prompt — and leave things out">
          Title, body, tags, score, answer count and the reason it was selected are sent. The body
          is flattened from HTML and truncated to{" "}
          <strong>{limits.max_body_chars.toLocaleString()} characters</strong>.
          <div className={styles.withheld} style={{ marginTop: 12 }}>
            <div className={ws.blockLabel}>Never sent, at any point</div>
            {withheld.map((item) => (
              <div key={item} className={styles.withheldItem}>
                · {item}
              </div>
            ))}
          </div>
          <p style={{ marginTop: 12 }}>
            This is the actual anti-spoiler mechanism. The model cannot leak a solution it was
            never shown — a structural guarantee, not an instruction it is asked to respect.
          </p>
        </Step>

        <Step n={3} title="Fence the untrusted content">
          Stack Overflow text is written by anyone, so it is treated as hostile. The system
          instruction is sent in a <em>separate field</em> from the question, and the question is
          wrapped in a <code>&lt;QUESTION&gt;</code> block that is declared to be data, never a
          command. Both halves of that fence are added by the application and cannot be edited
          away on the Prompt tab.
        </Step>

        <Step n={4} title="Ask for structured output">
          The provider is given a JSON schema and asked for five required fields. Currently{" "}
          <strong>{data.provider}</strong>.
        </Step>

        <Step n={5} title="Do not trust the answer">
          Schema-valid JSON can still contain exactly what was forbidden, so the output is checked
          again on the way back: required fields present, hints normalised to at most{" "}
          {limits.hint_labels.length} and labelled by position, difficulty discarded if out of
          range, and the text scanned for solution tells and code blocks.
          <div className={styles.promptBlock} style={{ marginTop: 12 }}>
            {validation.solution_tells.map((pattern) => `reject if matches: ${pattern}`).join("\n")}
            {`\nreject if matches: ${validation.code_fence}`}
          </div>
        </Step>

        <Step n={6} title="Retry once, then fail loudly">
          A validation failure is usually a model slip, so it retries once ({limits.attempts}{" "}
          attempts total). Persistent failure behaves differently depending on the path, on
          purpose: inside a digest the <em>whole digest</em> is marked failed, because a partial
          digest is never emailed; a promotion returns the reason and writes nothing.
        </Step>

        <Step n={7} title="Store it, with its provenance">
          The challenge is saved with the provider, model and prompt version that produced it, so
          a bad batch can be traced back to its cause. See{" "}
          <Link className={ws.textButton} href="/llm/generations">
            Generations
          </Link>
          .
        </Step>
      </div>

      <div className={ws.section}>
        <div className={ws.sectionHead}>
          <div>
            <h2 className={ws.sectionTitle}>The instruction being sent</h2>
            <div className={ws.sub}>
              Prompt version {prompt.version === 0 ? "default (from code)" : prompt.version}. Edit
              it on the{" "}
              <Link className={ws.textButton} href="/llm/prompt">
                Prompt
              </Link>{" "}
              tab.
            </div>
          </div>
        </div>

        <div className={ws.blockLabel}>Editable guidance</div>
        <div className={styles.promptBlock}>{prompt.system_instruction}</div>

        <div style={{ marginTop: 16 }}>
          <div className={styles.lockedLabel}>🔒 Always appended — not editable</div>
          <div className={`${styles.promptBlock} ${styles.lockedBlock}`}>{prompt.safety_clause}</div>
        </div>
      </div>

      <div className={ws.section}>
        <h2 className={ws.sectionTitle}>Required output shape</h2>
        <div className={ws.sub}>Sent to the provider as a JSON schema and re-checked on return.</div>
        <div className={styles.promptBlock}>{JSON.stringify(data.schema, null, 2)}</div>
      </div>
    </>
  );
}
