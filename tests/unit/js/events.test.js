/**
 * Unit tests for events.js module
 * Tests: Event handler initialization and dispatching
 */

import { describe, test, expect, vi, afterEach } from "vitest";

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
  },
}));
vi.mock("../../../mcpgateway/admin_ui/formFieldHandlers.js", () => ({
  updateEditToolRequestTypes: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/caCertificate.js", () => ({
  initializeCACertUpload: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/formValidation.js", () => ({
  setupFormValidation: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/gateway.js", () => ({
  getSelectedGatewayIds: vi.fn(() => []),
  initGatewaySelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/modals", () => ({
  closeModal: vi.fn(),
  openModal: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/monitoring.js", () => ({
  initializeRealTimeMonitoring: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => s || ""),
  validateInputName: vi.fn((s) => ({ valid: true, value: s })),
  validateUrl: vi.fn(() => ({ valid: true })),
}));
vi.mock("../../../mcpgateway/admin_ui/tags", () => ({
  initializeTagFiltering: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/teams", () => ({
  hideTeamEditModal: vi.fn(),
  initializeAddMembersForms: vi.fn(),
  initializePasswordValidation: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/tokens", () => ({
  initializeTeamScopingMonitor: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/tools", () => ({
  cleanupToolTestState: vi.fn(),
  loadTools: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/users", () => ({
  hideUserEditModal: vi.fn(),
  performUserSearch: vi.fn(),
  registerAdminActionListeners: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/initialization.js", () => ({
  initializeCodeMirrorEditors: vi.fn(),
  initializeEventListeners: vi.fn(),
  initializeExportImport: vi.fn(),
  initializeSearchInputs: vi.fn(),
  initializeTabState: vi.fn(),
  initializeToolSelects: vi.fn(),
  registerReloadAllResourceSections: vi.fn(),
  setupBulkImportModal: vi.fn(),
  setupTooltipsWithAlpine: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/utils", () => ({
  createMemoizedInit: vi.fn((fn) => ({
    init: fn,
    debouncedInit: vi.fn(),
    reset: vi.fn(),
  })),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showErrorMessage: vi.fn(),
  showSuccessMessage: vi.fn(),
  updateEditToolUrl: vi.fn(),
}));

afterEach(() => {
  document.body.innerHTML = "";
  vi.clearAllMocks();
});

describe("events.js - DOMContentLoaded initialization", () => {
  test("events module can be imported without errors", async () => {
    // Set up window.Admin namespace before import
    window.Admin = window.Admin || {};
    window.Admin.chartRegistry = { destroyAll: vi.fn() };

    await expect(
      import("../../../mcpgateway/admin_ui/events.js")
    ).resolves.toBeDefined();
  });
});

describe("events.js - Keyboard event handling", () => {
  test("Escape key triggers modal close", async () => {
    window.Admin = window.Admin || {};
    window.Admin.chartRegistry = { destroyAll: vi.fn() };

    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    const { closeModal } = await import("../../../mcpgateway/admin_ui/modals");
    AppState.activeModals = new Set(["test-modal"]);

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));

    expect(closeModal).toHaveBeenCalledWith("test-modal");
  });

  test("non-Escape key does not close modal", async () => {
    const { closeModal } = await import("../../../mcpgateway/admin_ui/modals");
    vi.clearAllMocks();

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));

    expect(closeModal).not.toHaveBeenCalled();
  });
});
