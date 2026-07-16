import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { serversApi } from "./servers";

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
});
