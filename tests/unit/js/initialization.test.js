/**
 * Comprehensive unit tests for initialization.js module
 */

import { describe, test, expect, vi, afterEach, beforeEach } from "vitest";

import {
  initializeCodeMirrorEditors,
  initializeToolSelects,
  initializeEventListeners,
  setupTabNavigation,
  registerFormListeners,
  initializeSearchInputs,
  initializeGlobalSearch,
  initializeTabState,
  setupSchemaModeHandlers,
  setupIntegrationTypeHandlers,
  setupBulkImportModal,
  initializeExportImport,
  setupTooltipsWithAlpine,
  registerReloadAllResourceSections,
} from "../../../mcpgateway/admin_ui/initialization.js";

// ---------------------------------------------------------------------------
// Import mocked modules for assertions
// ---------------------------------------------------------------------------
import { initToolSelect } from "../../../mcpgateway/admin_ui/tools.js";
import { initResourceSelect } from "../../../mcpgateway/admin_ui/resources.js";
import { initPromptSelect } from "../../../mcpgateway/admin_ui/prompts.js";
import {
  showTab,
  getVisibleSidebarTabs,
  isTabHidden,
  isAdminOnlyTab,
  isTabAvailable,
  resolveTabForNavigation,
  normalizeTabName,
  updateHashForTab,
  getUiHiddenSections,
} from "../../../mcpgateway/admin_ui/tabs.js";
import {
  fetchWithTimeout,
  isAdminUser,
} from "../../../mcpgateway/admin_ui/utils.js";
import {
  debouncedServerSideTokenSearch,
  getTeamNameById,
} from "../../../mcpgateway/admin_ui/tokens.js";
import {
  getPanelSearchStateFromUrl,
  queueSearchablePanelReload,
  runGlobalSearch,
  closeGlobalSearchModal,
  navigateToGlobalSearchResult,
  openGlobalSearchModal,
} from "../../../mcpgateway/admin_ui/search.js";
import {
  handleGatewayFormSubmit,
} from "../../../mcpgateway/admin_ui/formSubmitHandlers.js";
import { handleAuthTypeSelection } from "../../../mcpgateway/admin_ui/auth.js";
import {
  handleAddParameter,
  handleAddPassthrough,
  updateRequestTypeOptions,
  updateEditToolRequestTypes,
  updateSchemaPreview,
} from "../../../mcpgateway/admin_ui/formFieldHandlers.js";
import { openModal, closeModal } from "../../../mcpgateway/admin_ui/modals.js";
import {
  handleExportAll,
  handleExportSelected,
  handleFileSelect,
  handleDragOver,
  handleFileDrop,
  handleDragLeave,
  handleImport,
  loadRecentImports,
} from "../../../mcpgateway/admin_ui/fileTransfer.js";
import {
  safeSetInnerHTML,
} from "../../../mcpgateway/admin_ui/security.js";

// ---------------------------------------------------------------------------
// Mock all dependencies
// ---------------------------------------------------------------------------

vi.mock("../../../mcpgateway/admin_ui/auth.js", () => ({
  handleAuthTypeChange: vi.fn(),
  handleAuthTypeSelection: vi.fn(),
  handleEditOAuthGrantTypeChange: vi.fn(),
  handleOAuthGrantTypeChange: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/fileTransfer.js", () => ({
  handleDragLeave: vi.fn(),
  handleDragOver: vi.fn(),
  handleExportAll: vi.fn(),
  handleExportSelected: vi.fn(),
  handleFileDrop: vi.fn(),
  handleFileSelect: vi.fn(),
  handleImport: vi.fn(),
  loadRecentImports: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/formFieldHandlers.js", () => ({
  handleAddParameter: vi.fn(),
  handleAddPassthrough: vi.fn(),
  updateEditToolRequestTypes: vi.fn(),
  updateRequestTypeOptions: vi.fn(),
  updateSchemaPreview: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/formSubmitHandlers.js", () => ({
  handleA2AFormSubmit: vi.fn(),
  handleEditA2AAgentFormSubmit: vi.fn(),
  handleEditGatewayFormSubmit: vi.fn(),
  handleEditPromptFormSubmit: vi.fn(),
  handleEditResFormSubmit: vi.fn(),
  handleEditServerFormSubmit: vi.fn(),
  handleEditToolFormSubmit: vi.fn(),
  handleGatewayFormSubmit: vi.fn(),
  handleGrpcServiceFormSubmit: vi.fn(),
  handlePromptFormSubmit: vi.fn(),
  handleResourceFormSubmit: vi.fn(),
  handleServerFormSubmit: vi.fn(),
  handleToolFormSubmit: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/modals.js", () => ({
  closeModal: vi.fn(),
  openModal: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/prompts.js", () => ({
  initPromptSelect: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/resources.js", () => ({
  initResourceSelect: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  safeSetInnerHTML: vi.fn((el, html) => {
    if (el) el.innerHTML = html;
  }),
}));

vi.mock("../../../mcpgateway/admin_ui/tabs.js", () => ({
  getDefaultTabName: vi.fn(() => null),
  getUiHiddenSections: vi.fn(() => new Set()),
  getVisibleSidebarTabs: vi.fn(() => []),
  isAdminOnlyTab: vi.fn(() => false),
  isTabAvailable: vi.fn(() => true),
  isTabHidden: vi.fn(() => false),
  normalizeTabName: vi.fn(() => null),
  resolveTabForNavigation: vi.fn(() => null),
  showTab: vi.fn(),
  updateHashForTab: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/tools.js", () => ({
  initToolSelect: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  fetchWithTimeout: vi.fn(() =>
    Promise.resolve({
      ok: true,
      text: () => Promise.resolve("<div>ok</div>"),
      json: () => Promise.resolve({ success: true, message: "ok" }),
    })
  ),
  isAdminUser: vi.fn(() => true),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));

vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  debouncedServerSideTokenSearch: vi.fn(),
  getTeamNameById: vi.fn(() => null),
}));

vi.mock("../../../mcpgateway/admin_ui/search.js", () => ({
  closeGlobalSearchModal: vi.fn(),
  getPanelSearchStateFromUrl: vi.fn(() => ({ query: "", tags: "" })),
  navigateToGlobalSearchResult: vi.fn(),
  openGlobalSearchModal: vi.fn(),
  queueSearchablePanelReload: vi.fn(),
  renderGlobalSearchMessage: vi.fn((message) => {
    const container = document.getElementById("global-search-results");
    if (container) {
      container.textContent = message;
    }
  }),
  runGlobalSearch: vi.fn(),
  serverSideEditPromptsSearch: vi.fn(),
  serverSideEditResourcesSearch: vi.fn(),
  serverSideEditToolSearch: vi.fn(),
  serverSidePromptSearch: vi.fn(),
  serverSideResourceSearch: vi.fn(),
  serverSideToolSearch: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/filters.js", () => ({
  filterA2AAgentsTable: vi.fn(),
  filterGatewaysTable: vi.fn(),
  filterPromptsTable: vi.fn(),
  filterResourcesTable: vi.fn(),
  filterServerTable: vi.fn(),
  filterToolsTable: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/constants.js", () => ({
  PANEL_SEARCH_CONFIG: {
    tools: {
      searchInputId: "tools-search-input",
      tagInputId: "tools-tag-filter",
      tableName: "tools",
    },
    resources: {
      searchInputId: "resources-search-input",
      tagInputId: "resources-tag-filter",
      tableName: "resources",
    },
  },
}));

