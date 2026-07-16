/**
 * Resources API service
 */

import { api } from "./client";
import type { ResourceCreate, ResourceRead, ResourceUpdate } from "@/generated/types";

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

  // Enforce reasonable length limit to prevent DoS
  if (id.length > 255) {
    throw new Error("Resource ID too long");
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
  create: (data: ResourceCreate): Promise<void> => {
    return api.post("/resources", data);
  },

  /**
   * Update a resource
   */
  update: (id: string, data: ResourceUpdate): Promise<void> => {
    const validId = validateResourceId(id);
    return api.put(`/resources/${validId}`, data);
  },

  /**
   * Replace a resource's tags.
   *
   * Sends a partial `PUT /resources/{id}` carrying only `tags`; other fields are
   * preserved because the update service skips omitted values. Returns the
   * updated resource so callers can patch their cache with the normalized tags.
   */
  updateTags: (id: string, tags: string[]): Promise<ResourceRead> => {
    const validId = validateResourceId(id);
    return api.put<ResourceRead>(`/resources/${validId}`, { tags });
  },

  /**
   * Delete a resource
   */
  delete: (id: string): Promise<void> => {
    const validId = validateResourceId(id);
    return api.delete(`/resources/${validId}`);
  },
};
