import { describe, expect, it } from "vitest";

import { resolveHeadline } from "./resolveHeadline";

describe("resolveHeadline", () => {
  it("shows the healthy 'up and running' state when reachable with healthy dependencies", () => {
    expect(resolveHeadline({ reachable: true, dependenciesHealthy: true })).toEqual({
      messageId: "dashboard.home.headline.default",
      severity: "success",
    });
  });

  it("stays optimistic (healthy) while health is still loading", () => {
    // No signal yet — must not flash an error on first paint.
    expect(resolveHeadline()).toEqual({
      messageId: "dashboard.home.headline.default",
      severity: "success",
    });
    expect(resolveHeadline({ reachable: undefined, dependenciesHealthy: undefined })).toEqual({
      messageId: "dashboard.home.headline.default",
      severity: "success",
    });
  });

  it("reports unreachable as an error when /version does not respond", () => {
    expect(resolveHeadline({ reachable: false })).toEqual({
      messageId: "dashboard.home.headline.unreachable",
      severity: "error",
    });
  });

  it("reports degraded as a warning when a dependency is down but the process is up", () => {
    expect(resolveHeadline({ reachable: true, dependenciesHealthy: false })).toEqual({
      messageId: "dashboard.home.headline.degraded",
      severity: "warning",
    });
  });

  it("prioritises unreachable over a degraded dependency", () => {
    expect(resolveHeadline({ reachable: false, dependenciesHealthy: false })).toEqual({
      messageId: "dashboard.home.headline.unreachable",
      severity: "error",
    });
  });
});