// ---------------------------------------------------------------------------
// Global beforeEach / afterEach
// ---------------------------------------------------------------------------

beforeEach(() => {
  window.Admin = {};
  window.exportImportInitialized = false;
  vi.useFakeTimers();
  // Mock window.location.reload to prevent jsdom errors
  Object.defineProperty(window, "location", {
    value: { ...window.location, reload: vi.fn(), href: "" },
    writable: true,
    configurable: true,
  });
  // Reset fetchWithTimeout to default implementation each test
  fetchWithTimeout.mockImplementation(() =>
    Promise.resolve({
      ok: true,
      text: () => Promise.resolve("<div>ok</div>"),
      json: () => Promise.resolve({ success: true, message: "ok" }),
    })
  );
});

afterEach(() => {
  document.body.innerHTML = "";
  document.documentElement.className = "";
  delete window.ROOT_PATH;
  delete window.CodeMirror;
  delete window.Admin;
  delete window.exportImportInitialized;
  delete window.__globalSearchHotkeysBound;
  delete window.Alpine;
  delete window.htmx;
  delete window.__initialSectionMarkup;
  vi.clearAllMocks();
  vi.useRealTimers();
});

// Silence console noise globally for all tests
beforeEach(() => {
  vi.spyOn(console, "log").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
  vi.spyOn(console, "error").mockImplementation(() => {});
});

// ===========================================================================
// initializeCodeMirrorEditors
// ===========================================================================
describe("initializeCodeMirrorEditors", () => {
  test("warns for each editor config when CodeMirror is not available", () => {
    delete window.CodeMirror;
    initializeCodeMirrorEditors();
    expect(console.warn).toHaveBeenCalled();
  });

  test("does not throw when CodeMirror is missing", () => {
    delete window.CodeMirror;
    expect(() => initializeCodeMirrorEditors()).not.toThrow();
  });

  test("creates editor instance when element and CodeMirror are both present", () => {
    const mockEditor = { setValue: vi.fn(), getValue: vi.fn() };
    window.CodeMirror = { fromTextArea: vi.fn(() => mockEditor) };

    const textarea = document.createElement("textarea");
    textarea.id = "schema-editor";
    document.body.appendChild(textarea);

    // safeGetElement is mocked to use getElementById
    initializeCodeMirrorEditors();

    expect(window.CodeMirror.fromTextArea).toHaveBeenCalledWith(
      textarea,
      expect.objectContaining({ mode: "application/json" })
    );
    expect(window.schemaEditor).toBe(mockEditor);
  });

  test("stores editor instance on window[varName]", () => {
    const mockEditor = { setValue: vi.fn() };
    window.CodeMirror = { fromTextArea: vi.fn(() => mockEditor) };

    const textarea = document.createElement("textarea");
    textarea.id = "headers-editor";
    document.body.appendChild(textarea);

    initializeCodeMirrorEditors();

    expect(window.headersEditor).toBe(mockEditor);
  });

  test("skips gracefully when element missing but CodeMirror present", () => {
    window.CodeMirror = { fromTextArea: vi.fn() };
    // No DOM elements added
    initializeCodeMirrorEditors();
    expect(window.CodeMirror.fromTextArea).not.toHaveBeenCalled();
    expect(console.warn).toHaveBeenCalled();
  });

  test("catches and logs errors when CodeMirror.fromTextArea throws", () => {
    window.CodeMirror = {
      fromTextArea: vi.fn(() => {
        throw new Error("CM init failure");
      }),
    };

    const textarea = document.createElement("textarea");
    textarea.id = "schema-editor";
    document.body.appendChild(textarea);

    expect(() => initializeCodeMirrorEditors()).not.toThrow();
    expect(console.error).toHaveBeenCalled();
  });
});

// ===========================================================================
// initializeToolSelects
// ===========================================================================
describe("initializeToolSelects", () => {
  test("calls initToolSelect at least once", () => {
    initializeToolSelects();
    expect(initToolSelect).toHaveBeenCalled();
  });

  test("calls initResourceSelect at least once", () => {
    initializeToolSelects();
    expect(initResourceSelect).toHaveBeenCalled();
  });

  test("calls initPromptSelect at least once", () => {
    initializeToolSelects();
    expect(initPromptSelect).toHaveBeenCalled();
  });
});

// ===========================================================================
// setupTabNavigation
// ===========================================================================
describe("setupTabNavigation", () => {
  test("skips tab element with onclick attribute", () => {
    getVisibleSidebarTabs.mockReturnValue(["tools"]);
    isTabHidden.mockReturnValue(false);
    isAdminOnlyTab.mockReturnValue(false);
    isTabAvailable.mockReturnValue(true);

    const tabEl = document.createElement("a");
    tabEl.id = "tab-tools";
    tabEl.setAttribute("onclick", "return false;");
    document.body.appendChild(tabEl);

    setupTabNavigation();

    // If onclick is present we should NOT add a click listener, so showTab won't be called
    tabEl.click();
    expect(showTab).not.toHaveBeenCalled();
  });

  test("skips tab element with data-tab-bound='true'", () => {
    getVisibleSidebarTabs.mockReturnValue(["tools"]);
    isTabHidden.mockReturnValue(false);
    isAdminOnlyTab.mockReturnValue(false);
    isTabAvailable.mockReturnValue(true);

    const tabEl = document.createElement("a");
    tabEl.id = "tab-tools";
    tabEl.dataset.tabBound = "true";
    document.body.appendChild(tabEl);

    setupTabNavigation();

    tabEl.click();
    expect(showTab).not.toHaveBeenCalled();
  });

  test("skips isTabHidden tabs", () => {
    getVisibleSidebarTabs.mockReturnValue(["hidden-tab"]);
    isTabHidden.mockReturnValue(true);

    setupTabNavigation();

    expect(showTab).not.toHaveBeenCalled();
  });

  test("skips admin-only tabs when isAdminUser() is false", () => {
    getVisibleSidebarTabs.mockReturnValue(["admin-tab"]);
    isTabHidden.mockReturnValue(false);
    isAdminUser.mockReturnValue(false);
    isAdminOnlyTab.mockReturnValue(true);

    setupTabNavigation();

    expect(showTab).not.toHaveBeenCalled();
  });

  test("skips tabs where isTabAvailable returns false", () => {
    getVisibleSidebarTabs.mockReturnValue(["tools"]);
    isTabHidden.mockReturnValue(false);
    isAdminOnlyTab.mockReturnValue(false);
    isTabAvailable.mockReturnValue(false);

    setupTabNavigation();

    expect(showTab).not.toHaveBeenCalled();
  });

  test("binds click listener on normal available tab", () => {
    getVisibleSidebarTabs.mockReturnValue(["tools"]);
    isTabHidden.mockReturnValue(false);
    isAdminUser.mockReturnValue(true);
    isAdminOnlyTab.mockReturnValue(false);
    isTabAvailable.mockReturnValue(true);

    const tabEl = document.createElement("a");
    tabEl.id = "tab-tools";
    document.body.appendChild(tabEl);

    setupTabNavigation();

    expect(tabEl.dataset.tabBound).toBe("true");
    tabEl.click();
    expect(showTab).toHaveBeenCalledWith("tools");
  });

  test("handles missing tab element gracefully", () => {
    getVisibleSidebarTabs.mockReturnValue(["nonexistent"]);
    isTabHidden.mockReturnValue(false);
    isAdminOnlyTab.mockReturnValue(false);
    isTabAvailable.mockReturnValue(true);
    // No DOM element added for "tab-nonexistent"

    expect(() => setupTabNavigation()).not.toThrow();
    expect(showTab).not.toHaveBeenCalled();
  });
});

