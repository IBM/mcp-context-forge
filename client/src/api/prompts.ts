/**
 * Prompts API service
 */

import { api } from "@/api/client";
import type { Prompt, PromptArgument, PromptFormData } from "@/types/prompts";
import type { Visibility } from "@/types/server";

interface CreatePromptPayload {
  prompt: {
    name: string;
    description?: string;
    template: string;
    arguments: PromptArgument[];
    tags?: string[];
    visibility: Visibility;
    team_id: string | null;
  };
  team_id: string | null;
  visibility: Visibility;
}

function parseArguments(value: string): PromptArgument[] {
  if (!value.trim()) return [];
  const parsed = JSON.parse(value) as unknown;
  if (!Array.isArray(parsed)) {
    throw new Error("Prompt arguments must be a JSON array");
  }
  return parsed as PromptArgument[];
}

function parseTags(value?: string): string[] | undefined {
  const tags = value
    ?.split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);

  return tags && tags.length > 0 ? tags : undefined;
}

export function buildCreatePromptPayload(data: PromptFormData): CreatePromptPayload {
  const visibility = data.visibility as Visibility;
  const teamId = visibility === "team" && data.teamId ? data.teamId : null;

  return {
    prompt: {
      name: data.name,
      description: data.description || undefined,
      template: data.template,
      arguments: parseArguments(data.arguments),
      tags: parseTags(data.tags),
      visibility,
      team_id: teamId,
    },
    team_id: teamId,
    visibility,
  };
}

/**
 * Create a new prompt using the JSON prompts API.
 */
export function createPrompt(data: PromptFormData): Promise<Prompt> {
  return api.post<Prompt>("/prompts", buildCreatePromptPayload(data));
}

export const promptsApi = {
  create: createPrompt,
};
