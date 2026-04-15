/**
 * Unit tests for search.js module
 */

import { describe, test, expect, vi, afterEach, beforeEach } from "vitest";

import {
  clearSearch,
  serverSideToolSearch,
  serverSidePromptSearch,
  serverSideResourceSearch,
  serverSideEditToolSearch,
  serverSideEditPromptsSearch,
  serverSideEditResourcesSearch,
  getPanelSearchConfig,
  getPanelSearchStateFromUrl,
  updatePanelSearchStateInUrl,
  getPanelPerPage,
  loadSearchablePanel,
  queueSearchablePanelReload,
  renderGlobalSearchMessage,
  renderGlobalSearchResults,
  runGlobalSearch,
  openGlobalSearchModal,
  closeGlobalSearchModal,
  navigateToGlobalSearchResult,
  ensureNoResultsElement,
  captureNonMemberSelections,
  restoreNonMemberSelections,
  captureMemberOverrides,
  restoreMemberOverrides,
  debouncedMemberSearch,
  debouncedNonMemberSearch,
  serverSideMemberSearch,
  serverSideNonMemberSearch,
} from "../../../mcpgateway/admin_ui/search.js";
import { AppState } from "../../../mcpgateway/admin_ui/appState.js";

// Mock dependencies
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  getCookie: vi.fn(() => "mock-token"),
  getCurrentTeamId: vi.fn(() => null),
  isAdminUser: vi.fn(() => false),
  fetchWithAuth: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  fetchWithAuth: vi.fn(),
  performTokenSearch: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((str) => String(str).replace(/[&<>"']/g, (m) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[m])),
  safeReplaceState: vi.fn((state, title, url) => {
    window.history.replaceState(state, title, url);
  }),
}));

vi.mock("../../../mcpgateway/admin_ui/tabs.js", () => ({
  getUiHiddenSections: vi.fn(() => new Set()),
  showTab: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/filters.js", () => ({
  filterServerTable: vi.fn(),
  filterToolsTable: vi.fn(),
  filterResourcesTable: vi.fn(),
  filterPromptsTable: vi.fn(),
  filterGatewaysTable: vi.fn(),
  filterA2AAgentsTable: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/gateways.js", () => ({
  getSelectedGatewayIds: vi.fn(() => []),
}));

vi.mock("../../../mcpgateway/admin_ui/servers.js", () => ({
  getEditSelections: vi.fn(() => new Set()),
  updateToolMapping: vi.fn(),
  updatePromptMapping: vi.fn(),
  updateResourceMapping: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/tools.js", () => ({
  initToolSelect: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/prompts.js", () => ({
  initPromptSelect: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/resources.js", () => ({
  initResourceSelect: vi.fn(),
}));

beforeEach(() => {
  window.ROOT_PATH = "";
  window.htmx = {
    ajax: vi.fn(),
  };
  window.Admin = {
    toolMapping: {},
    promptMapping: {},
    resourceMapping: {},
  };
  vi.clearAllMocks();
});

afterEach(() => {
  document.body.innerHTML = "";
  delete window.htmx;
  delete window.Admin;
});

// Helper: build a simple table with searchable rows
function buildSearchableTable(entityType, tbodyId, rows) {
  const panel = document.createElement("div");
  panel.id = `${entityType}-panel`;

  const input = document.createElement("input");
  // Match the actual IDs used in PANEL_SEARCH_CONFIG
  const searchInputId = entityType === "catalog" ? "servers-search-input" : `${entityType}-search-input`;
  input.id = searchInputId;
  input.value = "previous search";
  panel.appendChild(input);

  const table = document.createElement("table");
  const tbody = document.createElement("tbody");
  tbody.id = tbodyId;

  rows.forEach((text) => {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.textContent = text;
    tr.appendChild(td);
    tbody.appendChild(tr);
  });

  table.appendChild(tbody);
  panel.appendChild(table);
  document.body.appendChild(panel);
  return input;
}

