/**
 * Unit tests for logging.js module
 * Tests: getLogLevelClass, getSeverityClass, searchStructuredLogs,
 *        previousLogPage, nextLogPage, showCorrelationTrace, displayCorrelationTrace,
 *        showSecurityEvents, displaySecurityEvents, showAuditTrail,
 *        displayAuditTrail, showPerformanceMetrics, displayPerformanceMetrics,
 *        restoreLogTableHeaders
 * (getPerformanceAggregationConfig/Label/Query, displayLogResults,
 *  generateStatusBadgeHtml are already tested)
 */

import { describe, test, expect, vi, afterEach } from "vitest";

import {
  getLogLevelClass,
  getSeverityClass,
  searchStructuredLogs,
  showCorrelationTrace,
  displayCorrelationTrace,
  showSecurityEvents,
  displaySecurityEvents,
  showAuditTrail,
  displayAuditTrail,
  restoreLogTableHeaders,
  setPerformanceAggregationVisibility,
  setLogFiltersVisibility,
} from "../../../mcpgateway/admin_ui/logging.js";
import { fetchWithAuth } from "../../../mcpgateway/admin_ui/tokens.js";

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
}));
vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  fetchWithAuth: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  fetchWithTimeout: vi.fn(),
  formatTimestamp: vi.fn((ts) => ts || ""),
  getRootPath: vi.fn(() => ""),
  safeGetElement: vi.fn((id, silent) => document.getElementById(id)),
  showNotification: vi.fn(),
  showToast: vi.fn(),
  truncateText: vi.fn((s, len) => (s != null ? String(s).slice(0, len || 80) : "")),
}));

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
});

// ---------------------------------------------------------------------------
// getLogLevelClass
// ---------------------------------------------------------------------------
describe("getLogLevelClass", () => {
  test("returns correct class for DEBUG", () => {
    const cls = getLogLevelClass("DEBUG");
    expect(cls).toContain("gray");
  });

  test("returns correct class for INFO", () => {
    const cls = getLogLevelClass("INFO");
    expect(cls).toContain("blue");
  });

  test("returns correct class for WARNING", () => {
    const cls = getLogLevelClass("WARNING");
    expect(cls).toContain("yellow");
  });

  test("returns correct class for ERROR", () => {
    const cls = getLogLevelClass("ERROR");
    expect(cls).toContain("red");
  });

  test("returns correct class for CRITICAL", () => {
    const cls = getLogLevelClass("CRITICAL");
    expect(cls).toContain("purple");
  });

  test("returns INFO class for unknown levels", () => {
    const cls = getLogLevelClass("UNKNOWN");
    expect(cls).toContain("blue");
  });
});

// ---------------------------------------------------------------------------
// getSeverityClass
// ---------------------------------------------------------------------------
describe("getSeverityClass", () => {
  test("returns correct class for LOW", () => {
    expect(getSeverityClass("LOW")).toContain("blue");
  });

  test("returns correct class for MEDIUM", () => {
    expect(getSeverityClass("MEDIUM")).toContain("yellow");
  });

  test("returns correct class for HIGH", () => {
    expect(getSeverityClass("HIGH")).toContain("orange");
  });

  test("returns correct class for CRITICAL", () => {
    expect(getSeverityClass("CRITICAL")).toContain("red");
  });

  test("returns MEDIUM class for unknown severity", () => {
    expect(getSeverityClass("UNKNOWN")).toContain("yellow");
  });
});

