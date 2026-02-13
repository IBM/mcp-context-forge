
/**
 * Unit tests for admin.js notification, password, and selection functions.
 */

import { describe, test, expect, beforeAll, beforeEach } from "vitest";
import { JSDOM } from "jsdom";

// Set up JSDOM before importing modules
const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
  url: "http://localhost",
});
global.document = dom.window.document;
global.window = dom.window;

// Now import the functions - they'll use the JSDOM document
/* eslint-disable import-x/first */
import {
  showErrorMessage,
  showSuccessMessage,
  showNotification,
  copyToClipboard,
} from "../../mcpgateway/admin_ui/utils.js";
import {
  validatePasswordMatch,
  validatePasswordRequirements,
  dedupeSelectorItems,
} from "../../mcpgateway/admin_ui/teams.js";
import {
  updateSelectionCount,
  selectAllItems,
  selectNoneItems,
} from "../../mcpgateway/admin_ui/selectiveImport.js";

let doc;

beforeAll(() => {
  doc = global.document;
});

beforeEach(() => {
  doc.body.textContent = "";
});

// ---------------------------------------------------------------------------
// showErrorMessage
// ---------------------------------------------------------------------------
describe("showErrorMessage", () => {
  test("creates global error div when no elementId", () => {
    showErrorMessage("Something went wrong");
    const errorDiv = doc.querySelector(".fixed.bg-red-600");
    expect(errorDiv).not.toBeNull();
    expect(errorDiv.textContent).toBe("Something went wrong");
  });

  test("sets text on target element when elementId provided", () => {
    const el = doc.createElement("div");
    el.id = "my-error";
    doc.body.appendChild(el);

    showErrorMessage("Field is required", "my-error");
    expect(el.textContent).toBe("Field is required");
    expect(el.classList.contains("text-red-600")).toBe(true);
  });

  test("does not throw when elementId does not exist", () => {
    expect(() => showErrorMessage("err", "nonexistent-id")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// showSuccessMessage
// ---------------------------------------------------------------------------
describe("showSuccessMessage", () => {
  test("creates success toast div", () => {
    showSuccessMessage("Operation successful");
    const toast = doc.querySelector(".fixed.bg-green-600");
    expect(toast).not.toBeNull();
    expect(toast.textContent).toBe("Operation successful");
  });

  test("appends toast to body", () => {
    showSuccessMessage("Saved!");
    const toasts = doc.querySelectorAll(".fixed.bg-green-600");
    expect(toasts.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// showNotification
// ---------------------------------------------------------------------------
describe("showNotification", () => {
  test("creates success notification with green styling", () => {
    showNotification("Done!", "success");
    const toast = doc.querySelector(".bg-green-100");
    expect(toast).not.toBeNull();
    expect(toast.textContent).toBe("Done!");
  });

  test("creates error notification with red styling", () => {
    showNotification("Failed!", "error");
    const toast = doc.querySelector(".bg-red-100");
    expect(toast).not.toBeNull();
    expect(toast.textContent).toBe("Failed!");
  });

  test("creates info notification with blue styling (default)", () => {
    showNotification("FYI");
    const toast = doc.querySelector(".bg-blue-100");
    expect(toast).not.toBeNull();
    expect(toast.textContent).toBe("FYI");
  });

  test("creates info notification for explicit info type", () => {
    showNotification("Note", "info");
    const toast = doc.querySelector(".bg-blue-100");
    expect(toast).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// validatePasswordRequirements
// ---------------------------------------------------------------------------
describe("validatePasswordRequirements", () => {
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
    [
      "edit-req-length",
      "edit-req-uppercase",
      "edit-req-lowercase",
      "edit-req-numbers",
      "edit-req-special",
    ].forEach((id) => {
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
      policy: {
        minLength: 8,
        requireUppercase: true,
        requireLowercase: true,
        requireNumbers: true,
        requireSpecial: true,
      },
    });
    validatePasswordRequirements();
    expect(btn.disabled).toBe(true);
  });

  test("enables submit when password meets all requirements", () => {
    const { btn } = setupPasswordDOM({
      password: "StrongP@ss1",
      policy: {
        minLength: 8,
        requireUppercase: true,
        requireLowercase: true,
        requireNumbers: true,
        requireSpecial: true,
      },
    });
    validatePasswordRequirements();
    expect(btn.disabled).toBe(false);
  });

  test("enables submit when password is empty (optional password)", () => {
    const { btn } = setupPasswordDOM({
      password: "",
      policy: {
        minLength: 8,
        requireUppercase: true,
        requireLowercase: true,
        requireNumbers: true,
        requireSpecial: true,
      },
    });
    validatePasswordRequirements();
    expect(btn.disabled).toBe(false);
  });

  test("does not throw when policy element is missing", () => {
    const input = doc.createElement("input");
    input.id = "password-field";
    doc.body.appendChild(input);
    expect(() => validatePasswordRequirements()).not.toThrow();
  });

  test("does not throw when password field is missing", () => {
    expect(() => validatePasswordRequirements()).not.toThrow();
  });

  test("validates length requirement", () => {
    setupPasswordDOM({
      password: "Ab1!",
      policy: {
        minLength: 8,
        requireUppercase: false,
        requireLowercase: false,
        requireNumbers: false,
        requireSpecial: false,
      },
    });
    validatePasswordRequirements();
    // Password is only 4 chars, minLength is 8 -> should disable
    const btn = doc.querySelector(
      '#user-edit-modal-content button[type="submit"]'
    );
    expect(btn.disabled).toBe(true);
  });

  test("passes when only lowercase required and met", () => {
    const { btn } = setupPasswordDOM({
      password: "abcdefgh",
      policy: {
        minLength: 8,
        requireUppercase: false,
        requireLowercase: true,
        requireNumbers: false,
        requireSpecial: false,
      },
    });
    validatePasswordRequirements();
    expect(btn.disabled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// validatePasswordMatch
// ---------------------------------------------------------------------------
describe("validatePasswordMatch", () => {
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
    validatePasswordMatch();
    expect(msg.classList.contains("hidden")).toBe(false);
    expect(btn.disabled).toBe(true);
  });

  test("hides mismatch message when passwords match", () => {
    const { msg, btn } = setupMatchDOM({ password: "abc", confirm: "abc" });
    validatePasswordMatch();
    expect(msg.classList.contains("hidden")).toBe(true);
    expect(btn.disabled).toBe(false);
  });

  test("hides message when both fields are empty", () => {
    const { msg, btn } = setupMatchDOM({ password: "", confirm: "" });
    validatePasswordMatch();
    expect(msg.classList.contains("hidden")).toBe(true);
    expect(btn.disabled).toBe(false);
  });

  test("shows mismatch when only confirm has content", () => {
    const { msg } = setupMatchDOM({ password: "", confirm: "something" });
    validatePasswordMatch();
    expect(msg.classList.contains("hidden")).toBe(false);
  });

  test("does not throw when elements are missing", () => {
    expect(() => validatePasswordMatch()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// updateSelectionCount
// ---------------------------------------------------------------------------
describe("updateSelectionCount", () => {
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

    updateSelectionCount();
    expect(count.textContent).toContain("2 items selected");
    expect(count.textContent).toContain("1 gateways");
    expect(count.textContent).toContain("1 individual items");
  });

  test("shows zero when nothing checked", () => {
    const count = doc.createElement("span");
    count.id = "selection-count";
    doc.body.appendChild(count);

    updateSelectionCount();
    expect(count.textContent).toContain("0 items selected");
  });

  test("does not throw when count element missing", () => {
    expect(() => updateSelectionCount()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// selectAllItems
// ---------------------------------------------------------------------------
describe("selectAllItems", () => {
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

    selectAllItems();
    expect(gw.checked).toBe(true);
    expect(item.checked).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// selectNoneItems
// ---------------------------------------------------------------------------
describe("selectNoneItems", () => {
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

    selectNoneItems();
    expect(gw.checked).toBe(false);
    expect(item.checked).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// dedupeSelectorItems
// ---------------------------------------------------------------------------
describe("dedupeSelectorItems", () => {
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
    dedupeSelectorItems(container);

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

    dedupeSelectorItems(container);
    expect(container.querySelectorAll(".user-item").length).toBe(1);
  });

  test("does nothing with null container", () => {
    expect(() => dedupeSelectorItems(null)).not.toThrow();
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

    dedupeSelectorItems(container);
    expect(container.querySelectorAll(".user-item").length).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// copyToClipboard
// ---------------------------------------------------------------------------
describe("copyToClipboard", () => {
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

    copyToClipboard("token-value");
    expect(copyCalled).toBe(true);
  });

  test("does not throw when element does not exist", () => {
    expect(() => copyToClipboard("nonexistent")).not.toThrow();
  });
});
