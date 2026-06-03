import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { paramsForWindow, REFRESH_INTERVAL_MS, useMetrics } from "./useMetrics";
import { metricsApi } from "@/api/metrics";

const TIMESERIES_FIXTURE = {
  timestamps: ["2026-01-01T00:00:00Z"],
  request_count: [10],
  success_count: [9],
  error_count: [1],
  error_rate: [10],
};

const PERCENTILES_FIXTURE = {
  timestamps: ["2026-01-01T00:00:00Z"],
  p50: [50],
  p90: [90],
  p95: [95],
  p99: [99],
};

describe("paramsForWindow", () => {
  it("maps each window to the expected hours + interval", () => {
    expect(paramsForWindow("hour")).toEqual({ hours: 1, intervalMinutes: 5 });
    expect(paramsForWindow("day")).toEqual({ hours: 24, intervalMinutes: 60 });
    expect(paramsForWindow("week")).toEqual({ hours: 168, intervalMinutes: 360 });
  });
});

// Real-time tests cover behavior that doesn't depend on the refresh interval:
// initial fetch, error capture, window-change refetch.
describe("useMetrics — initial fetch", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches both endpoints on mount with the window's params", async () => {
    const tsSpy = vi.spyOn(metricsApi, "getTimeseries").mockResolvedValue(TIMESERIES_FIXTURE);
    const pctSpy = vi.spyOn(metricsApi, "getPercentiles").mockResolvedValue(PERCENTILES_FIXTURE);

    const { result } = renderHook(() => useMetrics("day"));

    await waitFor(() => expect(result.current.timeseries).not.toBeNull());

    expect(tsSpy).toHaveBeenCalledWith(expect.objectContaining({ hours: 24, intervalMinutes: 60 }));
    expect(pctSpy).toHaveBeenCalledWith(
      expect.objectContaining({ hours: 24, intervalMinutes: 60 }),
    );
    expect(result.current.percentiles).toEqual(PERCENTILES_FIXTURE);
    expect(result.current.error).toBeNull();
    expect(result.current.lastUpdated).toBeInstanceOf(Date);
  });

  it("captures fetch errors and stops loading", async () => {
    vi.spyOn(metricsApi, "getTimeseries").mockRejectedValue(new Error("boom"));
    vi.spyOn(metricsApi, "getPercentiles").mockResolvedValue(PERCENTILES_FIXTURE);

    const { result } = renderHook(() => useMetrics("day"));

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error?.message).toBe("boom");
    expect(result.current.isLoading).toBe(false);
  });

  it("refetches when window changes", async () => {
    const tsSpy = vi.spyOn(metricsApi, "getTimeseries").mockResolvedValue(TIMESERIES_FIXTURE);
    vi.spyOn(metricsApi, "getPercentiles").mockResolvedValue(PERCENTILES_FIXTURE);

    type Props = { w: "hour" | "day" | "week" };
    const { rerender, result } = renderHook(({ w }: Props) => useMetrics(w), {
      initialProps: { w: "hour" } as Props,
    });
    await waitFor(() => expect(result.current.timeseries).not.toBeNull());
    expect(tsSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({ hours: 1, intervalMinutes: 5 }),
    );

    rerender({ w: "week" });
    await waitFor(() => expect(tsSpy).toHaveBeenCalledTimes(2));
    expect(tsSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({ hours: 168, intervalMinutes: 360 }),
    );
  });
});

// Fake-time tests cover interval ticks and visibility transitions. We mock the
// `document.visibilityState` getter via Object.defineProperty so toggling
// `visibilityState` in the test body reflects in the hook's check.
describe("useMetrics — refresh interval", () => {
  let visibilityState: DocumentVisibilityState;

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    visibilityState = "visible";
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => visibilityState,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("refetches on the 30s interval when tab is visible", async () => {
    const tsSpy = vi.spyOn(metricsApi, "getTimeseries").mockResolvedValue(TIMESERIES_FIXTURE);
    vi.spyOn(metricsApi, "getPercentiles").mockResolvedValue(PERCENTILES_FIXTURE);

    const { result } = renderHook(() => useMetrics("day"));
    await vi.waitFor(() => expect(result.current.lastUpdated).not.toBeNull());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(REFRESH_INTERVAL_MS);
    });

    await vi.waitFor(() => expect(tsSpy).toHaveBeenCalledTimes(2));
  });

  it("skips the interval tick when the tab is hidden", async () => {
    const tsSpy = vi.spyOn(metricsApi, "getTimeseries").mockResolvedValue(TIMESERIES_FIXTURE);
    vi.spyOn(metricsApi, "getPercentiles").mockResolvedValue(PERCENTILES_FIXTURE);

    const { result } = renderHook(() => useMetrics("day"));
    await vi.waitFor(() => expect(result.current.lastUpdated).not.toBeNull());

    visibilityState = "hidden";

    await act(async () => {
      await vi.advanceTimersByTimeAsync(REFRESH_INTERVAL_MS * 3);
    });

    expect(tsSpy).toHaveBeenCalledTimes(1);
  });

  it("refetches immediately when tab becomes visible after being hidden longer than the interval", async () => {
    const tsSpy = vi.spyOn(metricsApi, "getTimeseries").mockResolvedValue(TIMESERIES_FIXTURE);
    vi.spyOn(metricsApi, "getPercentiles").mockResolvedValue(PERCENTILES_FIXTURE);

    const { result } = renderHook(() => useMetrics("day"));
    await vi.waitFor(() => expect(result.current.lastUpdated).not.toBeNull());

    visibilityState = "hidden";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REFRESH_INTERVAL_MS + 1_000);
    });

    visibilityState = "visible";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    await vi.waitFor(() => expect(tsSpy).toHaveBeenCalledTimes(2));
  });

  it("clears the interval on unmount", async () => {
    const tsSpy = vi.spyOn(metricsApi, "getTimeseries").mockResolvedValue(TIMESERIES_FIXTURE);
    vi.spyOn(metricsApi, "getPercentiles").mockResolvedValue(PERCENTILES_FIXTURE);

    const { result, unmount } = renderHook(() => useMetrics("day"));
    await vi.waitFor(() => expect(result.current.lastUpdated).not.toBeNull());

    unmount();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(REFRESH_INTERVAL_MS * 2);
    });

    expect(tsSpy).toHaveBeenCalledTimes(1);
  });
});
