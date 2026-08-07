import { describe, expect, it } from "vitest";

import { computeMiniCardStatuses } from "./miniCardStatus";

const base = {
  systemReachable: true,
  mcpReachable: true,
  a2aReachable: true,
  errors: 0,
  warnings: 0,
};

const ONLINE = { kind: "dot", tone: "success", labelId: "dashboard.home.status.online" };
const OFFLINE = { kind: "dot", tone: "muted", labelId: "dashboard.home.status.offline" };

describe("computeMiniCardStatuses", () => {
  it("shows a green Online dot for reachable sources", () => {
    const s = computeMiniCardStatuses(base);
    expect(s.system).toEqual(ONLINE);
    expect(s.mcp).toEqual(ONLINE);
    expect(s.a2a).toEqual(ONLINE);
  });

  it("shows a grey Offline dot when a source is not reachable", () => {
    const s = computeMiniCardStatuses({
      ...base,
      systemReachable: false,
      mcpReachable: false,
      a2aReachable: false,
    });
    expect(s.system).toEqual(OFFLINE);
    expect(s.mcp).toEqual(OFFLINE);
    expect(s.a2a).toEqual(OFFLINE);
  });

  it("always marks REST and gRPC offline (transport not built)", () => {
    const s = computeMiniCardStatuses(base);
    expect(s.rest).toEqual(OFFLINE);
    expect(s.grpc).toEqual(OFFLINE);
  });

  it("never returns a null/absent status — every card has a dot or counts", () => {
    const s = computeMiniCardStatuses({
      ...base,
      systemReachable: false,
      mcpReachable: false,
      a2aReachable: false,
    });
    for (const id of ["system", "activity", "mcp", "a2a", "rest", "grpc"] as const) {
      expect(s[id]).not.toBeNull();
    }
  });

  it("carries the activity error/warning counts", () => {
    const s = computeMiniCardStatuses({ ...base, errors: 2, warnings: 5 });
    expect(s.activity).toEqual({ kind: "activity", errors: 2, warnings: 5 });
  });
});
