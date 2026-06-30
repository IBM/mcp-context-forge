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
    it("POSTs args to /prompts/:id and returns the rendered prompt", async () => {
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
      expect(result).toEqual(rendered);
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

    it("throws synchronously for an empty ID", () => {
      expect(() => promptsApi.render("")).toThrow("Invalid prompt ID");
    });

    it("throws synchronously for an ID with path traversal characters", () => {
      expect(() => promptsApi.render("../etc/passwd")).toThrow("Invalid prompt ID format");
    });
  });
});
