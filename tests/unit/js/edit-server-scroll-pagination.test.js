/**
 * Tests for #3358 — edit-server selector checked state is re-applied after
 * HTMX scroll-paginated appends.
 *
 * The infinite-scroll sentinel uses hx-swap="outerHTML", which replaces itself
 * with the next page of tool/resource/prompt items.  The htmx:afterSwap event
 * bubbles up to the container div.  Before the fix the afterSwap handler in
 * initialization.js only called initToolSelect (which wires buttons) without
 * restoring checked state, so page-2+ items for associated entities appeared
 * unchecked despite being in the persistent selection store.
 *
 * These tests confirm:
 *   1. The bug exists on current main (test FAILS before the fix).
 *   2. After the fix, checkboxes on scroll-appended pages are checked when
 *      their id is in getEditSelections(containerId).
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import {
  getEditSelections,
  ensureEditStoreListeners,
} from "../../../mcpgateway/admin_ui/servers.js";
import { AppState } from "../../../mcpgateway/admin_ui/appState.js";

// ---------------------------------------------------------------------------
// Module-level mocks required by servers.js transitive imports
// ---------------------------------------------------------------------------
vi.mock("../../../mcpgateway/admin_ui/appState.js", () => ({
  AppState: {
    editServerSelections: {},
    setModalActive: vi.fn(),
    setModalInactive: vi.fn(),
    isModalActive: vi.fn(() => false),
  },
}));
vi.mock("../../../mcpgateway/admin_ui/configExport.js", () => ({
  getCatalogUrl: vi.fn(() => ""),
}));
vi.mock("../../../mcpgateway/admin_ui/gateways.js", () => ({
  initGatewaySelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/modals.js", () => ({
  openModal: vi.fn(),
  closeModal: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/prompts.js", () => ({
  initPromptSelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/resources.js", () => ({
  initResourceSelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  validateInputName: vi.fn((s) => ({ valid: true, value: s })),
  validateUrl: vi.fn(() => ({ valid: true })),
}));
vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  fetchWithAuth: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  fetchWithTimeout: vi.fn(),
  isInactiveChecked: vi.fn(() => false),
  handleFetchError: vi.fn((e) => e.message),
  showErrorMessage: vi.fn(),
  decodeHtml: vi.fn((s) => s || ""),
  makeCopyIdButton: vi.fn(() => document.createElement("button")),
}));
vi.mock("../../../mcpgateway/admin_ui/filters.js", () => ({
  toggleViewPublic: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/teams.js", () => ({
  applyVisibilityRestrictions: vi.fn(),
  isTeamScopedView: vi.fn(() => false),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Build an edit-server-tools container with an initial page of checkboxes.
 * Returns the container element.
 */
function buildEditToolsContainer(initialToolIds = []) {
  const container = document.createElement("div");
  container.id = "edit-server-tools";
  document.body.appendChild(container);

  for (const id of initialToolIds) {
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedTools";
    cb.value = id;
    cb.checked = false;
    container.appendChild(cb);
  }
  return container;
}

/**
 * Build an edit-server-resources container with an initial page of checkboxes.
 */
function buildEditResourcesContainer(initialResourceIds = []) {
  const container = document.createElement("div");
  container.id = "edit-server-resources";
  document.body.appendChild(container);

  for (const id of initialResourceIds) {
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedResources";
    cb.value = id;
    cb.checked = false;
    container.appendChild(cb);
  }
  return container;
}

/**
 * Build an edit-server-prompts container with an initial page of checkboxes.
 */
function buildEditPromptsContainer(initialPromptIds = []) {
  const container = document.createElement("div");
  container.id = "edit-server-prompts";
  document.body.appendChild(container);

  for (const id of initialPromptIds) {
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedPrompts";
    cb.value = id;
    cb.checked = false;
    container.appendChild(cb);
  }
  return container;
}

/**
 * Simulate an HTMX scroll-paginated append:
 *   - appends new checkbox elements as direct children of `container`
 *   - dispatches htmx:afterSwap on the body with `target` = the appended sentinel div
 *     (mirroring outerHTML swap where the sentinel replaces itself with page content
 *     and htmx fires afterSwap with the old sentinel's parent or the elt itself)
 *
 * In practice HTMX fires htmx:afterSwap on body with detail.target = the element
 * whose content was swapped (the container when hx-swap=innerHTML, or the elt
 * itself's parent for hx-swap=outerHTML).  For the infinite scroll sentinel
 * (hx-swap="outerHTML" on a child of edit-server-tools), the detail.target is
 * the sentinel div; the event bubbles through its ancestor chain which includes
 * the container.  We fire it directly on the container to mirror what bubbling
 * delivers there.
 */
function simulateScrollAppend(container, newCheckboxDefs) {
  // Append the new-page checkboxes to the container (simulating HTMX outerHTML
  // replacement of the sentinel div with page content that contains checkboxes)
  for (const { name, value } of newCheckboxDefs) {
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = name;
    cb.value = value;
    cb.checked = false;
    container.appendChild(cb);
  }

  // Dispatch htmx:afterSwap bubbling through the container (as the browser
  // event model delivers when the sentinel — a descendant — is the target)
  const evt = new Event("htmx:afterSwap", { bubbles: true });
  evt.detail = { target: container };
  container.dispatchEvent(evt);
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  AppState.editServerSelections = {};
  window._editStoreListenersAttached = false;
  document.body.innerHTML = "";
  window.ROOT_PATH = "";
  window.Admin = window.Admin || {};
});

