import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { toolsApi } from "./tools";

describe("toolsApi", () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    global.fetch = mockFetch;
    vi.clearAllMocks();
    Object.defineProperty(document, "cookie", {
      writable: true,
      value: "mcpgateway_csrf_token=test-csrf-token",
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("delete", () => {
    it("calls DELETE /tools/:id with CSRF token and same-origin credentials", async () => {
      mockFetch.mockResolvedValueOnce(new Response(null, { status: 204 }));

      await toolsApi.delete("tool-abc-123");

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/tools/tool-abc-123"),
        expect.objectContaining({
          method: "DELETE",
          headers: expect.objectContaining({
            "X-CSRF-Token": "test-csrf-token",
          }),
          credentials: "same-origin", // pragma: allowlist secret
        }),
      );
    });

    it("accepts UUID format IDs", async () => {
      mockFetch.mockResolvedValueOnce(new Response(null, { status: 204 }));

      await expect(
        toolsApi.delete("550e8400-e29b-41d4-a716-446655440000"),
      ).resolves.toBeUndefined();
    });

    it("accepts alphanumeric IDs with underscores", async () => {
      mockFetch.mockResolvedValueOnce(new Response(null, { status: 204 }));

      await expect(toolsApi.delete("tool_123_abc")).resolves.toBeUndefined();
    });

    it("throws synchronously for an empty ID", () => {
      expect(() => toolsApi.delete("")).toThrow("Invalid tool ID");
    });

    it("throws synchronously for ID with path traversal characters", () => {
      expect(() => toolsApi.delete("../etc/passwd")).toThrow("Invalid tool ID format");
    });

    it("throws synchronously for ID with spaces", () => {
      expect(() => toolsApi.delete("tool id with spaces")).toThrow("Invalid tool ID format");
    });

    it("throws synchronously for ID with special characters", () => {
      expect(() => toolsApi.delete("tool<script>")).toThrow("Invalid tool ID format");
    });

    it("throws ApiError on 404 response", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Tool not found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      );

      await expect(toolsApi.delete("tool-abc-123")).rejects.toThrow("HTTP 404");
    });

    it("throws ApiError on 500 response", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Internal server error" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }),
      );

      await expect(toolsApi.delete("tool-abc-123")).rejects.toThrow("HTTP 500");
    });
  });
});
