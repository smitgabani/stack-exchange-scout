"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./yutori.module.css";

/**
 * Everything about how Yutori discovers questions, under one section.
 *
 * Scouts, monitors, runs and accounts were five top-level destinations
 * competing with Questions and Challenges for the same nav bar, even though
 * they are all one subject: the machinery that produces candidates. They stay
 * separate routes — the monitors page alone is 800+ lines and has no business
 * sharing a render tree with the accounts list — and this layout is what makes
 * them read as one place.
 */
const TABS = [
  { href: "/yutori/scouts", label: "Scouts", hint: "Saved queries you can run" },
  { href: "/yutori/monitors", label: "Monitors", hint: "Live Scouts and remote objects" },
  { href: "/yutori/runs", label: "Runs", hint: "What each run cost and found" },
  { href: "/yutori/accounts", label: "Accounts", hint: "API keys and per-key spend" },
  { href: "/yutori/defaults", label: "Defaults", hint: "Query template and the settings every scout inherits" },
];

export default function YutoriLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitle}>Yutori</div>
        <div className={styles.sectionSub}>
          Discovery — how questions get found, what it costs, and which key paid for it.
        </div>
      </div>

      <nav className={styles.tabs}>
        {TABS.map((tab) => {
          // A run detail lives at /yutori/runs/<id> and a scout detail at
          // /yutori/scouts/<id>, so the tab has to stay lit on child routes
          // too — matching the header's own rule rather than inventing one.
          const active = pathname === tab.href || pathname.startsWith(`${tab.href}/`);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={`${styles.tab} ${active ? styles.tabActive : ""}`}
              aria-current={active ? "page" : undefined}
              title={tab.hint}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>

      <div className={styles.tabPanel}>{children}</div>
    </div>
  );
}
