/**
 * Unit tests for HTML generation functions from metrics.js.
 *
 * These functions return DOM elements. We test for key content
 * presence using textContent/toContain rather than exact HTML matching.
 */

import { describe, test, expect, beforeEach } from "vitest";
import {
  createSystemSummaryCard,
  createKPISection,
  createPerformanceCard,
  createRecentActivitySection,
  createMetricsCard,
} from "../../mcpgateway/admin_ui/metrics.js";

beforeEach(() => {
  document.body.textContent = "";
});

// ---------------------------------------------------------------------------
// createSystemSummaryCard
// ---------------------------------------------------------------------------
describe("createSystemSummaryCard", () => {
  test("returns element with system stats from camelCase keys", () => {
    const card = createSystemSummaryCard({
      uptime: "5d 3h",
      totalRequests: 12345,
      activeConnections: 42,
      memoryUsage: 65,
      cpuUsage: 30,
      diskUsage: 45,
      networkIn: 100,
      networkOut: 200,
    });
    const text = card.textContent;
    expect(text).toContain("System Overview");
    expect(text).toContain("5d 3h");
    expect(text).toContain("12345");
    expect(text).toContain("42");
    expect(text).toContain("65%");
    expect(text).toContain("30%");
  });

  test("resolves snake_case keys via fallback", () => {
    const card = createSystemSummaryCard({
      total_requests: 999,
      active_connections: 10,
      memory_usage: 50,
      cpu_usage: 20,
      disk_usage: 30,
      network_in: 5,
      network_out: 8,
    });
    const text = card.textContent;
    expect(text).toContain("999");
    expect(text).toContain("10");
  });

  test("shows N/A for missing fields", () => {
    const card = createSystemSummaryCard({});
    const text = card.textContent;
    expect(text).toContain("N/A");
  });

  test("contains all 8 stat labels", () => {
    const card = createSystemSummaryCard({});
    const text = card.textContent;
    expect(text).toContain("Uptime");
    expect(text).toContain("Total Requests");
    expect(text).toContain("Active Connections");
    expect(text).toContain("Memory Usage");
    expect(text).toContain("CPU Usage");
    expect(text).toContain("Disk Usage");
    expect(text).toContain("Network In");
    expect(text).toContain("Network Out");
  });

  test("returns safe fallback on error", () => {
    // null input triggers error path
    const card = createSystemSummaryCard(null);
    expect(card).toBeDefined();
    expect(card.tagName).toBe("DIV");
  });
});

// ---------------------------------------------------------------------------
// createKPISection
// ---------------------------------------------------------------------------
describe("createKPISection", () => {
  test("returns element with 4 KPI cards", () => {
    const section = createKPISection({
      totalExecutions: 5000,
      successRate: 99.5,
      avgResponseTime: 1.23456,
      errorRate: 0.5,
    });
    const text = section.textContent;
    expect(text).toContain("Total Executions");
    expect(text).toContain("5000");
    expect(text).toContain("Success Rate");
    expect(text).toContain("99.5%");
    expect(text).toContain("Avg Response Time");
    expect(text).toContain("1.235 ms"); // 3 decimal places
    expect(text).toContain("Error Rate");
    expect(text).toContain("0.5%");
  });

  test("shows N/A for null values", () => {
    const section = createKPISection({
      totalExecutions: null,
      successRate: null,
      avgResponseTime: null,
      errorRate: null,
    });
    const text = section.textContent;
    // Each N/A value should appear
    expect((text.match(/N\/A/g) || []).length).toBeGreaterThanOrEqual(4);
  });

  test("shows N/A for undefined values", () => {
    const section = createKPISection({});
    const text = section.textContent;
    expect(text).toContain("N/A");
  });

  test("handles non-numeric avgResponseTime", () => {
    const section = createKPISection({
      avgResponseTime: "not-a-number",
    });
    expect(section.textContent).toContain("N/A");
  });

  test("returns safe fallback on error", () => {
    const section = createKPISection(null);
    expect(section).toBeDefined();
    expect(section.tagName).toBe("DIV");
  });
});

