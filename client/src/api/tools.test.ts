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

  describe("get", () => {
    it("calls GET /tools/:id and returns the tool", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "tool-abc-123", enabled: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      const tool = await toolsApi.get("tool-abc-123");

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/tools/tool-abc-123"),
        expect.objectContaining({ method: "GET" }),
      );
      expect(tool).toEqual({ id: "tool-abc-123", enabled: false });
    });

    it("throws synchronously for an empty ID", () => {
      expect(() => toolsApi.get("")).toThrow("Invalid tool ID");
    });

    it("throws synchronously for ID with path traversal characters", () => {
      expect(() => toolsApi.get("../etc/passwd")).toThrow("Invalid tool ID format");
    });
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

  describe("activate", () => {
    it("calls POST /tools/:id/state?activate=true with CSRF token and same-origin credentials", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "tool-abc-123", enabled: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      await toolsApi.activate("tool-abc-123");

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/tools/tool-abc-123/state?activate=true"),
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({
            "X-CSRF-Token": "test-csrf-token",
          }),
          credentials: "same-origin", // pragma: allowlist secret
        }),
      );
    });

    it("throws synchronously for an empty ID", () => {
      expect(() => toolsApi.activate("")).toThrow("Invalid tool ID");
    });

    it("throws synchronously for ID with path traversal characters", () => {
      expect(() => toolsApi.activate("../etc/passwd")).toThrow("Invalid tool ID format");
    });
  });

  describe("deactivate", () => {
    it("calls POST /tools/:id/state?activate=false with CSRF token and same-origin credentials", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "tool-abc-123", enabled: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      await toolsApi.deactivate("tool-abc-123");

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/tools/tool-abc-123/state?activate=false"),
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({
            "X-CSRF-Token": "test-csrf-token",
          }),
          credentials: "same-origin", // pragma: allowlist secret
        }),
      );
    });

    it("throws synchronously for an empty ID", () => {
      expect(() => toolsApi.deactivate("")).toThrow("Invalid tool ID");
    });

    it("throws ApiError on 403 response", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Forbidden" }), {
          status: 403,
          headers: { "Content-Type": "application/json" },
        }),
      );

      await expect(toolsApi.deactivate("tool-abc-123")).rejects.toThrow("HTTP 403");
    });
  });

  describe("generateSchemasFromOpenapi", () => {
    it("POSTs to /v1/tools/generate-schemas-from-openapi and returns the schemas", async () => {
      const body = {
        message: "Schemas generated successfully",
        success: true,
        input_schema: { type: "object" },
        output_schema: null,
        spec_url: "https://api.example.com/openapi.json",
      };
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      const result = await toolsApi.generateSchemasFromOpenapi({
        url: "https://api.example.com/v1/calculate",
        request_type: "POST",
      });

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/v1/tools/generate-schemas-from-openapi"),
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({ "X-CSRF-Token": "test-csrf-token" }),
          credentials: "same-origin", // pragma: allowlist secret
        }),
      );
      expect(result).toEqual(body);
    });

    it("throws ApiError carrying the backend status on failure", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ success: false, message: "blocked" }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        }),
      );

      await expect(
        toolsApi.generateSchemasFromOpenapi({
          url: "https://api.example.com/v1/calculate",
          request_type: "POST",
        }),
      ).rejects.toThrow("HTTP 400");
    });
  });

  describe("updateTags", () => {
    it("PUTs /tools/:id with a tags-only body and returns the updated tool", async () => {
      const updated = { id: "tool-abc-123", tags: [{ id: "ml", label: "ml" }] };
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify(updated), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      const result = await toolsApi.updateTags("tool-abc-123", ["ml"]);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/tools/tool-abc-123"),
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ tags: ["ml"] }),
        }),
      );
      expect(result).toEqual(updated);
    });

    it("throws synchronously for an invalid ID", () => {
      expect(() => toolsApi.updateTags("../etc/passwd", ["ml"])).toThrow("Invalid tool ID format");
    });
  });
});
