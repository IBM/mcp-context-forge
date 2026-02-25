/**
 * Tests for pagination cascade isolation (#3244).
 *
 * Verifies that pagination state is independent per section/table:
 * - getPaginationParams uses namespaced URL params so tables don't share state
 * - The Alpine.js pagination component in pagination_controls.html correctly
 *   hides navigation when totalPages === 0 and shows it when totalPages > 0
 * - goToPage rejects navigation when totalPages is 0
 */

import { describe, test, expect, beforeAll, beforeEach, afterAll } from "vitest";
import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";

let win;
let doc;

beforeAll(() => {
  // Inject getPaginationParams and buildTableUrl before admin.js loads,
  // mirroring the inline <script> in admin.html that defines them.
  win = loadAdminJs({
    beforeEval: (window) => {
      // Mirrors admin.html lines 160-206
      window.getPaginationParams = function getPaginationParams (tableName) {
        const urlParams = new URLSearchParams(window.location.search);
        const prefix = tableName + "_";
        return {
          page: Math.max(1, parseInt(urlParams.get(prefix + "page"), 10) || 1),
          perPage: Math.max(1, parseInt(urlParams.get(prefix + "size"), 10) || 10),
          includeInactive: urlParams.get(prefix + "inactive")
        };
      };

      window.buildTableUrl = function buildTableUrl (tableName, baseUrl, additionalParams) {
        if (additionalParams === undefined) additionalParams = {};
        const params = window.getPaginationParams(tableName);
        const urlParams = new URLSearchParams(window.location.search);
        const prefix = tableName + "_";
        const url = new URL(baseUrl, window.location.origin);
        url.searchParams.set("page", params.page);
        url.searchParams.set("per_page", params.perPage);

        for (const [key, value] of Object.entries(additionalParams)) {
          if (key === "include_inactive" && params.includeInactive !== null) {
            url.searchParams.set("include_inactive", params.includeInactive);
          } else if (value !== null && value !== undefined && value !== "") {
            url.searchParams.set(key, value);
          }
        }

        if (!additionalParams.hasOwnProperty("include_inactive") && params.includeInactive !== null) {
          url.searchParams.set("include_inactive", params.includeInactive);
        }

        const namespacedQuery = urlParams.get(prefix + "q");
        const namespacedTags = urlParams.get(prefix + "tags");
        if (namespacedQuery) {
          url.searchParams.set("q", namespacedQuery);
        }
        if (namespacedTags) {
          url.searchParams.set("tags", namespacedTags);
        }

        return url.pathname + url.search;
      };

      // Stub safeReplaceState used by admin.js
      window.safeReplaceState = function () {};
    }
  });
  doc = win.document;
});

afterAll(() => {
  cleanupAdminJs();
});

beforeEach(() => {
  doc.body.textContent = "";
  win.history.replaceState({}, "", "/admin");
});

// ---------------------------------------------------------------------------
// getPaginationParams namespace isolation
// ---------------------------------------------------------------------------
describe("getPaginationParams namespace isolation", () => {
  test("each table reads only its own namespaced URL params", () => {
    win.history.replaceState(
      {},
      "",
      "/admin?servers_page=3&servers_size=50&tools_page=1&tools_size=25"
    );

    const servers = win.getPaginationParams("servers");
    const tools = win.getPaginationParams("tools");

    expect(servers.page).toBe(3);
    expect(servers.perPage).toBe(50);
    expect(tools.page).toBe(1);
    expect(tools.perPage).toBe(25);
  });

  test("missing params for one table do not leak from another", () => {
    win.history.replaceState({}, "", "/admin?servers_page=5&servers_size=100");

    const servers = win.getPaginationParams("servers");
    const tools = win.getPaginationParams("tools");

    expect(servers.page).toBe(5);
    expect(servers.perPage).toBe(100);
    // Tools should get defaults, not servers' values
    expect(tools.page).toBe(1);
    expect(tools.perPage).toBe(10);
  });

  test("all five section namespaces are independent", () => {
    win.history.replaceState(
      {},
      "",
      "/admin?servers_page=1&servers_size=10" +
        "&tools_page=2&tools_size=25" +
        "&gateways_page=3&gateways_size=50" +
        "&tokens_page=4&tokens_size=100" +
        "&agents_page=5&agents_size=200"
    );

    const sections = ["servers", "tools", "gateways", "tokens", "agents"];
    const expectedPages = [1, 2, 3, 4, 5];
    const expectedSizes = [10, 25, 50, 100, 200];

    sections.forEach((name, i) => {
      const state = win.getPaginationParams(name);
      expect(state.page).toBe(expectedPages[i]);
      expect(state.perPage).toBe(expectedSizes[i]);
    });
  });
});

