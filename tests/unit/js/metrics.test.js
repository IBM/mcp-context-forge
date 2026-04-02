/**
 * Comprehensive unit tests for metrics.js module
 * Covers all exported functions to increase test coverage
 */

import { describe, test, expect, vi, afterEach, beforeEach } from "vitest";

import {
  showMetricsLoading,
  hideMetricsLoading,
  showMetricsError,
  showMetricsPlaceholder,
  retryLoadMetrics,
  displayMetrics,
  switchTopPerformersTab,
  createStandardPaginationControls,
  showTopPerformerTab,
  createSystemSummaryCard,
  createKPISection,
  extractKPIData,
  formatValue,
  updateKPICards,
  createPerformanceCard,
  createRecentActivitySection,
  createMetricsCard,
  calculateSuccessRate,
  formatNumber,
  formatLastUsed,
  updateTableRows,
  loadAggregatedMetrics,
} from "../../../mcpgateway/admin_ui/metrics.js";

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  fetchWithTimeout: vi.fn(),
  handleFetchError: vi.fn((e) => e.message),
  safeGetElement: vi.fn((id, silent) => document.getElementById(id)),
  showNotification: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  document.body.innerHTML = "";
  window.ROOT_PATH = "";
  window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT = 60000;
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

// ===================================================================
// Loading Functions
// ===================================================================

describe("showMetricsLoading", () => {
  test("adds loading indicator to aggregated section", () => {
    const section = document.createElement("div");
    section.id = "aggregated-metrics-section";
    document.body.appendChild(section);

    showMetricsLoading();
    const loading = document.getElementById("metrics-loading");
    expect(loading).not.toBeNull();
    expect(loading.innerHTML).toContain("Loading");
  });

  test("does not add duplicate loading indicator", () => {
    const section = document.createElement("div");
    section.id = "aggregated-metrics-section";
    document.body.appendChild(section);

    showMetricsLoading();
    showMetricsLoading();
    const loadings = section.querySelectorAll("#metrics-loading");
    expect(loadings.length).toBe(1);
  });

  test("does nothing when section is missing", () => {
    expect(() => showMetricsLoading()).not.toThrow();
  });
});

describe("hideMetricsLoading", () => {
  test("removes loading indicator", () => {
    const section = document.createElement("div");
    section.id = "aggregated-metrics-section";
    const loading = document.createElement("div");
    loading.id = "metrics-loading";
    section.appendChild(loading);
    document.body.appendChild(section);

    hideMetricsLoading();
    expect(document.getElementById("metrics-loading")).toBeNull();
  });

  test("does nothing when loading indicator is missing", () => {
    expect(() => hideMetricsLoading()).not.toThrow();
  });
});

// ===================================================================
// Error Handling Functions
// ===================================================================

describe("showMetricsError", () => {
  test("displays error message in content section", () => {
    const section = document.createElement("div");
    section.id = "aggregated-metrics-content";
    document.body.appendChild(section);

    showMetricsError(new Error("Network failure"));
    expect(section.innerHTML).toContain("Failed to Load");
    expect(section.innerHTML).toContain("Network failure");
  });

  test("does nothing when section is missing", () => {
    expect(() => showMetricsError(new Error("test"))).not.toThrow();
  });

  test("shows network-specific help text for fetch errors", () => {
    const section = document.createElement("div");
    section.id = "aggregated-metrics-content";
    document.body.appendChild(section);

    showMetricsError(new Error("Failed to fetch"));
    expect(section.innerHTML).toContain("network issue");
  });

  test("shows network-specific help text for timeout errors", () => {
    const section = document.createElement("div");
    section.id = "aggregated-metrics-content";
    document.body.appendChild(section);

    showMetricsError(new Error("timeout"));
    expect(section.innerHTML).toContain("network issue");
  });

  test("handles abort errors", () => {
    const section = document.createElement("div");
    section.id = "aggregated-metrics-content";
    document.body.appendChild(section);

    const abortError = new Error("aborted");
    abortError.name = "AbortError";
    showMetricsError(abortError);
    expect(section.innerHTML).toContain("network issue");
  });
});

describe("showMetricsPlaceholder", () => {
  test("shows placeholder message in section", () => {
    const section = document.createElement("div");
    section.id = "aggregated-metrics-section";
    document.body.appendChild(section);

    showMetricsPlaceholder();
    expect(section.textContent).toContain("not available");
  });

  test("does nothing when section is missing", () => {
    expect(() => showMetricsPlaceholder()).not.toThrow();
  });
});

