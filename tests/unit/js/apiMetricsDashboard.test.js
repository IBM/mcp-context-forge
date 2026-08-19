/**
 * @vitest-environment jsdom
 *
 * Regression tests for the API Metrics dashboard's inline Alpine controller.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const TEMPLATE_PATH = path.resolve(
  __dirname,
  "../../../mcpgateway/templates/api_metrics_dashboard.html",
);

function templateSource() {
  return fs.readFileSync(TEMPLATE_PATH, "utf8");
}

function loadDashboardFactory() {
  const scriptBody = [...templateSource().matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)]
    .map((match) => match[1])
    .join("\n")
    .replace(/\{\{[\s\S]*?\}\}/g, '""');

  // Compiling the real inline script catches syntax regressions in the template.
  // eslint-disable-next-line no-new-func
  new Function(scriptBody)();
  return window.apiMetricsDashboard;
}

function jsonResponse(payload, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(payload),
  };
}

describe("API Metrics dashboard", () => {
  beforeEach(() => {
    window.ROOT_PATH = "/forge";
    delete window.apiMetricsDashboard;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete window.apiMetricsDashboard;
    delete window.ROOT_PATH;
    document.body.innerHTML = "";
  });

  it("compiles the inline controller and formats dashboard values", () => {
    const factory = loadDashboardFactory();
    const dashboard = factory();

    expect(typeof factory).toBe("function");
    expect(dashboard.fmtCount(1250)).toBe("1.3K");
    expect(dashboard.fmtPct(12.34)).toBe("12.3%");
    expect(dashboard.fmtMs(1200)).toBe("1.2s");
    expect(dashboard.methodBadge("get")).toContain("bg-green-100");
  });

  it("consumes the stats and percentile endpoint contracts", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          total_traces: 20,
          success_count: 18,
          error_count: 2,
          avg_duration_ms: 45,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          timestamps: ["2026-08-18T10:00:00Z", "2026-08-18T11:00:00Z"],
          p50: [10, 12],
          p90: [20, 22],
          p95: [30, 34],
          p99: [40, 45],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          endpoints: [
            {
              endpoint: "GET /failed",
              method: "GET",
              url: "/failed",
              total_count: 4,
              error_count: 2,
              error_rate: 50,
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          endpoints: [
            {
              endpoint: "POST /slow",
              method: "POST",
              url: "/slow",
              count: 3,
              avg_duration_ms: 750,
              max_duration_ms: 1200,
            },
          ],
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const dashboard = loadDashboardFactory()();
    await dashboard.loadAll();

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/forge/admin/observability/stats?hours=24",
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/forge/admin/observability/metrics/percentiles?hours=24&interval_minutes=60",
    );
    expect(dashboard.stats.total_traces).toBe(20);
    expect(dashboard.successRate()).toBe(90);
    expect(dashboard.latestPercentile(95)).toBe(34);
    expect(dashboard.latestPercentile(99)).toBe(45);
    expect(dashboard.topErrors).toHaveLength(1);
    expect(dashboard.topSlow).toHaveLength(1);
    expect(dashboard.error).toBeNull();
    expect(dashboard.loading).toBe(false);
  });

  it("shows a useful error when any metrics endpoint fails", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(jsonResponse({}, { ok: false, status: 503 }))
      .mockResolvedValueOnce(jsonResponse({ endpoints: [] }))
      .mockResolvedValueOnce(jsonResponse({ endpoints: [] }));
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "error").mockImplementation(() => {});

    const dashboard = loadDashboardFactory()();
    await dashboard.loadAll();

    expect(dashboard.error).toBe(
      "Failed to load metrics: Percentiles endpoint returned 503",
    );
    expect(dashboard.loading).toBe(false);
  });

  it("keeps Alpine error-rate expressions valid JavaScript", () => {
    const markup = templateSource().replace(/<script[^>]*>[\s\S]*?<\/script>/g, "");
    document.body.innerHTML = markup;

    const errorRows = document.querySelector('template[x-for="ep in topErrors"]');
    const rateText = errorRows.content.querySelector('[x-text*="error_rate"]');
    const textExpression = rateText.getAttribute("x-text");
    const classExpression = rateText.getAttribute(":class");

    // eslint-disable-next-line no-new-func
    expect(new Function("ep", `return ${textExpression};`)({ error_rate: 60 })).toBe(
      "60%",
    );
    // eslint-disable-next-line no-new-func
    expect(new Function("ep", `return ${classExpression};`)({ error_rate: 60 })).toContain(
      "bg-red-100",
    );
  });
});
