import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useTokenSpend } from "./useTokenSpend";
import { REFRESH_INTERVAL_MS } from "./useMetrics";
import { metricsApi } from "@/api/metrics";

const TOKEN_SPEND_FIXTURE = {
  timestamps: ["2026-01-01T00:00:00Z"],
  input_tokens: [1200],
  output_tokens: [800],
  cost_usd: [0.05],
};

describe("useTokenSpend — initial fetch", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches on mount with the window's params", async () => {
    const spy = vi.spyOn(metricsApi, "getTokenSpend").mockResolvedValue(TOKEN_SPEND_FIXTURE);

    const { result } = renderHook(() => useTokenSpend("day"));

    await waitFor(() => expect(result.current.data).not.toBeNull());

    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ hours: 24, intervalMinutes: 60 }));
    expect(result.current.data).toEqual(TOKEN_SPEND_FIXTURE);
    expect(result.current.error).toBeNull();
    expect(result.current.lastUpdated).toBeInstanceOf(Date);
  });

  it("captures fetch errors and stops loading", async () => {
    vi.spyOn(metricsApi, "getTokenSpend").mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useTokenSpend("day"));

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error?.message).toBe("boom");
    expect(result.current.isLoading).toBe(false);
  });

  it("refetches when window changes", async () => {
    const spy = vi.spyOn(metricsApi, "getTokenSpend").mockResolvedValue(TOKEN_SPEND_FIXTURE);

    type Props = { w: "hour" | "day" | "week" };
    const { rerender, result } = renderHook(({ w }: Props) => useTokenSpend(w), {
      initialProps: { w: "hour" } as Props,
    });
    await waitFor(() => expect(result.current.data).not.toBeNull());
    expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ hours: 1, intervalMinutes: 5 }));

    rerender({ w: "week" });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(spy).toHaveBeenLastCalledWith(
      expect.objectContaining({ hours: 168, intervalMinutes: 360 }),
    );
  });
});

describe("useTokenSpend — refresh interval", () => {
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
    const spy = vi.spyOn(metricsApi, "getTokenSpend").mockResolvedValue(TOKEN_SPEND_FIXTURE);

    const { result } = renderHook(() => useTokenSpend("day"));
    await vi.waitFor(() => expect(result.current.lastUpdated).not.toBeNull());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(REFRESH_INTERVAL_MS);
    });

    await vi.waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  });

  it("skips the interval tick when the tab is hidden", async () => {
    const spy = vi.spyOn(metricsApi, "getTokenSpend").mockResolvedValue(TOKEN_SPEND_FIXTURE);

    const { result } = renderHook(() => useTokenSpend("day"));
    await vi.waitFor(() => expect(result.current.lastUpdated).not.toBeNull());

    visibilityState = "hidden";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REFRESH_INTERVAL_MS * 3);
    });

    expect(spy).toHaveBeenCalledTimes(1);
  });
});
