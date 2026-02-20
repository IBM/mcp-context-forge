/**
 * Unit tests for async/fetch-related functions.
 * Tests pure functions with mocked fetch - no DOM required.
 */

import { describe, test, expect, vi, beforeEach } from "vitest";
import {
  parseErrorResponse,
  safeParseJsonResponse,
} from "../../mcpgateway/admin_ui/security.js";
import {
  getAuthToken,
  fetchWithAuth,
} from "../../mcpgateway/admin_ui/tokens.js";
import { fetchWithTimeout } from "../../mcpgateway/admin_ui/utils.js";

// ---------------------------------------------------------------------------
// Helper: create a mock Response-like object
// ---------------------------------------------------------------------------
function mockResponse({
  ok = true,
  status = 200,
  body = "",
  contentType = "text/plain",
  headers = {},
} = {}) {
  const allHeaders = { "content-type": contentType, ...headers };
  const textValue = typeof body === "string" ? body : JSON.stringify(body);
  // json() lazily parses: if body is already an object, return it directly;
  // otherwise attempt JSON.parse (may fail, which is expected for non-JSON).
  const jsonValue =
    typeof body === "object" && body !== null
      ? body
      : (() => {
        try {
          return JSON.parse(body || "{}");
        } catch {
          return {};
        }
      })();
  return {
    ok,
    status,
    headers: {
      get(name) {
        return allHeaders[name.toLowerCase()] || null;
      },
    },
    json: vi.fn().mockResolvedValue(jsonValue),
    text: vi.fn().mockResolvedValue(textValue),
    clone() {
      return mockResponse({ ok, status, body, contentType, headers });
    },
  };
}

// ---------------------------------------------------------------------------
// parseErrorResponse
// ---------------------------------------------------------------------------
describe("parseErrorResponse", () => {
  test("parses JSON error body", async () => {
    const resp = mockResponse({
      ok: false,
      status: 400,
      contentType: "application/json",
      body: { detail: "Bad request" },
    });
    const result = await parseErrorResponse(resp, "fallback");
    expect(result).toContain("Bad request");
  });

  test("returns text body for non-JSON response", async () => {
    const resp = mockResponse({
      ok: false,
      status: 500,
      body: "Internal Server Error",
    });
    const result = await parseErrorResponse(resp, "fallback");
    expect(result).toBe("Internal Server Error");
  });

  test("returns fallback for empty text body", async () => {
    const resp = mockResponse({
      ok: false,
      status: 500,
      body: "",
    });
    const result = await parseErrorResponse(resp, "fallback");
    expect(result).toBe("fallback");
  });

  test("detects HTML responses and returns generic message", async () => {
    const resp = mockResponse({
      ok: false,
      status: 502,
      body: "<!DOCTYPE html><html><body>Bad Gateway</body></html>",
    });
    const result = await parseErrorResponse(resp, "Error occurred");
    expect(result).toContain("Error occurred");
    expect(result).toContain("HTML error page");
  });

  test("detects <html starting responses", async () => {
    const resp = mockResponse({
      ok: false,
      status: 502,
      body: "<html><body>Error</body></html>",
    });
    const result = await parseErrorResponse(resp, "Error occurred");
    expect(result).toContain("HTML error page");
  });

  test("truncates long text responses", async () => {
    const longText = "x".repeat(300);
    const resp = mockResponse({
      ok: false,
      status: 500,
      body: longText,
    });
    const result = await parseErrorResponse(resp, "fallback");
    expect(result.length).toBeLessThan(300);
    expect(result).toContain("...");
  });

  test("returns fallback on exception", async () => {
    const resp = {
      headers: {
        get() {
          throw new Error("broken");
        },
      },
    };
    const result = await parseErrorResponse(resp, "safe fallback");
    expect(result).toBe("safe fallback");
  });

  test("uses default fallback message", async () => {
    const resp = mockResponse({ ok: false, status: 500, body: "" });
    const result = await parseErrorResponse(resp);
    expect(result).toBe("An error occurred");
  });
});

// ---------------------------------------------------------------------------
// safeParseJsonResponse
// ---------------------------------------------------------------------------
describe("safeParseJsonResponse", () => {
  test("parses JSON from OK response", async () => {
    const resp = mockResponse({
      ok: true,
      status: 200,
      contentType: "application/json",
      body: { result: "success" },
    });
    const data = await safeParseJsonResponse(resp);
    expect(data.result).toBe("success");
  });

  test("throws for non-OK response", async () => {
    const resp = mockResponse({
      ok: false,
      status: 400,
      contentType: "application/json",
      body: { detail: "Bad request" },
    });
    await expect(safeParseJsonResponse(resp)).rejects.toThrow();
  });

  test("throws for non-JSON content type on OK response", async () => {
    const resp = mockResponse({
      ok: true,
      status: 200,
      contentType: "text/html",
      body: "<html></html>",
    });
    await expect(safeParseJsonResponse(resp)).rejects.toThrow(
      /unexpected response/
    );
  });

  test("includes custom fallback error in thrown message", async () => {
    const resp = mockResponse({
      ok: false,
      status: 500,
      body: "",
    });
    await expect(safeParseJsonResponse(resp, "Custom error")).rejects.toThrow(
      /Custom error/
    );
  });
});

