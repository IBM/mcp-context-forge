/**
 * Unit tests for flame-graph.js — FlameGraph class.
 *
 * Imports flame-graph.js directly so v8 coverage can track it.
 */

import { describe, test, expect, beforeAll } from "vitest";

let FlameGraph;

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
    },
    {
      span_id: "child1",
      parent_span_id: "root",
      name: "db.query",
      duration_ms: 60,
      start_time: "2025-01-01T00:00:00.010Z",
      kind: "client",
      status: "ok",
    },
    {
      span_id: "grandchild",
      parent_span_id: "child1",
      name: "SELECT *",
      duration_ms: 30,
      start_time: "2025-01-01T00:00:00.020Z",
      kind: "internal",
      status: "ok",
    },
    {
      span_id: "child2",
      parent_span_id: "root",
      name: "http.call",
      duration_ms: 35,
      start_time: "2025-01-01T00:00:00.070Z",
      kind: "client",
      status: "error",
    },
  ],
  duration_ms: 100,
  start_time: "2025-01-01T00:00:00.000Z",
};

beforeAll(async () => {
  // Create the container element the constructor expects
  const container = document.createElement("div");
  container.id = "flame-container";
  document.body.appendChild(container);

  const mod = await import("../../mcpgateway/static/flame-graph.js");
  FlameGraph = mod.FlameGraph;
});

// ---------------------------------------------------------------------------
// buildSpanTree
// ---------------------------------------------------------------------------
describe("FlameGraph.buildSpanTree", () => {
  test("returns root node with children", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    const tree = fg.spans; // buildSpanTree result stored here
    expect(tree).not.toBeNull();
    expect(tree.span_id).toBe("root");
    expect(tree.children.length).toBe(2);
  });

  test("root has correct child names", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    const childNames = fg.spans.children.map((c) => c.name);
    expect(childNames).toContain("db.query");
    expect(childNames).toContain("http.call");
  });

  test("grandchild is nested under child1", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    const child1 = fg.spans.children.find((c) => c.span_id === "child1");
    expect(child1.children.length).toBe(1);
    expect(child1.children[0].name).toBe("SELECT *");
  });

  test("calculates totalDuration on root", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    expect(fg.spans.totalDuration).toBe(100);
  });

  test("handles empty spans", () => {
    const fg = new FlameGraph("flame-container", {
      spans: [],
      duration_ms: 0,
    });
    expect(fg.spans).toBeNull();
  });

  test("handles single span (no parent)", () => {
    const fg = new FlameGraph("flame-container", {
      spans: [
        {
          span_id: "only",
          parent_span_id: null,
          name: "root",
          duration_ms: 50,
          start_time: "2025-01-01T00:00:00Z",
          kind: "server",
          status: "ok",
        },
      ],
    });
    expect(fg.spans.span_id).toBe("only");
    expect(fg.spans.children).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// calculateDepth
// ---------------------------------------------------------------------------
describe("FlameGraph.calculateDepth", () => {
  test("returns 3 for root > child > grandchild", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    const depth = fg.calculateDepth(fg.rootNode);
    expect(depth).toBe(3);
  });

  test("returns 1 for leaf node", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    const leaf = fg.findNode(fg.rootNode, "grandchild");
    expect(fg.calculateDepth(leaf)).toBe(1);
  });

  test("returns 1 for null node", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    expect(fg.calculateDepth(null)).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// getSpanColor
// ---------------------------------------------------------------------------
describe("FlameGraph.getSpanColor", () => {
  test("returns red for error status", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    expect(fg.getSpanColor({ status: "error", kind: "client" })).toBe(
      "#ef4444"
    );
  });

  test("returns blue for client kind", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    expect(fg.getSpanColor({ status: "ok", kind: "client" })).toBe("#3b82f6");
  });

  test("returns green for server kind", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    expect(fg.getSpanColor({ status: "ok", kind: "server" })).toBe("#10b981");
  });

  test("returns purple for internal kind", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    expect(fg.getSpanColor({ status: "ok", kind: "internal" })).toBe("#8b5cf6");
  });

  test("returns gray for unknown kind", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    expect(fg.getSpanColor({ status: "ok", kind: "unknown" })).toBe("#6b7280");
  });
});

// ---------------------------------------------------------------------------
// findNode
// ---------------------------------------------------------------------------
describe("FlameGraph.findNode", () => {
  test("finds root by span_id", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    const found = fg.findNode(fg.rootNode, "root");
    expect(found).not.toBeNull();
    expect(found.name).toBe("GET /api");
  });

  test("finds nested grandchild", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    const found = fg.findNode(fg.rootNode, "grandchild");
    expect(found).not.toBeNull();
    expect(found.name).toBe("SELECT *");
  });

  test("returns null for non-existent span_id", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    expect(fg.findNode(fg.rootNode, "nonexistent")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// zoomTo / reset
// ---------------------------------------------------------------------------
describe("FlameGraph zoom", () => {
  test("zoomTo changes currentRoot", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    fg.zoomTo("child1");
    expect(fg.currentRoot.span_id).toBe("child1");
  });

  test("reset restores root and clears search", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    fg.searchTerm = "query";
    fg.zoomTo("child1");
    fg.reset();
    expect(fg.currentRoot.span_id).toBe("root");
    expect(fg.searchTerm).toBe("");
  });

  test("zoomTo with invalid id does nothing", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    const before = fg.currentRoot.span_id;
    fg.zoomTo("nonexistent");
    expect(fg.currentRoot.span_id).toBe(before);
  });
});

// ---------------------------------------------------------------------------
// search
// ---------------------------------------------------------------------------
describe("FlameGraph.search", () => {
  test("sets searchTerm", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    fg.search("db");
    expect(fg.searchTerm).toBe("db");
  });
});

// ---------------------------------------------------------------------------
// renderNode
// ---------------------------------------------------------------------------
describe("FlameGraph.renderNode", () => {
  test("returns empty string for null node", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    expect(fg.renderNode(null, 0, 0, 800)).toBe("");
  });

  test("returns SVG content for valid node", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    const svg = fg.renderNode(fg.rootNode, 0, 0, 800);
    expect(svg).toContain("flame-node");
    expect(svg).toContain("GET /api");
  });

  test("includes child nodes in SVG", () => {
    const fg = new FlameGraph("flame-container", sampleTrace);
    const svg = fg.renderNode(fg.rootNode, 0, 0, 800);
    expect(svg).toContain("db.query");
  });
});