// ---------------------------------------------------------------------------
// createPerformanceCard
// ---------------------------------------------------------------------------
describe("createPerformanceCard", () => {
  test("returns card with 6 performance metrics", () => {
    const card = createPerformanceCard({
      memoryUsage: "512 MB",
      cpuUsage: "25%",
      diskIo: "10 MB/s",
      networkThroughput: "100 Mbps",
      cacheHitRate: "95%",
      activeThreads: 8,
    });
    const text = card.textContent;
    expect(text).toContain("Performance Metrics");
    expect(text).toContain("Memory Usage");
    expect(text).toContain("512 MB");
    expect(text).toContain("CPU Usage");
    expect(text).toContain("25%");
    expect(text).toContain("Disk I/O");
    expect(text).toContain("10 MB/s");
    expect(text).toContain("Network Throughput");
    expect(text).toContain("Cache Hit Rate");
    expect(text).toContain("Active Threads");
  });

  test("resolves snake_case keys via fallback", () => {
    const card = createPerformanceCard({
      memory_usage: "256 MB",
      cpu_usage: "10%",
      disk_io: "5 MB/s",
      network_throughput: "50 Mbps",
      cache_hit_rate: "80%",
      active_threads: 4,
    });
    const text = card.textContent;
    expect(text).toContain("256 MB");
    expect(text).toContain("10%");
  });

  test("shows N/A for missing fields", () => {
    const card = createPerformanceCard({});
    const text = card.textContent;
    expect(text).toContain("N/A");
  });

  test("returns safe fallback on error", () => {
    const card = createPerformanceCard(null);
    expect(card).toBeDefined();
    expect(card.tagName).toBe("DIV");
  });
});

// ---------------------------------------------------------------------------
// createRecentActivitySection
// ---------------------------------------------------------------------------
describe("createRecentActivitySection", () => {
  test("displays activity items", () => {
    const section = createRecentActivitySection([
      {
        action: "Created Tool",
        target: "get-weather",
        timestamp: "2025-01-01",
      },
      {
        action: "Deleted Resource",
        target: "old-config",
        timestamp: "2025-01-02",
      },
    ]);
    const text = section.textContent;
    expect(text).toContain("Recent Activity");
    expect(text).toContain("Created Tool");
    expect(text).toContain("get-weather");
    expect(text).toContain("Deleted Resource");
  });

  test("shows 'No recent activity' for empty array", () => {
    const section = createRecentActivitySection([]);
    expect(section.textContent).toContain("No recent activity");
  });

  test("shows 'No recent activity' for null input", () => {
    const section = createRecentActivitySection(null);
    expect(section.textContent).toContain("No recent activity");
  });

  test("limits to 10 items", () => {
    const items = Array.from({ length: 15 }, (_, i) => ({
      action: `Action ${i}`,
      target: `target-${i}`,
      timestamp: "2025-01-01",
    }));
    const section = createRecentActivitySection(items);
    // Should only show 10 items, not 15
    const text = section.textContent;
    expect(text).toContain("Action 0");
    expect(text).toContain("Action 9");
    expect(text).not.toContain("Action 10");
  });

  test("applies escapeHtml to user data", () => {
    const section = createRecentActivitySection([
      {
        action: "<script>alert('xss')</script>",
        target: "t",
        timestamp: "now",
      },
    ]);
    const html = section.innerHTML;
    expect(html).not.toContain("<script>");
  });

  test("handles missing action/target/timestamp gracefully", () => {
    const section = createRecentActivitySection([{}]);
    const text = section.textContent;
    expect(text).toContain("Unknown Action");
  });

  test("returns safe fallback on error", () => {
    // Trigger error by passing something that breaks .slice
    const section = createRecentActivitySection("not-an-array");
    expect(section).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// createMetricsCard
// ---------------------------------------------------------------------------
describe("createMetricsCard", () => {
  test("returns card with title and 6 metrics", () => {
    const card = createMetricsCard("Tool", {
      totalExecutions: 100,
      successfulExecutions: 95,
      failedExecutions: 5,
      failureRate: "5%",
      avgResponseTime: "1.5ms",
      lastExecutionTime: "2025-01-01T00:00:00Z",
    });
    const text = card.textContent;
    expect(text).toContain("Tool Metrics");
    expect(text).toContain("Total Executions");
    expect(text).toContain("100");
    expect(text).toContain("Successful Executions");
    expect(text).toContain("95");
    expect(text).toContain("Failed Executions");
    expect(text).toContain("5");
  });

  test("resolves snake_case keys via fallback", () => {
    const card = createMetricsCard("Resource", {
      total_executions: 50,
      successful_executions: 48,
      failed_executions: 2,
      failure_rate: "4%",
      avg_response_time: "2ms",
      last_execution_time: "2025-01-01",
    });
    const text = card.textContent;
    expect(text).toContain("Resource Metrics");
    expect(text).toContain("50");
    expect(text).toContain("48");
  });

  test("shows N/A for missing fields", () => {
    const card = createMetricsCard("Server", {});
    const text = card.textContent;
    expect(text).toContain("N/A");
  });

  test("contains all 6 metric labels", () => {
    const card = createMetricsCard("X", {});
    const text = card.textContent;
    expect(text).toContain("Total Executions");
    expect(text).toContain("Successful Executions");
    expect(text).toContain("Failed Executions");
    expect(text).toContain("Failure Rate");
    expect(text).toContain("Average Response Time");
    expect(text).toContain("Last Execution Time");
  });
});