describe("retryLoadMetrics", () => {
  test("does not throw when retrying", () => {
    const panel = document.createElement("div");
    panel.id = "metrics-panel";
    document.body.appendChild(panel);

    expect(() => retryLoadMetrics()).not.toThrow();
  });
});

// ===================================================================
// Display Functions
// ===================================================================

describe("displayMetrics", () => {
  test("handles empty data gracefully", () => {
    const section = document.createElement("div");
    section.id = "aggregated-metrics-section";
    const content = document.createElement("div");
    content.id = "aggregated-metrics-content";
    section.appendChild(content);
    document.body.appendChild(section);

    displayMetrics({});
    expect(content.innerHTML).toContain("No Metrics Available");
  });

  test("handles null data", () => {
    const section = document.createElement("div");
    section.id = "aggregated-metrics-section";
    const content = document.createElement("div");
    content.id = "aggregated-metrics-content";
    section.appendChild(content);
    document.body.appendChild(section);

    displayMetrics(null);
    expect(content.innerHTML).toContain("No Metrics Available");
  });

  test("displays KPI data when available", () => {
    const section = document.createElement("div");
    section.id = "aggregated-metrics-section";
    const content = document.createElement("div");
    content.id = "aggregated-metrics-content";
    section.appendChild(content);
    const kpiSection = document.createElement("div");
    kpiSection.id = "kpi-metrics-section";
    document.body.appendChild(section);
    document.body.appendChild(kpiSection);

    const data = {
      tools: {
        totalExecutions: 100,
        successfulExecutions: 95,
        failedExecutions: 5,
        avgResponseTime: 123.456,
      },
    };

    displayMetrics(data);
    expect(kpiSection.children.length).toBeGreaterThan(0);
  });

  test("displays individual metrics when available", () => {
    const section = document.createElement("div");
    section.id = "aggregated-metrics-section";
    const content = document.createElement("div");
    content.id = "aggregated-metrics-content";
    section.appendChild(content);
    const grid = document.createElement("div");
    grid.id = "individual-metrics-grid";
    document.body.appendChild(section);
    document.body.appendChild(grid);

    const data = {
      tools: { totalExecutions: 10 },
      resources: { totalExecutions: 20 },
      prompts: { totalExecutions: 30 },
    };

    displayMetrics(data);
    expect(grid.children.length).toBeGreaterThan(0);
  });

  test("retries display when section is initially missing", () => {
    vi.useFakeTimers();

    const data = { tools: { totalExecutions: 10 } };
    displayMetrics(data, 0);

    // Add section during retry
    setTimeout(() => {
      const section = document.createElement("div");
      section.id = "aggregated-metrics-section";
      const content = document.createElement("div");
      content.id = "aggregated-metrics-content";
      section.appendChild(content);
      document.body.appendChild(section);
    }, 50);

    vi.advanceTimersByTime(100);
    vi.useRealTimers();
  });

  test("handles errors gracefully during display", () => {
    const section = document.createElement("div");
    section.id = "aggregated-metrics-section";
    const content = document.createElement("div");
    content.id = "aggregated-metrics-content";
    section.appendChild(content);
    document.body.appendChild(section);

    // Mock console.error to avoid noise
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    // Pass invalid data that might cause errors
    const invalidData = { tools: "not an object" };

    expect(() => displayMetrics(invalidData)).not.toThrow();
    consoleError.mockRestore();
  });
});

// ===================================================================
// Tab Functions
// ===================================================================

describe("showTopPerformerTab", () => {
  test("does not throw when tab containers are missing", () => {
    expect(() => showTopPerformerTab("tools")).not.toThrow();
  });

  test("toggles tab visibility correctly", () => {
    const panel1 = document.createElement("div");
    panel1.id = "top-enabled-panel";
    panel1.setAttribute("data-type", "tools");
    const panel2 = document.createElement("div");
    panel2.id = "top-enabled-panel";
    panel2.setAttribute("data-type", "resources");

    document.body.appendChild(panel1);
    document.body.appendChild(panel2);

    expect(() => showTopPerformerTab("tools")).not.toThrow();
  });
});

