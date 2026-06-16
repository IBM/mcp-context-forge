/**
 * Prompts API service
 */

import { api } from "./client";

export interface PromptArgument {
  name: string;
  required?: boolean;
}

export interface PromptCreate {
  name: string;
  template: string;
  arguments: PromptArgument[];
}

export interface Prompt {
  id: string;
  name: string;
  displayName: string | null;
  description: string | null;
  template: string;
  arguments: PromptArgument[];
  gatewaySlug: string | null;
  visibility: "private" | "team" | "public";
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface PaginatedResponse<T> {
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
  list: (params?: {
    page?: number;
    perPage?: number;
    includeInactive?: boolean;
  }): Promise<PaginatedResponse<Prompt>> => {
    const searchParams = new URLSearchParams();

    if (params?.page !== undefined) {
      searchParams.set("page", params.page.toString());
    }

    if (params?.perPage !== undefined) {
      searchParams.set("per_page", params.perPage.toString());
    }

    if (params?.includeInactive) {
      searchParams.set("include_inactive", "true");
    }

    const query = searchParams.toString();
    return api.get(`/admin/prompts${query ? `?${query}` : ""}`);
  },
};
