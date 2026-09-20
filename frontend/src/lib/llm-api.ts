/** Client for the /llm endpoints.
 *
 * Every shape here mirrors what the backend reads out of the real code —
 * nothing about the prompt, the schema or the validation rules is duplicated
 * on this side, so the page cannot drift from what actually gets sent.
 */

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string" ? body.detail : `${path} failed: ${response.status}`,
    );
  }
  return response.json();
}

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

export type TestResult =
  | {
      ok: true;
      provider: string;
      model: string;
      prompt_version: number;
      challenge: {
        problem_summary: string;
        why_interesting: string;
        concepts: string[];
        starting_direction: string;
        hints: { label: string; text: string }[];
        estimated_difficulty: number | null;
      };
    }
  | { ok: false; provider: string; model: string; prompt_version: number; error: string };

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
    json<{ version: number }>("/api/llm/prompts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

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

  /** Costs one real LLM call and saves nothing. */
  test: (questionId: string) =>
    json<TestResult>(`/api/llm/test?question_id=${questionId}`, { method: "POST" }),

  generations: () => json<{ generations: Generation[] }>("/api/llm/generations"),
};
