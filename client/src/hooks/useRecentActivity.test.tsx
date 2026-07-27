import { describe, it, expect } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { RECENT_ACTIVITY_FIXTURE } from "@/test/mocks/fixtures/recentActivity";

import { useRecentActivity } from "./useRecentActivity";

describe("useRecentActivity", () => {
  it("fetches and returns the typed payload", async () => {
    const { result } = renderHook(() => useRecentActivity({ pollIntervalMs: 0 }));

    expect(result.current.isLoading).toBe(true);

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.error).toBeNull();
    expect(result.current.items).toHaveLength(RECENT_ACTIVITY_FIXTURE.length);
    expect(result.current.items[0].id).toBe(RECENT_ACTIVITY_FIXTURE[0].id);
  });

  it("respects the limit parameter", async () => {
    const { result } = renderHook(() => useRecentActivity({ limit: 3, pollIntervalMs: 0 }));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.items).toHaveLength(3);
  });

  it("sets error state when the server fails", async () => {
    server.use(
      http.get("*/api/logs/activity", () => HttpResponse.json({ detail: "boom" }, { status: 500 })),
    );

    const { result } = renderHook(() => useRecentActivity({ pollIntervalMs: 0 }));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.error).not.toBeNull();
    expect(result.current.items).toEqual([]);
  });

  it("refetch re-hits the endpoint and clears the error", async () => {
    let callCount = 0;
    server.use(
      http.get("*/api/logs/activity", () => {
        callCount += 1;
        if (callCount === 1) {
          return HttpResponse.json({ detail: "boom" }, { status: 500 });
        }
        return HttpResponse.json({ items: RECENT_ACTIVITY_FIXTURE.slice(0, 2) });
      }),
    );

    const { result } = renderHook(() => useRecentActivity({ pollIntervalMs: 0 }));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).not.toBeNull();

    await act(async () => {
      await result.current.refetch();
    });

    expect(callCount).toBe(2);
    expect(result.current.error).toBeNull();
    expect(result.current.items).toHaveLength(2);
  });
});