// ===========================================================================
// registerFormListeners
// ===========================================================================
describe("registerFormListeners", () => {
  test("returns without error when form not found", () => {
    expect(() =>
      registerFormListeners("nonexistent-form", vi.fn())
    ).not.toThrow();
  });

  test("attaches submit listener when form found", () => {
    const form = document.createElement("form");
    form.id = "test-form";
    document.body.appendChild(form);

    const handler = vi.fn();
    registerFormListeners("test-form", handler);

    const evt = new Event("submit");
    form.dispatchEvent(evt);
    expect(handler).toHaveBeenCalledWith(evt);
  });

  test("does not attach click when includeRefreshOnClick is false", () => {
    const form = document.createElement("form");
    form.id = "test-form-no-click";
    document.body.appendChild(form);

    const handler = vi.fn();
    registerFormListeners("test-form-no-click", handler, false);

    // Click the form – no additional behavior expected
    form.click();
    // Handler should NOT have been called from click (only from submit)
    expect(handler).not.toHaveBeenCalled();
  });

  test("attaches click when includeRefreshOnClick is true", () => {
    const form = document.createElement("form");
    form.id = "test-form-click";
    document.body.appendChild(form);

    const handler = vi.fn();
    registerFormListeners("test-form-click", handler, true);

    // Should not throw on click
    expect(() => form.click()).not.toThrow();
  });
});

// ===========================================================================
// initializeEventListeners
// ===========================================================================
describe("initializeEventListeners", () => {
  test("calls setupTabNavigation (getVisibleSidebarTabs is called)", () => {
    initializeEventListeners();
    expect(getVisibleSidebarTabs).toHaveBeenCalled();
  });

  test("htmx:beforeRequest event with matching target.id logs message", () => {
    initializeEventListeners();

    const mockTarget = { id: "tab-version-info" };
    const event = new CustomEvent("htmx:beforeRequest", {
      detail: { target: mockTarget },
    });
    document.body.dispatchEvent(event);

    expect(console.log).toHaveBeenCalledWith(
      expect.stringContaining("version info")
    );
  });

  test("htmx:afterSwap event with matching target.id logs message", () => {
    initializeEventListeners();

    const mockTarget = { id: "version-info-panel" };
    const event = new CustomEvent("htmx:afterSwap", {
      detail: { target: mockTarget },
    });
    document.body.dispatchEvent(event);

    expect(console.log).toHaveBeenCalledWith(
      expect.stringContaining("version-info-panel")
    );
  });

  test("attaches auth-type change handler that triggers handleAuthTypeSelection", () => {
    const select = document.createElement("select");
    select.id = "auth-type";
    select.innerHTML = '<option value="basic">basic</option>';
    document.body.appendChild(select);

    initializeEventListeners();
    select.dispatchEvent(new Event("change"));

    expect(handleAuthTypeSelection).toHaveBeenCalled();
  });

  test("attaches add-gateway-form submit handler", () => {
    const form = document.createElement("form");
    form.id = "add-gateway-form";
    document.body.appendChild(form);

    initializeEventListeners();
    form.dispatchEvent(new Event("submit"));

    expect(handleGatewayFormSubmit).toHaveBeenCalled();
  });

  test("attaches add-parameter-btn click handler", () => {
    const btn = document.createElement("button");
    btn.id = "add-parameter-btn";
    document.body.appendChild(btn);

    initializeEventListeners();
    btn.click();

    expect(handleAddParameter).toHaveBeenCalled();
  });

  test("attaches add-passthrough-btn click handler", () => {
    const btn = document.createElement("button");
    btn.id = "add-passthrough-btn";
    document.body.appendChild(btn);

    initializeEventListeners();
    btn.click();

    expect(handleAddPassthrough).toHaveBeenCalled();
  });
});

// ===========================================================================
// initializeSearchInputs
// ===========================================================================
describe("initializeSearchInputs", () => {
  test("does not throw when search inputs are absent", () => {
    expect(() => initializeSearchInputs()).not.toThrow();
  });

  test("clones and replaces existing search inputs from PANEL_SEARCH_CONFIG", () => {
    const input = document.createElement("input");
    input.id = "tools-search-input";
    document.body.appendChild(input);

    initializeSearchInputs();

    // After replacement, the original input reference is gone from DOM
    // but a new one with the same id should exist
    const found = document.getElementById("tools-search-input");
    expect(found).not.toBeNull();
    expect(found).not.toBe(input); // It was replaced
  });

  test("attaches input listener that calls queueSearchablePanelReload", () => {
    const input = document.createElement("input");
    input.id = "tools-search-input";
    document.body.appendChild(input);

    initializeSearchInputs();

    const newInput = document.getElementById("tools-search-input");
    newInput.dispatchEvent(new Event("input"));

    expect(queueSearchablePanelReload).toHaveBeenCalledWith("tools", 250);
  });

  test("sets search input value from getPanelSearchStateFromUrl when query is non-empty", () => {
    getPanelSearchStateFromUrl.mockReturnValue({ query: "myquery", tags: "" });

    const input = document.createElement("input");
    input.id = "tools-search-input";
    document.body.appendChild(input);

    initializeSearchInputs();

    const newInput = document.getElementById("tools-search-input");
    expect(newInput.value).toBe("myquery");
  });

  test("sets tag input value from search state when tags present", () => {
    getPanelSearchStateFromUrl.mockReturnValue({ query: "", tags: "mytag" });

    const input = document.createElement("input");
    input.id = "tools-search-input";
    document.body.appendChild(input);

    const tagInput = document.createElement("input");
    tagInput.id = "tools-tag-filter";
    document.body.appendChild(tagInput);

    initializeSearchInputs();

    expect(tagInput.value).toBe("mytag");
  });

  test("attaches debouncedServerSideTokenSearch to tokens-search-input", () => {
    const tokensInput = document.createElement("input");
    tokensInput.id = "tokens-search-input";
    document.body.appendChild(tokensInput);

    initializeSearchInputs();

    const newInput = document.getElementById("tokens-search-input");
    newInput.value = "search term";
    newInput.dispatchEvent(new Event("input"));

    expect(debouncedServerSideTokenSearch).toHaveBeenCalledWith("search term");
  });

  test("handles missing tokens-search-input gracefully", () => {
    // No tokens-search-input in DOM
    expect(() => initializeSearchInputs()).not.toThrow();
  });
});