afterEach(() => {
  document.body.innerHTML = "";
  AppState.editServerSelections = {};
  delete window._editStoreListenersAttached;
  delete window.ROOT_PATH;
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("edit-server scroll-pagination: checked state restored on afterSwap (#3358)", () => {
  test("tools: associated tool on page 2 is checked after scroll append", () => {
    // page-1 tool already rendered (not in selection store — it was loaded fresh)
    const container = buildEditToolsContainer(["tool-page1-a"]);

    // seed the selection store: both tools are associated with this server
    const toolSel = getEditSelections("edit-server-tools");
    toolSel.add("tool-page1-a");
    toolSel.add("tool-page2-b"); // lives on page 2, not yet rendered

    ensureEditStoreListeners();

    // simulate scroll loads page 2 → new checkbox appended + afterSwap fires
    simulateScrollAppend(container, [
      { name: "associatedTools", value: "tool-page2-b" },
      { name: "associatedTools", value: "tool-page2-c" }, // not associated
    ]);

    // tool-page2-b is in the store → must be checked
    const cbB = container.querySelector('input[value="tool-page2-b"]');
    expect(cbB).not.toBeNull();
    expect(cbB.checked).toBe(true);

    // tool-page2-c is NOT in the store → must stay unchecked
    const cbC = container.querySelector('input[value="tool-page2-c"]');
    expect(cbC).not.toBeNull();
    expect(cbC.checked).toBe(false);
  });

  test("resources: associated resource on page 2 is checked after scroll append", () => {
    const container = buildEditResourcesContainer(["res-page1-a"]);

    const resSel = getEditSelections("edit-server-resources");
    resSel.add("res-page1-a");
    resSel.add("res-page2-b");

    ensureEditStoreListeners();

    simulateScrollAppend(container, [
      { name: "associatedResources", value: "res-page2-b" },
      { name: "associatedResources", value: "res-page2-c" },
    ]);

    const cbB = container.querySelector('input[value="res-page2-b"]');
    expect(cbB).not.toBeNull();
    expect(cbB.checked).toBe(true);

    const cbC = container.querySelector('input[value="res-page2-c"]');
    expect(cbC).not.toBeNull();
    expect(cbC.checked).toBe(false);
  });

  test("prompts: associated prompt on page 2 is checked after scroll append", () => {
    const container = buildEditPromptsContainer(["prompt-page1-a"]);

    const promptSel = getEditSelections("edit-server-prompts");
    promptSel.add("prompt-page1-a");
    promptSel.add("prompt-page2-b");

    ensureEditStoreListeners();

    simulateScrollAppend(container, [
      { name: "associatedPrompts", value: "prompt-page2-b" },
      { name: "associatedPrompts", value: "prompt-page2-c" },
    ]);

    const cbB = container.querySelector('input[value="prompt-page2-b"]');
    expect(cbB).not.toBeNull();
    expect(cbB.checked).toBe(true);

    const cbC = container.querySelector('input[value="prompt-page2-c"]');
    expect(cbC).not.toBeNull();
    expect(cbC.checked).toBe(false);
  });

  test("multiple scroll pages: all associated tools across pages are checked", () => {
    const container = buildEditToolsContainer([]);

    const toolSel = getEditSelections("edit-server-tools");
    // 5 associated tools spread across 3 pages
    ["t-p1", "t-p2-assoc", "t-p3-assoc"].forEach((id) => toolSel.add(id));

    ensureEditStoreListeners();

    // page 1
    simulateScrollAppend(container, [
      { name: "associatedTools", value: "t-p1" },
      { name: "associatedTools", value: "t-p1-extra" },
    ]);
    // page 2
    simulateScrollAppend(container, [
      { name: "associatedTools", value: "t-p2-assoc" },
      { name: "associatedTools", value: "t-p2-free" },
    ]);
    // page 3
    simulateScrollAppend(container, [
      { name: "associatedTools", value: "t-p3-assoc" },
      { name: "associatedTools", value: "t-p3-free" },
    ]);

    expect(container.querySelector('input[value="t-p1"]').checked).toBe(true);
    expect(container.querySelector('input[value="t-p1-extra"]').checked).toBe(false);
    expect(container.querySelector('input[value="t-p2-assoc"]').checked).toBe(true);
    expect(container.querySelector('input[value="t-p2-free"]').checked).toBe(false);
    expect(container.querySelector('input[value="t-p3-assoc"]').checked).toBe(true);
    expect(container.querySelector('input[value="t-p3-free"]').checked).toBe(false);
  });

  test("containers are independent: tools afterSwap does not affect resources", () => {
    const toolsContainer = buildEditToolsContainer([]);
    const resourcesContainer = buildEditResourcesContainer([]);

    getEditSelections("edit-server-tools").add("tool-x");
    // resource-y is NOT in the tools store
    getEditSelections("edit-server-resources").add("resource-y");

    ensureEditStoreListeners();

    // only tools container gets the afterSwap
    simulateScrollAppend(toolsContainer, [
      { name: "associatedTools", value: "tool-x" },
    ]);
    // manually append to resources container without event
    const resCb = document.createElement("input");
    resCb.type = "checkbox";
    resCb.name = "associatedResources";
    resCb.value = "resource-y";
    resCb.checked = false;
    resourcesContainer.appendChild(resCb);

    // tools: tool-x should be checked
    expect(toolsContainer.querySelector('input[value="tool-x"]').checked).toBe(true);
    // resources: resource-y was not given an afterSwap, so still unchecked
    // (this confirms the fix is scoped to the dispatching container)
    expect(resourcesContainer.querySelector('input[value="resource-y"]').checked).toBe(false);
  });
});