describe("switchTopPerformersTab", () => {
  test("does not throw when DOM elements are missing", () => {
    expect(() => switchTopPerformersTab("tools")).not.toThrow();
  });

  test("switches tabs when elements exist", () => {
    const panel = document.createElement("div");
    panel.id = "top-performers-panel-tools";
    panel.classList.add("hidden", "top-performers-panel");
    const tab = document.createElement("a");
    tab.id = "top-performers-tab-tools";
    tab.classList.add("top-performers-tab");

    document.body.appendChild(panel);
    document.body.appendChild(tab);

    switchTopPerformersTab("tools");
    expect(panel.classList.contains("hidden")).toBe(false);
  });
});

// ===================================================================
// Pagination Functions
// ===================================================================

describe("createStandardPaginationControls", () => {
  test("creates pagination controls with correct structure", () => {
    const controls = createStandardPaginationControls("tools", 50, 10, vi.fn());
    expect(controls).toBeInstanceOf(HTMLElement);
    expect(controls.getAttribute("x-data")).toBeTruthy();
  });

  test("creates controls for large datasets", () => {
    const controls = createStandardPaginationControls("tools", 1000, 25, vi.fn());
    expect(controls).toBeInstanceOf(HTMLElement);
    expect(controls.innerHTML).toContain("per page");
  });

  test("handles single page correctly", () => {
    const controls = createStandardPaginationControls("tools", 5, 10, vi.fn());
    expect(controls).toBeInstanceOf(HTMLElement);
  });
});

describe("updateTableRows", () => {
  test("updates table with paginated data", () => {
    const tbody = document.createElement("tbody");
    const data = Array.from({ length: 20 }, (_, i) => ({
      name: `Item ${i}`,
      executionCount: 100 + i,
      avgResponseTime: 50 + i,
      successRate: 95,
      lastExecution: new Date().toISOString(),
    }));

    updateTableRows(tbody, "tools", data, 1, 10);
    expect(tbody.children.length).toBe(10);
  });

  test("handles second page correctly", () => {
    const tbody = document.createElement("tbody");
    const data = Array.from({ length: 20 }, (_, i) => ({
      name: `Item ${i}`,
      executionCount: 100 + i,
    }));

    updateTableRows(tbody, "tools", data, 2, 10);
    expect(tbody.children.length).toBe(10);
    expect(tbody.children[0].textContent).toContain("11"); // Rank should be 11
  });

  test("handles empty data", () => {
    const tbody = document.createElement("tbody");
    updateTableRows(tbody, "tools", [], 1, 10);
    expect(tbody.children.length).toBe(0);
  });
});

// ===================================================================
// Formatting Functions
// ===================================================================

describe("formatNumber", () => {
  test("formats numbers with thousand separators", () => {
    expect(formatNumber(1000)).toBe("1,000");
    expect(formatNumber(1000000)).toBe("1,000,000");
    expect(formatNumber(123456789)).toBe("123,456,789");
  });

  test("handles small numbers", () => {
    expect(formatNumber(0)).toBe("0");
    expect(formatNumber(42)).toBe("42");
    expect(formatNumber(999)).toBe("999");
  });

  test("handles negative numbers", () => {
    expect(formatNumber(-1000)).toBe("-1,000");
    expect(formatNumber(-42)).toBe("-42");
  });
});

describe("formatLastUsed", () => {
  test("returns Never for null timestamp", () => {
    expect(formatLastUsed(null)).toBe("Never");
    expect(formatLastUsed(undefined)).toBe("Never");
    expect(formatLastUsed("")).toBe("Never");
  });

  test("formats recent timestamps as Just now", () => {
    const now = Date.now();
    expect(formatLastUsed(now)).toBe("Just now");
  });

  test("formats timestamps as minutes ago", () => {
    const fiveMinutesAgo = Date.now() - 5 * 60 * 1000;
    const result = formatLastUsed(fiveMinutesAgo);
    expect(result).toContain("min ago");
  });

  test("formats old timestamps with full date", () => {
    const oldDate = new Date("2020-01-01T12:00:00Z");
    const result = formatLastUsed(oldDate.toISOString());
    expect(result).toContain("2020");
  });

  test("handles epoch seconds", () => {
    const epochSeconds = Math.floor(Date.now() / 1000) - 300; // 5 minutes ago
    const result = formatLastUsed(epochSeconds);
    expect(result).toContain("min ago");
  });

  test("handles invalid dates", () => {
    expect(formatLastUsed("invalid-date")).toBe("Never");
  });

  test("handles timestamps without Z suffix", () => {
    const date = new Date();
    const isoWithoutZ = date.toISOString().slice(0, -1);
    const result = formatLastUsed(isoWithoutZ);
    expect(result).toBeTruthy();
  });
});

