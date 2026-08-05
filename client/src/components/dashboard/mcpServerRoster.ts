/**
 * MCP server reachability roster model (#5842).
 *
 * Pure classification/aggregation/sort over the `GET /gateways` list (React
 * "MCP servers"). Kept free of React and i18n so it can be unit tested without
 * mounting the card; `McpHealthCard` renders the result and maps enum kinds to
 * i18n strings + tones.
 *
 * Design (posted to issue #5842): two-tone only — green = online + reachable,
 * grey = everything else. Errors live in the Activity feed, so there is no
 * amber/red here. A server is classified on `enabled && reachable`, never
 * `reachable` alone: a server disabled while up keeps `reachable: true` frozen.
 */

import type { MCPServer } from "@/types/server";

/**
 * Per-server state:
 * - `reachable`   = enabled && reachable            -> green, "last seen X ago"
 * - `unreachable` = enabled && !reachable && seen   -> grey,  "last seen X ago"
 * - `checking`    = enabled && !reachable && !seen  -> grey,  "checking connection…" (never probed)
 * - `disabled`    = !enabled                        -> grey,  "disabled X ago"
 */
export type ServerState = "reachable" | "unreachable" | "checking" | "disabled";

export interface ClassifiedServer {
  server: MCPServer;
  state: ServerState;
}

/** Header label kinds. `null` = no header (empty fleet or all still checking). */
export type RosterHeaderKind = "reachable" | "reducedCoverage" | "unreachable" | "disabled";

export interface RosterSummary {
  /** Total servers, including those still checking. */
  total: number;
  reachable: number;
  unreachable: number;
  checking: number;
  disabled: number;
  /** Component totals summed across all servers (cached last-known for offline). */
  toolCount: number;
  resourceCount: number;
  promptCount: number;
}

export interface SummarySegment {
  kind: "unreachable" | "disabled" | "reachable" | "pending";
  count: number;
  /** Fleet size N; unused (and irrelevant) for the bare "pending" segment. */
  total: number;
}

export interface Roster {
  header: RosterHeaderKind | null;
  summary: RosterSummary;
  /** Segments to render, already in display order. */
  segments: SummarySegment[];
  /** Rows sorted problem-first. */
  rows: ClassifiedServer[];
}

/** Classify a single server. Keys on `enabled && reachable`, never `reachable` alone. */
export function classifyServer(server: MCPServer): ServerState {
  if (!server.enabled) return "disabled";
  if (server.reachable) return "reachable";
  return server.lastSeen ? "unreachable" : "checking";
}

/**
 * Header status over the SETTLED servers only (reachable + unreachable +
 * disabled). Servers still `checking` are excluded so a fresh fleet that has
 * not finished its first probe cannot false-alarm the header.
 */
export function computeHeader(summary: RosterSummary): RosterHeaderKind | null {
  const { reachable, unreachable, disabled } = summary;
  const settled = reachable + unreachable + disabled;
  if (settled === 0) return null;
  if (reachable === settled) return "reachable";
  if (reachable > 0) return "reducedCoverage";
  if (unreachable > 0) return "unreachable";
  return "disabled";
}

/**
 * Ordered summary segments. Order is fixed; a segment is omitted when its count
 * is zero. The "unreachable" segment only appears when nothing is reachable
 * (otherwise "reduced coverage" already tells that story via the header).
 */
export function summarySegments(summary: RosterSummary): SummarySegment[] {
  const { total, reachable, unreachable, disabled, checking } = summary;
  const segments: SummarySegment[] = [];
  if (unreachable > 0 && reachable === 0) {
    segments.push({ kind: "unreachable", count: unreachable, total });
  }
  if (disabled > 0) segments.push({ kind: "disabled", count: disabled, total });
  if (reachable > 0) segments.push({ kind: "reachable", count: reachable, total });
  if (checking > 0) segments.push({ kind: "pending", count: checking, total });
  return segments;
}

// Problem-first ordering: surface what needs attention before what is healthy.
const STATE_SORT_RANK: Record<ServerState, number> = {
  unreachable: 0,
  disabled: 1,
  reachable: 2,
  checking: 3,
};

/**
 * Sort problem-first (unreachable -> disabled -> reachable -> checking), then by
 * last-seen descending within a group, with a name tiebreak for stability.
 */
export function sortServers(classified: ClassifiedServer[]): ClassifiedServer[] {
  return [...classified].sort((a, b) => {
    const byState = STATE_SORT_RANK[a.state] - STATE_SORT_RANK[b.state];
    if (byState !== 0) return byState;

    const seenA = a.server.lastSeen ? Date.parse(a.server.lastSeen) : Number.NEGATIVE_INFINITY;
    const seenB = b.server.lastSeen ? Date.parse(b.server.lastSeen) : Number.NEGATIVE_INFINITY;
    if (seenA !== seenB) return seenB - seenA;

    return a.server.name.localeCompare(b.server.name);
  });
}

/** Build the full roster: classify, tally, header, segments, sorted rows. */
export function computeRoster(servers: MCPServer[]): Roster {
  const classified = servers.map((server) => ({ server, state: classifyServer(server) }));

  const summary: RosterSummary = {
    total: servers.length,
    reachable: 0,
    unreachable: 0,
    checking: 0,
    disabled: 0,
    toolCount: 0,
    resourceCount: 0,
    promptCount: 0,
  };

  for (const { server, state } of classified) {
    summary[state] += 1;
    summary.toolCount += server.toolCount ?? 0;
    summary.resourceCount += server.resourceCount ?? 0;
    summary.promptCount += server.promptCount ?? 0;
  }

  return {
    header: computeHeader(summary),
    summary,
    segments: summarySegments(summary),
    rows: sortServers(classified),
  };
}

/** StatusDot tone for a header kind: only an all-reachable fleet is green. */
export function headerTone(header: RosterHeaderKind): "success" | "muted" {
  return header === "reachable" ? "success" : "muted";
}

/** StatusDot tone for a row state: only a reachable server is green. */
export function rowTone(state: ServerState): "success" | "muted" {
  return state === "reachable" ? "success" : "muted";
}
