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
      return { closest: vi.fn(() => null), scrollIntoView: vi.fn() };
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
