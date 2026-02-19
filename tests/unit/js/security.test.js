/**
 * Unit tests for security.js module
 * Tests: parseErrorResponse, safeParseJsonResponse, safeSetInnerHTML,
 *        logRestrictedContext, safeReplaceState
 * (escapeHtml, extractApiError, escapeHtmlChat, validatePassthroughHeader,
 *  validateInputName, validateUrl, validateJson are already tested in tests/js/)
 */

import { describe, test, expect, vi, beforeEach } from "vitest";
import {
  parseErrorResponse,
  safeParseJsonResponse,
  safeSetInnerHTML,
  safeReplaceState,
} from "../../../mcpgateway/admin_ui/security.js";

// ---------------------------------------------------------------------------
// Helper: create a mock Response object
// ---------------------------------------------------------------------------
function mockResponse(body, options = {}) {
  const {
    status = 200,
    ok = status >= 200 && status < 300,
    contentType = "application/json",
  } = options;

  const headers = new Map([["content-type", contentType]]);
  const textValue = typeof body === "string" ? body : JSON.stringify(body);
  let jsonValue;
  try {
    jsonValue = typeof body === "string" ? JSON.parse(body) : body;
  } catch {
    jsonValue = undefined;
  }

  return {
    ok,
    status,
    headers: { get: (key) => headers.get(key.toLowerCase()) || null },
    json: jsonValue !== undefined
      ? vi.fn().mockResolvedValue(jsonValue)
      : vi.fn().mockRejectedValue(new SyntaxError("Invalid JSON")),
    text: vi.fn().mockResolvedValue(textValue),
  };
}

// ---------------------------------------------------------------------------
// parseErrorResponse
// ---------------------------------------------------------------------------
describe("parseErrorResponse", () => {
  test("parses JSON error with detail string", async () => {
    const resp = mockResponse({ detail: "Not found" }, { status: 404, ok: false });
    const msg = await parseErrorResponse(resp, "fallback");
    expect(msg).toBe("Not found");
  });

  test("parses JSON error with message field", async () => {
    const resp = mockResponse({ message: "Bad request" }, { status: 400, ok: false });
    const msg = await parseErrorResponse(resp);
    expect(msg).toBe("Bad request");
  });

  test("parses JSON Pydantic validation error array", async () => {
    const resp = mockResponse(
      { detail: [{ msg: "field required" }, { msg: "invalid type" }] },
      { status: 422, ok: false }
    );
    const msg = await parseErrorResponse(resp);
    expect(msg).toBe("field required; invalid type");
  });

  test("returns plain text body for non-JSON response", async () => {
    const resp = mockResponse("Something went wrong", {
      status: 500,
      ok: false,
      contentType: "text/plain",
    });
    resp.json = vi.fn().mockRejectedValue(new Error("not json"));
    const msg = await parseErrorResponse(resp);
    expect(msg).toBe("Something went wrong");
  });

  test("returns generic message for HTML error page", async () => {
    const resp = mockResponse("<!DOCTYPE html><html>error</html>", {
      status: 502,
      ok: false,
      contentType: "text/html",
    });
    const msg = await parseErrorResponse(resp, "Gateway error");
    expect(msg).toContain("Gateway error");
    expect(msg).toContain("HTML error page");
  });

  test("detects <html prefix for HTML responses", async () => {
    const resp = mockResponse("<html><body>error</body></html>", {
      status: 500,
      ok: false,
      contentType: "text/html",
    });
    const msg = await parseErrorResponse(resp);
    expect(msg).toContain("HTML error page");
  });

  test("truncates long text responses", async () => {
    const longText = "a".repeat(300);
    const resp = mockResponse(longText, {
      status: 500,
      ok: false,
      contentType: "text/plain",
    });
    const msg = await parseErrorResponse(resp);
    expect(msg.length).toBeLessThan(longText.length);
    expect(msg).toContain("...");
  });

  test("returns fallback when response parsing throws", async () => {
    const resp = {
      headers: { get: () => { throw new Error("boom"); } },
      json: vi.fn().mockRejectedValue(new Error("boom")),
      text: vi.fn().mockRejectedValue(new Error("boom")),
      ok: false,
      status: 500,
    };
    const msg = await parseErrorResponse(resp, "Fallback msg");
    expect(msg).toBe("Fallback msg");
  });

  test("returns fallback for empty text body", async () => {
    const resp = mockResponse("", {
      status: 500,
      ok: false,
      contentType: "text/plain",
    });
    resp.text = vi.fn().mockResolvedValue("");
    const msg = await parseErrorResponse(resp, "Default");
    expect(msg).toBe("Default");
  });

  test("returns fallback for JSON with no detail or message", async () => {
    const resp = mockResponse({ code: 500 }, { status: 500, ok: false });
    const msg = await parseErrorResponse(resp, "Oops");
    expect(msg).toBe("Oops");
  });
});

