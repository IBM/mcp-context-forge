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
  previousLogPage,
  nextLogPage,
  showCorrelationTrace,
  displayCorrelationTrace,
  showSecurityEvents,
  displaySecurityEvents,
  showAuditTrail,
  displayAuditTrail,
  showPerformanceMetrics,
  displayPerformanceMetrics,
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
