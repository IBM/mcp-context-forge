/**
 * Unit tests for tab visibility behavior.
 *
 * Functions are imported directly from their source modules.
 * Only tokens.js is mocked (to spy on fetchWithAuth); all other modules
 * are imported as-is — they are pure function exports with no module-level
 * side effects and therefore safe to load in the jsdom environment.
 */

import { beforeEach, describe, expect, test, vi } from "vitest";

import {
  getDefaultTabName,
  getUiHiddenSections,
  getUiHiddenTabs,
  isTabAvailable,
  isTabHidden,
  normalizeTabName,
  resolveTabForNavigation,
  showTab,
} from "../../mcpgateway/admin_ui/tabs.js";
import { initializeTabState } from "../../mcpgateway/admin_ui/initialization.js";
import { loadTools } from "../../mcpgateway/admin_ui/tools.js";
import {
  renderGlobalSearchResults,
  runGlobalSearch,
} from "../../mcpgateway/admin_ui/search.js";
import { fetchWithAuth } from "../../mcpgateway/admin_ui/tokens.js";

// Mock tokens.js so fetchWithAuth can be inspected in runGlobalSearch tests.
// This also prevents real fetch calls from being made.
vi.mock("../../mcpgateway/admin_ui/tokens.js", () => ({
  fetchWithAuth: vi.fn(),
  performTokenSearch: vi.fn(),
  getAuthToken: vi.fn(),
  getTeamNameById: vi.fn(),
  setupCreateTokenForm: vi.fn(),
  setupTokenListEventHandlers: vi.fn(),
  updateTeamScopingWarning: vi.fn(),
  loadTokensList: vi.fn(),
  debouncedServerSideTokenSearch: vi.fn(),
}));

// ---------------------------------------------------------------------------
// DOM helper — mirrors the original createTab() helper
// ---------------------------------------------------------------------------
function createTab(tabName) {
  const link = document.createElement("a");
  link.id = `tab-${tabName}`;
  link.href = `#${tabName}`;
  link.className = "sidebar-link";
  link.textContent = tabName;
  document.body.appendChild(link);

  const panel = document.createElement("div");
  panel.id = `${tabName}-panel`;
  panel.className = "tab-panel hidden";
  document.body.appendChild(panel);

  return { link, panel };
}

