/**
 * Unit tests for app.js module
 * Tests: Chart registry, HTMX handlers, initialization
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

// Mock dependencies
vi.mock("../../../mcpgateway/admin_ui/logging.js", () => ({
  emergencyFixMCPSearch: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/plugins.js", () => ({
  populatePluginFilters: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  installInnerHtmlGuard: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/servers.js", () => ({
  getEditSelections: vi.fn(() => new Set()),
  updatePromptMapping: vi.fn(),
  updateResourceMapping: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  isAdminUser: vi.fn(() => true),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));

describe("app.js - Chart Registry", () => {
  beforeEach(async () => {
    // Initialize Admin object
    window.Admin = {};

    // Load the app.js module to initialize chartRegistry
    vi.resetModules();
    await import("../../../mcpgateway/admin_ui/app.js");
  });

  afterEach(() => {
    if (window.Admin && window.Admin.chartRegistry) {
      window.Admin.chartRegistry.destroyAll();
    }
    delete window.Admin;
  });

  test("chartRegistry is initialized", () => {
    expect(window.Admin.chartRegistry).toBeDefined();
    expect(window.Admin.chartRegistry.charts).toBeInstanceOf(Map);
  });

  test("register() adds chart to registry", () => {
    const mockChart = { destroy: vi.fn() };
    window.Admin.chartRegistry.register("test-chart", mockChart);

    expect(window.Admin.chartRegistry.has("test-chart")).toBe(true);
    expect(window.Admin.chartRegistry.get("test-chart")).toBe(mockChart);
  });

  test("register() destroys existing chart before registering new one", () => {
    const oldChart = { destroy: vi.fn() };
    const newChart = { destroy: vi.fn() };

    window.Admin.chartRegistry.register("test-chart", oldChart);
    window.Admin.chartRegistry.register("test-chart", newChart);

    expect(oldChart.destroy).toHaveBeenCalled();
    expect(window.Admin.chartRegistry.get("test-chart")).toBe(newChart);
  });

  test("destroy() removes chart from registry", () => {
    const mockChart = { destroy: vi.fn() };
    window.Admin.chartRegistry.register("test-chart", mockChart);

    window.Admin.chartRegistry.destroy("test-chart");

    expect(mockChart.destroy).toHaveBeenCalled();
    expect(window.Admin.chartRegistry.has("test-chart")).toBe(false);
  });

  test("destroy() handles non-existent chart gracefully", () => {
    expect(() => {
      window.Admin.chartRegistry.destroy("non-existent");
    }).not.toThrow();
  });

  test("destroy() handles chart destruction errors", () => {
    const mockChart = {
      destroy: vi.fn(() => {
        throw new Error("Destruction failed");
      }),
    };
    window.Admin.chartRegistry.register("test-chart", mockChart);

    expect(() => {
      window.Admin.chartRegistry.destroy("test-chart");
    }).not.toThrow();

    expect(window.Admin.chartRegistry.has("test-chart")).toBe(false);
  });

  test("destroyAll() removes all charts", () => {
    const chart1 = { destroy: vi.fn() };
    const chart2 = { destroy: vi.fn() };
    const chart3 = { destroy: vi.fn() };

    window.Admin.chartRegistry.register("chart-1", chart1);
    window.Admin.chartRegistry.register("chart-2", chart2);
    window.Admin.chartRegistry.register("chart-3", chart3);

    window.Admin.chartRegistry.destroyAll();

    expect(chart1.destroy).toHaveBeenCalled();
    expect(chart2.destroy).toHaveBeenCalled();
    expect(chart3.destroy).toHaveBeenCalled();
    expect(window.Admin.chartRegistry.size()).toBe(0);
  });

  test("destroyByPrefix() removes charts matching prefix", () => {
    const chart1 = { destroy: vi.fn() };
    const chart2 = { destroy: vi.fn() };
    const chart3 = { destroy: vi.fn() };

    window.Admin.chartRegistry.register("metrics-chart-1", chart1);
    window.Admin.chartRegistry.register("metrics-chart-2", chart2);
    window.Admin.chartRegistry.register("other-chart", chart3);

    window.Admin.chartRegistry.destroyByPrefix("metrics-");

    expect(chart1.destroy).toHaveBeenCalled();
    expect(chart2.destroy).toHaveBeenCalled();
    expect(chart3.destroy).not.toHaveBeenCalled();
    expect(window.Admin.chartRegistry.has("other-chart")).toBe(true);
  });

  test("size() returns correct chart count", () => {
    expect(window.Admin.chartRegistry.size()).toBe(0);

    window.Admin.chartRegistry.register("chart-1", { destroy: vi.fn() });
    expect(window.Admin.chartRegistry.size()).toBe(1);

    window.Admin.chartRegistry.register("chart-2", { destroy: vi.fn() });
    expect(window.Admin.chartRegistry.size()).toBe(2);

    window.Admin.chartRegistry.destroy("chart-1");
    expect(window.Admin.chartRegistry.size()).toBe(1);
  });

  test("has() returns correct boolean", () => {
    expect(window.Admin.chartRegistry.has("test-chart")).toBe(false);

    window.Admin.chartRegistry.register("test-chart", { destroy: vi.fn() });
    expect(window.Admin.chartRegistry.has("test-chart")).toBe(true);

    window.Admin.chartRegistry.destroy("test-chart");
    expect(window.Admin.chartRegistry.has("test-chart")).toBe(false);
  });

  test("get() returns correct chart", () => {
    const mockChart = { destroy: vi.fn() };
    window.Admin.chartRegistry.register("test-chart", mockChart);

    expect(window.Admin.chartRegistry.get("test-chart")).toBe(mockChart);
    expect(window.Admin.chartRegistry.get("non-existent")).toBeUndefined();
  });
});

describe("app.js - HTMX Tools Handler", () => {
  beforeEach(() => {
    vi.resetModules();
    window.Admin = {};
    window.htmx = {
      on: vi.fn(),
    };
    document.body.innerHTML = `
      <div id="associatedTools">
        <input name="selectAllTools" value="false" />
      </div>
      <div id="edit-server-tools" data-server-tools='["tool1", "tool2"]'>
        <input name="selectAllTools" value="false" />
      </div>
    `;
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.Admin;
    delete window.htmx;
    delete window._toolsHtmxHandlerAttached;
    delete window._resourcesHtmxHandlerAttached;
    delete window._promptsHtmxHandlerAttached;
  });

  test("HTMX tools handler is attached", async () => {
    await import("../../../mcpgateway/admin_ui/app.js");

    expect(window.htmx.on).toHaveBeenCalledWith(
      "htmx:afterSettle",
      expect.any(Function)
    );
  });

  test("tools handler only attaches once", async () => {
    window._toolsHtmxHandlerAttached = true;
    await import("../../../mcpgateway/admin_ui/app.js");

    // Tools handler is skipped; resources + prompts handlers still attach
    const callCount = window.htmx.on.mock.calls.filter(
      (call) => call[0] === "htmx:afterSettle"
    ).length;
    expect(callCount).toBe(2);
  });
});

describe("app.js - HTMX Resources Handler", () => {
  beforeEach(() => {
    vi.resetModules();
    window.Admin = {};
    window.htmx = {
      on: vi.fn(),
    };
    document.body.innerHTML = `
      <div id="associatedResources">
        <input name="selectAllResources" value="false" />
      </div>
      <div id="edit-server-resources" data-server-resources='["res1", "res2"]'>
        <input name="selectAllResources" value="false" />
      </div>
    `;
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.Admin;
    delete window.htmx;
    delete window._toolsHtmxHandlerAttached;
    delete window._resourcesHtmxHandlerAttached;
    delete window._promptsHtmxHandlerAttached;
  });

  test("HTMX resources handler is attached", async () => {
    await import("../../../mcpgateway/admin_ui/app.js");

    expect(window.htmx.on).toHaveBeenCalled();
  });

  test("resources handler only attaches once", async () => {
    window._resourcesHtmxHandlerAttached = true;
    await import("../../../mcpgateway/admin_ui/app.js");

    // Resources handler is skipped; tools + prompts handlers still attach
    const callCount = window.htmx.on.mock.calls.filter(
      (call) => call[0] === "htmx:afterSettle"
    ).length;
    expect(callCount).toBe(2);
  });
});

describe("app.js - HTMX Prompts Handler", () => {
  beforeEach(() => {
    vi.resetModules();
    window.Admin = {};
    window.htmx = {
      on: vi.fn(),
    };
    document.body.innerHTML = `
      <div id="associatedPrompts">
        <input name="selectAllPrompts" value="false" />
      </div>
      <div id="edit-server-prompts" data-server-prompts='["prompt1", "prompt2"]'>
        <input name="selectAllPrompts" value="false" />
      </div>
    `;
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.Admin;
    delete window.htmx;
    delete window._toolsHtmxHandlerAttached;
    delete window._resourcesHtmxHandlerAttached;
    delete window._promptsHtmxHandlerAttached;
  });

  test("HTMX prompts handler is attached", async () => {
    await import("../../../mcpgateway/admin_ui/app.js");

    expect(window.htmx.on).toHaveBeenCalled();
  });

  test("prompts handler only attaches once", async () => {
    window._promptsHtmxHandlerAttached = true;
    await import("../../../mcpgateway/admin_ui/app.js");

    // Prompts handler is skipped; tools + resources handlers still attach
    const callCount = window.htmx.on.mock.calls.filter(
      (call) => call[0] === "htmx:afterSettle"
    ).length;
    expect(callCount).toBe(2);
  });
});

describe("app.js - Initialization", () => {
  beforeEach(() => {
    vi.resetModules();
    window.Admin = {};
    document.body.innerHTML = `
      <div id="plugins-panel"></div>
    `;
    vi.useFakeTimers();
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.Admin;
    vi.useRealTimers();
  });

  test("installs innerHTML guard", async () => {
    const { installInnerHtmlGuard } = await import("../../../mcpgateway/admin_ui/security.js");

    await import("../../../mcpgateway/admin_ui/app.js");

    expect(installInnerHtmlGuard).toHaveBeenCalled();
  });

  test("populates plugin filters when plugins panel exists and user is admin", async () => {
    const { populatePluginFilters } = await import("../../../mcpgateway/admin_ui/plugins.js");
    const { isAdminUser } = await import("../../../mcpgateway/admin_ui/utils.js");

    isAdminUser.mockReturnValue(true);

    await import("../../../mcpgateway/admin_ui/app.js");

    expect(populatePluginFilters).toHaveBeenCalled();
  });

  test("does not populate plugin filters when user is not admin", async () => {
    const { populatePluginFilters } = await import("../../../mcpgateway/admin_ui/plugins.js");
    const { isAdminUser } = await import("../../../mcpgateway/admin_ui/utils.js");

    isAdminUser.mockReturnValue(false);
    populatePluginFilters.mockClear();

    await import("../../../mcpgateway/admin_ui/app.js");

    expect(populatePluginFilters).not.toHaveBeenCalled();
  });

  test("does not populate plugin filters when plugins panel does not exist", async () => {
    document.body.innerHTML = "";
    const { populatePluginFilters } = await import("../../../mcpgateway/admin_ui/plugins.js");

    populatePluginFilters.mockClear();

    await import("../../../mcpgateway/admin_ui/app.js");

    expect(populatePluginFilters).not.toHaveBeenCalled();
  });

  test("calls emergencyFixMCPSearch after 1 second", async () => {
    const { emergencyFixMCPSearch } = await import("../../../mcpgateway/admin_ui/logging.js");

    await import("../../../mcpgateway/admin_ui/app.js");

    expect(emergencyFixMCPSearch).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1000);

    expect(emergencyFixMCPSearch).toHaveBeenCalled();
  });
});
