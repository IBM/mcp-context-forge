import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { promptsApi } from "./prompts";

describe("promptsApi", () => {
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

  describe("render", () => {
    it("POSTs args to /prompts/:name and returns the rendered prompt with the real HTTP status", async () => {
      const rendered = {
        messages: [{ role: "user", content: { type: "text", text: "Hello Alice" } }],
      };
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify(rendered), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      const result = await promptsApi.render("greet_user", { name: "Alice" });

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/prompts/greet_user"),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ name: "Alice" }),
        }),
      );
      expect(result).toEqual({ rendered, status: 200 });
    });

    it("propagates non-200 success codes (e.g. 202) through", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ messages: [] }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      );

      const result = await promptsApi.render("greet_user");

      expect(result.status).toBe(202);
    });

    it("defaults args to an empty object when omitted", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ messages: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      await promptsApi.render("noop");

      expect(mockFetch).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ body: JSON.stringify({}) }),
      );
    });

    it("throws synchronously for an empty name", () => {
      expect(() => promptsApi.render("")).toThrow("Invalid prompt name");
    });

    it("throws synchronously for a name with path traversal characters", () => {
      expect(() => promptsApi.render("../etc/passwd")).toThrow("Invalid prompt name format");
    });

    it("accepts backend-legal names with spaces and dots", async () => {
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ messages: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      await promptsApi.render("my prompt.v2");

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/prompts/my%20prompt.v2"),
        expect.anything(),
      );
    });
  });

  describe("updateTags", () => {
    it("PUTs /prompts/:id with a tags-only body and returns the updated prompt", async () => {
      const updated = { id: "prompt-1", tags: [{ id: "draft", label: "draft" }] };
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify(updated), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

      const result = await promptsApi.updateTags("prompt-1", ["draft"]);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/prompts/prompt-1"),
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ tags: ["draft"] }),
        }),
      );
      expect(result).toEqual(updated);
    });

    it("throws synchronously for an invalid prompt ID", () => {
      expect(() => promptsApi.updateTags("../etc/passwd", ["x"])).toThrow(
        "Invalid prompt ID format",
      );
    });
  });
});
