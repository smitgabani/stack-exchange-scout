"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { fetchBootstrap } from "./auth-gate";

export function OnboardingGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  // No fetch of its own: AuthGate has already asked, under the same key, and
  // the answer carries both keys. Two requests per page load removed.
  const { data, isLoading } = useQuery({ queryKey: ["bootstrap"], queryFn: fetchBootstrap });

  const setupComplete = data?.onboarding_complete ?? false;

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