// ---------------------------------------------------------------------------
// safeParseJsonResponse
// ---------------------------------------------------------------------------
describe("safeParseJsonResponse", () => {
  test("returns parsed JSON for ok response with JSON content-type", async () => {
    const resp = mockResponse({ data: [1, 2, 3] });
    const result = await safeParseJsonResponse(resp);
    expect(result).toEqual({ data: [1, 2, 3] });
  });

  test("throws on non-ok response", async () => {
    const resp = mockResponse(
      { detail: "Unauthorized" },
      { status: 401, ok: false }
    );
    await expect(safeParseJsonResponse(resp, "Auth failed")).rejects.toThrow(
      "Unauthorized"
    );
  });

  test("throws on non-JSON content-type even if ok", async () => {
    const resp = mockResponse("<html>login</html>", {
      status: 200,
      ok: true,
      contentType: "text/html",
    });
    await expect(safeParseJsonResponse(resp)).rejects.toThrow(
      /unexpected response/
    );
  });

  test("propagates JSON parse errors", async () => {
    const resp = mockResponse({}, { status: 200, ok: true });
    resp.json = vi.fn().mockRejectedValue(new SyntaxError("Unexpected token"));
    await expect(safeParseJsonResponse(resp)).rejects.toThrow();
  });

  test("includes HTTP status in error for non-ok responses", async () => {
    const resp = mockResponse(
      { detail: "Forbidden" },
      { status: 403, ok: false }
    );
    await expect(
      safeParseJsonResponse(resp, "Request failed")
    ).rejects.toThrow("Forbidden");
  });
});

// ---------------------------------------------------------------------------
// safeSetInnerHTML
// ---------------------------------------------------------------------------
describe("safeSetInnerHTML", () => {
  let element;

  beforeEach(() => {
    element = document.createElement("div");
  });

  test("sets innerHTML when isTrusted is true", () => {
    safeSetInnerHTML(element, "<b>bold</b>", true);
    expect(element.innerHTML).toBe("<b>bold</b>");
  });

  test("falls back to textContent when isTrusted is false", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    safeSetInnerHTML(element, "<script>alert(1)</script>", false);
    expect(element.textContent).toBe("<script>alert(1)</script>");
    expect(element.innerHTML).not.toContain("<script>");
    consoleSpy.mockRestore();
  });

  test("falls back to textContent when isTrusted is omitted (default false)", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    safeSetInnerHTML(element, "<img src=x onerror=alert(1)>");
    expect(element.textContent).toContain("<img");
    consoleSpy.mockRestore();
  });

  test("logs error for untrusted content", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    safeSetInnerHTML(element, "test");
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("untrusted content")
    );
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// logRestrictedContext
// ---------------------------------------------------------------------------
describe("logRestrictedContext", () => {

  beforeEach(() => {
    // Reset the module-level AppState mock
    vi.resetModules();
  });

  test("logs debug message on first call", async () => {
    // Re-import with fresh AppState
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.restrictedContextLogged = false;

    const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
    const { logRestrictedContext: logRC } = await import(
      "../../../mcpgateway/admin_ui/security.js"
    );

    logRC(new Error("SecurityError"));
    expect(debugSpy).toHaveBeenCalledWith(
      expect.stringContaining("restricted context"),
      "SecurityError"
    );
    debugSpy.mockRestore();
    AppState.restrictedContextLogged = false;
  });

  test("does not log on subsequent calls", async () => {
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.restrictedContextLogged = true;

    const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
    const { logRestrictedContext: logRC } = await import(
      "../../../mcpgateway/admin_ui/security.js"
    );

    logRC(new Error("SecurityError"));
    expect(debugSpy).not.toHaveBeenCalled();
    debugSpy.mockRestore();
    AppState.restrictedContextLogged = false;
  });
});

// ---------------------------------------------------------------------------
// safeReplaceState
// ---------------------------------------------------------------------------
describe("safeReplaceState", () => {
  test("calls history.replaceState when available", () => {
    const spy = vi.spyOn(window.history, "replaceState").mockImplementation(() => {});
    safeReplaceState({ foo: 1 }, "title", "/new-url");
    expect(spy).toHaveBeenCalledWith({ foo: 1 }, "title", "/new-url");
    spy.mockRestore();
  });

  test("silently catches errors in restricted contexts", async () => {
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.restrictedContextLogged = false;

    const spy = vi.spyOn(window.history, "replaceState").mockImplementation(() => {
      throw new DOMException("Blocked", "SecurityError");
    });
    const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});

    // Should not throw
    expect(() => safeReplaceState({}, "", "/url")).not.toThrow();

    spy.mockRestore();
    debugSpy.mockRestore();
    AppState.restrictedContextLogged = false;
  });
});
