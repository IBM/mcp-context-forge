/**
 * Prompts API service
 */

import { api } from "./client";

export interface PromptArgument {
  name: string;
}

export interface PromptCreate {
  name: string;
  template: string;
  arguments: PromptArgument[];
}

export interface Prompt {
  id: string;
  name: string;
  display_name: string | null;
  description: string | null;
  template: string;
  arguments: PromptArgument[];
  gateway_slug: string | null;
  visibility: "private" | "team" | "public";
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

interface PaginatedResponse<T> {
  data: T[];
  links: {
    first: string;
    last: string;
    next: string | null;
    prev: string | null;
    self: string;
  };
  pagination: {
    page: number;
    per_page: number;
    total_items: number;
    total_pages: number;
    has_next: boolean;
    has_prev: boolean;
  };
}

export const promptsApi = {
  /**
   * Create a new prompt
   */
  create: (data: PromptCreate): Promise<Prompt> => {
    const formData = new FormData();

    formData.append("name", data.name);
    formData.append("template", data.template);
    formData.append("arguments", JSON.stringify(data.arguments));

    return api.post("/admin/prompts", formData);
  },

  /**
   * List all prompts
   */
  list: async (): Promise<Prompt[]> => {
    const response = await api.get<PaginatedResponse<Prompt>>("/admin/prompts");
    return response.data;
  },
};
