/**
 * Prompts API service
 */

import { api } from "./client";

/**
 * Shape of a rendered MCP `prompts/get` response — the gateway substitutes
 * template variables and runs plugin hooks, but does not invoke an LLM.
 *
 * The OpenAPI spec models this as `unknown`; this local type captures the
 * fields the UI actually renders. Keep narrow — widen only as the panel grows.
 */
export interface RenderedPromptMessage {
  role: "user" | "assistant" | "system";
  content: {
    type: "text";
    text: string;
  };
}

export interface RenderedPrompt {
  messages: RenderedPromptMessage[];
  description?: string | null;
}

export interface RenderResult {
  rendered: RenderedPrompt;
  status: number;
}

// Mirrors the backend `SecurityValidator.NAME_PATTERN` in
// `mcpgateway/utils/security_validator.py` — the same characters the gateway
// accepts for a prompt name (space, dot, dash allowed). If the backend widens
// the pattern, update here in lockstep.
const PROMPT_NAME_PATTERN = /^[a-zA-Z0-9_.\- ]+$/;

function validatePromptName(value: string): string {
  if (!value || typeof value !== "string") {
    throw new Error("Invalid prompt name");
  }
  if (!PROMPT_NAME_PATTERN.test(value)) {
    throw new Error("Invalid prompt name format");
  }
  return value;
}

export const promptsApi = {
  /**
   * Render a prompt without invoking an LLM. Runs plugin hooks; returns the
   * MCP `messages` array with template substitutions applied.
   *
   * Mirrors `POST /prompts/{prompt_id}` (`mcpgateway/main.py`). The gateway
   * endpoint accepts either the prompt's name or its ID (see
   * `_find_prompt_by_name_or_id` in `mcpgateway/services/prompt_service.py`);
   * this call passes the name so the identifier matches what the Code-tab
   * snippets show and what MCP-spec clients use on the wire.
   *
   * Failure modes to be aware of:
   *   - If the same name is visible to the caller in more than one scope, the
   *     backend raises PromptError ("ambiguous across multiple scopes"). The
   *     hook unwraps `ApiError.detail` and surfaces the message via toast.
   *   - MCP 2026-07-28 RC introduces an `Mcp-Name` header as the canonical
   *     wire identifier for prompts; keeping this call name-shaped means the
   *     snippet URL string and the future header value are the same identifier.
   *
   * Future option (tracked separately from this fix-up):
   *   - Route Preview and snippets through the server-scoped MCP transport
   *     (`POST /servers/{server_id}/mcp` with a JSON-RPC `prompts/get`
   *     envelope). Removes ambiguity entirely and matches how real MCP
   *     clients address prompts. Depends on the Prompts page carrying a
   *     server context, which is not the case today.
   */
  render: (name: string, args: Record<string, string> = {}): Promise<RenderResult> => {
    // Validate outside the async chain so bad names reject the *caller* before
    // any network I/O and preserve the synchronous-throw contract exercised by
    // `prompts.test.ts`.
    const validName = validatePromptName(name);
    return api
      .postWithMeta<RenderedPrompt>(`/prompts/${encodeURIComponent(validName)}`, args)
      .then(({ data, status }) => ({ rendered: data, status }));
  },
};
