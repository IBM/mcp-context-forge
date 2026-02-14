/**
 * Unit tests for tabs.js module
 * Tests: ADMIN_ONLY_TABS, getDefaultTabName, getTableNamesForTab, showTab
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

// Mock heavy dependencies before importing tabs
vi.mock("../../../mcpgateway/admin_ui/fileTransfer.js", () => ({
  loadRecentImports: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/initialization.js", () => ({
  initializeExportImport: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/llmChat.js", () => ({
  initializeLLMChat: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/logging.js", () => ({
  searchStructuredLogs: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/metrics.js", () => ({
  loadAggregatedMetrics: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/plugins.js", () => ({
  populatePluginFilters: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  loadTokensList: vi.fn(),
  setupCreateTokenForm: vi.fn(),
  updateTeamScopingWarning: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/users.js", () => ({
  initializePermissionsPanel: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  fetchWithTimeout: vi.fn(),
  isAdminUser: vi.fn(() => true),
  safeGetElement: vi.fn((id, silent) => document.getElementById(id)),
  showErrorMessage: vi.fn(),
}));

import {
  ADMIN_ONLY_TABS,
  isAdminOnlyTab,
  getDefaultTabName,
  getTableNamesForTab,
  showTab,
} from "../../../mcpgateway/admin_ui/tabs.js";
import { isAdminUser } from "../../../mcpgateway/admin_ui/utils.js";

// ---------------------------------------------------------------------------
// ADMIN_ONLY_TABS
// ---------------------------------------------------------------------------
describe("ADMIN_ONLY_TABS", () => {
  test("is a Set with expected admin tabs", () => {
    expect(ADMIN_ONLY_TABS).toBeInstanceOf(Set);
    expect(ADMIN_ONLY_TABS.has("users")).toBe(true);
    expect(ADMIN_ONLY_TABS.has("metrics")).toBe(true);
    expect(ADMIN_ONLY_TABS.has("plugins")).toBe(true);
    expect(ADMIN_ONLY_TABS.has("logs")).toBe(true);
  });

  test("does not include non-admin tabs", () => {
    expect(ADMIN_ONLY_TABS.has("gateways")).toBe(false);
    expect(ADMIN_ONLY_TABS.has("catalog")).toBe(false);
    expect(ADMIN_ONLY_TABS.has("tools")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isAdminOnlyTab
// ---------------------------------------------------------------------------
describe("isAdminOnlyTab", () => {
  test("returns true for admin tabs", () => {
    expect(isAdminOnlyTab("users")).toBe(true);
    expect(isAdminOnlyTab("metrics")).toBe(true);
  });

  test("returns false for non-admin tabs", () => {
    expect(isAdminOnlyTab("gateways")).toBe(false);
    expect(isAdminOnlyTab("catalog")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// getDefaultTabName
// ---------------------------------------------------------------------------
describe("getDefaultTabName", () => {
  test("returns 'overview' when overview-panel exists", () => {
    const panel = document.createElement("div");
    panel.id = "overview-panel";
    document.body.appendChild(panel);

    expect(getDefaultTabName()).toBe("overview");

    panel.remove();
  });

  test("returns 'gateways' when overview-panel does not exist", () => {
    expect(getDefaultTabName()).toBe("gateways");
  });
});

// ---------------------------------------------------------------------------
// getTableNamesForTab
// ---------------------------------------------------------------------------
describe("getTableNamesForTab", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("returns table names from pagination controls in the panel", () => {
    const panel = document.createElement("div");
    panel.id = "catalog-panel";

    const ctrl1 = document.createElement("div");
    ctrl1.id = "servers-pagination-controls";
    panel.appendChild(ctrl1);

    const ctrl2 = document.createElement("div");
    ctrl2.id = "tools-pagination-controls";
    panel.appendChild(ctrl2);

    document.body.appendChild(panel);

    const result = getTableNamesForTab("catalog");
    expect(result).toContain("servers");
    expect(result).toContain("tools");
  });

  test("returns empty array when panel does not exist", () => {
    expect(getTableNamesForTab("nonexistent")).toEqual([]);
  });

  test("returns empty array when panel has no pagination controls", () => {
    const panel = document.createElement("div");
    panel.id = "empty-panel";
    document.body.appendChild(panel);

    expect(getTableNamesForTab("empty")).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// showTab
// ---------------------------------------------------------------------------
describe("showTab", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = "";
    // Set up minimal DOM for tab switching
    const panel = document.createElement("div");
    panel.id = "gateways-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#gateways";
    document.body.appendChild(link);

    // Mock window properties
    window.ROOT_PATH = "";
    window.Admin = { chartRegistry: { destroyByPrefix: vi.fn() } };
    window.htmx = { trigger: vi.fn(), ajax: vi.fn(), process: vi.fn() };
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
    delete window.Admin;
    delete window.htmx;
  });

  test("reveals the target panel and hides others", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("gateways");

    const panel = document.getElementById("gateways-panel");
    expect(panel.classList.contains("hidden")).toBe(false);
    consoleSpy.mockRestore();
  });

  test("activates the corresponding sidebar link", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("gateways");

    const link = document.querySelector('.sidebar-link[href="#gateways"]');
    expect(link.classList.contains("active")).toBe(true);
    consoleSpy.mockRestore();
  });

  test("blocks non-admin users from admin-only tabs", () => {
    isAdminUser.mockReturnValue(false);
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    showTab("users");

    // Should not create a users-panel since it's blocked
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("Blocked non-admin")
    );

    isAdminUser.mockReturnValue(true);
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });

  test("logs error when panel is not found", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    showTab("nonexistent");

    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("not found")
    );
    errorSpy.mockRestore();
    logSpy.mockRestore();
  });
});
