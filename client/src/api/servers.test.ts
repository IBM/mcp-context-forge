import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { serversApi } from "./servers";
import type { GatewayTestRequest } from "@/generated/types";

describe("serversApi", () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    // Mock fetch globally
    global.fetch = mockFetch;
    vi.clearAllMocks();
    // Mock document.cookie for CSRF token
    Object.defineProperty(document, "cookie", {
      writable: true,
      value: "mcpgateway_csrf_token=test-csrf-token",
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("toggleEnabled", () => {
    it("should activate a server with CSRF token", async () => {
      const mockResponse = new Response(
        JSON.stringify({ status: "success", message: "Server activated" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
      mockFetch.mockResolvedValueOnce(mockResponse);

      const result = await serversApi.toggleEnabled("server-123", true);

      expect(result).toEqual({ status: "success", message: "Server activated" });

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/gateways/server-123/state?activate=true"),
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": "test-csrf-token",
          }),
          credentials: "same-origin", // pragma: allowlist secret
        }),
      );
    });

    it("should deactivate a server with CSRF token", async () => {
      const mockResponse = new Response(
        JSON.stringify({ status: "success", message: "Server deactivated" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
      mockFetch.mockResolvedValueOnce(mockResponse);

      const result = await serversApi.toggleEnabled("server-123", false);

      expect(result).toEqual({ status: "success", message: "Server deactivated" });
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/gateways/server-123/state?activate=false"),
        expect.anything(),
      );
    });

    it("should throw error when response is not ok", async () => {
      const mockResponse = new Response(JSON.stringify({ detail: "Internal server error" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
      mockFetch.mockResolvedValueOnce(mockResponse);

      await expect(serversApi.toggleEnabled("server-123", true)).rejects.toThrow("HTTP 500");
    });

    it("should work without CSRF token", async () => {
      Object.defineProperty(document, "cookie", {
        writable: true,
        value: "",
      });

      const mockResponse = new Response(
        JSON.stringify({ status: "success", message: "Server activated" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
      mockFetch.mockResolvedValueOnce(mockResponse);

      await serversApi.toggleEnabled("server-123", true);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/gateways/server-123/state?activate=true"),
        expect.objectContaining({
          headers: expect.objectContaining({
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
          }),
        }),
      );
    });
  });

  describe("fetchToolsAfterOAuth", () => {
    it("makes a POST to /oauth/fetch-tools/{id} with CSRF header and returns success response", async () => {
      const mockResponse = new Response(
        JSON.stringify({ success: true, message: "Successfully fetched and created 43 tools" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
      mockFetch.mockResolvedValueOnce(mockResponse);

      const result = await serversApi.fetchToolsAfterOAuth("server-abc");

      expect(result).toEqual({
        success: true,
        message: "Successfully fetched and created 43 tools",
      });
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/oauth/fetch-tools/server-abc"),
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({
            "X-CSRF-Token": "test-csrf-token",
          }),
          credentials: "same-origin", // pragma: allowlist secret
        }),
      );
    });

    it("throws ApiError on non-2xx response", async () => {
      const mockResponse = new Response(
        JSON.stringify({ detail: "Gateway not found: server-xyz" }),
        { status: 404, headers: { "Content-Type": "application/json" } },
      );
      mockFetch.mockResolvedValueOnce(mockResponse);

      await expect(serversApi.fetchToolsAfterOAuth("server-xyz")).rejects.toThrow("HTTP 404");
    });

    it("throws synchronously on invalid server ID", () => {
      expect(() => serversApi.fetchToolsAfterOAuth("../etc/passwd")).toThrow(
        "Invalid server ID format",
      );
    });
  });

  describe("triggerOAuthAuthorization", () => {
    it("rejects when popup is blocked (window.open returns null)", async () => {
      vi.spyOn(window, "open").mockReturnValue(null);

      await expect(serversApi.triggerOAuthAuthorization("server-123")).rejects.toThrow(
        "Failed to open OAuth authorization window",
      );
    });

    it("opens the popup with the correct URL and popup=true flag", () => {
      const mockAuthWindow = { closed: false } as unknown as Window;
      vi.spyOn(window, "open").mockReturnValue(mockAuthWindow);

      // Don't await — just trigger the call
      serversApi.triggerOAuthAuthorization("server-abc");

      expect(window.open).toHaveBeenCalledWith(
        expect.stringContaining("/oauth/authorize/server-abc?popup=true"),
        "oauth_authorization",
        expect.any(String),
      );
    });

    it("resolves with success data when popup sends a success postMessage", async () => {
      const mockAuthWindow = { closed: false } as unknown as Window;
      vi.spyOn(window, "open").mockReturnValue(mockAuthWindow);

      const promise = serversApi.triggerOAuthAuthorization("server-123");

      const successData = {
        type: "oauth_callback",
        status: "success",
        gatewayId: "server-123",
        gatewayName: "Test Server",
      };
      const event = new MessageEvent("message", { data: successData });
      Object.defineProperty(event, "source", { value: mockAuthWindow, writable: false });
      window.dispatchEvent(event);

      await expect(promise).resolves.toEqual(successData);
    });

    it("rejects with errorDescription when popup sends an error postMessage", async () => {
      const mockAuthWindow = { closed: false } as unknown as Window;
      vi.spyOn(window, "open").mockReturnValue(mockAuthWindow);

      const promise = serversApi.triggerOAuthAuthorization("server-123");

      const event = new MessageEvent("message", {
        data: {
          type: "oauth_callback",
          status: "error",
          error: "access_denied",
          errorDescription: "User denied access",
        },
      });
      Object.defineProperty(event, "source", { value: mockAuthWindow, writable: false });
      window.dispatchEvent(event);

      await expect(promise).rejects.toThrow("User denied access");
    });

    it("falls back to the error code when errorDescription is absent", async () => {
      const mockAuthWindow = { closed: false } as unknown as Window;
      vi.spyOn(window, "open").mockReturnValue(mockAuthWindow);

      const promise = serversApi.triggerOAuthAuthorization("server-123");

      const event = new MessageEvent("message", {
        data: { type: "oauth_callback", status: "error", error: "server_error" },
      });
      Object.defineProperty(event, "source", { value: mockAuthWindow, writable: false });
      window.dispatchEvent(event);

      await expect(promise).rejects.toThrow("server_error");
    });

    it("falls back to generic message when neither errorDescription nor error is present", async () => {
      const mockAuthWindow = { closed: false } as unknown as Window;
      vi.spyOn(window, "open").mockReturnValue(mockAuthWindow);

      const promise = serversApi.triggerOAuthAuthorization("server-123");

      const event = new MessageEvent("message", {
        data: { type: "oauth_callback", status: "error" },
      });
      Object.defineProperty(event, "source", { value: mockAuthWindow, writable: false });
      window.dispatchEvent(event);

      await expect(promise).rejects.toThrow("OAuth authorization failed");
    });

    it("ignores postMessages from other sources", async () => {
      vi.useFakeTimers();
      const mockAuthWindow = { closed: false } as unknown as Window;
      vi.spyOn(window, "open").mockReturnValue(mockAuthWindow);

      const promise = serversApi.triggerOAuthAuthorization("server-123");

      // Message from a different source — should be ignored
      const foreignEvent = new MessageEvent("message", {
        data: { type: "oauth_callback", status: "success", gatewayId: "server-123" },
      });
      // source stays null (the default), which !== mockAuthWindow
      window.dispatchEvent(foreignEvent);

      // Simulate popup closing to settle the promise
      (mockAuthWindow as { closed: boolean }).closed = true;
      vi.advanceTimersByTime(1000);

      await expect(promise).rejects.toThrow("OAuth authorization was cancelled");

      vi.useRealTimers();
    });

    it("ignores non-oauth_callback messages from the popup", async () => {
      vi.useFakeTimers();
      const mockAuthWindow = { closed: false } as unknown as Window;
      vi.spyOn(window, "open").mockReturnValue(mockAuthWindow);

      const promise = serversApi.triggerOAuthAuthorization("server-123");

      // Correct source, but payloads that fail the null / type guard are ignored.
      const nullEvent = new MessageEvent("message", { data: null });
      Object.defineProperty(nullEvent, "source", { value: mockAuthWindow, writable: false });
      window.dispatchEvent(nullEvent);

      const wrongTypeEvent = new MessageEvent("message", { data: { type: "something_else" } });
      Object.defineProperty(wrongTypeEvent, "source", { value: mockAuthWindow, writable: false });
      window.dispatchEvent(wrongTypeEvent);

      // Neither settled the promise; closing the popup does.
      (mockAuthWindow as { closed: boolean }).closed = true;
      vi.advanceTimersByTime(1000);

      await expect(promise).rejects.toThrow("OAuth authorization was cancelled");

      vi.useRealTimers();
    });

    it("rejects with cancellation message when user closes the popup", async () => {
      vi.useFakeTimers();
      const mockAuthWindow = { closed: false } as unknown as Window;
      vi.spyOn(window, "open").mockReturnValue(mockAuthWindow);

      const promise = serversApi.triggerOAuthAuthorization("server-123");

      (mockAuthWindow as { closed: boolean }).closed = true;
      vi.advanceTimersByTime(1000);

      await expect(promise).rejects.toThrow("OAuth authorization was cancelled");

      vi.useRealTimers();
    });
  });

  describe("updateTags", () => {
    it("PUTs /gateways/:id with a tags-only body and returns the updated server", async () => {
      const updated = { id: "server-123", tags: [{ id: "prod", label: "prod" }] };
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify(updated), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      const result = await serversApi.updateTags("server-123", ["prod"]);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/gateways/server-123"),
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ tags: ["prod"] }),
        }),
      );
      expect(result).toEqual(updated);
    });

    it("throws synchronously for an invalid server ID", () => {
      expect(() => serversApi.updateTags("../etc/passwd", ["prod"])).toThrow(
        "Invalid server ID format",
      );
    });
  });

  describe("validateServerId (via get)", () => {
    it("throws 'Invalid server ID' for an empty id", () => {
      expect(() => serversApi.get("")).toThrow(/^Invalid server ID$/);
    });

    it("throws 'Invalid server ID format' for an id with illegal characters", () => {
      expect(() => serversApi.get("bad/id")).toThrow("Invalid server ID format");
    });
  });

  describe("list", () => {
    const jsonResponse = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });

    it("requests /gateways with only include_pagination by default", async () => {
      const body = { servers: [], pagination: { nextCursor: null } };
      mockFetch.mockResolvedValueOnce(jsonResponse(body));

      const result = await serversApi.list();

      expect(result).toEqual(body);
      const url = mockFetch.mock.calls[0][0] as string;
      expect(url).toContain("/gateways?");
      expect(url).toContain("include_pagination=true");
      expect(url).not.toContain("cursor=");
      expect(url).not.toContain("limit=");
      expect(url).not.toContain("include_inactive=");
    });

    it("includes cursor, clamped limit, and include_inactive when provided", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ servers: [] }));

      await serversApi.list({ cursor: "next-page", limit: 500, include_inactive: true });

      const url = mockFetch.mock.calls[0][0] as string;
      expect(url).toContain("cursor=next-page");
      expect(url).toContain("limit=100"); // clamped to the max of 100
      expect(url).toContain("include_inactive=true");
    });

    it("clamps a limit below 1 up to 1", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ servers: [] }));

      await serversApi.list({ limit: 0 });

      expect(mockFetch.mock.calls[0][0]).toContain("limit=1");
    });

    it("falls back to a limit of 25 for a non-finite limit", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ servers: [] }));

      await serversApi.list({ limit: Number.POSITIVE_INFINITY });

      expect(mockFetch.mock.calls[0][0]).toContain("limit=25");
    });

    it("resolves when passed an AbortSignal", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ servers: [] }));
      const controller = new AbortController();

      await expect(serversApi.list({ signal: controller.signal })).resolves.toEqual({
        servers: [],
      });
    });
  });

  describe("get", () => {
    const jsonResponse = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });

    it("fetches /gateways/:id and returns the server", async () => {
      const server = { id: "get-basic", name: "Basic" };
      mockFetch.mockResolvedValueOnce(jsonResponse(server));

      const result = await serversApi.get("get-basic");

      expect(result).toEqual(server);
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/gateways/get-basic"),
        expect.objectContaining({ method: "GET" }),
      );
    });

    it("returns the same in-flight promise for concurrent gets (request cache)", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ id: "get-cache" }));

      const first = serversApi.get("get-cache");
      const second = serversApi.get("get-cache");

      expect(first).toBe(second);
      await first;
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it("evicts the cache on failure so a later call retries", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "boom" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }),
      );

      await expect(serversApi.get("get-evict")).rejects.toThrow("HTTP 500");

      // The failed request was removed from the cache, so this refetches.
      mockFetch.mockResolvedValueOnce(jsonResponse({ id: "get-evict" }));
      const result = await serversApi.get("get-evict");

      expect(result).toEqual({ id: "get-evict" });
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });

  describe("testConnection", () => {
    it("POSTs /gateways/:id/test and returns the result", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ success: true, message: "Reachable" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      const result = await serversApi.testConnection("server-123");

      expect(result).toEqual({ success: true, message: "Reachable" });
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/gateways/server-123/test"),
        expect.objectContaining({ method: "POST" }),
      );
    });

    it("throws synchronously for an invalid server ID", () => {
      expect(() => serversApi.testConnection("../etc/passwd")).toThrow("Invalid server ID format");
    });
  });

  describe("delete", () => {
    it("DELETEs /gateways/:id", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      await serversApi.delete("server-123");

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/gateways/server-123"),
        expect.objectContaining({ method: "DELETE" }),
      );
    });

    it("throws synchronously for an invalid server ID", () => {
      expect(() => serversApi.delete("../etc/passwd")).toThrow("Invalid server ID format");
    });
  });

  describe("testConnectivity", () => {
    it("POSTs the request to /v1/mcp-servers/test and returns the response", async () => {
      const upstream = { statusCode: 200, body: "ok" };
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify(upstream), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      const request: GatewayTestRequest = {
        method: "GET",
        baseUrl: "https://example.com",
        path: "/health",
      };
      const result = await serversApi.testConnectivity(request);

      expect(result).toEqual(upstream);
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/v1/mcp-servers/test"),
        expect.objectContaining({ method: "POST", body: JSON.stringify(request) }),
      );
    });
  });
});
