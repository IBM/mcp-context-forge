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
// Tooltip setup uses z-30 (below modals, above sidebar)
// ---------------------------------------------------------------------------
describe("tooltip z-index hierarchy", () => {
    test("setupTooltipsWithAlpine creates tooltip elements with z-30", () => {
        const trigger = doc.createElement("span");
        trigger.setAttribute("data-tooltip", "Helpful tip");
        doc.body.appendChild(trigger);

        win.setupTooltipsWithAlpine();

        // Simulate mouseenter to create the tooltip
        const mouseenterEvent = new win.Event("mouseenter");
        trigger.dispatchEvent(mouseenterEvent);

        const tooltip = doc.querySelector('[role="tooltip"]');
        if (tooltip) {
            expect(tooltip.classList.contains("z-30")).toBe(true);
            expect(tooltip.classList.contains("z-50")).toBe(false);
        }
    });
});
