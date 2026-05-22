/**
 * Unit tests for pagination.js module
 * Tests: paginationData
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { paginationData } from "../../../mcpgateway/admin_ui/pagination.js";

// Mock AppState
vi.mock("../../../mcpgateway/admin_ui/appState.js", () => ({
  AppState: {
    paginationQuerySetters: {},
  },
}));

// Mock security module
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  safeReplaceState: vi.fn(),
}));

describe("paginationData", () => {
  let component;
  let mockElement;

  beforeEach(() => {
    // Create mock element with dataset
    mockElement = {
      dataset: {
        currentPage: "1",
        perPage: "10",
        totalItems: "100",
        totalPages: "10",
        hasNext: "true",
        hasPrev: "false",
        hxTarget: "#tools-table",
        hxSwap: "innerHTML",
        tableName: "tools",
        baseUrl: "/admin/api/tools",
        hxIndicator: "#loading",
      },
    };

    // Mock window.htmx
    window.htmx = {
      ajax: vi.fn(),
    };

    // Mock document.querySelector
    global.document.querySelector = vi.fn((selector) => {
      if (selector === "#show-inactive-tools") {
        return { checked: false };
      }
      // Return a generic scrollable element for any other selector so that
      // loadPage() doesn't bail out early for non-#tools-table targets.
      return { closest: vi.fn(() => null), scrollIntoView: vi.fn(), addEventListener: vi.fn() };
    });

    global.document.getElementById = vi.fn((id) => {
      if (id === "show-inactive-tools") {
        return { checked: false };
      }
      return null;
    });

    // Mock window.location
    delete window.location;
    window.location = {
      href: "http://localhost:3000/admin",
      origin: "http://localhost:3000",
      pathname: "/admin",
      search: "",
      hash: "#tools",
    };

    component = paginationData();
    component.$el = mockElement;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  test("initializes with default values", () => {
    expect(component.currentPage).toBe(1);
    expect(component.perPage).toBe(10);
    expect(component.totalItems).toBe(0);
    expect(component.totalPages).toBe(0);
    expect(component.hasNext).toBe(false);
    expect(component.hasPrev).toBe(false);
  });

  test("init() reads values from dataset", () => {
    component.init();

    expect(component.currentPage).toBe(1);
    expect(component.perPage).toBe(10);
    expect(component.totalItems).toBe(100);
    expect(component.totalPages).toBe(10);
    expect(component.hasNext).toBe(true);
    expect(component.hasPrev).toBe(false);
    expect(component.targetSelector).toBe("#tools-table");
    expect(component.swapStyle).toBe("innerHTML");
    expect(component.tableName).toBe("tools");
    expect(component.baseUrl).toBe("/admin/api/tools");
  });

  test("init() honours namespaced URL param for page size", () => {
    window.location.search = "?tools_size=50";
    component.init();

    expect(component.perPage).toBe(50);
  });

  test("init() ignores invalid page sizes from URL", () => {
    window.location.search = "?tools_size=999";
    component.init();

    expect(component.perPage).toBe(10); // Falls back to dataset value
  });

  test("goToPage() changes page and calls loadPage", () => {
    component.init();
    component.loadPage = vi.fn();

    component.goToPage(3);

    expect(component.currentPage).toBe(3);
    expect(component.loadPage).toHaveBeenCalledWith(3);
  });

  test("goToPage() does not navigate to invalid pages", () => {
    component.init();
    component.loadPage = vi.fn();

    component.goToPage(0);
    expect(component.loadPage).not.toHaveBeenCalled();

    component.goToPage(11);
    expect(component.loadPage).not.toHaveBeenCalled();
  });

  test("goToPage() does not navigate to current page", () => {
    component.init();
    component.loadPage = vi.fn();

    component.goToPage(1);
    expect(component.loadPage).not.toHaveBeenCalled();
  });

  test("prevPage() navigates to previous page when hasPrev is true", () => {
    component.init();
    component.currentPage = 3;
    component.hasPrev = true;
    component.loadPage = vi.fn();

    component.prevPage();

    expect(component.currentPage).toBe(2);
    expect(component.loadPage).toHaveBeenCalledWith(2);
  });

  test("prevPage() does nothing when hasPrev is false", () => {
    component.init();
    component.hasPrev = false;
    component.loadPage = vi.fn();

    component.prevPage();

    expect(component.loadPage).not.toHaveBeenCalled();
  });

  test("nextPage() navigates to next page when hasNext is true", () => {
    component.init();
    component.currentPage = 1;
    component.hasNext = true;
    component.totalPages = 10;
    component.loadPage = vi.fn();

    component.nextPage();

    expect(component.currentPage).toBe(2);
    expect(component.loadPage).toHaveBeenCalledWith(2);
  });

  test("nextPage() does nothing when hasNext is false", () => {
    component.init();
    component.hasNext = false;
    component.loadPage = vi.fn();

    component.nextPage();

    expect(component.loadPage).not.toHaveBeenCalled();
  });

  test("changePageSize() updates perPage and resets to page 1", () => {
    component.init();
    component.currentPage = 5;
    component.loadPage = vi.fn();

    component.changePageSize(25);

    expect(component.perPage).toBe(25);
    expect(component.currentPage).toBe(1);
    expect(component.loadPage).toHaveBeenCalledWith(1);
  });

  test("updateBrowserUrl() does nothing when tableName is empty", async () => {
    const { safeReplaceState } = await import("../../../mcpgateway/admin_ui/security.js");
    component.init();
    component.tableName = "";

    component.updateBrowserUrl(2, true);

    expect(safeReplaceState).not.toHaveBeenCalled();
  });

  test("updateBrowserUrl() updates URL with namespaced params", async () => {
    const { safeReplaceState } = await import("../../../mcpgateway/admin_ui/security.js");
    component.init();

    component.updateBrowserUrl(3, true);

    expect(safeReplaceState).toHaveBeenCalledWith(
      {},
      "",
      expect.stringContaining("tools_page=3")
    );
    expect(safeReplaceState).toHaveBeenCalledWith(
      {},
      "",
      expect.stringContaining("tools_size=10")
    );
    expect(safeReplaceState).toHaveBeenCalledWith(
      {},
      "",
      expect.stringContaining("tools_inactive=true")
    );
  });

  test("loadPage() prevents concurrent requests", () => {
    component.init();
    component._loading = true;

    component.loadPage(2);

    expect(window.htmx.ajax).not.toHaveBeenCalled();
  });

  test("loadPage() bails out if target element is missing", () => {
    component.init();
    global.document.querySelector = vi.fn(() => null);

    component.loadPage(2);

    expect(window.htmx.ajax).not.toHaveBeenCalled();
  });

  test("loadPage() calls htmx.ajax with correct parameters", () => {
    component.init();

    component.loadPage(2);

    expect(window.htmx.ajax).toHaveBeenCalledWith(
      "GET",
      expect.stringContaining("/admin/api/tools"),
      expect.objectContaining({
        target: "#tools-table",
        swap: "innerHTML",
        indicator: "#loading",
      })
    );
  });

  test("loadPage() includes page and per_page in URL", () => {
    component.init();

    component.loadPage(3);

    const callArgs = window.htmx.ajax.mock.calls[0];
    const url = callArgs[1];
    expect(url).toContain("page=3");
    expect(url).toContain("per_page=10");
  });

  test("loadPage() includes include_inactive when checkbox is checked", () => {
    component.init();
    global.document.getElementById = vi.fn(() => ({ checked: true }));

    component.loadPage(1);

    const callArgs = window.htmx.ajax.mock.calls[0];
    const url = callArgs[1];
    expect(url).toContain("include_inactive=true");
  });

  test("loadPage() includes team_id from current URL", () => {
    component.init();
    window.location.search = "?team_id=team-123";

    component.loadPage(1);

    const callArgs = window.htmx.ajax.mock.calls[0];
    const url = callArgs[1];
    expect(url).toContain("team_id=team-123");
  });

  test("loadPage() applies extra query params from AppState", async () => {
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.paginationQuerySetters.tools = (url) => {
      url.searchParams.set("custom_param", "value");
    };
    component.init();

    component.loadPage(1);

    const callArgs = window.htmx.ajax.mock.calls[0];
    const url = callArgs[1];
    expect(url).toContain("custom_param=value");
  });

  test("loadPage() scrolls target into view", () => {
    const mockScrollIntoView = vi.fn();
    const mockElement = {
      closest: vi.fn(() => ({ scrollIntoView: mockScrollIntoView })),
      scrollIntoView: vi.fn(),
      addEventListener: vi.fn(),
    };
    global.document.querySelector = vi.fn(() => mockElement);
    component.init();

    component.loadPage(1);

    expect(mockScrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "start",
    });
  });

  test("loadPage() scrolls element directly if no panel found", () => {
    const mockScrollIntoView = vi.fn();
    const mockElement = {
      closest: vi.fn(() => null),
      scrollIntoView: mockScrollIntoView,
      addEventListener: vi.fn(),
    };
    global.document.querySelector = vi.fn(() => mockElement);
    component.init();

    component.loadPage(1);

    expect(mockScrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "start",
    });
  });

  test("resolves checkbox ID for servers-table", () => {
    mockElement.dataset.hxTarget = "#servers-table";
    mockElement.dataset.tableName = "servers";
    component.init();

    const mockCheckbox = { checked: true };
    global.document.getElementById = vi.fn((id) => {
      if (id === "show-inactive-servers") return mockCheckbox;
      return null;
    });

    component.loadPage(1);

    expect(global.document.getElementById).toHaveBeenCalledWith("show-inactive-servers");
  });

  test("resolves checkbox ID for agents to a2a-agents", () => {
    mockElement.dataset.hxTarget = "#agents-table";
    mockElement.dataset.tableName = "agents";
    component.init();

    const mockCheckbox = { checked: false };
    global.document.getElementById = vi.fn((id) => {
      if (id === "show-inactive-a2a-agents") return mockCheckbox;
      return null;
    });

    component.loadPage(1);

    expect(global.document.getElementById).toHaveBeenCalledWith("show-inactive-a2a-agents");
  });

  test("handles table-body suffix in target selector", () => {
    mockElement.dataset.hxTarget = "#tools-table-body";
    component.init();

    const mockCheckbox = { checked: true };
    global.document.getElementById = vi.fn((id) => {
      if (id === "show-inactive-tools") return mockCheckbox;
      return null;
    });

    component.loadPage(1);

    expect(global.document.getElementById).toHaveBeenCalledWith("show-inactive-tools");
  });

  test("handles list-container suffix in target selector", () => {
    mockElement.dataset.hxTarget = "#resources-list-container";
    mockElement.dataset.tableName = "resources";
    component.init();

    const mockCheckbox = { checked: false };
    global.document.getElementById = vi.fn((id) => {
      if (id === "show-inactive-resources") return mockCheckbox;
      return null;
    });

    component.loadPage(1);

    expect(global.document.getElementById).toHaveBeenCalledWith("show-inactive-resources");
  });
});

// ---------------------------------------------------------------------------
// data-extra-params handling
//
// pagination_controls.html serialises the backend's query_params dict into the
// `data-extra-params` JSON attribute on the component's root element. The JS
// must decode it in init() and apply each k/v to the pagination URL in
// loadPage(), so search/tag/gateway filters survive pagination clicks.
// ---------------------------------------------------------------------------
describe("paginationData data-extra-params handling", () => {
  let component;
  let mockElement;

  function makeElement(extra) {
    return {
      dataset: {
        currentPage: "1",
        perPage: "10",
        totalItems: "100",
        totalPages: "10",
        hasNext: "true",
        hasPrev: "false",
        hxTarget: "#tools-table",
        hxSwap: "innerHTML",
        tableName: "tools",
        baseUrl: "/admin/tools/partial",
        hxIndicator: "#tools-loading",
        ...(extra ? { extraParams: extra } : {}),
      },
    };
  }

  beforeEach(async () => {
    // Reset programmatic setters between tests so the appState path doesn't
    // leak state across describe blocks.
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.paginationQuerySetters = {};

    window.htmx = { ajax: vi.fn() };
    global.document.querySelector = vi.fn(() => ({
      closest: vi.fn(() => null),
      scrollIntoView: vi.fn(),
      addEventListener: vi.fn(),
    }));
    global.document.getElementById = vi.fn(() => null);
    delete window.location;
    window.location = {
      href: "http://localhost:3000/admin",
      origin: "http://localhost:3000",
      pathname: "/admin",
      search: "",
      hash: "#tools",
    };
    component = paginationData();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  test("init() decodes JSON data-extra-params into extraParams", () => {
    mockElement = makeElement(JSON.stringify({ q: "rest", gateway_id: "42" }));
    component.$el = mockElement;
    component.init();
    expect(component.extraParams).toEqual({ q: "rest", gateway_id: "42" });
  });

  test("init() defaults to empty object when data-extra-params missing", () => {
    mockElement = makeElement();
    component.$el = mockElement;
    component.init();
    expect(component.extraParams).toEqual({});
  });

  test("init() falls back to {} on malformed JSON without throwing", () => {
    mockElement = makeElement("{not json");
    component.$el = mockElement;
    expect(() => component.init()).not.toThrow();
    expect(component.extraParams).toEqual({});
  });

  test("init() rejects array payloads (must be plain object)", () => {
    mockElement = makeElement(JSON.stringify(["a", "b"]));
    component.$el = mockElement;
    component.init();
    expect(component.extraParams).toEqual({});
  });

  test("loadPage() forwards search term `q` from extraParams (Bug 1 fix)", () => {
    mockElement = makeElement(JSON.stringify({ q: "auth-tool" }));
    component.$el = mockElement;
    component.init();

    component.loadPage(2);

    const url = window.htmx.ajax.mock.calls[0][1];
    expect(url).toContain("q=auth-tool");
    expect(url).toContain("page=2");
  });

  test("loadPage() forwards tags and gateway_id from extraParams", () => {
    mockElement = makeElement(
      JSON.stringify({ tags: "fast,trusted", gateway_id: "g-7" })
    );
    component.$el = mockElement;
    component.init();

    component.loadPage(1);

    const url = window.htmx.ajax.mock.calls[0][1];
    expect(url).toContain("tags=fast%2Ctrusted");
    expect(url).toContain("gateway_id=g-7");
  });

  test("loadPage() does NOT forward include_inactive from extraParams (checkbox owns it)", () => {
    // Backend echoes include_inactive into query_params; the checkbox path
    // must remain authoritative so the user's UI toggle wins.
    mockElement = makeElement(
      JSON.stringify({ q: "x", include_inactive: "true" })
    );
    component.$el = mockElement;
    component.init();
    // No matching checkbox means include_inactive is omitted entirely.
    global.document.getElementById = vi.fn(() => null);

    component.loadPage(1);

    const url = new URL(window.htmx.ajax.mock.calls[0][1], "http://localhost");
    expect(url.searchParams.get("q")).toBe("x");
    expect(url.searchParams.has("include_inactive")).toBe(false);
  });

  test("loadPage() skips null/undefined values from extraParams", () => {
    mockElement = makeElement(
      JSON.stringify({ q: null, gateway_id: "5", tags: undefined })
    );
    component.$el = mockElement;
    component.init();

    component.loadPage(1);

    const url = new URL(window.htmx.ajax.mock.calls[0][1], "http://localhost");
    expect(url.searchParams.has("q")).toBe(false);
    expect(url.searchParams.has("tags")).toBe(false);
    expect(url.searchParams.get("gateway_id")).toBe("5");
  });

  test("loadPage() URL-encodes special characters from extraParams", () => {
    mockElement = makeElement(JSON.stringify({ q: 'foo"bar <x>' }));
    component.$el = mockElement;
    component.init();

    component.loadPage(1);

    const url = window.htmx.ajax.mock.calls[0][1];
    // Raw " or < must never appear in the URL.
    expect(url).not.toMatch(/q=foo"bar/);
    expect(url).not.toContain("<x>");
    expect(url).toContain("q=");
    // Round-trip back to confirm value is preserved.
    const parsed = new URL(url, "http://localhost");
    expect(parsed.searchParams.get("q")).toBe('foo"bar <x>');
  });

  test("loadPage() prefers extraParams.team_id over URL team_id", () => {
    mockElement = makeElement(JSON.stringify({ team_id: "from-server" }));
    component.$el = mockElement;
    component.init();
    window.location.search = "?team_id=from-url";

    component.loadPage(1);

    const url = new URL(window.htmx.ajax.mock.calls[0][1], "http://localhost");
    expect(url.searchParams.get("team_id")).toBe("from-server");
  });

  test("loadPage() falls back to URL team_id when extraParams omits it", () => {
    mockElement = makeElement(JSON.stringify({ q: "search" }));
    component.$el = mockElement;
    component.init();
    window.location.search = "?team_id=from-url";

    component.loadPage(1);

    const url = new URL(window.htmx.ajax.mock.calls[0][1], "http://localhost");
    expect(url.searchParams.get("team_id")).toBe("from-url");
    expect(url.searchParams.get("q")).toBe("search");
  });

  test("loadPage() lets paginationQuerySetters override extraParams", async () => {
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.paginationQuerySetters.tools = (url) => {
      url.searchParams.set("q", "live-form-value");
    };
    mockElement = makeElement(JSON.stringify({ q: "stale-server-value" }));
    component.$el = mockElement;
    component.init();

    component.loadPage(1);

    const url = new URL(window.htmx.ajax.mock.calls[0][1], "http://localhost");
    expect(url.searchParams.get("q")).toBe("live-form-value");
  });
});

// ---------------------------------------------------------------------------
// htmx:swapError unlocks _loading (Bug 2 regression)
//
// A swap failure (e.g. session expiry returning a full HTML login page that
// htmx can't merge into a fragment target) used to fire htmx:swapError but
// pagination.js only listened for afterSettle/responseError/sendError, so
// _loading stayed true forever and pagination silently froze.
// ---------------------------------------------------------------------------
describe("paginationData _loading unlock listeners", () => {
  let component;
  let mockElement;
  let registered;

  beforeEach(() => {
    registered = {};
    window.htmx = { ajax: vi.fn() };

    // The unlock listeners are now scoped to the swap target element (not
    // document). We capture them via addEventListener on the mock element
    // returned by document.querySelector for the target selector.
    const mockTarget = {
      closest: vi.fn(() => null),
      scrollIntoView: vi.fn(),
      addEventListener: vi.fn((event, fn) => {
        registered[event] = fn;
      }),
    };
    global.document.querySelector = vi.fn(() => mockTarget);
    global.document.getElementById = vi.fn(() => null);

    delete window.location;
    window.location = {
      href: "http://localhost:3000/admin",
      origin: "http://localhost:3000",
      pathname: "/admin",
      search: "",
      hash: "#tools",
    };

    mockElement = {
      dataset: {
        currentPage: "1",
        perPage: "10",
        totalItems: "100",
        totalPages: "10",
        hasNext: "true",
        hasPrev: "false",
        hxTarget: "#tools-table",
        hxSwap: "innerHTML",
        tableName: "tools",
        baseUrl: "/admin/tools/partial",
        hxIndicator: "#tools-loading",
      },
    };

    component = paginationData();
    component.$el = mockElement;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  test("loadPage() registers an unlock listener for htmx:swapError", () => {
    component.init();
    component.loadPage(2);

    // Bug 2 regression guard — without this listener, swap failures (e.g.
    // session expiry returning a login HTML page) leave _loading=true
    // forever and freeze pagination.
    expect(registered).toHaveProperty("htmx:swapError");
    expect(typeof registered["htmx:swapError"]).toBe("function");
  });

  test("loadPage() registers all four htmx unlock listeners", () => {
    component.init();
    component.loadPage(2);

    expect(Object.keys(registered).sort()).toEqual(
      [
        "htmx:afterSettle",
        "htmx:responseError",
        "htmx:sendError",
        "htmx:swapError",
      ].sort()
    );
  });

  test("loadPage() registers listeners on the target element, not document", () => {
    component.init();
    component.loadPage(2);

    // Listeners must be scoped to the target element so unrelated htmx
    // swaps on the page don't prematurely unlock this component.
    const targetEl = global.document.querySelector("#tools-table");
    expect(targetEl.addEventListener).toHaveBeenCalledTimes(4);
  });

  test("htmx:swapError unlocks _loading", () => {
    component.init();
    component.loadPage(2);
    expect(component._loading).toBe(true);

    // Simulate htmx firing swapError after the fragment merge fails.
    registered["htmx:swapError"]();

    expect(component._loading).toBe(false);
  });

  test("htmx:afterSettle unlocks _loading on the success path", () => {
    component.init();
    component.loadPage(2);
    expect(component._loading).toBe(true);

    registered["htmx:afterSettle"]();

    expect(component._loading).toBe(false);
  });

  test("after unlock, a subsequent loadPage() call is allowed", () => {
    component.init();
    component.loadPage(2);

    // Simulate the swap failing.
    registered["htmx:swapError"]();
    // Reset registered so the second call's listeners can be inspected.
    registered = {};

    component.loadPage(3);

    // The second call must have actually fired (proves no deadlock).
    expect(window.htmx.ajax).toHaveBeenCalledTimes(2);
    expect(registered).toHaveProperty("htmx:swapError");
  });

  test("loadPage() falls back to document if target element not found", () => {
    component.init();
    // First call returns null (target not found for listener registration),
    // but we need the bail-out check to pass — so return null only on
    // subsequent calls after the first querySelector for bail-out.
    let callCount = 0;
    global.document.addEventListener = vi.fn((event, fn) => {
      registered[event] = fn;
    });
    global.document.querySelector = vi.fn(() => {
      callCount++;
      // First call is the bail-out check (line: if (!document.querySelector(this.targetSelector)) return;)
      // which must return truthy. Second call is for the listener target.
      if (callCount <= 1) return { closest: vi.fn(() => null), scrollIntoView: vi.fn() };
      return null;
    });

    component.loadPage(2);

    // Should have fallen back to document.addEventListener
    expect(global.document.addEventListener).toHaveBeenCalled();
  });
});
