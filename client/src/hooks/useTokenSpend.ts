/**
 * LLM token spend dashboard hook.
 *
 * Independent of `useMetrics` so a slow or failing token-spend endpoint does
 * not block the executions/latency charts. Same refresh cadence, visibility
 * pausing, and abort behavior; window definitions are shared via
 * `paramsForWindow` and `REFRESH_INTERVAL_MS`.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { metricsApi, type TokenSpendResponse } from "@/api/metrics";
import { paramsForWindow, REFRESH_INTERVAL_MS, type TimeWindow } from "@/hooks/useMetrics";

export interface TokenSpendState {
  data: TokenSpendResponse | null;
  isLoading: boolean;
  error: Error | null;
  lastUpdated: Date | null;
  refetch: () => void;
}

export function useTokenSpend(window: TimeWindow): TokenSpendState {
  const [data, setData] = useState<TokenSpendResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchOnce = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setIsLoading(true);
    setError(null);

    const params = { ...paramsForWindow(window), signal: controller.signal };

    try {
      const result = await metricsApi.getTokenSpend(params);
      if (controller.signal.aborted) return;
      setData(result);
      setLastUpdated(new Date());
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err : new Error("Failed to load token spend"));
    } finally {
      if (!controller.signal.aborted) {
        setIsLoading(false);
      }
    }
  }, [window]);

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
    data,
    isLoading,
    error,
    lastUpdated,
    refetch: () => void fetchOnce(),
  };
}
