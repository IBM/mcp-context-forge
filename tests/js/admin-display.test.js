/**
 * Unit tests for admin.js display/UI utility functions.
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
// getLogLevelClass
// ---------------------------------------------------------------------------
describe("getLogLevelClass", () => {
    const f = () => win.getLogLevelClass;

    test("returns correct class for DEBUG", () => {
        expect(f()("DEBUG")).toContain("bg-gray");
    });

    test("returns correct class for INFO", () => {
        expect(f()("INFO")).toContain("bg-blue");
    });

    test("returns correct class for WARNING", () => {
        expect(f()("WARNING")).toContain("bg-yellow");
    });

    test("returns correct class for ERROR", () => {
        expect(f()("ERROR")).toContain("bg-red");
    });

    test("returns correct class for CRITICAL", () => {
        expect(f()("CRITICAL")).toContain("bg-purple");
    });

    test("returns INFO class as default for unknown level", () => {
        expect(f()("UNKNOWN")).toContain("bg-blue");
    });

    test("returns INFO class for undefined level", () => {
        expect(f()(undefined)).toContain("bg-blue");
    });
});

// ---------------------------------------------------------------------------
// getSeverityClass
// ---------------------------------------------------------------------------
describe("getSeverityClass", () => {
    const f = () => win.getSeverityClass;

    test("returns correct class for LOW", () => {
        expect(f()("LOW")).toContain("bg-blue");
    });

    test("returns correct class for MEDIUM", () => {
        expect(f()("MEDIUM")).toContain("bg-yellow");
    });

    test("returns correct class for HIGH", () => {
        expect(f()("HIGH")).toContain("bg-orange");
    });

    test("returns correct class for CRITICAL", () => {
        expect(f()("CRITICAL")).toContain("bg-red");
    });

    test("returns MEDIUM class as default for unknown severity", () => {
        expect(f()("UNKNOWN")).toContain("bg-yellow");
    });
});

// ---------------------------------------------------------------------------
// generateStatusBadgeHtml
// ---------------------------------------------------------------------------
describe("generateStatusBadgeHtml", () => {
    const f = () => win.generateStatusBadgeHtml;

    test("returns Inactive badge when not enabled", () => {
        const html = f()(false, true, "server");
        expect(html).toContain("Inactive");
        expect(html).toContain("bg-red");
        expect(html).toContain("Server is Manually Deactivated");
    });

    test("returns Offline badge when enabled but not reachable", () => {
        const html = f()(true, false, "gateway");
        expect(html).toContain("Offline");
        expect(html).toContain("bg-yellow");
        expect(html).toContain("Gateway is Not Reachable");
    });

    test("returns Active badge when enabled and reachable", () => {
        const html = f()(true, true, "tool");
        expect(html).toContain("Active");
        expect(html).toContain("bg-green");
        expect(html).toContain("Tool is Active");
    });

    test("capitalizes typeLabel", () => {
        const html = f()(true, true, "resource");
        expect(html).toContain("Resource is Active");
    });

    test("uses 'Item' as default when no typeLabel", () => {
        const html = f()(false, false, null);
        expect(html).toContain("Item is Manually Deactivated");
    });

    test("uses 'Item' for undefined typeLabel", () => {
        const html = f()(false, false, undefined);
        expect(html).toContain("Item is Manually Deactivated");
    });

    test("Inactive takes priority over Offline (disabled + unreachable)", () => {
        const html = f()(false, false, "server");
        expect(html).toContain("Inactive");
        expect(html).not.toContain("Offline");
    });
});

// ---------------------------------------------------------------------------
// calculateSuccessRate
// ---------------------------------------------------------------------------
describe("calculateSuccessRate", () => {
    const f = () => win.calculateSuccessRate;

    test("returns successRate directly when available", () => {
        expect(f()({ successRate: 95.7 })).toBe(96);
    });

    test("rounds successRate to nearest integer", () => {
        expect(f()({ successRate: 99.4 })).toBe(99);
    });

    test("returns 0 for successRate = 0", () => {
        expect(f()({ successRate: 0 })).toBe(0);
    });

    test("computes from execution_count and successful_count (legacy)", () => {
        expect(
            f()({ execution_count: 100, successful_count: 85 }),
        ).toBe(85);
    });

    test("computes from executions and successfulExecutions", () => {
        expect(
            f()({ executions: 200, successfulExecutions: 150 }),
        ).toBe(75);
    });

    test("returns 0 when total is 0", () => {
        expect(f()({ execution_count: 0, successful_count: 0 })).toBe(0);
    });

    test("returns 0 for empty object", () => {
        expect(f()({})).toBe(0);
    });
});

// ---------------------------------------------------------------------------
// isAdminOnlyTab
// ---------------------------------------------------------------------------
describe("isAdminOnlyTab", () => {
    const f = () => win.isAdminOnlyTab;

    test("returns true for users tab", () => {
        expect(f()("users")).toBe(true);
    });

    test("returns true for metrics tab", () => {
        expect(f()("metrics")).toBe(true);
    });

    test("returns true for performance tab", () => {
        expect(f()("performance")).toBe(true);
    });

    test("returns true for observability tab", () => {
        expect(f()("observability")).toBe(true);
    });

    test("returns true for plugins tab", () => {
        expect(f()("plugins")).toBe(true);
    });

    test("returns true for logs tab", () => {
        expect(f()("logs")).toBe(true);
    });

    test("returns true for export-import tab", () => {
        expect(f()("export-import")).toBe(true);
    });

    test("returns true for version-info tab", () => {
        expect(f()("version-info")).toBe(true);
    });

    test("returns true for maintenance tab", () => {
        expect(f()("maintenance")).toBe(true);
    });

    test("returns false for gateways tab", () => {
        expect(f()("gateways")).toBe(false);
    });

    test("returns false for tools tab", () => {
        expect(f()("tools")).toBe(false);
    });

    test("returns false for overview tab", () => {
        expect(f()("overview")).toBe(false);
    });

    test("returns false for undefined", () => {
        expect(f()(undefined)).toBe(false);
    });
});
