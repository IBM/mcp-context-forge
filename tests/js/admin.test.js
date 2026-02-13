/**
 * Unit tests for escapeHtml function.
 * Tests pure function - no DOM required.
 */

import { describe, test, expect } from "vitest";
import { escapeHtml } from "../../mcpgateway/admin_ui/security.js";

describe("escapeHtml", () => {
  describe("Happy Path", () => {
    test("should escape basic HTML tags", () => {
      expect(escapeHtml('<script>alert("XSS")</script>')).toBe(
        "&lt;script&gt;alert(&quot;XSS&quot;)&lt;&#x2F;script&gt;"
      );
    });

    test("should escape special characters", () => {
      expect(escapeHtml("'\"&`/")).toBe("&#039;&quot;&amp;&#x60;&#x2F;");
    });

    test("should return plain text unchanged", () => {
      expect(escapeHtml("Hello World")).toBe("Hello World");
    });
  });

  describe("Null, Undefined and Empty Strings Handling", () => {
    test("should return empty string for null and undefined", () => {
      expect(escapeHtml(null)).toBe("");
      expect(escapeHtml(undefined)).toBe("");
    });

    test("should return empty string for empty input", () => {
      expect(escapeHtml("")).toBe("");
    });

    test("should preserve whitespace-only strings", () => {
      expect(escapeHtml("   ")).toBe("   ");
      expect(escapeHtml("\t")).toBe("\t");
      expect(escapeHtml("\n")).toBe("\n");
    });
  });

  describe("Type Coercion", () => {
    test("should convert numbers to strings", () => {
      expect(escapeHtml(123)).toBe("123");
      expect(escapeHtml(0)).toBe("0");
      expect(escapeHtml(-456)).toBe("-456");
    });

    test("should convert booleans to strings", () => {
      expect(escapeHtml(true)).toBe("true");
      expect(escapeHtml(false)).toBe("false");
    });

    test("should handle NaN", () => {
      expect(escapeHtml(NaN)).toBe("NaN");
    });

    test("should handle Infinity", () => {
      expect(escapeHtml(Infinity)).toBe("Infinity");
      expect(escapeHtml(-Infinity)).toBe("-Infinity");
    });

    test("should convert objects to strings", () => {
      expect(escapeHtml({})).toBe("[object Object]");
      expect(escapeHtml({ key: "value" })).toBe("[object Object]");
    });

    test("should convert arrays to strings", () => {
      expect(escapeHtml([1, 2, 3])).toBe("1,2,3");
      expect(escapeHtml(["<", ">"])).toBe("&lt;,&gt;");
    });
  });

  describe("Edge Cases", () => {
    test("should handle Unicode characters", () => {
      expect(escapeHtml("Hello 世界 🌍")).toBe("Hello 世界 🌍");
    });
  });
});
