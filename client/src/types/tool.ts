import type { ToolRead } from "@/generated/types";

/**
 * A tool as returned by the API.
 *
 * Aliased to the generated OpenAPI `ToolRead` (unwrapped from its `| null`) so
 * the UI stays in lockstep with the backend contract: an OpenAPI change to a
 * field the components read breaks the build rather than failing at runtime.
 * Mirrors the pattern used for resources (`NonNullable<ResourceRead>`).
 */
export type Tool = NonNullable<ToolRead>;

export interface ToolGroup {
  gatewaySlug: string;
  gatewayId?: string | null;
  tools: Tool[];
  isActive: boolean;
}
