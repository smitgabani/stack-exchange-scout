"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { MODE_LABEL, duration, money, scoutApi, when } from "@/lib/scout-api";
import styles from "../../workspace.module.css";

/**
 * Every run, across every scout — the tab that had no page before.
 *
 * Run history existed only per definition, so answering "what have I spent
 * lately" meant opening each scout in turn. `GET /scout-runs` already returned
 * the whole list; nothing rendered it.
 */
export default function RunsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["runs"],
    queryFn: scoutApi.listRuns,
  });

  const runs = data?.runs ?? [];
  const totalSpend = runs.reduce((sum, run) => sum + (run.cost_usd ?? 0), 0);
  const found = runs.reduce((sum, run) => sum + (run.questions_found ?? 0), 0);

  return (
    <>
      <div className={styles.sectionHead}>
        <div>
          <h2 className={styles.sectionTitle}>Runs</h2>
          <div className={styles.sub}>
            What each run cost, how long it took, and how many questions it produced.
          </div>
        </div>
      </div>

      {runs.length > 0 && (
        <div className={styles.stats}>
          <div className={styles.stat}>
            <div className={styles.statKey}>Runs</div>
            <div className={styles.statValue}>{runs.length}</div>
          </div>
          <div className={styles.stat}>
            <div className={styles.statKey}>Total spend</div>
            <div className={styles.statValue}>{money(totalSpend)}</div>
          </div>
          <div className={styles.stat}>
            <div className={styles.statKey}>Questions found</div>
            <div className={styles.statValue}>{found}</div>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className={styles.empty}>Loading…</div>
      ) : isError ? (
        <div className={styles.empty}>Could not load runs.</div>
      ) : runs.length === 0 ? (
        <div className={styles.empty}>
          No runs yet. Start one from a scout — the button names the price first.
        </div>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Started</th>
                <th>Kind</th>
                <th>Status</th>
                <th>Cost</th>
                <th>Took</th>
                <th>Found</th>
                <th>Account</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td>{when(run.started_at)}</td>
                  <td>{MODE_LABEL[run.kind === "scout" ? "scout" : "research"]}</td>
                  <td>
                    <span
                      className={`${styles.pill} ${
                        run.status === "succeeded"
                          ? styles.pillOn
                          : run.status === "running"
                            ? styles.pillLive
                            : styles.pillBad
                      }`}
                    >
                      {run.status}
                    </span>
                  </td>
                  <td className={styles.mono}>{money(run.cost_usd)}</td>
                  <td>{duration(run.duration_seconds)}</td>
                  <td>{run.questions_found ?? "—"}</td>
                  <td>{run.account_label ?? "—"}</td>
                  <td>
                    <Link className={styles.textButton} href={`/yutori/runs/${run.id}`}>
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
