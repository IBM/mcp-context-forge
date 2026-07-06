/**
 * @vitest-environment jsdom
 *
 * Regression tests for the MCP Registry partial (#5154 / PR #5197).
 *
 * The seven action handlers in mcp_registry_partial.html were declared as plain
 * globals and never attached to window.Admin, so eventDelegation.js executeAction()
 * could not resolve them — every data-action-click in the panel was a silent no-op
 * (e.g. "Action is not a function: refreshCatalog"). These tests evaluate the
 * partial's inline scripts and assert the handlers are both registered on
 * window.Admin and dispatchable through the real event-delegation path.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { initializeEventDelegation, resetEventDelegation } from "../../../mcpgateway/admin_ui/eventDelegation.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const TEMPLATE_PATH = path.resolve(__dirname, "../../../mcpgateway/templates/mcp_registry_partial.html");

// The partial-specific handlers that must be resolvable via window.Admin for
// executeAction() to dispatch the panel's buttons and filter badges.
// showApiKeyModal / closeApiKeyModal are deliberately excluded: they are owned
// by the bundled modals.js and the partial must not override them (see #5154).
const EXPECTED_ACTIONS = [
  "refreshCatalog",
  "filterByCategory",
  "filterByAuthType",
  "filterByProvider",
  "registerServerWithApiKey",
];

// Handlers the partial must leave to the bundled modals.js (registered in
// admin.js) rather than shadowing with its own inline copies.
const BUNDLE_OWNED_ACTIONS = ["showApiKeyModal", "closeApiKeyModal"];

/**
 * Evaluate the partial's inline <script> blocks against the current window.
 *
 * The partial uses classic (non-module) <script> tags whose function
 * declarations span two blocks and whose trailing block wires them onto
 * window.Admin. We concatenate both bodies, strip the Jinja expressions, and
 * run them together so those registration statements execute. window.Admin
 * assignments happen inside this scope, so the references are captured even
 * though the function declarations themselves stay local.
 */
function evaluateRegistryScripts() {
  const html = fs.readFileSync(TEMPLATE_PATH, "utf8");
  const body = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)]
    .map((match) => match[1])
    .join("\n")
    // Replace Jinja expressions (e.g. {{ root_path|tojson }}) with empty strings
    // so the body is valid JavaScript.
    .replace(/\{\{[\s\S]*?\}\}/g, '""');
  // eslint-disable-next-line no-new-func
  new Function(body)();
}

describe("mcp_registry_partial window.Admin registration", () => {
  beforeEach(() => {
    delete window.Admin;
    window.htmx = { trigger: vi.fn(), ajax: vi.fn() };
  });

  afterEach(() => {
    delete window.Admin;
    delete window.htmx;
    document.body.innerHTML = "";
  });

  it("registers every panel action handler on window.Admin", () => {
    evaluateRegistryScripts();

    expect(window.Admin).toBeDefined();
    for (const action of EXPECTED_ACTIONS) {
      expect(typeof window.Admin[action], `window.Admin.${action}`).toBe("function");
    }
  });

  it("preserves an existing window.Admin namespace instead of clobbering it", () => {
    const existing = vi.fn();
    window.Admin = { existingHandler: existing };

    evaluateRegistryScripts();

    expect(window.Admin.existingHandler).toBe(existing);
    for (const action of EXPECTED_ACTIONS) {
      expect(typeof window.Admin[action]).toBe("function");
    }
  });

  it("does not override the bundled showApiKeyModal / closeApiKeyModal", () => {
    // Simulate the bundle (modals.js via admin.js) having already registered
    // the canonical modal handlers before the partial's inline script runs.
    const bundled = Object.fromEntries(BUNDLE_OWNED_ACTIONS.map((name) => [name, vi.fn()]));
    window.Admin = { ...bundled };

    evaluateRegistryScripts();

    // The partial must leave the bundled implementations untouched...
    for (const action of BUNDLE_OWNED_ACTIONS) {
      expect(window.Admin[action]).toBe(bundled[action]);
    }
    // ...while still registering its own five handlers.
    for (const action of EXPECTED_ACTIONS) {
      expect(typeof window.Admin[action]).toBe("function");
    }
  });
});

describe("mcp_registry_partial action dispatch via eventDelegation", () => {
  beforeEach(() => {
    delete window.Admin;
    window.ROOT_PATH = "";
    window.htmx = { trigger: vi.fn(), ajax: vi.fn() };
    evaluateRegistryScripts();
    resetEventDelegation();
    initializeEventDelegation();
  });

  afterEach(() => {
    resetEventDelegation();
    delete window.Admin;
    delete window.htmx;
    document.body.innerHTML = "";
  });

  it("dispatches refreshCatalog when its button is clicked", () => {
    const button = document.createElement("button");
    button.setAttribute("data-action-click", "refreshCatalog");
    document.body.appendChild(button);

    button.click();

    expect(window.htmx.ajax).toHaveBeenCalledTimes(1);
    expect(window.htmx.ajax).toHaveBeenCalledWith(
      "GET",
      "/admin/mcp-registry/partial",
      expect.objectContaining({ target: "#mcp-registry-servers", swap: "innerHTML" }),
    );
  });

  it("dispatches filterByCategory with its parsed argument", () => {
    const select = document.createElement("select");
    select.id = "category-filter";
    const option = document.createElement("option");
    option.value = "development";
    select.appendChild(option);
    document.body.appendChild(select);

    const badge = document.createElement("button");
    badge.setAttribute("data-action-click", "filterByCategory");
    badge.setAttribute("data-arg0", '"development"');
    document.body.appendChild(badge);

    badge.click();

    expect(window.htmx.trigger).toHaveBeenCalledTimes(1);
    expect(window.htmx.trigger).toHaveBeenCalledWith(select, "change");
    expect(select.value).toBe("development");
  });
});
