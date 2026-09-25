"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { money, scoutApi } from "@/lib/scout-api";
import ws from "./workspace.module.css";

/**
 * A standing reminder that something is billing on its own.
 *
 * A Scout monitor runs at its interval until stopped, with nobody pressing
 * anything — so it is the one cost in the app that can grow unseen. The
 * banner stays neutral while every monitor is one a scout is meant to have,
 * and turns to the alert colour when some are leftovers (superseded), which
 * is money spent on nothing.
 *
 * Reads the local summary only; it never calls Yutori, so it is safe on
 * every dashboard load.
 */
export function MonitorBanner() {
  const { data } = useQuery({ queryKey: ["monitors"], queryFn: scoutApi.monitors });

  if (!data || data.live_count === 0) return null;

  const plural = data.live_count === 1 ? "" : "s";
  const leftovers = data.superseded_count;

  return (
    <div className={leftovers > 0 ? ws.alert : ws.notice}>
      <strong>
        {data.live_count} monitor{plural} running at Yutori
      </strong>{" "}
      · about {money(data.monthly_cost_usd)} a month, billed on {data.live_count === 1 ? "its" : "their"}{" "}
      own schedule.
      {leftovers > 0 && (
        <>
          {" "}
          {leftovers} {leftovers === 1 ? "is a leftover" : "are leftovers"} from earlier runs and
          can be stopped.
        </>
      )}{" "}
      <Link href="/yutori/monitors" style={{ color: "inherit", textDecoration: "underline" }}>
        Review on Monitors →
      </Link>
    </div>
  );
}
