/**
 * Unit tests for pagination state management functions from teams.js.
 */

import { describe, test, expect, beforeEach } from "vitest";
import {
  getTeamsCurrentPaginationState,
  handleAdminTeamAction,
} from "../../mcpgateway/admin_ui/teams.js";

beforeEach(() => {
  document.body.textContent = "";
  // Reset URL to clean state
  window.history.replaceState({}, "", "/admin");
});

// ---------------------------------------------------------------------------
// getTeamsCurrentPaginationState
// ---------------------------------------------------------------------------
describe("getTeamsCurrentPaginationState", () => {
  test("returns default values when URL params are missing", () => {
    const state = getTeamsCurrentPaginationState();
    expect(state).toEqual({
      page: 1,
      perPage: 10,
    });
  });

  test("returns page from teams_page URL parameter", () => {
    window.history.replaceState({}, "", "/admin?teams_page=3&teams_size=10");
    const state = getTeamsCurrentPaginationState();
    expect(state.page).toBe(3);
    expect(state.perPage).toBe(10);
  });

  test("returns perPage from teams_size URL parameter", () => {
    window.history.replaceState({}, "", "/admin?teams_page=1&teams_size=25");
    const state = getTeamsCurrentPaginationState();
    expect(state.page).toBe(1);
    expect(state.perPage).toBe(25);
  });

  test("returns both page and perPage from URL parameters", () => {
    window.history.replaceState({}, "", "/admin?teams_page=5&teams_size=50");
    const state = getTeamsCurrentPaginationState();
    expect(state).toEqual({
      page: 5,
      perPage: 50,
    });
  });

  test("returns defaults when only teams_page is present", () => {
    window.history.replaceState({}, "", "/admin?teams_page=2");
    const state = getTeamsCurrentPaginationState();
    expect(state.page).toBe(2);
    expect(state.perPage).toBe(10);
  });

  test("returns defaults when only teams_size is present", () => {
    window.history.replaceState({}, "", "/admin?teams_size=20");
    const state = getTeamsCurrentPaginationState();
    expect(state.page).toBe(1);
    expect(state.perPage).toBe(20);
  });

  test("ignores other URL parameters", () => {
    window.history.replaceState(
      {},
      "",
      "/admin?teams_page=4&teams_size=15&other=value&foo=bar"
    );
    const state = getTeamsCurrentPaginationState();
    expect(state).toEqual({
      page: 4,
      perPage: 15,
    });
  });

  test("handles URL with hash fragment", () => {
    window.history.replaceState(
      {},
      "",
      "/admin?teams_page=2&teams_size=20#teams"
    );
    const state = getTeamsCurrentPaginationState();
    expect(state).toEqual({
      page: 2,
      perPage: 20,
    });
  });

  test("handles empty string values in URL params", () => {
    window.history.replaceState({}, "", "/admin?teams_page=&teams_size=");
    const state = getTeamsCurrentPaginationState();
    expect(state).toEqual({
      page: 1,
      perPage: 10,
    });
  });

  test("handles non-numeric values in URL params", () => {
    window.history.replaceState(
      {},
      "",
      "/admin?teams_page=abc&teams_size=xyz"
    );
    const state = getTeamsCurrentPaginationState();
    expect(state).toEqual({
      page: 1,
      perPage: 10,
    });
  });

  test("clamps negative page to 1", () => {
    window.history.replaceState({}, "", "/admin?teams_page=-1&teams_size=10");
    const state = getTeamsCurrentPaginationState();
    expect(state.page).toBe(1);
  });

  test("clamps negative perPage to 1", () => {
    window.history.replaceState({}, "", "/admin?teams_page=1&teams_size=-5");
    const state = getTeamsCurrentPaginationState();
    expect(state.perPage).toBe(1);
  });

  test("clamps zero page to 1", () => {
    window.history.replaceState({}, "", "/admin?teams_page=0&teams_size=10");
    const state = getTeamsCurrentPaginationState();
    expect(state.page).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Integration: handleAdminTeamAction with pagination preservation
// ---------------------------------------------------------------------------
describe("handleAdminTeamAction pagination preservation", () => {
  let lastHtmxUrl;

  beforeEach(() => {
    lastHtmxUrl = undefined;

    // Set up DOM elements needed for team refresh
    const unifiedList = document.createElement("div");
    unifiedList.id = "unified-teams-list";
    document.body.appendChild(unifiedList);

    const searchInput = document.createElement("input");
    searchInput.id = "team-search";
    searchInput.value = "";
    document.body.appendChild(searchInput);

    // Mock htmx.ajax
    window.htmx = {
      ajax: (method, url, options) => {
        lastHtmxUrl = url;
        return Promise.resolve();
      },
    };
  });

  test("preserves pagination state when refreshing teams list", async () => {
    window.history.replaceState(
      {},
      "",
      "/admin?teams_page=3&teams_size=25#teams"
    );

    const event = new window.CustomEvent("adminTeamAction", {
      detail: {
        refreshUnifiedTeamsList: true,
        delayMs: 0,
      },
    });

    handleAdminTeamAction(event);

    // Wait for setTimeout to complete
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(lastHtmxUrl).toBeDefined();
    expect(lastHtmxUrl).toContain("page=3");
    expect(lastHtmxUrl).toContain("per_page=25");
  });

  test("uses default pagination when URL params are missing", async () => {
    window.history.replaceState({}, "", "/admin#teams");

    const event = new window.CustomEvent("adminTeamAction", {
      detail: {
        refreshUnifiedTeamsList: true,
        delayMs: 0,
      },
    });

    handleAdminTeamAction(event);

    // Wait for setTimeout to complete
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(lastHtmxUrl).toBeDefined();
    expect(lastHtmxUrl).toContain("page=1");
    expect(lastHtmxUrl).toContain("per_page=10");
  });

  test("preserves search query along with pagination", async () => {
    window.history.replaceState(
      {},
      "",
      "/admin?teams_page=2&teams_size=20#teams"
    );
    const searchInput = document.getElementById("team-search");
    searchInput.value = "test team query";

    const event = new window.CustomEvent("adminTeamAction", {
      detail: {
        refreshUnifiedTeamsList: true,
        delayMs: 0,
      },
    });

    handleAdminTeamAction(event);

    // Wait for setTimeout to complete
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(lastHtmxUrl).toBeDefined();
    expect(lastHtmxUrl).toContain("page=2");
    expect(lastHtmxUrl).toContain("per_page=20");
    // Accept both URL encodings for space: %20 or +
    expect(lastHtmxUrl).toMatch(/q=test(\+|%20)team(\+|%20)query/);
  });

  test("uses page 1 after search resets pagination, not stale URL state", async () => {
    // Simulate: user was on page 3, then searched (which resets to page 1),
    // then triggers a CRUD action. The CRUD refresh should use page 1, not
    // the stale teams_page=3 from the URL.
    window.history.replaceState(
      {},
      "",
      "/admin?teams_page=3&teams_size=25#teams"
    );

    // Simulate what performTeamSearch does: sync URL to page 1
    const currentUrl = new URL(window.location.href);
    const urlParams = new URLSearchParams(currentUrl.searchParams);
    urlParams.set("teams_page", "1");
    const newUrl =
      currentUrl.pathname + "?" + urlParams.toString() + currentUrl.hash;
    window.history.replaceState({}, "", newUrl);

    // Verify URL was synced to page 1
    const urlAfterSearch = new URL(window.location.href);
    expect(urlAfterSearch.searchParams.get("teams_page")).toBe("1");

    // Now trigger a CRUD action
    const event = new window.CustomEvent("adminTeamAction", {
      detail: {
        refreshUnifiedTeamsList: true,
        delayMs: 0,
      },
    });

    handleAdminTeamAction(event);

    await new Promise((resolve) => setTimeout(resolve, 10));

    // CRUD refresh should use page 1, not stale page 3
    expect(lastHtmxUrl).toBeDefined();
    expect(lastHtmxUrl).toContain("page=1");
    expect(lastHtmxUrl).not.toContain("page=3");
  });
});
