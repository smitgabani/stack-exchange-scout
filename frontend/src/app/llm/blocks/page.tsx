"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { type BlockMeta, llmApi } from "@/lib/llm-api";
import { ConfirmDialog } from "../../confirm-dialog";
import { InfoButton } from "../../info-button";
import ws from "../../workspace.module.css";
import styles from "../llm.module.css";

/**
 * The block library: what each block asks the model for, and blocks you add.
 *
 * A block is a question put to the model plus a layout for its answer. Both
 * halves are editable here — but only the wording for the blocks that ship in
 * the code, because their shape is what `validate` demands on every run.
 */

type Draft = {
  id: number | null;
  key: string;
  label: string;
  description: string;
  kind: string;
  instruction: string;
  gated: boolean;
};

const EMPTY: Draft = {
  id: null,
  key: "",
  label: "",
  description: "",
  kind: "checklist",
  instruction: "",
  gated: false,
};

/** What each layout does with the model's answer, in the reader's terms. */
const KIND_HELP: Record<string, string> = {
  prose: "A paragraph of text.",
  chips: "Short labels in rounded pills, like the Concepts row.",
  list: "A bulleted list of short lines.",
  checklist: "A list with tick marks, for things to verify.",
  steps: "A numbered list, each step with optional detail.",
  definition_list: "Term-and-definition pairs, like a glossary.",
  resource_list: "Links with a title and a reason. Every URL is checked before it is stored.",
  stat: "One prominent figure with a line of rationale.",
  diagram: "A Mermaid diagram, drawn on the page.",
};

function keyFromLabel(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40);
}

