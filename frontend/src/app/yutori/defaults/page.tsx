"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { YutoriSettings } from "@/lib/scout-api";
import { yutoriApi } from "@/lib/yutori-api";
import { InfoButton } from "../../info-button";
import ws from "../../workspace.module.css";
import { ParametersForm } from "../parameters-form";

/**
 * What every scout starts from (M13): the wording of the query sent to
 * Yutori, and the default settings a scout inherits unless it overrides them.
 *
 * The template editor mirrors the LLM prompt page on purpose — draft until
 * saved, every save a new version, older versions one click away, and a free
 * preview filled with your real topics.
 */
export default function DefaultsPage() {
  return (
    <main className={ws.page}>
      <QueryTemplateEditor />
      <DefaultSettings />
    </main>
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

function QueryTemplateEditor() {
  const queryClient = useQueryClient();
  // null = no edits: show the active template.
  const [draft, setDraft] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  const { data: config } = useQuery({ queryKey: ["query-template"], queryFn: yutoriApi.queryTemplate });
  const { data: history } = useQuery({
    queryKey: ["query-templates"],
    queryFn: yutoriApi.queryTemplates,
  });

  const debounced = useDebounced(draft, 400);
  const preview = useQuery({
    queryKey: ["query-template-preview", debounced],
    queryFn: () => yutoriApi.previewQueryTemplate(debounced ?? ""),
    enabled: debounced !== null,
    retry: false,
  });

  const refresh = async (text: string) => {
    setMessage(text);
    setDraft(null);
    setNotes("");
    await queryClient.invalidateQueries({ queryKey: ["query-template"] });
    await queryClient.invalidateQueries({ queryKey: ["query-templates"] });
    // Every topics-based scout's rendered query just changed.
    await queryClient.invalidateQueries({ queryKey: ["definitions"] });
    await queryClient.invalidateQueries({ queryKey: ["definition"] });
    await queryClient.invalidateQueries({ queryKey: ["definition-settings"] });
  };

  const save = useMutation({
    mutationFn: () => yutoriApi.saveQueryTemplate(draft ?? "", notes),
    onSuccess: (r) => refresh(`Saved as version ${r.version}. The next topics-based run uses it.`),
    onError: (e: Error) => setMessage(e.message),
  });
  const activate = useMutation({
    mutationFn: (version: number) => yutoriApi.activateQueryTemplate(version),
    onSuccess: (r) => refresh(`Version ${r.version} is active again.`),
    onError: (e: Error) => setMessage(e.message),
  });
  const reset = useMutation({
    mutationFn: yutoriApi.resetQueryTemplate,
    onSuccess: () => refresh("Back to the built-in template."),
    onError: (e: Error) => setMessage(e.message),
  });

  if (!config) return <div className={ws.empty}>Loading…</div>;

  const body = draft ?? config.template.body;
  const dirty = draft !== null && draft !== config.template.body;
  const limit = config.limits.max_template_chars;
  const previewError = draft !== null && preview.isError ? (preview.error as Error).message : null;
  const rendered = draft === null ? config.rendered : preview.data?.rendered;

  return (
    <div className={ws.section}>
      <div className={ws.sectionHead}>
        <div>
          <h2 className={ws.sectionTitle}>Query template</h2>
          <div className={ws.sub}>
            {config.template.is_default
              ? "Using the template that ships in the code."
              : `Using stored version ${config.template.version}.`}{" "}
            This is what a scout set to &ldquo;From my topics&rdquo; sends Yutori, with your topics
            filled in. Saving writes a new version, so every run stays traceable to its wording.
          </div>
        </div>
        <div className={ws.actions}>
          <button
            className={ws.primary}
            onClick={() => save.mutate()}
            disabled={!dirty || save.isPending || Boolean(previewError) || body.length > limit}
          >
            {save.isPending ? "Saving…" : "Save as new version"}
          </button>
          <InfoButton text="Writes the template as a new version and makes it active. Free — nothing is sent to Yutori until a scout runs." />
          {dirty && (
            <button className={ws.secondary} onClick={() => setDraft(null)}>
              Discard
            </button>
          )}
          {!config.template.is_default && (
            <button className={ws.secondary} onClick={() => reset.mutate()} disabled={reset.isPending}>
              Reset to built-in
            </button>
          )}
        </div>
      </div>

      {message && <div className={ws.notice}>{message}</div>}

      <div className={ws.grid2}>
        <div className={ws.card}>
          <label className={ws.label} htmlFor="query-template">
            Template
          </label>
          <textarea
            id="query-template"
            className={ws.textarea}
            style={{ minHeight: 380, fontFamily: "var(--font-geist-mono), monospace", fontSize: 13 }}
            spellCheck={false}
            value={body}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className={ws.hint}>
            Placeholders:{" "}
            {config.placeholders.map((name) => (
              <code key={name} style={{ marginRight: 6 }}>
                {`{${name}}`}
              </code>
            ))}
            · {body.length.toLocaleString()} / {limit.toLocaleString()} characters
            {body.length > limit && <strong className={ws.bad}> — too long to save</strong>}
          </div>
          {previewError && <div className={ws.bad}>{previewError}</div>}
          <input
            id="query-template-notes"
            className={ws.input}
            placeholder="What changed, and why (optional)"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>

        <div className={ws.card}>
          <div className={ws.cardTitle}>What Yutori would receive</div>
          <p className={ws.hint}>Filled with your current topics. Free — nothing is sent.</p>
          <pre className={ws.query}>
            {draft !== null && preview.isFetching && !preview.data
              ? "Updating…"
              : previewError
                ? "Fix the template to see it filled in."
                : rendered ?? "—"}
          </pre>
        </div>
      </div>

      {(history?.versions.length ?? 0) > 0 && (
        <div className={ws.tableWrap}>
          <table className={ws.table}>
            <thead>
              <tr>
                <th>Version</th>
                <th>Saved</th>
                <th>Note</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {history!.versions.map((row) => (
                <tr key={row.id}>
                  <td className={ws.num}>v{row.version}</td>
                  <td>{row.created_at ? new Date(row.created_at).toLocaleString() : "—"}</td>
                  <td>{row.notes ?? "—"}</td>
                  <td>
                    {row.is_active ? (
                      <span className={`${ws.pill} ${ws.pillOn}`}>Active</span>
                    ) : (
                      <button
                        className={ws.textButton}
                        onClick={() => activate.mutate(row.version)}
                        disabled={activate.isPending}
                      >
                        Activate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function DefaultSettings() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const { data } = useQuery({ queryKey: ["yutori-defaults"], queryFn: yutoriApi.defaults });

  const after = async (text: string) => {
    setMessage(text);
    await queryClient.invalidateQueries({ queryKey: ["yutori-defaults"] });
    // Every scout that inherits a field just changed what it would send.
    await queryClient.invalidateQueries({ queryKey: ["definition-settings"] });
  };
  const save = useMutation({
    mutationFn: (values: YutoriSettings) => yutoriApi.putDefaults(values),
    onSuccess: () => after("Saved. Scouts that don't override a setting use these on their next run."),
    onError: (e: Error) => setMessage(e.message),
  });
  const reset = useMutation({
    mutationFn: yutoriApi.resetDefaults,
    onSuccess: () => after("Back to the built-in defaults."),
    onError: (e: Error) => setMessage(e.message),
  });

  if (!data) return null;

  return (
    <div className={ws.section}>
      <div className={ws.sectionHead}>
        <div>
          <h2 className={ws.sectionTitle}>Default settings</h2>
          <div className={ws.sub}>
            What every scout starts from. A scout can override any of these on its Parameters tab;
            everything it doesn&apos;t override follows what&apos;s here.
          </div>
        </div>
      </div>
      {message && <div className={ws.notice}>{message}</div>}
      <ParametersForm
        variant="defaults"
        mode="scout"
        base={data.built_in}
        saved={data.stored}
        defaultSchema={data.default_output_schema}
        yutoriDefaultTimezone={data.yutori_default_timezone}
        runCost={data.run_cost_usd}
        scopeKey="defaults"
        saving={save.isPending || reset.isPending}
        onSave={(values) => save.mutate(values)}
        onResetAll={() => reset.mutate()}
      />
    </div>
  );
}