// ---------------------------------------------------------------------------
// clearSearch
// ---------------------------------------------------------------------------
describe("clearSearch", () => {
  test("clears catalog search input", () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const input = buildSearchableTable("catalog", "servers-table-body", ["Server A"]);
    clearSearch("catalog");
    expect(input.value).toBe("");
    consoleSpy.mockRestore();
  });

  test("clears tools search input", () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const input = buildSearchableTable("tools", "tools-table-body", ["Tool A"]);
    clearSearch("tools");
    expect(input.value).toBe("");
    consoleSpy.mockRestore();
  });

  test("clears resources search input", () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const input = buildSearchableTable("resources", "resources-table-body", ["Res A"]);
    clearSearch("resources");
    expect(input.value).toBe("");
    consoleSpy.mockRestore();
  });

  test("clears prompts search input", () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const input = buildSearchableTable("prompts", "prompts-table-body", ["Prompt A"]);
    clearSearch("prompts");
    expect(input.value).toBe("");
    consoleSpy.mockRestore();
  });

  test("clears a2a-agents search input", () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const input = buildSearchableTable("a2a-agents", "agents-table-body", ["Agent A"]);
    clearSearch("a2a-agents");
    expect(input.value).toBe("");
    consoleSpy.mockRestore();
  });

  test("clears gateways search input", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const input = buildSearchableTable("gateways", "gateways-table-body", ["GW A"]);
    clearSearch("gateways");
    expect(input.value).toBe("");
    consoleSpy.mockRestore();
  });

  test("does not throw for unknown entity type", () => {
    expect(() => clearSearch("unknown")).not.toThrow();
  });

  test("does not throw when input elements are missing", () => {
    expect(() => clearSearch("catalog")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// serverSideToolSearch
// ---------------------------------------------------------------------------
describe("serverSideToolSearch", () => {
  test("does nothing when container is missing", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await serverSideToolSearch("test");
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("not found")
    );
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// serverSidePromptSearch
// ---------------------------------------------------------------------------
describe("serverSidePromptSearch", () => {
  test("does nothing when container is missing", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await serverSidePromptSearch("test");
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("not found")
    );
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// serverSideResourceSearch
// ---------------------------------------------------------------------------
describe("serverSideResourceSearch", () => {
  test("does nothing when container is missing", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await serverSideResourceSearch("test");
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("not found")
    );
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// getPanelSearchConfig
// ---------------------------------------------------------------------------
describe("getPanelSearchConfig", () => {
  test("returns config for valid entity type", () => {
    const config = getPanelSearchConfig("catalog");
    expect(config).toBeTruthy();
    expect(config.tableName).toBe("servers");
  });

  test("returns null for invalid entity type", () => {
    const config = getPanelSearchConfig("invalid");
    expect(config).toBeNull();
  });

  test("returns config for tools", () => {
    const config = getPanelSearchConfig("tools");
    expect(config).toBeTruthy();
    expect(config.tableName).toBe("tools");
  });

  test("returns config for resources", () => {
    const config = getPanelSearchConfig("resources");
    expect(config).toBeTruthy();
    expect(config.tableName).toBe("resources");
  });

  test("returns config for prompts", () => {
    const config = getPanelSearchConfig("prompts");
    expect(config).toBeTruthy();
    expect(config.tableName).toBe("prompts");
  });
});

// ---------------------------------------------------------------------------
// getPanelSearchStateFromUrl
// ---------------------------------------------------------------------------
describe("getPanelSearchStateFromUrl", () => {
  test("extracts query and tags from URL", () => {
    window.history.replaceState({}, "", "?servers_q=test&servers_tags=tag1");
    const state = getPanelSearchStateFromUrl("servers");
    expect(state.query).toBe("test");
    expect(state.tags).toBe("tag1");
  });

  test("returns empty strings when params missing", () => {
    window.history.replaceState({}, "", "?other=value");
    const state = getPanelSearchStateFromUrl("servers");
    expect(state.query).toBe("");
    expect(state.tags).toBe("");
  });

  test("trims whitespace from values", () => {
    window.history.replaceState({}, "", "?servers_q=  test  &servers_tags=  tag1  ");
    const state = getPanelSearchStateFromUrl("servers");
    expect(state.query).toBe("test");
    expect(state.tags).toBe("tag1");
  });
});

// ---------------------------------------------------------------------------
// updatePanelSearchStateInUrl
// ---------------------------------------------------------------------------
describe("updatePanelSearchStateInUrl", () => {
  test("sets query param in URL", () => {
    updatePanelSearchStateInUrl("servers", "test", "");
    expect(window.location.search).toContain("servers_q=test");
  });

  test("sets tags param in URL", () => {
    updatePanelSearchStateInUrl("servers", "", "tag1");
    expect(window.location.search).toContain("servers_tags=tag1");
  });

  test("removes params when empty", () => {
    window.history.replaceState({}, "", "?servers_q=test&servers_tags=tag1");
    updatePanelSearchStateInUrl("servers", "", "");
    expect(window.location.search).not.toContain("servers_q");
    expect(window.location.search).not.toContain("servers_tags");
  });

  test("resets page to 1", () => {
    updatePanelSearchStateInUrl("servers", "test", "");
    expect(window.location.search).toContain("servers_page=1");
  });

  test("trims whitespace from inputs", () => {
    updatePanelSearchStateInUrl("servers", "  test  ", "  tag1  ");
    expect(window.location.search).toContain("servers_q=test");
    expect(window.location.search).toContain("servers_tags=tag1");
  });
});

// ---------------------------------------------------------------------------
// getPanelPerPage
// ---------------------------------------------------------------------------
describe("getPanelPerPage", () => {
  test("returns value from selector", () => {
    const select = document.createElement("select");
    select.id = "servers-pagination-controls";
    select.innerHTML = '<option value="25" selected>25</option>';

    const controls = document.createElement("div");
    controls.id = "servers-pagination-controls";
    controls.appendChild(select);
    document.body.appendChild(controls);

    const perPage = getPanelPerPage({ tableName: "servers", defaultPerPage: 10 });
    expect(perPage).toBe(25);
  });

  test("returns default when selector missing", () => {
    const perPage = getPanelPerPage({ tableName: "servers", defaultPerPage: 10 });
    expect(perPage).toBe(10);
  });

  test("returns default when value is NaN", () => {
    const select = document.createElement("select");
    select.value = "invalid";

    const controls = document.createElement("div");
    controls.id = "servers-pagination-controls";
    controls.appendChild(select);
    document.body.appendChild(controls);

    const perPage = getPanelPerPage({ tableName: "servers", defaultPerPage: 10 });
    expect(perPage).toBe(10);
  });
});

// ---------------------------------------------------------------------------
// loadSearchablePanel
// ---------------------------------------------------------------------------
describe("loadSearchablePanel", () => {
  test("does nothing for invalid entity type", () => {
    loadSearchablePanel("invalid");
    expect(window.htmx.ajax).not.toHaveBeenCalled();
  });

  test("loads panel with search params", () => {
    const searchInput = document.createElement("input");
    searchInput.id = "servers-search-input";
    searchInput.value = "test";
    document.body.appendChild(searchInput);

    const tagInput = document.createElement("input");
    tagInput.id = "servers-tag-filter";
    tagInput.value = "tag1";
    document.body.appendChild(tagInput);

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = "show-inactive-servers";
    checkbox.checked = true;
    document.body.appendChild(checkbox);

    loadSearchablePanel("catalog");

    expect(window.htmx.ajax).toHaveBeenCalledWith(
      "GET",
      expect.stringContaining("q=test"),
      expect.any(Object)
    );
  });

  test("includes team_id when available", async () => {
    const { getCurrentTeamId } = await import("../../../mcpgateway/admin_ui/utils.js");
    getCurrentTeamId.mockReturnValue("team-123");

    const searchInput = document.createElement("input");
    searchInput.id = "catalog-search-input";
    document.body.appendChild(searchInput);

    loadSearchablePanel("catalog");

    expect(window.htmx.ajax).toHaveBeenCalledWith(
      "GET",
      expect.stringContaining("team_id=team-123"),
      expect.any(Object)
    );
  });
});

// ---------------------------------------------------------------------------
// queueSearchablePanelReload
// ---------------------------------------------------------------------------
describe("queueSearchablePanelReload", () => {
  test("debounces panel reload", () => {
    vi.useFakeTimers();

    const searchInput = document.createElement("input");
    searchInput.id = "catalog-search-input";
    document.body.appendChild(searchInput);

    queueSearchablePanelReload("catalog", 100);
    expect(window.htmx.ajax).not.toHaveBeenCalled();

    vi.advanceTimersByTime(100);
    expect(window.htmx.ajax).toHaveBeenCalled();

    vi.useRealTimers();
  });

  test("cancels previous timer", () => {
    vi.useFakeTimers();

    const searchInput = document.createElement("input");
    searchInput.id = "catalog-search-input";
    document.body.appendChild(searchInput);

    queueSearchablePanelReload("catalog", 100);
    queueSearchablePanelReload("catalog", 100);

    vi.advanceTimersByTime(100);
    expect(window.htmx.ajax).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
  });
});

// ---------------------------------------------------------------------------
// renderGlobalSearchMessage
// ---------------------------------------------------------------------------
describe("renderGlobalSearchMessage", () => {
  test("renders message in container", () => {
    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    renderGlobalSearchMessage("Test message");
    expect(container.innerHTML).toContain("Test message");
  });

  test("does nothing when container missing", () => {
    expect(() => renderGlobalSearchMessage("Test")).not.toThrow();
  });

  test("escapes HTML in message", () => {
    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    renderGlobalSearchMessage("<script>alert('xss')</script>");
    expect(container.innerHTML).not.toContain("<script>");
    expect(container.innerHTML).toContain("&lt;script&gt;");
  });
});

// ---------------------------------------------------------------------------
// renderGlobalSearchResults
// ---------------------------------------------------------------------------
describe("renderGlobalSearchResults", () => {
  test("renders results grouped by entity type", () => {
    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    const payload = {
      groups: [
        {
          entity_type: "servers",
          items: [
            { id: "s1", name: "Server 1", description: "Test server" }
          ]
        }
      ]
    };

    renderGlobalSearchResults(payload);
    expect(container.innerHTML).toContain("Server 1");
    expect(container.innerHTML).toContain("Test server");
  });

  test("shows no results message when empty", () => {
    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    renderGlobalSearchResults({ groups: [] });
    expect(container.innerHTML).toContain("No matching results");
  });

  test("filters hidden sections", async () => {
    const { getUiHiddenSections } = await import("../../../mcpgateway/admin_ui/tabs.js");
    getUiHiddenSections.mockReturnValueOnce(new Set(["servers"]));

    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    const payload = {
      groups: [
        {
          entity_type: "servers",
          items: [{ id: "s1", name: "Server 1" }]
        }
      ]
    };

    renderGlobalSearchResults(payload);
    expect(container.innerHTML).toContain("No matching results");
  });

  test("attaches click listeners to results", () => {
    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    const payload = {
      groups: [
        {
          entity_type: "servers",
          items: [{ id: "s1", name: "Server 1" }]
        }
      ]
    };

    renderGlobalSearchResults(payload);
    const button = container.querySelector('[data-action="navigate-search-result"]');
    expect(button).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// runGlobalSearch
// ---------------------------------------------------------------------------
describe("runGlobalSearch", () => {
  test("shows message for empty query", async () => {
    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    await runGlobalSearch("");
    expect(container.innerHTML).toContain("Start typing");
  });

  test("performs search with query", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: async () => ({ groups: [] })
    });

    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    await runGlobalSearch("test");
    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("q=test")
    );
  });

  test("handles search error", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    fetchWithAuth.mockRejectedValue(new Error("Network error"));

    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await runGlobalSearch("test");
    expect(container.innerHTML).toContain("Search failed");
    consoleSpy.mockRestore();
  });

  test("ignores out-of-order responses", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");

    let resolveFirst;
    const firstPromise = new Promise(resolve => { resolveFirst = resolve; });

    fetchWithAuth
      .mockReturnValueOnce(firstPromise)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ groups: [{ entity_type: "servers", items: [{ id: "s2", name: "Server 2" }] }] })
      });

    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    const search1 = runGlobalSearch("first");
    const search2 = runGlobalSearch("second");

    await search2;
    expect(container.innerHTML).toContain("Server 2");

    resolveFirst({
      ok: true,
      json: async () => ({ groups: [{ entity_type: "servers", items: [{ id: "s1", name: "Server 1" }] }] })
    });
    await search1;

    // Should still show Server 2 (latest request)
    expect(container.innerHTML).toContain("Server 2");
    expect(container.innerHTML).not.toContain("Server 1");
  });

  test("includes roots in entity_types for admin users", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    const { isAdminUser } = await import("../../../mcpgateway/admin_ui/utils.js");
    const { getUiHiddenSections } = await import("../../../mcpgateway/admin_ui/tabs.js");
    isAdminUser.mockReturnValue(true);
    getUiHiddenSections.mockReturnValue(new Set());
    fetchWithAuth.mockResolvedValue({ ok: true, json: async () => ({ groups: [] }) });

    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    await runGlobalSearch("tmp");

    expect(fetchWithAuth).toHaveBeenCalledTimes(1);
    const requestUrl = new URL(fetchWithAuth.mock.calls[0][0], "http://localhost");
    const entityTypes = requestUrl.searchParams.get("entity_types").split(",");
    expect(entityTypes).toContain("roots");
  });

  test("omits roots when the roots section is hidden", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    const { isAdminUser } = await import("../../../mcpgateway/admin_ui/utils.js");
    const { getUiHiddenSections } = await import("../../../mcpgateway/admin_ui/tabs.js");
    isAdminUser.mockReturnValue(true);
    getUiHiddenSections.mockReturnValue(new Set(["roots"]));
    fetchWithAuth.mockResolvedValue({ ok: true, json: async () => ({ groups: [] }) });

    const container = document.createElement("div");
    container.id = "global-search-results";
    document.body.appendChild(container);

    await runGlobalSearch("tmp");

    const requestUrl = new URL(fetchWithAuth.mock.calls[0][0], "http://localhost");
    const entityTypes = requestUrl.searchParams.get("entity_types").split(",");
    expect(entityTypes).not.toContain("roots");
  });
});

// ---------------------------------------------------------------------------
// openGlobalSearchModal
// ---------------------------------------------------------------------------
describe("openGlobalSearchModal", () => {
  test("opens modal and focuses input", () => {
    const modal = document.createElement("div");
    modal.id = "global-search-modal";
    modal.classList.add("hidden");
    document.body.appendChild(modal);

    const input = document.createElement("input");
    input.id = "global-search-input";
    modal.appendChild(input);

    const focusSpy = vi.spyOn(input, "focus");

    openGlobalSearchModal();

    expect(modal.classList.contains("hidden")).toBe(false);
    expect(modal.getAttribute("aria-hidden")).toBe("false");
    expect(focusSpy).toHaveBeenCalled();
  });

  test("triggers search when input has value", () => {
    const modal = document.createElement("div");
    modal.id = "global-search-modal";
    modal.classList.add("hidden");
    document.body.appendChild(modal);

    const input = document.createElement("input");
    input.id = "global-search-input";
    input.value = "test";
    modal.appendChild(input);

    const results = document.createElement("div");
    results.id = "global-search-results";
    modal.appendChild(results);

    openGlobalSearchModal();

    // Verify modal opened
    expect(modal.classList.contains("hidden")).toBe(false);

    // Verify search was triggered - results container should show "Searching..." message
    expect(results.innerHTML).toContain("Searching");
  });

  test("does nothing when elements missing", () => {
    expect(() => openGlobalSearchModal()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// closeGlobalSearchModal
// ---------------------------------------------------------------------------
describe("closeGlobalSearchModal", () => {
  test("closes modal", () => {
    const modal = document.createElement("div");
    modal.id = "global-search-modal";
    document.body.appendChild(modal);

    closeGlobalSearchModal();

    expect(modal.classList.contains("hidden")).toBe(true);
    expect(modal.getAttribute("aria-hidden")).toBe("true");
  });

  test("does nothing when modal missing", () => {
    expect(() => closeGlobalSearchModal()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// navigateToGlobalSearchResult
// ---------------------------------------------------------------------------
describe("navigateToGlobalSearchResult", () => {
  test("navigates to result", async () => {
    const { showTab } = await import("../../../mcpgateway/admin_ui/tabs.js");

    const button = document.createElement("button");
    button.dataset.entity = "servers";
    button.dataset.id = "s1";

    window.viewServer = vi.fn();

    navigateToGlobalSearchResult(button);

    expect(showTab).toHaveBeenCalledWith("catalog");
  });

  test("does nothing for invalid button", () => {
    expect(() => navigateToGlobalSearchResult(null)).not.toThrow();
  });

  test("does nothing when entity type missing", () => {
    const button = document.createElement("button");
    button.dataset.id = "s1";

    navigateToGlobalSearchResult(button);
  });

  test("does nothing when entity id missing", () => {
    const button = document.createElement("button");
    button.dataset.entity = "servers";

    navigateToGlobalSearchResult(button);
  });
});

// ---------------------------------------------------------------------------
// ensureNoResultsElement
// ---------------------------------------------------------------------------
describe("ensureNoResultsElement", () => {
  test("returns existing element", () => {
    const container = document.createElement("div");
    container.id = "test-container";
    document.body.appendChild(container);

    const msg = document.createElement("p");
    msg.id = "test-msg";
    const span = document.createElement("span");
    span.id = "test-span";
    msg.appendChild(span);
    document.body.appendChild(msg);

    const result = ensureNoResultsElement("test-container", "test-msg", "test-span", "item");
    expect(result.msg).toBe(msg);
    expect(result.span).toBe(span);
  });

  test("creates element when missing", () => {
    const container = document.createElement("div");
    container.id = "test-container";
    document.body.appendChild(container);

    const result = ensureNoResultsElement("test-container", "test-msg", "test-span", "item");
    expect(result.msg).toBeTruthy();
    expect(result.span).toBeTruthy();
    expect(result.msg.id).toBe("test-msg");
    expect(result.span.id).toBe("test-span");
  });

  test("returns null when container missing", () => {
    const result = ensureNoResultsElement("missing", "test-msg", "test-span", "item");
    expect(result.msg).toBeNull();
    expect(result.span).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// serverSideEditToolSearch
// ---------------------------------------------------------------------------
describe("serverSideEditToolSearch", () => {
  test("does nothing when container is missing", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await serverSideEditToolSearch("test");
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("not found")
    );
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// serverSideEditPromptsSearch
// ---------------------------------------------------------------------------
describe("serverSideEditPromptsSearch", () => {
  test("does nothing when container is missing", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await serverSideEditPromptsSearch("test");
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("not found")
    );
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// serverSideEditResourcesSearch
// ---------------------------------------------------------------------------
describe("serverSideEditResourcesSearch", () => {
  test("does nothing when container is missing", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await serverSideEditResourcesSearch("test");
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("not found")
    );
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// captureNonMemberSelections
// ---------------------------------------------------------------------------
describe("captureNonMemberSelections", () => {
  beforeEach(() => {
    AppState.nonMemberSelectionsCache = {};
  });

  test("does nothing when container is missing", () => {
    captureNonMemberSelections("team1");
    expect(AppState.nonMemberSelectionsCache["team1"]).toBeUndefined();
  });

  test("initializes cache entry for new teamId", () => {
    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";
    document.body.appendChild(container);

    captureNonMemberSelections("team1");

    expect(AppState.nonMemberSelectionsCache["team1"]).toBeDefined();
  });

  test("captures checked non-auto-check user with role into cache", () => {
    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";

    const item = document.createElement("div");
    item.className = "user-item";
    item.setAttribute("data-user-email", "user@test.com");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedUsers";
    cb.checked = true;

    const roleSelect = document.createElement("select");
    roleSelect.className = "role-select";
    const opt = document.createElement("option");
    opt.value = "owner";
    opt.selected = true;
    roleSelect.appendChild(opt);

    item.appendChild(cb);
    item.appendChild(roleSelect);
    container.appendChild(item);
    document.body.appendChild(container);

    captureNonMemberSelections("team1");

    expect(AppState.nonMemberSelectionsCache["team1"]["user@test.com"]).toBe("owner");
  });

  test("removes unchecked non-auto-check user from cache", () => {
    AppState.nonMemberSelectionsCache["team1"] = { "user@test.com": "member" };

    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";

    const item = document.createElement("div");
    item.className = "user-item";
    item.setAttribute("data-user-email", "user@test.com");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedUsers";
    cb.checked = false;

    item.appendChild(cb);
    container.appendChild(item);
    document.body.appendChild(container);

    captureNonMemberSelections("team1");

    expect(AppState.nonMemberSelectionsCache["team1"]["user@test.com"]).toBeUndefined();
  });

  test("ignores items with data-auto-check attribute", () => {
    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";

    const item = document.createElement("div");
    item.className = "user-item";
    item.setAttribute("data-user-email", "auto@test.com");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedUsers";
    cb.checked = true;
    cb.setAttribute("data-auto-check", "true");

    item.appendChild(cb);
    container.appendChild(item);
    document.body.appendChild(container);

    captureNonMemberSelections("team1");

    expect(AppState.nonMemberSelectionsCache["team1"]["auto@test.com"]).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// restoreNonMemberSelections
// ---------------------------------------------------------------------------
describe("restoreNonMemberSelections", () => {
  beforeEach(() => {
    AppState.nonMemberSelectionsCache = {};
  });

  test("does nothing when container is missing", () => {
    AppState.nonMemberSelectionsCache["team1"] = { "user@test.com": "member" };
    // should not throw
    restoreNonMemberSelections("team1");
  });

  test("does nothing when no cache entry for teamId", () => {
    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";
    document.body.appendChild(container);

    restoreNonMemberSelections("team1");
    // no cached-selection elements injected
    expect(container.querySelectorAll(".cached-selection").length).toBe(0);
  });

  test("restores checkbox and role for visible cached user", () => {
    AppState.nonMemberSelectionsCache["team1"] = { "user@test.com": "owner" };

    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";

    const item = document.createElement("div");
    item.className = "user-item";
    item.setAttribute("data-user-email", "user@test.com");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedUsers";
    cb.checked = false;

    const roleSelect = document.createElement("select");
    roleSelect.className = "role-select";
    const optMember = document.createElement("option");
    optMember.value = "member";
    const optOwner = document.createElement("option");
    optOwner.value = "owner";
    roleSelect.appendChild(optMember);
    roleSelect.appendChild(optOwner);

    item.appendChild(cb);
    item.appendChild(roleSelect);
    container.appendChild(item);
    document.body.appendChild(container);

    restoreNonMemberSelections("team1");

    expect(cb.checked).toBe(true);
    expect(roleSelect.value).toBe("owner");
  });

  test("removes stale cached-selection elements before re-injecting", () => {
    AppState.nonMemberSelectionsCache["team1"] = {};

    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";

    const stale = document.createElement("div");
    stale.className = "cached-selection hidden";
    container.appendChild(stale);
    document.body.appendChild(container);

    restoreNonMemberSelections("team1");

    expect(container.querySelectorAll(".cached-selection").length).toBe(0);
  });

  test("injects hidden cached-selection for email not visible in DOM", () => {
    AppState.nonMemberSelectionsCache["team1"] = { "ghost@test.com": "member" };

    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";
    document.body.appendChild(container);

    restoreNonMemberSelections("team1");

    const injected = container.querySelector(".cached-selection");
    expect(injected).toBeTruthy();
    expect(injected.querySelector('input[name="associatedUsers"]').value).toBe("ghost@test.com");
    expect(injected.querySelector('input[type="hidden"]').value).toBe("member");
  });
});

// ---------------------------------------------------------------------------
// captureMemberOverrides
// ---------------------------------------------------------------------------
describe("captureMemberOverrides", () => {
  beforeEach(() => {
    AppState.memberOverridesCache = {};
  });

  test("does nothing when container is missing", () => {
    captureMemberOverrides("team1");
    expect(AppState.memberOverridesCache["team1"]).toBeUndefined();
  });

  test("initializes cache entry for new teamId", () => {
    const container = document.createElement("div");
    container.id = "team-members-container-team1";
    document.body.appendChild(container);

    captureMemberOverrides("team1");

    expect(AppState.memberOverridesCache["team1"]).toBeDefined();
  });

  test("captures unchecked auto-check member as override", () => {
    const container = document.createElement("div");
    container.id = "team-members-container-team1";

    const item = document.createElement("div");
    item.className = "user-item";
    item.setAttribute("data-user-email", "member@test.com");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedUsers";
    cb.checked = false;
    cb.setAttribute("data-auto-check", "true");

    const roleSelect = document.createElement("select");
    roleSelect.className = "role-select";
    const opt = document.createElement("option");
    opt.value = "member";
    opt.selected = true;
    roleSelect.appendChild(opt);

    item.appendChild(cb);
    item.appendChild(roleSelect);
    container.appendChild(item);
    document.body.appendChild(container);

    captureMemberOverrides("team1");

    expect(AppState.memberOverridesCache["team1"]["member@test.com"]).toEqual({
      checked: false,
      role: "member",
    });
  });

  test("ignores items without data-auto-check", () => {
    const container = document.createElement("div");
    container.id = "team-members-container-team1";

    const item = document.createElement("div");
    item.className = "user-item";
    item.setAttribute("data-user-email", "plain@test.com");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedUsers";
    cb.checked = false;

    item.appendChild(cb);
    container.appendChild(item);
    document.body.appendChild(container);

    captureMemberOverrides("team1");

    expect(AppState.memberOverridesCache["team1"]["plain@test.com"]).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// restoreMemberOverrides
// ---------------------------------------------------------------------------
describe("restoreMemberOverrides", () => {
  beforeEach(() => {
    AppState.memberOverridesCache = {};
  });

  test("does nothing when container is missing", () => {
    AppState.memberOverridesCache["team1"] = { "member@test.com": { checked: false, role: "owner" } };
    restoreMemberOverrides("team1");
  });

  test("does nothing when no cache entry for teamId", () => {
    const container = document.createElement("div");
    container.id = "team-members-container-team1";
    document.body.appendChild(container);

    restoreMemberOverrides("team1");
  });

  test("restores checkbox state and role from cache", () => {
    AppState.memberOverridesCache["team1"] = {
      "member@test.com": { checked: false, role: "owner" },
    };

    const container = document.createElement("div");
    container.id = "team-members-container-team1";

    const item = document.createElement("div");
    item.className = "user-item";
    item.setAttribute("data-user-email", "member@test.com");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedUsers";
    cb.checked = true;

    const roleSelect = document.createElement("select");
    roleSelect.className = "role-select";
    const optMember = document.createElement("option");
    optMember.value = "member";
    const optOwner = document.createElement("option");
    optOwner.value = "owner";
    roleSelect.appendChild(optMember);
    roleSelect.appendChild(optOwner);
    roleSelect.value = "member";

    item.appendChild(cb);
    item.appendChild(roleSelect);
    container.appendChild(item);
    document.body.appendChild(container);

    restoreMemberOverrides("team1");

    expect(cb.checked).toBe(false);
    expect(roleSelect.value).toBe("owner");
  });

  test("skips items not present in cache", () => {
    AppState.memberOverridesCache["team1"] = {};

    const container = document.createElement("div");
    container.id = "team-members-container-team1";

    const item = document.createElement("div");
    item.className = "user-item";
    item.setAttribute("data-user-email", "other@test.com");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.name = "associatedUsers";
    cb.checked = true;

    item.appendChild(cb);
    container.appendChild(item);
    document.body.appendChild(container);

    restoreMemberOverrides("team1");

    expect(cb.checked).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// debouncedMemberSearch
// ---------------------------------------------------------------------------
describe("debouncedMemberSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    AppState.memberSearchTimers = {};
    window.ROOT_PATH = "";
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test("schedules serverSideMemberSearch after delay", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    fetchWithAuth.mockResolvedValue({ ok: true, text: () => Promise.resolve("<div>Members</div>") });

    const container = document.createElement("div");
    container.id = "team-members-container-team1";
    document.body.appendChild(container);

    debouncedMemberSearch("team1", "alice", 200);
    expect(fetchWithAuth).not.toHaveBeenCalled();

    await vi.runAllTimersAsync();

    expect(fetchWithAuth).toHaveBeenCalledTimes(1);
    expect(fetchWithAuth).toHaveBeenCalledWith(expect.stringContaining("search=alice"));
  });

  test("cancels previous pending timer for same teamId", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    fetchWithAuth.mockResolvedValue({ ok: true, text: () => Promise.resolve("<div>Members</div>") });

    const container = document.createElement("div");
    container.id = "team-members-container-team1";
    document.body.appendChild(container);

    debouncedMemberSearch("team1", "alice", 200);
    debouncedMemberSearch("team1", "bob", 200);

    await vi.runAllTimersAsync();

    expect(fetchWithAuth).toHaveBeenCalledTimes(1);
    expect(fetchWithAuth).toHaveBeenCalledWith(expect.stringContaining("search=bob"));
  });
});

// ---------------------------------------------------------------------------
// debouncedNonMemberSearch
// ---------------------------------------------------------------------------
describe("debouncedNonMemberSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    AppState.nonMemberSearchTimers = {};
    AppState.nonMemberSelectionsCache = {};
    window.ROOT_PATH = "";
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test("schedules serverSideNonMemberSearch after delay", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    fetchWithAuth.mockResolvedValue({ ok: true, text: () => Promise.resolve("<div>Non-members</div>") });

    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";
    document.body.appendChild(container);

    debouncedNonMemberSearch("team1", "alice", 200);
    expect(fetchWithAuth).not.toHaveBeenCalled();

    await vi.runAllTimersAsync();

    expect(fetchWithAuth).toHaveBeenCalledTimes(1);
    expect(fetchWithAuth).toHaveBeenCalledWith(expect.stringContaining("search=alice"));
  });

  test("cancels previous pending timer for same teamId", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    fetchWithAuth.mockResolvedValue({ ok: true, text: () => Promise.resolve("<div>Non-members</div>") });

    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";
    document.body.appendChild(container);

    debouncedNonMemberSearch("team1", "alice", 200);
    debouncedNonMemberSearch("team1", "bob", 200);

    await vi.runAllTimersAsync();

    expect(fetchWithAuth).toHaveBeenCalledTimes(1);
    expect(fetchWithAuth).toHaveBeenCalledWith(expect.stringContaining("search=bob"));
  });
});

// ---------------------------------------------------------------------------
// serverSideMemberSearch
// ---------------------------------------------------------------------------
describe("serverSideMemberSearch", () => {
  beforeEach(() => {
    AppState.memberOverridesCache = {};
    window.ROOT_PATH = "";
    window.htmx = { ajax: vi.fn(), process: vi.fn() };
  });

  test("does nothing when container is missing", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    await serverSideMemberSearch("team1", "alice");
    expect(fetchWithAuth).not.toHaveBeenCalled();
  });

  test("fetches with search param when searchTerm is provided", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    fetchWithAuth.mockResolvedValue({ ok: true, text: () => Promise.resolve("<div>Results</div>") });

    const container = document.createElement("div");
    container.id = "team-members-container-team1";
    document.body.appendChild(container);

    await serverSideMemberSearch("team1", "alice");

    expect(fetchWithAuth).toHaveBeenCalledWith(expect.stringContaining("search=alice"));
  });

  test("fetches without search param when searchTerm is empty", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    fetchWithAuth.mockResolvedValue({ ok: true, text: () => Promise.resolve("<div>All members</div>") });

    const container = document.createElement("div");
    container.id = "team-members-container-team1";
    document.body.appendChild(container);

    await serverSideMemberSearch("team1", "");

    const url = fetchWithAuth.mock.calls[0][0];
    expect(url).not.toContain("search=");
  });

  test("renders response HTML into container on success", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    fetchWithAuth.mockResolvedValue({ ok: true, text: () => Promise.resolve("<div>Member A</div>") });

    const container = document.createElement("div");
    container.id = "team-members-container-team1";
    document.body.appendChild(container);

    await serverSideMemberSearch("team1", "a");

    expect(container.innerHTML).toContain("Member A");
  });

  test("renders error message on fetch failure", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    fetchWithAuth.mockRejectedValue(new Error("Network error"));

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const container = document.createElement("div");
    container.id = "team-members-container-team1";
    document.body.appendChild(container);

    await serverSideMemberSearch("team1", "a");

    expect(container.innerHTML).toContain("Error searching members");
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// serverSideNonMemberSearch
// ---------------------------------------------------------------------------
describe("serverSideNonMemberSearch", () => {
  beforeEach(() => {
    AppState.nonMemberSelectionsCache = {};
    window.ROOT_PATH = "";
    window.htmx = { ajax: vi.fn(), process: vi.fn() };
  });

  test("does nothing when container is missing", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    await serverSideNonMemberSearch("team1", "alice");
    expect(fetchWithAuth).not.toHaveBeenCalled();
  });

  test("shows prompt message for empty search term", async () => {
    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";
    document.body.appendChild(container);

    await serverSideNonMemberSearch("team1", "");

    expect(container.innerHTML).toContain("Type at least 2 characters");
  });

  test("shows prompt message for single-character search term", async () => {
    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";
    document.body.appendChild(container);

    await serverSideNonMemberSearch("team1", "a");

    expect(container.innerHTML).toContain("Type at least 2 characters");
  });

  test("fetches with search param for valid search term", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    fetchWithAuth.mockResolvedValue({ ok: true, text: () => Promise.resolve("<div>User A</div>") });

    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";
    document.body.appendChild(container);

    await serverSideNonMemberSearch("team1", "al");

    expect(fetchWithAuth).toHaveBeenCalledWith(expect.stringContaining("search=al"));
  });

  test("renders response HTML into container on success", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    fetchWithAuth.mockResolvedValue({ ok: true, text: () => Promise.resolve("<div>User B</div>") });

    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";
    document.body.appendChild(container);

    await serverSideNonMemberSearch("team1", "al");

    expect(container.innerHTML).toContain("User B");
  });

  test("renders error message on fetch failure", async () => {
    const { fetchWithAuth } = await import("../../../mcpgateway/admin_ui/tokens.js");
    fetchWithAuth.mockRejectedValue(new Error("Network error"));

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const container = document.createElement("div");
    container.id = "team-non-members-container-team1";
    document.body.appendChild(container);

    await serverSideNonMemberSearch("team1", "al");

    expect(container.innerHTML).toContain("Error searching users");
    consoleSpy.mockRestore();
  });
});
