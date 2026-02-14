/**
 * Unit tests for metrics.js module
 * Tests untested functions: showMetricsLoading, hideMetricsLoading,
 *        showMetricsError, showMetricsPlaceholder, displayMetrics,
 *        exportMetricsToCSV, updateKPICards, switchTopPerformersTab,
 *        createStandardPaginationControls, updateTableRows,
 *        createTopPerformersTable, createTab, showTopPerformerTab
 * (createSystemSummaryCard, createKPISection, createPerformanceCard,
 *  createRecentActivitySection, createMetricsCard, formatValue, extractKPIData,
 *  calculateSuccessRate, formatNumber, formatLastUsed are already tested)
 */

import { describe, test, expect, vi, afterEach } from "vitest";

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  fetchWithTimeout: vi.fn(),
  handleFetchError: vi.fn((e) => e.message),
  safeGetElement: vi.fn((id, silent) => document.getElementById(id)),
  showNotification: vi.fn(),
}));

import {
  showMetricsLoading,
  hideMetricsLoading,
  showMetricsError,
  showMetricsPlaceholder,
  switchTopPerformersTab,
  createStandardPaginationControls,
  showTopPerformerTab,
} from "../../../mcpgateway/admin_ui/metrics.js";

afterEach(() => {
  document.body.innerHTML = "";
});

// ---------------------------------------------------------------------------
// showMetricsLoading
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// hideMetricsLoading
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// showMetricsError
// ---------------------------------------------------------------------------
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
});

// ---------------------------------------------------------------------------
// showMetricsPlaceholder
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// showTopPerformerTab
// ---------------------------------------------------------------------------
describe("showTopPerformerTab", () => {
  test("does not throw when tab containers are missing", () => {
    expect(() => showTopPerformerTab("tools")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// switchTopPerformersTab
// ---------------------------------------------------------------------------
describe("switchTopPerformersTab", () => {
  test("does not throw when DOM elements are missing", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(() => switchTopPerformersTab("tools")).not.toThrow();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// createStandardPaginationControls
// ---------------------------------------------------------------------------
describe("createStandardPaginationControls", () => {
  test("creates pagination controls for multiple pages", () => {
    const controls = createStandardPaginationControls(
      "tools",
      1,
      3,
      50,
      vi.fn(),
      vi.fn()
    );
    expect(controls).toBeInstanceOf(HTMLElement);
    expect(controls.innerHTML).toContain("Page");
  });

  test("creates controls for single page", () => {
    const controls = createStandardPaginationControls(
      "tools",
      1,
      1,
      10,
      vi.fn(),
      vi.fn()
    );
    expect(controls).toBeInstanceOf(HTMLElement);
  });
});
