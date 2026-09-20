import { redirect } from "next/navigation";

/**
 * /yutori has no page of its own — Scouts is the section's front door, since
 * it is where a run starts. Kept as a redirect rather than a duplicate of the
 * scouts list so there is only one place that list is written.
 */
export default function YutoriIndex() {
  redirect("/yutori/scouts");
}