// ===========================================================================
// initializeGlobalSearch
// ===========================================================================
describe("initializeGlobalSearch", () => {
  afterEach(() => {
    delete window.__globalSearchHotkeysBound;
  });

  test("does nothing when global-search-input is absent", () => {
    initializeGlobalSearch();
    expect(runGlobalSearch).not.toHaveBeenCalled();
  });

  test("attaches input listener that calls runGlobalSearch with debounce", async () => {
    const input = document.createElement("input");
    input.id = "global-search-input";
    document.body.appendChild(input);

    initializeGlobalSearch();

    input.value = "hello";
    input.dispatchEvent(new InputEvent("input", { target: input }));

    await vi.runAllTimersAsync();

    expect(runGlobalSearch).toHaveBeenCalledWith("hello");
  });

  test("Escape keydown calls closeGlobalSearchModal", () => {
    const input = document.createElement("input");
    input.id = "global-search-input";
    document.body.appendChild(input);

    initializeGlobalSearch();

    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
    );

    expect(closeGlobalSearchModal).toHaveBeenCalled();
  });

  test("Enter keydown with first result calls navigateToGlobalSearchResult", () => {
    const input = document.createElement("input");
    input.id = "global-search-input";
    input.value = "query";
    document.body.appendChild(input);

    const resultsContainer = document.createElement("div");
    resultsContainer.id = "global-search-results";
    const resultItem = document.createElement("div");
    resultItem.className = "global-search-result-item";
    resultsContainer.appendChild(resultItem);
    document.body.appendChild(resultsContainer);

    initializeGlobalSearch();

    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true })
    );

    expect(navigateToGlobalSearchResult).toHaveBeenCalledWith(resultItem);
  });

  test("Enter keydown with no result does nothing", () => {
    const input = document.createElement("input");
    input.id = "global-search-input";
    input.value = "query";
    document.body.appendChild(input);

    initializeGlobalSearch();

    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true })
    );

    expect(navigateToGlobalSearchResult).not.toHaveBeenCalled();
  });

  test("Enter keydown with empty/whitespace query prompts for a term and prevents default", async () => {
    const { renderGlobalSearchMessage } = await import(
      "../../../mcpgateway/admin_ui/search.js"
    );
    const input = document.createElement("input");
    input.id = "global-search-input";
    input.value = "   ";
    document.body.appendChild(input);

    const resultsContainer = document.createElement("div");
    resultsContainer.id = "global-search-results";
    const resultItem = document.createElement("div");
    resultItem.className = "global-search-result-item";
    resultsContainer.appendChild(resultItem);
    document.body.appendChild(resultsContainer);

    initializeGlobalSearch();

    const event = new KeyboardEvent("keydown", {
      key: "Enter",
      bubbles: true,
      cancelable: true,
    });
    input.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
    expect(renderGlobalSearchMessage).toHaveBeenCalledWith(
      "Please enter a search term.",
    );
    expect(navigateToGlobalSearchResult).not.toHaveBeenCalled();
  });

  test("does not double-bind when listenerAttached already set", () => {
    const input = document.createElement("input");
    input.id = "global-search-input";
    input.dataset.listenerAttached = "true";
    document.body.appendChild(input);

    initializeGlobalSearch();
    initializeGlobalSearch();

    input.value = "x";
    input.dispatchEvent(new InputEvent("input"));
    // Since listener was not attached (listenerAttached was already true), runGlobalSearch not debounced-called yet
    // (won't call since listener skipped)
    expect(runGlobalSearch).not.toHaveBeenCalled();
  });

  test("registers document Ctrl+K hotkey to openGlobalSearchModal", () => {
    delete window.__globalSearchHotkeysBound;

    initializeGlobalSearch();

    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true })
    );

    expect(openGlobalSearchModal).toHaveBeenCalled();
  });

  test("document Escape closes modal when modal is visible", () => {
    delete window.__globalSearchHotkeysBound;

    const modal = document.createElement("div");
    modal.id = "global-search-modal";
    // No 'hidden' class means it's visible
    document.body.appendChild(modal);

    initializeGlobalSearch();

    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
    );

    expect(closeGlobalSearchModal).toHaveBeenCalled();
  });

  test("does not re-register hotkeys when __globalSearchHotkeysBound is already true", () => {
    // Clear any accumulated mock calls and set bound flag BEFORE calling init
    vi.clearAllMocks();
    window.__globalSearchHotkeysBound = true;

    initializeGlobalSearch();

    // Since __globalSearchHotkeysBound was already true, no new listener was registered.
    // The Ctrl+K dispatch here should NOT trigger openGlobalSearchModal via a newly
    // registered listener (the initializeGlobalSearch call above registered nothing).
    // However, we cannot remove previously-registered document listeners from other tests,
    // so we just verify that initializeGlobalSearch() itself doesn't call openGlobalSearchModal.
    expect(openGlobalSearchModal).not.toHaveBeenCalled();
  });
});

// ===========================================================================
// initializeTabState
// ===========================================================================
describe("initializeTabState", () => {
  test("calls showTab with resolvedTab when available", () => {
    resolveTabForNavigation.mockReturnValue("tools");

    initializeTabState();

    expect(showTab).toHaveBeenCalledWith("tools");
  });

  test("warns when no tab is resolved", () => {
    resolveTabForNavigation.mockReturnValue(null);

    initializeTabState();

    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining("No available tabs")
    );
  });

  test("calls updateHashForTab when initialHashTab differs from initialTab", () => {
    normalizeTabName.mockReturnValue("old-tab");
    resolveTabForNavigation.mockReturnValue("tools");

    initializeTabState();

    expect(updateHashForTab).toHaveBeenCalledWith("tools");
  });

  test("does not call updateHashForTab when hash matches resolved tab", () => {
    normalizeTabName.mockReturnValue("tools");
    resolveTabForNavigation.mockReturnValue("tools");

    initializeTabState();

    expect(updateHashForTab).not.toHaveBeenCalled();
  });

  test("checkbox state set from namespaced URL param (tools_inactive=true)", () => {
    resolveTabForNavigation.mockReturnValue(null);
    // Set URL search params
    const originalSearch = window.location.search;
    Object.defineProperty(window, "location", {
      value: { ...window.location, search: "?tools_inactive=true", hash: "" },
      writable: true,
      configurable: true,
    });

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = "show-inactive-tools";
    document.body.appendChild(checkbox);

    initializeTabState();

    expect(checkbox.checked).toBe(true);

    window.location = { ...window.location, search: originalSearch };
  });

  test("checkbox state falls back to legacy include_inactive param", () => {
    resolveTabForNavigation.mockReturnValue(null);
    Object.defineProperty(window, "location", {
      value: { ...window.location, search: "?include_inactive=true", hash: "" },
      writable: true,
      configurable: true,
    });

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = "show-inactive-tools";
    document.body.appendChild(checkbox);

    initializeTabState();

    expect(checkbox.checked).toBe(true);

    window.location = { ...window.location, search: "" };
  });

  test("show-inactive-toggle is disabled when hx-target not in DOM", () => {
    resolveTabForNavigation.mockReturnValue(null);

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "show-inactive-toggle";
    checkbox.setAttribute("hx-target", "#nonexistent-target");
    document.body.appendChild(checkbox);

    initializeTabState();

    expect(checkbox.disabled).toBe(true);
  });

  test("htmx:afterSettle re-enables toggle when target is now present", () => {
    resolveTabForNavigation.mockReturnValue(null);

    const target = document.createElement("div");
    target.id = "my-table";
    document.body.appendChild(target);

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "show-inactive-toggle";
    checkbox.setAttribute("hx-target", "#my-table");
    checkbox.disabled = true;
    document.body.appendChild(checkbox);

    initializeTabState();

    // Fire htmx:afterSettle event
    window.dispatchEvent(new Event("htmx:afterSettle"));

    expect(checkbox.disabled).toBe(false);
  });

  test("pre-loads version-info panel when admin and initialTab is version-info", async () => {
    resolveTabForNavigation.mockReturnValue("version-info");
    isAdminUser.mockReturnValue(true);
    window.ROOT_PATH = "/test";

    const panel = document.createElement("div");
    panel.id = "version-info-panel";
    panel.innerHTML = "";
    document.body.appendChild(panel);

    initializeTabState();

    await vi.runAllTimersAsync();

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("/version?partial=true")
    );
  });

  test("pre-loads maintenance panel when admin and initialTab is maintenance", async () => {
    resolveTabForNavigation.mockReturnValue("maintenance");
    isAdminUser.mockReturnValue(true);
    window.ROOT_PATH = "/test";

    const panel = document.createElement("div");
    panel.id = "maintenance-panel";
    panel.innerHTML = "";
    document.body.appendChild(panel);

    initializeTabState();

    await vi.runAllTimersAsync();

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("/admin/maintenance/partial")
    );
  });

  test("pre-load fetch failure shows error div in panel", async () => {
    resolveTabForNavigation.mockReturnValue("version-info");
    isAdminUser.mockReturnValue(true);
    window.ROOT_PATH = "/test";

    fetchWithTimeout.mockRejectedValue(new Error("network error"));

    const panel = document.createElement("div");
    panel.id = "version-info-panel";
    panel.innerHTML = "";
    document.body.appendChild(panel);

    initializeTabState();

    await vi.runAllTimersAsync();

    expect(panel.querySelector(".text-red-600")).not.toBeNull();
  });

  test("maintenance fetch non-ok response shows error div", async () => {
    resolveTabForNavigation.mockReturnValue("maintenance");
    isAdminUser.mockReturnValue(true);
    window.ROOT_PATH = "/test";

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve(""),
    });

    const panel = document.createElement("div");
    panel.id = "maintenance-panel";
    panel.innerHTML = "";
    document.body.appendChild(panel);

    initializeTabState();

    await vi.runAllTimersAsync();

    expect(panel.querySelector(".text-red-600")).not.toBeNull();
  });

  test("maintenance fetch 403 shows platform admin error message", async () => {
    resolveTabForNavigation.mockReturnValue("maintenance");
    isAdminUser.mockReturnValue(true);
    window.ROOT_PATH = "/test";

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 403,
      text: () => Promise.resolve(""),
    });

    const panel = document.createElement("div");
    panel.id = "maintenance-panel";
    panel.innerHTML = "";
    document.body.appendChild(panel);

    initializeTabState();

    await vi.runAllTimersAsync();

    expect(panel.querySelector(".text-red-600")).not.toBeNull();
    // Error message should reflect admin requirement
    const errEl = panel.querySelector(".text-red-600");
    expect(errEl.textContent).toContain("Platform administrator");
  });
});

