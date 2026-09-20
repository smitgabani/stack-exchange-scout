"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { RunScoutButton } from "../run-scout-button";
import { useScout } from "../use-scout";
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

type Digest = { frequency_days: number; questions: number };
type Difficulty = { minimum: number; maximum: number };
type Profile = {
  data: { llm: { provider: "gemini" | "openai" }; digest: Digest; difficulty: Difficulty };
  version: number;
};

async function fetchProfile(): Promise<Profile> {
  const response = await fetch("/api/profile");
  if (!response.ok) {
    throw new Error(`failed to fetch profile: ${response.status}`);
  }
  return response.json();
}

async function switchProvider(provider: "gemini" | "openai"): Promise<Response> {
  return fetch("/api/profile", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ llm: { provider } }),
  });
}

function ActiveProviderCard() {
  const queryClient = useQueryClient();
  const { data: profile } = useQuery({ queryKey: ["profile"], queryFn: fetchProfile });
  const { data: openaiConnected } = useQuery({
    queryKey: ["settings", "openai-key", "status"],
    queryFn: () => fetchStatus("openai"),
  });
  const activeProvider = profile?.data.llm.provider ?? "gemini";

  async function handleSwitch(provider: "gemini" | "openai") {
    if (provider === activeProvider) return;
    if (provider === "openai" && !openaiConnected) return;
    const response = await switchProvider(provider);
    if (response.ok) {
      await queryClient.invalidateQueries({ queryKey: ["profile"] });
    }
  }

  return (
    <div className={styles.card}>
      <div className={styles.cardTitle}>Active LLM provider</div>
      <div className={styles.toggleRow}>
        <button
          className={`${styles.toggleOpt} ${activeProvider === "gemini" ? styles.on : ""}`}
          onClick={() => handleSwitch("gemini")}
        >
          Gemini
        </button>
        <button
          className={`${styles.toggleOpt} ${activeProvider === "openai" ? styles.on : ""} ${!openaiConnected ? styles.disabled : ""}`}
          onClick={() => handleSwitch("openai")}
          disabled={!openaiConnected}
        >
          {openaiConnected ? "OpenAI" : "OpenAI — add a key to enable"}
        </button>
      </div>
    </div>
  );
}

function ScoutCard() {
  const { scout, isLoading, isRunning, message } = useScout();

  const parked =
    scout?.external_status === "done" || scout?.external_status === "paused";
  const state = !scout?.configured
    ? "No Scout created yet"
    : isRunning
      ? "Running now"
      : parked
        ? "Parked \u2014 runs only when you ask"
        : "Active";

  return (
    <div className={styles.card}>
      <div className={styles.cardTitle}>Discovery Scout</div>
      <div className={styles.keyRow}>
        <div>
          <div className={styles.keyName}>{isLoading ? "Checking\u2026" : state}</div>
          <div className={styles.keyReq}>
            {scout?.last_synced_at
              ? `Last synced ${new Date(scout.last_synced_at).toLocaleString()}`
              : "Never synced."}
          </div>
          {scout?.rejection_reason && (
            <div className={styles.keyReq} style={{ color: "var(--coral)" }}>
              Yutori stopped this Scout: {scout.rejection_reason.replace(/_/g, " ")}
            </div>
          )}
          {scout?.last_sync_error && (
            <div className={styles.keyReq} style={{ color: "var(--coral)" }}>
              Last error: {scout.last_sync_error}
            </div>
          )}
          {message && <div className={styles.keyReq}>{message}</div>}
        </div>
        <div className={styles.scoutActions}>
          <RunScoutButton className={styles.btnText} label="Run now" />
          <Link className={styles.btnText} href="/yutori/scouts">
            Manage Scout \u2192
          </Link>
        </div>
      </div>
    </div>
  );
}

function DigestDifficultyCard() {
  const queryClient = useQueryClient();
  const { data: profile } = useQuery({ queryKey: ["profile"], queryFn: fetchProfile });

  const [digest, setDigest] = useState<Digest | null>(null);
  const [difficulty, setDifficulty] = useState<Difficulty | null>(null);
  const [loadedVersion, setLoadedVersion] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [showSaved, setShowSaved] = useState(false);

  // See topics/page.tsx for why this is done during render, not a useEffect.
  if (profile && loadedVersion !== profile.version) {
    setDigest(profile.data.digest);
    setDifficulty(profile.data.difficulty);
    setLoadedVersion(profile.version);
  }

  if (!digest || !difficulty) {
    return null;
  }

  async function handleSave() {
    setSaving(true);
    try {
      const response = await fetch("/api/profile", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ digest, difficulty }),
      });
      if (response.ok) {
        await queryClient.invalidateQueries({ queryKey: ["profile"] });
        setShowSaved(true);
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.card}>
      <div className={styles.cardTitle}>Digest & difficulty</div>

      <div className={styles.settingsField}>
        <div className={styles.fieldLabel}>Questions per digest</div>
        <div className={styles.stepper}>
          <button
            type="button"
            onClick={() => {
              setDigest({ ...digest, questions: Math.max(1, digest.questions - 1) });
              setShowSaved(false);
            }}
          >
            −
          </button>
          <div className={styles.stepVal}>{digest.questions}</div>
          <button
            type="button"
            onClick={() => {
              setDigest({ ...digest, questions: Math.min(10, digest.questions + 1) });
              setShowSaved(false);
            }}
          >
            +
          </button>
        </div>
      </div>

      <div className={styles.settingsField}>
        <div className={styles.fieldLabel}>Frequency</div>
        <div className={styles.freqRow}>
          {[1, 3, 7].map((days) => (
            <button
              key={days}
              type="button"
              className={`${styles.freqBtn} ${digest.frequency_days === days ? styles.on : ""}`}
              onClick={() => {
                setDigest({ ...digest, frequency_days: days });
                setShowSaved(false);
              }}
            >
              {days === 1 ? "Every day" : `Every ${days} days`}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.settingsField}>
        <div className={styles.fieldLabel}>Difficulty range</div>
        <div className={styles.diffRow}>
          <div className={styles.stepper}>
            <button
              type="button"
              onClick={() => {
                setDifficulty({ ...difficulty, minimum: Math.max(1, difficulty.minimum - 1) });
                setShowSaved(false);
              }}
            >
              −
            </button>
            <div className={styles.stepVal}>{difficulty.minimum}</div>
            <button
              type="button"
              onClick={() => {
                setDifficulty({ ...difficulty, minimum: Math.min(difficulty.maximum, difficulty.minimum + 1) });
                setShowSaved(false);
              }}
            >
              +
            </button>
          </div>
          <span>to</span>
          <div className={styles.stepper}>
            <button
              type="button"
              onClick={() => {
                setDifficulty({ ...difficulty, maximum: Math.max(difficulty.minimum, difficulty.maximum - 1) });
                setShowSaved(false);
              }}
            >
              −
            </button>
            <div className={styles.stepVal}>{difficulty.maximum}</div>
            <button
              type="button"
              onClick={() => {
                setDifficulty({ ...difficulty, maximum: Math.min(5, difficulty.maximum + 1) });
                setShowSaved(false);
              }}
            >
              +
            </button>
          </div>
        </div>
      </div>

      <div className={styles.saveRow}>
        {showSaved && <span className={styles.savedToast}>Saved</span>}
        <button className={styles.saveButton} onClick={handleSave} disabled={saving} type="button">
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
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
      <ActiveProviderCard />
      <ScoutCard />
      <DigestDifficultyCard />
    </main>
  );
}
