"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { type MonitorRemote, every, money, scoutApi, when } from "@/lib/scout-api";
import { ConfirmDialog } from "../confirm-dialog";
import { InfoButton } from "../info-button";
import ws from "../workspace.module.css";

/**
 * Keeping a live monitor in step with its scout (M13 F6/F7).
 *
 * Saving settings changes what the *next* monitor would be created with. A
 * monitor already running at Yutori keeps what it was created with until it
 * is told otherwise — so this compares the two and offers the free PATCH
 * that brings it in line. Only the start time can't be patched; that one
 * needs the monitor replaced, which starts a paid run.
 */

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "public" : "private";
  if (typeof value === "number") return every(value);
  if (typeof value === "string") return value.length > 60 ? `${value.slice(0, 57)}…` : value;
  return "custom";
}

export function LiveMonitorBanner({ definitionId }: { definitionId: string }) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [confirmReplace, setConfirmReplace] = useState(false);

  const { data: monitors } = useQuery({ queryKey: ["monitors"], queryFn: scoutApi.monitors });
  const live = monitors?.monitors.find((m) => m.definition_id === definitionId && !m.superseded);

  const remote = useQuery({
    queryKey: ["monitor-remote", live?.id],
    queryFn: () => scoutApi.monitorRemote(live!.id),
    enabled: Boolean(live),
    retry: false,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["monitor-remote"] });
    await queryClient.invalidateQueries({ queryKey: ["monitors"] });
  };

  const apply = useMutation({
    mutationFn: () => scoutApi.applyToMonitor(live!.id),
    onSuccess: async (result) => {
      setMessage(
        ["Applied to the live monitor. Free — it uses these settings from its next run.", ...result.warnings].join(" "),
      );
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const replace = useMutation({
    mutationFn: () => scoutApi.runDefinition(definitionId, "scout", { replace: true }),
    onSuccess: async (result) => {
      setMessage(`Replaced: the old monitor was stopped and ${result.external_id} started.`);
      await refresh();
      await queryClient.invalidateQueries({ queryKey: ["definition", definitionId] });
    },
    onError: (e: Error) => setMessage(e.message),
  });

  if (!live) return null;

  const data = remote.data;
  const cost = monitors?.run_cost_usd ?? 0.35;

  return (
    <>
      {message && <div className={ws.notice}>{message}</div>}
      {remote.isError ? (
        <div className={ws.notice}>
          Couldn&apos;t read the live monitor from Yutori: {(remote.error as Error).message}
        </div>
      ) : !data ? (
        <div className={ws.notice}>Checking the live monitor at Yutori…</div>
      ) : data.diff.length === 0 && !data.start_changed ? (
        <div className={ws.notice}>
          <strong>Live monitor matches these settings.</strong> It runs{" "}
          {every(data.remote.output_interval ?? live.output_interval)}, next {when(data.remote.next_run)}.
          Location, Yutori email and subscribers aren&apos;t reported back by Yutori, so Apply sends
          them anyway if you&apos;ve changed them.{" "}
          <button className={ws.textButton} onClick={() => apply.mutate()} disabled={apply.isPending}>
            Apply anyway
          </button>
        </div>
      ) : (
        <div className={ws.notice} style={{ background: "var(--cream)", border: "none" }}>
          <strong>Your live monitor is using older settings.</strong>{" "}
          {data.diff.map((d) => `${d.label}: ${show(d.live)} → ${show(d.saved)}`).join(" · ")}
          {data.start_changed && " · Start time changed (needs a replace)"}
          <div className={ws.actions} style={{ marginTop: 10 }}>
            {data.diff.length > 0 && (
              <>
                <button className={`${ws.primary} ${ws.tiny}`} onClick={() => apply.mutate()} disabled={apply.isPending}>
                  {apply.isPending ? "Applying…" : "Apply to live monitor · free"}
                </button>
                <InfoButton text="Sends this scout's saved settings to the monitor already running at Yutori. Free — it doesn't start a run; the monitor uses them from its next scheduled run." />
              </>
            )}
            {data.start_changed && (
              <button
                className={`${ws.secondary} ${ws.tiny}`}
                onClick={() => setConfirmReplace(true)}
                disabled={replace.isPending}
              >
                Replace… · {money(cost)}
              </button>
            )}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirmReplace}
        title="Replace the live monitor?"
        body={
          <p>
            Yutori can&apos;t move an existing monitor&apos;s start time. This stops the current
            monitor, then creates a new one with your saved settings — which starts a paid run of{" "}
            <strong>{money(cost)}</strong>. If the old one can&apos;t be stopped, nothing new is
            created.
          </p>
        }
        confirmLabel={`Replace · ${money(cost)}`}
        busy={replace.isPending}
        onCancel={() => setConfirmReplace(false)}
        onConfirm={() => {
          setConfirmReplace(false);
          replace.mutate();
        }}
      />
    </>
  );
}

/** One live monitor's settings as Yutori reports them, for the Monitors page. */
export function MonitorDetails({ instanceId }: { instanceId: string }) {
  const { data, isLoading, error } = useQuery<MonitorRemote>({
    queryKey: ["monitor-remote", instanceId],
    queryFn: () => scoutApi.monitorRemote(instanceId),
    retry: false,
  });

  if (isLoading) return <div className={ws.hint}>Asking Yutori…</div>;
  if (error || !data) return <div className={ws.bad}>{(error as Error)?.message ?? "Couldn't read it."}</div>;

  const r = data.remote;
  const rows: [string, string][] = [
    ["Status", r.status ?? "—"],
    ["How often", every(r.output_interval)],
    ["Next run", when(r.next_run)],
    ["Updates", `${r.update_count ?? 0}${r.last_update ? ` · last ${when(r.last_update)}` : ""}`],
    ["Timezone", r.user_timezone ?? "—"],
    ["Visibility", r.is_public ? "public" : "private"],
    ["Output format", r.has_output_schema ? "structured" : "prose"],
    ["Rejection", r.rejection_reason ?? "none"],
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "6px 0 12px" }}>
      <dl className={ws.dl}>
        {rows.map(([key, value]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {data.diff.length > 0 && (
        <div className={ws.hint}>
          Differs from its scout: {data.diff.map((d) => d.label).join(", ")}.{" "}
          {data.monitor.definition_id && (
            <Link className={ws.textButton} href={`/yutori/scouts/${data.monitor.definition_id}`}>
              Review on its Parameters tab →
            </Link>
          )}
        </div>
      )}
      <div className={ws.hint}>
        {r.view_url ? (
          <a className={ws.textButton} href={r.view_url} target="_blank" rel="noreferrer">
            View on Yutori ↗
          </a>
        ) : null}{" "}
        Yutori&apos;s API has no pause: Stop marks a monitor done, and Restart brings it back on its
        schedule.
      </div>
    </div>
  );
}
