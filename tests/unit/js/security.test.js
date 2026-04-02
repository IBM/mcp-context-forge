/**
 * Unit tests for security.js module
 * Tests: parseErrorResponse, safeParseJsonResponse, safeSetInnerHTML,
 *        logRestrictedContext, safeReplaceState
 * (escapeHtml, extractApiError, escapeHtmlChat, validatePassthroughHeader,
 *  validateInputName, validateUrl, validateJson are already tested in tests/js/)
 */

import { describe, test, expect, vi, beforeEach } from "vitest";
import {
  escapeHtml,
  escapeHtmlChat,
  extractApiError,
  hasUnsafeUrlProtocol,
  parseErrorResponse,
  safeParseJsonResponse,
  safeSetInnerHTML,
  safeReplaceState,
  sanitizeHtmlForInsertion,
  validateJson,
  validatePassthroughHeader,
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
// escapeHtml
// ---------------------------------------------------------------------------
describe("escapeHtml", () => {
  test("returns empty string for null", () => {
    expect(escapeHtml(null)).toBe("");
  });

  test("returns empty string for undefined", () => {
    expect(escapeHtml(undefined)).toBe("");
  });

  test("escapes ampersand", () => {
    expect(escapeHtml("a & b")).toBe("a &amp; b");
  });

  test("escapes less-than", () => {
    expect(escapeHtml("<div>")).toBe("&lt;div&gt;");
  });

  test("escapes double quotes", () => {
    expect(escapeHtml('"quoted"')).toBe("&quot;quoted&quot;");
  });

  test("escapes single quotes", () => {
    expect(escapeHtml("it's")).toBe("it&#039;s");
  });

  test("escapes backtick", () => {
    expect(escapeHtml("`cmd`")).toBe("&#x60;cmd&#x60;");
  });

  test("escapes forward slash", () => {
    expect(escapeHtml("a/b")).toBe("a&#x2F;b");
  });

  test("escapes XSS script tag payload", () => {
    const result = escapeHtml("<script>alert(1)</script>");
    expect(result).not.toContain("<script>");
    expect(result).toContain("&lt;script&gt;");
  });

  test("converts non-string values to string", () => {
    expect(escapeHtml(42)).toBe("42");
    expect(escapeHtml(true)).toBe("true");
  });

  test("returns plain text unchanged", () => {
    expect(escapeHtml("hello world")).toBe("hello world");
  });
});

// ---------------------------------------------------------------------------
// escapeHtmlChat
// ---------------------------------------------------------------------------
describe("escapeHtmlChat", () => {
  test("escapes HTML tags", () => {
    const result = escapeHtmlChat("<script>alert(1)</script>");
    expect(result).not.toContain("<script>");
    expect(result).toContain("&lt;script&gt;");
  });

  test("escapes ampersand", () => {
    expect(escapeHtmlChat("a & b")).toBe("a &amp; b");
  });

  test("leaves plain text unchanged", () => {
    expect(escapeHtmlChat("hello")).toBe("hello");
  });

  test("preserves double quotes (textContent path does not encode them)", () => {
    expect(escapeHtmlChat('"hello"')).toBe('"hello"');
  });
});

// ---------------------------------------------------------------------------
// extractApiError
// ---------------------------------------------------------------------------
describe("extractApiError", () => {
  test("returns fallback for null input", () => {
    expect(extractApiError(null)).toBe("An error occurred");
  });

  test("returns fallback for empty object", () => {
    expect(extractApiError({ code: 500 }, "Oops")).toBe("Oops");
  });

  test("returns message field when present", () => {
    expect(extractApiError({ message: "Bad input" })).toBe("Bad input");
  });

  test("returns string detail", () => {
    expect(extractApiError({ detail: "Not found" })).toBe("Not found");
  });

  test("joins Pydantic validation error array with msg field", () => {
    const error = { detail: [{ msg: "field required" }, { msg: "invalid type" }] };
    expect(extractApiError(error)).toBe("field required; invalid type");
  });

  test("JSON-stringifies array items without msg", () => {
    const error = { detail: [{ loc: ["body"], type: "missing" }] };
    const result = extractApiError(error);
    expect(result).toContain("missing");
  });

  test("prefers message over detail", () => {
    const error = { message: "msg wins", detail: "detail loses" };
    expect(extractApiError(error)).toBe("msg wins");
  });

  test("uses custom fallback", () => {
    expect(extractApiError({}, "Custom fallback")).toBe("Custom fallback");
  });
});

// ---------------------------------------------------------------------------
// validatePassthroughHeader
// ---------------------------------------------------------------------------
describe("validatePassthroughHeader", () => {
  test("accepts valid header name and value", () => {
    const result = validatePassthroughHeader("X-Custom-Header", "value");
    expect(result.valid).toBe(true);
  });

  test("rejects header name with spaces", () => {
    const result = validatePassthroughHeader("X Custom Header", "value");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("invalid characters");
  });

  test("rejects header name with special characters", () => {
    const result = validatePassthroughHeader("X-Header!", "value");
    expect(result.valid).toBe(false);
  });

  test("rejects value with newline", () => {
    const result = validatePassthroughHeader("X-Header", "val\nue");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("newline");
  });

  test("rejects value with carriage return", () => {
    const result = validatePassthroughHeader("X-Header", "val\rue");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("newline");
  });

  test("rejects value exceeding max length", () => {
    const result = validatePassthroughHeader("X-Header", "a".repeat(4097));
    expect(result.valid).toBe(false);
    expect(result.error).toContain("too long");
  });

  test("rejects value with control characters", () => {
    const result = validatePassthroughHeader("X-Header", "val\x01ue");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("control characters");
  });

  test("allows tab character in value", () => {
    const result = validatePassthroughHeader("X-Header", "val\tue");
    expect(result.valid).toBe(true);
  });

  test("accepts value at exactly max length", () => {
    const result = validatePassthroughHeader("X-Header", "a".repeat(4096));
    expect(result.valid).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// validateJson
// ---------------------------------------------------------------------------
describe("validateJson", () => {
  test("returns valid empty object for empty string", () => {
    const result = validateJson("");
    expect(result.valid).toBe(true);
    expect(result.value).toEqual({});
  });

  test("returns valid empty object for whitespace-only input", () => {
    const result = validateJson("   ");
    expect(result.valid).toBe(true);
    expect(result.value).toEqual({});
  });

  test("parses valid JSON object", () => {
    const result = validateJson('{"key": "value"}');
    expect(result.valid).toBe(true);
    expect(result.value).toEqual({ key: "value" });
  });

  test("parses valid JSON array", () => {
    const result = validateJson("[1, 2, 3]");
    expect(result.valid).toBe(true);
    expect(result.value).toEqual([1, 2, 3]);
  });

  test("returns error for invalid JSON", () => {
    const result = validateJson("{not valid json}");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("Invalid");
  });

  test("includes field name in error message", () => {
    const result = validateJson("bad", "Config");
    expect(result.error).toContain("Config");
  });

  test("handles null input", () => {
    const result = validateJson(null);
    expect(result.valid).toBe(true);
    expect(result.value).toEqual({});
  });
});

// ---------------------------------------------------------------------------
// hasUnsafeUrlProtocol
// ---------------------------------------------------------------------------
describe("hasUnsafeUrlProtocol", () => {
  test("detects javascript: protocol", () => {
    expect(hasUnsafeUrlProtocol("javascript:alert(1)")).toBe(true);
  });

  test("detects javascript: with mixed case", () => {
    expect(hasUnsafeUrlProtocol("JavaScript:alert(1)")).toBe(true);
  });

  test("detects javascript: with leading whitespace", () => {
    expect(hasUnsafeUrlProtocol("  javascript:alert(1)")).toBe(true);
  });

  test("detects vbscript: protocol", () => {
    expect(hasUnsafeUrlProtocol("vbscript:msgbox(1)")).toBe(true);
  });

  test("detects data:text/html", () => {
    expect(hasUnsafeUrlProtocol("data:text/html,<h1>hi</h1>")).toBe(true);
  });

  test("returns false for http:", () => {
    expect(hasUnsafeUrlProtocol("http://example.com")).toBe(false);
  });

  test("returns false for https:", () => {
    expect(hasUnsafeUrlProtocol("https://example.com")).toBe(false);
  });

  test("returns false for relative URL", () => {
    expect(hasUnsafeUrlProtocol("/admin/page")).toBe(false);
  });

  test("returns false for non-string input", () => {
    expect(hasUnsafeUrlProtocol(42)).toBe(false);
    expect(hasUnsafeUrlProtocol(null)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// sanitizeHtmlForInsertion
// ---------------------------------------------------------------------------
describe("sanitizeHtmlForInsertion", () => {
  test("returns empty string for null", () => {
    expect(sanitizeHtmlForInsertion(null)).toBe("");
  });

  test("returns empty string for undefined", () => {
    expect(sanitizeHtmlForInsertion(undefined)).toBe("");
  });

  test("preserves safe HTML tags", () => {
    const result = sanitizeHtmlForInsertion("<b>bold</b><p>text</p>");
    expect(result).toContain("<b>bold</b>");
  });

  test("removes script tags", () => {
    const result = sanitizeHtmlForInsertion("<script>alert(1)</script><p>hi</p>");
    expect(result).not.toContain("<script>");
    expect(result).toContain("<p>hi</p>");
  });

  test("removes inline event handlers", () => {
    const result = sanitizeHtmlForInsertion('<img src="x" onerror="alert(1)">');
    expect(result).not.toContain("onerror");
  });

  test("removes javascript: href", () => {
    const result = sanitizeHtmlForInsertion('<a href="javascript:alert(1)">click</a>');
    expect(result).not.toContain("javascript:");
  });

  test("removes javascript: src", () => {
    const result = sanitizeHtmlForInsertion('<img src="javascript:alert(1)">');
    expect(result).not.toContain("javascript:");
  });

  test("removes iframe elements", () => {
    const result = sanitizeHtmlForInsertion('<iframe src="evil.com"></iframe>');
    expect(result).not.toContain("<iframe");
  });

  test("preserves plain text", () => {
    expect(sanitizeHtmlForInsertion("hello world")).toBe("hello world");
  });
});

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
