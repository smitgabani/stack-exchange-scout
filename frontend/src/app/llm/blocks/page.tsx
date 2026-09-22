"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { type BlockMeta, llmApi } from "@/lib/llm-api";
import { ConfirmDialog } from "../../confirm-dialog";
import { InfoButton } from "../../info-button";
import ws from "../../workspace.module.css";
import styles from "../llm.module.css";

/**
 * The block library: what each block asks the model for, and how it renders.
 *
 * Two tiers, and the difference is structural rather than a matter of taste.
 * Six blocks are NOT NULL columns on `challenges`, demanded by validation on
 * every generation and read directly by the digest email — those can be
 * reworded but not reshaped or removed. Everything else lives in the database
 * and can be changed or deleted freely, whether it shipped with the app or you
 * wrote it.
 */

type Draft = {
  id: number | null;
  key: string;
  label: string;
  description: string;
  kind: string;
  instruction: string;
  gated: boolean;
  /** The layout it had when the draft opened, to warn about reshaping. */
  originalKind: string | null;
};

const EMPTY: Draft = {
  id: null,
  key: "",
  label: "",
  description: "",
  kind: "checklist",
  instruction: "",
  gated: false,
  originalKind: null,
};

/** What each layout does with the model's answer, in the reader's terms. */
const KIND_HELP: Record<string, string> = {
  prose: "One or more paragraphs of plain text.",
  chips: "Short labels in rounded pills, like the Concepts row.",
  list: "A bulleted list of short lines.",
  checklist: "A list with tick marks, for things to verify one by one.",
  steps: "A numbered list, each step with an optional line of detail.",
  definition_list: "Term-and-definition pairs, like a glossary.",
  resource_list: "Links, each with a title and a reason. Every URL is checked before it is stored, and dead ones are dropped.",
  stat: "One prominent figure with a line of rationale under it.",
  diagram: "A Mermaid diagram — flowchart, sequence or state — drawn on the page.",
  progressive_hints: "Hints revealed one at a time, behind a button.",
  rating: "A number out of five.",
};

