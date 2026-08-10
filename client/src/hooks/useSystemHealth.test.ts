import { describe, it, expect, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { useSystemHealth } from "./useSystemHealth";

const VERSION = {
  database: { dialect: "sqlite", reachable: true, server_version: null },
  redis: { available: false, reachable: false, server_version: null },
  settings: { cache_type: "memory" },
};

function setTabHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { value: hidden, configurable: true });
}

describe("useSystemHealth", () => {
  afterEach(() => {
    setTabHidden(false);
  });

  it("fetches /version when enabled", async () => {
    server.use(http.get("*/version", () => HttpResponse.json(VERSION)));

    const { result } = renderHook(() => useSystemHealth(0)); // polling disabled

    await waitFor(() => expect(result.current.data).toBeTruthy());
    expect(result.current.data?.database.reachable).toBe(true);
  });

  it("makes no request when disabled", async () => {
    let calls = 0;
    server.use(
      http.get("*/version", () => {
        calls += 1;
        return HttpResponse.json(VERSION);
      }),
    );

    const { result } = renderHook(() => useSystemHealth(0, false));

    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(calls).toBe(0);
    expect(result.current.data).toBeUndefined();
  });

  it("polls on the interval and pauses while the tab is hidden", async () => {
    let calls = 0;
    server.use(
      http.get("*/version", () => {
        calls += 1;
        return HttpResponse.json(VERSION);
      }),
    );

    renderHook(() => useSystemHealth(20)); // 20ms poll

    await waitFor(() => expect(calls).toBeGreaterThanOrEqual(2)); // initial + a tick
    const afterPolling = calls;

    setTabHidden(true);
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(calls).toBe(afterPolling); // hidden tab -> no additional fetches
  });

  it("fetches again when the tab becomes visible", async () => {
    let calls = 0;
    server.use(
      http.get("*/version", () => {
        calls += 1;
        return HttpResponse.json(VERSION);
      }),
    );

    renderHook(() => useSystemHealth(100_000)); // long interval; visibility drives the refetch

    await waitFor(() => expect(calls).toBe(1));
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(calls).toBe(2));
  });
});
