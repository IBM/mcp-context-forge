/**
 * Mini-card status model (#5532 right column).
 *
 * Each right-column / source mini card can show a small status under its label:
 * a tone dot with a word (runtime health, "Not configured") or the activity
 * error/warning counts. The mapping is pure and lives here so it can be unit
 * tested without mounting the fetching hook (`useMiniCardStatuses`).
 *
 * Semantics:
 * - MCP / A2A "runtime" health mirrors the in-process backend health from
 *   `/version` (`deriveMcpHealthy`); an unconfigured source (no MCP servers /
 *   A2A disabled or no agents) shows "Not configured"; unknown health (e.g. the
 *   caller lacks access to `/version`) shows no dot rather than a false claim.
 * - REST / gRPC are always "Not configured" (transport not built).
 * - Activity shows raw error/warning counts (real once #5944 lands).
 */

import type { MiniCardId } from "./homeStates";
import type { StatusTone } from "./StatusDot";

export type MiniCardStatus =
  | { kind: "dot"; tone: StatusTone; labelId: string }
  | { kind: "activity"; errors: number; warnings: number }
  | null;

const NOT_CONFIGURED: MiniCardStatus = {
  kind: "dot",
  tone: "muted",
  labelId: "dashboard.home.status.notConfigured",
};

/**
 * Runtime health dot. `configured`/`healthy` are tri-state: `null` means "not
 * known yet" (still loading) and renders no dot, so a card never flashes a
 * wrong "Not configured" / health label before its data resolves.
 */
function runtimeStatus(configured: boolean | null, healthy: boolean | null): MiniCardStatus {
  if (configured === null) return null;
  if (!configured) return NOT_CONFIGURED;
  if (healthy === null) return null;
  return healthy
    ? { kind: "dot", tone: "success", labelId: "dashboard.home.status.healthy" }
    : { kind: "dot", tone: "error", labelId: "dashboard.home.status.unhealthy" };
}

export interface MiniCardStatusInput {
  /**
   * Backend reachability (a `/version` response arrived): true -> "Running",
   * null while unknown/loading/unreachable. Distinct from `healthy`, which also
   * factors dependency (DB/Redis) health.
   */
  systemRunning: boolean | null;
  /** At least one MCP server is registered; null while still loading. */
  mcpConfigured: boolean | null;
  /** A2A is enabled and has at least one agent; null while still loading. */
  a2aConfigured: boolean | null;
  /** In-process backend health, or null when unknown/still loading. */
  healthy: boolean | null;
  errors: number;
  warnings: number;
}

export function computeMiniCardStatuses(
  input: MiniCardStatusInput,
): Record<MiniCardId, MiniCardStatus> {
  return {
    system: input.systemRunning
      ? { kind: "dot", tone: "success", labelId: "dashboard.home.status.running" }
      : null,
    activity: { kind: "activity", errors: input.errors, warnings: input.warnings },
    mcp: runtimeStatus(input.mcpConfigured, input.healthy),
    a2a: runtimeStatus(input.a2aConfigured, input.healthy),
    rest: NOT_CONFIGURED,
    grpc: NOT_CONFIGURED,
  };
}
