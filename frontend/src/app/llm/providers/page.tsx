"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { llmApi } from "@/lib/llm-api";
import { InfoButton } from "../../info-button";
import ws from "../../workspace.module.css";

type Provider = "gemini" | "openai";

const PROVIDERS: { id: Provider; name: string; note: string }[] = [
  { id: "gemini", name: "Gemini", note: "Default provider" },
  { id: "openai", name: "OpenAI", note: "Alternative provider" },
];

async function fetchStatus(provider: Provider): Promise<boolean> {
  const response = await fetch(`/api/settings/${provider}-key/status`);
  if (!response.ok) throw new Error(`status check failed: ${response.status}`);
  return (await response.json()).connected;
}

async function saveKey(provider: Provider, apiKey: string): Promise<void> {
  const response = await fetch(`/api/settings/${provider}-key`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!response.ok) throw new Error(`failed to save the ${provider} key`);
}

function KeyRow({ id, name, note, active }: { id: Provider; name: string; note: string; active: boolean }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const [editing, setEditing] = useState(false);

  const { data: connected } = useQuery({
    queryKey: ["settings", `${id}-key`, "status"],
    queryFn: () => fetchStatus(id),
  });

  const save = useMutation({
    mutationFn: () => saveKey(id, value),
    onSuccess: async () => {
      setValue("");
      setEditing(false);
      await queryClient.invalidateQueries({ queryKey: ["settings", `${id}-key`, "status"] });
    },
  });

  return (
    <div className={ws.item}>
      <div>
        <div className={ws.itemName}>
          {name}
          {active && <span className={`${ws.pill} ${ws.pillOn}`}>In use</span>}
          {connected ? (
            <span className={ws.pill}>Key stored</span>
          ) : (
            <span className={`${ws.pill} ${ws.pillBad}`}>No key</span>
          )}
        </div>
        <div className={ws.itemMeta}>{note}</div>
        {editing && (
          <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
            <input
              className={ws.input}
              type="password"
              value={value}
              placeholder={`Paste your ${name} API key`}
              onChange={(e) => setValue(e.target.value)}
              autoComplete="off"
            />
            <button
              className={`${ws.primary} ${ws.tiny}`}
              onClick={() => save.mutate()}
              disabled={!value || save.isPending}
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
            <InfoButton text="Stores this key encrypted at rest, replacing any key already saved for this provider. It cannot be read back afterward, only replaced." />
            <button className={`${ws.secondary} ${ws.tiny}`} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        )}
        {save.isError && <div className={ws.hint}>Could not save that key.</div>}
      </div>
      <div className={ws.itemSide}>
        <div className={ws.actions}>
          <button className={`${ws.secondary} ${ws.tiny}`} onClick={() => setEditing((v) => !v)}>
            {connected ? "Replace key" : "Add key"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ProvidersPage() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const { data: config } = useQuery({ queryKey: ["llm-config"], queryFn: llmApi.config });

  const { data: openaiConnected } = useQuery({
    queryKey: ["settings", "openai-key", "status"],
    queryFn: () => fetchStatus("openai"),
  });

  const switchProvider = useMutation({
    mutationFn: async (provider: Provider) => {
      const response = await fetch("/api/profile", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ llm: { provider } }),
      });
      if (!response.ok) throw new Error("could not switch provider");
    },
    onSuccess: async () => {
      setMessage("Provider switched. New challenges will use it.");
      await queryClient.invalidateQueries({ queryKey: ["llm-config"] });
      await queryClient.invalidateQueries({ queryKey: ["profile"] });
    },
    onError: (e: Error) => setMessage(e.message),
  });

  if (!config) return <div className={ws.empty}>Loading…</div>;

  return (
    <>
      <div className={ws.section}>
        <h2 className={ws.sectionTitle}>Active provider</h2>
        <div className={ws.sub}>
          Which service generates challenges. The prompt and the validation rules are identical
          either way — only the model differs.
        </div>
        <div className={ws.seg} style={{ marginTop: 12, alignItems: "center" }}>
          {PROVIDERS.map((p) => {
            const disabled = p.id === "openai" && !openaiConnected;
            return (
              <button
                key={p.id}
                className={`${ws.segItem} ${config.provider === p.id ? ws.pillOn : ""}`}
                onClick={() => config.provider !== p.id && switchProvider.mutate(p.id)}
                disabled={disabled || switchProvider.isPending}
                title={disabled ? "Add an OpenAI key first" : undefined}
              >
                {p.name}
              </button>
            );
          })}
          <InfoButton text="Switches which service generates future challenges. Challenges already generated keep the provider and model that made them — only new generations use the switch." />
        </div>
        {message && <div className={ws.notice}>{message}</div>}
      </div>

      <div className={ws.section}>
        <h2 className={ws.sectionTitle}>Keys</h2>
        <div className={ws.sub}>
          Stored encrypted at rest and never returned by any endpoint — a stored key can be
          replaced but not read back.
        </div>
        <div className={ws.list}>
          {PROVIDERS.map((p) => (
            <KeyRow key={p.id} id={p.id} name={p.name} note={p.note} active={config.provider === p.id} />
          ))}
        </div>
      </div>
    </>
  );
}
