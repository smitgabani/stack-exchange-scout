import { redirect } from "next/navigation";

/** Pipeline is the section's front door — it is the question the page exists
 *  to answer. */
export default function LlmIndex() {
  redirect("/llm/pipeline");
}
