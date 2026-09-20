"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./llm.module.css";

/**
 * Everything about how a question becomes a challenge, in one place.
 *
 * Mirrors the Yutori section deliberately: discovery has a home, and so should
 * the half of the pipeline that turns what discovery found into something to
 * solve.
 */
const TABS = [
  { href: "/llm/pipeline", label: "Pipeline", hint: "How a question becomes a challenge" },
  { href: "/llm/prompt", label: "Prompt", hint: "Edit, preview and test the curator prompt" },
  { href: "/llm/providers", label: "Providers", hint: "Keys, model and the active provider" },
  { href: "/llm/generations", label: "Generations", hint: "What produced each challenge" },
];

export default function LlmLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitle}>LLM</div>
        <div className={styles.sectionSub}>
          How a question becomes a challenge — what is sent, what is deliberately withheld, and
          what happens to the answer.
        </div>
      </div>

      <nav className={styles.tabs}>
        {TABS.map((tab) => {
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