// ===========================================================================
// setupSchemaModeHandlers
// ===========================================================================
describe("setupSchemaModeHandlers", () => {
  test("returns early and warns when no schema_input_mode radios exist", () => {
    setupSchemaModeHandlers();
    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining("Schema mode radios not found")
    );
  });

  test("radio 'ui' change shows ui-builder, hides json-input-container", () => {
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "schema_input_mode";
    radio.value = "ui";
    document.body.appendChild(radio);

    const uiBuilder = document.createElement("div");
    uiBuilder.id = "ui-builder";
    uiBuilder.style.display = "none";
    document.body.appendChild(uiBuilder);

    const jsonContainer = document.createElement("div");
    jsonContainer.id = "json-input-container";
    jsonContainer.style.display = "block";
    document.body.appendChild(jsonContainer);

    setupSchemaModeHandlers();

    radio.checked = true;
    radio.dispatchEvent(new Event("change"));

    expect(uiBuilder.style.display).toBe("block");
    expect(jsonContainer.style.display).toBe("none");
  });

  test("radio 'json' change hides ui-builder, shows json-input-container, calls updateSchemaPreview", () => {
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "schema_input_mode";
    radio.value = "json";
    document.body.appendChild(radio);

    const uiBuilder = document.createElement("div");
    uiBuilder.id = "ui-builder";
    uiBuilder.style.display = "block";
    document.body.appendChild(uiBuilder);

    const jsonContainer = document.createElement("div");
    jsonContainer.id = "json-input-container";
    jsonContainer.style.display = "none";
    document.body.appendChild(jsonContainer);

    setupSchemaModeHandlers();

    radio.checked = true;
    radio.dispatchEvent(new Event("change"));

    expect(uiBuilder.style.display).toBe("none");
    expect(jsonContainer.style.display).toBe("block");
    expect(updateSchemaPreview).toHaveBeenCalled();
  });

  test("handles missing uiBuilderDiv gracefully (no null error)", () => {
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "schema_input_mode";
    radio.value = "ui";
    document.body.appendChild(radio);
    // No ui-builder in DOM

    setupSchemaModeHandlers();

    radio.checked = true;
    expect(() => radio.dispatchEvent(new Event("change"))).not.toThrow();
  });

  test("handles missing jsonInputContainer gracefully", () => {
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "schema_input_mode";
    radio.value = "json";
    document.body.appendChild(radio);
    // No json-input-container in DOM

    setupSchemaModeHandlers();

    radio.checked = true;
    expect(() => radio.dispatchEvent(new Event("change"))).not.toThrow();
  });

  test("catches and logs errors in change handler", () => {
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "schema_input_mode";
    radio.value = "json";
    document.body.appendChild(radio);

    updateSchemaPreview.mockImplementation(() => {
      throw new Error("preview error");
    });

    setupSchemaModeHandlers();

    radio.checked = true;
    expect(() => radio.dispatchEvent(new Event("change"))).not.toThrow();
    expect(console.error).toHaveBeenCalledWith(
      expect.stringContaining("Error handling schema mode change"),
      expect.any(Error)
    );
  });
});

// ===========================================================================
// setupIntegrationTypeHandlers
// ===========================================================================
describe("setupIntegrationTypeHandlers", () => {
  test("does not throw when elements are missing", () => {
    expect(() => setupIntegrationTypeHandlers()).not.toThrow();
  });

  test("sets integrationTypeSelect.value to data-default if present", () => {
    const select = document.createElement("select");
    select.id = "integrationType";
    select.dataset.default = "grpc";
    const opt1 = document.createElement("option");
    opt1.value = "rest";
    const opt2 = document.createElement("option");
    opt2.value = "grpc";
    select.appendChild(opt1);
    select.appendChild(opt2);
    document.body.appendChild(select);

    setupIntegrationTypeHandlers();

    expect(select.value).toBe("grpc");
  });

  test("falls back to options[0].value when no data-default", () => {
    const select = document.createElement("select");
    select.id = "integrationType";
    const opt1 = document.createElement("option");
    opt1.value = "rest";
    const opt2 = document.createElement("option");
    opt2.value = "grpc";
    select.appendChild(opt1);
    select.appendChild(opt2);
    document.body.appendChild(select);

    setupIntegrationTypeHandlers();

    expect(select.value).toBe("rest");
  });

  test("calls updateRequestTypeOptions immediately on setup", () => {
    const select = document.createElement("select");
    select.id = "integrationType";
    const opt = document.createElement("option");
    opt.value = "rest";
    select.appendChild(opt);
    document.body.appendChild(select);

    setupIntegrationTypeHandlers();

    expect(updateRequestTypeOptions).toHaveBeenCalled();
  });

  test("attaches change listener that calls updateRequestTypeOptions", () => {
    const select = document.createElement("select");
    select.id = "integrationType";
    const opt = document.createElement("option");
    opt.value = "rest";
    select.appendChild(opt);
    document.body.appendChild(select);

    setupIntegrationTypeHandlers();
    updateRequestTypeOptions.mockClear();

    select.dispatchEvent(new Event("change"));

    expect(updateRequestTypeOptions).toHaveBeenCalled();
  });

  test("attaches change listener to edit-tool-type that calls updateEditToolRequestTypes", () => {
    const editSelect = document.createElement("select");
    editSelect.id = "edit-tool-type";
    const opt = document.createElement("option");
    opt.value = "rest";
    editSelect.appendChild(opt);
    document.body.appendChild(editSelect);

    setupIntegrationTypeHandlers();

    editSelect.dispatchEvent(new Event("change"));

    expect(updateEditToolRequestTypes).toHaveBeenCalled();
  });
});

