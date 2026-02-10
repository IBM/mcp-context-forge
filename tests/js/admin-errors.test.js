/**
 * Unit tests for admin.js error handling functions.
 */

import { describe, test, expect, beforeAll, afterAll } from "vitest";
import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";

let win;

beforeAll(() => {
    win = loadAdminJs();
});

afterAll(() => {
    cleanupAdminJs();
});

// ---------------------------------------------------------------------------
// handleFetchError
// ---------------------------------------------------------------------------
describe("handleFetchError", () => {
    const f = () => win.handleFetchError;

    test("returns timeout message for AbortError", () => {
        const error = new Error("The operation was aborted");
        error.name = "AbortError";
        const result = f()(error, "fetch data");
        expect(result).toContain("timed out");
        expect(result).toContain("fetch data");
    });

    test("returns server error message for HTTP errors", () => {
        const error = new Error("HTTP 500 Internal Server Error");
        const result = f()(error, "save settings");
        expect(result).toContain("Server error");
        expect(result).toContain("save settings");
        expect(result).toContain("HTTP 500");
    });

    test("returns network error message for NetworkError", () => {
        const error = new Error("NetworkError when attempting to fetch");
        const result = f()(error, "load data");
        expect(result).toContain("Network error");
        expect(result).toContain("load data");
    });

    test("returns network error message for Failed to fetch", () => {
        const error = new Error("Failed to fetch");
        const result = f()(error, "connect");
        expect(result).toContain("Network error");
        expect(result).toContain("connect");
    });

    test("returns generic error for unknown errors", () => {
        const error = new Error("Something unexpected");
        const result = f()(error, "process");
        expect(result).toContain("Failed to process");
        expect(result).toContain("Something unexpected");
    });

    test("uses default operation name", () => {
        const error = new Error("Something unexpected");
        const result = f()(error);
        expect(result).toContain("operation");
    });

    test("handles AbortError with default operation", () => {
        const error = new Error("aborted");
        error.name = "AbortError";
        const result = f()(error);
        expect(result).toContain("timed out");
        expect(result).toContain("operation");
    });
});
