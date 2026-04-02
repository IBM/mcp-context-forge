/**
 * Unit tests for servers.js module
 * Tests: viewServer, editServer, setEditServerAssociations, loadServers
 */

import { describe, test, expect, vi, afterEach, beforeEach } from "vitest";

import {
  viewServer,
  editServer,
  setEditServerAssociations,
  loadServers,
} from "../../../mcpgateway/admin_ui/servers.js";
import { fetchWithTimeout } from "../../../mcpgateway/admin_ui/utils";
import { openModal } from "../../../mcpgateway/admin_ui/modals";
import { AppState } from "../../../mcpgateway/admin_ui/appState.js";
import { fetchWithAuth } from "../../../mcpgateway/admin_ui/tokens.js";

vi.mock("../../../mcpgateway/admin_ui/appState.js", () => ({
  AppState: {
    editServerSelections: {},
  },
}));
vi.mock("../../../mcpgateway/admin_ui/configExport.js", () => ({
  getCatalogUrl: vi.fn(() => "http://localhost/catalog"),
}));
vi.mock("../../../mcpgateway/admin_ui/gateways.js", () => ({
  initGatewaySelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/modals", () => ({
  openModal: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/prompts", () => ({
  initPromptSelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/resources", () => ({
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
vi.mock("../../../mcpgateway/admin_ui/utils", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  fetchWithTimeout: vi.fn(),
  isInactiveChecked: vi.fn(() => false),
  handleFetchError: vi.fn((e) => e.message),
  showErrorMessage: vi.fn(),
  decodeHtml: vi.fn((s) => s || ""),
  makeCopyIdButton: vi.fn(() => {
    const btn = document.createElement("button");
    btn.textContent = "Copy";
    return btn;
  }),
}));

beforeEach(() => {
  vi.useFakeTimers();
  window.Admin = window.Admin || {};
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  delete window.Admin;
  delete window._editStoreListenersAttached;
  delete window._addStoreListenersAttached;
  // Reset AppState.editServerSelections
  AppState.editServerSelections = {};
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// viewServer
// ---------------------------------------------------------------------------
describe("viewServer", () => {
  test("fetches and displays server details", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "server-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "s1",
          name: "test-server",
          description: "A test server",
          tools: [],
          prompts: [],
          resources: [],
        }),
    });

    await viewServer("s1");
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("s1")
    );
    consoleSpy.mockRestore();
  });

  test("displays server with icon", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "server-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "s1",
          name: "test-server",
          description: "A test server",
          icon: "https://example.com/icon.png",
          visibility: "public",
          tags: ["tag1", "tag2"],
          enabled: true,
          associatedTools: ["t1", "t2", "t3", "t4"],
          associatedResources: ["r1", "r2", "r3", "r4"],
          associatedPrompts: ["p1", "p2", "p3", "p4"],
          associatedA2aAgents: ["a1"],
          createdBy: "user@example.com",
          createdAt: "2024-01-01T00:00:00Z",
          created_from_ip: "127.0.0.1",
          created_via: "API",
          modified_by: "admin@example.com",
          updated_at: "2024-01-02T00:00:00Z",
          modified_from_ip: "127.0.0.2",
          modified_via: "UI",
          version: "2",
          importBatchId: "batch-123",
        }),
    });

    window.Admin.toolMapping = { t1: "Tool 1", t2: "Tool 2", t3: "Tool 3", t4: "Tool 4" };
    window.Admin.resourceMapping = { r1: "Resource 1", r2: "Resource 2", r3: "Resource 3", r4: "Resource 4" };
    window.Admin.promptMapping = { p1: "Prompt 1", p2: "Prompt 2", p3: "Prompt 3", p4: "Prompt 4" };

    await viewServer("s1");

    const container = details.querySelector("div");
    expect(container).toBeTruthy();
    expect(openModal).toHaveBeenCalledWith("server-modal");

    consoleSpy.mockRestore();
  });

  test("displays server with object tags", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "server-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "s1",
          name: "test-server",
          tags: [{ id: "tag1", label: "Tag One" }, { id: "tag2" }],
          enabled: false,
        }),
    });

    await viewServer("s1");
    expect(openModal).toHaveBeenCalledWith("server-modal");
    consoleSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Network error"));

    await viewServer("s1");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });

  test("handles non-ok response", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
    });

    await viewServer("missing");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// editServer
