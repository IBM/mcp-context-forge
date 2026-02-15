/**
 * Unit tests for admin.js config/state lookup functions.
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
// isAdminUser
// ---------------------------------------------------------------------------
describe("isAdminUser", () => {
    const f = () => win.isAdminUser;

    test("returns true when IS_ADMIN is true", () => {
        win.IS_ADMIN = true;
        expect(f()()).toBe(true);
    });

    test("returns true when IS_ADMIN is truthy string", () => {
        win.IS_ADMIN = "yes";
        expect(f()()).toBe(true);
    });

    test("returns false when IS_ADMIN is false", () => {
        win.IS_ADMIN = false;
        expect(f()()).toBe(false);
    });

    test("returns false when IS_ADMIN is undefined", () => {
        win.IS_ADMIN = undefined;
        expect(f()()).toBe(false);
    });

    test("returns false when IS_ADMIN is null", () => {
        win.IS_ADMIN = null;
        expect(f()()).toBe(false);
    });

    test("returns false when IS_ADMIN is 0", () => {
        win.IS_ADMIN = 0;
        expect(f()()).toBe(false);
    });

    test("returns false when IS_ADMIN is empty string", () => {
        win.IS_ADMIN = "";
        expect(f()()).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// getRootPath
// ---------------------------------------------------------------------------
describe("getRootPath", () => {
    const f = () => win.getRootPath;

    test("returns ROOT_PATH when set", () => {
        win.ROOT_PATH = "/gateway";
        expect(f()()).toBe("/gateway");
    });

    test("returns empty string when ROOT_PATH is undefined", () => {
        win.ROOT_PATH = undefined;
        expect(f()()).toBe("");
    });

    test("returns empty string when ROOT_PATH is null", () => {
        win.ROOT_PATH = null;
        expect(f()()).toBe("");
    });

    test("returns empty string when ROOT_PATH is empty", () => {
        win.ROOT_PATH = "";
        expect(f()()).toBe("");
    });
});

// ---------------------------------------------------------------------------
// getAuthenticatedUserId
// ---------------------------------------------------------------------------
describe("getAuthenticatedUserId", () => {
    const f = () => win.getAuthenticatedUserId;

    test("returns empty string when CURRENT_USER is undefined", () => {
        win.CURRENT_USER = undefined;
        expect(f()()).toBe("");
    });

    test("returns empty string when CURRENT_USER is null", () => {
        win.CURRENT_USER = null;
        expect(f()()).toBe("");
    });

    test("returns string when CURRENT_USER is a string", () => {
        win.CURRENT_USER = "admin@example.com";
        expect(f()()).toBe("admin@example.com");
    });

    test("extracts id from object", () => {
        win.CURRENT_USER = { id: "user-123" };
        expect(f()()).toBe("user-123");
    });

    test("extracts user_id from object", () => {
        win.CURRENT_USER = { user_id: "u456" };
        expect(f()()).toBe("u456");
    });

    test("extracts sub from object", () => {
        win.CURRENT_USER = { sub: "subject-789" };
        expect(f()()).toBe("subject-789");
    });

    test("extracts email from object", () => {
        win.CURRENT_USER = { email: "user@test.com" };
        expect(f()()).toBe("user@test.com");
    });

    test("prefers id over user_id over sub over email", () => {
        win.CURRENT_USER = {
            id: "id-1",
            user_id: "uid-2",
            sub: "sub-3",
            email: "e@x.com",
        };
        expect(f()()).toBe("id-1");
    });

    test("returns empty string for empty object", () => {
        win.CURRENT_USER = {};
        expect(f()()).toBe("");
    });
});

// ---------------------------------------------------------------------------
// getPerformanceAggregationConfig / Label / Query
// ---------------------------------------------------------------------------
describe("getPerformanceAggregationConfig", () => {
    const config = () => win.getPerformanceAggregationConfig;
    const label = () => win.getPerformanceAggregationLabel;
    const query = () => win.getPerformanceAggregationQuery;

    test('returns 5m config by default', () => {
        const result = config()("5m");
        expect(result).toEqual({
            label: "5-minute aggregation",
            query: "5m",
        });
    });

    test('returns 24h config', () => {
        const result = config()("24h");
        expect(result).toEqual({
            label: "24-hour aggregation",
            query: "24h",
        });
    });

    test('falls back to 5m for unknown key', () => {
        const result = config()("unknown");
        expect(result).toEqual({
            label: "5-minute aggregation",
            query: "5m",
        });
    });

    test('getPerformanceAggregationLabel returns label for 5m', () => {
        expect(label()("5m")).toBe("5-minute aggregation");
    });

    test('getPerformanceAggregationLabel returns label for 24h', () => {
        expect(label()("24h")).toBe("24-hour aggregation");
    });

    test('getPerformanceAggregationQuery returns query for 5m', () => {
        expect(query()("5m")).toBe("5m");
    });

    test('getPerformanceAggregationQuery returns query for 24h', () => {
        expect(query()("24h")).toBe("24h");
    });
});