// ===========================================================================
// setupBulkImportModal
// ===========================================================================
describe("setupBulkImportModal", () => {
  function buildBulkImportDOM() {
    const openBtn = document.createElement("button");
    openBtn.id = "open-bulk-import";
    document.body.appendChild(openBtn);

    const modal = document.createElement("div");
    modal.id = "bulk-import-modal";
    document.body.appendChild(modal);

    const closeBtn = document.createElement("button");
    closeBtn.id = "close-bulk-import";
    document.body.appendChild(closeBtn);

    const backdrop = document.createElement("div");
    backdrop.id = "bulk-import-backdrop";
    document.body.appendChild(backdrop);

    const resultEl = document.createElement("div");
    resultEl.id = "import-result";
    document.body.appendChild(resultEl);

    const indicator = document.createElement("div");
    indicator.id = "bulk-import-indicator";
    indicator.style.display = "none";
    document.body.appendChild(indicator);

    const form = document.createElement("form");
    form.id = "bulk-import-form";

    const jsonTextarea = document.createElement("textarea");
    jsonTextarea.name = "tools_json";
    form.appendChild(jsonTextarea);

    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.name = "tools_file";
    form.appendChild(fileInput);

    document.body.appendChild(form);

    return {
      openBtn,
      modal,
      closeBtn,
      backdrop,
      resultEl,
      indicator,
      form,
      jsonTextarea,
      fileInput,
    };
  }

  test("returns early when openBtn missing", () => {
    // No DOM elements
    expect(() => setupBulkImportModal()).not.toThrow();
    expect(openModal).not.toHaveBeenCalled();
  });

  test("returns early when modal missing", () => {
    const openBtn = document.createElement("button");
    openBtn.id = "open-bulk-import";
    document.body.appendChild(openBtn);
    // No modal

    expect(() => setupBulkImportModal()).not.toThrow();
    expect(openModal).not.toHaveBeenCalled();
  });

  test("returns early when already wired (openBtn.dataset.wired === '1')", () => {
    const { openBtn } = buildBulkImportDOM();
    openBtn.dataset.wired = "1";

    setupBulkImportModal();

    // A second call after already wired
    openBtn.click();
    expect(openModal).not.toHaveBeenCalled();
  });

  test("sets openBtn.dataset.wired = '1'", () => {
    const { openBtn } = buildBulkImportDOM();

    setupBulkImportModal();

    expect(openBtn.dataset.wired).toBe("1");
  });

  test("openBtn click calls openModal and adds overflow-hidden to html/body", () => {
    const { openBtn } = buildBulkImportDOM();

    setupBulkImportModal();

    const evt = new MouseEvent("click", { bubbles: true, cancelable: true });
    openBtn.dispatchEvent(evt);

    expect(openModal).toHaveBeenCalledWith("bulk-import-modal");
    expect(document.documentElement.classList.contains("overflow-hidden")).toBe(
      true
    );
    expect(document.body.classList.contains("overflow-hidden")).toBe(true);
  });

  test("open() clears resultEl.innerHTML", () => {
    const { openBtn, resultEl } = buildBulkImportDOM();
    resultEl.innerHTML = "<p>old content</p>";

    setupBulkImportModal();

    openBtn.click();

    expect(resultEl.innerHTML).toBe("");
  });

  test("closeBtn click calls closeModal and removes overflow-hidden", () => {
    const { closeBtn } = buildBulkImportDOM();
    document.documentElement.classList.add("overflow-hidden");
    document.body.classList.add("overflow-hidden");

    setupBulkImportModal();

    closeBtn.click();

    expect(closeModal).toHaveBeenCalled();
    expect(document.documentElement.classList.contains("overflow-hidden")).toBe(
      false
    );
    expect(document.body.classList.contains("overflow-hidden")).toBe(false);
  });

  test("backdrop click on backdrop itself calls close", () => {
    const { backdrop } = buildBulkImportDOM();

    setupBulkImportModal();

    const evt = new MouseEvent("click", { bubbles: true });
    Object.defineProperty(evt, "target", {
      value: backdrop,
      configurable: true,
    });
    backdrop.dispatchEvent(evt);

    expect(closeModal).toHaveBeenCalled();
  });

  test("backdrop click on child element does NOT call close", () => {
    const { backdrop } = buildBulkImportDOM();
    const child = document.createElement("div");
    backdrop.appendChild(child);

    setupBulkImportModal();

    const evt = new MouseEvent("click", { bubbles: true });
    Object.defineProperty(evt, "target", { value: child, configurable: true });
    backdrop.dispatchEvent(evt);

    expect(closeModal).not.toHaveBeenCalled();
  });

  test("ESC keydown on modal calls close and stops propagation", () => {
    const { modal } = buildBulkImportDOM();

    setupBulkImportModal();

    const evt = new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
      cancelable: true,
    });
    const stopPropSpy = vi.spyOn(evt, "stopPropagation");
    modal.dispatchEvent(evt);

    expect(closeModal).toHaveBeenCalled();
    expect(stopPropSpy).toHaveBeenCalled();
  });

  test("form submit with valid JSON text calls fetchWithTimeout", async () => {
    const { form, jsonTextarea } = buildBulkImportDOM();
    window.ROOT_PATH = "/test";

    jsonTextarea.value = JSON.stringify([{ name: "tool1" }]);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, message: "All imported" }),
    });

    setupBulkImportModal();

    form.dispatchEvent(new Event("submit", { cancelable: true }));

    await vi.runAllTimersAsync();

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("/admin/tools/import"),
      expect.any(Object)
    );
  });

  test("form submit with invalid JSON shows error, does not fetch", async () => {
    const { form, jsonTextarea, resultEl } = buildBulkImportDOM();
    window.ROOT_PATH = "/test";

    jsonTextarea.value = "not valid json {{{";

    setupBulkImportModal();

    form.dispatchEvent(new Event("submit", { cancelable: true }));

    await vi.runAllTimersAsync();

    expect(fetchWithTimeout).not.toHaveBeenCalled();
    expect(resultEl.innerHTML).toContain("Invalid JSON");
  });

  test("form submit with no data shows warning, does not fetch", async () => {
    const { form, resultEl } = buildBulkImportDOM();
    window.ROOT_PATH = "/test";
    // No data in textarea or file

    setupBulkImportModal();

    form.dispatchEvent(new Event("submit", { cancelable: true }));

    await vi.runAllTimersAsync();

    expect(fetchWithTimeout).not.toHaveBeenCalled();
    expect(resultEl.innerHTML).toContain("Please provide");
  });

  test("form submit success result.success=true shows success HTML", async () => {
    const { form, jsonTextarea, resultEl } = buildBulkImportDOM();
    window.ROOT_PATH = "/test";

    jsonTextarea.value = JSON.stringify([{ name: "tool1" }]);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, message: "Imported ok" }),
    });

    setupBulkImportModal();

    form.dispatchEvent(new Event("submit", { cancelable: true }));

    await vi.runAllTimersAsync();

    expect(resultEl.innerHTML).toContain("Import Successful");
  });

  test("form submit partial import (imported > 0) shows partial HTML with details", async () => {
    const { form, jsonTextarea, resultEl } = buildBulkImportDOM();
    window.ROOT_PATH = "/test";

    jsonTextarea.value = JSON.stringify([{ name: "t1" }, { name: "t2" }]);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          success: false,
          imported: 1,
          message: "Partial",
          details: { failed: [{ name: "t2", error: "some error" }] },
        }),
    });

    setupBulkImportModal();

    form.dispatchEvent(new Event("submit", { cancelable: true }));

    await vi.runAllTimersAsync();

    expect(resultEl.innerHTML).toContain("Partial Import");
    expect(resultEl.innerHTML).toContain("t2");
  });

  test("form submit failed import (imported 0) shows failure HTML", async () => {
    const { form, jsonTextarea, resultEl } = buildBulkImportDOM();
    window.ROOT_PATH = "/test";

    jsonTextarea.value = JSON.stringify([{ name: "t1" }]);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          success: false,
          imported: 0,
          message: "Nothing imported",
        }),
    });

    setupBulkImportModal();

    form.dispatchEvent(new Event("submit", { cancelable: true }));

    await vi.runAllTimersAsync();

    expect(resultEl.innerHTML).toContain("Import Failed");
  });

  test("form submit network error shows error HTML", async () => {
    const { form, jsonTextarea, resultEl } = buildBulkImportDOM();
    window.ROOT_PATH = "/test";

    jsonTextarea.value = JSON.stringify([{ name: "t1" }]);

    fetchWithTimeout.mockRejectedValue(new Error("Network failure"));

    setupBulkImportModal();

    form.dispatchEvent(new Event("submit", { cancelable: true }));

    await vi.runAllTimersAsync();

    expect(resultEl.innerHTML).toContain("Import Error");
  });

  test("indicator shown during submit, hidden in finally", async () => {
    const { form, jsonTextarea, indicator } = buildBulkImportDOM();
    window.ROOT_PATH = "/test";

    jsonTextarea.value = JSON.stringify([{ name: "t1" }]);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, message: "ok" }),
    });

    setupBulkImportModal();

    form.dispatchEvent(new Event("submit", { cancelable: true }));

    await vi.runAllTimersAsync();

    // After completion, indicator should be hidden
    expect(indicator.style.display).toBe("none");
  });
});

