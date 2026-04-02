/**
 * Unit tests for tabs.js module
 * Comprehensive test coverage for all exported functions
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import {
  ADMIN_ONLY_TABS,
  isAdminOnlyTab,
  resolveTabForNavigation,
  normalizeTabName,
  getUiHiddenSections,
  getUiHiddenTabs,
  isTabHidden,
  getVisibleSidebarTabs,
  isTabAvailable,
  getDefaultTabName,
  updateHashForTab,
  getTableNamesForTab,
  cleanUpUrlParamsForTab,
  showTab,
} from "../../../mcpgateway/admin_ui/tabs.js";
import { isAdminUser } from "../../../mcpgateway/admin_ui/utils.js";
import { safeReplaceState } from "../../../mcpgateway/admin_ui/security.js";

// Mock dependencies
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((str) => str),
  safeReplaceState: vi.fn(),
  safeSetInnerHTML: vi.fn((el, html) => {
    el.innerHTML = html;
  }),
}));

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
  filterPlugins: vi.fn(),
  dispatchPluginAction: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  loadTokensList: vi.fn(),
  setupCreateTokenForm: vi.fn(),
  setupTokenListEventHandlers: vi.fn(),
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
// normalizeTabName
// ---------------------------------------------------------------------------
describe("normalizeTabName", () => {
  test("removes leading hash and trims whitespace", () => {
    expect(normalizeTabName("#gateways")).toBe("gateways");
    expect(normalizeTabName("  catalog  ")).toBe("catalog");
    expect(normalizeTabName("#  servers  ")).toBe("servers");
  });

  test("converts to lowercase", () => {
    expect(normalizeTabName("GATEWAYS")).toBe("gateways");
    expect(normalizeTabName("Catalog")).toBe("catalog");
  });

  test("removes invalid characters", () => {
    expect(normalizeTabName("gate@ways!")).toBe("gateways");
    expect(normalizeTabName("servers$123")).toBe("servers123");
    expect(normalizeTabName("my-tab_name")).toBe("my-tabname");
  });

  test("handles empty or null input", () => {
    expect(normalizeTabName("")).toBe("");
    expect(normalizeTabName(null)).toBe("");
    expect(normalizeTabName(undefined)).toBe("");
  });

  test("handles non-string input", () => {
    expect(normalizeTabName(123)).toBe("");
    expect(normalizeTabName({})).toBe("");
  });
});

// ---------------------------------------------------------------------------
// getUiHiddenSections
// ---------------------------------------------------------------------------
describe("getUiHiddenSections", () => {
  beforeEach(() => {
    delete window.UI_HIDDEN_SECTIONS;
  });

  test("returns empty Set when UI_HIDDEN_SECTIONS is not defined", () => {
    const result = getUiHiddenSections();
    expect(result).toBeInstanceOf(Set);
    expect(result.size).toBe(0);
  });

  test("returns Set with normalized section names", () => {
    window.UI_HIDDEN_SECTIONS = ["SERVERS", "  tools  ", "#prompts"];
    const result = getUiHiddenSections();
    expect(result.has("servers")).toBe(true);
    expect(result.has("tools")).toBe(true);
    expect(result.has("prompts")).toBe(true);
  });

  test("handles non-array UI_HIDDEN_SECTIONS", () => {
    window.UI_HIDDEN_SECTIONS = "not-an-array";
    const result = getUiHiddenSections();
    expect(result.size).toBe(0);
  });

  test("filters out invalid section names", () => {
    window.UI_HIDDEN_SECTIONS = ["valid-section", "", null, 123];
    const result = getUiHiddenSections();
    expect(result.has("valid-section")).toBe(true);
    expect(result.size).toBe(3); // "valid-section", "null", "123"
  });
});

// ---------------------------------------------------------------------------
// getUiHiddenTabs
// ---------------------------------------------------------------------------
describe("getUiHiddenTabs", () => {
  beforeEach(() => {
    delete window.UI_HIDDEN_TABS;
  });

  test("returns empty Set when UI_HIDDEN_TABS is not defined", () => {
    const result = getUiHiddenTabs();
    expect(result).toBeInstanceOf(Set);
    expect(result.size).toBe(0);
  });

  test("returns Set with normalized tab names", () => {
    window.UI_HIDDEN_TABS = ["METRICS", "  logs  ", "#version-info"];
    const result = getUiHiddenTabs();
    expect(result.has("metrics")).toBe(true);
    expect(result.has("logs")).toBe(true);
    expect(result.has("version-info")).toBe(true);
  });

  test("handles non-array UI_HIDDEN_TABS", () => {
    window.UI_HIDDEN_TABS = null;
    const result = getUiHiddenTabs();
    expect(result.size).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// isTabHidden
// ---------------------------------------------------------------------------
describe("isTabHidden", () => {
  beforeEach(() => {
    delete window.UI_HIDDEN_TABS;
  });

  test("returns false when no tabs are hidden", () => {
    expect(isTabHidden("gateways")).toBe(false);
  });

  test("returns true for hidden tabs", () => {
    window.UI_HIDDEN_TABS = ["metrics", "logs"];
    expect(isTabHidden("metrics")).toBe(true);
    expect(isTabHidden("logs")).toBe(true);
  });

  test("returns false for non-hidden tabs", () => {
    window.UI_HIDDEN_TABS = ["metrics"];
    expect(isTabHidden("gateways")).toBe(false);
  });

  test("normalizes tab name before checking", () => {
    window.UI_HIDDEN_TABS = ["metrics"];
    expect(isTabHidden("METRICS")).toBe(true);
    expect(isTabHidden("#metrics")).toBe(true);
  });

  test("handles empty or invalid tab name", () => {
    expect(isTabHidden("")).toBe(false);
    expect(isTabHidden(null)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// getVisibleSidebarTabs
// ---------------------------------------------------------------------------
describe("getVisibleSidebarTabs", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  test("returns tabs from sidebar links", () => {
    const nav = document.createElement("nav");
    nav.innerHTML = `
      <a class="sidebar-link" href="#gateways">Gateways</a>
      <a class="sidebar-link" href="#catalog">Catalog</a>
      <a class="sidebar-link" href="#tools">Tools</a>
    `;
    document.body.appendChild(nav);

    const result = getVisibleSidebarTabs();
    expect(result).toContain("gateways");
    expect(result).toContain("catalog");
    expect(result).toContain("tools");
  });

  test("returns empty array when no sidebar links exist", () => {
    const result = getVisibleSidebarTabs();
    expect(result).toEqual([]);
  });

  test("filters out duplicate tabs", () => {
    const nav = document.createElement("nav");
    nav.innerHTML = `
      <a class="sidebar-link" href="#gateways">Gateways</a>
      <a class="sidebar-link" href="#gateways">Gateways Again</a>
    `;
    document.body.appendChild(nav);

    const result = getVisibleSidebarTabs();
    expect(result.filter((t) => t === "gateways").length).toBe(1);
  });

  test("ignores links without hash hrefs", () => {
    const nav = document.createElement("nav");
    nav.innerHTML = `
      <a class="sidebar-link" href="#gateways">Gateways</a>
      <a class="sidebar-link" href="/external">External</a>
    `;
    document.body.appendChild(nav);

    const result = getVisibleSidebarTabs();
    expect(result).toContain("gateways");
    expect(result.length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// isTabAvailable
// ---------------------------------------------------------------------------
describe("isTabAvailable", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  test("returns true when both panel and nav exist", () => {
    const panel = document.createElement("div");
    panel.id = "gateways-panel";
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#gateways";
    document.body.appendChild(link);

    expect(isTabAvailable("gateways")).toBe(true);
  });

  test("returns false when panel does not exist", () => {
    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#gateways";
    document.body.appendChild(link);

    expect(isTabAvailable("gateways")).toBe(false);
  });

  test("returns false when nav does not exist", () => {
    const panel = document.createElement("div");
    panel.id = "gateways-panel";
    document.body.appendChild(panel);

    expect(isTabAvailable("gateways")).toBe(false);
  });

  test("returns false for empty tab name", () => {
    expect(isTabAvailable("")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// resolveTabForNavigation
// ---------------------------------------------------------------------------
describe("resolveTabForNavigation", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    delete window.UI_HIDDEN_TABS;
    isAdminUser.mockReturnValue(true);

    // Set up default tab
    const panel = document.createElement("div");
    panel.id = "overview-panel";
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#overview";
    document.body.appendChild(link);
  });

  test("returns normalized tab when available", () => {
    const panel = document.createElement("div");
    panel.id = "gateways-panel";
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#gateways";
    document.body.appendChild(link);

    expect(resolveTabForNavigation("GATEWAYS")).toBe("gateways");
  });

  test("returns default tab for hidden tabs", () => {
    window.UI_HIDDEN_TABS = ["metrics"];
    expect(resolveTabForNavigation("metrics")).toBe("overview");
  });

  test("returns default tab for admin-only tabs when not admin", () => {
    isAdminUser.mockReturnValue(false);
    expect(resolveTabForNavigation("users")).toBe("overview");
  });

  test("returns default tab when tab is not available", () => {
    expect(resolveTabForNavigation("nonexistent")).toBe("overview");
  });

  test("returns default tab for empty input", () => {
    expect(resolveTabForNavigation("")).toBe("overview");
    expect(resolveTabForNavigation(null)).toBe("overview");
  });
});

// ---------------------------------------------------------------------------
// getDefaultTabName
// ---------------------------------------------------------------------------

describe("getDefaultTabName", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    delete window.UI_HIDDEN_TABS;
    isAdminUser.mockReturnValue(true);
  });

  test("returns 'overview' when overview-panel exists", () => {
    const panel = document.createElement("div");
    panel.id = "overview-panel";
    document.body.appendChild(panel);
    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#overview";
    document.body.appendChild(link);
    expect(getDefaultTabName()).toBe("overview");
  });

  test("returns 'gateways' when overview not available", () => {
    const panel = document.createElement("div");
    panel.id = "gateways-panel";
    document.body.appendChild(panel);
    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#gateways";
    document.body.appendChild(link);
    expect(getDefaultTabName()).toBe("gateways");
  });

  test("returns first visible tab", () => {
    const panel = document.createElement("div");
    panel.id = "catalog-panel";
    document.body.appendChild(panel);
    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#catalog";
    document.body.appendChild(link);
    expect(getDefaultTabName()).toBe("catalog");
  });

  test("falls back to gateways", () => {
    expect(getDefaultTabName()).toBe("gateways");
  });
});

// ---------------------------------------------------------------------------
// updateHashForTab
// ---------------------------------------------------------------------------
describe("updateHashForTab", () => {
  beforeEach(() => {
    delete window.location;
    window.location = { href: "http://localhost:4444/admin", hash: "" };
  });

  test("updates hash when different", () => {
    safeReplaceState.mockClear();
    updateHashForTab("gateways");
    expect(safeReplaceState).toHaveBeenCalled();
  });

  test("skips when hash matches", () => {
    safeReplaceState.mockClear();
    window.location.hash = "#gateways";
    updateHashForTab("gateways");
    expect(safeReplaceState).not.toHaveBeenCalled();
  });
  test("handles empty name", () => {
    safeReplaceState.mockClear();
    updateHashForTab("");
    expect(safeReplaceState).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// getTableNamesForTab
// ---------------------------------------------------------------------------
describe("getTableNamesForTab", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("returns table names", () => {
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

  test("returns empty for nonexistent", () => {
    expect(getTableNamesForTab("nonexistent")).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// cleanUpUrlParamsForTab
// ---------------------------------------------------------------------------
describe("cleanUpUrlParamsForTab", () => {
  beforeEach(() => {
    delete window.location;
    window.location = {
      href: "http://localhost:4444/admin?servers_page=2&tools_page=3&team_id=t1",
      search: "?servers_page=2&tools_page=3&team_id=t1",
      pathname: "/admin",
      hash: "#catalog",
    };
    document.body.innerHTML = "";
  });

  test("keeps relevant params", () => {
    safeReplaceState.mockClear();
    const panel = document.createElement("div");
    panel.id = "catalog-panel";
    const ctrl = document.createElement("div");
    ctrl.id = "servers-pagination-controls";
    panel.appendChild(ctrl);
    document.body.appendChild(panel);
    cleanUpUrlParamsForTab("catalog");
    expect(safeReplaceState).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// showTab
// ---------------------------------------------------------------------------
describe("showTab", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = "";
    delete window.UI_HIDDEN_TABS;
    isAdminUser.mockReturnValue(true);
    window.ROOT_PATH = "";
    window.chartRegistry = { destroyByPrefix: vi.fn() };
    window.htmx = {
      trigger: vi.fn(),
      ajax: vi.fn().mockResolvedValue({}),
      process: vi.fn(),
    };
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
    delete window.chartRegistry;
    delete window.htmx;
  });

  test("reveals panel", () => {
    const panel = document.createElement("div");
    panel.id = "gateways-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);
    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#gateways";
    document.body.appendChild(link);
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("gateways");
    logSpy.mockRestore();
    expect(panel.classList.contains("hidden")).toBe(false);
  });

  test("activates link", () => {
    const panel = document.createElement("div");
    panel.id = "gateways-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);
    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#gateways";
    document.body.appendChild(link);
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("gateways");
    logSpy.mockRestore();
    expect(link.classList.contains("active")).toBe(true);
  });

  test("blocks non-admin", () => {
    isAdminUser.mockReturnValue(false);
    const overviewPanel = document.createElement("div");
    overviewPanel.id = "overview-panel";
    overviewPanel.classList.add("tab-panel", "hidden");
    document.body.appendChild(overviewPanel);
    const overviewLink = document.createElement("a");
    overviewLink.classList.add("sidebar-link");
    overviewLink.href = "#overview";
    document.body.appendChild(overviewLink);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("users");
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("Blocked non-admin")
    );
    warnSpy.mockRestore();
    logSpy.mockRestore();
  });

  test("blocks hidden", () => {
    window.UI_HIDDEN_TABS = ["metrics"];
    const overviewPanel = document.createElement("div");
    overviewPanel.id = "overview-panel";
    overviewPanel.classList.add("tab-panel", "hidden");
    document.body.appendChild(overviewPanel);
    const overviewLink = document.createElement("a");
    overviewLink.classList.add("sidebar-link");
    overviewLink.href = "#overview";
    document.body.appendChild(overviewLink);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("metrics");
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("hidden tab"));
    warnSpy.mockRestore();
    logSpy.mockRestore();
  });

  test("logs error for missing panel", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("nonexistent");
    expect(errorSpy).toHaveBeenCalledWith(expect.stringContaining("not found"));
    errorSpy.mockRestore();
    logSpy.mockRestore();
  });

  test("handles invalid tab name", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    showTab("");
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("without a valid tab name")
    );
    warnSpy.mockRestore();
  });

  test("skips when tab is already visible (idempotency)", () => {
    const panel = document.createElement("div");
    panel.id = "gateways-panel";
    panel.classList.add("tab-panel");
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#gateways";
    document.body.appendChild(link);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("gateways");
    logSpy.mockRestore();

    expect(link.classList.contains("active")).toBe(true);
  });

  test("cleans up observability tab when leaving", () => {
    const obsPanel = document.createElement("div");
    obsPanel.id = "observability-panel";
    obsPanel.classList.add("tab-panel");
    document.body.appendChild(obsPanel);

    const gatewaysPanel = document.createElement("div");
    gatewaysPanel.id = "gateways-panel";
    gatewaysPanel.classList.add("tab-panel", "hidden");
    document.body.appendChild(gatewaysPanel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#gateways";
    document.body.appendChild(link);

    const destroySpy = vi.fn();
    window.chartRegistry = { destroyByPrefix: destroySpy };

    const dispatchSpy = vi.spyOn(document, "dispatchEvent");
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    showTab("gateways");
    vi.runAllTimers();

    expect(destroySpy).toHaveBeenCalledWith("metrics-");
    expect(destroySpy).toHaveBeenCalledWith("tools-");
    expect(destroySpy).toHaveBeenCalledWith("prompts-");
    expect(destroySpy).toHaveBeenCalledWith("resources-");
    expect(dispatchSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "observability:leave",
      })
    );

    logSpy.mockRestore();
  });

  test("loads overview tab content with loading message", () => {
    const panel = document.createElement("div");
    panel.id = "overview-panel";
    panel.classList.add("tab-panel", "hidden");
    panel.innerHTML = "Loading overview...";
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#overview";
    document.body.appendChild(link);

    const triggerSpy = vi.fn();
    window.htmx = { trigger: triggerSpy, ajax: vi.fn(), process: vi.fn() };

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("overview");
    vi.runAllTimers();

    expect(triggerSpy).toHaveBeenCalledWith(panel, "load");
    logSpy.mockRestore();
  });

  test("loads metrics tab", async () => {
    const { loadAggregatedMetrics } =
      await import("../../../mcpgateway/admin_ui/metrics.js");

    const panel = document.createElement("div");
    panel.id = "metrics-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#metrics";
    document.body.appendChild(link);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("metrics");
    vi.runAllTimers();

    expect(loadAggregatedMetrics).toHaveBeenCalled();
    logSpy.mockRestore();
  });

  test("initializes llm-chat tab", async () => {
    const { initializeLLMChat } =
      await import("../../../mcpgateway/admin_ui/llmChat.js");

    const panel = document.createElement("div");
    panel.id = "llm-chat-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#llm-chat";
    document.body.appendChild(link);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("llm-chat");
    vi.runAllTimers();

    expect(initializeLLMChat).toHaveBeenCalled();
    logSpy.mockRestore();
  });

  test("loads logs tab when tbody is empty", async () => {
    const { searchStructuredLogs } =
      await import("../../../mcpgateway/admin_ui/logging.js");

    const panel = document.createElement("div");
    panel.id = "logs-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const tbody = document.createElement("tbody");
    tbody.id = "logs-tbody";
    panel.appendChild(tbody);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#logs";
    document.body.appendChild(link);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("logs");
    vi.runAllTimers();

    expect(searchStructuredLogs).toHaveBeenCalled();
    logSpy.mockRestore();
  });

  test("loads catalog tab with servers list", () => {
    const panel = document.createElement("div");
    panel.id = "catalog-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const serversList = document.createElement("div");
    serversList.id = "servers-table";
    serversList.innerHTML = "Loading servers...";
    panel.appendChild(serversList);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#catalog";
    document.body.appendChild(link);

    const triggerSpy = vi.fn();
    window.htmx = { trigger: triggerSpy, ajax: vi.fn(), process: vi.fn() };

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("catalog");
    vi.runAllTimers();

    expect(triggerSpy).toHaveBeenCalledWith(serversList, "load");
    logSpy.mockRestore();
  });

  test("loads a2a-agents tab", () => {
    const panel = document.createElement("div");
    panel.id = "a2a-agents-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const agentsList = document.createElement("div");
    agentsList.id = "agents-table";
    agentsList.innerHTML = "Loading agents...";
    panel.appendChild(agentsList);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#a2a-agents";
    document.body.appendChild(link);

    const triggerSpy = vi.fn();
    window.htmx = { trigger: triggerSpy, ajax: vi.fn(), process: vi.fn() };

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("a2a-agents");
    vi.runAllTimers();

    expect(triggerSpy).toHaveBeenCalledWith(agentsList, "load");
    logSpy.mockRestore();
  });

  test("loads mcp-registry tab via htmx.ajax", () => {
    const panel = document.createElement("div");
    panel.id = "mcp-registry-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const registryContent = document.createElement("div");
    registryContent.id = "mcp-registry-servers";
    registryContent.innerHTML = "Loading MCP Registry servers...";
    panel.appendChild(registryContent);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#mcp-registry";
    document.body.appendChild(link);

    const ajaxSpy = vi.fn().mockResolvedValue({});
    window.htmx = { trigger: vi.fn(), ajax: ajaxSpy, process: vi.fn() };

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("mcp-registry");
    vi.runAllTimers();

    expect(ajaxSpy).toHaveBeenCalledWith(
      "GET",
      "/admin/mcp-registry/partial",
      expect.any(Object)
    );
    logSpy.mockRestore();
  });

  test("loads export-import tab", async () => {
    const { initializeExportImport } =
      await import("../../../mcpgateway/admin_ui/initialization.js");
    const { loadRecentImports } =
      await import("../../../mcpgateway/admin_ui/fileTransfer.js");

    const panel = document.createElement("div");
    panel.id = "export-import-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#export-import";
    document.body.appendChild(link);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("export-import");
    vi.runAllTimers();

    expect(initializeExportImport).toHaveBeenCalled();
    expect(loadRecentImports).toHaveBeenCalled();
    logSpy.mockRestore();
  });

  test("loads permissions tab", async () => {
    const { initializePermissionsPanel } =
      await import("../../../mcpgateway/admin_ui/users.js");

    const panel = document.createElement("div");
    panel.id = "permissions-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#permissions";
    document.body.appendChild(link);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("permissions");
    vi.runAllTimers();

    expect(initializePermissionsPanel).toHaveBeenCalled();
    logSpy.mockRestore();
  });

  test("loads plugins tab with fetch", async () => {
    const { fetchWithTimeout } =
      await import("../../../mcpgateway/admin_ui/utils.js");

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("<div>Plugins content</div>"),
    });

    const panel = document.createElement("div");
    panel.id = "plugins-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#plugins";
    document.body.appendChild(link);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("plugins");
    vi.runAllTimers();

    await vi.waitFor(() => {
      expect(fetchWithTimeout).toHaveBeenCalledWith(
        "/admin/plugins/partial",
        expect.any(Object),
        5000
      );
    });

    logSpy.mockRestore();
  });

  test("handles plugins tab fetch error", async () => {
    const { fetchWithTimeout } =
      await import("../../../mcpgateway/admin_ui/utils.js");

    fetchWithTimeout.mockRejectedValueOnce(new Error("Network error"));

    const panel = document.createElement("div");
    panel.id = "plugins-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#plugins";
    document.body.appendChild(link);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    showTab("plugins");
    vi.runAllTimers();

    await vi.waitFor(() => {
      expect(errorSpy).toHaveBeenCalledWith(
        expect.stringContaining("Error loading plugins"),
        expect.any(Error)
      );
    });

    logSpy.mockRestore();
    errorSpy.mockRestore();
  });

  test("loads version-info tab with fetch", async () => {
    const { fetchWithTimeout } =
      await import("../../../mcpgateway/admin_ui/utils.js");

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("<div>Version info</div>"),
    });

    const panel = document.createElement("div");
    panel.id = "version-info-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#version-info";
    document.body.appendChild(link);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("version-info");
    vi.runAllTimers();

    await vi.waitFor(() => {
      expect(fetchWithTimeout).toHaveBeenCalledWith(
        "/version?partial=true",
        expect.any(Object),
        expect.any(Number)
      );
    });

    logSpy.mockRestore();
  });

  test("handles version-info tab fetch error", async () => {
    const { fetchWithTimeout } =
      await import("../../../mcpgateway/admin_ui/utils.js");

    fetchWithTimeout.mockRejectedValueOnce(new Error("Fetch failed"));

    const panel = document.createElement("div");
    panel.id = "version-info-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#version-info";
    document.body.appendChild(link);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    showTab("version-info");
    vi.runAllTimers();

    await vi.waitFor(() => {
      expect(errorSpy).toHaveBeenCalledWith(
        expect.stringContaining("Failed to load version info"),
        expect.any(Error)
      );
    });

    logSpy.mockRestore();
    errorSpy.mockRestore();
  });

  test("loads maintenance tab with fetch", async () => {
    const { fetchWithTimeout } =
      await import("../../../mcpgateway/admin_ui/utils.js");

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("<div>Maintenance panel</div>"),
    });

    const panel = document.createElement("div");
    panel.id = "maintenance-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#maintenance";
    document.body.appendChild(link);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("maintenance");
    vi.runAllTimers();

    await vi.waitFor(() => {
      expect(fetchWithTimeout).toHaveBeenCalledWith(
        "/admin/maintenance/partial",
        expect.any(Object),
        expect.any(Number)
      );
    });

    logSpy.mockRestore();
  });

  test("handles maintenance tab 403 error", async () => {
    const { fetchWithTimeout } =
      await import("../../../mcpgateway/admin_ui/utils.js");

    fetchWithTimeout.mockResolvedValueOnce({
      ok: false,
      status: 403,
      statusText: "Forbidden",
    });

    const panel = document.createElement("div");
    panel.id = "maintenance-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#maintenance";
    document.body.appendChild(link);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    showTab("maintenance");
    vi.runAllTimers();

    await vi.waitFor(() => {
      expect(errorSpy).toHaveBeenCalledWith(
        expect.stringContaining("Failed to load maintenance panel"),
        expect.any(Error)
      );
    });

    logSpy.mockRestore();
    errorSpy.mockRestore();
  });

  test("loads gateways tab with fetch fallback when htmx not available", async () => {
    delete window.htmx;

    const panel = document.createElement("div");
    panel.id = "gateways-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const gatewaysTable = document.createElement("div");
    gatewaysTable.id = "gateways-table";
    gatewaysTable.innerHTML = "Loading gateways...";
    panel.appendChild(gatewaysTable);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#gateways";
    document.body.appendChild(link);

    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      text: () =>
        Promise.resolve('<div id="gateways-table"><div>Gateway 1</div></div>'),
    });

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("gateways");
    vi.runAllTimers();

    await vi.waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith("/admin");
    });

    logSpy.mockRestore();
  });

  test("loads mcp-registry tab with fetch fallback when htmx not available", async () => {
    delete window.htmx;

    const panel = document.createElement("div");
    panel.id = "mcp-registry-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const registryContent = document.createElement("div");
    registryContent.id = "mcp-registry-servers";
    registryContent.innerHTML = "Loading MCP Registry servers...";
    panel.appendChild(registryContent);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#mcp-registry";
    document.body.appendChild(link);

    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("<div>Registry content</div>"),
    });

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    showTab("mcp-registry");
    vi.runAllTimers();

    await vi.waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith("/admin/mcp-registry/partial");
    });

    logSpy.mockRestore();
  });

  test("handles mcp-registry tab fetch error", async () => {
    delete window.htmx;

    const panel = document.createElement("div");
    panel.id = "mcp-registry-panel";
    panel.classList.add("tab-panel", "hidden");
    document.body.appendChild(panel);

    const registryContent = document.createElement("div");
    registryContent.id = "mcp-registry-servers";
    registryContent.innerHTML = "Loading MCP Registry servers...";
    panel.appendChild(registryContent);

    const link = document.createElement("a");
    link.classList.add("sidebar-link");
    link.href = "#mcp-registry";
    document.body.appendChild(link);

    global.fetch = vi.fn().mockRejectedValueOnce(new Error("Network error"));

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    showTab("mcp-registry");
    vi.runAllTimers();

    await vi.waitFor(() => {
      expect(errorSpy).toHaveBeenCalledWith(
        expect.stringContaining("Failed to load MCP Registry"),
        expect.any(Error)
      );
    });

    logSpy.mockRestore();
    errorSpy.mockRestore();
  });
});
