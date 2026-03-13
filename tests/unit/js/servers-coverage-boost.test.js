/**
 * Additional unit tests for servers.js module to increase coverage
 * Tests: selection stores, mapping functions, OAuth config, visibility settings
 */

import { describe, test, expect, vi, afterEach, beforeEach } from "vitest";

import {
  getEditSelections,
  resetEditSelections,
  ensureEditStoreListeners,
  ensureAddStoreListeners,
  updateToolMapping,
  updatePromptMapping,
  updateResourceMapping,
} from "../../../mcpgateway/admin_ui/servers.js";
import { AppState } from "../../../mcpgateway/admin_ui/appState.js";

vi.mock("../../../mcpgateway/admin_ui/appState.js", () => ({
  AppState: {
    editServerSelections: {},
  },
}));

beforeEach(() => {
  window.Admin = window.Admin || {};
  AppState.editServerSelections = {};
  document.body.innerHTML = "";
  delete window._editStoreListenersAttached;
  delete window._addStoreListenersAttached;
});

afterEach(() => {
  document.body.innerHTML = "";
  delete window.Admin;
  AppState.editServerSelections = {};
  delete window._editStoreListenersAttached;
  delete window._addStoreListenersAttached;
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// getEditSelections
// ---------------------------------------------------------------------------
describe("getEditSelections", () => {
  test("returns empty Set for new container", () => {
    const sel = getEditSelections("edit-server-tools");
    expect(sel).toBeInstanceOf(Set);
    expect(sel.size).toBe(0);
  });

  test("returns same Set instance for same container", () => {
    const sel1 = getEditSelections("edit-server-tools");
    const sel2 = getEditSelections("edit-server-tools");
    expect(sel1).toBe(sel2);
  });

  test("returns different Sets for different containers", () => {
    const sel1 = getEditSelections("edit-server-tools");
    const sel2 = getEditSelections("edit-server-resources");
    expect(sel1).not.toBe(sel2);
  });

  test("persists selections across calls", () => {
    const sel = getEditSelections("edit-server-tools");
    sel.add("tool-1");
    sel.add("tool-2");
    
    const sel2 = getEditSelections("edit-server-tools");
    expect(sel2.has("tool-1")).toBe(true);
    expect(sel2.has("tool-2")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// resetEditSelections
// ---------------------------------------------------------------------------
describe("resetEditSelections", () => {
  test("clears all selection stores", () => {
    const toolSel = getEditSelections("edit-server-tools");
    const resSel = getEditSelections("edit-server-resources");
    const promptSel = getEditSelections("edit-server-prompts");
    
    toolSel.add("t1");
    resSel.add("r1");
    promptSel.add("p1");
    
    resetEditSelections();
    
    expect(AppState.editServerSelections["edit-server-tools"]).toBeUndefined();
    expect(AppState.editServerSelections["edit-server-resources"]).toBeUndefined();
    expect(AppState.editServerSelections["edit-server-prompts"]).toBeUndefined();
  });

  test("removes stale hidden inputs from containers", () => {
    // Create tool container with hidden inputs
    const toolContainer = document.createElement("div");
    toolContainer.id = "edit-server-tools";
    
    const selectAllInput = document.createElement("input");
    selectAllInput.name = "selectAllTools";
    selectAllInput.type = "hidden";
    toolContainer.appendChild(selectAllInput);
    
    const allIdsInput = document.createElement("input");
    allIdsInput.name = "allToolIds";
    allIdsInput.type = "hidden";
    toolContainer.appendChild(allIdsInput);
    
    document.body.appendChild(toolContainer);
    
    resetEditSelections();
    
    expect(toolContainer.querySelector('input[name="selectAllTools"]')).toBeNull();
    expect(toolContainer.querySelector('input[name="allToolIds"]')).toBeNull();
  });

  test("removes hidden inputs from resources container", () => {
    const resContainer = document.createElement("div");
    resContainer.id = "edit-server-resources";
    
    const selectAllInput = document.createElement("input");
    selectAllInput.name = "selectAllResources";
    selectAllInput.type = "hidden";
    resContainer.appendChild(selectAllInput);
    
    document.body.appendChild(resContainer);
    
    resetEditSelections();
    
    expect(resContainer.querySelector('input[name="selectAllResources"]')).toBeNull();
  });

  test("removes hidden inputs from prompts container", () => {
    const promptContainer = document.createElement("div");
    promptContainer.id = "edit-server-prompts";
    
    const selectAllInput = document.createElement("input");
    selectAllInput.name = "selectAllPrompts";
    selectAllInput.type = "hidden";
    promptContainer.appendChild(selectAllInput);
    
    document.body.appendChild(promptContainer);
    
    resetEditSelections();
    
    expect(promptContainer.querySelector('input[name="selectAllPrompts"]')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// ensureEditStoreListeners
// ---------------------------------------------------------------------------
describe("ensureEditStoreListeners", () => {
  test("attaches listeners only once", () => {
    ensureEditStoreListeners();
    expect(window._editStoreListenersAttached).toBe(true);
    
    ensureEditStoreListeners();
    // Should not throw or re-attach
    expect(window._editStoreListenersAttached).toBe(true);
  });

  test("updates selection store when checkbox changes", () => {
    const toolContainer = document.createElement("div");
    toolContainer.id = "edit-server-tools";
    
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "associatedTools";
    checkbox.value = "tool-123";
    
    toolContainer.appendChild(checkbox);
    document.body.appendChild(toolContainer);
    
    ensureEditStoreListeners();
    
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    
    const sel = getEditSelections("edit-server-tools");
    expect(sel.has("tool-123")).toBe(true);
  });

  test("removes from selection store when unchecked", () => {
    const toolContainer = document.createElement("div");
    toolContainer.id = "edit-server-tools";
    
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "associatedTools";
    checkbox.value = "tool-123";
    
    toolContainer.appendChild(checkbox);
    document.body.appendChild(toolContainer);
    
    const sel = getEditSelections("edit-server-tools");
    sel.add("tool-123");
    
    ensureEditStoreListeners();
    
    checkbox.checked = false;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    
    expect(sel.has("tool-123")).toBe(false);
  });

  test("handles resources checkbox changes", () => {
    const resContainer = document.createElement("div");
    resContainer.id = "edit-server-resources";
    
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "associatedResources";
    checkbox.value = "res-456";
    
    resContainer.appendChild(checkbox);
    document.body.appendChild(resContainer);
    
    ensureEditStoreListeners();
    
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    
    const sel = getEditSelections("edit-server-resources");
    expect(sel.has("res-456")).toBe(true);
  });

  test("handles prompts checkbox changes", () => {
    const promptContainer = document.createElement("div");
    promptContainer.id = "edit-server-prompts";
    
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "associatedPrompts";
    checkbox.value = "prompt-789";
    
    promptContainer.appendChild(checkbox);
    document.body.appendChild(promptContainer);
    
    ensureEditStoreListeners();
    
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    
    const sel = getEditSelections("edit-server-prompts");
    expect(sel.has("prompt-789")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// ensureAddStoreListeners
// ---------------------------------------------------------------------------
describe("ensureAddStoreListeners", () => {
  test("attaches listeners only once", () => {
    ensureAddStoreListeners();
    expect(window._addStoreListenersAttached).toBe(true);
    
    ensureAddStoreListeners();
    expect(window._addStoreListenersAttached).toBe(true);
  });

  test("updates selection store for add form tools", () => {
    const toolContainer = document.createElement("div");
    toolContainer.id = "associatedTools";
    
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "associatedTools";
    checkbox.value = "tool-abc";
    
    toolContainer.appendChild(checkbox);
    document.body.appendChild(toolContainer);
    
    ensureAddStoreListeners();
    
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    
    const sel = getEditSelections("associatedTools");
    expect(sel.has("tool-abc")).toBe(true);
  });

  test("clears selections on form reset", () => {
    const form = document.createElement("form");
    form.id = "add-server-form";
    
    const toolContainer = document.createElement("div");
    toolContainer.id = "associatedTools";
    
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "associatedTools";
    checkbox.value = "tool-xyz";
    
    toolContainer.appendChild(checkbox);
    form.appendChild(toolContainer);
    document.body.appendChild(form);
    
    const sel = getEditSelections("associatedTools");
    sel.add("tool-xyz");
    sel.add("tool-123");
    
    ensureAddStoreListeners();
    
    form.dispatchEvent(new Event("reset"));
    
    expect(AppState.editServerSelections["associatedTools"]).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// updateToolMapping
// ---------------------------------------------------------------------------
describe("updateToolMapping", () => {
  test("creates tool mapping from checkboxes", () => {
    window.Admin.toolMapping = {};
    
    const container = document.createElement("div");
    
    const cb1 = document.createElement("input");
    cb1.name = "associatedTools";
    cb1.value = "tool-uuid-1";
    cb1.setAttribute("data-tool-name", "My Tool 1");
    
    const cb2 = document.createElement("input");
    cb2.name = "associatedTools";
    cb2.value = "tool-uuid-2";
    cb2.setAttribute("data-tool-name", "My Tool 2");
    
    container.appendChild(cb1);
    container.appendChild(cb2);
    
    updateToolMapping(container);
    
    expect(window.Admin.toolMapping["tool-uuid-1"]).toBe("My Tool 1");
    expect(window.Admin.toolMapping["tool-uuid-2"]).toBe("My Tool 2");
  });

  test("initializes toolMapping if not present", () => {
    delete window.Admin.toolMapping;
    
    const container = document.createElement("div");
    const cb = document.createElement("input");
    cb.name = "associatedTools";
    cb.value = "tool-123";
    cb.setAttribute("data-tool-name", "Test Tool");
    container.appendChild(cb);
    
    updateToolMapping(container);
    
    expect(window.Admin.toolMapping).toBeDefined();
    expect(window.Admin.toolMapping["tool-123"]).toBe("Test Tool");
  });
});

// ---------------------------------------------------------------------------
// updatePromptMapping
// ---------------------------------------------------------------------------
describe("updatePromptMapping", () => {
  test("creates prompt mapping from checkboxes with data attribute", () => {
    window.Admin.promptMapping = {};
    
    const container = document.createElement("div");
    
    const cb = document.createElement("input");
    cb.name = "associatedPrompts";
    cb.value = "prompt-uuid-1";
    cb.setAttribute("data-prompt-name", "My Prompt");
    
    container.appendChild(cb);
    
    updatePromptMapping(container);
    
    expect(window.Admin.promptMapping["prompt-uuid-1"]).toBe("My Prompt");
  });

  test("uses nextElementSibling text if no data attribute", () => {
    window.Admin.promptMapping = {};
    
    const container = document.createElement("div");
    
    const cb = document.createElement("input");
    cb.name = "associatedPrompts";
    cb.value = "prompt-uuid-2";
    
    const label = document.createElement("label");
    label.textContent = "  Prompt Label  ";
    
    container.appendChild(cb);
    container.appendChild(label);
    
    updatePromptMapping(container);
    
    expect(window.Admin.promptMapping["prompt-uuid-2"]).toBe("Prompt Label");
  });

  test("falls back to ID if no name available", () => {
    window.Admin.promptMapping = {};
    
    const container = document.createElement("div");
    
    const cb = document.createElement("input");
    cb.name = "associatedPrompts";
    cb.value = "prompt-uuid-3";
    
    container.appendChild(cb);
    
    updatePromptMapping(container);
    
    expect(window.Admin.promptMapping["prompt-uuid-3"]).toBe("prompt-uuid-3");
  });

  test("initializes promptMapping if not present", () => {
    delete window.Admin.promptMapping;
    
    const container = document.createElement("div");
    const cb = document.createElement("input");
    cb.name = "associatedPrompts";
    cb.value = "p-123";
    cb.setAttribute("data-prompt-name", "Test Prompt");
    container.appendChild(cb);
    
    updatePromptMapping(container);
    
    expect(window.Admin.promptMapping).toBeDefined();
    expect(window.Admin.promptMapping["p-123"]).toBe("Test Prompt");
  });
});

// ---------------------------------------------------------------------------
// updateResource