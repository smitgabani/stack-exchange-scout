"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { llmApi } from "@/lib/llm-api";
import ws from "../../workspace.module.css";

export default function GenerationsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["llm-generations"],
    queryFn: llmApi.generations,
  });

  const rows = data?.generations ?? [];
  // Grouped because the question this page answers is "did a prompt or model
  // change make things worse", and that is a per-batch question.
  const batches = new Map<string, number>();
  for (const row of rows) {
    const key = `${row.provider ?? "?"} · ${row.model ?? "?"} · v${row.prompt_version ?? "?"}`;
    batches.set(key, (batches.get(key) ?? 0) + 1);
  }

  return (
    <>
      <div className={ws.section}>
        <h2 className={ws.sectionTitle}>Generations</h2>
        <div className={ws.sub}>
          Every challenge with the provider, model and prompt version that produced it — recorded
          so a bad batch can be traced to its cause rather than guessed at.
        </div>

        {batches.size > 0 && (
          <div className={ws.stats} style={{ marginTop: 14 }}>
            {[...batches].map(([label, count]) => (
              <div className={ws.stat} key={label}>
                <div className={ws.statKey}>{label}</div>
                <div className={ws.statValue}>{count}</div>
                <div className={ws.statMeta}>challenge{count === 1 ? "" : "s"}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className={ws.section}>
        {isLoading ? (
          <div className={ws.empty}>Loading…</div>
        ) : isError ? (
          <div className={ws.empty}>Could not load generations.</div>
        ) : rows.length === 0 ? (
          <div className={ws.empty}>No challenges generated yet.</div>
        ) : (
          <div className={ws.tableWrap}>
            <table className={ws.table}>
              <thead>
                <tr>
                  <th>Challenge</th>
                  <th>Origin</th>
                  <th>Provider</th>
                  <th>Model</th>
                  <th>Prompt</th>
                  <th>Made</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <Link className={ws.textButton} href={`/challenge/${row.id}`}>
                        {row.question_title ?? "Untitled"}
                      </Link>
                    </td>
                    <td>
                      <span className={ws.pill}>
                        {row.source === "manual" ? "Your pick" : "Digest"}
                      </span>
                    </td>
                    <td>{row.provider ?? "—"}</td>
                    <td className={ws.mono}>{row.model ?? "—"}</td>
                    <td>v{row.prompt_version ?? "—"}</td>
                    <td>{row.created_at ? new Date(row.created_at).toLocaleDateString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
