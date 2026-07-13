/**
 * Tools API service
 */

import { api } from "./client";
import type { Tool } from "@/types/tool";
import type { GenerateSchemaRequest } from "@/generated/types/generateSchemaRequest";

/**
 * Request body for {@link toolsApi.generateSchemasFromOpenapi}.
 *
 * Re-exported from the generated OpenAPI client so the shape stays in lockstep
 * with the backend contract (`url`, optional `request_type`, optional
 * `openapi_url`).
 */
export type GenerateSchemasFromOpenapiInput = GenerateSchemaRequest;

/**
 * Response from `POST /v1/tools/generate-schemas-from-openapi`.
 *
 * The endpoint returns an untyped `JSONResponse` on the backend, so orval
 * generates only `data: unknown` for it; this narrows that shape by hand.
 */
export interface GenerateSchemasFromOpenapiResult {
  message: string;
  success: boolean;
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  spec_url: string;
  /** Set by the backend when the spec host requires authentication. */
  requires_auth?: boolean;
}

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

  /**
   * Generate input/output JSON schemas for a REST tool from its OpenAPI spec.
   *
   * Delegates to `POST /v1/tools/generate-schemas-from-openapi`, which fetches
   * the OpenAPI 3.x document for the tool host, resolves the requested
   * path + method, and returns the extracted schemas plus the `spec_url` it used.
   * Requires the `tools.create` permission. Rejects with an {@link ApiError}
   * carrying the backend status code (400/404/502/500) on failure.
   *
   * @param input - Tool URL, HTTP method, and optional spec URL / auth
   */
  generateSchemasFromOpenapi: (
    input: GenerateSchemasFromOpenapiInput,
  ): Promise<GenerateSchemasFromOpenapiResult> =>
    api.post<GenerateSchemasFromOpenapiResult>("/v1/tools/generate-schemas-from-openapi", input),
};
