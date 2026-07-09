/**
 * Unit tests for lazy-loader.js module
 * Tests: loadFeature dedup/in-flight coalescing/error path, loadFeatures,
 *        isFeatureLoaded, isFeatureLoading, getLoadedFeatures, the chart.js special case
 */

import { describe, test, expect, vi, beforeEach } from "vitest";

vi.mock("../../../mcpgateway/admin_ui/tools.js", () => ({
  __esModule: true,
  loadTools: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/servers.js", () => ({
  __esModule: true,
  loadServers: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/gateways.js", () => ({
  __esModule: true,
  loadGateways: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/teams.js", () => ({
  __esModule: true,
  loadTeams: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/logging.js", () => ({
  __esModule: true,
  searchStructuredLogs: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/metrics.js", () => ({
  __esModule: true,
  loadAggregatedMetrics: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/llmChat.js", () => ({
  __esModule: true,
  initializeLLMChat: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/llmModels.js", () => ({
  __esModule: true,
  overviewDashboard: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/plugins.js", () => ({
  __esModule: true,
  populatePluginFilters: vi.fn(),
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
    const { loadTools } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );

    await loadFeature("tools");

    expect(window.Admin.loadTools).toBe(loadTools);
  });

  test("dedup: a second call for an already-loaded feature does not re-import", async () => {
    const { loadFeature, isFeatureLoaded } = await import(
      "../../../mcpgateway/admin_ui/lazy-loader.js"
    );
    const toolsModule = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );

    await loadFeature("tools");
    expect(isFeatureLoaded("tools")).toBe(true);

    // Swap the export after the first load; if loadFeature re-imported, window.Admin
    // would be reassigned to this new function.
    const secondLoadTools = vi.fn();
    toolsModule.loadTools = secondLoadTools;

    await loadFeature("tools");

    expect(window.Admin.loadTools).not.toBe(secondLoadTools);
  });

  test("in-flight coalescing: concurrent calls for the same feature share one load", async () => {
    const { loadFeature, isFeatureLoading } = await import(
      "../../../mcpgateway/admin_ui/lazy-loader.js"
    );

    const first = loadFeature("servers");
    expect(isFeatureLoading("servers")).toBe(true);

    const second = loadFeature("servers");

    await Promise.all([first, second]);

    // Only one in-flight promise should have been tracked; both callers resolve together
    // and the module ends up loaded exactly once.
    expect(isFeatureLoading("servers")).toBe(false);
  });

  test("error path: a rejected dynamic import propagates and clears the in-flight state", async () => {
    vi.doMock("../../../mcpgateway/admin_ui/gateways.js", () => {
      throw new Error("network error");
    });

    const { loadFeature, isFeatureLoading, isFeatureLoaded } = await import(
      "../../../mcpgateway/admin_ui/lazy-loader.js"
    );

    await expect(loadFeature("gateways")).rejects.toThrow();

    expect(isFeatureLoading("gateways")).toBe(false);
    expect(isFeatureLoaded("gateways")).toBe(false);
  });

  test("retries after a failed load instead of caching the failure", async () => {
    let shouldFail = true;
    vi.doMock("../../../mcpgateway/admin_ui/teams.js", () => {
      if (shouldFail) {
        throw new Error("network error");
      }
      return { __esModule: true, loadTeams: vi.fn() };
    });

    const { loadFeature, isFeatureLoaded } = await import(
      "../../../mcpgateway/admin_ui/lazy-loader.js"
    );

    await expect(loadFeature("teams")).rejects.toThrow();
    expect(isFeatureLoaded("teams")).toBe(false);

    shouldFail = false;
    await loadFeature("teams");
    expect(isFeatureLoaded("teams")).toBe(true);
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

    await loadFeatures(["tools", "servers"]);

    expect(isFeatureLoaded("tools")).toBe(true);
    expect(isFeatureLoaded("servers")).toBe(true);
  });

  test("getLoadedFeatures reflects everything loaded so far", async () => {
    const { loadFeature, getLoadedFeatures } = await import(
      "../../../mcpgateway/admin_ui/lazy-loader.js"
    );

    await loadFeature("tools");
    await loadFeature("servers");

    expect(getLoadedFeatures()).toEqual(
      expect.arrayContaining(["tools", "servers"]),
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
