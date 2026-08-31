/**
 * Mini-card status model (#5532 right column).
 *
 * Each source / system mini card shows a two-tone reachability dot that mirrors
 * the MCP roster's scheme: green when something is reachable, grey for
 * everything else (unreachable, disabled, none, or still loading). There is no
 * "no dot" state — a card always shows a green or grey dot. The one exception is
 * the Activity card, which shows raw error/warning counts rather than a dot.
 *
 * The mapping is pure and lives here so it can be unit tested without mounting
 * the fetching hook (`useMiniCardStatuses`).
 *
 * Semantics:
 * - system / mcp / a2a: green ("Online") when reachable, grey ("Offline") else.
 * - REST / gRPC: always grey ("Offline") — transports not built yet.
 * - Activity: raw error/warning counts (real once #5944 lands).
 */

import type { MiniCardId } from "./homeStates";
import type { StatusTone } from "./StatusDot";

export type MiniCardStatus =
  | { kind: "dot"; tone: StatusTone; labelId: string }
  | { kind: "activity"; errors: number; warnings: number };

const ONLINE: MiniCardStatus = {
  kind: "dot",
  tone: "success",
  labelId: "dashboard.home.status.online",
};

// Grey umbrella for anything not reachable (unreachable, disabled, none,
// loading). A single "Offline" label that still reads correctly when several
// servers are offline for different reasons.
const OFFLINE: MiniCardStatus = {
  kind: "dot",
  tone: "muted",
  labelId: "dashboard.home.status.offline",
};

function reachabilityDot(reachable: boolean): MiniCardStatus {
  return reachable ? ONLINE : OFFLINE;
}

export interface MiniCardStatusInput {
  /** Backend reachable (any successful API response). */
  systemReachable: boolean;
  /** At least one MCP server is enabled and reachable. */
  mcpReachable: boolean;
  /** At least one A2A agent is enabled and reachable. */
  a2aReachable: boolean;
  errors: number;
  warnings: number;
}

export function computeMiniCardStatuses(
  input: MiniCardStatusInput,
): Record<MiniCardId, MiniCardStatus> {
  return {
    system: reachabilityDot(input.systemReachable),
    activity: { kind: "activity", errors: input.errors, warnings: input.warnings },
    mcp: reachabilityDot(input.mcpReachable),
    a2a: reachabilityDot(input.a2aReachable),
    // REST and gRPC transports are not built yet -> always offline.
    rest: OFFLINE,
    grpc: OFFLINE,
  };
}
