/**
 * Dashboard metrics hook.
 *
 * Fetches the observability timeseries + percentile endpoints in parallel for the
 * selected time window, auto-refreshes every 30s, and pauses while the tab is
 * hidden to avoid burning gateway capacity when no one is looking.
 *
 * In-flight requests are aborted on unmount or when a new fetch starts (window
 * change, manual retry, visibility change). Failures are surfaced as `error`
 * but do not stop the refresh interval — the next tick may succeed.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { metricsApi, type PercentilesResponse, type TimeseriesResponse } from "@/api/metrics";

export type TimeWindow = "hour" | "day" | "week";

interface WindowParams {
  hours: number;
  intervalMinutes: number;
}

const WINDOW_PARAMS: Record<TimeWindow, WindowParams> = {
  hour: { hours: 1, intervalMinutes: 5 },
  day: { hours: 24, intervalMinutes: 60 },
  week: { hours: 168, intervalMinutes: 360 },
};

export const REFRESH_INTERVAL_MS = 30_000;

export function paramsForWindow(window: TimeWindow): WindowParams {
  return WINDOW_PARAMS[window];
}

export interface MetricsState {
  timeseries: TimeseriesResponse | null;
  percentiles: PercentilesResponse | null;
  isLoading: boolean;
  error: Error | null;
  lastUpdated: Date | null;
  refetch: () => void;
}

export function useMetrics(window: TimeWindow): MetricsState {
  const [timeseries, setTimeseries] = useState<TimeseriesResponse | null>(null);
  const [percentiles, setPercentiles] = useState<PercentilesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchOnce = useCallback(async () => {
    // Abort any in-flight request before starting a new one
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setIsLoading(true);
    setError(null);

    const params = { ...WINDOW_PARAMS[window], signal: controller.signal };

    try {
      const [tsResult, pctResult] = await Promise.all([
        metricsApi.getTimeseries(params),
        metricsApi.getPercentiles(params),
      ]);

      if (controller.signal.aborted) return;

      setTimeseries(tsResult);
      setPercentiles(pctResult);
      setLastUpdated(new Date());
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err : new Error("Failed to load metrics"));
    } finally {
      if (!controller.signal.aborted) {
        setIsLoading(false);
      }
    }
  }, [window]);

  // Restart fetch + interval whenever the window changes.
  useEffect(() => {
    void fetchOnce();

    intervalRef.current = globalThis.setInterval(() => {
      if (document.visibilityState === "visible") {
        void fetchOnce();
      }
    }, REFRESH_INTERVAL_MS);

    return () => {
      if (intervalRef.current !== null) {
        globalThis.clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      abortRef.current?.abort();
    };
  }, [fetchOnce]);

  // When the tab becomes visible after being hidden, refetch immediately if the
  // last successful fetch is older than the refresh interval. Otherwise the
  // dashboard could show stale data for up to 30s after a long idle period.
  useEffect(() => {
    const handler = () => {
      if (document.visibilityState !== "visible") return;
      const ageMs = lastUpdated ? Date.now() - lastUpdated.getTime() : Infinity;
      if (ageMs >= REFRESH_INTERVAL_MS) {
        void fetchOnce();
      }
    };

    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, [fetchOnce, lastUpdated]);

  return {
    timeseries,
    percentiles,
    isLoading,
    error,
    lastUpdated,
    refetch: () => void fetchOnce(),
  };
}
