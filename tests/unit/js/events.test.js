/**
 * Unit tests for events.js module
 * Tests: Event handler initialization and dispatching
 */

import { describe, test, expect, vi, afterEach, beforeEach } from "vitest";

vi.mock("../../../mcpgateway/admin_ui/appState.js", () => ({
  AppState: {
    parameterCount: 0,
    getParameterCount: () => 0,
    isModalActive: vi.fn(() => false),
    currentTestTool: null,
    toolTestResultEditor: null,
    isInitialized: false,
    activeModals: new Set(),
    reset: vi.fn(),
    setLastActivePaginationRoot: vi.fn(),
    getLastActivePaginationRoot: vi.fn(() => null),
  },
}));

vi.mock("../../../mcpgateway/admin_ui/filters.js", () => ({ toggleViewPublic: vi.fn() }));
vi.mock("../../../mcpgateway/admin_ui/formFieldHandlers.js", () => ({ updateEditToolRequestTypes: vi.fn(), selectTeamFromSelector: vi.fn() }));
vi.mock("../../../mcpgateway/admin_ui/caCertificate.js", () => ({ initializeCACertUpload: vi.fn() }));
vi.mock("../../../mcpgateway/admin_ui/formValidation.js", () => ({ setupFormValidation: vi.fn() }));
vi.mock("../../../mcpgateway/admin_ui/gateways.js", () => ({ getSelectedGatewayIds: vi.fn(() => []), initGatewaySelect: vi.fn() }));
vi.mock("../../../mcpgateway/admin_ui/modals", () => ({ closeModal: vi.fn(), openModal: vi.fn() }));
vi.mock("../../../mcpgateway/admin_ui/monitoring.js", () => ({ initializeRealTimeMonitoring: vi.fn() }));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({ escapeHtml: vi.fn((s) => s || ""), validateInputName: vi.fn((s) => ({ valid: true, value: s })), validateUrl: vi.fn(() => ({ valid: true })) }));
vi.mock("../../../mcpgateway/admin_ui/servers.js", () => ({
  ensureAddStoreListeners: vi.fn(),
  updateToolMapping: vi.fn(),
  updatePromptMapping: vi.fn(),
  updateResourceMapping: vi.fn()
}));
vi.mock("../../../mcpgateway/admin_ui/tags.js", () => ({ initializeTagFiltering: vi.fn() }));
vi.mock("../../../mcpgateway/admin_ui/teams.js", () => ({ hideTeamEditModal: vi.fn(), initializeAddMembersForms: vi.fn(), initializePasswordValidation: vi.fn(), updateDefaultVisibility: vi.fn() }));
vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({ initializeTeamScopingMonitor: vi.fn() }));
vi.mock("../../../mcpgateway/admin_ui/tools.js", () => ({ cleanupToolTestState: vi.fn(), editTool: vi.fn(), enrichTool: vi.fn(), generateToolTestCases: vi.fn(), initToolSelect: vi.fn(), loadTools: vi.fn(), validateTool: vi.fn(), viewTool: vi.fn() }));
vi.mock("../../../mcpgateway/admin_ui/users.js", () => ({ hideUserEditModal: vi.fn(), performUserSearch: vi.fn(), registerAdminActionListeners: vi.fn() }));
vi.mock("../../../mcpgateway/admin_ui/initialization.js", () => ({ initializeCodeMirrorEditors: vi.fn(), initializeEventListeners: vi.fn(), initializeExportImport: vi.fn(), initializeGlobalSearch: vi.fn(), initializeSearchInputs: vi.fn(), initializeTabState: vi.fn(), initializeToolSelects: vi.fn(), registerReloadAllResourceSections: vi.fn(), setupBulkImportModal: vi.fn(), setupTooltipsWithAlpine: vi.fn() }));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({ createMemoizedInit: vi.fn((fn) => ({ init: fn, debouncedInit: vi.fn(), reset: vi.fn() })), safeGetElement: vi.fn((id) => document.getElementById(id)), showErrorMessage: vi.fn(), showSuccessMessage: vi.fn(), updateEditToolUrl: vi.fn() }));

beforeEach(() => {
  window.Admin = { chartRegistry: { destroyAll: vi.fn() }, generateBulkTestCases: vi.fn() };
  window.performance = { mark: vi.fn() };
  global.fetch = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.clearAllMocks();
  delete global.fetch;
});

describe("events.js - Module Import", () => {
  test("events module can be imported without errors", async () => {
    await expect(import("../../../mcpgateway/admin_ui/events.js")).resolves.toBeDefined();
  });
});

