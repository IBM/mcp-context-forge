/**
 * MCP Servers API service
 *
 * Wraps /gateways backend endpoint but exposes as "servers" API
 * for frontend consistency.
 */

import { api } from "./client";
import type { ServersResponse, MCPServer } from "../types/server";
import type { GatewayTestRequest, GatewayTestResponse } from "@/generated/types";

const serverByIdRequestCache = new Map<string, Promise<MCPServer>>();

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

    const cachedRequest = serverByIdRequestCache.get(validId);
    if (cachedRequest) {
      return cachedRequest;
    }

    const request = api.get<MCPServer>(`/gateways/${validId}`);
    serverByIdRequestCache.set(validId, request);

    request.catch(() => {
      serverByIdRequestCache.delete(validId);
    });

    return request;
  },

  /**
   * Delete an MCP server
   */
  delete: (id: string): Promise<void> => {
    const validId = validateServerId(id);
    return api.delete(`/gateways/${validId}`);
  },

  /**
   * Replace an MCP server's (gateway's) tags.
   *
   * Sends a partial `PUT /gateways/{id}` carrying only `tags`; the gateway
   * update service preserves every other field when it is omitted. Returns the
   * updated server so callers can patch their cache with the normalized tags.
   */
  updateTags: (id: string, tags: string[]): Promise<MCPServer> => {
    const validId = validateServerId(id);
    return api.put<MCPServer>(`/gateways/${validId}`, { tags });
  },

  /**
   * Test connection to an MCP server
   */
  testConnection: (id: string): Promise<{ success: boolean; message: string }> => {
    const validId = validateServerId(id);
    return api.post(`/gateways/${validId}/test`, {});
  },

  /**
   * Test ad-hoc connectivity to an MCP server / gateway URL.
   *
   * Unlike {@link testConnection} (which pings an already-registered server by
   * ID), this sends a caller-supplied request (URL, method, path, headers, body)
   * to the v1 REST endpoint and returns the upstream response. The React UI must
   * use this rather than the legacy /admin/gateways/test route.
   */
  testConnectivity: (
    request: GatewayTestRequest,
    signal?: AbortSignal,
  ): Promise<GatewayTestResponse> => {
    return api.post("/v1/mcp-servers/test", request, { signal });
  },

  /**
   * Toggle the enabled state of an MCP server (activate/deactivate)
   */
  toggleEnabled: (id: string, enabled: boolean): Promise<{ status: string; message: string }> => {
    const validId = validateServerId(id);
    return api.post(`/gateways/${validId}/state?activate=${enabled}`);
  },

  /**
   * Fetch tools, resources, and prompts from the MCP server after OAuth authorization
   */
  // prettier-ignore
  fetchToolsAfterOAuth: ( // pragma: allowlist secret
    id: string,
  ): Promise<{ success: boolean; message: string }> => {
    const validId = validateServerId(id);
    return api.post(`/oauth/fetch-tools/${validId}`);
  },

  /**
   * Trigger OAuth authorization flow for a gateway via a popup window.
   *
   * Opens /oauth/authorize/{id}?popup=true in a centered popup. The backend
   * encodes a "popup." prefix in the OAuth state so the callback page responds
   * with window.opener.postMessage instead of rendering a full HTML page.
   *
   * Returns a Promise that resolves on success or rejects on error / cancellation.
   */
  triggerOAuthAuthorization: (id: string): Promise<OAuthCallbackResult> => {
    const validId = validateServerId(id);
    const authUrl = `/oauth/authorize/${validId}?popup=true`;

    return new Promise((resolve, reject) => {
      const width = 600;
      const height = 700;
      const left = window.screenX + (window.outerWidth - width) / 2;
      const top = window.screenY + (window.outerHeight - height) / 2;

      const authWindow = window.open(
        authUrl,
        "oauth_authorization",
        `width=${width},height=${height},left=${left},top=${top},toolbar=no,location=no,status=no,menubar=no,scrollbars=yes,resizable=yes`,
      );

      if (!authWindow) {
        reject(
          new Error(
            "Failed to open OAuth authorization window. Please check your popup blocker settings.",
          ),
        );
        return;
      }

      let settled = false;

      const cleanup = () => {
        window.removeEventListener("message", messageHandler);
        clearInterval(pollInterval);
      };

      const messageHandler = (event: MessageEvent) => {
        // Verify the message came from our specific popup rather than checking
        // origin, which breaks when the React dev server (e.g. :3000) and the
        // API server (e.g. :8000) run on different ports — the popup ends up on
        // the API origin so event.origin !== window.location.origin.
        if (event.source !== authWindow) return;
        const data = event.data as OAuthCallbackResult;
        if (!data || data.type !== "oauth_callback") return;
        if (settled) return;
        settled = true;
        cleanup();
        if (data.status === "success") {
          resolve(data);
        } else {
          reject(new Error(data.errorDescription ?? data.error ?? "OAuth authorization failed"));
        }
      };

      window.addEventListener("message", messageHandler);

      // Detect when the user closes the popup without completing OAuth.
      // 1 s is fast enough to feel responsive while not burning cycles.
      const pollInterval = setInterval(() => {
        if (authWindow.closed) {
          if (!settled) {
            settled = true;
            cleanup();
            reject(new Error("OAuth authorization was cancelled"));
          }
        }
      }, 1000);
    });
  },
};

export interface OAuthCallbackResult {
  type: "oauth_callback";
  status: "success" | "error";
  gatewayId?: string;
  gatewayName?: string;
  error?: string;
  errorDescription?: string;
}
