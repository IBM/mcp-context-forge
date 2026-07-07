/**
 * Observability metrics API service.
 *
 * Wraps the admin observability timeseries endpoints. Both endpoints require
 * the `admin.system_config` permission today, so callers must already be in an
 * admin session. Both rely on the `observability_traces` table being populated
 * (`OBSERVABILITY_ENABLED=true` on the gateway).
 */

import { api } from "@/api/client";

const HOURS_MIN = 1;
const HOURS_MAX = 168;
const INTERVAL_MIN = 5;
const INTERVAL_MAX = 1440;

export interface TimeseriesParams {
  /** Time range in hours (1-168). Defaults to 24 on the server. */
  hours?: number;
  /** Aggregation bucket size in minutes (5-1440). Defaults to 60 on the server. */
  intervalMinutes?: number;
  signal?: AbortSignal;
}

export interface TimeseriesResponse {
  timestamps: string[];
  request_count: number[];
  success_count: number[];
  error_count: number[];
  /** Error rate as a percentage (0-100), rounded to 2 decimals per bucket. */
  error_rate: number[];
}

export interface PercentilesResponse {
  timestamps: string[];
  /** Latency in milliseconds. */
  p50: number[];
  p90: number[];
  p95: number[];
  p99: number[];
}

export interface TokenSpendResponse {
  timestamps: string[];
  input_tokens: number[];
  output_tokens: number[];
  /** Estimated spend in USD per bucket, rounded to 6 decimals server-side. */
  cost_usd: number[];
}

function clampInt(value: number | undefined, min: number, max: number): number | undefined {
  if (value === undefined) return undefined;
  if (!Number.isFinite(value)) return undefined;
  return Math.max(min, Math.min(max, Math.floor(value)));
}

function buildQuery(params: TimeseriesParams): string {
  const search = new URLSearchParams();
  const hours = clampInt(params.hours, HOURS_MIN, HOURS_MAX);
  if (hours !== undefined) search.set("hours", hours.toString());

  const interval = clampInt(params.intervalMinutes, INTERVAL_MIN, INTERVAL_MAX);
  if (interval !== undefined) search.set("interval_minutes", interval.toString());

  const query = search.toString();
  return query ? `?${query}` : "";
}

export const metricsApi = {
  /**
   * Get request volume + success/error counts bucketed over time.
   */
  getTimeseries: (params: TimeseriesParams = {}): Promise<TimeseriesResponse> => {
    return api.get<TimeseriesResponse>(
      `/admin/observability/metrics/timeseries${buildQuery(params)}`,
      undefined,
      params.signal,
    );
  },

  /**
   * Get latency percentiles (p50, p90, p95, p99) bucketed over time, in milliseconds.
   */
  getPercentiles: (params: TimeseriesParams = {}): Promise<PercentilesResponse> => {
    return api.get<PercentilesResponse>(
      `/admin/observability/metrics/percentiles${buildQuery(params)}`,
      undefined,
      params.signal,
    );
  },

  /**
   * Get LLM token consumption (input/output) and estimated USD spend bucketed
   * over time. Sources rows from observability_metrics whose name is one of
   * llm.tokens.input, llm.tokens.output, llm.cost. Writer: the LLM proxy at
   * POST /v1/chat/completions records usage for non-streaming completions;
   * streaming coverage is a follow-up, so totals under-report until it lands.
   */
  getTokenSpend: (params: TimeseriesParams = {}): Promise<TokenSpendResponse> => {
    return api.get<TokenSpendResponse>(
      `/admin/observability/metrics/token-spend${buildQuery(params)}`,
      undefined,
      params.signal,
    );
  },
};

export const __test__ = { buildQuery, clampInt };