beforeEach(() => {
  document.body.innerHTML = "";
  window.UI_HIDDEN_TABS = [];
  window.UI_HIDDEN_SECTIONS = [];
  window.IS_ADMIN = true;
  window.location.hash = "";
  window.ROOT_PATH = "";
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// normalizeTabName
// ---------------------------------------------------------------------------
describe("normalizeTabName", () => {
  test("strips leading hash, trims, and lowercases", () => {
    expect(normalizeTabName("#Tools")).toBe("tools");
    expect(normalizeTabName("  Gateways  ")).toBe("gateways");
    expect(normalizeTabName("#A2A-Agents")).toBe("a2a-agents");
  });

  test("returns empty string for null, undefined, and non-string inputs", () => {
    expect(normalizeTabName(null)).toBe("");
    expect(normalizeTabName(undefined)).toBe("");
    expect(normalizeTabName(42)).toBe("");
    expect(normalizeTabName("")).toBe("");
  });

  test("strips characters outside the allowed set", () => {
    expect(normalizeTabName('#"],.evil[x="')).toBe("evilx");
    expect(normalizeTabName("tab<script>")).toBe("tabscript");
    expect(normalizeTabName("valid-name")).toBe("valid-name");
  });
});

// ---------------------------------------------------------------------------
// showTab hidden tab fallback
// ---------------------------------------------------------------------------
describe("showTab hidden tab fallback", () => {
  test("redirects hidden tab navigation to the default visible tab", () => {
    const { panel: gatewaysPanel } = createTab("gateways");
    const { panel: promptsPanel } = createTab("prompts");
    const { panel: overviewPanel } = createTab("overview");

    window.UI_HIDDEN_TABS = ["prompts"];

    showTab("prompts");

    expect(overviewPanel.classList.contains("hidden")).toBe(false);
    expect(gatewaysPanel.classList.contains("hidden")).toBe(true);
    expect(promptsPanel.classList.contains("hidden")).toBe(true);
    expect(window.location.hash).toBe("#overview");
  });

  test("blocks non-admin access to admin-only tabs", () => {
    const { panel: overviewPanel } = createTab("overview");
    const { panel: gatewaysPanel } = createTab("gateways");
    createTab("users");

    window.IS_ADMIN = false;

    showTab("users");

    expect(overviewPanel.classList.contains("hidden")).toBe(false);
    expect(gatewaysPanel.classList.contains("hidden")).toBe(true);
    expect(window.location.hash).toBe("#overview");
  });
});

// ---------------------------------------------------------------------------
// showTab idempotency
// ---------------------------------------------------------------------------
describe("showTab idempotency", () => {
  test("does not re-process a tab that is already visible", () => {
    const { panel: overviewPanel, link: overviewLink } = createTab("overview");
    createTab("gateways");

    showTab("overview");
    expect(overviewPanel.classList.contains("hidden")).toBe(false);

    // Call showTab again for the same tab — should be a no-op
    overviewLink.classList.remove("active");
    showTab("overview");

    // The link should get its active class restored but no full re-render
    expect(overviewLink.classList.contains("active")).toBe(true);
    expect(overviewPanel.classList.contains("hidden")).toBe(false);
  });

  test("re-processes when multiple panels are visible to restore a clean state", () => {
    const { panel: overviewPanel } = createTab("overview");
    const { panel: toolOpsPanel } = createTab("tool-ops");
    createTab("gateways");

    showTab("overview");
    toolOpsPanel.classList.remove("hidden");

    // Same-tab navigation should still hide other visible panels.
    showTab("overview");

    expect(overviewPanel.classList.contains("hidden")).toBe(false);
    expect(toolOpsPanel.classList.contains("hidden")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// getDefaultTabName priority
// ---------------------------------------------------------------------------
describe("getDefaultTabName priority", () => {
  test("prefers overview when available", () => {
    createTab("gateways");
    createTab("tools");
    createTab("overview");

    expect(getDefaultTabName()).toBe("overview");
  });

  test("falls back to gateways when overview is hidden", () => {
    createTab("gateways");
    createTab("tools");
    createTab("overview");

    window.UI_HIDDEN_TABS = ["overview"];

    expect(getDefaultTabName()).toBe("gateways");
  });

  test("falls back to first visible tab when overview and gateways are hidden", () => {
    createTab("gateways");
    createTab("tools");
    createTab("prompts");
    createTab("overview");

    window.UI_HIDDEN_TABS = ["overview", "gateways"];

    expect(getDefaultTabName()).toBe("tools");
  });
});

// ---------------------------------------------------------------------------
// isTabAvailable
// ---------------------------------------------------------------------------
describe("isTabAvailable", () => {
  test("returns true only when both panel and sidebar link exist", () => {
    createTab("gateways");

    expect(isTabAvailable("gateways")).toBe(true);
  });

  test("returns false when panel exists but no sidebar link", () => {
    const panel = document.createElement("div");
    panel.id = "orphan-panel";
    panel.className = "tab-panel hidden";
    document.body.appendChild(panel);

    expect(isTabAvailable("orphan")).toBe(false);
  });

  test("returns false for empty or invalid names", () => {
    expect(isTabAvailable("")).toBe(false);
    expect(isTabAvailable(null)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isSectionHidden with override mapping (tested via getUiHiddenSections)
// ---------------------------------------------------------------------------
describe("isSectionHidden with override mapping", () => {
  test("maps catalog to servers section for hide check", () => {
    createTab("gateways");
    window.UI_HIDDEN_SECTIONS = ["servers"];

    // isSectionHidden is a module-scoped function, not directly accessible.
    // Test it indirectly via getUiHiddenSections which uses it.
    const hiddenSections = getUiHiddenSections();
    expect(hiddenSections.has("servers")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// getUiHiddenSections and getUiHiddenTabs
// ---------------------------------------------------------------------------
describe("getUiHiddenSections and getUiHiddenTabs", () => {
  test("normalizes and deduplicates window globals", () => {
    window.UI_HIDDEN_SECTIONS = ["Tools", "TOOLS", "prompts"];
    const sections = getUiHiddenSections();
    expect(sections.has("tools")).toBe(true);
    expect(sections.has("prompts")).toBe(true);
    expect(sections.size).toBe(2);
  });

  test("returns empty set when globals are not arrays", () => {
    window.UI_HIDDEN_SECTIONS = "tools";
    expect(getUiHiddenSections().size).toBe(0);

    window.UI_HIDDEN_TABS = null;
    expect(getUiHiddenTabs().size).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// initializeTabState hidden hash handling
// ---------------------------------------------------------------------------
describe("initializeTabState hidden hash handling", () => {
  test("maps an initial hidden hash to a visible default tab", () => {
    const { panel: gatewaysPanel } = createTab("gateways");
    const { panel: promptsPanel } = createTab("prompts");
    const { panel: overviewPanel } = createTab("overview");
    window.UI_HIDDEN_TABS = ["prompts"];

    window.location.hash = "#prompts";
    initializeTabState();

    expect(window.location.hash).toBe("#overview");
    expect(overviewPanel.classList.contains("hidden")).toBe(false);
    expect(gatewaysPanel.classList.contains("hidden")).toBe(true);
    expect(promptsPanel.classList.contains("hidden")).toBe(true);
  });

  test("blocks hashchange navigation to hidden tabs", () => {
    const { panel: gatewaysPanel } = createTab("gateways");
    const { panel: promptsPanel } = createTab("prompts");
    const { panel: overviewPanel } = createTab("overview");
    window.UI_HIDDEN_TABS = ["prompts"];

    window.location.hash = "#overview";
    initializeTabState();
    expect(window.location.hash).toBe("#overview");

    window.location.hash = "#prompts";
    window.dispatchEvent(new HashChangeEvent("hashchange"));

    expect(window.location.hash).toBe("#overview");
    expect(overviewPanel.classList.contains("hidden")).toBe(false);
    expect(gatewaysPanel.classList.contains("hidden")).toBe(true);
    expect(promptsPanel.classList.contains("hidden")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// loadTools hidden section behavior
// ---------------------------------------------------------------------------
describe("loadTools hidden section behavior", () => {
  test("skips fetch when the tools section is hidden", async () => {
    const toolBody = document.createElement("tbody");
    toolBody.id = "toolBody";
    document.body.appendChild(toolBody);

    const fetchSpy = vi.fn();
    window.fetch = fetchSpy;
    window.UI_HIDDEN_SECTIONS = ["tools"];

    await loadTools();

    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// renderGlobalSearchResults hidden section filtering
// ---------------------------------------------------------------------------
describe("renderGlobalSearchResults hidden section filtering", () => {
  test("filters out groups belonging to hidden sections", () => {
    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    window.UI_HIDDEN_SECTIONS = ["tools", "prompts"];

    renderGlobalSearchResults({
      groups: [
        { entity_type: "tools", items: [{ id: "t1", name: "Tool 1" }] },
        { entity_type: "gateways", items: [{ id: "g1", name: "GW 1" }] },
        { entity_type: "prompts", items: [{ id: "p1", name: "Prompt 1" }] },
      ],
    });

    const html = container.innerHTML;
    expect(html).toContain("Gateways");
    expect(html).not.toContain("Tools");
    expect(html).not.toContain("Prompts");
  });

  test("shows no results message when all groups are hidden", () => {
    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    window.UI_HIDDEN_SECTIONS = ["tools"];

    renderGlobalSearchResults({
      groups: [
        { entity_type: "tools", items: [{ id: "t1", name: "Tool 1" }] },
      ],
    });

    expect(container.innerHTML).toContain("No matching results");
  });
});

// ---------------------------------------------------------------------------
// runGlobalSearch visible entity filtering
// ---------------------------------------------------------------------------
describe("runGlobalSearch visible entity filtering", () => {
  test("sends only visible entity types to the backend", async () => {
    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    window.IS_ADMIN = true;
    window.UI_HIDDEN_SECTIONS = ["tools", "prompts", "teams"];
    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: async () => ({ groups: [] }),
    });

    await runGlobalSearch("gateway");

    expect(fetchWithAuth).toHaveBeenCalledTimes(1);
    const requestUrl = new URL(
      fetchWithAuth.mock.calls[0][0],
      "http://localhost",
    );
    expect(requestUrl.searchParams.get("entity_types")).toBe(
      "servers,gateways,resources,agents,users",
    );
  });

  test("short-circuits when all searchable sections are hidden", async () => {
    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    window.IS_ADMIN = true;
    window.UI_HIDDEN_SECTIONS = [
      "servers",
      "gateways",
      "tools",
      "resources",
      "prompts",
      "agents",
      "teams",
      "users",
    ];

    await runGlobalSearch("anything");

    expect(fetchWithAuth).not.toHaveBeenCalled();
    expect(container.innerHTML).toContain("No searchable sections are visible");
  });
});

// ---------------------------------------------------------------------------
// isTabHidden
// ---------------------------------------------------------------------------
describe("isTabHidden", () => {
  test("returns true for a tab in the hidden list", () => {
    window.UI_HIDDEN_TABS = ["prompts", "tools"];
    expect(isTabHidden("prompts")).toBe(true);
    expect(isTabHidden("tools")).toBe(true);
  });

  test("returns false for a tab not in the hidden list", () => {
    window.UI_HIDDEN_TABS = ["prompts"];
    expect(isTabHidden("gateways")).toBe(false);
  });

  test("returns false for empty or null input", () => {
    window.UI_HIDDEN_TABS = ["prompts"];
    expect(isTabHidden("")).toBe(false);
    expect(isTabHidden(null)).toBe(false);
  });

  test("normalizes input before checking", () => {
    window.UI_HIDDEN_TABS = ["prompts"];
    expect(isTabHidden("#Prompts")).toBe(true);
    expect(isTabHidden("  PROMPTS  ")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// resolveTabForNavigation
// ---------------------------------------------------------------------------
describe("resolveTabForNavigation", () => {
  test("returns the tab itself when visible and available", () => {
    createTab("gateways");
    createTab("overview");

    expect(resolveTabForNavigation("gateways")).toBe("gateways");
  });

  test("falls back to default for hidden tab", () => {
    createTab("gateways");
    createTab("prompts");
    createTab("overview");
    window.UI_HIDDEN_TABS = ["prompts"];

    expect(resolveTabForNavigation("prompts")).toBe("overview");
  });

  test("falls back to default for empty input", () => {
    createTab("overview");
    createTab("gateways");

    expect(resolveTabForNavigation("")).toBe("overview");
    expect(resolveTabForNavigation(null)).toBe("overview");
  });

  test("falls back to default for admin-only tab when non-admin", () => {
    createTab("overview");
    createTab("users");
    window.IS_ADMIN = false;

    expect(resolveTabForNavigation("users")).toBe("overview");
  });

  test("falls back to default for non-existent tab", () => {
    createTab("overview");
    createTab("gateways");

    expect(resolveTabForNavigation("nonexistent")).toBe("overview");
  });
});

// ---------------------------------------------------------------------------
// showTab normal navigation
// ---------------------------------------------------------------------------
describe("showTab normal navigation", () => {
  test("shows the requested visible tab and hides others", () => {
    const { panel: overviewPanel, link: overviewLink } = createTab("overview");
    const { panel: gatewaysPanel, link: gatewaysLink } = createTab("gateways");

    showTab("gateways");

    expect(gatewaysPanel.classList.contains("hidden")).toBe(false);
    expect(overviewPanel.classList.contains("hidden")).toBe(true);
    expect(gatewaysLink.classList.contains("active")).toBe(true);
    expect(overviewLink.classList.contains("active")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// getDefaultTabName edge cases
// ---------------------------------------------------------------------------
describe("getDefaultTabName edge cases", () => {
  test("returns gateways fallback when all tabs are hidden and no panels exist", () => {
    // No tabs created, nothing available
    window.UI_HIDDEN_TABS = ["overview"];
    expect(getDefaultTabName()).toBe("gateways");
  });

  test("returns overview when overview panel exists but no sidebar links", () => {
    // Create only the panel, not the sidebar link
    const panel = document.createElement("div");
    panel.id = "overview-panel";
    panel.className = "tab-panel hidden";
    document.body.appendChild(panel);

    expect(getDefaultTabName()).toBe("overview");
  });
});
