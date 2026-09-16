"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import styles from "./settings.module.css";

type Provider = "yutori" | "gemini" | "openai";

const PROVIDERS: { id: Provider; name: string; requirement: string }[] = [
  { id: "yutori", name: "Yutori", requirement: "Required — discovery is blocked without it" },
  { id: "gemini", name: "Gemini", requirement: "Required — active provider" },
  { id: "openai", name: "OpenAI", requirement: "Optional — alternative provider" },
];

async function fetchStatus(provider: Provider): Promise<boolean> {
  const response = await fetch(`/api/settings/${provider}-key/status`);
  if (!response.ok) {
    throw new Error(`status check failed: ${response.status}`);
  }
  const body = await response.json();
  return body.connected as boolean;
}

async function saveKey(provider: Provider, apiKey: string): Promise<void> {
  const response = await fetch(`/api/settings/${provider}-key`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!response.ok) {
    throw new Error(`failed to save ${provider} key: ${response.status}`);
  }
}

function KeyRow({ id, name, requirement }: { id: Provider; name: string; requirement: string }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  const { data: connected, isLoading } = useQuery({
    queryKey: ["settings", `${id}-key`, "status"],
    queryFn: () => fetchStatus(id),
  });

  async function handleSave() {
    if (!value || saving) return;
    setSaving(true);
    try {
      await saveKey(id, value);
      await queryClient.invalidateQueries({ queryKey: ["settings", `${id}-key`, "status"] });
      setEditing(false);
      setValue("");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.keyRow}>
      <div>
        <div className={styles.keyName}>{name}</div>
        <div className={styles.keyReq}>{requirement}</div>
      </div>
      {editing ? (
        <div className={styles.editRow}>
          <input
            type="password"
            placeholder="Paste new key"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            autoFocus
          />
          <button onClick={handleSave} disabled={!value || saving}>
            {saving ? "Saving…" : "Save"}
          </button>
          <button
            onClick={() => {
              setEditing(false);
              setValue("");
            }}
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className={styles.keyStatus}>
          <div className={`${styles.statusDot} ${isLoading ? "" : connected ? styles.set : styles.missing}`} />
          <div className={styles.statusText}>{isLoading ? "Checking…" : connected ? "Connected" : "Not set"}</div>
          <button className={styles.btnText} onClick={() => setEditing(true)}>
            {connected ? "Rotate" : "Add key"}
          </button>
        </div>
      )}
    </div>
  );
}

export default function SettingsPage() {
  return (
    <main className={styles.page}>
      <div className={styles.pageTitle}>Settings</div>
      <div className={styles.card}>
        <div className={styles.cardTitle}>API keys</div>
        {PROVIDERS.map((provider) => (
          <KeyRow key={provider.id} {...provider} />
        ))}
      </div>
    </main>
  );
}
