/** Client for the /llm endpoints.
 *
 * Every shape here mirrors what the backend reads out of the real code —
 * nothing about the prompt, the schema or the validation rules is duplicated
 * on this side, so the page cannot drift from what actually gets sent.
 */

import { json, send } from "./api";

export type LlmConfig = {
  provider: "gemini" | "openai";
  prompt: {
    version: number;
    is_default: boolean;
    system_instruction: string;
    safety_clause: string;
    composed_system_instruction: string;
    user_preamble: string;
    default_system_instruction: string;
    default_user_preamble: string;
  };
  limits: {
    max_body_chars: number;
    attempts: number;
    hint_labels: string[];
    max_prompt_chars: number;
  };
  format: { name: string; blocks: string[] };
  schema: Record<string, unknown>;
  validation: { solution_tells: string[]; code_fence: string };
  withheld: string[];
};

export type PromptVersion = {
  id: number;
  version: number;
  system_instruction: string;
  user_preamble: string;
  notes: string | null;
  is_active: boolean;
  created_at: string | null;
};

export type Preview = {
  question: {
    id: string;
    title: string | null;
    status: string;
    body_chars: number;
    body_chars_sent: number;
  };
  system_instruction: string;
  prompt: string;
  prompt_chars: number;
};

type TestMeta = {
  provider: string;
  model: string;
  prompt_version: number;
  format: { name: string; blocks: string[] };
};

export type TestResult =
  | (TestMeta & {
      ok: true;
      /** The whole block output, so a test shows exactly what a real run would
       *  store — including optional blocks. */
      content: Record<string, unknown>;
      /** URLs dropped because they did not resolve. */
      dropped_links: string[];
    })
  | (TestMeta & { ok: false; error: string });

export type BlockMeta = {
  /** Null for a block that ships in the code — it has no row of its own. */
  id: number | null;
  key: string;
  label: string;
  description: string;
  kind: string;
  core: boolean;
  gated: boolean;
  has_urls: boolean;
  /** Deprecated alias for `editable`, kept for one release. */
  custom: boolean;
  /** Whether this block lives in `library_blocks` — editable and deletable.
   *  False for the six core blocks, which are columns on `challenges`. */
  editable: boolean;
  /** What it currently asks the model for. */
  instruction: string;
  /** What "reset" would restore. Null for a custom block — it has no default. */
  default_instruction: string | null;
  is_overridden: boolean;
};

export type ChallengeFormat = {
  id: number;
  name: string;
  description: string | null;
  blocks: string[];
  optional_blocks: string[];
  is_default: boolean;
  created_at: string | null;
};

export type Generation = {
  id: string;
  question_title: string | null;
  source: "digest" | "manual";
  provider: string | null;
  model: string | null;
  prompt_version: number | null;
  estimated_difficulty: number | null;
  created_at: string | null;
};

export const llmApi = {
  config: () => json<LlmConfig>("/api/llm/config"),

  prompts: () => json<{ versions: PromptVersion[] }>("/api/llm/prompts"),

  savePrompt: (body: { system_instruction: string; user_preamble: string; notes?: string }) =>
    json<{ version: number }>("/api/llm/prompts", send("POST", body)),

  activatePrompt: (version: number) =>
    json<{ version: number }>(`/api/llm/prompts/${version}/activate`, { method: "POST" }),

  resetPrompt: () => json<{ version: number }>("/api/llm/prompts/reset", { method: "POST" }),

  /** Free — renders the prompt without calling the model. Optional overrides
   *  let an unsaved edit be previewed before it is stored. */
  preview: (questionId: string, overrides?: { system_instruction?: string; user_preamble?: string }) => {
    const params = new URLSearchParams({ question_id: questionId });
    if (overrides?.system_instruction) params.set("system_instruction", overrides.system_instruction);
    if (overrides?.user_preamble) params.set("user_preamble", overrides.user_preamble);
    return json<Preview>(`/api/llm/preview?${params}`);
  },

  generations: () => json<{ generations: Generation[] }>("/api/llm/generations"),

  blocks: () =>
    json<{
      blocks: BlockMeta[];
      kinds: string[];
      /** The subset a custom block may choose — narrower than `kinds`. */
      custom_kinds: string[];
      max_instruction_chars: number;
    }>("/api/llm/blocks"),

  createBlock: (body: {
    key: string;
    label: string;
    kind: string;
    instruction: string;
    description?: string;
    gated?: boolean;
  }) => json<BlockMeta>("/api/llm/blocks/custom", send("POST", body)),

  updateBlock: (
    id: number,
    body: {
      label: string;
      kind: string;
      instruction: string;
      description?: string | null;
      gated?: boolean;
    },
  ) => json<BlockMeta>(`/api/llm/blocks/custom/${id}`, send("PATCH", body)),

  deleteBlock: (id: number) => json<void>(`/api/llm/blocks/custom/${id}`, send("DELETE")),

  /** Reword a block that ships in the code. Its shape is unaffected. */
  setInstruction: (key: string, instruction: string) =>
    json<{ key: string; instruction: string }>(
      `/api/llm/blocks/${key}/instruction`,
      send("PUT", { instruction }),
    ),

  resetInstruction: (key: string) =>
    json<{ key: string; instruction: string }>(`/api/llm/blocks/${key}/instruction`, {
      method: "DELETE",
    }),

  formats: () =>
    json<{ formats: ChallengeFormat[]; active: { name: string; blocks: string[] } }>(
      "/api/llm/formats",
    ),

  createFormat: (body: {
    name: string;
    blocks: string[];
    description?: string;
    make_default?: boolean;
  }) => json<ChallengeFormat>("/api/llm/formats", send("POST", body)),

  updateFormat: (
    id: number,
    body: { name: string; blocks: string[]; description?: string | null },
  ) => json<ChallengeFormat>(`/api/llm/formats/${id}`, send("PATCH", body)),

  makeFormatDefault: (id: number) =>
    json<ChallengeFormat>(`/api/llm/formats/${id}/default`, { method: "POST" }),

  deleteFormat: (id: number) => json<void>(`/api/llm/formats/${id}`, send("DELETE")),
};