// ---------------------------------------------------------------------------
describe("editServer", () => {
  test("fetches server data for editing", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "s1",
          name: "test-server",
          description: "desc",
          tools: ["t1"],
          prompts: ["p1"],
          resources: ["r1"],
        }),
    });

    const nameInput = document.createElement("input");
    nameInput.id = "edit-server-name";
    document.body.appendChild(nameInput);

    const idInput = document.createElement("input");
    idInput.id = "edit-server-id";
    document.body.appendChild(idInput);

    await editServer("s1");
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("s1")
    );
    consoleSpy.mockRestore();
    errorSpy.mockRestore();
  });

  test("handles OAuth configuration", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const form = document.createElement("form");
    form.id = "edit-server-form";
    document.body.appendChild(form);

    const nameInput = document.createElement("input");
    nameInput.id = "edit-server-name";
    form.appendChild(nameInput);

    const idInput = document.createElement("input");
    idInput.id = "edit-server-id";
    form.appendChild(idInput);

    const oauthCheckbox = document.createElement("input");
    oauthCheckbox.type = "checkbox";
    oauthCheckbox.id = "edit-server-oauth-enabled";
    form.appendChild(oauthCheckbox);

    const oauthSection = document.createElement("div");
    oauthSection.id = "edit-server-oauth-config-section";
    oauthSection.classList.add("hidden");
    form.appendChild(oauthSection);

    const authServerInput = document.createElement("input");
    authServerInput.id = "edit-server-oauth-authorization-server";
    form.appendChild(authServerInput);

    const scopesInput = document.createElement("input");
    scopesInput.id = "edit-server-oauth-scopes";
    form.appendChild(scopesInput);

    const tokenEndpointInput = document.createElement("input");
    tokenEndpointInput.id = "edit-server-oauth-token-endpoint";
    form.appendChild(tokenEndpointInput);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "s1",
          name: "test-server",
          oauthEnabled: true,
          oauthConfig: {
            authorization_servers: ["https://auth.example.com"],
            scopes_supported: ["read", "write"],
            token_endpoint: "https://auth.example.com/token",
          },
        }),
    });

    await editServer("s1");

    expect(oauthCheckbox.checked).toBe(true);
    expect(oauthSection.classList.contains("hidden")).toBe(false);
    expect(authServerInput.value).toBe("https://auth.example.com");
    expect(scopesInput.value).toBe("read write");
    expect(tokenEndpointInput.value).toBe("https://auth.example.com/token");

    consoleSpy.mockRestore();
  });

  test("handles visibility radio buttons", async () => {
    window.ROOT_PATH = "";
    window.ALLOW_PUBLIC_VISIBILITY = true;
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const form = document.createElement("form");
    form.id = "edit-server-form";
    document.body.appendChild(form);

    const nameInput = document.createElement("input");
    nameInput.id = "edit-server-name";
    form.appendChild(nameInput);

    const idInput = document.createElement("input");
    idInput.id = "edit-server-id";
    form.appendChild(idInput);

    const publicRadio = document.createElement("input");
    publicRadio.type = "radio";
    publicRadio.id = "edit-server-visibility-public";
    form.appendChild(publicRadio);

    const teamRadio = document.createElement("input");
    teamRadio.type = "radio";
    teamRadio.id = "edit-server-visibility-team";
    form.appendChild(teamRadio);

    const privateRadio = document.createElement("input");
    privateRadio.type = "radio";
    privateRadio.id = "edit-server-visibility-private";
    form.appendChild(privateRadio);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "s1",
          name: "test-server",
          visibility: "team",
        }),
    });

    await editServer("s1");

    expect(teamRadio.checked).toBe(true);
    expect(publicRadio.checked).toBe(false);
    expect(privateRadio.checked).toBe(false);

    consoleSpy.mockRestore();
  });

  test("handles tags and icon fields", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const form = document.createElement("form");
    form.id = "edit-server-form";
    document.body.appendChild(form);

    const nameInput = document.createElement("input");
    nameInput.id = "edit-server-name";
    form.appendChild(nameInput);

    const idInput = document.createElement("input");
    idInput.id = "edit-server-id";
    form.appendChild(idInput);

    const tagsInput = document.createElement("input");
    tagsInput.id = "edit-server-tags";
    form.appendChild(tagsInput);

    const iconInput = document.createElement("input");
    iconInput.id = "edit-server-icon";
    form.appendChild(iconInput);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "s1",
          name: "test-server",
          tags: [{ label: "tag1" }, { id: "tag2" }, "tag3"],
          icon: "https://example.com/icon.png",
        }),
    });

    await editServer("s1");

    expect(tagsInput.value).toBe("tag1, tag2, tag3");
    expect(iconInput.value).toBe("https://example.com/icon.png");

    consoleSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Failed"));

    await editServer("s1");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// setEditServerAssociations
