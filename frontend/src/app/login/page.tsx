"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import styles from "./login.module.css";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showError, setShowError] = useState(false);
  const [checking, setChecking] = useState(false);
  const router = useRouter();
  const queryClient = useQueryClient();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (checking) return;

    setChecking(true);
    setShowError(false);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!response.ok) {
        setShowError(true);
        return;
      }
      await queryClient.invalidateQueries({ queryKey: ["session"] });
      router.replace("/");
    } finally {
      setChecking(false);
    }
  }

  return (
    <main className={styles.bg}>
      <form className={styles.card} onSubmit={handleSubmit}>
        <div className={styles.iconBadge}>🔒</div>
        <div className={styles.title}>Enter the access password</div>
        <div className={styles.subtitle}>
          This is a personal tool. One shared password keeps it away from anyone who just finds the URL.
        </div>

        <div className={styles.fieldWrap}>
          <input
            type={showPassword ? "text" : "password"}
            placeholder="Password"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              setShowError(false);
            }}
            autoFocus
          />
          <button
            type="button"
            className={styles.toggleButton}
            onClick={() => setShowPassword((value) => !value)}
          >
            {showPassword ? "Hide" : "Show"}
          </button>
        </div>

        {showError && <div className={styles.error}>That password isn&apos;t right — try again.</div>}

        <button type="submit" className={styles.submitButton} disabled={checking}>
          {checking ? "Checking…" : "Unlock"}
        </button>

        <div className={styles.footnote}>No accounts here — just this one password for the one person using this app.</div>
      </form>
    </main>
  );
}
