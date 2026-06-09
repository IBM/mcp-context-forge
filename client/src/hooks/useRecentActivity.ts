/**
 * useRecentActivity
 *
 * Polls GET /api/logs/activity every POLL_INTERVAL_MS. When
 * VITE_USE_MOCK_ACTIVITY=true (dev convenience while the backend endpoint is
 * unimplemented), returns the fixture directly without a network call.
 */

import { useCallback, useEffect, useState } from "react";

import { activityApi } from "@/api/activity";
import { RECENT_ACTIVITY_FIXTURE } from "@/test/mocks/fixtures/recentActivity";
import type { ActivityItem } from "@/types/activity";

export const RECENT_ACTIVITY_POLL_INTERVAL_MS = 30_000;

interface UseRecentActivityResult {
  items: ActivityItem[];
  isLoading: boolean;
  error: { message: string } | null;
  refetch: () => Promise<void>;
}

interface UseRecentActivityOptions {
  /** Defaults to 10. Server clamps to [1, 100]. */
  limit?: number;
  /** Polling cadence override. Pass 0 to disable. */
  pollIntervalMs?: number;
}

function isMockEnabled(): boolean {
  return import.meta.env.VITE_USE_MOCK_ACTIVITY === "true";
}

export function useRecentActivity(options: UseRecentActivityOptions = {}): UseRecentActivityResult {
  const { limit = 10, pollIntervalMs = RECENT_ACTIVITY_POLL_INTERVAL_MS } = options;
  const mock = isMockEnabled();

  const [items, setItems] = useState<ActivityItem[]>(mock ? RECENT_ACTIVITY_FIXTURE : []);
  const [isLoading, setIsLoading] = useState<boolean>(!mock);
  const [error, setError] = useState<{ message: string } | null>(null);

  const fetchOnce = useCallback(
    async (signal?: AbortSignal): Promise<void> => {
      if (mock) {
        setItems(RECENT_ACTIVITY_FIXTURE.slice(0, limit));
        setIsLoading(false);
        setError(null);
        return;
      }

      try {
        const response = await activityApi.list({ limit, signal });
        setItems(response.items);
        setError(null);
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return;
        const message = err instanceof Error ? err.message : "Failed to load recent activity";
        setError({ message });
      } finally {
        setIsLoading(false);
      }
    },
    [limit, mock],
  );

  useEffect(() => {
    const controller = new AbortController();
    void fetchOnce(controller.signal);

    if (mock || pollIntervalMs <= 0) {
      return () => controller.abort();
    }

    const intervalId = window.setInterval(() => {
      void fetchOnce();
    }, pollIntervalMs);

    return () => {
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, [fetchOnce, mock, pollIntervalMs]);

  const refetch = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    await fetchOnce();
  }, [fetchOnce]);

  return { items, isLoading, error, refetch };
}
