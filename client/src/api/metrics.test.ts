import { afterEach, describe, expect, it, vi } from "vitest";
import { metricsApi, __test__ } from "./metrics";
import { api } from "./client";

const { buildQuery, clampInt } = __test__;

describe("metrics API", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("clampInt", () => {
    it("returns undefined when value is undefined", () => {
      expect(clampInt(undefined, 1, 100)).toBeUndefined();
    });

    it("returns undefined when value is not finite", () => {
      expect(clampInt(Number.NaN, 1, 100)).toBeUndefined();
      expect(clampInt(Number.POSITIVE_INFINITY, 1, 100)).toBeUndefined();
    });

    it("clamps below min and above max", () => {
      expect(clampInt(0, 1, 100)).toBe(1);
      expect(clampInt(500, 1, 100)).toBe(100);
    });

    it("floors fractional values", () => {
      expect(clampInt(2.9, 1, 100)).toBe(2);
    });
  });

  describe("buildQuery", () => {
    it("returns an empty string when nothing is provided", () => {
      expect(buildQuery({})).toBe("");
    });

    it("emits hours and interval_minutes when provided", () => {
      expect(buildQuery({ hours: 24, intervalMinutes: 60 })).toBe("?hours=24&interval_minutes=60");
    });

    it("clamps params to backend-supported ranges", () => {
      expect(buildQuery({ hours: 9999, intervalMinutes: 1 })).toBe("?hours=168&interval_minutes=5");
    });
  });

  describe("metricsApi.getTimeseries", () => {
    it("hits the admin timeseries endpoint with clamped params", async () => {
      const spy = vi.spyOn(api, "get").mockResolvedValue({
        timestamps: [],
        request_count: [],
        success_count: [],
        error_count: [],
        error_rate: [],
      });

      await metricsApi.getTimeseries({ hours: 24, intervalMinutes: 60 });

      expect(spy).toHaveBeenCalledWith(
        "/admin/observability/metrics/timeseries?hours=24&interval_minutes=60",
        undefined,
        undefined,
      );
    });

    it("forwards the abort signal", async () => {
      const spy = vi.spyOn(api, "get").mockResolvedValue({
        timestamps: [],
        request_count: [],
        success_count: [],
        error_count: [],
        error_rate: [],
      });
      const controller = new AbortController();

      await metricsApi.getTimeseries({ signal: controller.signal });

      expect(spy).toHaveBeenCalledWith(
        "/admin/observability/metrics/timeseries",
        undefined,
        controller.signal,
      );
    });
  });

  describe("metricsApi.getPercentiles", () => {
    it("hits the admin percentiles endpoint with clamped params", async () => {
      const spy = vi.spyOn(api, "get").mockResolvedValue({
        timestamps: [],
        p50: [],
        p90: [],
        p95: [],
        p99: [],
      });

      await metricsApi.getPercentiles({ hours: 168, intervalMinutes: 1440 });

      expect(spy).toHaveBeenCalledWith(
        "/admin/observability/metrics/percentiles?hours=168&interval_minutes=1440",
        undefined,
        undefined,
      );
    });
  });
});
