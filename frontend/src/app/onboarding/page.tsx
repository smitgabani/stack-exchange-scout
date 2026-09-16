"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import styles from "./onboarding.module.css";

type Step = "yutori" | "gemini" | "done";

async function saveKey(provider: "yutori" | "gemini", apiKey: string): Promise<void> {
  const response = await fetch(`/api/settings/${provider}-key`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!response.ok) {
    throw new Error(`failed to save ${provider} key: ${response.status}`);
  }
}

export default function OnboardingPage() {
  const [step, setStep] = useState<Step>("yutori");
  const [yutoriKey, setYutoriKey] = useState("");
  const [geminiKey, setGeminiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const router = useRouter();
  const queryClient = useQueryClient();

  async function handleYutoriContinue() {
    if (!yutoriKey || saving) return;
    setSaving(true);
    try {
      await saveKey("yutori", yutoriKey);
      await queryClient.invalidateQueries({ queryKey: ["settings", "yutori-key", "status"] });
      setStep("gemini");
    } finally {
      setSaving(false);
    }
  }

  async function handleGeminiContinue() {
    if (!geminiKey || saving) return;
    setSaving(true);
    try {
      await saveKey("gemini", geminiKey);
      await queryClient.invalidateQueries({ queryKey: ["settings", "gemini-key", "status"] });
      setStep("done");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className={styles.bg}>
      <div className={styles.card}>
        <div className={styles.eyebrow}>Setup — step {step === "yutori" ? 1 : 2} of 2</div>
        <div className={styles.title}>
          {step === "yutori" ? "Connect Yutori" : step === "gemini" ? "Connect Gemini" : "All set"}
        </div>
        <div className={styles.subtitle}>
          {step === "yutori"
            ? "Discovery is blocked until a Yutori key is supplied."
            : step === "gemini"
              ? "Challenge generation is blocked until a Gemini key is supplied."
              : "Both keys are stored encrypted — never shown again in plain text."}
        </div>

        <div className={styles.steps}>
          <div className={`${styles.stepDot} ${step !== "yutori" ? styles.done : ""}`} />
          <div className={`${styles.stepDot} ${step === "done" ? styles.done : ""}`} />
        </div>

        {step === "yutori" && (
          <div className={styles.field}>
            <div className={styles.row}>
              <label htmlFor="yutori-key">Yutori API key</label>
              <div className={styles.badgeReq}>Required to start discovery</div>
            </div>
            <input
              id="yutori-key"
              type="password"
              placeholder="yut_••••••••••••"
              value={yutoriKey}
              onChange={(event) => setYutoriKey(event.target.value)}
              autoFocus
            />
            <div className={styles.hint}>
              Yutori bills per Scout run from a one-time signup credit — the app tracks estimated spend for you
              once this is set (see Settings).
            </div>
            <button className={styles.btnPrimary} disabled={!yutoriKey || saving} onClick={handleYutoriContinue}>
              {saving ? "Saving…" : "Save & continue"}
            </button>
          </div>
        )}

        {step === "gemini" && (
          <>
            <div className={styles.doneRow}>
              <div className={styles.checkmark}>✓</div>
              <div className={styles.hint}>Yutori key saved</div>
            </div>
            <div className={styles.field}>
              <div className={styles.row}>
                <label htmlFor="gemini-key">Gemini API key</label>
                <div className={styles.badgeReq}>Required for challenges</div>
              </div>
              <input
                id="gemini-key"
                type="password"
                placeholder="AIza••••••••••••"
                value={geminiKey}
                onChange={(event) => setGeminiKey(event.target.value)}
                autoFocus
              />
              <div className={styles.hint}>
                Gemini turns selected questions into challenges. OpenAI is available later, in Settings, as an
                optional alternative provider.
              </div>
              <button className={styles.btnPrimary} disabled={!geminiKey || saving} onClick={handleGeminiContinue}>
                {saving ? "Saving…" : "Save & finish setup"}
              </button>
            </div>
          </>
        )}

        {step === "done" && (
          <>
            <div className={styles.doneRow}>
              <div className={styles.checkmark}>✓</div>
              <div className={styles.hint}>Yutori key saved</div>
            </div>
            <div className={styles.doneRow}>
              <div className={styles.checkmark}>✓</div>
              <div className={styles.hint}>Gemini key saved</div>
            </div>
            <div className={styles.hint} style={{ marginTop: 4 }}>
              You&apos;re set up. Discovery starts on your next scout cycle — head to the dashboard.
            </div>
            <button className={styles.btnPrimary} onClick={() => router.replace("/")}>
              Go to dashboard
            </button>
          </>
        )}
      </div>
    </main>
  );
}