// ===========================================================================
// initializeExportImport
// ===========================================================================
describe("initializeExportImport", () => {
  function buildExportImportDOM() {
    const exportAllBtn = document.createElement("button");
    exportAllBtn.id = "export-all-btn";
    document.body.appendChild(exportAllBtn);

    const exportSelectedBtn = document.createElement("button");
    exportSelectedBtn.id = "export-selected-btn";
    document.body.appendChild(exportSelectedBtn);

    const importDropZone = document.createElement("div");
    importDropZone.id = "import-drop-zone";
    document.body.appendChild(importDropZone);

    const importFileInput = document.createElement("input");
    importFileInput.type = "file";
    importFileInput.id = "import-file-input";
    document.body.appendChild(importFileInput);

    const importValidateBtn = document.createElement("button");
    importValidateBtn.id = "import-validate-btn";
    document.body.appendChild(importValidateBtn);

    const importExecuteBtn = document.createElement("button");
    importExecuteBtn.id = "import-execute-btn";
    document.body.appendChild(importExecuteBtn);

    return {
      exportAllBtn,
      exportSelectedBtn,
      importDropZone,
      importFileInput,
      importValidateBtn,
      importExecuteBtn,
    };
  }

  test("skips if already initialized (window.exportImportInitialized = true)", () => {
    window.exportImportInitialized = true;
    buildExportImportDOM();

    initializeExportImport();

    expect(loadRecentImports).not.toHaveBeenCalled();
  });

  test("attaches click on export-all-btn -> handleExportAll", () => {
    buildExportImportDOM();

    initializeExportImport();

    document.getElementById("export-all-btn").click();

    expect(handleExportAll).toHaveBeenCalled();
  });

  test("attaches click on export-selected-btn -> handleExportSelected", () => {
    buildExportImportDOM();

    initializeExportImport();

    document.getElementById("export-selected-btn").click();

    expect(handleExportSelected).toHaveBeenCalled();
  });

  test("importDropZone click triggers importFileInput.click()", () => {
    const { importDropZone, importFileInput } = buildExportImportDOM();
    const clickSpy = vi
      .spyOn(importFileInput, "click")
      .mockImplementation(() => {});

    initializeExportImport();

    importDropZone.click();

    expect(clickSpy).toHaveBeenCalled();
  });

  test("importFileInput change -> handleFileSelect", () => {
    const { importFileInput } = buildExportImportDOM();

    initializeExportImport();

    importFileInput.dispatchEvent(new Event("change"));

    expect(handleFileSelect).toHaveBeenCalled();
  });

  test("dragover -> handleDragOver", () => {
    const { importDropZone } = buildExportImportDOM();

    initializeExportImport();

    importDropZone.dispatchEvent(new Event("dragover"));

    expect(handleDragOver).toHaveBeenCalled();
  });

  test("drop -> handleFileDrop", () => {
    const { importDropZone } = buildExportImportDOM();

    initializeExportImport();

    importDropZone.dispatchEvent(new Event("drop"));

    expect(handleFileDrop).toHaveBeenCalled();
  });

  test("dragleave -> handleDragLeave", () => {
    const { importDropZone } = buildExportImportDOM();

    initializeExportImport();

    importDropZone.dispatchEvent(new Event("dragleave"));

    expect(handleDragLeave).toHaveBeenCalled();
  });

  test("importValidateBtn click -> handleImport(true)", () => {
    buildExportImportDOM();

    initializeExportImport();

    document.getElementById("import-validate-btn").click();

    expect(handleImport).toHaveBeenCalledWith(true);
  });

  test("importExecuteBtn click -> handleImport(false)", () => {
    buildExportImportDOM();

    initializeExportImport();

    document.getElementById("import-execute-btn").click();

    expect(handleImport).toHaveBeenCalledWith(false);
  });

  test("sets window.Admin.exportImportInitialized after init", () => {
    buildExportImportDOM();

    initializeExportImport();

    expect(window.Admin.exportImportInitialized).toBe(true);
  });

  test("calls loadRecentImports", () => {
    buildExportImportDOM();

    initializeExportImport();

    expect(loadRecentImports).toHaveBeenCalled();
  });
});