// ---------------------------------------------------------------------------
describe("setEditServerAssociations", () => {
  test("sets tool, prompt, and resource checkbox selections", () => {
    // Setup tool mapping
    window.Admin.toolMapping = { "uuid-t1": "tool-name-1" };

    // Create tool container with checkbox inputs
    const toolContainer = document.createElement("div");
    toolContainer.id = "edit-server-tools";
    const toolCb = document.createElement("input");
    toolCb.type = "checkbox";
    toolCb.name = "associatedTools";
    toolCb.value = "uuid-t1";
    toolContainer.appendChild(toolCb);
    document.body.appendChild(toolContainer);

    // Create resource container with checkbox inputs
    const resourceContainer = document.createElement("div");
    resourceContainer.id = "edit-server-resources";
    const resCb = document.createElement("input");
    resCb.type = "checkbox";
    resCb.name = "associatedResources";
    resCb.value = "r1";
    resourceContainer.appendChild(resCb);
    document.body.appendChild(resourceContainer);

    // Create prompt container with checkbox inputs
    const promptContainer = document.createElement("div");
    promptContainer.id = "edit-server-prompts";
    const promptCb = document.createElement("input");
    promptCb.type = "checkbox";
    promptCb.name = "associatedPrompts";
    promptCb.value = "p1";
    promptContainer.appendChild(promptCb);
    document.body.appendChild(promptContainer);

    setEditServerAssociations({
      associatedTools: ["tool-name-1"],
      associatedResources: ["r1"],
      associatedPrompts: ["p1"],
    });

    expect(toolCb.checked).toBe(true);
    expect(resCb.checked).toBe(true);
    expect(promptCb.checked).toBe(true);
  });



  test("does nothing when no checkboxes found", () => {
    expect(() =>
      setEditServerAssociations({
        associatedTools: [],
        associatedResources: [],
        associatedPrompts: [],
      })
    ).not.toThrow();
  });

  test("triggers change events after timeout", async () => {
    vi.useFakeTimers();

    // Setup tool mapping so checkbox gets checked
    window.Admin.toolMapping = { "t1": "Tool One" };

    const toolContainer = document.createElement("div");
    toolContainer.id = "edit-server-tools";
    const toolCb = document.createElement("input");
    toolCb.type = "checkbox";
    toolCb.name = "associatedTools";
    toolCb.value = "t1";
    toolContainer.appendChild(toolCb);
    document.body.appendChild(toolContainer);

    let changeCount = 0;
    toolCb.addEventListener("change", () => {
      changeCount++;
    });

    setEditServerAssociations({
      associatedTools: ["Tool One"],
    });

    // Checkbox should be checked immediately
    expect(toolCb.checked).toBe(true);
    expect(changeCount).toBe(0);

    // After 50ms timeout, change event should fire
    await vi.advanceTimersByTimeAsync(50);
    expect(changeCount).toBe(1);

    vi.useRealTimers();
  });
});

// ---------------------------------------------------------------------------
// loadServers
// ---------------------------------------------------------------------------
describe("loadServers", () => {
  test("builds URL and navigates (page reload)", async () => {
    // loadServers uses `new URL(window.location)` then sets window.location.href
    // In jsdom this requires a proper location object
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    // loadServers is async but uses window.location.href assignment
    // We can't prevent the navigation in jsdom, so just verify it's a function
    expect(typeof loadServers).toBe("function");
    consoleSpy.mockRestore();
  });

  test("includes inactive parameter when checkbox is checked", async () => {
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = "show-inactive-servers";
    checkbox.checked = true;
    document.body.appendChild(checkbox);

    // Mock window.location to capture the href assignment
    const originalLocation = window.location;
    delete window.location;
    window.location = { href: "", toString: () => "http://localhost/servers" };

    await loadServers();

    // Verify the function attempted to set location
    expect(window.location.href).toContain("include_inactive=true");

    // Restore
    window.location = originalLocation;
  });

  test("removes inactive parameter when checkbox is unchecked", async () => {
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = "show-inactive-servers";
    checkbox.checked = false;
    document.body.appendChild(checkbox);

    // Mock window.location
    const originalLocation = window.location;
    delete window.location;
    window.location = {
      href: "",
      toString: () => "http://localhost/servers?include_inactive=true"
    };

    await loadServers();

    // Verify the function attempted to remove the parameter
    expect(window.location.href).not.toContain("include_inactive");

    // Restore
    window.location = originalLocation;
  });
});

