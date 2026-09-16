"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { OnboardingGate } from "./onboarding-gate";

async function fetchSession(): Promise<{ authenticated: boolean }> {
  const response = await fetch("/api/auth/session");
  if (!response.ok) {
    throw new Error(`session check failed: ${response.status}`);
  }
  return response.json();
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["session"], queryFn: fetchSession });
  const authenticated = data?.authenticated ?? false;

  useEffect(() => {
    if (isLoading) return;
    if (!authenticated && pathname !== "/login") {
      router.replace("/login");
    } else if (authenticated && pathname === "/login") {
      router.replace("/");
    }
  }, [isLoading, authenticated, pathname, router]);

  // The login page renders itself regardless of session state — the check
  // above just bounces an already-authenticated visitor away from it.
  if (pathname === "/login") {
    return children;
  }

  if (isLoading || !authenticated) {
    return null;
  }

  async function handleLogout() {
    await fetch("/api/auth/logout", { method: "POST" });
    await queryClient.invalidateQueries({ queryKey: ["session"] });
    router.replace("/login");
  }

  return (
    <>
      <header style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: "16px", padding: "12px 24px", borderBottom: "1px solid #ddd" }}>
        <Link href="/settings">Settings</Link>
        <button onClick={handleLogout}>Log out</button>
      </header>
      <OnboardingGate>{children}</OnboardingGate>
    </>
  );
}
