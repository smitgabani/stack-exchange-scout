"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { json } from "@/lib/api";
import { jobsApi } from "@/lib/jobs-api";
import { type TestResult, llmApi } from "@/lib/llm-api";
import { JobStatus, useJob } from "../../job-status";
import { ConfirmDialog } from "../../confirm-dialog";
import { InfoButton } from "../../info-button";
import { VersionTable } from "../../version-table";
import ws from "../../workspace.module.css";
import styles from "../llm.module.css";

type QuestionOption = { id: string; title: string | null; status: string };

const fetchQuestions = () => json<QuestionOption[]>("/api/questions?status=all&limit=60");

export default function PromptPage() {
  const queryClient = useQueryClient();
  // A null draft means "showing what is active". Deriving the textarea value
  // rather than syncing it in an effect means a background refetch can never
  // overwrite what is being typed, and there is no effect to get wrong.
  const [draft, setDraft] = useState<{ system: string; preamble: string } | null>(null);
  const [notes, setNotes] = useState("");
  const [pickedQuestion, setPickedQuestion] = useState<string>("");
  const [message, setMessage] = useState<string | null>(null);
  const [confirmTest, setConfirmTest] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  const { data: config } = useQuery({ queryKey: ["llm-config"], queryFn: llmApi.config });
  const { data: versions } = useQuery({ queryKey: ["llm-prompts"], queryFn: llmApi.prompts });
  const { data: questions } = useQuery({ queryKey: ["questions", "all"], queryFn: fetchQuestions });

  const system = draft?.system ?? config?.prompt.system_instruction ?? "";
  const preamble = draft?.preamble ?? config?.prompt.user_preamble ?? "";
  const dirty = draft !== null;
  // Same trick for the dropdown: fall back to the first question rather than
  // writing a default into state.
  const questionId = pickedQuestion || questions?.[0]?.id || "";

  const { data: preview } = useQuery({
    queryKey: ["llm-preview", questionId, system, preamble],
    queryFn: () => llmApi.preview(questionId, { system_instruction: system, user_preamble: preamble }),
    enabled: Boolean(questionId && system && preamble),
  });

  const save = useMutation({
    mutationFn: () =>
      llmApi.savePrompt({ system_instruction: system, user_preamble: preamble, notes: notes || undefined }),
    onSuccess: async (result) => {
      setMessage(`Saved as version ${result.version} and made active.`);
      setDraft(null);
      setNotes("");
      await queryClient.invalidateQueries({ queryKey: ["llm-config"] });
      await queryClient.invalidateQueries({ queryKey: ["llm-prompts"] });
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const activate = useMutation({
    mutationFn: (version: number) => llmApi.activatePrompt(version),
    onSuccess: async (r) => {
      setMessage(`Version ${r.version} is active again.`);
      setDraft(null);
      await queryClient.invalidateQueries({ queryKey: ["llm-config"] });
      await queryClient.invalidateQueries({ queryKey: ["llm-prompts"] });
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const reset = useMutation({
    mutationFn: () => llmApi.resetPrompt(),
    onSuccess: async () => {
      setMessage("Back to the prompt that ships in the code.");
      setDraft(null);
      await queryClient.invalidateQueries({ queryKey: ["llm-config"] });
      await queryClient.invalidateQueries({ queryKey: ["llm-prompts"] });
    },
    onError: (e: Error) => setMessage(e.message),
  });

  // A real generation, thrown away. One LLM call, held the request open.
  const testJob = useJob((job) => {
    if (job.status === "succeeded" && job.result) {
      setTestResult(job.result as unknown as TestResult);
    }
  });

  const test = useMutation({
    mutationFn: () => jobsApi.test(questionId),
    onSuccess: (job) => {
      setConfirmTest(false);
      setMessage(null);
      setTestResult(null);
      testJob.start(job);
    },
    onError: (e: Error) => {
      setConfirmTest(false);
      setMessage(e.message);
    },
  });

  if (!config) return <div className={ws.empty}>Loading…</div>;

  const isDefault = config.prompt.is_default;
  const combined = system.length + preamble.length;
  const overLimit = combined > config.limits.max_prompt_chars;

  return (
    <>
      <div className={ws.section}>
        <div className={ws.sectionHead}>
          <div>
            <h2 className={ws.sectionTitle}>Curator prompt</h2>
            <div className={ws.sub}>
              {isDefault
                ? "Using the prompt that ships in the code."
                : `Using stored version ${config.prompt.version}.`}{" "}
              Saving writes a new version rather than editing this one, so challenges already made
              stay traceable to the text that made them.
            </div>
          </div>
          <div className={ws.actions}>
            <button
              className={ws.primary}
              onClick={() => save.mutate()}
              disabled={save.isPending || !dirty || overLimit}
            >
              {save.isPending ? "Saving…" : "Save as new version"}
            </button>
            <InfoButton text="Writes your edited prompt as a new version and makes it active immediately. The previous version stays in history, so any challenge already generated remains traceable to the exact prompt text that produced it." />
            {!isDefault && (
              <>
                <button className={ws.secondary} onClick={() => reset.mutate()} disabled={reset.isPending}>
                  Reset to default
                </button>
                <InfoButton text="Discards any stored custom prompt and reverts to the prompt that ships in the code." />
              </>
            )}
          </div>
        </div>

        {message && <div className={ws.notice}>{message}</div>}

        <div className={ws.blockLabel}>System instruction — editable guidance</div>
        <textarea
          className={styles.editor}
          value={system}
          onChange={(e) => setDraft({ system: e.target.value, preamble })}
          spellCheck={false}
        />

        <div style={{ marginTop: 16 }}>
          <div className={styles.lockedLabel}>🔒 Always appended — not editable</div>
          <div className={`${styles.promptBlock} ${styles.lockedBlock}`}>
            {config.prompt.safety_clause}
          </div>
          <div className={ws.hint} style={{ marginTop: 8 }}>
            These lines are the prompt-injection defence. They are composed in code around whatever
            you write above, so a bad edit can produce poor challenges but never an unfenced call.
          </div>
        </div>

        <div style={{ marginTop: 20 }}>
          <div className={ws.blockLabel}>User message preamble — editable</div>
          <textarea
            className={styles.editor}
            style={{ minHeight: "80px" }}
            value={preamble}
            onChange={(e) => setDraft({ system, preamble: e.target.value })}
            spellCheck={false}
          />
          <div className={ws.hint} style={{ marginTop: 8 }}>
            The trusted metadata block and the fenced question follow this automatically.
          </div>
        </div>

        <div style={{ marginTop: 16 }}>
          <input
            className={ws.input}
            placeholder="What changed, and why (optional)"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <div className={ws.hint} style={{ marginTop: 6 }}>
            {combined.toLocaleString()} / {config.limits.max_prompt_chars.toLocaleString()}{" "}
            characters
            {overLimit && <strong className={ws.bad}> — too long to save</strong>}
          </div>
        </div>
      </div>

      <div className={ws.section}>
        <div className={ws.sectionHead}>
          <div>
            <h2 className={ws.sectionTitle}>Exactly what gets sent</h2>
            <div className={ws.sub}>
              Rendered against a real question, including your unsaved edits. Free — no model call.
            </div>
          </div>
          <div className={ws.actions}>
            <select
              className={ws.input}
              value={questionId}
              onChange={(e) => setPickedQuestion(e.target.value)}
            >
              {(questions ?? []).map((q) => (
                <option key={q.id} value={q.id}>
                  {(q.title ?? "Untitled").slice(0, 60)}
                </option>
              ))}
            </select>
            <button
              className={ws.secondary}
              onClick={() => setConfirmTest(true)}
              disabled={!questionId || test.isPending}
            >
              {test.isPending ? "Generating…" : "Test generate"}
            </button>
            <InfoButton text="Sends your current prompt (including unsaved edits) to your LLM provider for the selected question and shows the raw result. Costs one real LLM call. Nothing is saved — no challenge is created and the question is unchanged." />
          </div>
        </div>

        {preview ? (
          <>
            <div className={ws.hint}>
              Body: {preview.question.body_chars.toLocaleString()} characters on the question,{" "}
              {preview.question.body_chars_sent.toLocaleString()} actually sent after stripping and
              truncation. Prompt is {preview.prompt_chars.toLocaleString()} characters.
            </div>
            <div className={ws.blockLabel} style={{ marginTop: 14 }}>
              System instruction (as sent)
            </div>
            <div className={styles.promptBlock}>{preview.system_instruction}</div>
            <div className={ws.blockLabel} style={{ marginTop: 14 }}>
              User message (as sent)
            </div>
            <div className={styles.promptBlock}>{preview.prompt}</div>
          </>
        ) : (
          <div className={ws.empty}>Pick a question to see the prompt it would produce.</div>
        )}
      </div>

      <JobStatus
        job={testJob.job}
        onCheck={() => testJob.check.mutate()}
        checking={testJob.check.isPending}
        estimate="around half a minute"
      >
        <span>Generation finished — the result is below.</span>
      </JobStatus>

      {testResult && (
        <div className={ws.section}>
          <h2 className={ws.sectionTitle}>Test result</h2>
          <div className={ws.sub}>
            {testResult.provider} · {testResult.model} · {testResult.format.name} · prompt v
            {testResult.prompt_version || "default"} · nothing was saved
          </div>
          {testResult.ok ? (
            <>
              <div className={`${ws.pill} ${ws.pillOn}`}>Passed validation</div>
              {testResult.dropped_links.length > 0 && (
                /* Reported rather than hidden: a model that invents links is
                   worth knowing about when judging a prompt. */
                <div className={ws.notice} style={{ marginTop: 10 }}>
                  {testResult.dropped_links.length} resource link
                  {testResult.dropped_links.length === 1 ? "" : "s"} did not resolve and would have
                  been dropped.
                </div>
              )}
              {/* Raw, on purpose: this view is for judging what the model
                  returned, not for reading a finished challenge. */}
              <div className={styles.promptBlock} style={{ marginTop: 14 }}>
                {JSON.stringify(testResult.content, null, 2)}
              </div>
            </>
          ) : (
            <>
              {/* A rejection is a useful result, not a failure to hide — it is
                  how a prompt that produces spoilers is caught before it ships. */}
              <div className={`${ws.pill} ${ws.pillBad}`}>Rejected by validation</div>
              <div className={styles.promptBlock} style={{ marginTop: 12 }}>
                {testResult.error}
              </div>
            </>
          )}
        </div>
      )}

      <div className={ws.section}>
        <h2 className={ws.sectionTitle}>Version history</h2>
        {!versions || versions.versions.length === 0 ? (
          <div className={ws.empty}>
            No saved versions — the prompt in the code is in use. Saving an edit creates version 2.
          </div>
        ) : (
          <VersionTable
            versions={versions.versions}
            onActivate={(version) => activate.mutate(version)}
            pending={activate.isPending}
          />
        )}
      </div>

      <ConfirmDialog
        open={confirmTest}
        title="Run a real generation?"
        body={
          <>
            <p>
              This sends the prompt above to {config.provider} for the selected question and shows
              you exactly what comes back.
            </p>
            <p>
              It costs <strong>one LLM call</strong>. Nothing is saved — no challenge is created and
              the question is not changed.
            </p>
          </>
        }
        confirmLabel="Run test"
        busy={test.isPending}
        onConfirm={() => test.mutate()}
        onCancel={() => setConfirmTest(false)}
      />
    </>
  );
}
