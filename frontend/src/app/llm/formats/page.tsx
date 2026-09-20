"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { type ChallengeFormat, llmApi } from "@/lib/llm-api";
import { ConfirmDialog } from "../../confirm-dialog";
import ws from "../../workspace.module.css";
import styles from "../llm.module.css";

type Draft = { id: number | null; name: string; description: string; blocks: string[] };

const EMPTY: Draft = { id: null, name: "", description: "", blocks: [] };

export default function FormatsPage() {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [removing, setRemoving] = useState<ChallengeFormat | null>(null);

  const { data: catalogue } = useQuery({ queryKey: ["llm-blocks"], queryFn: llmApi.blocks });
  const { data } = useQuery({ queryKey: ["llm-formats"], queryFn: llmApi.formats });

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["llm-formats"] });
    await queryClient.invalidateQueries({ queryKey: ["llm-config"] });
  }

  const save = useMutation({
    mutationFn: async (d: Draft) => {
      const body = { name: d.name, blocks: d.blocks, description: d.description || undefined };
      return d.id === null ? llmApi.createFormat(body) : llmApi.updateFormat(d.id, body);
    },
    onSuccess: async (row) => {
      setMessage(`Saved “${row.name}”.`);
      setDraft(null);
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const makeDefault = useMutation({
    mutationFn: (id: number) => llmApi.makeFormatDefault(id),
    onSuccess: async (row) => {
      setMessage(`“${row.name}” is now the default — digests will use it.`);
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: number) => llmApi.deleteFormat(id),
    onSuccess: async () => {
      setMessage("Format deleted. Challenges made with it are untouched.");
      setRemoving(null);
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const blocks = catalogue?.blocks ?? [];
  const optional = blocks.filter((b) => !b.core);
  const core = blocks.filter((b) => b.core);

  function toggle(key: string) {
    if (!draft) return;
    setDraft({
      ...draft,
      blocks: draft.blocks.includes(key)
        ? draft.blocks.filter((k) => k !== key)
        : [...draft.blocks, key],
    });
  }

  return (
    <>
      <div className={ws.section}>
        <div className={ws.sectionHead}>
          <div>
            <h2 className={ws.sectionTitle}>Challenge formats</h2>
            <div className={ws.sub}>
              A format is a set of blocks. Turning one on changes what the model is asked for and
              what the challenge page renders — the two stay in step because both read the same
              registry. Currently in use:{" "}
              <strong>{data?.active.name ?? "Standard"}</strong>.
            </div>
          </div>
          <div className={ws.actions}>
            <button className={ws.primary} onClick={() => setDraft({ ...EMPTY })}>
              New format
            </button>
          </div>
        </div>
        {message && <div className={ws.notice}>{message}</div>}
      </div>

      {draft && (
        <div className={ws.section}>
          <h2 className={ws.sectionTitle}>{draft.id === null ? "New format" : "Edit format"}</h2>

          <input
            className={ws.input}
            placeholder="Name — e.g. “Deep dive”"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
          <input
            className={ws.input}
            style={{ marginTop: 10 }}
            placeholder="What it's for (optional)"
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
          />

          <div className={ws.blockLabel} style={{ marginTop: 20 }}>
            Always included
          </div>
          <div className={ws.hint}>
            The six fields every challenge has. They cannot be switched off — the digest email and
            every existing challenge depend on them.
          </div>
          <div className={styles.blockGrid}>
            {core.map((block) => (
              <div key={block.key} className={`${styles.blockCard} ${styles.blockCore}`}>
                <div className={styles.blockName}>{block.label}</div>
                <div className={styles.blockDesc}>{block.description}</div>
              </div>
            ))}
          </div>

          <div className={ws.blockLabel} style={{ marginTop: 22 }}>
            Optional blocks
          </div>
          <div className={styles.blockGrid}>
            {optional.map((block) => {
              const on = draft.blocks.includes(block.key);
              return (
                <button
                  type="button"
                  key={block.key}
                  className={`${styles.blockCard} ${on ? styles.blockOn : ""}`}
                  onClick={() => toggle(block.key)}
                  aria-pressed={on}
                >
                  <div className={styles.blockName}>
                    {block.label}
                    {block.gated && <span className={`${ws.pill} ${ws.pillBad}`}>Gated</span>}
                    {block.has_urls && <span className={ws.pill}>Links checked</span>}
                  </div>
                  <div className={styles.blockDesc}>{block.description}</div>
                </button>
              );
            })}
          </div>

          <div className={ws.hint} style={{ marginTop: 12 }}>
            Gated blocks only appear after every hint has been revealed. Blocks with links have
            each URL checked at generation time; ones that do not resolve are dropped.
          </div>

          <div className={ws.actions} style={{ marginTop: 16 }}>
            <button
              className={ws.primary}
              onClick={() => save.mutate(draft)}
              disabled={!draft.name.trim() || save.isPending}
            >
              {save.isPending ? "Saving…" : "Save format"}
            </button>
            <button className={ws.secondary} onClick={() => setDraft(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className={ws.section}>
        {!data || data.formats.length === 0 ? (
          <div className={ws.empty}>
            No formats saved. Challenges use the six standard blocks until you create one.
          </div>
        ) : (
          <div className={ws.list}>
            {data.formats.map((format) => (
              <div key={format.id} className={ws.item}>
                <div>
                  <div className={ws.itemName}>
                    {format.name}
                    {format.is_default && (
                      <span className={`${ws.pill} ${ws.pillOn}`}>Default</span>
                    )}
                  </div>
                  <div className={ws.itemMeta}>
                    {format.description || "No description"} · {format.blocks.length} blocks
                  </div>
                  <div className={ws.itemQuery}>{format.blocks.join(" · ")}</div>
                </div>
                <div className={ws.itemSide}>
                  <div className={ws.actions}>
                    {!format.is_default && (
                      <button
                        className={`${ws.secondary} ${ws.tiny}`}
                        onClick={() => makeDefault.mutate(format.id)}
                        disabled={makeDefault.isPending}
                      >
                        Make default
                      </button>
                    )}
                    <button
                      className={`${ws.secondary} ${ws.tiny}`}
                      onClick={() =>
                        setDraft({
                          id: format.id,
                          name: format.name,
                          description: format.description ?? "",
                          blocks: format.optional_blocks,
                        })
                      }
                    >
                      Edit
                    </button>
                    <button
                      className={`${ws.danger} ${ws.tiny}`}
                      onClick={() => setRemoving(format)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={removing !== null}
        title={`Delete “${removing?.name}”?`}
        body={
          <p>
            The format is removed. Challenges already generated with it keep rendering exactly as
            they are — each one stores its own content and the format&apos;s name.
          </p>
        }
        confirmLabel="Delete format"
        busy={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing.id)}
        onCancel={() => setRemoving(null)}
      />
    </>
  );
}
