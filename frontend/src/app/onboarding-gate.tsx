"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

async function fetchKeyConnected(provider: "yutori" | "gemini"): Promise<boolean> {
  const response = await fetch(`/api/settings/${provider}-key/status`);
  if (!response.ok) {
    throw new Error(`${provider} status check failed: ${response.status}`);
  }
  const body = await response.json();
  return body.connected as boolean;
}

export function OnboardingGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  const yutori = useQuery({
    queryKey: ["settings", "yutori-key", "status"],
    queryFn: () => fetchKeyConnected("yutori"),
  });
  const gemini = useQuery({
    queryKey: ["settings", "gemini-key", "status"],
    queryFn: () => fetchKeyConnected("gemini"),
  });

  const isLoading = yutori.isLoading || gemini.isLoading;
  const setupComplete = (yutori.data ?? false) && (gemini.data ?? false);

  useEffect(() => {
    if (isLoading) return;
    // Only redirect *to* onboarding when incomplete. Deliberately no
    // redirect *away* from it on completion — the onboarding page's own
    // "Go to dashboard" button owns that transition, so the user sees the
    // final confirmation screen instead of being yanked away mid-flow the
    // instant the second key is saved.
    if (!setupComplete && pathname !== "/onboarding") {
      router.replace("/onboarding");
    }
  }, [isLoading, setupComplete, pathname, router]);

  // The onboarding page always renders itself once reached — it owns its
  // own exit (the "Go to dashboard" button), not this gate.
  if (pathname === "/onboarding") {
    return children;
  }

  if (isLoading || !setupComplete) {
    return null;
  }

  return children;
}
