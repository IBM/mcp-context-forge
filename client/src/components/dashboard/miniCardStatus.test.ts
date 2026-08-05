import { describe, expect, it } from "vitest";

import { computeMiniCardStatuses } from "./miniCardStatus";

const base = {
  systemRunning: true,
  mcpConfigured: true,
  a2aConfigured: true,
  healthy: true,
  errors: 0,
  warnings: 0,
};

describe("computeMiniCardStatuses", () => {
  it("marks a healthy configured runtime as success", () => {
    const s = computeMiniCardStatuses(base);
    expect(s.mcp).toEqual({
      kind: "dot",
      tone: "success",
      labelId: "dashboard.home.status.healthy",
    });
    expect(s.a2a).toEqual({
      kind: "dot",
      tone: "success",
      labelId: "dashboard.home.status.healthy",
    });
  });

  it("marks an unhealthy configured runtime as error", () => {
    const s = computeMiniCardStatuses({ ...base, healthy: false });
    expect(s.mcp).toEqual({
      kind: "dot",
      tone: "error",
      labelId: "dashboard.home.status.unhealthy",
    });
  });

  it("shows Not configured when a source has no instances", () => {
    const s = computeMiniCardStatuses({ ...base, mcpConfigured: false, a2aConfigured: false });
    expect(s.mcp).toEqual({
      kind: "dot",
      tone: "muted",
      labelId: "dashboard.home.status.notConfigured",
    });
    expect(s.a2a).toEqual({
      kind: "dot",
      tone: "muted",
      labelId: "dashboard.home.status.notConfigured",
    });
  });

  it("shows no dot when health is unknown but the source is configured", () => {
    const s = computeMiniCardStatuses({ ...base, healthy: null });
    expect(s.mcp).toBeNull();
    expect(s.a2a).toBeNull();
  });

  it("shows no dot (not a premature 'Not configured') while presence is loading", () => {
    const s = computeMiniCardStatuses({ ...base, mcpConfigured: null, a2aConfigured: null });
    expect(s.mcp).toBeNull();
    expect(s.a2a).toBeNull();
  });

  it("always marks REST and gRPC Not configured", () => {
    const s = computeMiniCardStatuses(base);
    expect(s.rest).toEqual({
      kind: "dot",
      tone: "muted",
      labelId: "dashboard.home.status.notConfigured",
    });
    expect(s.grpc).toEqual({
      kind: "dot",
      tone: "muted",
      labelId: "dashboard.home.status.notConfigured",
    });
  });

  it("marks System as Running when the backend is reachable, no dot otherwise", () => {
    expect(computeMiniCardStatuses(base).system).toEqual({
      kind: "dot",
      tone: "success",
      labelId: "dashboard.home.status.running",
    });
    expect(computeMiniCardStatuses({ ...base, systemRunning: null }).system).toBeNull();
  });

  it("carries the activity error/warning counts", () => {
    const s = computeMiniCardStatuses({ ...base, errors: 2, warnings: 5 });
    expect(s.activity).toEqual({ kind: "activity", errors: 2, warnings: 5 });
  });
});
