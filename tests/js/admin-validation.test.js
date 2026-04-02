/**
 * Unit tests for validation functions.
 * Tests pure functions - no DOM required.
 */

import { describe, test, expect } from "vitest";
import {
  validatePassthroughHeader,
  validateInputName,
  validateUrl,
  validateJson,
} from "../../mcpgateway/admin_ui/security.js";
import { isValidBase64 } from "../../mcpgateway/admin_ui/utils.js";

// Note: isValidIpOrCidr, isValidPermission, isValidCertificate are still in static/admin.js
// They need to be extracted to a module first

// ---------------------------------------------------------------------------
// validatePassthroughHeader
// ---------------------------------------------------------------------------
describe("validatePassthroughHeader", () => {
  test("accepts valid header name and value", () => {
    expect(
      validatePassthroughHeader("Content-Type", "application/json")
    ).toEqual({
      valid: true,
    });
  });

  test("accepts header with empty value", () => {
    expect(validatePassthroughHeader("X-Custom", "")).toEqual({ valid: true });
  });

  test("rejects header name with spaces", () => {
    const result = validatePassthroughHeader("Bad Header", "value");
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/invalid characters/);
  });

  test("rejects header name with underscore", () => {
    const result = validatePassthroughHeader("bad_header", "value");
    expect(result.valid).toBe(false);
  });

  test("rejects header name with colon", () => {
    const result = validatePassthroughHeader("Host:", "value");
    expect(result.valid).toBe(false);
  });

  test("rejects value with newline (CRLF injection)", () => {
    const result = validatePassthroughHeader(
      "X-Custom",
      "val\r\nEvil: injected"
    );
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/newline/);
  });

  test("rejects value with bare newline", () => {
    const result = validatePassthroughHeader("X-Custom", "val\nEvil");
    expect(result.valid).toBe(false);
  });

  test("rejects value with bare carriage return", () => {
    const result = validatePassthroughHeader("X-Custom", "val\rEvil");
    expect(result.valid).toBe(false);
  });

  test("rejects value exceeding max length", () => {
    const longValue = "x".repeat(5000);
    const result = validatePassthroughHeader("X-Custom", longValue);
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/too long/);
  });

  test("accepts value at exactly max length (4096)", () => {
    const exactValue = "x".repeat(4096);
    expect(validatePassthroughHeader("X-Custom", exactValue)).toEqual({
      valid: true,
    });
  });

  test("rejects value with control characters (NUL)", () => {
    const result = validatePassthroughHeader("X-Custom", "val\x00ue");
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/control characters/);
  });

  test("allows tab in value", () => {
    expect(validatePassthroughHeader("X-Custom", "val\tue")).toEqual({
      valid: true,
    });
  });

  test("accepts numeric header name", () => {
    expect(validatePassthroughHeader("123", "value")).toEqual({ valid: true });
  });
});

