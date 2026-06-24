/**
 * Tools API service
 */

import { api } from "./client";
import type { Tool } from "@/types/tool";

/**
 * Validates tool ID to prevent path traversal and injection attacks
 * @param id - The tool ID to validate
 * @returns The validated ID
 * @throws Error if ID is invalid
 */
function validateToolId(id: string): string {
  if (!id || typeof id !== "string") {
    throw new Error("Invalid tool ID");
  }

  // Ensure ID is alphanumeric with hyphens/underscores only
  if (!/^[a-zA-Z0-9_-]+$/.test(id)) {
    throw new Error("Invalid tool ID format");
  }

  return id;
}

export const toolsApi = {
  /**
   * Fetch a single tool by ID.
   *
   * @param id - The tool ID
   */
  get: (id: string): Promise<Tool> => {
    const validId = validateToolId(id);
    return api.get<Tool>(`/tools/${validId}`);
  },

  /**
   * Delete a tool
   */
  delete: (id: string): Promise<void> => {
    const validId = validateToolId(id);
    return api.delete(`/tools/${validId}`);
  },

  // Activation uses the canonical `POST /tools/{tool_id}/state?activate=true|false`
  // endpoint (requires `tools.update` permission). The deprecated `/toggle` endpoint
  // is intentionally not used.

  /**
   * Activate a tool (take it back into routing/availability).
   *
   * @param id - The tool ID
   */
  activate: (id: string): Promise<void> => {
    const validId = validateToolId(id);
    return api.post(`/tools/${validId}/state?activate=true`);
  },

  /**
   * Deactivate a tool (remove it from routing/availability).
   *
   * @param id - The tool ID
   */
  deactivate: (id: string): Promise<void> => {
    const validId = validateToolId(id);
    return api.post(`/tools/${validId}/state?activate=false`);
  },
};
