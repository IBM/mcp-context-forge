/**
 * Unit tests for admin.js escapeHtml function
 * Comprehensive test coverage including happy path and edge cases
 *
 * Note: admin.js is loaded as a browser script in jsdom environment.
 * Functions are accessed from the window object after script execution.
 */

import { describe, test, expect } from "vitest";
import fs from "fs";
import path from "path";
import { JSDOM } from "jsdom";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Load admin.js
const adminJsPath = path.join(__dirname, "../../mcpgateway/static/admin.js");
const adminJsContent = fs.readFileSync(adminJsPath, "utf8");

// Create minimal DOM and execute admin.js
const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    url: "http://localhost",
    runScripts: "outside-only",
});

// Mock console to reduce noise in test output
dom.window.console = {
    ...dom.window.console,
    log: () => {},
    warn: () => {},
    error: () => {},
};

dom.window.eval(adminJsContent);

describe("escapeHtml", () => {
    // Extract escapeHtml from the JSDOM window object
    const { escapeHtml } = dom.window;

    // Happy Path Tests
    describe("Happy Path", () => {
        test("should escape basic HTML tags", () => {
            expect(escapeHtml('<script>alert("XSS")</script>')).toBe(
                "&lt;script&gt;alert(&quot;XSS&quot;)&lt;&#x2F;script&gt;",
            );
        });

        test("should escape special characters", () => {
            expect(escapeHtml("'\"&`/")).toBe("&#039;&quot;&amp;&#x60;&#x2F;");
        });

        test("should return plain text unchanged", () => {
            expect(escapeHtml("Hello World")).toBe("Hello World");
        });
    });

    // Null and Undefined Tests
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

    // Type Coercion Tests
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

    // Edge Cases
    describe("Edge Cases", () => {
        test("should handle Unicode characters", () => {
            expect(escapeHtml("Hello 世界 🌍")).toBe("Hello 世界 🌍");
        });
    });
});
