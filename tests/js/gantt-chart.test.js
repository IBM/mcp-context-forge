/**
 * Unit tests for gantt-chart.js — GanttChart class.
 *
 * Imports gantt-chart.js directly so v8 coverage can track it.
 */

import { describe, test, expect, beforeAll } from "vitest";

let GanttChart;

const sampleTrace = {
  spans: [
    {
      span_id: "root",
      parent_span_id: null,
      name: "GET /api",
      duration_ms: 100,
      start_time: "2025-01-01T00:00:00.000Z",
      kind: "server",
      status: "ok",
      attributes: {},
    },
    {
      span_id: "child1",
      parent_span_id: "root",
      name: "db.query",
      duration_ms: 60,
      start_time: "2025-01-01T00:00:00.010Z",
      kind: "client",
      status: "ok",
      attributes: {},
    },
    {
      span_id: "grandchild",
      parent_span_id: "child1",
      name: "SELECT *",
      duration_ms: 30,
      start_time: "2025-01-01T00:00:00.020Z",
      kind: "internal",
      status: "ok",
      attributes: {},
    },
    {
      span_id: "child2",
      parent_span_id: "root",
      name: "http.call",
      duration_ms: 35,
      start_time: "2025-01-01T00:00:00.070Z",
      kind: "client",
      status: "error",
      attributes: {},
    },
  ],
  duration_ms: 100,
  start_time: "2025-01-01T00:00:00.000Z",
};

beforeAll(async () => {
  // Create the container element the constructor expects
  const container = document.createElement("div");
  container.id = "gantt-container";
  document.body.appendChild(container);

  const mod = await import("../../mcpgateway/static/gantt-chart.js");
  GanttChart = mod.GanttChart;
});

// ---------------------------------------------------------------------------
// calculateTimeStep
// ---------------------------------------------------------------------------
describe("GanttChart.calculateTimeStep", () => {
  test("returns 1 for durations < 10ms", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    expect(gc.calculateTimeStep(5)).toBe(1);
  });

  test("returns 5 for durations < 50ms", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    expect(gc.calculateTimeStep(30)).toBe(5);
  });

  test("returns 10 for durations >= 50 and < 100ms", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    expect(gc.calculateTimeStep(75)).toBe(10);
    expect(gc.calculateTimeStep(99)).toBe(10);
  });

  test("returns 50 for durations < 500ms", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    expect(gc.calculateTimeStep(250)).toBe(50);
  });

  test("returns 100 for durations < 1000ms", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    expect(gc.calculateTimeStep(750)).toBe(100);
  });

  test("returns 500 for durations < 5000ms", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    expect(gc.calculateTimeStep(3000)).toBe(500);
  });

  test("returns 1000 for durations >= 5000ms", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    expect(gc.calculateTimeStep(10000)).toBe(1000);
  });
});