// ===========================================================================
// setupTooltipsWithAlpine
// ===========================================================================
describe("setupTooltipsWithAlpine", () => {
  test("does not throw when called", () => {
    expect(() => setupTooltipsWithAlpine()).not.toThrow();
  });

  test("fires alpine:init event, which registers Alpine.directive", () => {
    const directiveSpy = vi.fn();
    window.Alpine = { directive: directiveSpy };

    setupTooltipsWithAlpine();

    document.dispatchEvent(new Event("alpine:init"));

    expect(directiveSpy).toHaveBeenCalledWith("tooltip", expect.any(Function));
  });

  test("registered directive is 'tooltip'", () => {
    let registeredName = null;
    window.Alpine = {
      directive: (name, fn) => {
        registeredName = name;
      },
    };

    setupTooltipsWithAlpine();
    document.dispatchEvent(new Event("alpine:init"));

    expect(registeredName).toBe("tooltip");
  });
});

// ===========================================================================
// registerReloadAllResourceSections
// ===========================================================================
describe("registerReloadAllResourceSections", () => {
  // Reset getUiHiddenSections before each test in this describe to prevent
  // cross-test contamination from the "hidden sections" test
  beforeEach(() => {
    getUiHiddenSections.mockReturnValue(new Set());
    getTeamNameById.mockReturnValue(null);
  });

  test("registers window.Admin.reloadAllResourceSections function", () => {
    registerReloadAllResourceSections();

    expect(typeof window.Admin.reloadAllResourceSections).toBe("function");
  });

  test("DOMContentLoaded saves section markup to window.Admin.__initialSectionMarkup for non-hidden sections", () => {
    registerReloadAllResourceSections();

    const toolsSection = document.createElement("div");
    toolsSection.id = "tools-section";
    toolsSection.innerHTML = "<p>tools content</p>";
    document.body.appendChild(toolsSection);

    window.Admin.__initialSectionMarkup = {};
    window.__initialSectionMarkup = {};

    document.dispatchEvent(new Event("DOMContentLoaded"));

    expect(window.Admin.__initialSectionMarkup.tools).toBe(
      "<p>tools content</p>"
    );
  });

  test("DOMContentLoaded: does not save markup for hidden sections", () => {
    // Set hidden BEFORE calling registerReloadAllResourceSections
    getUiHiddenSections.mockReturnValue(new Set(["tools"]));

    registerReloadAllResourceSections();

    const toolsSection = document.createElement("div");
    toolsSection.id = "tools-section";
    toolsSection.innerHTML = "<p>tools content</p>";
    document.body.appendChild(toolsSection);

    window.Admin.__initialSectionMarkup = {};
    window.__initialSectionMarkup = {};

    document.dispatchEvent(new Event("DOMContentLoaded"));

    expect(window.Admin.__initialSectionMarkup["tools"]).toBeUndefined();

    // Restore after test
    getUiHiddenSections.mockReturnValue(new Set());
  });

  test("reloadAllResourceSections warns and returns when ROOT_PATH missing", async () => {
    registerReloadAllResourceSections();

    delete window.ROOT_PATH;

    await window.Admin.reloadAllResourceSections();

    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining("ROOT_PATH not defined")
    );
    expect(fetchWithTimeout).not.toHaveBeenCalled();
  });

  test("reloadAllResourceSections iterates visible sections and fetches each", async () => {
    window.ROOT_PATH = "/test";
    registerReloadAllResourceSections();

    const toolsSection = document.createElement("div");
    toolsSection.id = "tools-section";
    document.body.appendChild(toolsSection);

    await window.Admin.reloadAllResourceSections();

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("/admin/sections/tools?partial=true"),
      expect.any(Object),
      expect.any(Number)
    );
  });

  test("reloadAllResourceSections skips section when element not found", async () => {
    window.ROOT_PATH = "/test";
    registerReloadAllResourceSections();
    // No tools-section in DOM

    await window.Admin.reloadAllResourceSections();

    // Should warn about missing element and not call fetch for missing elements
    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining("Section element not found: tools-section")
    );
  });

  test("reloadAllResourceSections on fetch failure restores from __initialSectionMarkup if available", async () => {
    window.ROOT_PATH = "/test";

    const toolsSection = document.createElement("div");
    toolsSection.id = "tools-section";
    toolsSection.innerHTML = "<p>old</p>";
    document.body.appendChild(toolsSection);

    window.__initialSectionMarkup = { tools: "<p>original</p>" };

    fetchWithTimeout.mockRejectedValue(new Error("network error"));

    registerReloadAllResourceSections();

    await window.Admin.reloadAllResourceSections();

    expect(toolsSection.innerHTML).toBe("<p>original</p>");
  });

  test("reloadAllResourceSections logs warning when no fallback markup available", async () => {
    window.ROOT_PATH = "/test";

    const toolsSection = document.createElement("div");
    toolsSection.id = "tools-section";
    document.body.appendChild(toolsSection);

    window.__initialSectionMarkup = {};

    fetchWithTimeout.mockRejectedValue(new Error("network error"));

    registerReloadAllResourceSections();

    await window.Admin.reloadAllResourceSections();

    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining("No saved initial markup for section tools")
    );
  });

  test("reloadAllResourceSections appends team_id param when teamId provided", async () => {
    window.ROOT_PATH = "/test";
    registerReloadAllResourceSections();

    const toolsSection = document.createElement("div");
    toolsSection.id = "tools-section";
    document.body.appendChild(toolsSection);

    await window.Admin.reloadAllResourceSections("team-123");

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("team_id=team-123"),
      expect.any(Object),
      expect.any(Number)
    );
  });

  test("updateSectionHeaders adds team badge to header when teamId set", async () => {
    window.ROOT_PATH = "/test";
    getTeamNameById.mockReturnValue("My Team");

    // The safeSetInnerHTML mock replaces el.innerHTML, so we use HTML that includes h2
    // but the updateSectionHeaders queries `#tools-section h2` AFTER fetch.
    // We need safeSetInnerHTML to preserve or add the h2.
    // Override safeSetInnerHTML for this test to not replace content:
    safeSetInnerHTML.mockImplementation(() => {}); // no-op: don't replace

    const toolsSection = document.createElement("div");
    toolsSection.id = "tools-section";
    const h2 = document.createElement("h2");
    toolsSection.appendChild(h2);
    document.body.appendChild(toolsSection);

    registerReloadAllResourceSections();

    await window.Admin.reloadAllResourceSections("team-123");

    const badge = h2.querySelector(".team-badge");
    expect(badge).not.toBeNull();
    expect(badge.textContent).toBe("My Team");

    // Restore
    safeSetInnerHTML.mockImplementation((el, html) => {
      if (el) el.innerHTML = html;
    });
  });

  test("updateSectionHeaders removes existing team badge before adding new one", async () => {
    window.ROOT_PATH = "/test";
    getTeamNameById.mockReturnValue("New Team");

    // Don't replace section content so h2 persists
    safeSetInnerHTML.mockImplementation(() => {});

    const toolsSection = document.createElement("div");
    toolsSection.id = "tools-section";
    const h2 = document.createElement("h2");

    const existingBadge = document.createElement("span");
    existingBadge.className = "team-badge";
    existingBadge.textContent = "Old Team";
    h2.appendChild(existingBadge);

    toolsSection.appendChild(h2);
    document.body.appendChild(toolsSection);

    registerReloadAllResourceSections();

    await window.Admin.reloadAllResourceSections("team-456");

    const badges = h2.querySelectorAll(".team-badge");
    expect(badges.length).toBe(1);
    expect(badges[0].textContent).toBe("New Team");

    // Restore
    safeSetInnerHTML.mockImplementation((el, html) => {
      if (el) el.innerHTML = html;
    });
  });
});
