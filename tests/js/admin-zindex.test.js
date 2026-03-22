/**
 * Tests for z-index hierarchy in admin UI elements.
 *
 * Verifies the stacking order:
 *   z-10  Sticky header / LLM toolbar
 *   z-20  Sidebar
 *   z-30  Dropdowns / tooltips
 *   z-40  Modals
 *   z-50  Toast notifications
 */

import {
    describe,
    test,
    expect,
    beforeAll,
    beforeEach,
    afterAll,
} from "vitest";
import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";

let win;
let doc;

beforeAll(() => {
    win = loadAdminJs();
    doc = win.document;
});

afterAll(() => {
    cleanupAdminJs();
});

beforeEach(() => {
    doc.body.textContent = "";
});

// ---------------------------------------------------------------------------
// Toast notifications must use z-50 (above modals at z-40)
// ---------------------------------------------------------------------------
describe("toast z-index hierarchy", () => {
    test("showErrorMessage creates toast with z-50", () => {
        win.showErrorMessage("error");
        const el = doc.querySelector(".fixed.bg-red-600");
        expect(el).not.toBeNull();
        expect(el.classList.contains("z-50")).toBe(true);
    });

    test("showSuccessMessage creates toast with z-50", () => {
        win.showSuccessMessage("success");
        const el = doc.querySelector(".fixed.bg-green-600");
        expect(el).not.toBeNull();
        expect(el.classList.contains("z-50")).toBe(true);
    });

    test("showNotification creates toast with z-50", () => {
        win.showNotification("info", "info");
        const el = doc.querySelector(".fixed.z-50");
        expect(el).not.toBeNull();
    });
});

// ---------------------------------------------------------------------------
// JS-created modals must use z-40 (below toasts, above dropdowns)
// ---------------------------------------------------------------------------
describe("modal z-index hierarchy", () => {
    test("showCopyableModal creates overlay with z-40", () => {
        win.showCopyableModal("Title", "message", "info");
        const overlay = doc.getElementById("copyable-modal-overlay");
        expect(overlay).not.toBeNull();
        expect(overlay.classList.contains("z-40")).toBe(true);
        expect(overlay.classList.contains("z-50")).toBe(false);
    });

    test("showTokenCreatedModal creates modal with z-40", () => {
        win.showTokenCreatedModal({ token: "tok_123", name: "test" });
        const modals = doc.querySelectorAll(".fixed.inset-0.z-40");
        expect(modals.length).toBeGreaterThan(0);
    });
});

// ---------------------------------------------------------------------------
// Status badge tooltips must use z-30 (below modals, above sidebar)
// ---------------------------------------------------------------------------
describe("status badge tooltip z-index hierarchy", () => {
    function parseBadgeHtml(html) {
        // Use DOMParser to safely parse the generated markup (test-only).
        const parsed = new win.DOMParser().parseFromString(html, "text/html");
        return parsed.body;
    }

    test("inactive badge tooltip uses z-30", () => {
        const body = parseBadgeHtml(
            win.generateStatusBadgeHtml(false, true, "gateway"),
        );
        const tooltip = body.querySelector(".group-hover\\:block");
        expect(tooltip).not.toBeNull();
        expect(tooltip.classList.contains("z-30")).toBe(true);
    });

    test("offline badge tooltip uses z-30", () => {
        const body = parseBadgeHtml(
            win.generateStatusBadgeHtml(true, false, "gateway"),
        );
        const tooltip = body.querySelector(".group-hover\\:block");
        expect(tooltip).not.toBeNull();
        expect(tooltip.classList.contains("z-30")).toBe(true);
    });

    test("active badge tooltip uses z-30", () => {
        const body = parseBadgeHtml(
            win.generateStatusBadgeHtml(true, true, "gateway"),
        );
        const tooltip = body.querySelector(".group-hover\\:block");
        expect(tooltip).not.toBeNull();
        expect(tooltip.classList.contains("z-30")).toBe(true);
    });
});