// ---------------------------------------------------------------------------
// searchStructuredLogs
// ---------------------------------------------------------------------------
describe("searchStructuredLogs", () => {
  test("fetches logs and calls displayLogResults", async () => {
    // eslint-disable-next-line no-unused-vars
    const { tbody } = addLogDOM();

    const pageInfo = document.createElement("span");
    pageInfo.id = "log-page-info";
    document.body.appendChild(pageInfo);

    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ logs: [], total: 0 }),
    });

    await searchStructuredLogs();
    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("/api/logs/search"),
      expect.any(Object)
    );
  });

  test("handles fetch errors gracefully", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    // eslint-disable-next-line no-unused-vars
    const { tbody } = addLogDOM();

    fetchWithAuth.mockRejectedValue(new Error("Network error"));

    await searchStructuredLogs();
    expect(errorSpy).toHaveBeenCalled();
    errorSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// restoreLogTableHeaders
// ---------------------------------------------------------------------------
describe("restoreLogTableHeaders", () => {
  test("restores default table headers", () => {
    const thead = document.createElement("thead");
    thead.id = "logs-thead";
    thead.innerHTML = "<tr><th>Custom</th></tr>";
    document.body.appendChild(thead);

    restoreLogTableHeaders();
    expect(thead.innerHTML).toContain("Time");
    expect(thead.innerHTML).toContain("Level");
    expect(thead.innerHTML).toContain("Component");
  });

  test("does nothing when thead is missing", () => {
    expect(() => restoreLogTableHeaders()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// showCorrelationTrace
// ---------------------------------------------------------------------------
describe("showCorrelationTrace", () => {
  test("fetches correlation trace data", async () => {
    addLogDOM();

    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        correlation_id: "corr-123",
        logs: [],
        security_events: [],
        audit_trails: [],
        total_duration_ms: 0,
      }),
    });

    await showCorrelationTrace("corr-123");
    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("corr-123"),
      expect.any(Object)
    );
  });
});

// ---------------------------------------------------------------------------
// Helper: create common log DOM elements
// ---------------------------------------------------------------------------
function addLogDOM() {
  const thead = document.createElement("thead");
  thead.id = "logs-thead";
  document.body.appendChild(thead);

  const tbody = document.createElement("tbody");
  tbody.id = "logs-tbody";
  document.body.appendChild(tbody);

  const logCount = document.createElement("span");
  logCount.id = "log-count";
  document.body.appendChild(logCount);

  const logStats = document.createElement("div");
  logStats.id = "log-stats";
  document.body.appendChild(logStats);

  return { thead, tbody, logCount, logStats };
}

// ---------------------------------------------------------------------------
// displayCorrelationTrace
// ---------------------------------------------------------------------------
describe("displayCorrelationTrace", () => {
  test("renders trace entries to tbody", () => {
    const { tbody } = addLogDOM();

    displayCorrelationTrace({
      correlation_id: "corr-123",
      logs: [
        {
          timestamp: "2024-01-01T00:00:00Z",
          level: "INFO",
          component: "gateway",
          message: "forwarding request",
          correlation_id: "corr-123",
        },
      ],
      security_events: [],
      audit_trails: [],
      total_duration_ms: 50,
    });

    expect(tbody.innerHTML).toContain("gateway");
  });

  test("shows empty message when no events", () => {
    const { tbody } = addLogDOM();

    displayCorrelationTrace({
      correlation_id: "c1",
      logs: [],
      security_events: [],
      audit_trails: [],
      total_duration_ms: 0,
    });
    expect(tbody.innerHTML).toContain("No events");
  });
});

// ---------------------------------------------------------------------------
// showSecurityEvents
// ---------------------------------------------------------------------------
describe("showSecurityEvents", () => {
  test("fetches and displays security events", async () => {
    addLogDOM();

    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ events: [] }),
    });

    await showSecurityEvents();
    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("security"),
      expect.any(Object)
    );
  });
});

// ---------------------------------------------------------------------------
// displaySecurityEvents
// ---------------------------------------------------------------------------
describe("displaySecurityEvents", () => {
  test("renders security events to tbody", () => {
    const { tbody } = addLogDOM();

    displaySecurityEvents([
      {
        timestamp: "2024-01-01T00:00:00Z",
        event_type: "auth_failure",
        severity: "HIGH",
        threat_score: 0.85,
        user_email: "admin@test.com",
        description: "Failed login",
      },
    ]);

    expect(tbody.innerHTML).toContain("auth_failure");
    expect(tbody.innerHTML).toContain("admin@test.com");
  });

  test("shows empty message when no events", () => {
    const { tbody } = addLogDOM();

    displaySecurityEvents([]);
    expect(tbody.innerHTML).toContain("No unresolved security events");
  });
});