// ---------------------------------------------------------------------------
// validateInputName
// ---------------------------------------------------------------------------
describe("validateInputName", () => {
  test("accepts simple name", () => {
    const result = validateInputName("my-tool");
    expect(result.valid).toBe(true);
    expect(result.value).toBe("my-tool");
  });

  test("rejects null", () => {
    const result = validateInputName(null);
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/required/);
  });

  test("rejects undefined", () => {
    const result = validateInputName(undefined);
    expect(result.valid).toBe(false);
  });

  test("rejects empty string", () => {
    const result = validateInputName("");
    expect(result.valid).toBe(false);
  });

  test("rejects non-string (number)", () => {
    const result = validateInputName(123);
    expect(result.valid).toBe(false);
  });

  test("strips HTML tags and validates cleaned result", () => {
    const result = validateInputName("my<b>tool</b>");
    expect(result.valid).toBe(true);
    expect(result.value).toBe("mytool");
  });

  test("rejects script tag injection", () => {
    const result = validateInputName('<script>alert("xss")</script>');
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/invalid characters/);
  });

  test("rejects javascript: protocol", () => {
    const result = validateInputName("javascript:alert(1)");
    expect(result.valid).toBe(false);
  });

  test("rejects event handler injection", () => {
    const result = validateInputName('onerror=alert("xss")');
    expect(result.valid).toBe(false);
  });

  test("rejects data:text/html", () => {
    const result = validateInputName("data:text/html,<h1>hi</h1>");
    expect(result.valid).toBe(false);
  });

  test("rejects vbscript:", () => {
    const result = validateInputName("vbscript:MsgBox");
    expect(result.valid).toBe(false);
  });

  test("uses custom type label in error messages", () => {
    const result = validateInputName(null, "Server name");
    expect(result.error).toMatch(/Server name/);
  });

  test("rejects name exceeding MAX_NAME_LENGTH", () => {
    const long = "a".repeat(256);
    const result = validateInputName(long);
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/255 characters or less/);
  });

  test("accepts name at exactly MAX_NAME_LENGTH", () => {
    const exact = "a".repeat(255);
    const result = validateInputName(exact);
    expect(result.valid).toBe(true);
  });

  test("prompt type rejects special characters", () => {
    const result = validateInputName("my.prompt!", "prompt");
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/letters, numbers/);
  });

  test("prompt type accepts valid prompt name", () => {
    const result = validateInputName("my-prompt_v2", "prompt");
    expect(result.valid).toBe(true);
  });

  test("prompt type allows spaces", () => {
    const result = validateInputName("My Prompt Name", "prompt");
    expect(result.valid).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// validateUrl
// ---------------------------------------------------------------------------
describe("validateUrl", () => {
  test("accepts valid HTTP URL", () => {
    const result = validateUrl("http://example.com");
    expect(result.valid).toBe(true);
    expect(result.value).toBe("http://example.com");
  });

  test("accepts valid HTTPS URL", () => {
    const result = validateUrl("https://example.com/path?q=1");
    expect(result.valid).toBe(true);
  });

  test("rejects null", () => {
    const result = validateUrl(null);
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/required/);
  });

  test("rejects empty string", () => {
    const result = validateUrl("");
    expect(result.valid).toBe(false);
  });

  test("rejects non-string", () => {
    const result = validateUrl(123);
    expect(result.valid).toBe(false);
  });

  test("rejects ftp:// protocol", () => {
    const result = validateUrl("ftp://example.com");
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/HTTP and HTTPS/);
  });

  test("rejects javascript: protocol", () => {
    const result = validateUrl("javascript:alert(1)");
    expect(result.valid).toBe(false);
  });

  test("rejects malformed URL", () => {
    const result = validateUrl("not a url");
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/Invalid URL/);
  });

  test("uses custom label in error", () => {
    const result = validateUrl(null, "Gateway URL");
    expect(result.error).toMatch(/Gateway URL/);
  });

  test("uses default 'URL' label when no label given", () => {
    const result = validateUrl(null);
    expect(result.error).toMatch(/URL/);
  });
});

// ---------------------------------------------------------------------------
// validateJson
// ---------------------------------------------------------------------------
describe("validateJson", () => {
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

  test("returns empty object for null input", () => {
    const result = validateJson(null);
    expect(result.valid).toBe(true);
    expect(result.value).toEqual({});
  });

  test("returns empty object for empty string", () => {
    const result = validateJson("");
    expect(result.valid).toBe(true);
    expect(result.value).toEqual({});
  });

  test("returns empty object for whitespace-only string", () => {
    const result = validateJson("   ");
    expect(result.valid).toBe(true);
    expect(result.value).toEqual({});
  });

  test("rejects invalid JSON", () => {
    const result = validateJson("{invalid}");
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/Invalid JSON format/);
  });

  test("uses custom field name in error", () => {
    const result = validateJson("{bad}", "Headers");
    expect(result.error).toMatch(/Headers/);
  });

  test("handles nested JSON", () => {
    const result = validateJson('{"a": {"b": [1, 2]}}');
    expect(result.valid).toBe(true);
    expect(result.value.a.b).toEqual([1, 2]);
  });
});

// ---------------------------------------------------------------------------
// isValidBase64
// ---------------------------------------------------------------------------
describe("isValidBase64", () => {
  test("accepts valid base64 string", () => {
    expect(isValidBase64("SGVsbG8gV29ybGQ=")).toBe(true);
  });

  test("accepts base64 without padding", () => {
    expect(isValidBase64("SGVsbG8")).toBe(true);
  });

  test("accepts base64 with double padding", () => {
    expect(isValidBase64("SGVsbA==")).toBe(true);
  });

  test("rejects empty string", () => {
    expect(isValidBase64("")).toBe(false);
  });

  test("rejects string with spaces", () => {
    expect(isValidBase64("SGVs bG8=")).toBe(false);
  });

  test("rejects string with special characters", () => {
    expect(isValidBase64("SGVsbG8!")).toBe(false);
  });

  test("accepts base64 with + and /", () => {
    expect(isValidBase64("ab+cd/ef==")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// TODO: Extract these functions from static/admin.js to modules
// ---------------------------------------------------------------------------
// - isValidIpOrCidr
// - isValidPermission
// - isValidCertificate
