import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { resourcesApi } from "./resources";
import { setCsrfToken } from "./client";

describe("resourcesApi", () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    global.fetch = mockFetch;
    vi.clearAllMocks();
    setCsrfToken("test-csrf-token");
  });

  afterEach(() => {
    setCsrfToken(null);
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

  const okJson = (body: unknown) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });

  describe("create", () => {
    it("POSTs the resource to /resources", async () => {
      mockFetch.mockResolvedValueOnce(okJson({ id: "new-resource" }));

      await resourcesApi.create({
        uri: "resource://example",
        name: "Example",
        content: "hello",
      } as Parameters<typeof resourcesApi.create>[0]);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/resources"),
        expect.objectContaining({ method: "POST" }),
      );
    });
  });

  describe("update", () => {
    it("PUTs the resource to /resources/:id", async () => {
      mockFetch.mockResolvedValueOnce(okJson({ id: "res-1" }));

      await resourcesApi.update("res-1", { name: "Renamed" } as Parameters<
        typeof resourcesApi.update
      >[1]);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/resources/res-1"),
        expect.objectContaining({ method: "PUT" }),
      );
    });

    it("throws synchronously for an invalid ID", () => {
      expect(() => resourcesApi.update("../etc/passwd", {})).toThrow("Invalid resource ID format");
    });
  });

  describe("delete", () => {
    it("DELETEs /resources/:id", async () => {
      mockFetch.mockResolvedValueOnce(okJson({}));

      await resourcesApi.delete("res-1");

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/resources/res-1"),
        expect.objectContaining({ method: "DELETE" }),
      );
    });

    it("throws synchronously for an invalid ID", () => {
      expect(() => resourcesApi.delete("bad/id")).toThrow("Invalid resource ID format");
    });
  });

  describe("setState", () => {
    it("POSTs /resources/:id/state?activate=true and returns the canonical resource", async () => {
      const body = {
        status: "success",
        message: "Resource res-1 activated",
        resource: { id: "res-1", enabled: true },
      };
      mockFetch.mockResolvedValueOnce(okJson(body));

      const result = await resourcesApi.setState("res-1", true);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/resources/res-1/state?activate=true"),
        expect.objectContaining({ method: "POST" }),
      );
      expect(result).toEqual(body);
    });

    it("POSTs /resources/:id/state?activate=false", async () => {
      mockFetch.mockResolvedValueOnce(
        okJson({
          status: "success",
          message: "deactivated",
          resource: { id: "res-1", enabled: false },
        }),
      );

      await resourcesApi.setState("res-1", false);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/resources/res-1/state?activate=false"),
        expect.objectContaining({ method: "POST" }),
      );
    });

    it("throws synchronously for an invalid ID", () => {
      expect(() => resourcesApi.setState("../etc/passwd", true)).toThrow(
        "Invalid resource ID format",
      );
    });

    it("throws ApiError on a non-2xx response", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Not found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      );

      await expect(resourcesApi.setState("res-1", true)).rejects.toThrow("HTTP 404");
    });
  });

  describe("validateResourceId (via delete)", () => {
    it("rejects an empty id", () => {
      expect(() => resourcesApi.delete("")).toThrow(/^Invalid resource ID$/);
    });

    it("rejects an id longer than 255 characters", () => {
      expect(() => resourcesApi.delete("a".repeat(256))).toThrow("Resource ID too long");
    });
  });
});
