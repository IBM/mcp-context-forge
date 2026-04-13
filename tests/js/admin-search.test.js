/**
 * Unit tests for unified admin search (panel search + global search).
 *
 * Functions are imported directly from their source modules.
 */

import { describe, test, expect, beforeEach, vi } from "vitest";

import {
  clearSearch,
  openGlobalSearchModal,
  closeGlobalSearchModal,
  navigateToGlobalSearchResult,
} from "../../mcpgateway/admin_ui/search.js";
import { showUserEditModal } from "../../mcpgateway/admin_ui/users.js";
import {
  filterServerTable,
  filterToolsTable,
} from "../../mcpgateway/admin_ui/filters.js";
import { showTab } from "../../mcpgateway/admin_ui/tabs.js";
import {
  fetchWithAuth,
  performTokenSearch,
} from "../../mcpgateway/admin_ui/tokens.js";

// ---------------------------------------------------------------------------
// Mock heavy / circular dependency chains before importing modules under test.
// ---------------------------------------------------------------------------

vi.mock("../../mcpgateway/admin_ui/filters.js", () => ({
  filterA2AAgentsTable: vi.fn(),
  filterGatewaysTable: vi.fn(),
  filterPromptsTable: vi.fn(),
  filterResourcesTable: vi.fn(),
  filterServerTable: vi.fn(),
  filterToolsTable: vi.fn(),
  toggleViewPublic: vi.fn(),
}));

vi.mock("../../mcpgateway/admin_ui/tabs.js", () => ({
  showTab: vi.fn(),
  getUiHiddenSections: vi.fn(() => new Set()),
  ADMIN_ONLY_TABS: new Set(),
}));

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

vi.mock("../../mcpgateway/admin_ui/teams.js", () => ({
  dedupeSelectorItems: vi.fn(),
  extractTeamId: vi.fn(),
  handleAdminTeamAction: vi.fn(),
  initializeAddMembersForms: vi.fn(),
  initializePasswordValidation: vi.fn(),
  updateAddMembersCount: vi.fn(),
  approveJoinRequest: vi.fn(),
  filterByRelationship: vi.fn(),
  filterTeams: vi.fn(),
  hideTeamEditModal: vi.fn(),
  leaveTeam: vi.fn(),
  rejectJoinRequest: vi.fn(),
  requestToJoinTeam: vi.fn(),
  serverSideTeamSearch: vi.fn(),
  updateDefaultVisibility: vi.fn(),
  validatePasswordMatch: vi.fn(),
  validatePasswordRequirements: vi.fn(),
}));

beforeEach(() => {
  document.body.innerHTML = "";
  vi.clearAllMocks();
  delete window.ROOT_PATH;
  delete window.htmx;
});

// ---------------------------------------------------------------------------
// clearSearch
// ---------------------------------------------------------------------------
describe("clearSearch", () => {
  test("clears search and tag inputs for panel entity", () => {
    const searchInput = document.createElement("input");
    searchInput.id = "tools-search-input";
    searchInput.value = "some query";
    document.body.appendChild(searchInput);

    const tagInput = document.createElement("input");
    tagInput.id = "tools-tag-filter";
    tagInput.value = "prod,staging";
    document.body.appendChild(tagInput);

    const table = document.createElement("div");
    table.id = "tools-table";
    document.body.appendChild(table);

    clearSearch("tools");

    expect(searchInput.value).toBe("");
    expect(tagInput.value).toBe("");
  });

  test("does not throw for unknown entity type", () => {
    expect(() => clearSearch("nonexistent")).not.toThrow();
  });

  test("handles tokens entity (not in panel search config)", () => {
    const searchInput = document.createElement("input");
    searchInput.id = "tokens-search-input";
    searchInput.value = "my-token";
    document.body.appendChild(searchInput);

    clearSearch("tokens");

    expect(searchInput.value).toBe("");
    expect(performTokenSearch).toHaveBeenCalledWith("");
  });

  test("calls legacy filter function to immediately clear rows for panel entities", () => {
    const searchInput = document.createElement("input");
    searchInput.id = "tools-search-input";
    document.body.appendChild(searchInput);

    const table = document.createElement("div");
    table.id = "tools-table";
    document.body.appendChild(table);

    clearSearch("tools");

    expect(filterToolsTable).toHaveBeenCalledWith("");
  });
});