// ---------------------------------------------------------------------------
// buildSpanTree
// ---------------------------------------------------------------------------
describe("GanttChart.buildSpanTree", () => {
  test("flattens tree depth-first", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    const names = gc.spans.map((s) => s.name);
    // root first, then child1, then grandchild, then child2
    expect(names[0]).toBe("GET /api");
    expect(names).toContain("db.query");
    expect(names).toContain("SELECT *");
    expect(names).toContain("http.call");
  });

  test("sets depth on child nodes", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    const root = gc.spans.find((s) => s.span_id === "root");
    const child1 = gc.spans.find((s) => s.span_id === "child1");
    const grandchild = gc.spans.find((s) => s.span_id === "grandchild");
    expect(root.depth).toBe(0);
    expect(child1.depth).toBe(1);
    expect(grandchild.depth).toBe(2);
  });

  test("respects collapsed spans", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    // Collapse root — its children should be hidden
    gc.collapsedSpans.add("root");
    const spans = gc.buildSpanTree(sampleTrace.spans);
    const names = spans.map((s) => s.name);
    expect(names).toContain("GET /api");
    expect(names).not.toContain("db.query");
    expect(names).not.toContain("http.call");
  });

  test("handles empty spans", () => {
    const gc = new GanttChart("gantt-container", {
      spans: [],
      duration_ms: 0,
      start_time: "2025-01-01T00:00:00Z",
    });
    expect(gc.spans).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// calculateCriticalPath
// ---------------------------------------------------------------------------
describe("GanttChart.calculateCriticalPath", () => {
  test("returns a Set of span IDs", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    expect(gc.criticalPath).toBeInstanceOf(Set);
    expect(gc.criticalPath.size).toBeGreaterThan(0);
  });

  test("includes root in critical path", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    expect(gc.criticalPath.has("root")).toBe(true);
  });

  test("includes child with longest chain", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    // child1 (60ms) + grandchild (30ms) = 90ms > child2 (35ms)
    expect(gc.criticalPath.has("child1")).toBe(true);
    expect(gc.criticalPath.has("grandchild")).toBe(true);
  });

  test("excludes shorter branch", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    // child2 (35ms) is shorter than child1 chain (90ms)
    expect(gc.criticalPath.has("child2")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// renderTimeScale
// ---------------------------------------------------------------------------
describe("GanttChart.renderTimeScale", () => {
  test("returns time markers as HTML string", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    const html = gc.renderTimeScale(100);
    expect(html).toContain("time-marker");
    expect(html).toContain("0ms");
  });

  test("includes markers at expected intervals for 100ms", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    const html = gc.renderTimeScale(100);
    // step=50 for 100ms (100 is not < 100, falls to < 500 bracket)
    expect(html).toContain("0ms");
    expect(html).toContain("50ms");
    expect(html).toContain("100ms");
  });
});

// ---------------------------------------------------------------------------
// zoom controls
// ---------------------------------------------------------------------------
describe("GanttChart zoom controls", () => {
  test("zoomIn increases zoomLevel", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    const before = gc.zoomLevel;
    gc.zoomIn();
    expect(gc.zoomLevel).toBeGreaterThan(before);
  });

  test("zoomOut decreases zoomLevel", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    const before = gc.zoomLevel;
    gc.zoomOut();
    expect(gc.zoomLevel).toBeLessThan(before);
  });

  test("resetZoom resets to 1", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    gc.zoomIn();
    gc.zoomIn();
    gc.resetZoom();
    expect(gc.zoomLevel).toBe(1);
    expect(gc.panOffset).toBe(0);
  });

  test("zoomIn caps at 10", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    for (let i = 0; i < 50; i++) gc.zoomIn();
    expect(gc.zoomLevel).toBeLessThanOrEqual(10);
  });

  test("zoomOut caps at 0.1", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    for (let i = 0; i < 50; i++) gc.zoomOut();
    expect(gc.zoomLevel).toBeGreaterThanOrEqual(0.1);
  });
});

// ---------------------------------------------------------------------------
// collapse controls
// ---------------------------------------------------------------------------
describe("GanttChart collapse controls", () => {
  test("toggleSpan collapses a span", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    gc.toggleSpan("root");
    expect(gc.collapsedSpans.has("root")).toBe(true);
  });

  test("toggleSpan expands a collapsed span", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    gc.toggleSpan("root");
    gc.toggleSpan("root");
    expect(gc.collapsedSpans.has("root")).toBe(false);
  });

  test("expandAll clears all collapsed spans", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    gc.collapseAll();
    gc.expandAll();
    expect(gc.collapsedSpans.size).toBe(0);
  });

  test("collapseAll hides child spans from flattened list", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    gc.collapseAll();
    // After collapse, only root should remain visible
    const names = gc.spans.map((s) => s.name);
    expect(names).toContain("GET /api");
    expect(names).not.toContain("db.query");
    expect(names).not.toContain("SELECT *");
  });
});

// ---------------------------------------------------------------------------
// renderSpan
// ---------------------------------------------------------------------------
describe("GanttChart.renderSpan", () => {
  test("renders span row HTML", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    const span = gc.spans[0];
    const traceStart = new Date(sampleTrace.start_time);
    const html = gc.renderSpan(span, 100, traceStart);
    expect(html).toContain("span-row");
    expect(html).toContain("GET /api");
  });

  test("marks critical path spans", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    const rootSpan = gc.spans.find((s) => s.span_id === "root");
    const traceStart = new Date(sampleTrace.start_time);
    const html = gc.renderSpan(rootSpan, 100, traceStart);
    expect(html).toContain("critical-path");
  });

  test("shows toggle button for spans with children", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    const rootSpan = gc.spans.find((s) => s.span_id === "root");
    const traceStart = new Date(sampleTrace.start_time);
    const html = gc.renderSpan(rootSpan, 100, traceStart);
    expect(html).toContain("span-toggle");
  });

  test("error span uses red color", () => {
    const gc = new GanttChart("gantt-container", sampleTrace);
    const errSpan = gc.spans.find((s) => s.span_id === "child2");
    const traceStart = new Date(sampleTrace.start_time);
    const html = gc.renderSpan(errSpan, 100, traceStart);
    expect(html).toContain("#ef4444");
  });
});