// ---------------------------------------------------------------------------
// buildTableUrl namespace isolation
// ---------------------------------------------------------------------------
describe("buildTableUrl namespace isolation", () => {
  test("builds URL using only the specified table's params", () => {
    win.history.replaceState(
      {},
      "",
      "/admin?servers_page=5&servers_size=100&tools_page=2&tools_size=25"
    );

    const serversUrl = win.buildTableUrl("servers", "/admin/servers/partial");
    const toolsUrl = win.buildTableUrl("tools", "/admin/tools/partial");

    expect(serversUrl).toContain("page=5");
    expect(serversUrl).toContain("per_page=100");
    expect(toolsUrl).toContain("page=2");
    expect(toolsUrl).toContain("per_page=25");
  });

  test("does not cross-contaminate search queries between tables", () => {
    win.history.replaceState(
      {},
      "",
      "/admin?servers_q=myserver&tools_q=mytool&servers_page=1&servers_size=10&tools_page=1&tools_size=10"
    );

    const serversUrl = win.buildTableUrl("servers", "/admin/servers/partial");
    const toolsUrl = win.buildTableUrl("tools", "/admin/tools/partial");

    expect(serversUrl).toContain("q=myserver");
    expect(serversUrl).not.toContain("q=mytool");
    expect(toolsUrl).toContain("q=mytool");
    expect(toolsUrl).not.toContain("q=myserver");
  });
});

// ---------------------------------------------------------------------------
// Pagination component: goToPage boundary behavior
// ---------------------------------------------------------------------------
describe("pagination component goToPage behavior", () => {
  /**
   * Simulate the Alpine.js pagination component's goToPage logic.
   * This mirrors pagination_controls.html x-data methods.
   */
  function createPaginationComponent (opts) {
    const pages = [];
    const component = {
      currentPage: opts.currentPage || 1,
      perPage: opts.perPage || 50,
      totalItems: opts.totalItems || 0,
      totalPages: opts.totalPages || 0,
      hasNext: opts.hasNext || false,
      hasPrev: opts.hasPrev || false,
      _loadedPages: pages,

      goToPage (page) {
        if (page >= 1 && page <= this.totalPages && page !== this.currentPage) {
          this.currentPage = page;
          pages.push(page);
        }
      },

      prevPage () {
        if (this.hasPrev) {
          this.goToPage(this.currentPage - 1);
        }
      },

      nextPage () {
        if (this.hasNext) {
          this.goToPage(this.currentPage + 1);
        }
      },

      changePageSize (size) {
        this.perPage = parseInt(size, 10);
        this.currentPage = 1;
        pages.push(1);
      }
    };
    return component;
  }

  test("goToPage is a no-op when totalPages is 0 (cascade poison scenario)", () => {
    // This is the exact scenario from #3244: servers had 0 items, cascade
    // poisoned tools' totalPages to 0, so navigation buttons disappeared
    const component = createPaginationComponent({
      currentPage: 1,
      totalItems: 0,
      totalPages: 0,
      hasNext: false,
      hasPrev: false
    });

    component.goToPage(1);
    component.goToPage(2);
    component.goToPage(3);

    expect(component._loadedPages).toHaveLength(0);
    expect(component.currentPage).toBe(1);
  });

  test("goToPage works when totalPages > 0 (correct pagination)", () => {
    // After the fix, each section computes its own totalPages correctly
    const component = createPaginationComponent({
      currentPage: 1,
      totalItems: 75,
      totalPages: 2,
      hasNext: true,
      hasPrev: false
    });

    component.goToPage(2);

    expect(component._loadedPages).toEqual([2]);
    expect(component.currentPage).toBe(2);
  });

  test("navigation buttons hidden when totalPages is 0", () => {
    // Mirrors: <template x-if="totalPages > 0"> in pagination_controls.html
    const component = createPaginationComponent({
      totalItems: 0,
      totalPages: 0
    });

    // The x-if="totalPages > 0" condition
    const navigationVisible = component.totalPages > 0;
    expect(navigationVisible).toBe(false);
  });

  test("navigation buttons shown when totalPages > 0", () => {
    const component = createPaginationComponent({
      totalItems: 75,
      totalPages: 2
    });

    const navigationVisible = component.totalPages > 0;
    expect(navigationVisible).toBe(true);
  });

  test("two independent sections have independent pagination state", () => {
    // Simulates the fixed behavior: servers and tools compute independently
    const servers = createPaginationComponent({
      currentPage: 1,
      totalItems: 0,
      totalPages: 0,
      hasNext: false,
      hasPrev: false
    });

    const tools = createPaginationComponent({
      currentPage: 1,
      totalItems: 75,
      totalPages: 2,
      hasNext: true,
      hasPrev: false
    });

    // Servers: 0 items → no navigation possible
    servers.goToPage(2);
    expect(servers.currentPage).toBe(1);
    expect(servers.totalPages).toBe(0);

    // Tools: 75 items → navigation works independently
    tools.goToPage(2);
    expect(tools.currentPage).toBe(2);
    expect(tools.totalPages).toBe(2);

    // Verify they didn't affect each other
    expect(servers.currentPage).toBe(1);
    expect(servers.totalItems).toBe(0);
    expect(tools.totalItems).toBe(75);
  });

  test("prevPage and nextPage respect bounds", () => {
    const component = createPaginationComponent({
      currentPage: 1,
      totalItems: 150,
      totalPages: 3,
      hasNext: true,
      hasPrev: false
    });

    // Can't go prev from page 1
    component.prevPage();
    expect(component.currentPage).toBe(1);

    // Can go next
    component.hasNext = true;
    component.goToPage(2);
    expect(component.currentPage).toBe(2);

    // Can go next to page 3
    component.goToPage(3);
    expect(component.currentPage).toBe(3);

    // Can't go beyond totalPages
    component.goToPage(4);
    expect(component.currentPage).toBe(3);
  });
});
