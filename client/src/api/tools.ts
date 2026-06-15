/**
 * Tools API service
 */

import { api } from "./client";

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
   * Delete a tool
   */
  delete: (id: string): Promise<void> => {
    const validId = validateToolId(id);
    return api.delete(`/tools/${validId}`);
  },
};
