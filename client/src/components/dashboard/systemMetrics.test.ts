import { describe, expect, it } from "vitest";

import {
  aggregateSystemStats,
  countActiveTotal,
  formatCount,
  formatResponseTime,
  formatSuccessRate,
  UNAVAILABLE,
  type EntityMetrics,
  type MetricsResponse,
} from "./systemMetrics";

function entity(overrides: Partial<EntityMetrics>): EntityMetrics {
  return {
    totalExecutions: 0,
    successfulExecutions: 0,
    failedExecutions: 0,
    failureRate: 0,
    minResponseTime: null,
    maxResponseTime: null,
    avgResponseTime: null,
    ...overrides,
  };
}

function metrics(overrides: Partial<MetricsResponse> = {}): MetricsResponse {
  return {
    tools: entity({}),
    resources: entity({}),
    servers: entity({}),
    prompts: entity({}),
    ...overrides,
  };
}

describe("aggregateSystemStats", () => {
  it("returns null when metrics are unavailable", () => {
    expect(aggregateSystemStats(undefined)).toBeNull();
  });

  it("sums executions across every entity type", () => {
    const result = aggregateSystemStats(
      metrics({
        tools: entity({ totalExecutions: 10 }),
        resources: entity({ totalExecutions: 5 }),
        servers: entity({ totalExecutions: 2 }),
        prompts: entity({ totalExecutions: 3 }),
      }),
    );
    expect(result?.executions).toBe(20);
  });

  it("includes A2A interactions in the execution total", () => {
    const result = aggregateSystemStats(
      metrics({
        tools: entity({ totalExecutions: 10 }),
        a2aAgents: { totalInteractions: 7 },
      }),
    );
    expect(result?.executions).toBe(17);
  });

  it("weights the average response time by execution count", () => {
    // tools: avg 1ms over 10 execs; servers: avg 3ms over 30 execs -> (10 + 90)/40 = 2.5
    const result = aggregateSystemStats(
      metrics({
        tools: entity({ totalExecutions: 10, avgResponseTime: 1 }),
        servers: entity({ totalExecutions: 30, avgResponseTime: 3 }),
      }),
    );
    expect(result?.avgResponseTime).toBeCloseTo(2.5, 6);
  });

  it("takes min/max across types and skips null timings", () => {
    const result = aggregateSystemStats(
      metrics({
        tools: entity({ totalExecutions: 1, minResponseTime: 0.5, maxResponseTime: 2 }),
        servers: entity({ totalExecutions: 1, minResponseTime: 0.2, maxResponseTime: 5 }),
        prompts: entity({ totalExecutions: 0, minResponseTime: null, maxResponseTime: null }),
      }),
    );
    expect(result?.minResponseTime).toBe(0.2);
    expect(result?.maxResponseTime).toBe(5);
  });

  it("yields a null average when no type has timing data", () => {
    const result = aggregateSystemStats(metrics({ tools: entity({ totalExecutions: 4 }) }));
    expect(result?.avgResponseTime).toBeNull();
  });
});

describe("countActiveTotal", () => {
  it("returns zeros for undefined input", () => {
    expect(countActiveTotal(undefined)).toEqual({ active: 0, total: 0 });
  });

  it("treats missing flags as active", () => {
    expect(countActiveTotal([{}, {}])).toEqual({ active: 2, total: 2 });
  });

  it("excludes disabled and unreachable rows from the active count", () => {
    const result = countActiveTotal([
      { enabled: true, reachable: true },
      { enabled: false },
      { enabled: true, reachable: false },
    ]);
    expect(result).toEqual({ active: 1, total: 3 });
  });
});

describe("formatters", () => {
  it("formats response times with three decimals and a ms suffix", () => {
    expect(formatResponseTime(0.472)).toBe("0.472ms");
    expect(formatResponseTime(0)).toBe("0.000ms");
  });

  it("returns the placeholder for missing response times", () => {
    expect(formatResponseTime(null)).toBe(UNAVAILABLE);
    expect(formatResponseTime(undefined)).toBe(UNAVAILABLE);
    expect(formatResponseTime(Number.NaN)).toBe(UNAVAILABLE);
  });

  it("derives success rate from failure rate", () => {
    expect(formatSuccessRate(0.0003)).toBe("99.97%");
    expect(formatSuccessRate(0)).toBe("100.00%");
  });

  it("returns the placeholder for a missing failure rate", () => {
    expect(formatSuccessRate(null)).toBe(UNAVAILABLE);
  });

  it("formats counts and falls back to the placeholder", () => {
    expect(formatCount(0)).toBe("0");
    expect(formatCount(17)).toBe("17");
    expect(formatCount(null)).toBe(UNAVAILABLE);
  });
});
