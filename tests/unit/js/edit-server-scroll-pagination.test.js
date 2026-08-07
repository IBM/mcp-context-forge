/**
 * Tests for #3358 — edit-server selector checked state is re-applied after
 * HTMX scroll-paginated appends.
 *
 * The infinite-scroll sentinel uses hx-swap="outerHTML", which replaces itself
 * with the next page of tool/resource/prompt items.  htmx:afterSwap /
 * htmx:afterSettle bubble up to the container div.  The edit modal seeds the
 * persistent selection store with the associated item ids on open, but as the
 * pages stream in, tools.js's pill-count update() syncs DOM->store and DELETES
 * the id of every checkbox that is currently rendered unchecked.  Associated
 * items on page 2+ always render unchecked, so their seeded ids are stripped
 * from the store before any re-check runs — a store-only restore then restores
 * nothing, and the associated tools render unchecked despite being associated.
 *
 * These tests confirm:
 *   1. The bug exists on current main (the "real path" tests FAIL before the
 *      fix, because the store has been depleted and only the data-server-*
 *      attribute still carries the association).
 *   2. After the fix, checkboxes on scroll-appended pages are checked when
 *      their id is in getEditSelections(containerId) OR their identity is in the
 *      container's data-server-* attribute, and re-checking repairs the store.
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
 * Each checkbox carries a data-tool-name so the name-based association match
 * (the real save/render path for tools) can be exercised.
 */
function buildEditToolsContainer(initialTools = []) {
  const container = document.createElement("div");
  container.id = "edit-server-tools";
  document.body.appendChild(container);
  for (const t of initialTools) {
    container.appendChild(makeToolCheckbox(t));
  }
  return container;
}

function makeToolCheckbox({ id, name }) {
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.name = "associatedTools";
  cb.value = id;
  cb.checked = false;
  if (name != null) {
    cb.setAttribute("data-tool-name", name);
  }
  return cb;
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
 * Simulate the pill-count update() DOM->store sync from tools.js (lines ~1030):
 * for every checkbox currently in the container, add its id to the store when
 * checked and DELETE it when unchecked.  This is the churn that erases the
 * seeded association ids as unchecked page-2+ items render — the crux of the
 * bug.  Firing this before the restore is what makes these tests exercise the
 * REAL path rather than a store that conveniently still holds the seed.
 */
function simulatePillUpdateStoreSync(container, containerId) {
  const sel = getEditSelections(containerId);
  container.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
    if (cb.checked) {
      sel.add(String(cb.value));
    } else {
      sel.delete(String(cb.value));
    }
  });
}

/**
 * Simulate an HTMX scroll-paginated append of a new page, mirroring the real
 * event/mutation ordering:
 *   1. append the new-page checkboxes to the container (outerHTML swap of the
 *      sentinel with page content),
 *   2. run the pill-count store sync (tools.js update()), which deletes the
 *      unchecked associated ids from the store,
 *   3. dispatch htmx:afterSettle bubbling through the container — this is the
 *      phase the fix's listener acts on, after update() has run.
 *
 * @param {HTMLElement} container
 * @param {string} containerId
 * @param {Array<{name:string, value:string, toolName?:string}>} newCheckboxDefs
 */
