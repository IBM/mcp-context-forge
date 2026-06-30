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

function validatePromptId(id: string): string {
  if (!id || typeof id !== "string") {
    throw new Error("Invalid prompt ID");
  }

  if (!/^[a-zA-Z0-9_-]+$/.test(id)) {
    throw new Error("Invalid prompt ID format");
  }

  return id;
}

export const promptsApi = {
  /**
   * Render a prompt without invoking an LLM. Runs plugin hooks; returns the
   * MCP `messages` array with template substitutions applied.
   *
   * Mirrors `POST /prompts/{id}` (`mcpgateway/main.py`, accepts a flat
   * `Dict[str, str]` body of arg values).
   */
  render: (id: string, args: Record<string, string> = {}): Promise<RenderedPrompt> => {
    const validId = validatePromptId(id);
    return api.post<RenderedPrompt>(`/prompts/${validId}`, args);
  },
};
