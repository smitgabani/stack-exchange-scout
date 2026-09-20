"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { money, scoutApi, when } from "@/lib/scout-api";
import styles from "../../../workspace.module.css";

export default function AccountPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);

  const { data: accounts } = useQuery({ queryKey: ["accounts"], queryFn: scoutApi.listAccounts });
  const { data: objects, isLoading } = useQuery({
    queryKey: ["account-objects", id],
    queryFn: () => scoutApi.accountObjects(id),
  });

  const account = accounts?.accounts.find((a) => a.id === id);
  const runs = account?.run_count ?? 0;
  // Yutori's own count, beside ours. They should agree; when they don't, one
  // of the two is missing runs and that is worth seeing.
  const theirRuns = objects?.usage?.scout_runs ?? null;

  return (
    <main className={styles.page}>
      <Link className={styles.back} href="/yutori/accounts">← All accounts</Link>

      <div className={styles.head}>
        <div>
          <div className={styles.title}>{account?.label ?? "Account"}</div>
          <div className={`${styles.sub} ${styles.mono}`}>
            fingerprint {account?.account_fingerprint ?? "not recorded"} ·{" "}
            {account?.is_active ? "active" : "stored"} · added {when(account?.created_at)}
          </div>
        </div>
      </div>

      <div className={styles.blocks}>
        <div className={`${styles.block} ${styles.cream}`}>
          <div className={styles.blockLabel}>Charged through this app</div>
          <div className={styles.blockValue}>{money(account?.spend_usd ?? 0)}</div>
          <div className={styles.blockNote}>{runs} run{runs === 1 ? "" : "s"} · our own ledger</div>
        </div>
        <div className={`${styles.block} ${styles.cream}`}>
          <div className={styles.blockLabel}>Yutori reports</div>
          <div className={styles.blockValue}>{theirRuns === null ? "—" : theirRuns}</div>
          <div className={styles.blockNote}>
            {theirRuns === null
              ? "not available"
              : theirRuns === runs
                ? "30 days · matches ours"
                : `30 days · differs from our ${runs}`}
          </div>
        </div>
        <div className={`${styles.block} ${account?.is_active ? styles.mint : styles.soft}`}>
          <div className={styles.blockLabel}>Status</div>
          <div className={styles.blockValue}>{account?.is_active ? "Active" : "Stored"}</div>
          <div className={styles.blockNote}>
            {account?.is_active
              ? "runs are charged here"
              : "make it active to run against this account"}
          </div>
        </div>
      </div>

      {objects?.error && (
        <div className={styles.alert}>
          <strong>Could not read this account.</strong> {objects.error}
        </div>
      )}

      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Everything that exists under this key</h2>
        <p className={styles.hint}>
          Listed from Yutori directly, not from our records — an object this app never created, or
          created and lost track of, is exactly the one that would otherwise keep billing unnoticed.
        </p>
        {isLoading ? (
          <div className={styles.empty}>Checking with Yutori…</div>
        ) : !objects?.scouts.length ? (
          <div className={styles.empty}>Nothing exists under this key.</div>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr><th>Scout</th><th>Status</th><th>Created</th><th>Updates</th><th>Tracked here</th></tr>
              </thead>
              <tbody>
                {objects.scouts.map((scout) => (
                  <tr key={scout.id}>
                    <td className={styles.mono}>{scout.id}</td>
                    <td>{scout.status}</td>
                    <td>{when(scout.created_at)}</td>
                    <td className={styles.num}>{scout.update_count ?? "—"}</td>
                    <td className={scout.tracked ? styles.ok : styles.bad}>
                      {scout.tracked ? "yes" : "untracked"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {objects?.scouts.some((s) => !s.tracked && s.status === "active") && (
          <div className={styles.alert}>
            <strong>An active Scout here is not tracked by this app.</strong> It will keep running
            on its own interval, and nothing in this app is watching it.
          </div>
        )}
      </div>
    </main>
  );
}