// ---------------------------------------------------------------------------
// showAuditTrail
// ---------------------------------------------------------------------------
describe("showAuditTrail", () => {
  test("fetches and displays audit trail", async () => {
    addLogDOM();

    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ trails: [] }),
    });

    await showAuditTrail();
    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("audit"),
      expect.any(Object)
    );
  });
});

// ---------------------------------------------------------------------------
// displayAuditTrail
// ---------------------------------------------------------------------------
describe("displayAuditTrail", () => {
  test("renders audit entries to tbody", () => {
    const { tbody } = addLogDOM();

    displayAuditTrail([
      {
        timestamp: "2024-01-01T00:00:00Z",
        action: "create",
        resource_type: "tool",
        resource_id: "tool-1",
        user_email: "admin@test.com",
        success: true,
        requires_review: false,
      },
    ]);

    expect(tbody.innerHTML).toContain("CREATE");
    expect(tbody.innerHTML).toContain("tool");
  });

  test("shows empty message for no audit trails", () => {
    const { tbody } = addLogDOM();

    displayAuditTrail([]);
    expect(tbody.innerHTML).toContain("No audit");
  });
});

// ---------------------------------------------------------------------------
// setPerformanceAggregationVisibility / setLogFiltersVisibility
// ---------------------------------------------------------------------------
describe("setPerformanceAggregationVisibility", () => {
  test("shows performance aggregation controls", () => {
    const el = document.createElement("div");
    el.id = "performance-aggregation-controls";
    el.classList.add("hidden");
    document.body.appendChild(el);

    setPerformanceAggregationVisibility(true);
    expect(el.classList.contains("hidden")).toBe(false);
  });

  test("hides performance aggregation controls", () => {
    const el = document.createElement("div");
    el.id = "performance-aggregation-controls";
    document.body.appendChild(el);

    setPerformanceAggregationVisibility(false);
    expect(el.classList.contains("hidden")).toBe(true);
  });
});