// ---------------------------------------------------------------------------
// Global search modal
// ---------------------------------------------------------------------------
describe("Global search modal", () => {
  function setupSearchModal() {
    const modal = document.createElement("div");
    modal.id = "global-search-modal";
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    document.body.appendChild(modal);

    const input = document.createElement("input");
    input.id = "global-search-input";
    input.type = "text";
    modal.appendChild(input);

    const results = document.createElement("div");
    results.id = "global-search-results";
    modal.appendChild(results);

    return { modal, input, results };
  }

  test("openGlobalSearchModal shows modal", () => {
    const { modal } = setupSearchModal();
    openGlobalSearchModal();
    expect(modal.classList.contains("hidden")).toBe(false);
    expect(modal.getAttribute("aria-hidden")).toBe("false");
  });

  test("closeGlobalSearchModal hides modal", () => {
    const { modal } = setupSearchModal();
    modal.classList.remove("hidden");
    closeGlobalSearchModal();
    expect(modal.classList.contains("hidden")).toBe(true);
    expect(modal.getAttribute("aria-hidden")).toBe("true");
  });

  test("openGlobalSearchModal is idempotent", () => {
    const { modal } = setupSearchModal();
    openGlobalSearchModal();
    openGlobalSearchModal();
    expect(modal.classList.contains("hidden")).toBe(false);
  });

  test("closeGlobalSearchModal is idempotent when already hidden", () => {
    const { modal } = setupSearchModal();
    closeGlobalSearchModal();
    expect(modal.classList.contains("hidden")).toBe(true);
  });

  test("openGlobalSearchModal renders placeholder in results container", () => {
    const { results } = setupSearchModal();
    openGlobalSearchModal();
    expect(results.textContent).toContain("Start typing to search");
  });

  test("does nothing when modal element is missing", () => {
    expect(() => openGlobalSearchModal()).not.toThrow();
    expect(() => closeGlobalSearchModal()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// navigateToGlobalSearchResult
// ---------------------------------------------------------------------------
describe("navigateToGlobalSearchResult", () => {
  test("does nothing for null button", () => {
    expect(() => navigateToGlobalSearchResult(null)).not.toThrow();
  });

  test("does nothing for button without entity data", () => {
    const btn = document.createElement("button");
    expect(() => navigateToGlobalSearchResult(btn)).not.toThrow();
  });

  test("closes modal when navigating to result", () => {
    const modal = document.createElement("div");
    modal.id = "global-search-modal";
    document.body.appendChild(modal);

    const btn = document.createElement("button");
    btn.dataset.entity = "tools";
    btn.dataset.id = "tool-1";
    document.body.appendChild(btn);

    navigateToGlobalSearchResult(btn);

    expect(modal.classList.contains("hidden")).toBe(true);
    expect(showTab).toHaveBeenCalledWith("tools");
  });

  test("does nothing for unknown entity type", () => {
    const modal = document.createElement("div");
    modal.id = "global-search-modal";
    document.body.appendChild(modal);

    const btn = document.createElement("button");
    btn.dataset.entity = "unknown_entity_xyzzy";
    btn.dataset.id = "123";
    document.body.appendChild(btn);

    // Should close modal but not throw
    expect(() => navigateToGlobalSearchResult(btn)).not.toThrow();
    expect(modal.classList.contains("hidden")).toBe(true);
  });

  test("routes users results to users tab and invokes user modal loader", () => {
    const modal = document.createElement("div");
    modal.id = "global-search-modal";
    document.body.appendChild(modal);

    window.showUserEditModal = vi.fn();

    const btn = document.createElement("button");
    btn.dataset.entity = "users";
    btn.dataset.id = "user@example.com";
    document.body.appendChild(btn);

    vi.useFakeTimers();
    try {
      navigateToGlobalSearchResult(btn);
      vi.runAllTimers();
    } finally {
      vi.useRealTimers();
    }

    expect(showTab).toHaveBeenCalledWith("users");
    expect(window.showUserEditModal).toHaveBeenCalledWith("user@example.com");
    expect(modal.classList.contains("hidden")).toBe(true);
    delete window.showUserEditModal;
  });

  test("routes teams results to teams tab and invokes team modal loader", () => {
    const modal = document.createElement("div");
    modal.id = "global-search-modal";
    document.body.appendChild(modal);

    window.showTeamEditModal = vi.fn();

    const btn = document.createElement("button");
    btn.dataset.entity = "teams";
    btn.dataset.id = "team-123";
    document.body.appendChild(btn);

    vi.useFakeTimers();
    try {
      navigateToGlobalSearchResult(btn);
      vi.runAllTimers();
    } finally {
      vi.useRealTimers();
    }

    expect(showTab).toHaveBeenCalledWith("teams");
    expect(window.showTeamEditModal).toHaveBeenCalledWith("team-123");
    expect(modal.classList.contains("hidden")).toBe(true);
    delete window.showTeamEditModal;
  });
});

// ---------------------------------------------------------------------------
// showUserEditModal
// ---------------------------------------------------------------------------
describe("showUserEditModal", () => {
  test("loads user edit form content via authenticated fetch fallback", async () => {
    const modal = document.createElement("div");
    modal.id = "user-edit-modal";
    modal.classList.add("hidden");
    modal.style.display = "none";
    document.body.appendChild(modal);

    const content = document.createElement("div");
    content.id = "user-edit-modal-content";
    modal.appendChild(content);

    window.ROOT_PATH = "";
    window.htmx = null;
    fetchWithAuth.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      text: async () => '<div id="loaded-user-form">Loaded user form</div>',
    });

    await showUserEditModal("user@example.com");

    expect(fetchWithAuth).toHaveBeenCalledWith(
      "/admin/users/user%40example.com/edit",
      { method: "GET" }
    );
    expect(content.innerHTML).toContain("loaded-user-form");
    expect(modal.classList.contains("hidden")).toBe(false);
    expect(modal.style.display).toBe("block");
  });

  test("prefers HTMX loader when available", async () => {
    const modal = document.createElement("div");
    modal.id = "user-edit-modal";
    modal.classList.add("hidden");
    document.body.appendChild(modal);

    const content = document.createElement("div");
    content.id = "user-edit-modal-content";
    modal.appendChild(content);

    window.ROOT_PATH = "";
    window.htmx = {
      ajax: vi.fn().mockResolvedValue(undefined),
    };

    await showUserEditModal("user@example.com");

    expect(window.htmx.ajax).toHaveBeenCalledWith(
      "GET",
      "/admin/users/user%40example.com/edit",
      {
        target: "#user-edit-modal-content",
        swap: "innerHTML",
      }
    );
    expect(fetchWithAuth).not.toHaveBeenCalled();
    expect(modal.classList.contains("hidden")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Filter functions
// ---------------------------------------------------------------------------
describe("filterServerTable", () => {
  test("is a function", () => {
    expect(typeof filterServerTable).toBe("function");
  });
});
