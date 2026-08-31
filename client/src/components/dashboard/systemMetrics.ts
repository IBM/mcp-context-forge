/**
 * System view data model + pure helpers (#5942 / #5943).
 *
 * The System home view is built entirely from data that exists today:
 * - Top stats come from `GET /metrics`, which returns per-entity-type aggregates
 *   (tools/resources/servers/prompts/a2aAgents). There is NO system-wide roll-up,
 *   so `aggregateSystemStats` combines the types client-side. These figures are
 *   ALL-TIME cumulative (since first execution or last `POST /metrics/reset`),
 *   not windowed — `/metrics` exposes no time window and no percentiles.
 * - Counts come from list endpoints with `limit=0` (all rows), counted by length;
 *   there is no cheap COUNT endpoint.
 *
 * Response times are rendered with the same convention as the legacy admin UI
 * (`Number(value).toFixed(3) + "ms"`). Success rate is derived from `failureRate`.
 */

/** Per-entity aggregate as returned by `GET /metrics` (camelCase wire format). */
export interface EntityMetrics {
  totalExecutions: number;
  successfulExecutions: number;
  failedExecutions: number;
  failureRate: number;
  minResponseTime: number | null;
  maxResponseTime: number | null;
  avgResponseTime: number | null;
  lastExecutionTime?: string | null;
}

/** A2A aggregate is shaped differently (interactions, not executions). */
export interface A2AAggregateMetrics {
  totalInteractions?: number;
  successRate?: number;
  avgResponseTime?: number | null;
  minResponseTime?: number | null;
  maxResponseTime?: number | null;
}

/** `GET /metrics` response. `a2aAgents` is omitted when A2A metrics are disabled. */
export interface MetricsResponse {
  tools: EntityMetrics;
  resources: EntityMetrics;
  servers: EntityMetrics;
  prompts: EntityMetrics;
  a2aAgents?: A2AAggregateMetrics | null;
}

/** The four scalars rendered by the top System card. */
export interface SystemStats {
  executions: number;
  minResponseTime: number | null;
  avgResponseTime: number | null;
  maxResponseTime: number | null;
}

/**
 * Combine the per-type `/metrics` aggregates into a single system-wide summary.
 *
 * - `executions` sums every type's execution count (plus A2A interactions).
 * - `avgResponseTime` is execution-count weighted, so it is a true mean rather
 *   than a mean-of-means; buckets with no timing data are skipped.
 * - `min`/`max` are the extremes across all types.
 *
 * Returns `null` when metrics are unavailable (e.g. the request failed or the
 * caller lacks `admin.metrics`).
 */
export function aggregateSystemStats(metrics: MetricsResponse | undefined): SystemStats | null {
  if (!metrics) return null;

  let executions = 0;
  let weightedAvgSum = 0;
  let weightedAvgWeight = 0;
  let min: number | null = null;
  let max: number | null = null;

  const accumulate = (
    total: number,
    avg: number | null | undefined,
    lo: number | null | undefined,
    hi: number | null | undefined,
  ) => {
    executions += total;
    if (avg != null && total > 0) {
      weightedAvgSum += avg * total;
      weightedAvgWeight += total;
    }
    if (lo != null) min = min == null ? lo : Math.min(min, lo);
    if (hi != null) max = max == null ? hi : Math.max(max, hi);
  };

  for (const entity of [metrics.tools, metrics.resources, metrics.servers, metrics.prompts]) {
    if (!entity) continue;
    accumulate(
      entity.totalExecutions ?? 0,
      entity.avgResponseTime,
      entity.minResponseTime,
      entity.maxResponseTime,
    );
  }

  const a2a = metrics.a2aAgents;
  if (a2a) {
    accumulate(
      a2a.totalInteractions ?? 0,
      a2a.avgResponseTime,
      a2a.minResponseTime,
      a2a.maxResponseTime,
    );
  }

  return {
    executions,
    minResponseTime: min,
    avgResponseTime: weightedAvgWeight > 0 ? weightedAvgSum / weightedAvgWeight : null,
    maxResponseTime: max,
  };
}

/** Minimal shape of a list row used only to derive active/total counts. */
export interface Activatable {
  enabled?: boolean;
  reachable?: boolean;
}

export interface ActiveTotal {
  active: number;
  total: number;
}

/**
 * Count active vs. total rows. A row is "active" unless it is explicitly
 * disabled or explicitly unreachable; missing flags are treated as active
 * (list endpoints omit `reachable` for entities that have no upstream).
 *
 * Non-array input (undefined while loading, or an unexpected paginated wrapper)
 * counts as zero rather than throwing.
 */
export function countActiveTotal(items: Activatable[] | undefined): ActiveTotal {
  if (!Array.isArray(items)) return { active: 0, total: 0 };
  const active = items.filter((item) => item.enabled !== false && item.reachable !== false).length;
  return { active, total: items.length };
}

/** Placeholder shown whenever a value is unavailable. */
export const UNAVAILABLE = "—";

/** Format a response time the way the legacy admin UI does: 3 decimals + "ms". */
export function formatResponseTime(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return UNAVAILABLE;
  return `${value.toFixed(3)}ms`;
}

/** Derive a success-rate percentage from a `failureRate` in [0, 1]. */
export function formatSuccessRate(failureRate: number | null | undefined): string {
  if (failureRate == null || Number.isNaN(failureRate)) return UNAVAILABLE;
  return `${((1 - failureRate) * 100).toFixed(2)}%`;
}

/** Format a plain count, or the unavailable placeholder for missing data. */
export function formatCount(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return UNAVAILABLE;
  return String(value);
}