describe("setLogFiltersVisibility", () => {
  test("shows log filter controls", () => {
    const el = document.createElement("div");
    el.id = "log-filters";
    el.classList.add("hidden");
    document.body.appendChild(el);

    setLogFiltersVisibility(true);
    expect(el.classList.contains("hidden")).toBe(false);
  });

  test("hides log filter controls", () => {
    const el = document.createElement("div");
    el.id = "log-filters";
    document.body.appendChild(el);

    setLogFiltersVisibility(false);
    expect(el.classList.contains("hidden")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// getPerformanceAggregationConfig/Label/Query
// ---------------------------------------------------------------------------
describe("getPerformanceAggregationConfig", () => {
  test("returns config for valid range key", async () => {
    const { getPerformanceAggregationConfig } = await import("../../../mcpgateway/admin_ui/logging.js");
    const config = getPerformanceAggregationConfig("5m");
    expect(config).toBeDefined();
    expect(config.label).toBeDefined();
    expect(config.query).toBeDefined();
  });

  test("returns default config for invalid range key", async () => {
    const { getPerformanceAggregationConfig } = await import("../../../mcpgateway/admin_ui/logging.js");
    const config = getPerformanceAggregationConfig("invalid");
    expect(config).toBeDefined();
  });
});

describe("getPerformanceAggregationLabel", () => {
  test("returns label for valid range key", async () => {
    const { getPerformanceAggregationLabel } = await import("../../../mcpgateway/admin_ui/logging.js");
    const label = getPerformanceAggregationLabel("5m");
    expect(typeof label).toBe("string");
    expect(label.length).toBeGreaterThan(0);
  });
});

describe("getPerformanceAggregationQuery", () => {
  test("returns query for valid range key", async () => {
    const { getPerformanceAggregationQuery } = await import("../../../mcpgateway/admin_ui/logging.js");
    const query = getPerformanceAggregationQuery("5m");
    expect(typeof query).toBe("string");
    expect(query.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// syncPerformanceAggregationSelect
// ---------------------------------------------------------------------------
describe("syncPerformanceAggregationSelect", () => {
  test("syncs select element value", async () => {
    const { syncPerformanceAggregationSelect } = await import("../../../mcpgateway/admin_ui/logging.js");
    const select = document.createElement("select");
    select.id = "performance-aggregation-select";
    const option = document.createElement("option");
    option.value = "5m";
    select.appendChild(option);
    document.body.appendChild(select);

    syncPerformanceAggregationSelect();
    expect(select.value).toBe("5m");
  });

  test("handles missing select element", async () => {
    const { syncPerformanceAggregationSelect } = await import("../../../mcpgateway/admin_ui/logging.js");
    expect(() => syncPerformanceAggregationSelect()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// handlePerformanceAggregationChange
// ---------------------------------------------------------------------------
describe("handlePerformanceAggregationChange", () => {
  test("calls showPerformanceMetrics with selected key", async () => {
    const { handlePerformanceAggregationChange } = await import("../../../mcpgateway/admin_ui/logging.js");

    addLogDOM();
    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    });

    const event = { target: { value: "5m" } };
    await handlePerformanceAggregationChange(event);

    expect(fetchWithAuth).toHaveBeenCalled();
  });

  test("handles invalid selection gracefully", async () => {
    const { handlePerformanceAggregationChange } = await import("../../../mcpgateway/admin_ui/logging.js");
    const event = { target: { value: "invalid" } };
    expect(() => handlePerformanceAggregationChange(event)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// displayLogResults
// ---------------------------------------------------------------------------
describe("displayLogResults", () => {
  test("displays log results in table", async () => {
    const { displayLogResults } = await import("../../../mcpgateway/admin_ui/logging.js");
    const { tbody } = addLogDOM();

    const prevBtn = document.createElement("button");
    prevBtn.id = "prev-page";
    document.body.appendChild(prevBtn);

    const nextBtn = document.createElement("button");
    nextBtn.id = "next-page";
    document.body.appendChild(nextBtn);

    displayLogResults({
      results: [
        {
          id: "log-1",
          timestamp: "2024-01-01T00:00:00Z",
          level: "INFO",
          component: "gateway",
          message: "Test message",
          correlation_id: "corr-123",
        },
      ],
      total: 1,
    });

    expect(tbody.innerHTML).toContain("Test message");
    expect(tbody.innerHTML).toContain("gateway");
  });

  test("shows empty message when no results", async () => {
    const { displayLogResults } = await import("../../../mcpgateway/admin_ui/logging.js");
    const { tbody } = addLogDOM();

    displayLogResults({ results: [], total: 0 });
    expect(tbody.innerHTML).toContain("No logs found");
  });

  test("handles pagination correctly", async () => {
    const { displayLogResults } = await import("../../../mcpgateway/admin_ui/logging.js");
    addLogDOM();

    const prevBtn = document.createElement("button");
    prevBtn.id = "prev-page";
    document.body.appendChild(prevBtn);

    const nextBtn = document.createElement("button");
    nextBtn.id = "next-page";
    document.body.appendChild(nextBtn);

    displayLogResults({
      results: Array(50).fill({
        id: "log-1",
        timestamp: "2024-01-01T00:00:00Z",
        level: "INFO",
        component: "test",
        message: "msg",
      }),
      total: 100,
    });

    expect(nextBtn.disabled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// showLogDetails
// ---------------------------------------------------------------------------
describe("showLogDetails", () => {
  test("calls showCorrelationTrace when correlation ID exists", async () => {
    const { showLogDetails } = await import("../../../mcpgateway/admin_ui/logging.js");
    addLogDOM();

    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        correlation_id: "corr-123",
        logs: [],
        security_events: [],
        audit_trails: [],
      }),
    });

    await showLogDetails("log-1", "corr-123");
    expect(fetchWithAuth).toHaveBeenCalled();
  });

  test("logs message when no correlation ID", async () => {
    const { showLogDetails } = await import("../../../mcpgateway/admin_ui/logging.js");
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    showLogDetails("log-1", null);
    expect(logSpy).toHaveBeenCalledWith("Log details:", "log-1");
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// generateStatusBadgeHtml
// ---------------------------------------------------------------------------
describe("generateStatusBadgeHtml", () => {
  test("generates inactive badge when disabled", async () => {
    const { generateStatusBadgeHtml } = await import("../../../mcpgateway/admin_ui/logging.js");
    const html = generateStatusBadgeHtml(false, true, "gateway");
    expect(html).toContain("Inactive");
    expect(html).toContain("red");
  });

  test("generates offline badge when unreachable", async () => {
    const { generateStatusBadgeHtml } = await import("../../../mcpgateway/admin_ui/logging.js");
    const html = generateStatusBadgeHtml(true, false, "gateway");
    expect(html).toContain("Offline");
    expect(html).toContain("yellow");
  });

  test("generates active badge when enabled and reachable", async () => {
    const { generateStatusBadgeHtml } = await import("../../../mcpgateway/admin_ui/logging.js");
    const html = generateStatusBadgeHtml(true, true, "gateway");
    expect(html).toContain("Active");
    expect(html).toContain("green");
  });
});

// ---------------------------------------------------------------------------
// updateEntityActionButtons
// ---------------------------------------------------------------------------
describe("updateEntityActionButtons", () => {
  test("updates button to Deactivate when enabled", async () => {
    const { updateEntityActionButtons } = await import("../../../mcpgateway/admin_ui/logging.js");
    const cell = document.createElement("td");
    const form = document.createElement("form");
    form.action = "/state";
    cell.appendChild(form);

    updateEntityActionButtons(cell, "gateway", "gw-1", true);
    expect(form.innerHTML).toContain("Deactivate");
    expect(form.innerHTML).toContain('value="false"');
  });

  test("updates button to Activate when disabled", async () => {
    const { updateEntityActionButtons } = await import("../../../mcpgateway/admin_ui/logging.js");
    const cell = document.createElement("td");
    const form = document.createElement("form");
    form.action = "/state";
    cell.appendChild(form);

    updateEntityActionButtons(cell, "gateway", "gw-1", false);
    expect(form.innerHTML).toContain("Activate");
    expect(form.innerHTML).toContain('value="true"');
  });

  test("handles missing form gracefully", async () => {
    const { updateEntityActionButtons } = await import("../../../mcpgateway/admin_ui/logging.js");
    const cell = document.createElement("td");
    expect(() => updateEntityActionButtons(cell, "gateway", "gw-1", true)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// showPerformanceMetrics
// ---------------------------------------------------------------------------
describe("showPerformanceMetrics", () => {
  test("fetches and displays performance metrics", async () => {
    const { showPerformanceMetrics } = await import("../../../mcpgateway/admin_ui/logging.js");
    addLogDOM();

    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([
        {
          window_start: "2024-01-01T00:00:00Z",
          component: "gateway",
          operation_type: "tool_call",
          avg_duration_ms: 50,
          p95_duration_ms: 100,
          p99_duration_ms: 150,
          request_count: 100,
          error_rate: 0.05,
        },
      ]),
    });

    await showPerformanceMetrics("5m");
    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("performance-metrics"),
      expect.any(Object)
    );
  });

  test("handles fetch errors", async () => {
    const { showPerformanceMetrics } = await import("../../../mcpgateway/admin_ui/logging.js");
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    addLogDOM();

    fetchWithAuth.mockRejectedValue(new Error("Network error"));
    await showPerformanceMetrics("5m");

    expect(errorSpy).toHaveBeenCalled();
    errorSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// displayPerformanceMetrics
// ---------------------------------------------------------------------------
describe("displayPerformanceMetrics", () => {
  test("displays performance metrics in table", async () => {
    const { displayPerformanceMetrics } = await import("../../../mcpgateway/admin_ui/logging.js");
    const { tbody } = addLogDOM();

    displayPerformanceMetrics([
      {
        window_start: "2024-01-01T00:00:00Z",
        component: "gateway",
        operation_type: "tool_call",
        avg_duration_ms: 50,
        p95_duration_ms: 100,
        p99_duration_ms: 150,
        request_count: 100,
        error_rate: 0.05,
      },
    ]);

    expect(tbody.innerHTML).toContain("gateway");
    expect(tbody.innerHTML).toContain("tool_call");
    expect(tbody.innerHTML).toContain("50.00ms");
  });

  test("shows empty message when no metrics", async () => {
    const { displayPerformanceMetrics } = await import("../../../mcpgateway/admin_ui/logging.js");
    const { tbody } = addLogDOM();

    displayPerformanceMetrics([]);
    expect(tbody.innerHTML).toContain("No performance metrics");
  });

  test("highlights high error rates", async () => {
    const { displayPerformanceMetrics } = await import("../../../mcpgateway/admin_ui/logging.js");
    const { tbody } = addLogDOM();

    displayPerformanceMetrics([
      {
        window_start: "2024-01-01T00:00:00Z",
        component: "gateway",
        operation_type: "tool_call",
        avg_duration_ms: 50,
        p95_duration_ms: 100,
        p99_duration_ms: 150,
        request_count: 100,
        error_rate: 0.15,
      },
    ]);

    expect(tbody.innerHTML).toContain("text-red-600");
    expect(tbody.innerHTML).toContain("⚠️");
  });
});

// ---------------------------------------------------------------------------
// previousLogPage / nextLogPage
// ---------------------------------------------------------------------------
describe("previousLogPage", () => {
  test("decrements page and searches logs", async () => {
    const { previousLogPage } = await import("../../../mcpgateway/admin_ui/logging.js");
    addLogDOM();

    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ results: [], total: 0 }),
    });

    // Simulate being on page 1
    await previousLogPage();
    expect(fetchWithAuth).toHaveBeenCalled();
  });
});

describe("nextLogPage", () => {
  test("increments page and searches logs", async () => {
    const { nextLogPage } = await import("../../../mcpgateway/admin_ui/logging.js");
    addLogDOM();

    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ results: [], total: 0 }),
    });

    await nextLogPage();
    expect(fetchWithAuth).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Emergency MCP Search Functions
// ---------------------------------------------------------------------------
describe("emergencyFixMCPSearch", () => {
  test("fixes search input event listeners", async () => {
    const { emergencyFixMCPSearch } = await import("../../../mcpgateway/admin_ui/logging.js");
    const input = document.createElement("input");
    input.id = "gateways-search-input";
    document.body.appendChild(input);

    const result = emergencyFixMCPSearch();
    expect(result).toBe(true);
  });

  test("returns false when input not found", async () => {
    const { emergencyFixMCPSearch } = await import("../../../mcpgateway/admin_ui/logging.js");
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const result = emergencyFixMCPSearch();
    expect(result).toBe(false);
    errorSpy.mockRestore();
  });
});

describe("debugMCPSearchState", () => {
  test("returns debug state object", async () => {
    const { debugMCPSearchState } = await import("../../../mcpgateway/admin_ui/logging.js");
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const state = debugMCPSearchState();
    expect(state).toHaveProperty("searchInput");
    expect(state).toHaveProperty("panel");
    expect(state).toHaveProperty("table");
    expect(state).toHaveProperty("rowCount");
    logSpy.mockRestore();
  });
});
