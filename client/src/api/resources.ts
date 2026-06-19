/**
 * Resources API service
 */

import { api } from "./client";
import type { ResourceCreateRequest, ResourceUpdateRequest } from "@/types/resource";

/**
 * Validates resource ID to prevent path traversal and injection attacks
 * @param id - The resource ID to validate
 * @returns The validated ID
 * @throws Error if ID is invalid
 */
function validateResourceId(id: string): string {
  if (!id || typeof id !== "string") {
    throw new Error("Invalid resource ID");
  }

  // Ensure ID is alphanumeric with hyphens/underscores only
  if (!/^[a-zA-Z0-9_-]+$/.test(id)) {
    throw new Error("Invalid resource ID format");
  }

  return id;
}

export const resourcesApi = {
  /**
   * Create a new resource
   */
  create: (data: ResourceCreateRequest): Promise<void> => {
    return api.post("/resources", data);
  },

  /**
   * Update a resource
   */
  update: (id: string, data: ResourceUpdateRequest): Promise<void> => {
    const validId = validateResourceId(id);
    return api.put(`/resources/${validId}`, data);
  },

  /**
   * Delete a resource
   */
  delete: (id: string): Promise<void> => {
    const validId = validateResourceId(id);
    return api.delete(`/resources/${validId}`);
  },
};
