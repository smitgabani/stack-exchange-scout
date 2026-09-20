"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
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
  { href: "/settings", label: "Settings" },
];

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
            <button className={styles.logout} onClick={handleLogout}>
              Log out
            </button>
          </nav>
        </div>
      </header>
      <OnboardingGate>{children}</OnboardingGate>
    </>
  );
}