describe("events.js - DOMContentLoaded initialization", () => {
  test("calls setupTooltipsWithAlpine on DOMContentLoaded", async () => {
    const { setupTooltipsWithAlpine } = await import("../../../mcpgateway/admin_ui/initialization.js");
    document.dispatchEvent(new Event("DOMContentLoaded"));
    expect(setupTooltipsWithAlpine).toHaveBeenCalled();
  });

  test("calls initializeCodeMirrorEditors on DOMContentLoaded", async () => {
    const { initializeCodeMirrorEditors } = await import("../../../mcpgateway/admin_ui/initialization.js");
    document.dispatchEvent(new Event("DOMContentLoaded"));
    expect(initializeCodeMirrorEditors).toHaveBeenCalled();
  });

  test("calls registerReloadAllResourceSections on DOMContentLoaded", async () => {
    const { registerReloadAllResourceSections } = await import("../../../mcpgateway/admin_ui/initialization.js");
    document.dispatchEvent(new Event("DOMContentLoaded"));
    expect(registerReloadAllResourceSections).toHaveBeenCalled();
  });

  test("calls initializeToolSelects on DOMContentLoaded", async () => {
    const { initializeToolSelects } = await import("../../../mcpgateway/admin_ui/initialization.js");
    document.dispatchEvent(new Event("DOMContentLoaded"));
    expect(initializeToolSelects).toHaveBeenCalled();
  });

  test("calls ensureAddStoreListeners on DOMContentLoaded", async () => {
    const { ensureAddStoreListeners } = await import("../../../mcpgateway/admin_ui/servers.js");
    document.dispatchEvent(new Event("DOMContentLoaded"));
    expect(ensureAddStoreListeners).toHaveBeenCalled();
  });

  test("calls initializeEventListeners on DOMContentLoaded", async () => {
    const { initializeEventListeners } = await import("../../../mcpgateway/admin_ui/initialization.js");
    document.dispatchEvent(new Event("DOMContentLoaded"));
    expect(initializeEventListeners).toHaveBeenCalled();
  });

  test("calls initializeTabState on DOMContentLoaded", async () => {
    const { initializeTabState } = await import("../../../mcpgateway/admin_ui/initialization.js");
    document.dispatchEvent(new Event("DOMContentLoaded"));
    expect(initializeTabState).toHaveBeenCalled();
  });

  test("calls setupFormValidation on DOMContentLoaded", async () => {
    const { setupFormValidation } = await import("../../../mcpgateway/admin_ui/formValidation.js");
    document.dispatchEvent(new Event("DOMContentLoaded"));
    expect(setupFormValidation).toHaveBeenCalled();
  });

  test("handles setupBulkImportModal errors gracefully", async () => {
    const { setupBulkImportModal } = await import("../../../mcpgateway/admin_ui/initialization.js");
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    setupBulkImportModal.mockImplementation(() => { throw new Error("Bulk import setup failed"); });
    document.dispatchEvent(new Event("DOMContentLoaded"));
    expect(consoleSpy).toHaveBeenCalledWith("Error setting up bulk import modal:", expect.any(Error));
    consoleSpy.mockRestore();
  });

  test("handles initializeExportImport errors gracefully", async () => {
    const { initializeExportImport } = await import("../../../mcpgateway/admin_ui/initialization.js");
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    initializeExportImport.mockImplementation(() => { throw new Error("Export/import setup failed"); });
    document.dispatchEvent(new Event("DOMContentLoaded"));
    expect(consoleSpy).toHaveBeenCalledWith("Error setting up export/import functionality:", expect.any(Error));
    consoleSpy.mockRestore();
  });
});

describe("events.js - Tool selection", () => {
  beforeEach(async () => {
    await import("../../../mcpgateway/admin_ui/events.js");
    const wrapper = document.createElement("div");
    wrapper.id = "tool-ops-main-content-wrapper";
    const selectedList = document.createElement("div");
    selectedList.id = "selectedList";
    const selectedCount = document.createElement("span");
    selectedCount.id = "selectedCount";
    const searchBox = document.createElement("input");
    searchBox.id = "searchBox";
    document.body.appendChild(wrapper);
    document.body.appendChild(selectedList);
    document.body.appendChild(selectedCount);
    document.body.appendChild(searchBox);
    document.dispatchEvent(new Event("DOMContentLoaded"));
  });

  test("updates selected list when tool checkbox is checked", () => {
    const wrapper = document.getElementById("tool-ops-main-content-wrapper");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "tool-checkbox";
    checkbox.setAttribute("data-tool", "TestTool###tool-123");
    wrapper.appendChild(checkbox);
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    const selectedList = document.getElementById("selectedList");
    expect(selectedList.textContent).toContain("TestTool");
  });

  test("updates selected list when tool checkbox is unchecked", () => {
    const wrapper = document.getElementById("tool-ops-main-content-wrapper");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "tool-checkbox";
    checkbox.setAttribute("data-tool", "TestTool###tool-123");
    wrapper.appendChild(checkbox);
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    checkbox.checked = false;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    const selectedList = document.getElementById("selectedList");
    expect(selectedList.textContent).toBe("No tools selected");
  });
});