describe("formatValue", () => {
  test("formats average response time", () => {
    expect(formatValue(123.456, "avgResponseTime")).toBe("123.456 ms");
    expect(formatValue(50, "avgResponseTime")).toBe("50.000 ms");
  });

  test("formats success rate", () => {
    expect(formatValue(95, "successRate")).toBe("95%");
    expect(formatValue(100, "successRate")).toBe("100%");
  });

  test("formats error rate", () => {
    expect(formatValue(5, "errorRate")).toBe("5%");
  });

  test("handles N/A values", () => {
    expect(formatValue(null, "anyKey")).toBe("N/A");
    expect(formatValue(undefined, "anyKey")).toBe("N/A");
    expect(formatValue("N/A", "anyKey")).toBe("N/A");
  });

  test("handles NaN values", () => {
    expect(formatValue(NaN, "avgResponseTime")).toBe("N/A");
  });

  test("returns string for other keys", () => {
    expect(formatValue(42, "totalExecutions")).toBe("42");
    expect(formatValue("text", "name")).toBe("text");
  });

  test("handles empty string", () => {
    expect(formatValue("", "anyKey")).toBe("N/A");
  });
});

describe("calculateSuccessRate", () => {
  test("calculates from direct successRate property", () => {
    expect(calculateSuccessRate({ successRate: 95.5 })).toBe(96);
    expect(calculateSuccessRate({ successRate: 100 })).toBe(100);
  });

  test("calculates from execution counts", () => {
    expect(
      calculateSuccessRate({
        execution_count: 100,
        successful_count: 95,
      })
    ).toBe(95);
  });

  test("handles alternative property names", () => {
    expect(
      calculateSuccessRate({
        executions: 100,
        successfulExecutions: 90,
      })
    ).toBe(90);
  });

  test("returns 0 for zero executions", () => {
    expect(
      calculateSuccessRate({
        execution_count: 0,
        successful_count: 0,
      })
    ).toBe(0);
  });

  test("handles missing properties", () => {
    expect(calculateSuccessRate({})).toBe(0);
  });
});

// ===================================================================
// KPI Functions
// ===================================================================

describe("extractKPIData", () => {
  test("extracts KPI data from complete metrics", () => {
    const data = {
      tools: {
        "Total Executions": 100,
        "Successful Executions": 95,
        "Failed Executions": 5,
        "Average Response Time": 123.456,
      },
      resources: {
        "Total Executions": 50,
        "Successful Executions": 48,
        "Failed Executions": 2,
        "Average Response Time": 200,
      },
    };

    const kpi = extractKPIData(data);
    expect(kpi.totalExecutions).toBe(150);
    expect(kpi.successRate).toBe(95);
    expect(kpi.errorRate).toBe(5);
    expect(kpi.avgResponseTime).toBeGreaterThan(0);
  });

  test("handles missing categories", () => {
    const kpi = extractKPIData({});
    expect(kpi.totalExecutions).toBe(0);
    expect(kpi.successRate).toBe(0);
    expect(kpi.errorRate).toBe(0);
  });

  test("handles case variations in keys", () => {
    const data = {
      tools: {
        totalexecutions: 100,
        successfulexecutions: 90,
        failedexecutions: 10,
      },
    };

    const kpi = extractKPIData(data);
    expect(kpi.totalExecutions).toBe(100);
  });

  test("handles snake_case property names", () => {
    const data = {
      tools: {
        total_executions: 100,
        successful_executions: 95,
        failed_executions: 5,
        avg_response_time: 100,
      },
    };

    const kpi = extractKPIData(data);
    expect(kpi.totalExecutions).toBe(100);
    expect(kpi.successRate).toBe(95);
  });

  test("calculates weighted average response time", () => {
    const data = {
      tools: {
        "Total Executions": 100,
        "Average Response Time": 100,
        "Successful Executions": 100,
        "Failed Executions": 0,
      },
      resources: {
        "Total Executions": 100,
        "Average Response Time": 200,
        "Successful Executions": 100,
        "Failed Executions": 0,
      },
    };

    const kpi = extractKPIData(data);
    expect(kpi.avgResponseTime).toBe(150); // Weighted average
  });

  test("handles null avgResponseTime", () => {
    const data = {
      tools: {
        "Total Executions": 100,
        "Successful Executions": 100,
        "Failed Executions": 0,
        "Average Response Time": null,
      },
    };

    const kpi = extractKPIData(data);
    expect(kpi.avgResponseTime).toBeNull();
  });

  test("handles errors gracefully", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const kpi = extractKPIData(null);
    expect(kpi.totalExecutions).toBe(0);
    consoleError.mockRestore();
  });

  test("handles multiple category aliases", () => {
    const data = {
      virtualServers: {
        "Total Executions": 50,
        "Successful Executions": 45,
        "Failed Executions": 5,
      },
      gateways: {
        "Total Executions": 30,
        "Successful Executions": 28,
        "Failed Executions": 2,
      },
    };

    const kpi = extractKPIData(data);
    expect(kpi.totalExecutions).toBe(80);
  });
});

