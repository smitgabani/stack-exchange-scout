"use client";

import { InfoButton } from "./info-button";
import ws from "./workspace.module.css";

type Version = {
  id: number;
  version: number;
  notes: string | null;
  is_active: boolean;
  created_at: string | null;
};

/** The history of a versioned template: the curator prompt or the query template. */
export function VersionTable({
  versions,
  onActivate,
  pending,
}: {
  versions: Version[];
  onActivate: (version: number) => void;
  pending: boolean;
}) {
  return (
    <div className={ws.tableWrap}>
      <table className={ws.table}>
        <thead>
          <tr>
            <th>Version</th>
            <th>Saved</th>
            <th>Notes</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.id}>
              <td>
                v{v.version} {v.is_active && <span className={`${ws.pill} ${ws.pillOn}`}>Active</span>}
              </td>
              <td>{v.created_at ? new Date(v.created_at).toLocaleString() : "—"}</td>
              <td>{v.notes ?? "—"}</td>
              <td>
                {!v.is_active && (
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <button
                      className={`${ws.secondary} ${ws.tiny}`}
                      onClick={() => onActivate(v.version)}
                      disabled={pending}
                    >
                      Activate
                    </button>
                    <InfoButton text="Makes this earlier version active again. The version that's currently active is kept in history, not deleted." />
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