describe("events.js - Event delegation", () => {
  beforeEach(async () => {
    await import("../../../mcpgateway/admin_ui/events.js");
    const wrapper = document.createElement("div");
    wrapper.id = "tool-ops-main-content-wrapper";
    document.body.appendChild(wrapper);
    document.dispatchEvent(new Event("DOMContentLoaded"));
  });

  test("handles view-tool action via event delegation", async () => {
    const { viewTool } = await import("../../../mcpgateway/admin_ui/tools.js");
    const wrapper = document.getElementById("tool-ops-main-content-wrapper");
    const button = document.createElement("button");
    button.setAttribute("data-action", "view-tool");
    button.setAttribute("data-tool-id", "tool-123");
    wrapper.appendChild(button);
    vi.clearAllMocks();
    button.click();
    expect(viewTool).toHaveBeenCalledWith("tool-123");
  });

  test("handles edit-tool action via event delegation", async () => {
    const { editTool } = await import("../../../mcpgateway/admin_ui/tools.js");
    const wrapper = document.getElementById("tool-ops-main-content-wrapper");
    const button = document.createElement("button");
    button.setAttribute("data-action", "edit-tool");
    button.setAttribute("data-tool-id", "tool-456");
    wrapper.appendChild(button);
    vi.clearAllMocks();
    button.click();
    expect(editTool).toHaveBeenCalledWith("tool-456");
  });

  test("handles enrich-tool action via event delegation", async () => {
    const { enrichTool } = await import("../../../mcpgateway/admin_ui/tools.js");
    const wrapper = document.getElementById("tool-ops-main-content-wrapper");
    const button = document.createElement("button");
    button.setAttribute("data-action", "enrich-tool");
    button.setAttribute("data-tool-id", "tool-789");
    wrapper.appendChild(button);
    vi.clearAllMocks();
    button.click();
    expect(enrichTool).toHaveBeenCalledWith("tool-789");
  });

  test("handles validate-tool action via event delegation", async () => {
    const { validateTool } = await import("../../../mcpgateway/admin_ui/tools.js");
    const wrapper = document.getElementById("tool-ops-main-content-wrapper");
    const button = document.createElement("button");
    button.setAttribute("data-action", "validate-tool");
    button.setAttribute("data-tool-id", "tool-abc");
    wrapper.appendChild(button);
    vi.clearAllMocks();
    button.click();
    expect(validateTool).toHaveBeenCalledWith("tool-abc");
  });

  test("handles generate-tool-tests action via event delegation", async () => {
    const { generateToolTestCases } = await import("../../../mcpgateway/admin_ui/tools.js");
    const wrapper = document.getElementById("tool-ops-main-content-wrapper");
    const button = document.createElement("button");
    button.setAttribute("data-action", "generate-tool-tests");
    button.setAttribute("data-tool-id", "tool-def");
    wrapper.appendChild(button);
    vi.clearAllMocks();
    button.click();
    expect(generateToolTestCases).toHaveBeenCalledWith("tool-def");
  });
});

describe("events.js - Window event handlers", () => {
  test("handles beforeunload event - cleans up app state", async () => {
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    const { cleanupToolTestState } = await import("../../../mcpgateway/admin_ui/tools.js");
    await import("../../../mcpgateway/admin_ui/events.js");
    vi.clearAllMocks();
    window.dispatchEvent(new Event("beforeunload"));
    expect(AppState.reset).toHaveBeenCalled();
    expect(cleanupToolTestState).toHaveBeenCalled();
  });
});

describe("events.js - Keyboard event handling", () => {
  test("Escape key closes active modal", async () => {
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    const { closeModal } = await import("../../../mcpgateway/admin_ui/modals");
    AppState.activeModals = new Set(["test-modal"]);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(closeModal).toHaveBeenCalledWith("test-modal");
  });

  test("Escape key does nothing when no modals are active", async () => {
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    const { closeModal } = await import("../../../mcpgateway/admin_ui/modals");
    AppState.activeModals = new Set();
    vi.clearAllMocks();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(closeModal).not.toHaveBeenCalled();
  });
});

describe("events.js - Error handlers", () => {
  test("handles global errors", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await import("../../../mcpgateway/admin_ui/events.js");
    const error = new Error("Test error");
    window.dispatchEvent(new ErrorEvent("error", { error, filename: "test.js", lineno: 10 }));
    expect(consoleSpy).toHaveBeenCalledWith("Global error:", error, "test.js", 10);
    consoleSpy.mockRestore();
  });

  test("handles unhandled promise rejections", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { showErrorMessage } = await import("../../../mcpgateway/admin_ui/utils.js");
    await import("../../../mcpgateway/admin_ui/events.js");
    const reason = new Error("Promise rejection");
    const rejectedPromise = Promise.reject(reason);
    rejectedPromise.catch(() => {}); // Prevent unhandled rejection
    window.dispatchEvent(new PromiseRejectionEvent("unhandledrejection", { reason, promise: rejectedPromise }));
    expect(consoleSpy).toHaveBeenCalledWith("Unhandled promise rejection:", reason);
    expect(showErrorMessage).toHaveBeenCalledWith("An unexpected error occurred. Please refresh the page.");
    consoleSpy.mockRestore();
  });
});