function simulateScrollAppend(container, containerId, newCheckboxDefs) {
  for (const { name, value, toolName } of newCheckboxDefs) {
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = name;
    cb.value = value;
    cb.checked = false;
    if (toolName != null) {
      cb.setAttribute("data-tool-name", toolName);
    }
    container.appendChild(cb);
  }

  // The pill-count update() runs on settle and depletes the store first...
  simulatePillUpdateStoreSync(container, containerId);

  // ...then afterSettle bubbles up to the container, where the fix re-applies.
  const swap = new Event("htmx:afterSwap", { bubbles: true });
  swap.detail = { target: container };
  container.dispatchEvent(swap);
  const settle = new Event("htmx:afterSettle", { bubbles: true });
  settle.detail = { target: container };
  container.dispatchEvent(settle);
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
// Tests — REAL PATH: store is depleted by update(), only data-server-* survives
// ---------------------------------------------------------------------------

describe("edit-server scroll-pagination: real path with store depletion (#3358)", () => {
  test("tools: associated tool on page 2+ stays checked even after the pill-count sync deletes it from the store", () => {
    // Page 1 renders tools that are NOT associated with this server.
    const container = buildEditToolsContainer([
      { id: "id-p1-x", name: "tool-p1-x" },
      { id: "id-p1-y", name: "tool-p1-y" },
    ]);

    // The server's association is carried by the data-server-tools attribute as
    // tool NAMES (exactly as servers.js seeds it from server.associatedTools).
    container.setAttribute(
      "data-server-tools",
      JSON.stringify(["tool-assoc-a", "tool-assoc-b"]),
    );

    // Store seeded on open with the associated tool IDS (as editServer does).
    const toolSel = getEditSelections("edit-server-tools");
    toolSel.add("id-assoc-a");
    toolSel.add("id-assoc-b");

    ensureEditStoreListeners();

    // Page 1 settles first: update() would delete seeded ids for any of them
    // rendered unchecked.  Here the assoc checkboxes are not on page 1, so
    // nothing is deleted yet — but the store is now the only carrier.
    simulateScrollAppend(container, "edit-server-tools", []);
    expect(getEditSelections("edit-server-tools").has("id-assoc-a")).toBe(true);

    // Page 2 brings in the two associated tools (unchecked) + a free one.
    simulateScrollAppend(container, "edit-server-tools", [
      { name: "associatedTools", value: "id-assoc-a", toolName: "tool-assoc-a" },
      { name: "associatedTools", value: "id-assoc-b", toolName: "tool-assoc-b" },
      { name: "associatedTools", value: "id-p2-free", toolName: "tool-p2-free" },
    ]);

    // Associated tools must be checked (restored via the name attribute even
    // though update() stripped their ids from the store as they rendered).
    expect(container.querySelector('input[value="id-assoc-a"]').checked).toBe(true);
    expect(container.querySelector('input[value="id-assoc-b"]').checked).toBe(true);
    // The non-associated tool must stay unchecked.
    expect(container.querySelector('input[value="id-p2-free"]').checked).toBe(false);

    // And the re-check must have repaired the store (change event re-adds ids),
    // so the save payload and pill count are correct.
    const sel = getEditSelections("edit-server-tools");
    expect(sel.has("id-assoc-a")).toBe(true);
    expect(sel.has("id-assoc-b")).toBe(true);
    expect(sel.has("id-p2-free")).toBe(false);
  });

  test("resources: associated resource on page 2 stays checked despite store depletion (id match via data-server-resources)", () => {
    const container = buildEditResourcesContainer(["res-p1"]);
    container.setAttribute(
      "data-server-resources",
      JSON.stringify(["res-assoc"]),
    );

    const resSel = getEditSelections("edit-server-resources");
    resSel.add("res-assoc"); // seeded on open, then stripped by update()

    ensureEditStoreListeners();

    simulateScrollAppend(container, "edit-server-resources", [
      { name: "associatedResources", value: "res-assoc" },
      { name: "associatedResources", value: "res-free" },
    ]);

    expect(container.querySelector('input[value="res-assoc"]').checked).toBe(true);
    expect(container.querySelector('input[value="res-free"]').checked).toBe(false);
    expect(getEditSelections("edit-server-resources").has("res-assoc")).toBe(true);
  });

  test("prompts: associated prompt on page 2 stays checked despite store depletion", () => {
    const container = buildEditPromptsContainer(["prompt-p1"]);
    container.setAttribute(
      "data-server-prompts",
      JSON.stringify(["prompt-assoc"]),
    );

    const promptSel = getEditSelections("edit-server-prompts");
    promptSel.add("prompt-assoc");

    ensureEditStoreListeners();

    simulateScrollAppend(container, "edit-server-prompts", [
      { name: "associatedPrompts", value: "prompt-assoc" },
      { name: "associatedPrompts", value: "prompt-free" },
    ]);

    expect(container.querySelector('input[value="prompt-assoc"]').checked).toBe(true);
    expect(container.querySelector('input[value="prompt-free"]').checked).toBe(false);
    expect(getEditSelections("edit-server-prompts").has("prompt-assoc")).toBe(true);
  });

  test("tools: all associated tools across many pages stay checked while store is depleted page by page", () => {
    const container = buildEditToolsContainer([]);
    container.setAttribute(
      "data-server-tools",
      JSON.stringify(["a1", "a2", "a3"]),
    );
    // Seed the store with the ids; update() will erase them as pages render.
    ["ida1", "ida2", "ida3"].forEach((id) =>
      getEditSelections("edit-server-tools").add(id),
    );

    ensureEditStoreListeners();

    // page 1 — no associated items
    simulateScrollAppend(container, "edit-server-tools", [
      { name: "associatedTools", value: "idp1", toolName: "p1" },
    ]);
    // page 2 — one associated
    simulateScrollAppend(container, "edit-server-tools", [
      { name: "associatedTools", value: "ida1", toolName: "a1" },
      { name: "associatedTools", value: "idp2", toolName: "p2" },
    ]);
    // page 3 — two associated
    simulateScrollAppend(container, "edit-server-tools", [
      { name: "associatedTools", value: "ida2", toolName: "a2" },
      { name: "associatedTools", value: "ida3", toolName: "a3" },
    ]);

    expect(container.querySelector('input[value="ida1"]').checked).toBe(true);
    expect(container.querySelector('input[value="ida2"]').checked).toBe(true);
    expect(container.querySelector('input[value="ida3"]').checked).toBe(true);
    expect(container.querySelector('input[value="idp1"]').checked).toBe(false);
    expect(container.querySelector('input[value="idp2"]').checked).toBe(false);

    const sel = getEditSelections("edit-server-tools");
    expect(sel.has("ida1")).toBe(true);
    expect(sel.has("ida2")).toBe(true);
    expect(sel.has("ida3")).toBe(true);
  });

  test("tools: a user-unchecked associated tool is NOT re-checked (data-server-tools tracks intent)", () => {
    const container = buildEditToolsContainer([]);
    container.setAttribute("data-server-tools", JSON.stringify(["a1", "a2"]));
    ["ida1", "ida2"].forEach((id) =>
      getEditSelections("edit-server-tools").add(id),
    );

    ensureEditStoreListeners();

    simulateScrollAppend(container, "edit-server-tools", [
      { name: "associatedTools", value: "ida1", toolName: "a1" },
      { name: "associatedTools", value: "ida2", toolName: "a2" },
    ]);
    expect(container.querySelector('input[value="ida1"]').checked).toBe(true);
    expect(container.querySelector('input[value="ida2"]').checked).toBe(true);

    // User unchecks ida1.  The real tools.js change handler removes its name
    // from data-server-tools; mirror that, then fire a fresh settle.
    const victim = container.querySelector('input[value="ida1"]');
    victim.checked = false;
    victim.dispatchEvent(new Event("change", { bubbles: true }));
    container.setAttribute("data-server-tools", JSON.stringify(["a2"]));

    const settle = new Event("htmx:afterSettle", { bubbles: true });
    settle.detail = { target: container };
    container.dispatchEvent(settle);

    // The re-apply must respect the user's uncheck, not force it back on.
    expect(container.querySelector('input[value="ida1"]').checked).toBe(false);
    expect(container.querySelector('input[value="ida2"]').checked).toBe(true);
    expect(getEditSelections("edit-server-tools").has("ida1")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Tests — store-match path (no data attribute): a user's fresh selection that
// scrolls out of and back into view must remain checked.
// ---------------------------------------------------------------------------

describe("edit-server scroll-pagination: store-match preserved without data attribute (#3358)", () => {
  test("tools: an id present only in the store (no data-server-tools) is restored", () => {
    const container = buildEditToolsContainer([]);
    // No data-server-tools attribute at all (e.g. a brand-new user selection).
    const toolSel = getEditSelections("edit-server-tools");
    toolSel.add("user-picked");

    ensureEditStoreListeners();

    // Because there is no data attribute, the store must survive for this to
    // work — so DO NOT run the depleting sync here; append + settle only.
    const cb = makeToolCheckbox({ id: "user-picked", name: "up" });
    container.appendChild(cb);
    const settle = new Event("htmx:afterSettle", { bubbles: true });
    settle.detail = { target: container };
    container.dispatchEvent(settle);

    expect(container.querySelector('input[value="user-picked"]').checked).toBe(true);
  });

  test("containers are independent: tools afterSettle does not affect resources", () => {
    const toolsContainer = buildEditToolsContainer([]);
    toolsContainer.setAttribute("data-server-tools", JSON.stringify(["tx"]));
    const resourcesContainer = buildEditResourcesContainer([]);
    resourcesContainer.setAttribute(
      "data-server-resources",
      JSON.stringify(["resource-y"]),
    );

    ensureEditStoreListeners();

    // only tools container gets the afterSettle
    simulateScrollAppend(toolsContainer, "edit-server-tools", [
      { name: "associatedTools", value: "id-tx", toolName: "tx" },
    ]);
    // manually append to resources container without event
    const resCb = document.createElement("input");
    resCb.type = "checkbox";
    resCb.name = "associatedResources";
    resCb.value = "resource-y";
    resCb.checked = false;
    resourcesContainer.appendChild(resCb);

    expect(toolsContainer.querySelector('input[value="id-tx"]').checked).toBe(true);
    // resources: resource-y was not given an event, so still unchecked
    expect(resourcesContainer.querySelector('input[value="resource-y"]').checked).toBe(false);
  });
});