export default function BlocksPage() {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [removing, setRemoving] = useState<BlockMeta | null>(null);

  const { data } = useQuery({ queryKey: ["llm-blocks"], queryFn: llmApi.blocks });

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["llm-blocks"] });
    // The composed instruction on the pipeline and prompt pages is built from
    // these, so it is stale the moment one changes.
    await queryClient.invalidateQueries({ queryKey: ["llm-config"] });
  }

  const saveCustom = useMutation({
    mutationFn: (d: Draft) => {
      const body = {
        label: d.label,
        kind: d.kind,
        instruction: d.instruction,
        description: d.description || undefined,
        gated: d.gated,
      };
      return d.id === null
        ? llmApi.createBlock({ ...body, key: d.key || keyFromLabel(d.label) })
        : llmApi.updateBlock(d.id, body);
    },
    onSuccess: async (row) => {
      setMessage(`Saved “${row.label}”. New challenges will ask for it.`);
      setDraft(null);
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const saveInstruction = useMutation({
    mutationFn: ({ key, instruction }: { key: string; instruction: string }) =>
      llmApi.setInstruction(key, instruction),
    onSuccess: async (row) => {
      setMessage(`Reworded “${row.key}”. Challenges already made are unchanged.`);
      setEdits((current) => {
        const next = { ...current };
        delete next[row.key];
        return next;
      });
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const resetInstruction = useMutation({
    mutationFn: (key: string) => llmApi.resetInstruction(key),
    onSuccess: async (row) => {
      setMessage(`“${row.key}” is back to the wording that ships in the code.`);
      setEdits((current) => {
        const next = { ...current };
        delete next[row.key];
        return next;
      });
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: number) => llmApi.deleteBlock(id),
    onSuccess: async () => {
      setMessage("Block deleted. Challenges that already have it stop showing it.");
      setRemoving(null);
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const blocks = data?.blocks ?? [];
  const builtIn = blocks.filter((b) => !b.custom);
  const custom = blocks.filter((b) => b.custom);
  const kinds = data?.custom_kinds ?? [];
  const limit = data?.max_instruction_chars ?? 1200;

  // Vercel and Fly deploy separately, so this page routinely runs against a
  // backend older than itself. Said plainly, because the failure is otherwise
  // silent and misleading: an empty layout picker and a page of blank prompt
  // boxes look like the feature is broken rather than absent. `custom_kinds`
  // is the marker — it arrived with the endpoints this page needs.
  const backendTooOld = Boolean(data) && data?.custom_kinds === undefined;

  function instructionFor(block: BlockMeta): string {
    return edits[block.key] ?? block.instruction;
  }

  return (
    <>
      <div className={ws.section}>
        <div className={ws.sectionHead}>
          <div>
            <h2 className={ws.sectionTitle}>Block library</h2>
            <div className={ws.sub}>
              Every block is one instruction to the model plus a layout for the answer. Reword any
              of them, or add your own. Changes apply to challenges generated from now on —
              existing ones keep what they were made with.
            </div>
          </div>
          <div className={ws.actions}>
            <button
              className={ws.primary}
              onClick={() => setDraft({ ...EMPTY })}
              disabled={backendTooOld}
            >
              New block
            </button>
            <InfoButton text="Defines a new block: a question put to the model and a layout for its answer. Nothing is saved until you press Save block, and no challenge uses it until you add it to a format." />
          </div>
        </div>
        {message && <div className={ws.notice}>{message}</div>}
        {backendTooOld && (
          <div className={ws.alert}>
            <strong>This page needs a newer backend than the one deployed.</strong> The block
            library is being served by an older API that does not know about editable instructions
            or custom blocks, so the layouts and the current prompts below are empty. Deploy the
            backend and reload.
          </div>
        )}
      </div>

      {draft && (
        <div className={ws.section}>
          <h2 className={ws.sectionTitle}>
            {draft.id === null ? "New block" : `Edit “${draft.label || "block"}”`}
          </h2>

          <div className={ws.field}>
            <span className={ws.label}>Heading on the challenge page</span>
            <input
              className={ws.input}
              placeholder="e.g. “Before you ship”"
              value={draft.label}
              onChange={(e) => setDraft({ ...draft, label: e.target.value })}
            />
          </div>

          {draft.id === null && (
            <div className={ws.field}>
              <span className={ws.label}>Key</span>
              <input
                className={ws.input}
                placeholder={keyFromLabel(draft.label) || "review_checklist"}
                value={draft.key}
                onChange={(e) => setDraft({ ...draft, key: e.target.value })}
              />
              {/* Stated plainly because it is the one irreversible choice here:
                  every challenge stores its content under this name. */}
              <span className={ws.hint}>
                Lowercase, no spaces. Left blank it is made from the heading. It cannot be changed
                afterwards — challenges store their content under it.
              </span>
            </div>
          )}

          <div className={ws.field}>
            <span className={ws.label}>What it&apos;s for (optional)</span>
            <input
              className={ws.input}
              placeholder="Shown in the format editor"
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            />
          </div>

          <div className={ws.blockLabel} style={{ marginTop: 18 }}>
            Layout
          </div>
          <div className={ws.hint}>
            This decides both how the answer is drawn and what shape the model is asked for, so
            there is never a block the page cannot render.
          </div>
          <div className={styles.blockGrid}>
            {kinds.map((kind) => (
              <button
                type="button"
                key={kind}
                className={`${styles.blockCard} ${draft.kind === kind ? styles.blockOn : ""}`}
                onClick={() => setDraft({ ...draft, kind })}
                aria-pressed={draft.kind === kind}
              >
                <div className={styles.blockName}>{kind.replace(/_/g, " ")}</div>
                <div className={styles.blockDesc}>{KIND_HELP[kind] ?? ""}</div>
              </button>
            ))}
          </div>

          <div className={ws.field} style={{ marginTop: 18 }}>
            <span className={ws.label}>
              What to ask the model ({instructionLength(draft.instruction)}/{limit})
            </span>
            <textarea
              className={ws.textarea}
              placeholder="List what to verify before calling this done. Do not state the solution."
              value={draft.instruction}
              onChange={(e) => setDraft({ ...draft, instruction: e.target.value })}
            />
            <span className={ws.hint}>
              This is added to the instruction sent on every generation, alongside the other blocks
              in the format.
            </span>
          </div>

          <label className={ws.field} style={{ marginTop: 6 }}>
            <span className={ws.label}>
              <input
                type="checkbox"
                checked={draft.gated}
                onChange={(e) => setDraft({ ...draft, gated: e.target.checked })}
                style={{ marginRight: 8 }}
              />
              Hide until every hint has been revealed
            </span>
          </label>
          {/* The one control here that loosens a safety check, so it says so
              rather than sitting quietly as a checkbox. */}
          {draft.gated && (
            <div className={ws.alert}>
              <strong>Gated blocks are exempt from the spoiler check.</strong> Everything else is
              scanned for phrases that give the answer away and rejected if it matches. Use this
              only for a block that is meant to help someone who has given up.
            </div>
          )}

          <div className={ws.actions} style={{ marginTop: 16 }}>
            <button
              className={ws.primary}
              onClick={() => saveCustom.mutate(draft)}
              disabled={!draft.label.trim() || !draft.instruction.trim() || saveCustom.isPending}
            >
              {saveCustom.isPending ? "Saving…" : "Save block"}
            </button>
            <InfoButton text="Saves the block to your library. It does nothing on its own — add it to a format under LLM → Formats for challenges to start asking for it." />
            <button className={ws.secondary} onClick={() => setDraft(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {custom.length > 0 && (
        <div className={ws.section}>
          <h2 className={ws.sectionTitle}>Your blocks</h2>
          <div className={ws.list}>
            {custom.map((block) => (
              <div key={block.key} className={ws.item}>
                <div>
                  <div className={ws.itemName}>
                    {block.label}
                    <span className={`${ws.pill} ${ws.pillOn}`}>Yours</span>
                    {block.gated && <span className={`${ws.pill} ${ws.pillBad}`}>Gated</span>}
                    {block.has_urls && <span className={ws.pill}>Links checked</span>}
                  </div>
                  <div className={ws.itemMeta}>
                    {block.kind.replace(/_/g, " ")} · {block.key}
                  </div>
                  <div className={ws.itemQuery}>{block.instruction}</div>
                </div>
                <div className={ws.itemSide}>
                  <div className={ws.actions}>
                    <button
                      className={`${ws.secondary} ${ws.tiny}`}
                      onClick={() =>
                        setDraft({
                          id: block.id,
                          key: block.key,
                          label: block.label,
                          description: block.description,
                          kind: block.kind,
                          instruction: block.instruction,
                          gated: block.gated,
                        })
                      }
                    >
                      Edit
                    </button>
                    <button className={`${ws.danger} ${ws.tiny}`} onClick={() => setRemoving(block)}>
                      Delete
                    </button>
                    <InfoButton text="Removes the block from your library and from every format using it. Challenges that already have its output keep it stored but stop showing it." />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className={ws.section}>
        <h2 className={ws.sectionTitle}>Built-in blocks</h2>
        <div className={ws.hint}>
          These ship with the app. You can change what each one asks for, but not its layout — the
          six core blocks are what every challenge and the digest email are built from, and
          validation demands their shape on every generation.
        </div>

        <div className={ws.list}>
          {builtIn.map((block) => {
            const value = instructionFor(block);
            const dirty = value !== block.instruction;
            return (
              <div key={block.key} className={ws.card}>
                <div className={ws.itemName}>
                  {block.label}
                  {block.core && <span className={ws.pill}>Always included</span>}
                  {block.gated && <span className={`${ws.pill} ${ws.pillBad}`}>Gated</span>}
                  {block.is_overridden && (
                    <span className={`${ws.pill} ${ws.pillLive}`}>Reworded</span>
                  )}
                </div>
                <div className={ws.itemMeta}>
                  {block.kind.replace(/_/g, " ")} · {block.description}
                </div>

                <textarea
                  className={ws.textarea}
                  style={{ minHeight: 90 }}
                  value={value}
                  onChange={(e) =>
                    setEdits((current) => ({ ...current, [block.key]: e.target.value }))
                  }
                />

                {block.is_overridden && block.default_instruction && (
                  <div className={ws.hint}>
                    <strong>Ships as:</strong> {block.default_instruction}
                  </div>
                )}

                <div className={ws.actions}>
                  <button
                    className={`${ws.primary} ${ws.tiny}`}
                    disabled={!dirty || !value.trim() || saveInstruction.isPending}
                    onClick={() =>
                      saveInstruction.mutate({ key: block.key, instruction: value })
                    }
                  >
                    Save wording
                  </button>
                  {block.is_overridden && (
                    <button
                      className={`${ws.secondary} ${ws.tiny}`}
                      disabled={resetInstruction.isPending}
                      onClick={() => resetInstruction.mutate(block.key)}
                    >
                      Reset to default
                    </button>
                  )}
                  {dirty && <span className={ws.hint}>Unsaved</span>}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <ConfirmDialog
        open={removing !== null}
        title={`Delete “${removing?.label}”?`}
        body={
          <>
            <p>
              The block is removed from your library and from any format that uses it. New
              challenges will stop asking for it.
            </p>
            <p>
              Challenges that already have its output keep it stored, but it will no longer appear
              on the page — nothing knows how to draw it any more.
            </p>
          </>
        }
        confirmLabel="Delete block"
        busy={remove.isPending}
        onConfirm={() => removing?.id != null && remove.mutate(removing.id)}
        onCancel={() => setRemoving(null)}
      />
    </>
  );
}

function instructionLength(text: string): number {
  return text.trim().length;
}
