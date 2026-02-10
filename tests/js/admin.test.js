/**
 * Unit tests for admin.js escapeHtml function.
 *
 * admin.js is a browser script (not an ES module), so functions are
 * accessed from the window object after executing the script in JSDOM.
 *
 * Coverage: admin.js is manually instrumented with istanbul before eval
 * so that coverage data flows back to Vitest's Istanbul reporter.
 */

import { describe, test, expect, beforeAll, afterAll } from "vitest";
import { createInstrumenter } from "istanbul-lib-instrument";
import fs from "fs";
import path from "path";
import { JSDOM } from "jsdom";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let dom;
let escapeHtml;

beforeAll(() => {
    const adminJsPath = path.resolve(
        __dirname,
        "../../mcpgateway/static/admin.js",
    );
    const adminJsContent = fs.readFileSync(adminJsPath, "utf8");

    // Instrument admin.js with Istanbul counters so coverage data is
    // collected when the script runs inside JSDOM's sandboxed context.
    const instrumenter = createInstrumenter({
        compact: false,
        esModules: false,
        coverageVariable: "__coverage__",
    });
    const instrumented = instrumenter.instrumentSync(
        adminJsContent,
        adminJsPath,
    );

    dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
        url: "http://localhost",
        runScripts: "outside-only",
    });

    // Suppress console noise from admin.js initialization
    dom.window.console = {
        ...dom.window.console,
        log: () => {},
        warn: () => {},
        error: () => {},
    };

    // Execute the instrumented script in JSDOM's sandbox.
    // admin.js is a non-modular browser script that attaches functions
    // to the window object — JSDOM eval is the standard way to load it.
    dom.window.eval(instrumented);
    escapeHtml = dom.window.escapeHtml;
});

afterAll(() => {
    // Copy Istanbul coverage data from JSDOM's sandbox into the
    // Node.js global where Vitest's Istanbul reporter collects it.
    const jsCoverage = dom.window.__coverage__;
    if (jsCoverage && typeof jsCoverage === "object") {
        const target = "__VITEST_COVERAGE__";
        if (!globalThis[target]) {
            globalThis[target] = {};
        }
        for (const [filePath, fileCov] of Object.entries(jsCoverage)) {
            globalThis[target][filePath] = fileCov;
        }
    }

    if (dom) {
        dom.window.close();
    }
});

describe("escapeHtml", () => {
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
