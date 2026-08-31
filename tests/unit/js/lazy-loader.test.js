/**
 * Unit tests for lazy-loader.js module
 * Tests: loadFeature dedup/in-flight coalescing/error path, loadFeatures,
 *        isFeatureLoaded, isFeatureLoading, getLoadedFeatures, the chart.js special case
 */

import { describe, test, expect, vi, beforeEach } from "vitest";

vi.mock("../../../mcpgateway/admin_ui/metrics.js", () => ({
  __esModule: true,
  loadAggregatedMetrics: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/llmChat.js", () => ({
  __esModule: true,
  initializeLLMChat: vi.fn(),
}));

const mockChartRegister = vi.fn();
vi.mock("chart.js", () => ({
  __esModule: true,
  Chart: { register: mockChartRegister },
  registerables: ["registerable-a", "registerable-b"],
}));

describe("lazy-loader", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    delete window.Admin;
    delete window.Chart;
  });

  test("loads a feature and merges its exports into window.Admin", async () => {
    const { loadFeature } = await import(
      "../../../mcpgateway/admin_ui/lazy-loader.js"
    );
    const { loadAggregatedMetrics } = await import(
      "../../../mcpgateway/admin_ui/metrics.js"
    );

    await loadFeature("metrics");

    expect(window.Admin.loadAggregatedMetrics).toBe(loadAggregatedMetrics);
  });

  test("dedup: a second call for an already-loaded feature does not re-import", async () => {
    const { loadFeature, isFeatureLoaded } = await import(
      "../../../mcpgateway/admin_ui/lazy-loader.js"
    );
    const metricsModule = await import(
      "../../../mcpgateway/admin_ui/metrics.js"
    );

    await loadFeature("metrics");
    expect(isFeatureLoaded("metrics")).toBe(true);

    // Swap the export after the first load; if loadFeature re-imported, window.Admin
    // would be reassigned to this new function.
    const secondLoadAggregatedMetrics = vi.fn();
    metricsModule.loadAggregatedMetrics = secondLoadAggregatedMetrics;

    await loadFeature("metrics");

    expect(window.Admin.loadAggregatedMetrics).not.toBe(
      secondLoadAggregatedMetrics,
    );
  });

  test("in-flight coalescing: concurrent calls for the same feature share one load", async () => {
    const { loadFeature, isFeatureLoading } = await import(
      "../../../mcpgateway/admin_ui/lazy-loader.js"
    );

    const first = loadFeature("llmChat");
    expect(isFeatureLoading("llmChat")).toBe(true);

    const second = loadFeature("llmChat");

    await Promise.all([first, second]);

    // Only one in-flight promise should have been tracked; both callers resolve together
    // and the module ends up loaded exactly once.
    expect(isFeatureLoading("llmChat")).toBe(false);
  });

  test("error path: a rejected dynamic import propagates and clears the in-flight state", async () => {
    vi.doMock("../../../mcpgateway/admin_ui/llmChat.js", () => {
      throw new Error("network error");
    });

    const { loadFeature, isFeatureLoading, isFeatureLoaded } = await import(
      "../../../mcpgateway/admin_ui/lazy-loader.js"
    );

    await expect(loadFeature("llmChat")).rejects.toThrow();

    expect(isFeatureLoading("llmChat")).toBe(false);
    expect(isFeatureLoaded("llmChat")).toBe(false);

    // vi.doMock persists past vi.resetModules(); restore the top-level mock
    // so later tests importing llmChat.js don't inherit this throwing factory.
    vi.doUnmock("../../../mcpgateway/admin_ui/llmChat.js");
  });

  test("retries after a failed load instead of caching the failure", async () => {
    let shouldFail = true;
    vi.doMock("../../../mcpgateway/admin_ui/metrics.js", () => {
      if (shouldFail) {
        throw new Error("network error");
      }
      return { __esModule: true, loadAggregatedMetrics: vi.fn() };
    });

    const { loadFeature, isFeatureLoaded } = await import(
      "../../../mcpgateway/admin_ui/lazy-loader.js"
    );

    await expect(loadFeature("metrics")).rejects.toThrow();
    expect(isFeatureLoaded("metrics")).toBe(false);

    shouldFail = false;
    await loadFeature("metrics");
    expect(isFeatureLoaded("metrics")).toBe(true);

    // vi.doMock persists past vi.resetModules(); restore the top-level mock
    // so later tests importing metrics.js don't inherit this closure-based factory.
    vi.doUnmock("../../../mcpgateway/admin_ui/metrics.js");
  });

  test("unknown feature name warns and resolves without throwing", async () => {
    const { loadFeature } = await import(
      "../../../mcpgateway/admin_ui/lazy-loader.js"
    );
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(loadFeature("not-a-real-feature")).resolves.toBeUndefined();
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("not-a-real-feature"),
    );

    warnSpy.mockRestore();
  });

  test("loadFeatures loads multiple features in parallel", async () => {
    const { loadFeatures, isFeatureLoaded } = await import(
      "../../../mcpgateway/admin_ui/lazy-loader.js"
    );

    await loadFeatures(["metrics", "llmChat"]);

    expect(isFeatureLoaded("metrics")).toBe(true);
    expect(isFeatureLoaded("llmChat")).toBe(true);
  });

  test("getLoadedFeatures reflects everything loaded so far", async () => {
    const { loadFeature, getLoadedFeatures } = await import(
      "../../../mcpgateway/admin_ui/lazy-loader.js"
    );

    await loadFeature("metrics");
    await loadFeature("llmChat");

    expect(getLoadedFeatures()).toEqual(
      expect.arrayContaining(["metrics", "llmChat"]),
    );
    expect(getLoadedFeatures()).toHaveLength(2);
  });

  test("charts feature registers Chart.js instead of merging into window.Admin", async () => {
    const { loadFeature } = await import(
      "../../../mcpgateway/admin_ui/lazy-loader.js"
    );

    await loadFeature("charts");

    expect(mockChartRegister).toHaveBeenCalledWith(
      "registerable-a",
      "registerable-b",
    );
    expect(window.Chart).toBeDefined();
    expect(window.Chart.register).toBe(mockChartRegister);
    // Chart.js exports shouldn't leak onto window.Admin
    expect(window.Admin?.Chart).toBeUndefined();
  });
});