// ---------------------------------------------------------------------------
// fetchWithTimeout
// ---------------------------------------------------------------------------
describe("fetchWithTimeout", () => {
  let originalFetch;

  beforeEach(() => {
    originalFetch = global.fetch;
  });

  test("calls fetch with merged headers", async () => {
    const fakeResponse = mockResponse({
      ok: true,
      status: 200,
      body: "ok",
    });
    global.fetch = vi.fn().mockResolvedValue(fakeResponse);

    await fetchWithTimeout("/api/test", {
      headers: { "X-Custom": "1" },
    });
    expect(global.fetch).toHaveBeenCalledTimes(1);

    const callArgs = global.fetch.mock.calls[0];
    expect(callArgs[0]).toBe("/api/test");
    expect(callArgs[1].headers["X-Custom"]).toBe("1");
    expect(callArgs[1].headers["Cache-Control"]).toBe("no-cache");

    global.fetch = originalFetch;
  });

  test("throws on status 0 (network error)", async () => {
    const fakeResponse = mockResponse({ ok: false, status: 0 });
    global.fetch = vi.fn().mockResolvedValue(fakeResponse);

    await expect(fetchWithTimeout("/api/test")).rejects.toThrow(
      /Network error/
    );

    global.fetch = originalFetch;
  });

  test("re-throws AbortError as timeout message", async () => {
    const abortErr = new Error("The operation was aborted");
    abortErr.name = "AbortError";
    global.fetch = vi.fn().mockRejectedValue(abortErr);

    await expect(fetchWithTimeout("/api/test", {}, 100)).rejects.toThrow(
      /timed out/
    );

    global.fetch = originalFetch;
  });

  test("re-throws Failed to fetch as connection error", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("Failed to fetch"));

    await expect(fetchWithTimeout("/api/test")).rejects.toThrow(
      /Unable to connect/
    );

    global.fetch = originalFetch;
  });

  test("re-throws empty response errors", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("ERR_EMPTY_RESPONSE"));

    await expect(fetchWithTimeout("/api/test")).rejects.toThrow(
      /empty response/
    );

    global.fetch = originalFetch;
  });

  test("passes through other errors unchanged", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("custom error"));

    await expect(fetchWithTimeout("/api/test")).rejects.toThrow("custom error");

    global.fetch = originalFetch;
  });

  test("returns response for non-200 OK responses", async () => {
    const fakeResponse = mockResponse({ ok: false, status: 404 });
    global.fetch = vi.fn().mockResolvedValue(fakeResponse);

    const result = await fetchWithTimeout("/api/test");
    expect(result.status).toBe(404);

    global.fetch = originalFetch;
  });
});

// ---------------------------------------------------------------------------
// getAuthToken
// ---------------------------------------------------------------------------
describe("getAuthToken", () => {
  beforeEach(() => {
    // Clear cookies before each test
    document.cookie = "jwt_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    document.cookie = "token=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  test("returns jwt_token cookie value", async () => {
    document.cookie = "jwt_token=my-secret-token";
    const token = await getAuthToken();
    expect(token).toBe("my-secret-token");
  });

  test("returns empty string when no token found", async () => {
    const token = await getAuthToken();
    expect(typeof token).toBe("string");
  });
});

// ---------------------------------------------------------------------------
// fetchWithAuth
// ---------------------------------------------------------------------------
describe("fetchWithAuth", () => {
  let originalFetch;

  beforeEach(() => {
    originalFetch = global.fetch;
    // Clear cookies
    document.cookie = "jwt_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  test("adds Authorization header when token exists", async () => {
    document.cookie = "jwt_token=test-token-123";
    global.fetch = vi.fn().mockResolvedValue(mockResponse());

    await fetchWithAuth("/api/data");

    const callArgs = global.fetch.mock.calls[0];
    const headers = callArgs[1].headers;
    // Headers object - check via get method
    expect(headers.get("Authorization")).toBe("Bearer test-token-123");

    global.fetch = originalFetch;
  });

  test("sets credentials to same-origin by default", async () => {
    global.fetch = vi.fn().mockResolvedValue(mockResponse());

    await fetchWithAuth("/api/data");

    const callArgs = global.fetch.mock.calls[0];
    expect(callArgs[1].credentials).toBe("same-origin");

    global.fetch = originalFetch;
  });

  test("preserves caller-provided credentials", async () => {
    global.fetch = vi.fn().mockResolvedValue(mockResponse());

    await fetchWithAuth("/api/data", { credentials: "include" });

    const callArgs = global.fetch.mock.calls[0];
    expect(callArgs[1].credentials).toBe("include");

    global.fetch = originalFetch;
  });

  test("preserves caller-provided headers", async () => {
    document.cookie = "jwt_token=tok";
    global.fetch = vi.fn().mockResolvedValue(mockResponse());

    await fetchWithAuth("/api/data", {
      headers: { "X-Custom": "value" },
    });

    const callArgs = global.fetch.mock.calls[0];
    const headers = callArgs[1].headers;
    expect(headers.get("X-Custom")).toBe("value");
    expect(headers.get("Authorization")).toBe("Bearer tok");

    global.fetch = originalFetch;
  });
});
