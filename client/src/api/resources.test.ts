import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { resourcesApi } from "./resources";

describe("resourcesApi", () => {
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

  describe("updateTags", () => {
    it("PUTs /resources/:id with a tags-only body and returns the updated resource", async () => {
      const updated = { id: "42", tags: ["alerts"] };
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify(updated), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      const result = await resourcesApi.updateTags("42", ["alerts"]);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/resources/42"),
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ tags: ["alerts"] }),
        }),
      );
      expect(result).toEqual(updated);
    });

    it("throws synchronously for an invalid ID", () => {
      expect(() => resourcesApi.updateTags("../etc/passwd", ["x"])).toThrow(
        "Invalid resource ID format",
      );
    });

    it("throws ApiError on a non-2xx response", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Forbidden" }), {
          status: 403,
          headers: { "Content-Type": "application/json" },
        }),
      );

      await expect(resourcesApi.updateTags("42", ["x"])).rejects.toThrow("HTTP 403");
    });
  });
});
