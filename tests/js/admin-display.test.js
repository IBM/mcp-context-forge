/**
 * Unit tests for display/UI utility functions.
 * Tests pure functions - no DOM required.
 */

import { describe, test, expect } from "vitest";
import {
  getLogLevelClass,
  getSeverityClass,
  generateStatusBadgeHtml,
} from "../../mcpgateway/admin_ui/logging.js";
import { calculateSuccessRate } from "../../mcpgateway/admin_ui/metrics.js";
import { isAdminOnlyTab } from "../../mcpgateway/admin_ui/tabs.js";

// ---------------------------------------------------------------------------
// getLogLevelClass
// ---------------------------------------------------------------------------
describe("getLogLevelClass", () => {
  test("returns correct class for DEBUG", () => {
    expect(getLogLevelClass("DEBUG")).toContain("bg-gray");
  });

  test("returns correct class for INFO", () => {
    expect(getLogLevelClass("INFO")).toContain("bg-blue");
  });

  test("returns correct class for WARNING", () => {
    expect(getLogLevelClass("WARNING")).toContain("bg-yellow");
  });

  test("returns correct class for ERROR", () => {
    expect(getLogLevelClass("ERROR")).toContain("bg-red");
  });

  test("returns correct class for CRITICAL", () => {
    expect(getLogLevelClass("CRITICAL")).toContain("bg-purple");
  });

  test("returns INFO class as default for unknown level", () => {
    expect(getLogLevelClass("UNKNOWN")).toContain("bg-blue");
  });

  test("returns INFO class for undefined level", () => {
    expect(getLogLevelClass(undefined)).toContain("bg-blue");
  });
});

// ---------------------------------------------------------------------------
// getSeverityClass
// ---------------------------------------------------------------------------
describe("getSeverityClass", () => {
  test("returns correct class for LOW", () => {
    expect(getSeverityClass("LOW")).toContain("bg-blue");
  });

  test("returns correct class for MEDIUM", () => {
    expect(getSeverityClass("MEDIUM")).toContain("bg-yellow");
  });

  test("returns correct class for HIGH", () => {
    expect(getSeverityClass("HIGH")).toContain("bg-orange");
  });

  test("returns correct class for CRITICAL", () => {
    expect(getSeverityClass("CRITICAL")).toContain("bg-red");
  });

  test("returns MEDIUM class as default for unknown severity", () => {
    expect(getSeverityClass("UNKNOWN")).toContain("bg-yellow");
  });
});

// ---------------------------------------------------------------------------
// generateStatusBadgeHtml
// ---------------------------------------------------------------------------
describe("generateStatusBadgeHtml", () => {
  test("returns Inactive badge when not enabled", () => {
    const html = generateStatusBadgeHtml(false, true, "server");
    expect(html).toContain("Inactive");
    expect(html).toContain("bg-red");
    expect(html).toContain("Server is Manually Deactivated");
  });

  test("returns Offline badge when enabled but not reachable", () => {
    const html = generateStatusBadgeHtml(true, false, "gateway");
    expect(html).toContain("Offline");
    expect(html).toContain("bg-yellow");
    expect(html).toContain("Gateway is Not Reachable");
  });

  test("returns Active badge when enabled and reachable", () => {
    const html = generateStatusBadgeHtml(true, true, "tool");
    expect(html).toContain("Active");
    expect(html).toContain("bg-green");
    expect(html).toContain("Tool is Active");
  });

  test("capitalizes typeLabel", () => {
    const html = generateStatusBadgeHtml(true, true, "resource");
    expect(html).toContain("Resource is Active");
  });

  test("uses 'Item' as default when no typeLabel", () => {
    const html = generateStatusBadgeHtml(false, false, null);
    expect(html).toContain("Item is Manually Deactivated");
  });

  test("uses 'Item' for undefined typeLabel", () => {
    const html = generateStatusBadgeHtml(false, false, undefined);
    expect(html).toContain("Item is Manually Deactivated");
  });

  test("Inactive takes priority over Offline (disabled + unreachable)", () => {
    const html = generateStatusBadgeHtml(false, false, "server");
    expect(html).toContain("Inactive");
    expect(html).not.toContain("Offline");
  });
});

// ---------------------------------------------------------------------------
// calculateSuccessRate
// ---------------------------------------------------------------------------
describe("calculateSuccessRate", () => {
  test("returns successRate directly when available", () => {
    expect(calculateSuccessRate({ successRate: 95.7 })).toBe(96);
  });

  test("rounds successRate to nearest integer", () => {
    expect(calculateSuccessRate({ successRate: 99.4 })).toBe(99);
  });

  test("returns 0 for successRate = 0", () => {
    expect(calculateSuccessRate({ successRate: 0 })).toBe(0);
  });

  test("computes from execution_count and successful_count (legacy)", () => {
    expect(
      calculateSuccessRate({ execution_count: 100, successful_count: 85 })
    ).toBe(85);
  });

  test("computes from executions and successfulExecutions", () => {
    expect(
      calculateSuccessRate({ executions: 200, successfulExecutions: 150 })
    ).toBe(75);
  });

  test("returns 0 when total is 0", () => {
    expect(
      calculateSuccessRate({ execution_count: 0, successful_count: 0 })
    ).toBe(0);
  });

  test("returns 0 for empty object", () => {
    expect(calculateSuccessRate({})).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// isAdminOnlyTab
// ---------------------------------------------------------------------------
describe("isAdminOnlyTab", () => {
  test("returns true for users tab", () => {
    expect(isAdminOnlyTab("users")).toBe(true);
  });

  test("returns true for metrics tab", () => {
    expect(isAdminOnlyTab("metrics")).toBe(true);
  });

  test("returns true for performance tab", () => {
    expect(isAdminOnlyTab("performance")).toBe(true);
  });

  test("returns true for observability tab", () => {
    expect(isAdminOnlyTab("observability")).toBe(true);
  });

  test("returns true for plugins tab", () => {
    expect(isAdminOnlyTab("plugins")).toBe(true);
  });

  test("returns true for logs tab", () => {
    expect(isAdminOnlyTab("logs")).toBe(true);
  });

  test("returns true for export-import tab", () => {
    expect(isAdminOnlyTab("export-import")).toBe(true);
  });

  test("returns true for version-info tab", () => {
    expect(isAdminOnlyTab("version-info")).toBe(true);
  });

  test("returns true for maintenance tab", () => {
    expect(isAdminOnlyTab("maintenance")).toBe(true);
  });

  test("returns false for gateways tab", () => {
    expect(isAdminOnlyTab("gateways")).toBe(false);
  });

  test("returns false for tools tab", () => {
    expect(isAdminOnlyTab("tools")).toBe(false);
  });

  test("returns false for overview tab", () => {
    expect(isAdminOnlyTab("overview")).toBe(false);
  });

  test("returns false for undefined", () => {
    expect(isAdminOnlyTab(undefined)).toBe(false);
  });
});
