import { describe, expect, it } from "vitest";

import {
  getRightColumnCards,
  HOME_STATES,
  readActiveView,
  viewHref,
  type HomeViewId,
} from "./homeStates";

describe("readActiveView", () => {
  it("resolves the default state when there is no ?view=", () => {
    expect(readActiveView("/app/")).toBe("default");
  });

  it("resolves a known view from ?view=", () => {
    expect(readActiveView("/app/?view=mcp")).toBe("mcp");
    expect(readActiveView("/app/?view=activity&foo=1")).toBe("activity");
  });

  it("falls back to default for an unknown or explicit default view", () => {
    expect(readActiveView("/app/?view=bogus")).toBe("default");
    expect(readActiveView("/app/?view=default")).toBe("default");
  });
});

describe("getRightColumnCards", () => {
  it("renders no right column in the default state", () => {
    expect(getRightColumnCards("default")).toEqual([]);
  });

  it("shows the fixed order minus the active card in a non-default state", () => {
    expect(getRightColumnCards("mcp")).toEqual(["system", "activity", "a2a", "rest", "grpc"]);
    expect(getRightColumnCards("system")).toEqual(["activity", "mcp", "a2a", "rest", "grpc"]);
  });

  it("always hides exactly the active card (five of six visible)", () => {
    const nonDefault: HomeViewId[] = ["activity", "mcp", "a2a", "rest", "grpc", "system"];
    for (const view of nonDefault) {
      const cards = getRightColumnCards(view);
      expect(cards).toHaveLength(5);
      expect(cards).not.toContain(view);
    }
  });
});

describe("viewHref", () => {
  it("drops the param for the default state and encodes others", () => {
    expect(viewHref("default")).toBe("/app/");
    expect(viewHref("mcp")).toBe("/app/?view=mcp");
  });
});

describe("HOME_STATES permission gates", () => {
  it("gates the metrics-backed and audit-backed views on real permissions", () => {
    expect(HOME_STATES.system.requiredPermission).toBe("metrics:read");
    expect(HOME_STATES.activity.requiredPermission).toBe("audit:read");
  });

  it("leaves the default and placeholder views ungated", () => {
    expect(HOME_STATES.default.requiredPermission).toBeUndefined();
    expect(HOME_STATES.rest.requiredPermission).toBeUndefined();
    expect(HOME_STATES.grpc.requiredPermission).toBeUndefined();
  });

  it("leaves the mcp view ungated so the roster card can self-gate", () => {
    expect(HOME_STATES.mcp.requiredPermission).toBeUndefined();
  });
});