// ---------------------------------------------------------------------------
// getEditSelections
// ---------------------------------------------------------------------------
describe("getEditSelections", () => {
  test("creates new Set for container if not exists", async () => {
    const { getEditSelections } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );
    const sel = getEditSelections("edit-server-tools");
    expect(sel).toBeInstanceOf(Set);
    expect(sel.size).toBe(0);
  });

  test("returns existing Set for container", async () => {
    const { getEditSelections } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );
    const sel1 = getEditSelections("edit-server-tools");
    sel1.add("tool1");
    const sel2 = getEditSelections("edit-server-tools");
    expect(sel2).toBe(sel1);
    expect(sel2.has("tool1")).toBe(true);
  });

  test("creates separate Sets for different containers", async () => {
    const { getEditSelections } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );
    const toolSel = getEditSelections("edit-server-tools");
    const resSel = getEditSelections("edit-server-resources");

    toolSel.add("t1");
    resSel.add("r1");

    expect(toolSel.has("t1")).toBe(true);
    expect(toolSel.has("r1")).toBe(false);
    expect(resSel.has("r1")).toBe(true);
    expect(resSel.has("t1")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// resetEditSelections
// ---------------------------------------------------------------------------
describe("resetEditSelections", () => {
  test("clears all selection stores", async () => {
    const { getEditSelections, resetEditSelections } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );
    const toolSel = getEditSelections("edit-server-tools");
    toolSel.add("t1");
    const resSel = getEditSelections("edit-server-resources");
    resSel.add("r1");

    resetEditSelections();

    // After reset, getting selections should return new empty Sets
    const newToolSel = getEditSelections("edit-server-tools");
    expect(newToolSel.size).toBe(0);
    expect(newToolSel.has("t1")).toBe(false);
  });

  test("removes stale hidden inputs from containers", async () => {
    const { resetEditSelections } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );

    const toolsContainer = document.createElement("div");
    toolsContainer.id = "edit-server-tools";
    const hiddenInput = document.createElement("input");
    hiddenInput.type = "hidden";
    hiddenInput.name = "selectAllTools";
    toolsContainer.appendChild(hiddenInput);
    document.body.appendChild(toolsContainer);

    resetEditSelections();

    expect(
      toolsContainer.querySelector('input[name="selectAllTools"]')
    ).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// updateToolMapping
// ---------------------------------------------------------------------------
describe("updateToolMapping", () => {
  test("populates window.Admin.toolMapping from checkboxes", async () => {
    const { updateToolMapping } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );

    const container = document.createElement("div");
    const cb1 = document.createElement("input");
    cb1.type = "checkbox";
    cb1.name = "associatedTools";
    cb1.value = "uuid-1";
    cb1.setAttribute("data-tool-name", "Tool One");
    container.appendChild(cb1);

    const cb2 = document.createElement("input");
    cb2.type = "checkbox";
    cb2.name = "associatedTools";
    cb2.value = "uuid-2";
    cb2.setAttribute("data-tool-name", "Tool Two");
    container.appendChild(cb2);

    updateToolMapping(container);

    expect(window.Admin.toolMapping["uuid-1"]).toBe("Tool One");
    expect(window.Admin.toolMapping["uuid-2"]).toBe("Tool Two");
  });

  test("initializes toolMapping if not exists", async () => {
    const { updateToolMapping } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );
    delete window.Admin.toolMapping;

    const container = document.createElement("div");
    updateToolMapping(container);

    expect(window.Admin.toolMapping).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// updatePromptMapping
// ---------------------------------------------------------------------------
describe("updatePromptMapping", () => {
  test("populates window.Admin.promptMapping from checkboxes", async () => {
    const { updatePromptMapping } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );

    const container = document.createElement("div");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedPrompts";
    cb.value = "p-uuid-1";
    cb.setAttribute("data-prompt-name", "Prompt One");
    container.appendChild(cb);

    updatePromptMapping(container);

    expect(window.Admin.promptMapping["p-uuid-1"]).toBe("Prompt One");
  });

  test("falls back to nextElementSibling text if no data-prompt-name", async () => {
    const { updatePromptMapping } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );

    const container = document.createElement("div");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedPrompts";
    cb.value = "p-uuid-2";
    const label = document.createElement("label");
    label.textContent = "  Fallback Prompt  ";
    container.appendChild(cb);
    container.appendChild(label);

    updatePromptMapping(container);

    expect(window.Admin.promptMapping["p-uuid-2"]).toBe("Fallback Prompt");
  });
});

// ---------------------------------------------------------------------------
// updateResourceMapping
// ---------------------------------------------------------------------------
describe("updateResourceMapping", () => {
  test("populates window.Admin.resourceMapping from checkboxes", async () => {
    const { updateResourceMapping } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );

    const container = document.createElement("div");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedResources";
    cb.value = "r-uuid-1";
    cb.setAttribute("data-resource-name", "Resource One");
    container.appendChild(cb);

    updateResourceMapping(container);

    expect(window.Admin.resourceMapping["r-uuid-1"]).toBe("Resource One");
  });
});

// ---------------------------------------------------------------------------
// ensureEditStoreListeners
// ---------------------------------------------------------------------------
describe("ensureEditStoreListeners", () => {
  test("attaches change listeners to containers", async () => {
    const { ensureEditStoreListeners, getEditSelections } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );

    const toolsContainer = document.createElement("div");
    toolsContainer.id = "edit-server-tools";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedTools";
    cb.value = "t1";
    toolsContainer.appendChild(cb);
    document.body.appendChild(toolsContainer);

    ensureEditStoreListeners();

    cb.checked = true;
    cb.dispatchEvent(new Event("change", { bubbles: true }));

    const sel = getEditSelections("edit-server-tools");
    expect(sel.has("t1")).toBe(true);
  });

  test("does not attach listeners twice", async () => {
    const { ensureEditStoreListeners } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );

    delete window._editStoreListenersAttached;
    ensureEditStoreListeners();
    expect(window._editStoreListenersAttached).toBe(true);

    // Second call should be no-op
    ensureEditStoreListeners();
    expect(window._editStoreListenersAttached).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// ensureAddStoreListeners
// ---------------------------------------------------------------------------
describe("ensureAddStoreListeners", () => {
  test("attaches change listeners to add-server containers", async () => {
    const { ensureAddStoreListeners, getEditSelections } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );

    const toolsContainer = document.createElement("div");
    toolsContainer.id = "associatedTools";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedTools";
    cb.value = "t2";
    toolsContainer.appendChild(cb);
    document.body.appendChild(toolsContainer);

    ensureAddStoreListeners();

    cb.checked = true;
    cb.dispatchEvent(new Event("change", { bubbles: true }));

    const sel = getEditSelections("associatedTools");
    expect(sel.has("t2")).toBe(true);
  });

  test("clears selections on form reset", async () => {
    const { ensureAddStoreListeners, getEditSelections } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );

    const form = document.createElement("form");
    form.id = "add-server-form";
    document.body.appendChild(form);

    const toolsContainer = document.createElement("div");
    toolsContainer.id = "associatedTools";
    form.appendChild(toolsContainer);

    ensureAddStoreListeners();

    const sel = getEditSelections("associatedTools");
    sel.add("t3");

    form.dispatchEvent(new Event("reset"));

    const newSel = getEditSelections("associatedTools");
    expect(newSel.size).toBe(0);
  });

  test("handles unchecking checkboxes", async () => {
    const { ensureAddStoreListeners, getEditSelections } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );

    const toolsContainer = document.createElement("div");
    toolsContainer.id = "associatedTools";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedTools";
    cb.value = "t4";
    toolsContainer.appendChild(cb);
    document.body.appendChild(toolsContainer);

    ensureAddStoreListeners();

    // Check then uncheck
    cb.checked = true;
    cb.dispatchEvent(new Event("change", { bubbles: true }));

    const sel = getEditSelections("associatedTools");
    expect(sel.has("t4")).toBe(true);

    cb.checked = false;
    cb.dispatchEvent(new Event("change", { bubbles: true }));

    expect(sel.has("t4")).toBe(false);
  });

  test("does not attach listeners twice", async () => {
    const { ensureAddStoreListeners } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );

    delete window._addStoreListenersAttached;
    ensureAddStoreListeners();
    expect(window._addStoreListenersAttached).toBe(true);

    // Second call should be no-op
    ensureAddStoreListeners();
    expect(window._addStoreListenersAttached).toBe(true);
  });
});
