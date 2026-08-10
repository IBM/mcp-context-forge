import { describe, it, expect, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { useMcpServers } from "./useMcpServers";

const GATEWAYS = {
  gateways: [{ id: "gw-1", name: "server-1", enabled: true, reachable: true }],
};

function setTabHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { value: hidden, configurable: true });
}

describe("useMcpServers", () => {
  afterEach(() => {
    setTabHidden(false);
  });

  it("fetches /gateways and exposes servers plus a lastUpdated timestamp", async () => {
    server.use(http.get("*/gateways", () => HttpResponse.json(GATEWAYS)));

    const { result } = renderHook(() => useMcpServers(0)); // polling disabled

    await waitFor(() => expect(result.current.servers).toBeTruthy());
    expect(result.current.servers).toHaveLength(1);
    expect(result.current.lastUpdated).toBeTypeOf("number");
  });

  it("polls on the interval and pauses while the tab is hidden", async () => {
    let calls = 0;
    server.use(
      http.get("*/gateways", () => {
        calls += 1;
        return HttpResponse.json(GATEWAYS);
      }),
    );

    renderHook(() => useMcpServers(20)); // 20ms poll

    await waitFor(() => expect(calls).toBeGreaterThanOrEqual(2)); // initial + a tick
    const afterPolling = calls;

    setTabHidden(true);
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(calls).toBe(afterPolling); // hidden tab -> no additional fetches
  });

  it("fetches again when the tab becomes visible", async () => {
    let calls = 0;
    server.use(
      http.get("*/gateways", () => {
        calls += 1;
        return HttpResponse.json(GATEWAYS);
      }),
    );

    renderHook(() => useMcpServers(100_000)); // long interval; visibility drives the refetch

    await waitFor(() => expect(calls).toBe(1));
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(calls).toBe(2));
  });
});
