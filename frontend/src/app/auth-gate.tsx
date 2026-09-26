"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { json } from "@/lib/api";
import styles from "./header.module.css";
import { OnboardingGate } from "./onboarding-gate";

const NAV_LINKS = [
  { href: "/topics", label: "Topics" },
  { href: "/questions", label: "Questions" },
  { href: "/challenges", label: "Challenges" },
  // Scouts, monitors, runs and accounts are one subject — how questions get
  // discovered — so they share a nav entry and split into tabs inside it.
  // `match` keeps the entry lit across the whole section while the link itself
  // goes straight to a real page rather than relying on /yutori's redirect.
  { href: "/yutori/scouts", label: "Yutori", match: "/yutori" },
  // The other half of the pipeline: discovery finds questions, this turns them
  // into challenges. Same shape of section, same reason for existing.
  { href: "/llm/pipeline", label: "LLM", match: "/llm" },
];

export type Bootstrap = {
  authenticated: boolean;
  onboarding_complete: boolean;
  yutori_key: boolean;
  gemini_key: boolean;
};

/**
 * The three questions every page load used to ask separately: is there a
 * session, is the Yutori key stored, is the Gemini key stored. Three round
 * trips before anything rendered, each one a Vercel function proxying to Fly.
 *
 * One query key, so `OnboardingGate` reads the same cached answer rather than
 * fetching again.
 */
export const fetchBootstrap = () => json<Bootstrap>("/api/auth/bootstrap");

export function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["bootstrap"], queryFn: fetchBootstrap });
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
    await queryClient.invalidateQueries({ queryKey: ["bootstrap"] });
    router.replace("/login");
  }

  return (
    <>
      <header className={styles.header}>
        <div className={styles.inner}>
          <Link href="/" className={styles.brand}>
            {/* eslint-disable-next-line @next/next/no-img-element -- a fixed-size
                inline SVG mark needs no optimisation pipeline */}
            <img src="/icon.svg" alt="" width={24} height={24} />
            Stack Exchange Scout
          </Link>
          <nav className={styles.nav}>
            {NAV_LINKS.map((link) => {
              const prefix = "match" in link ? link.match : link.href;
              const active = pathname === prefix || pathname.startsWith(`${prefix}/`);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`${styles.navLink} ${active ? styles.active : ""}`}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
          {/* A sibling of the nav rather than its last child: on a phone the
              nav becomes a full-width scrolling strip, and the way out of the
              app should not be something you have to scroll to find. */}
          <button className={styles.logout} onClick={handleLogout}>
            Log out
          </button>
        </div>
      </header>
      <OnboardingGate>{children}</OnboardingGate>
    </>
  );
}
