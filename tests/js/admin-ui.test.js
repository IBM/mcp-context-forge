/**
 * Unit tests for admin.js notification, password, and selection functions.
 */

import { describe, test, expect, beforeAll, beforeEach, afterAll } from "vitest";
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
// showErrorMessage
// ---------------------------------------------------------------------------
describe("showErrorMessage", () => {
    const f = () => win.showErrorMessage;

    test("creates global error div when no elementId", () => {
        f()("Something went wrong");
        const errorDiv = doc.querySelector(".fixed.bg-red-600");
        expect(errorDiv).not.toBeNull();
        expect(errorDiv.textContent).toBe("Something went wrong");
    });

    test("sets text on target element when elementId provided", () => {
        const el = doc.createElement("div");
        el.id = "my-error";
        doc.body.appendChild(el);

        f()("Field is required", "my-error");
        expect(el.textContent).toBe("Field is required");
        expect(el.classList.contains("text-red-600")).toBe(true);
    });

    test("does not throw when elementId does not exist", () => {
        expect(() => f()("err", "nonexistent-id")).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// showSuccessMessage
// ---------------------------------------------------------------------------
describe("showSuccessMessage", () => {
    const f = () => win.showSuccessMessage;

    test("creates success toast div", () => {
        f()("Operation successful");
        const toast = doc.querySelector(".fixed.bg-green-600");
        expect(toast).not.toBeNull();
        expect(toast.textContent).toBe("Operation successful");
    });

    test("appends toast to body", () => {
        f()("Saved!");
        const toasts = doc.querySelectorAll(".fixed.bg-green-600");
        expect(toasts.length).toBeGreaterThan(0);
    });
});

// ---------------------------------------------------------------------------
// showNotification
// ---------------------------------------------------------------------------
describe("showNotification", () => {
    const f = () => win.showNotification;

    test("creates success notification with green styling", () => {
        f()("Done!", "success");
        const toast = doc.querySelector(".bg-green-100");
        expect(toast).not.toBeNull();
        expect(toast.textContent).toBe("Done!");
    });

    test("creates error notification with red styling", () => {
        f()("Failed!", "error");
        const toast = doc.querySelector(".bg-red-100");
        expect(toast).not.toBeNull();
        expect(toast.textContent).toBe("Failed!");
    });

    test("creates info notification with blue styling (default)", () => {
        f()("FYI");
        const toast = doc.querySelector(".bg-blue-100");
        expect(toast).not.toBeNull();
        expect(toast.textContent).toBe("FYI");
    });

    test("creates info notification for explicit info type", () => {
        f()("Note", "info");
        const toast = doc.querySelector(".bg-blue-100");
        expect(toast).not.toBeNull();
    });
});

// ---------------------------------------------------------------------------
// validatePasswordRequirements
// ---------------------------------------------------------------------------
describe("validatePasswordRequirements", () => {
    const f = () => win.validatePasswordRequirements;

    function setupPasswordDOM({ password = "", policy = {} } = {}) {
        // Policy data element
        const policyEl = doc.createElement("div");
        policyEl.id = "edit-password-policy-data";
        policyEl.dataset.minLength = String(policy.minLength ?? 8);
        policyEl.dataset.requireUppercase = String(policy.requireUppercase ?? true);
        policyEl.dataset.requireLowercase = String(policy.requireLowercase ?? true);
        policyEl.dataset.requireNumbers = String(policy.requireNumbers ?? true);
        policyEl.dataset.requireSpecial = String(policy.requireSpecial ?? true);
        doc.body.appendChild(policyEl);

        // Password field
        const input = doc.createElement("input");
        input.id = "password-field";
        input.value = password;
        doc.body.appendChild(input);

        // Requirement icon elements
        ["edit-req-length", "edit-req-uppercase", "edit-req-lowercase", "edit-req-numbers", "edit-req-special"].forEach((id) => {
            const el = doc.createElement("span");
            el.id = id;
            doc.body.appendChild(el);
        });

        // Submit button (inside modal content)
        const modal = doc.createElement("div");
        modal.id = "user-edit-modal-content";
        const btn = doc.createElement("button");
        btn.type = "submit";
        modal.appendChild(btn);
        doc.body.appendChild(modal);

        return { input, btn };
    }

    test("disables submit when password does not meet requirements", () => {
        const { btn } = setupPasswordDOM({
            password: "weak",
            policy: { minLength: 8, requireUppercase: true, requireLowercase: true, requireNumbers: true, requireSpecial: true },
        });
        f()();
        expect(btn.disabled).toBe(true);
    });

    test("enables submit when password meets all requirements", () => {
        const { btn } = setupPasswordDOM({
            password: "StrongP@ss1",
            policy: { minLength: 8, requireUppercase: true, requireLowercase: true, requireNumbers: true, requireSpecial: true },
        });
        f()();
        expect(btn.disabled).toBe(false);
    });

    test("enables submit when password is empty (optional password)", () => {
        const { btn } = setupPasswordDOM({
            password: "",
            policy: { minLength: 8, requireUppercase: true, requireLowercase: true, requireNumbers: true, requireSpecial: true },
        });
        f()();
        expect(btn.disabled).toBe(false);
    });

    test("does not throw when policy element is missing", () => {
        const input = doc.createElement("input");
        input.id = "password-field";
        doc.body.appendChild(input);
        expect(() => f()()).not.toThrow();
    });

    test("does not throw when password field is missing", () => {
        expect(() => f()()).not.toThrow();
    });

    test("validates length requirement", () => {
        setupPasswordDOM({
            password: "Ab1!",
            policy: { minLength: 8, requireUppercase: false, requireLowercase: false, requireNumbers: false, requireSpecial: false },
        });
        f()();
        // Password is only 4 chars, minLength is 8 -> should disable
        const btn = doc.querySelector('#user-edit-modal-content button[type="submit"]');
        expect(btn.disabled).toBe(true);
    });

    test("passes when only lowercase required and met", () => {
        const { btn } = setupPasswordDOM({
            password: "abcdefgh",
            policy: { minLength: 8, requireUppercase: false, requireLowercase: true, requireNumbers: false, requireSpecial: false },
        });
        f()();
        expect(btn.disabled).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// validatePasswordMatch
// ---------------------------------------------------------------------------
describe("validatePasswordMatch", () => {
    const f = () => win.validatePasswordMatch;

    function setupMatchDOM({ password = "", confirm = "" } = {}) {
        const pw = doc.createElement("input");
        pw.id = "password-field";
        pw.value = password;
        doc.body.appendChild(pw);

        const cpw = doc.createElement("input");
        cpw.id = "confirm-password-field";
        cpw.value = confirm;
        doc.body.appendChild(cpw);

        const msg = doc.createElement("div");
        msg.id = "password-match-message";
        msg.classList.add("hidden");
        doc.body.appendChild(msg);

        const modal = doc.createElement("div");
        modal.id = "user-edit-modal-content";
        const btn = doc.createElement("button");
        btn.type = "submit";
        modal.appendChild(btn);
        doc.body.appendChild(modal);

        return { pw, cpw, msg, btn };
    }

    test("shows mismatch message when passwords differ", () => {
        const { msg, btn } = setupMatchDOM({ password: "abc", confirm: "xyz" });
        f()();
        expect(msg.classList.contains("hidden")).toBe(false);
        expect(btn.disabled).toBe(true);
    });

    test("hides mismatch message when passwords match", () => {
        const { msg, btn } = setupMatchDOM({ password: "abc", confirm: "abc" });
        f()();
        expect(msg.classList.contains("hidden")).toBe(true);
        expect(btn.disabled).toBe(false);
    });

    test("hides message when both fields are empty", () => {
        const { msg, btn } = setupMatchDOM({ password: "", confirm: "" });
        f()();
        expect(msg.classList.contains("hidden")).toBe(true);
        expect(btn.disabled).toBe(false);
    });

    test("shows mismatch when only confirm has content", () => {
        const { msg } = setupMatchDOM({ password: "", confirm: "something" });
        f()();
        expect(msg.classList.contains("hidden")).toBe(false);
    });

    test("does not throw when elements are missing", () => {
        expect(() => f()()).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// updateSelectionCount
// ---------------------------------------------------------------------------
describe("updateSelectionCount", () => {
    const f = () => win.updateSelectionCount;

    test("counts checked gateway and item checkboxes", () => {
        const count = doc.createElement("span");
        count.id = "selection-count";
        doc.body.appendChild(count);

        // 2 gateway checkboxes (1 checked)
        const gw1 = doc.createElement("input");
        gw1.type = "checkbox";
        gw1.className = "gateway-checkbox";
        gw1.checked = true;
        doc.body.appendChild(gw1);

        const gw2 = doc.createElement("input");
        gw2.type = "checkbox";
        gw2.className = "gateway-checkbox";
        gw2.checked = false;
        doc.body.appendChild(gw2);

        // 1 item checkbox (checked)
        const item1 = doc.createElement("input");
        item1.type = "checkbox";
        item1.className = "item-checkbox";
        item1.checked = true;
        doc.body.appendChild(item1);

        f()();
        expect(count.textContent).toContain("2 items selected");
        expect(count.textContent).toContain("1 gateways");
        expect(count.textContent).toContain("1 individual items");
    });

    test("shows zero when nothing checked", () => {
        const count = doc.createElement("span");
        count.id = "selection-count";
        doc.body.appendChild(count);

        f()();
        expect(count.textContent).toContain("0 items selected");
    });

    test("does not throw when count element missing", () => {
        expect(() => f()()).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// selectAllItems
// ---------------------------------------------------------------------------
describe("selectAllItems", () => {
    const f = () => win.selectAllItems;

    test("checks all gateway and item checkboxes", () => {
        const gw = doc.createElement("input");
        gw.type = "checkbox";
        gw.className = "gateway-checkbox";
        gw.checked = false;
        doc.body.appendChild(gw);

        const item = doc.createElement("input");
        item.type = "checkbox";
        item.className = "item-checkbox";
        item.checked = false;
        doc.body.appendChild(item);

        f()();
        expect(gw.checked).toBe(true);
        expect(item.checked).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// selectNoneItems
// ---------------------------------------------------------------------------
describe("selectNoneItems", () => {
    const f = () => win.selectNoneItems;

    test("unchecks all gateway and item checkboxes", () => {
        const gw = doc.createElement("input");
        gw.type = "checkbox";
        gw.className = "gateway-checkbox";
        gw.checked = true;
        doc.body.appendChild(gw);

        const item = doc.createElement("input");
        item.type = "checkbox";
        item.className = "item-checkbox";
        item.checked = true;
        doc.body.appendChild(item);

        f()();
        expect(gw.checked).toBe(false);
        expect(item.checked).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// dedupeSelectorItems
// ---------------------------------------------------------------------------
describe("dedupeSelectorItems", () => {
    const f = () => win.dedupeSelectorItems;

    test("removes duplicate user-item elements by data-user-email", () => {
        const container = doc.createElement("div");

        const u1 = doc.createElement("div");
        u1.className = "user-item";
        u1.setAttribute("data-user-email", "alice@test.com");
        u1.textContent = "Alice (first)";
        container.appendChild(u1);

        const u2 = doc.createElement("div");
        u2.className = "user-item";
        u2.setAttribute("data-user-email", "alice@test.com");
        u2.textContent = "Alice (duplicate)";
        container.appendChild(u2);

        const u3 = doc.createElement("div");
        u3.className = "user-item";
        u3.setAttribute("data-user-email", "bob@test.com");
        u3.textContent = "Bob";
        container.appendChild(u3);

        doc.body.appendChild(container);
        f()(container);

        const remaining = container.querySelectorAll(".user-item");
        expect(remaining.length).toBe(2);
        expect(remaining[0].textContent).toBe("Alice (first)");
        expect(remaining[1].textContent).toBe("Bob");
    });

    test("does nothing with no duplicates", () => {
        const container = doc.createElement("div");
        const u1 = doc.createElement("div");
        u1.className = "user-item";
        u1.setAttribute("data-user-email", "a@test.com");
        container.appendChild(u1);
        doc.body.appendChild(container);

        f()(container);
        expect(container.querySelectorAll(".user-item").length).toBe(1);
    });

    test("does nothing with null container", () => {
        expect(() => f()(null)).not.toThrow();
    });

    test("skips items without data-user-email", () => {
        const container = doc.createElement("div");
        const u1 = doc.createElement("div");
        u1.className = "user-item";
        // No data-user-email
        container.appendChild(u1);
        const u2 = doc.createElement("div");
        u2.className = "user-item";
        container.appendChild(u2);
        doc.body.appendChild(container);

        f()(container);
        expect(container.querySelectorAll(".user-item").length).toBe(2);
    });
});

// ---------------------------------------------------------------------------
// copyToClipboard
// ---------------------------------------------------------------------------
describe("copyToClipboard", () => {
    const f = () => win.copyToClipboard;

    test("selects element and calls execCommand('copy')", () => {
        const input = doc.createElement("input");
        input.id = "token-value";
        input.value = "my-secret-token";
        doc.body.appendChild(input);

        // Mock execCommand
        let copyCalled = false;
        doc.execCommand = (cmd) => {
            if (cmd === "copy") copyCalled = true;
            return true;
        };

        f()("token-value");
        expect(copyCalled).toBe(true);
    });

    test("does not throw when element does not exist", () => {
        expect(() => f()("nonexistent")).not.toThrow();
    });
});
