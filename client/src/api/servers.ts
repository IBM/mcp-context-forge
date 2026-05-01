/**
 * MCP Servers API service
 *
 * Wraps /gateways backend endpoint but exposes as "servers" API
 * for frontend consistency.
 */

import { api } from "./client";
import type { ServersResponse, MCPServer } from "../types/server";

/**
 * Validates server ID to prevent path traversal and injection attacks
 * @param id - The server ID to validate
 * @returns The validated ID
 * @throws Error if ID is invalid
 */
function validateServerId(id: string): string {
  if (!id || typeof id !== "string") {
    throw new Error("Invalid server ID");
  }

  // Ensure ID is alphanumeric with hyphens/underscores only
  if (!/^[a-zA-Z0-9_-]+$/.test(id)) {
    throw new Error("Invalid server ID format");
  }

  return id;
}

export const serversApi = {
  /**
   * List all MCP servers with cursor-based pagination
   */
  list: (params?: {
    cursor?: string;
    limit?: number;
    include_inactive?: boolean;
    signal?: AbortSignal;
  }): Promise<ServersResponse> => {
    const searchParams = new URLSearchParams();

    // Add cursor if provided
    if (params?.cursor) {
      searchParams.set("cursor", params.cursor);
    }

    // Validate and clamp limit (1-100)
    if (params?.limit !== undefined) {
      const limit = Number.isFinite(params.limit)
        ? Math.max(1, Math.min(100, Math.floor(params.limit)))
        : 25;
      searchParams.set("limit", limit.toString());
    }

    if (params?.include_inactive) {
      searchParams.set("include_inactive", "true");
    }

    // Always request pagination metadata to get structured response
    searchParams.set("include_pagination", "true");

    const query = searchParams.toString();
    return api.get(`/gateways${query ? `?${query}` : ""}`, undefined, params?.signal);
  },

  /**
   * Get a single MCP server by ID
   */
  get: (id: string): Promise<MCPServer> => {
    const validId = validateServerId(id);
    return api.get(`/gateways/${validId}`);
  },

  /**
   * Delete an MCP server
   */
  delete: (id: string): Promise<void> => {
    const validId = validateServerId(id);
    return api.delete(`/gateways/${validId}`);
  },

  /**
   * Test connection to an MCP server
   */
  testConnection: (id: string): Promise<{ success: boolean; message: string }> => {
    const validId = validateServerId(id);
    return api.post(`/gateways/${validId}/test`, {});
  },
};