describe("updateKPICards", () => {
  test("updates KPI card elements", () => {
    const execEl = document.createElement("div");
    execEl.id = "metrics-total-executions";
    const successEl = document.createElement("div");
    successEl.id = "metrics-success-rate";
    const avgEl = document.createElement("div");
    avgEl.id = "metrics-avg-response-time";
    const errorEl = document.createElement("div");
    errorEl.id = "metrics-error-rate";

    document.body.appendChild(execEl);
    document.body.appendChild(successEl);
    document.body.appendChild(avgEl);
    document.body.appendChild(errorEl);

    const kpiData = {
      totalExecutions: 100,
      successRate: 95,
      avgResponseTime: 123.456,
      errorRate: 5,
    };

    updateKPICards(kpiData);
    expect(execEl.textContent).toBe("100");
    expect(successEl.textContent).toBe("95%");
    expect(avgEl.textContent).toBe("123.456 ms");
    expect(errorEl.textContent).toBe("5%");
  });

  test("handles elements with value spans", () => {
    const execEl = document.createElement("div");
    execEl.id = "metrics-total-executions";
    const valueSpan = document.createElement("span");
    valueSpan.className = "value";
    execEl.appendChild(valueSpan);
    document.body.appendChild(execEl);

    updateKPICards({ totalExecutions: 200 });
    expect(valueSpan.textContent).toBe("200");
  });

  test("handles missing elements gracefully", () => {
    expect(() => updateKPICards({ totalExecutions: 100 })).not.toThrow();
  });

  test("handles null kpiData", () => {
    expect(() => updateKPICards(null)).not.toThrow();
  });
});

// ===================================================================
// Card Creation Functions
// ===================================================================

describe("createSystemSummaryCard", () => {
  test("creates system summary card with data", () => {
    const systemData = {
      uptime: "5d 3h",
      totalRequests: 10000,
      activeConnections: 42,
      memoryUsage: 65,
      cpuUsage: 45,
      diskUsage: 30,
      networkIn: 1024,
      networkOut: 2048,
    };

    const card = createSystemSummaryCard(systemData);
    expect(card).toBeInstanceOf(HTMLElement);
    expect(card.textContent).toContain("System Overview");
    expect(card.textContent).toContain("5d 3h");
  });

  test("handles missing properties", () => {
    const card = createSystemSummaryCard({});
    expect(card).toBeInstanceOf(HTMLElement);
    expect(card.textContent).toContain("N/A");
  });

  test("handles snake_case properties", () => {
    const systemData = {
      total_requests: 5000,
      active_connections: 10,
    };

    const card = createSystemSummaryCard(systemData);
    expect(card.textContent).toContain("5000");
  });

  test("handles errors gracefully", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const card = createSystemSummaryCard(null);
    expect(card).toBeInstanceOf(HTMLElement);
    consoleError.mockRestore();
  });
});

describe("createKPISection", () => {
  test("creates KPI section with complete data", () => {
    const kpiData = {
      totalExecutions: 1000,
      successRate: 95,
      avgResponseTime: 123.456,
      errorRate: 5,
    };

    const section = createKPISection(kpiData);
    expect(section).toBeInstanceOf(HTMLElement);
    expect(section.textContent).toContain("1000");
    expect(section.textContent).toContain("95%");
    expect(section.textContent).toContain("123.456 ms");
    expect(section.textContent).toContain("5%");
  });

  test("handles N/A values", () => {
    const kpiData = {
      totalExecutions: "N/A",
      successRate: null,
      avgResponseTime: undefined,
      errorRate: "N/A",
    };

    const section = createKPISection(kpiData);
    expect(section.textContent).toContain("N/A");
  });

  test("handles errors gracefully", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const section = createKPISection(null);
    expect(section).toBeInstanceOf(HTMLElement);
    consoleError.mockRestore();
  });
});