/** Which layouts store the same thing, so swapping between them is lossless. */
const SHAPE_OF: Record<string, string> = {
  prose: "text",
  chips: "a list of short strings",
  list: "a list of short strings",
  checklist: "a list of short strings",
  steps: "ordered steps",
  definition_list: "term and definition pairs",
  resource_list: "links",
  stat: "a figure and a rationale",
  diagram: "diagram source",
  progressive_hints: "labelled hints",
  rating: "a number",
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
    await queryClient.invalidateQueries({ queryKey: ["llm-formats"] });
  }

  const saveBlock = useMutation({
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
      setMessage(`Saved “${row.label}”. Challenges generated from now on use it.`);
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
  // `editable` replaced `custom` when the optional blocks moved into the
  // database; fall back so this page still works against the previous backend.
  const isEditable = (b: BlockMeta) => b.editable ?? b.custom;
  const editable = blocks.filter(isEditable);
  const core = blocks.filter((b) => !isEditable(b));
  const kinds = data?.custom_kinds ?? [];
  const limit = data?.max_instruction_chars ?? 1200;

  const backendTooOld = Boolean(data) && data?.custom_kinds === undefined;

  function infoFor(block: BlockMeta): string {
    const layout = KIND_HELP[block.kind] ?? "A layout this version of the page does not know.";
    const gated = block.gated
      ? " Hidden until every hint has been revealed, and exempt from the spoiler check."
      : "";
    return `Renders as ${block.kind.replace(/_/g, " ")}: ${layout}${gated}`;
  }

  function openEdit(block: BlockMeta) {
    setDraft({
      id: block.id,
      key: block.key,
      label: block.label,
      description: block.description,
      kind: block.kind,
      instruction: block.instruction,
      gated: block.gated,
      originalKind: block.kind,
    });
  }

  const reshaping =
    draft?.originalKind != null &&
    draft.kind !== draft.originalKind &&
    SHAPE_OF[draft.kind] !== SHAPE_OF[draft.originalKind];

  return (
    <>
      <div className={ws.section}>
        <div className={ws.sectionHead}>
          <div>
            <h2 className={ws.sectionTitle}>Block library</h2>
            <div className={ws.sub}>
              Every block is one instruction to the model plus a layout for the answer. Change
              either, or add your own. Edits apply to challenges generated from now on — existing
              ones keep what they were made with.
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
            <InfoButton text="Defines a new block: a question put to the model and a layout for its answer. Nothing is saved until you press Save block, and no challenge asks for it until you add it to a format." />
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

          {/* Changing the layout within one shape is lossless; across shapes it
              orphans whatever is already stored, which is worth saying before
              the save rather than after. */}
          {reshaping && draft.originalKind && (
            <div className={ws.alert} style={{ marginTop: 12 }}>
              <strong>
                {draft.originalKind.replace(/_/g, " ")} stores {SHAPE_OF[draft.originalKind]};{" "}
                {draft.kind.replace(/_/g, " ")} stores {SHAPE_OF[draft.kind]}.
              </strong>{" "}
              Challenges that already have this block will stop showing it, because what they
              stored no longer fits the new layout. Their content is kept, not deleted. New
              challenges are unaffected.
            </div>
          )}

          <div className={ws.field} style={{ marginTop: 18 }}>
            <span className={ws.label}>
              What to ask the model ({draft.instruction.trim().length}/{limit})
            </span>
            <textarea
              className={ws.textarea}
              placeholder="List what to verify before calling this done. Do not state the solution."
              value={draft.instruction}
              onChange={(e) => setDraft({ ...draft, instruction: e.target.value })}
            />
            <span className={ws.hint}>
              Added to the instruction sent on every generation, alongside the other blocks in the
              format.
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
              onClick={() => saveBlock.mutate(draft)}
              disabled={!draft.label.trim() || !draft.instruction.trim() || saveBlock.isPending}
            >
              {saveBlock.isPending ? "Saving…" : "Save block"}
            </button>
            <InfoButton text="Saves the block to your library. It does nothing on its own — add it to a format under LLM → Formats for challenges to start asking for it." />
            <button className={ws.secondary} onClick={() => setDraft(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className={ws.section}>
        <div className={ws.sectionHead}>
          <h2 className={ws.sectionTitle}>Optional blocks</h2>
        </div>
        <div className={ws.hint}>
          Everything a format can add on top of the six below. Change the wording, change how it
          renders, or delete it — nothing structural depends on these.
        </div>

        {editable.length === 0 ? (
          <div className={ws.empty}>
            No optional blocks. Press <strong>New block</strong> to add one.
          </div>
        ) : (
          <div className={ws.list}>
            {editable.map((block) => (
              <div key={block.key} className={ws.item}>
                <div>
                  <div className={ws.itemName}>
                    {block.label}
                    <InfoButton text={infoFor(block)} />
                    {block.gated && <span className={`${ws.pill} ${ws.pillBad}`}>Gated</span>}
                    {block.has_urls && <span className={ws.pill}>Links checked</span>}
                  </div>
                  <div className={ws.itemMeta}>
                    Renders as {block.kind.replace(/_/g, " ")} · {block.key}
                  </div>
                  <div className={ws.itemQuery}>{block.instruction}</div>
                </div>
                <div className={ws.itemSide}>
                  <div className={ws.actions}>
                    <button
                      className={`${ws.secondary} ${ws.tiny}`}
                      onClick={() => openEdit(block)}
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
        )}
      </div>

      <div className={ws.section}>
        <h2 className={ws.sectionTitle}>Core blocks</h2>
        <div className={ws.hint}>
          Every challenge has these six, and the digest email is built from five of them. They are
          real columns on the challenges table and validation demands their shape on every
          generation — so you can change what each one asks for, but not how it renders, and they
          cannot be removed.
        </div>

        <div className={ws.list}>
          {core.map((block) => {
            const value = edits[block.key] ?? block.instruction;
            const dirty = value !== block.instruction;
            return (
              <div key={block.key} className={ws.card}>
                <div className={ws.itemName}>
                  {block.label}
                  <InfoButton text={infoFor(block)} />
                  <span className={ws.pill}>Always included</span>
                  {block.is_overridden && (
                    <span className={`${ws.pill} ${ws.pillLive}`}>Reworded</span>
                  )}
                </div>
                <div className={ws.itemMeta}>
                  {/* Stated on every card rather than only in the hint above:
                      the layout being fixed is the question people ask here. */}
                  Renders as {block.kind.replace(/_/g, " ")} — fixed · {block.description}
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
                    onClick={() => saveInstruction.mutate({ key: block.key, instruction: value })}
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
