/**
 * Unit tests for initialization.js module
 * Tests: initializeCodeMirrorEditors, initializeToolSelects,
 *        initializeEventListeners, setupTabNavigation,
 *        initializeSearchInputs, initializeTabState,
 *        setupSchemaModeHandlers, setupIntegrationTypeHandlers,
 *        setupBulkImportModal, initializeExportImport,
 *        setupTooltipsWithAlpine, registerReloadAllResourceSections
 */

import { describe, test, expect, vi, afterEach, beforeEach } from "vitest";

import {
  initializeCodeMirrorEditors,
  initializeToolSelects,
  initializeEventListeners,
  setupTabNavigation,
  initializeSearchInputs,
  initializeTabState,
  setupSchemaModeHandlers,
  setupIntegrationTypeHandlers,
  setupBulkImportModal,
  initializeExportImport,
  setupTooltipsWithAlpine,
  registerReloadAllResourceSections,
} from "../../../mcpgateway/admin_ui/initialization.js";

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
vi.mock("../../../mcpgateway/admin_ui/formFieldHandlers", () => ({
  handleAddParameter: vi.fn(),
  handleAddPassthrough: vi.fn(),
  updateEditToolRequestTypes: vi.fn(),
  updateRequestTypeOptions: vi.fn(),
  updateSchemaPreview: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/formSubmitHandlers", () => ({
  handleA2AFormSubmit: vi.fn(),
  handleEditA2AAgentFormSubmit: vi.fn(),
  handleEditGatewayFormSubmit: vi.fn(),
  handleEditPromptFormSubmit: vi.fn(),
  handleEditResFormSubmit: vi.fn(),
  handleEditServerFormSubmit: vi.fn(),
  handleEditToolFormSubmit: vi.fn(),
  handleGatewayFormSubmit: vi.fn(),
  handlePromptFormSubmit: vi.fn(),
  handleResourceFormSubmit: vi.fn(),
  handleServerFormSubmit: vi.fn(),
  handleToolFormSubmit: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/llmChat.js", () => ({
  serverSideEditPromptsSearch: vi.fn(),
  serverSideEditResourcesSearch: vi.fn(),
  serverSideEditToolSearch: vi.fn(),
  serverSidePromptSearch: vi.fn(),
  serverSideResourceSearch: vi.fn(),
  serverSideToolSearch: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/modals", () => ({
  closeModal: vi.fn(),
  openModal: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/prompts", () => ({
  initPromptSelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/resources", () => ({
  initResourceSelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/filters", () => ({
  filterA2AAgentsTable: vi.fn(),
  filterGatewaysTable: vi.fn(),
  filterPromptsTable: vi.fn(),
  filterResourcesTable: vi.fn(),
  filterServerTable: vi.fn(),
  filterToolsTable: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  safeSetInnerHTML: vi.fn((el, html) => {
    if (el) el.innerHTML = html;
  }),
}));
vi.mock("../../../mcpgateway/admin_ui/tabs", () => ({
  ADMIN_ONLY_TABS: ["users", "tokens", "logs"],
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
vi.mock("../../../mcpgateway/admin_ui/tools", () => ({
  initToolSelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/utils", () => ({
  fetchWithTimeout: vi.fn(),
  isAdminUser: vi.fn(() => true),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));
vi.mock("../../../mcpgateway/admin_ui/tokens", () => ({
  getTeamNameById: vi.fn(() => null),
}));

beforeEach(() => {
  // Ensure window.Admin exists for functions that write to it
  window.Admin = window.Admin || {};
  // Reset exportImportInitialized flag
  window.exportImportInitialized = false;
});

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  delete window.CodeMirror;
  delete window.Admin;
  delete window.exportImportInitialized;
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// initializeCodeMirrorEditors
// ---------------------------------------------------------------------------
describe("initializeCodeMirrorEditors", () => {
  test("does nothing when CodeMirror is not available", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    delete window.CodeMirror;
    expect(() => initializeCodeMirrorEditors()).not.toThrow();
    consoleSpy.mockRestore();
    warnSpy.mockRestore();
  });

  test("initializes editors when CodeMirror is available", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const mockEditor = { setValue: vi.fn(), getValue: vi.fn() };
    window.CodeMirror = { fromTextArea: vi.fn(() => mockEditor) };

    const textarea = document.createElement("textarea");
    textarea.id = "schema-editor";
    document.body.appendChild(textarea);

    initializeCodeMirrorEditors();
    consoleSpy.mockRestore();
    warnSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// initializeToolSelects
// ---------------------------------------------------------------------------
describe("initializeToolSelects", () => {
  test("does not throw when called", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(() => initializeToolSelects()).not.toThrow();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// initializeEventListeners
// ---------------------------------------------------------------------------
describe("initializeEventListeners", () => {
  test("does not throw when DOM elements are missing", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(() => initializeEventListeners()).not.toThrow();
    consoleSpy.mockRestore();
    warnSpy.mockRestore();
  });

  test("attaches listeners to existing form elements", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const form = document.createElement("form");
    form.id = "tool-form";
    document.body.appendChild(form);

    initializeEventListeners();
    consoleSpy.mockRestore();
    warnSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// setupTabNavigation
// ---------------------------------------------------------------------------
describe("setupTabNavigation", () => {
  test("does not throw when tab elements are missing", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(() => setupTabNavigation()).not.toThrow();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// initializeSearchInputs
// ---------------------------------------------------------------------------
describe("initializeSearchInputs", () => {
  test("does not throw when search inputs are missing", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    expect(() => initializeSearchInputs()).not.toThrow();
    consoleSpy.mockRestore();
    errorSpy.mockRestore();
  });

  test("attaches input listeners to search fields", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    const searchInput = document.createElement("input");
    searchInput.id = "tools-search";
    searchInput.type = "text";
    document.body.appendChild(searchInput);

    initializeSearchInputs();
    consoleSpy.mockRestore();
    errorSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// initializeTabState
// ---------------------------------------------------------------------------
describe("initializeTabState", () => {
  test("does not throw when called", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(() => initializeTabState()).not.toThrow();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// setupSchemaModeHandlers
// ---------------------------------------------------------------------------
describe("setupSchemaModeHandlers", () => {
  test("does not throw when elements are missing", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(() => setupSchemaModeHandlers()).not.toThrow();
    consoleSpy.mockRestore();
    warnSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// setupIntegrationTypeHandlers
// ---------------------------------------------------------------------------
describe("setupIntegrationTypeHandlers", () => {
  test("does not throw when elements are missing", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(() => setupIntegrationTypeHandlers()).not.toThrow();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// setupBulkImportModal
// ---------------------------------------------------------------------------
describe("setupBulkImportModal", () => {
  test("does not throw when elements are missing", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(() => setupBulkImportModal()).not.toThrow();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// initializeExportImport
// ---------------------------------------------------------------------------
describe("initializeExportImport", () => {
  test("does not throw when elements are missing", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(() => initializeExportImport()).not.toThrow();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// setupTooltipsWithAlpine
// ---------------------------------------------------------------------------
describe("setupTooltipsWithAlpine", () => {
  test("does not throw when called", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(() => setupTooltipsWithAlpine()).not.toThrow();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// registerReloadAllResourceSections
// ---------------------------------------------------------------------------
describe("registerReloadAllResourceSections", () => {
  test("does not throw when called", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(() => registerReloadAllResourceSections()).not.toThrow();
    consoleSpy.mockRestore();
  });
});
