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
  { href: "/scout", label: "Scout" },
  { href: "/accounts", label: "Accounts" },
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
            {NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={`${styles.navLink} ${
                  pathname === link.href || pathname.startsWith(`${link.href}/`)
                    ? styles.active
                    : ""
                }`}
              >
                {link.label}
              </Link>
            ))}
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