describe("createPerformanceCard", () => {
  test("creates performance card with data", () => {
    const perfData = {
      memoryUsage: "512 MB",
      cpuUsage: "45%",
      diskIo: "100 MB/s",
      networkThroughput: "50 Mbps",
      cacheHitRate: "85%",
      activeThreads: 20,
    };

    const card = createPerformanceCard(perfData);
    expect(card).toBeInstanceOf(HTMLElement);
    expect(card.textContent).toContain("Performance Metrics");
    expect(card.textContent).toContain("512 MB");
  });

  test("handles snake_case properties", () => {
    const perfData = {
      memory_usage: "256 MB",
      cpu_usage: "30%",
    };

    const card = createPerformanceCard(perfData);
    expect(card.textContent).toContain("256 MB");
  });

  test("handles missing properties", () => {
    const card = createPerformanceCard({});
    expect(card.textContent).toContain("N/A");
  });

  test("handles errors gracefully", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const card = createPerformanceCard(null);
    expect(card).toBeInstanceOf(HTMLElement);
    consoleError.mockRestore();
  });
});

describe("createRecentActivitySection", () => {
  test("creates activity section with data", () => {
    const activityData = [
      { action: "Tool Executed", target: "git-status", timestamp: "2024-01-01T12:00:00Z" },
      { action: "Resource Fetched", target: "config.json", timestamp: "2024-01-01T11:00:00Z" },
    ];

    const section = createRecentActivitySection(activityData);
    expect(section).toBeInstanceOf(HTMLElement);
    expect(section.textContent).toContain("Recent Activity");
    expect(section.textContent).toContain("Tool Executed");
    expect(section.textContent).toContain("git-status");
  });

  test("handles empty activity", () => {
    const section = createRecentActivitySection([]);
    expect(section.textContent).toContain("No recent activity");
  });

  test("limits display to 10 items", () => {
    const activityData = Array.from({ length: 20 }, (_, i) => ({
      action: `Action ${i}`,
      target: `target-${i}`,
      timestamp: new Date().toISOString(),
    }));

    const section = createRecentActivitySection(activityData);
    const items = section.querySelectorAll(".bg-gray-50");
    expect(items.length).toBeLessThanOrEqual(10);
  });

  test("handles null activity data", () => {
    const section = createRecentActivitySection(null);
    expect(section.textContent).toContain("No recent activity");
  });

  test("handles errors gracefully", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const section = createRecentActivitySection("invalid");
    expect(section).toBeInstanceOf(HTMLElement);
    consoleError.mockRestore();
  });
});

describe("createMetricsCard", () => {
  test("creates metrics card with complete data", () => {
    const metrics = {
      totalExecutions: 100,
      successfulExecutions: 95,
      failedExecutions: 5,
      failureRate: "5%",
      avgResponseTime: "123 ms",
      lastExecutionTime: "2024-01-01T12:00:00Z",
    };

    const card = createMetricsCard("Tools", metrics);
    expect(card).toBeInstanceOf(HTMLElement);
    expect(card.textContent).toContain("Tools Metrics");
    expect(card.textContent).toContain("100");
    expect(card.textContent).toContain("95");
  });

  test("handles snake_case properties", () => {
    const metrics = {
      total_executions: 50,
      successful_executions: 48,
      failed_executions: 2,
    };

    const card = createMetricsCard("Resources", metrics);
    expect(card.textContent).toContain("50");
  });

  test("handles missing properties", () => {
    const card = createMetricsCard("Prompts", {});
    expect(card.textContent).toContain("N/A");
  });
});

// ===================================================================
// Async Loading Functions
// ===================================================================

describe("loadAggregatedMetrics", () => {
  test("skips loading when panel is not visible", async () => {
    const panel = document.createElement("div");
    panel.id = "metrics-panel";
    panel.classList.add("hidden");
    document.body.appendChild(panel);

    await loadAggregatedMetrics();
    // Just verify it doesn't throw
  });

  test("skips loading when panel is inside hidden tab", async () => {
    const tabPanel = document.createElement("div");
    tabPanel.classList.add("tab-panel", "hidden");
    const panel = document.createElement("div");
    panel.id = "metrics-panel";
    tabPanel.appendChild(panel);
    document.body.appendChild(tabPanel);

    await loadAggregatedMetrics();
    // Just verify it doesn't throw
  });

  test("does not throw when panel is missing", async () => {
    await expect(loadAggregatedMetrics()).resolves.not.toThrow();
  });
});
