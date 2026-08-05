import { describe, expect, it } from "vitest";

import type { MCPServer } from "@/types/server";
import {
  classifyServer,
  computeHeader,
  computeRoster,
  headerTone,
  rowTone,
  sortServers,
  summarySegments,
  type ClassifiedServer,
  type RosterSummary,
} from "./mcpServerRoster";

function makeServer(over: Partial<MCPServer> = {}): MCPServer {
  return {
    id: over.id ?? "s1",
    name: over.name ?? "server-1",
    enabled: over.enabled ?? true,
    visibility: "private",
    url: "https://example.test/mcp",
    transport: "STREAMABLEHTTP",
    reachable: over.reachable ?? true,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    ...over,
  };
}

function makeSummary(over: Partial<RosterSummary> = {}): RosterSummary {
  return {
    total: 0,
    reachable: 0,
    unreachable: 0,
    checking: 0,
    disabled: 0,
    toolCount: 0,
    resourceCount: 0,
    promptCount: 0,
    ...over,
  };
}

describe("classifyServer", () => {
  it("keys on enabled && reachable, never reachable alone", () => {
    expect(classifyServer(makeServer({ enabled: true, reachable: true }))).toBe("reachable");
    // Disabled while up keeps reachable frozen; still classified disabled.
    expect(classifyServer(makeServer({ enabled: false, reachable: true }))).toBe("disabled");
  });

  it("distinguishes unreachable (probed) from checking (never probed)", () => {
    expect(
      classifyServer(
        makeServer({ enabled: true, reachable: false, lastSeen: "2026-01-01T00:00:00Z" }),
      ),
    ).toBe("unreachable");
    expect(
      classifyServer(makeServer({ enabled: true, reachable: false, lastSeen: undefined })),
    ).toBe("checking");
  });
});

describe("computeHeader", () => {
  it("returns null when nothing has settled", () => {
    expect(computeHeader(makeSummary({ total: 2, checking: 2 }))).toBeNull();
    expect(computeHeader(makeSummary())).toBeNull();
  });

  it("is reachable only when every settled server is reachable", () => {
    // Checking servers are excluded from the settled set, so a still-probing
    // server cannot demote an otherwise all-reachable fleet.
    expect(computeHeader(makeSummary({ total: 3, reachable: 2, checking: 1 }))).toBe("reachable");
  });

  it("reports reducedCoverage when some but not all reachable", () => {
    expect(computeHeader(makeSummary({ total: 2, reachable: 1, unreachable: 1 }))).toBe(
      "reducedCoverage",
    );
    expect(computeHeader(makeSummary({ total: 2, reachable: 1, disabled: 1 }))).toBe(
      "reducedCoverage",
    );
  });

  it("reports unreachable, then disabled, when none reachable", () => {
    expect(computeHeader(makeSummary({ total: 2, unreachable: 1, disabled: 1 }))).toBe(
      "unreachable",
    );
    expect(computeHeader(makeSummary({ total: 1, disabled: 1 }))).toBe("disabled");
  });
});

describe("summarySegments", () => {
  it("omits the unreachable segment while anything is reachable", () => {
    const segments = summarySegments(makeSummary({ total: 2, reachable: 1, unreachable: 1 }));
    expect(segments.map((s) => s.kind)).toEqual(["reachable"]);
  });

  it("shows unreachable only when nothing is reachable", () => {
    const segments = summarySegments(makeSummary({ total: 2, unreachable: 1, disabled: 1 }));
    expect(segments.map((s) => s.kind)).toEqual(["unreachable", "disabled"]);
  });

  it("emits segments in fixed order and drops zero counts", () => {
    const segments = summarySegments(
      makeSummary({ total: 4, reachable: 1, disabled: 1, checking: 2 }),
    );
    expect(segments.map((s) => s.kind)).toEqual(["disabled", "reachable", "pending"]);
    expect(segments.every((s) => s.count > 0)).toBe(true);
  });
});

describe("sortServers", () => {
  it("orders problem-first, then last-seen desc, then name", () => {
    const rows: ClassifiedServer[] = [
      { server: makeServer({ id: "r", name: "reachable", reachable: true }), state: "reachable" },
      {
        server: makeServer({
          id: "u1",
          name: "beta",
          reachable: false,
          lastSeen: "2026-01-01T00:00:00Z",
        }),
        state: "unreachable",
      },
      {
        server: makeServer({
          id: "u2",
          name: "alpha",
          reachable: false,
          lastSeen: "2026-02-01T00:00:00Z",
        }),
        state: "unreachable",
      },
      { server: makeServer({ id: "d", name: "disabled", enabled: false }), state: "disabled" },
      {
        server: makeServer({ id: "c", name: "checking", reachable: false }),
        state: "checking",
      },
    ];

    expect(sortServers(rows).map((r) => r.server.id)).toEqual(["u2", "u1", "d", "r", "c"]);
  });
});

describe("computeRoster", () => {
  it("tallies counts, sums components, and derives header/segments/rows", () => {
    const roster = computeRoster([
      makeServer({ id: "a", name: "alpha", reachable: true, toolCount: 3, resourceCount: 1 }),
      makeServer({
        id: "b",
        name: "bravo",
        reachable: false,
        lastSeen: "2026-01-01T00:00:00Z",
        promptCount: 2,
      }),
      makeServer({ id: "c", name: "charlie", enabled: false }),
    ]);

    expect(roster.summary).toMatchObject({
      total: 3,
      reachable: 1,
      unreachable: 1,
      disabled: 1,
      toolCount: 3,
      resourceCount: 1,
      promptCount: 2,
    });
    expect(roster.header).toBe("reducedCoverage");
    expect(roster.segments.map((s) => s.kind)).toEqual(["disabled", "reachable"]);
    // Problem-first: unreachable bravo before disabled charlie before reachable alpha.
    expect(roster.rows.map((r) => r.server.id)).toEqual(["b", "c", "a"]);
  });

  it("has no header for an empty fleet", () => {
    const roster = computeRoster([]);
    expect(roster.header).toBeNull();
    expect(roster.rows).toEqual([]);
  });
});

describe("tones", () => {
  it("greens only all-reachable header and reachable rows", () => {
    expect(headerTone("reachable")).toBe("success");
    expect(headerTone("reducedCoverage")).toBe("muted");
    expect(headerTone("unreachable")).toBe("muted");
    expect(headerTone("disabled")).toBe("muted");

    expect(rowTone("reachable")).toBe("success");
    expect(rowTone("unreachable")).toBe("muted");
    expect(rowTone("disabled")).toBe("muted");
    expect(rowTone("checking")).toBe("muted");
  });
});
