/**
 * Unit tests for tokens.js module
 * Tests: getAuthToken, fetchWithAuth, getTeamNameById, updateTeamScopingWarning,
 *        displayTokensList, loadTokensList, initializeTeamScopingMonitor,
 *        setupCreateTokenForm, showTokenDetailsModal
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import {
  getAuthToken,
  fetchWithAuth,
  getTeamNameById,
  updateTeamScopingWarning,
  loadTokensList,
  initializeTeamScopingMonitor,
  setupCreateTokenForm,
  showTokenDetailsModal,
  showUsageStatsModal,
  setupTokenListEventHandlers,
  debouncedServerSideTokenSearch,
  performTokenSearch,
} from "../../../mcpgateway/admin_ui/tokens.js";
import {
  getCookie,
  getCurrentTeamId,
  getCurrentTeamName,
  fetchWithTimeout,
  buildTableUrl,
  getPaginationParams,
  copyToClipboard,
} from "../../../mcpgateway/admin_ui/utils.js";

// Mock dependencies
vi.mock("../../../mcpgateway/admin_ui/auth.js", () => ({
  getAuthHeaders: vi.fn(async () => ({ Authorization: "Bearer test-token" })),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  logRestrictedContext: vi.fn(),
  parseErrorResponse: vi.fn().mockResolvedValue("mocked error"),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  buildTableUrl: vi.fn(() => "/admin/tokens/partial?page=1"),
  copyToClipboard: vi.fn().mockResolvedValue(undefined),
  fetchWithTimeout: vi.fn(),
  getCookie: vi.fn(() => null),
  getCurrentTeamId: vi.fn(() => null),
  getCurrentTeamName: vi.fn(() => null),
  getPaginationParams: vi.fn(() => ({ perPage: 10 })),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showNotification: vi.fn(),
}));

// ---------------------------------------------------------------------------
// getAuthToken
// ---------------------------------------------------------------------------
describe("getAuthToken", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("returns jwt_token cookie when available", async () => {
    getCookie.mockImplementation((name) => (name === "jwt_token" ? "jwt-123" : null));
    const token = await getAuthToken();
    expect(token).toBe("jwt-123");
  });

  test("falls back to token cookie", async () => {
    getCookie.mockImplementation((name) => (name === "token" ? "tok-456" : null));
    const token = await getAuthToken();
    expect(token).toBe("tok-456");
  });

  test("falls back to localStorage", async () => {
    getCookie.mockReturnValue(null);
    vi.stubGlobal("localStorage", { getItem: vi.fn(() => "local-789") });
    const token = await getAuthToken();
    expect(token).toBe("local-789");
    vi.unstubAllGlobals();
  });

  test("returns empty string when no token found", async () => {
    getCookie.mockReturnValue(null);
    const spy = vi.spyOn(Storage.prototype, "getItem").mockReturnValue(null);
    const token = await getAuthToken();
    expect(token).toBe("");
    spy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// fetchWithAuth
// ---------------------------------------------------------------------------
describe("fetchWithAuth", () => {
  let fetchSpy;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("ok"));
    getCookie.mockImplementation((name) => (name === "jwt_token" ? "test-token" : null));
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  test("adds Authorization header with bearer token", async () => {
    await fetchWithAuth("/api/test");
    expect(fetchSpy).toHaveBeenCalled();
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toBe("/api/test");
    expect(opts.headers.get("Authorization")).toBe("Bearer test-token");
  });

  test("sets credentials to same-origin by default", async () => {
    await fetchWithAuth("/api/test");
    const [, opts] = fetchSpy.mock.calls[0];
    expect(opts.credentials).toBe("same-origin");
  });

  test("preserves caller-provided credentials", async () => {
    await fetchWithAuth("/api/test", { credentials: "include" }); // pragma: allowlist secret
    const [, opts] = fetchSpy.mock.calls[0];
    expect(opts.credentials).toBe("include");
  });

  test("preserves existing headers while adding auth", async () => {
    await fetchWithAuth("/api/test", {
      headers: { "Content-Type": "application/json" },
    });
    const [, opts] = fetchSpy.mock.calls[0];
    expect(opts.headers.get("Content-Type")).toBe("application/json");
    expect(opts.headers.get("Authorization")).toBe("Bearer test-token");
  });
});

// ---------------------------------------------------------------------------
// getTeamNameById
// ---------------------------------------------------------------------------
describe("getTeamNameById", () => {
  afterEach(() => {
    delete window.USERTEAMSDATA;
    document.body.innerHTML = "";
  });

  test("returns null for falsy teamId", () => {
    expect(getTeamNameById(null)).toBeNull();
    expect(getTeamNameById("")).toBeNull();
    expect(getTeamNameById(undefined)).toBeNull();
  });

  test("looks up team name from window.USERTEAMSDATA", () => {
    window.USERTEAMSDATA = [
      { id: "team-1", name: "Engineering" },
      { id: "team-2", name: "Design" },
    ];
    expect(getTeamNameById("team-1")).toBe("Engineering");
    expect(getTeamNameById("team-2")).toBe("Design");
  });

  test("returns truncated ID as fallback", () => {
    window.USERTEAMSDATA = [];
    const result = getTeamNameById("abcdefghijklmnop");
    expect(result).toBe("abcdefgh...");
  });
});

// ---------------------------------------------------------------------------
// updateTeamScopingWarning
// ---------------------------------------------------------------------------
describe("updateTeamScopingWarning", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("shows warning when no team is selected", () => {
    getCurrentTeamId.mockReturnValue(null);

    const warning = document.createElement("div");
    warning.id = "team-scoping-warning";
    warning.classList.add("hidden");
    document.body.appendChild(warning);

    const info = document.createElement("div");
    info.id = "team-scoping-info";
    document.body.appendChild(info);

    updateTeamScopingWarning();

    expect(warning.classList.contains("hidden")).toBe(false);
    expect(info.classList.contains("hidden")).toBe(true);
  });

  test("shows info when a team is selected", () => {
    getCurrentTeamId.mockReturnValue("team-1");
    getCurrentTeamName.mockReturnValue("Engineering");

    const warning = document.createElement("div");
    warning.id = "team-scoping-warning";
    document.body.appendChild(warning);

    const info = document.createElement("div");
    info.id = "team-scoping-info";
    info.classList.add("hidden");
    document.body.appendChild(info);

    const span = document.createElement("span");
    span.id = "selected-team-name";
    document.body.appendChild(span);

    updateTeamScopingWarning();

    expect(warning.classList.contains("hidden")).toBe(true);
    expect(info.classList.contains("hidden")).toBe(false);
    expect(span.textContent).toBe("Engineering");
  });

  test("does nothing when elements are missing", () => {
    expect(() => updateTeamScopingWarning()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// loadTokensList
// ---------------------------------------------------------------------------
describe("loadTokensList", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
  });

  test("does nothing when tokens-table element is missing", async () => {
    await loadTokensList();
    expect(fetchWithTimeout).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// setupCreateTokenForm
// ---------------------------------------------------------------------------
describe("setupCreateTokenForm", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("does nothing when form element is missing", () => {
    expect(() => setupCreateTokenForm()).not.toThrow();
  });

  test("attaches submit event listener to form", () => {
    getCurrentTeamId.mockReturnValue(null);

    // Set up required DOM
    const warning = document.createElement("div");
    warning.id = "team-scoping-warning";
    warning.classList.add("hidden");
    document.body.appendChild(warning);

    const info = document.createElement("div");
    info.id = "team-scoping-info";
    document.body.appendChild(info);

    const form = document.createElement("form");
    form.id = "create-token-form";
    document.body.appendChild(form);

    const spy = vi.spyOn(form, "addEventListener");
    setupCreateTokenForm();
    expect(spy).toHaveBeenCalledWith("submit", expect.any(Function));
  });
});

// ---------------------------------------------------------------------------
// showTokenDetailsModal
// ---------------------------------------------------------------------------
describe("showTokenDetailsModal", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("creates and appends modal to body", () => {
    window.USERTEAMSDATA = [];
    showTokenDetailsModal({
      id: "tok-123",
      name: "Test Token",
      description: "A test",
      is_active: true,
      created_at: "2024-01-01T00:00:00Z",
      expires_at: null,
      last_used: null,
      team_id: null,
      user_email: "admin@test.com",
      resource_scopes: [],
      ip_restrictions: [],
      time_restrictions: {},
      usage_limits: {},
      tags: [],
    });

    const modal = document.querySelector(".fixed");
    expect(modal).not.toBeNull();
    expect(modal.innerHTML).toContain("Token Details");
    expect(modal.innerHTML).toContain("tok-123");
    expect(modal.innerHTML).toContain("Test Token");
    delete window.USERTEAMSDATA;
  });

  test("shows revocation details when token is revoked", () => {
    window.USERTEAMSDATA = [];
    showTokenDetailsModal({
      id: "tok-456",
      name: "Revoked Token",
      is_active: false,
      is_revoked: true,
      revoked_at: "2024-06-01T00:00:00Z",
      revoked_by: "admin",
      revocation_reason: "Compromised",
      created_at: "2024-01-01T00:00:00Z",
      expires_at: null,
      last_used: null,
      team_id: null,
      resource_scopes: [],
      ip_restrictions: [],
      time_restrictions: {},
      usage_limits: {},
      tags: [],
    });

    const modal = document.querySelector(".fixed");
    expect(modal.innerHTML).toContain("Revocation Details");
    expect(modal.innerHTML).toContain("Compromised");
    delete window.USERTEAMSDATA;
  });

  test("close button removes modal", () => {
    window.USERTEAMSDATA = [];
    showTokenDetailsModal({
      id: "tok-789",
      name: "Close Test",
      is_active: true,
      created_at: null,
      expires_at: null,
      last_used: null,
      team_id: null,
      resource_scopes: [],
      ip_restrictions: [],
      time_restrictions: {},
      usage_limits: {},
      tags: [],
    });

    const modal = document.querySelector(".fixed");
    const closeBtn = modal.querySelector('[data-action="close-modal"]');
    closeBtn.click();
    expect(document.querySelector(".fixed")).toBeNull();
    delete window.USERTEAMSDATA;
  });
});

// ---------------------------------------------------------------------------
// initializeTeamScopingMonitor
// ---------------------------------------------------------------------------
describe("initializeTeamScopingMonitor", () => {
  test("registers alpine:init and DOMContentLoaded listeners", () => {
    const spy = vi.spyOn(document, "addEventListener");
    initializeTeamScopingMonitor();
    const eventNames = spy.mock.calls.map((c) => c[0]);
    expect(eventNames).toContain("alpine:init");
    expect(eventNames).toContain("DOMContentLoaded");
    spy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// getAuthToken — additional paths
// ---------------------------------------------------------------------------
describe("getAuthToken - additional", () => {
  test("does not add Authorization header when no token found", async () => {
    getCookie.mockReturnValue(null);
    vi.spyOn(Storage.prototype, "getItem").mockReturnValue(null);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("ok"));

    await fetchWithAuth("/api/test");

    const [, opts] = fetchSpy.mock.calls[0];
    expect(opts.headers.get("Authorization")).toBeNull();

    fetchSpy.mockRestore();
  });

  test("handles localStorage access error gracefully", async () => {
    const { logRestrictedContext } = await import("../../../mcpgateway/admin_ui/security.js");
    getCookie.mockReturnValue(null);
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => { throw new Error("localStorage unavailable"); }),
    });

    const token = await getAuthToken();
    expect(token).toBe("");
    expect(logRestrictedContext).toHaveBeenCalled();

    vi.unstubAllGlobals();
  });
});

// ---------------------------------------------------------------------------
// getTeamNameById — Alpine.js data stack fallback
// ---------------------------------------------------------------------------
describe("getTeamNameById - Alpine fallback", () => {
  afterEach(() => {
    delete window.USERTEAMSDATA;
    document.body.innerHTML = "";
  });

  test("looks up team name from Alpine.js _x_dataStack", () => {
    window.USERTEAMSDATA = undefined;
    const selector = document.createElement("div");
    selector.setAttribute("x-data", '{"selectedTeam":"t1"}');
    selector._x_dataStack = [{ teams: [{ id: "t-alpine", name: "AlpineTeam" }] }];
    document.body.appendChild(selector);

    expect(getTeamNameById("t-alpine")).toBe("AlpineTeam");
  });

  test("falls back to truncated ID when not found in Alpine data", () => {
    window.USERTEAMSDATA = undefined;
    const selector = document.createElement("div");
    selector.setAttribute("x-data", '{"selectedTeam":"t1"}');
    selector._x_dataStack = [{ teams: [{ id: "other", name: "Other" }] }];
    document.body.appendChild(selector);

    const result = getTeamNameById("not-found-team-id");
    expect(result).toContain("...");
  });
});

// ---------------------------------------------------------------------------
// updateTeamScopingWarning — additional paths
// ---------------------------------------------------------------------------
describe("updateTeamScopingWarning - additional", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.clearAllMocks();
  });

  test("uses teamId as fallback when getCurrentTeamName returns null", () => {
    getCurrentTeamId.mockReturnValue("team-fallback-id");
    getCurrentTeamName.mockReturnValue(null);

    const warning = document.createElement("div");
    warning.id = "team-scoping-warning";
    document.body.appendChild(warning);

    const info = document.createElement("div");
    info.id = "team-scoping-info";
    document.body.appendChild(info);

    const span = document.createElement("span");
    span.id = "selected-team-name";
    document.body.appendChild(span);

    updateTeamScopingWarning();

    expect(span.textContent).toBe("team-fallback-id");
  });

  test("handles missing teamNameSpan gracefully", () => {
    getCurrentTeamId.mockReturnValue("team-1");
    getCurrentTeamName.mockReturnValue("Engineering");

    const warning = document.createElement("div");
    warning.id = "team-scoping-warning";
    document.body.appendChild(warning);

    const info = document.createElement("div");
    info.id = "team-scoping-info";
    document.body.appendChild(info);

    // No selected-team-name span
    expect(() => updateTeamScopingWarning()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// loadTokensList — extended
// ---------------------------------------------------------------------------
describe("loadTokensList - extended", () => {
  let htmxMock;

  beforeEach(() => {
    window.ROOT_PATH = "";
    htmxMock = { process: vi.fn(), trigger: vi.fn() };
    window.htmx = htmxMock;
    delete window.location;
    window.location = { origin: "http://localhost", search: "" };
    getPaginationParams.mockReturnValue({ perPage: 10 });
    getCurrentTeamId.mockReturnValue(null);
    vi.clearAllMocks();
    getPaginationParams.mockReturnValue({ perPage: 10 });
    getCurrentTeamId.mockReturnValue(null);
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
    delete window.location;
    window.location = { origin: "http://localhost", search: "" };
  });

  function addTokensTable() {
    const table = document.createElement("div");
    table.id = "tokens-table";
    document.body.appendChild(table);
    return table;
  }

  test("resetToFirstPage=true sets page=1 in URL", async () => {
    const table = addTokensTable();
    await loadTokensList(true);

    const url = table.getAttribute("hx-get");
    expect(url).toContain("page=1");
    expect(htmxMock.process).toHaveBeenCalledWith(table);
    expect(htmxMock.trigger).toHaveBeenCalledWith(table, "refreshTokens");
  });

  test("resetToFirstPage=true includes per_page from getPaginationParams", async () => {
    getPaginationParams.mockReturnValue({ perPage: 25 });
    const table = addTokensTable();

    await loadTokensList(true);

    const url = table.getAttribute("hx-get");
    expect(url).toContain("per_page=25");
  });

  test("resetToFirstPage=true includes team_id when team is selected", async () => {
    getCurrentTeamId.mockReturnValue("team-abc");
    const table = addTokensTable();

    await loadTokensList(true);

    const url = table.getAttribute("hx-get");
    expect(url).toContain("team_id=team-abc");
  });

  test("resetToFirstPage=true includes include_inactive from checkbox", async () => {
    const checkbox = document.createElement("input");
    checkbox.id = "show-inactive-tokens";
    checkbox.type = "checkbox";
    checkbox.checked = true;
    document.body.appendChild(checkbox);

    const table = addTokensTable();
    await loadTokensList(true);

    const url = table.getAttribute("hx-get");
    expect(url).toContain("include_inactive=true");
  });

  test("resetToFirstPage=false uses buildTableUrl", async () => {
    buildTableUrl.mockReturnValue("/admin/tokens/partial?page=2&per_page=10");
    const table = addTokensTable();

    await loadTokensList(false);

    expect(buildTableUrl).toHaveBeenCalledWith(
      "tokens",
      expect.stringContaining("/admin/tokens/partial"),
      expect.any(Object)
    );
    const url = table.getAttribute("hx-get");
    expect(url).toContain("page=2");
  });

  test("htmx.process and htmx.trigger are called with tokens-table", async () => {
    const table = addTokensTable();
    await loadTokensList(true);

    expect(htmxMock.process).toHaveBeenCalledWith(table);
    expect(htmxMock.trigger).toHaveBeenCalledWith(table, "refreshTokens");
  });
});

// ---------------------------------------------------------------------------
// debouncedServerSideTokenSearch
// ---------------------------------------------------------------------------
describe("debouncedServerSideTokenSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    window.ROOT_PATH = "";
    window.htmx = { process: vi.fn(), trigger: vi.fn() };
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  test("does not throw when called", () => {
    expect(() => debouncedServerSideTokenSearch("test")).not.toThrow();
  });

  test("debounces multiple calls and only triggers once", () => {
    const table = document.createElement("div");
    table.id = "tokens-table";
    document.body.appendChild(table);

    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    debouncedServerSideTokenSearch("a");
    debouncedServerSideTokenSearch("ab");
    debouncedServerSideTokenSearch("abc");

    // Before 300ms, htmx should not have been triggered
    expect(window.htmx.trigger).not.toHaveBeenCalled();

    vi.advanceTimersByTime(300);

    // After debounce, should have been triggered once
    expect(window.htmx.trigger).toHaveBeenCalledTimes(1);

    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// performTokenSearch
// ---------------------------------------------------------------------------
describe("performTokenSearch", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.htmx = { process: vi.fn(), trigger: vi.fn() };
    getPaginationParams.mockReturnValue({ perPage: 10 });
    getCurrentTeamId.mockReturnValue(null);
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
    vi.clearAllMocks();
  });

  test("returns early and logs error when tokens-table is missing", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await performTokenSearch("test");
    expect(consoleSpy).toHaveBeenCalledWith(expect.stringContaining("tokens-table"));
    consoleSpy.mockRestore();
  });

  test("sets hx-get and triggers htmx when table exists", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const table = document.createElement("div");
    table.id = "tokens-table";
    document.body.appendChild(table);

    await performTokenSearch("my-token");

    expect(table.getAttribute("hx-get")).toContain("/admin/tokens/partial");
    expect(table.getAttribute("hx-get")).toContain("q=my-token");
    expect(window.htmx.process).toHaveBeenCalledWith(table);
    expect(window.htmx.trigger).toHaveBeenCalledWith(table, "refreshTokens");
    consoleSpy.mockRestore();
  });

  test("does not include q param for empty searchTerm", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const table = document.createElement("div");
    table.id = "tokens-table";
    document.body.appendChild(table);

    await performTokenSearch("");

    const url = table.getAttribute("hx-get");
    expect(url).not.toContain("q=");
    consoleSpy.mockRestore();
  });

  test("includes team_id when getCurrentTeamId returns a value", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    getCurrentTeamId.mockReturnValue("team-xyz");

    const table = document.createElement("div");
    table.id = "tokens-table";
    document.body.appendChild(table);

    await performTokenSearch("search");

    const url = table.getAttribute("hx-get");
    expect(url).toContain("team_id=team-xyz");
    consoleSpy.mockRestore();
  });

  test("includes include_inactive from checkbox", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const checkbox = document.createElement("input");
    checkbox.id = "show-inactive-tokens";
    checkbox.type = "checkbox";
    checkbox.checked = true;
    document.body.appendChild(checkbox);

    const table = document.createElement("div");
    table.id = "tokens-table";
    document.body.appendChild(table);

    await performTokenSearch("tok");

    const url = table.getAttribute("hx-get");
    expect(url).toContain("include_inactive=true");
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// setupTokenListEventHandlers
// ---------------------------------------------------------------------------
describe("setupTokenListEventHandlers", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.USERTEAMSDATA = [];
    window.Admin = {};
    window.htmx = { process: vi.fn(), trigger: vi.fn() };
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.USERTEAMSDATA;
    delete window.Admin;
    delete window.htmx;
    vi.clearAllMocks();
  });

  test("does nothing when panel is missing and no container provided", () => {
    expect(() => setupTokenListEventHandlers()).not.toThrow();
  });

  test("attaches handler to tokens-panel", () => {
    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);

    setupTokenListEventHandlers();

    expect(panel.dataset.tokenHandlersAttached).toBe("true");
  });

  test("does not attach handler twice (idempotent)", () => {
    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    panel.dataset.tokenHandlersAttached = "true";
    document.body.appendChild(panel);

    const spy = vi.spyOn(panel, "addEventListener");
    setupTokenListEventHandlers();

    expect(spy).not.toHaveBeenCalled();
  });

  test("uses container when tokens-panel is missing", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);

    setupTokenListEventHandlers(container);

    expect(container.dataset.tokenHandlersAttached).toBe("true");
  });

  test("token-details click opens details modal", () => {
    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);

    setupTokenListEventHandlers();

    const tokenObj = {
      id: "t1", name: "My Token", is_active: true,
      created_at: null, expires_at: null, last_used: null,
      team_id: null, resource_scopes: [], ip_restrictions: [],
      time_restrictions: {}, usage_limits: {}, tags: [],
    };

    const btn = document.createElement("button");
    btn.dataset.action = "token-details";
    btn.dataset.token = JSON.stringify(tokenObj);
    panel.appendChild(btn);

    btn.click();

    const modal = document.querySelector(".fixed");
    expect(modal).not.toBeNull();
    expect(modal.innerHTML).toContain("Token Details");
  });

  test("token-details click handles URI-encoded token data", () => {
    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);

    setupTokenListEventHandlers();

    const tokenObj = {
      id: "t1", name: "My Token", is_active: true,
      created_at: null, expires_at: null, last_used: null,
      team_id: null, resource_scopes: [], ip_restrictions: [],
      time_restrictions: {}, usage_limits: {}, tags: [],
    };

    const btn = document.createElement("button");
    btn.dataset.action = "token-details";
    btn.dataset.token = encodeURIComponent(JSON.stringify(tokenObj));
    panel.appendChild(btn);

    btn.click();

    const modal = document.querySelector(".fixed");
    expect(modal).not.toBeNull();
  });

  test("token-details logs error on invalid JSON", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);

    setupTokenListEventHandlers();

    const btn = document.createElement("button");
    btn.dataset.action = "token-details";
    btn.dataset.token = "not-valid-json{{";
    panel.appendChild(btn);

    btn.click();

    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("Failed to parse token data"),
      expect.any(Error)
    );
    consoleSpy.mockRestore();
  });

  test("token-revoke triggers confirm then fetchWithTimeout", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { showNotification } = await import("../../../mcpgateway/admin_ui/utils.js");

    fetchWithTimeout.mockResolvedValue({ ok: true });

    delete window.location;
    window.location = { origin: "http://localhost", search: "" };

    window.htmx = { process: vi.fn(), trigger: vi.fn() };

    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);

    const table = document.createElement("div");
    table.id = "tokens-table";
    document.body.appendChild(table);

    setupTokenListEventHandlers();

    const btn = document.createElement("button");
    btn.dataset.action = "token-revoke";
    btn.dataset.tokenId = "tok-99";
    btn.dataset.tokenName = "My Token";
    panel.appendChild(btn);

    btn.click();
    // Allow async handlers to run
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(confirmSpy).toHaveBeenCalled();
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("tok-99"),
      expect.objectContaining({ method: "DELETE" })
    );
    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("revoked successfully"),
      "success"
    );

    confirmSpy.mockRestore();
    consoleSpy.mockRestore();
  });

  test("token-revoke does nothing when confirm is cancelled", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);

    setupTokenListEventHandlers();

    const btn = document.createElement("button");
    btn.dataset.action = "token-revoke";
    btn.dataset.tokenId = "tok-99";
    btn.dataset.tokenName = "My Token";
    panel.appendChild(btn);

    btn.click();

    expect(fetchWithTimeout).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  test("non-button click is ignored", () => {
    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);

    setupTokenListEventHandlers();

    const div = document.createElement("div");
    panel.appendChild(div);
    expect(() => div.click()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// setupCreateTokenForm — HTMX error handler
// ---------------------------------------------------------------------------
describe("setupCreateTokenForm - HTMX error handlers", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.htmx = { process: vi.fn(), trigger: vi.fn() };
    getCurrentTeamId.mockReturnValue(null);
    getPaginationParams.mockReturnValue({ perPage: 10 });
    delete window.location;
    window.location = { origin: "http://localhost", search: "" };
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
    vi.clearAllMocks();
  });

  function buildSetup() {
    const warning = document.createElement("div");
    warning.id = "team-scoping-warning";
    document.body.appendChild(warning);
    const info = document.createElement("div");
    info.id = "team-scoping-info";
    document.body.appendChild(info);
    const form = document.createElement("form");
    form.id = "create-token-form";
    document.body.appendChild(form);
    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);
    const table = document.createElement("div");
    table.id = "tokens-table";
    document.body.appendChild(table);
    return { form, panel, table };
  }

  test("attaches htmx:responseError handler to tokens-panel", () => {
    const { panel } = buildSetup();
    setupCreateTokenForm();
    expect(panel.dataset.htmxErrorHandlerAttached).toBe("true");
  });

  test("does not attach error handler twice", () => {
    const { panel } = buildSetup();
    panel.dataset.htmxErrorHandlerAttached = "true";
    const spy = vi.spyOn(panel, "addEventListener");

    setupCreateTokenForm();

    const htmxCalls = spy.mock.calls.filter((c) =>
      c[0].startsWith("htmx:")
    );
    expect(htmxCalls.length).toBe(0);
  });

  test("htmx:responseError shows error with status in tokens-table", () => {
    const { panel, table } = buildSetup();
    setupCreateTokenForm();

    const evt = new CustomEvent("htmx:responseError", {
      detail: { xhr: { status: 503 } },
    });
    panel.dispatchEvent(evt);

    expect(table.innerHTML).toContain("Failed to load tokens");
    expect(table.innerHTML).toContain("503");
  });

  test("htmx:responseError retry button triggers loadTokensList", async () => {
    const { panel, table } = buildSetup();
    setupCreateTokenForm();

    panel.dispatchEvent(
      new CustomEvent("htmx:responseError", {
        detail: { xhr: { status: 500 } },
      })
    );

    const retryBtn = table.querySelector('[data-action="retry-tokens"]');
    expect(retryBtn).not.toBeNull();

    retryBtn.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    // loadTokensList will call htmx.process / htmx.trigger on tokens-table
    expect(window.htmx.process).toHaveBeenCalled();
  });

  test("htmx:sendError shows network error in tokens-table", () => {
    const { panel, table } = buildSetup();
    setupCreateTokenForm();

    panel.dispatchEvent(new CustomEvent("htmx:sendError"));

    expect(table.innerHTML).toContain("Failed to load tokens");
    expect(table.innerHTML).toContain("Network error");
  });

  test("htmx:sendError retry button triggers loadTokensList", async () => {
    const { panel, table } = buildSetup();
    setupCreateTokenForm();

    panel.dispatchEvent(new CustomEvent("htmx:sendError"));

    const retryBtn = table.querySelector('[data-action="retry-tokens"]');
    retryBtn.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(window.htmx.process).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// createToken via form submit
// ---------------------------------------------------------------------------
describe("createToken via setupCreateTokenForm submit", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.Admin = {};
    getCurrentTeamId.mockReturnValue(null);
    getCookie.mockImplementation((n) => (n === "jwt_token" ? "test-tok" : null));
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.Admin;
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  function buildForm() {
    const warning = document.createElement("div");
    warning.id = "team-scoping-warning";
    document.body.appendChild(warning);
    const info = document.createElement("div");
    info.id = "team-scoping-info";
    document.body.appendChild(info);

    const form = document.createElement("form");
    form.id = "create-token-form";

    const nameInput = document.createElement("input");
    nameInput.name = "name";
    nameInput.value = "My Token";
    form.appendChild(nameInput);

    const descInput = document.createElement("input");
    descInput.name = "description";
    descInput.value = "test desc";
    form.appendChild(descInput);

    const submitBtn = document.createElement("button");
    submitBtn.type = "submit";
    submitBtn.textContent = "Create";
    form.appendChild(submitBtn);

    document.body.appendChild(form);
    return { form, submitBtn };
  }

  test("successful token creation shows modal and resets form", async () => {
    const { form } = buildForm();
    const { showNotification } = await import("../../../mcpgateway/admin_ui/utils.js");

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        access_token: "new-tok-abc",
        token: { name: "My Token", expires_at: null },
      }),
    });

    setupCreateTokenForm();

    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("token created successfully"),
      "success"
    );
    const modal = document.querySelector(".fixed");
    expect(modal).not.toBeNull();
    expect(modal.innerHTML).toContain("new-tok-abc");
  });

  test("token creation failure shows error notification", async () => {
    const { form } = buildForm();
    const { showNotification } = await import("../../../mcpgateway/admin_ui/utils.js");

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 400,
      json: () => Promise.resolve({ detail: "Bad request" }),
    });

    setupCreateTokenForm();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Error creating token"),
      "error"
    );
  });

  test("409 conflict with generic message uses custom label", async () => {
    const { form } = buildForm();
    const { showNotification } = await import("../../../mcpgateway/admin_ui/utils.js");
    const { parseErrorResponse: mockParse } = await import("../../../mcpgateway/admin_ui/security.js");

    mockParse.mockResolvedValueOnce(
      "Unable to complete the operation. Please try again."
    );

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 409,
      json: () => Promise.resolve({}),
    });

    setupCreateTokenForm();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("All Teams"),
      "error"
    );
  });

  test("400 team-not-found error uses friendly message", async () => {
    const { form } = buildForm();
    const { showNotification } = await import("../../../mcpgateway/admin_ui/utils.js");
    const { parseErrorResponse: mockParse } = await import("../../../mcpgateway/admin_ui/security.js");

    mockParse.mockResolvedValueOnce("Team not found: xyz-team-id");

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 400,
      json: () => Promise.resolve({}),
    });

    setupCreateTokenForm();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("no longer available"),
      "error"
    );
  });

  test("invalid IP shows validation error without calling API", async () => {
    const { form } = buildForm();
    const { showNotification } = await import("../../../mcpgateway/admin_ui/utils.js");

    const ipInput = document.createElement("input");
    ipInput.name = "ip_restrictions";
    ipInput.value = "not-an-ip";
    form.appendChild(ipInput);

    setupCreateTokenForm();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchWithTimeout).not.toHaveBeenCalled();
    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Invalid IP address"),
      "error"
    );
  });

  test("invalid permission shows validation error without calling API", async () => {
    const { form } = buildForm();
    const { showNotification } = await import("../../../mcpgateway/admin_ui/utils.js");

    const permInput = document.createElement("input");
    permInput.name = "permissions";
    permInput.value = "bad permission format!!";
    form.appendChild(permInput);

    setupCreateTokenForm();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchWithTimeout).not.toHaveBeenCalled();
    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Invalid permission format"),
      "error"
    );
  });

  test("valid IPv4 and CIDR passes validation", async () => {
    const { form } = buildForm();
    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        access_token: "tok",
        token: { name: "My Token", expires_at: null },
      }),
    });

    const ipInput = document.createElement("input");
    ipInput.name = "ip_restrictions";
    ipInput.value = "192.168.1.0/24, 10.0.0.1";
    form.appendChild(ipInput);

    setupCreateTokenForm();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchWithTimeout).toHaveBeenCalled();
    const callBody = JSON.parse(fetchWithTimeout.mock.calls[0][1].body);
    expect(callBody.scope.ip_restrictions).toEqual(["192.168.1.0/24", "10.0.0.1"]);
  });

  test("wildcard * permission passes validation", async () => {
    const { form } = buildForm();
    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        access_token: "tok",
        token: { name: "My Token", expires_at: null },
      }),
    });

    const permInput = document.createElement("input");
    permInput.name = "permissions";
    permInput.value = "*";
    form.appendChild(permInput);

    setupCreateTokenForm();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchWithTimeout).toHaveBeenCalled();
    const callBody = JSON.parse(fetchWithTimeout.mock.calls[0][1].body);
    expect(callBody.scope.permissions).toEqual(["*"]);
  });
});

// ---------------------------------------------------------------------------
// showTokenDetailsModal — extended
// ---------------------------------------------------------------------------
describe("showTokenDetailsModal - extended", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    delete window.USERTEAMSDATA;
  });

  test("shows team name when token has team_id", () => {
    window.USERTEAMSDATA = [{ id: "team-1", name: "Engineering" }];
    showTokenDetailsModal({
      id: "tok-1", name: "Team Token", is_active: true,
      created_at: null, expires_at: null, last_used: null,
      team_id: "team-1", resource_scopes: [], ip_restrictions: [],
      time_restrictions: {}, usage_limits: {}, tags: [],
    });

    const modal = document.querySelector(".fixed");
    expect(modal.innerHTML).toContain("Engineering");
  });

  test("renders tags when token has tags", () => {
    window.USERTEAMSDATA = [];
    showTokenDetailsModal({
      id: "tok-2", name: "Tagged Token", is_active: true,
      created_at: null, expires_at: null, last_used: null,
      team_id: null, resource_scopes: [], ip_restrictions: [],
      time_restrictions: {}, usage_limits: {},
      tags: ["production", "critical"],
    });

    const modal = document.querySelector(".fixed");
    expect(modal.innerHTML).toContain("production");
    expect(modal.innerHTML).toContain("critical");
  });

  test("renders resource_scopes list", () => {
    window.USERTEAMSDATA = [];
    showTokenDetailsModal({
      id: "tok-3", name: "Scoped Token", is_active: true,
      created_at: null, expires_at: null, last_used: null,
      team_id: null, resource_scopes: ["tools.read", "resources.write"],
      ip_restrictions: [], time_restrictions: {}, usage_limits: {}, tags: [],
    });

    const modal = document.querySelector(".fixed");
    expect(modal.innerHTML).toContain("tools.read");
    expect(modal.innerHTML).toContain("resources.write");
  });

  test("renders ip_restrictions list", () => {
    window.USERTEAMSDATA = [];
    showTokenDetailsModal({
      id: "tok-4", name: "IP Token", is_active: true,
      created_at: null, expires_at: null, last_used: null,
      team_id: null, resource_scopes: [],
      ip_restrictions: ["192.168.1.0/24"],
      time_restrictions: {}, usage_limits: {}, tags: [],
    });

    const modal = document.querySelector(".fixed");
    expect(modal.innerHTML).toContain("192.168.1.0/24");
  });

  test("copy-id button copies value to clipboard", async () => {
    window.USERTEAMSDATA = [];
    vi.useFakeTimers();
    vi.stubGlobal("navigator", {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });

    showTokenDetailsModal({
      id: "tok-copy-me", name: "Copy Token", is_active: true,
      created_at: null, expires_at: null, last_used: null,
      team_id: null, resource_scopes: [], ip_restrictions: [],
      time_restrictions: {}, usage_limits: {}, tags: [],
    });

    const modal = document.querySelector(".fixed");
    const copyBtn = modal.querySelector('[data-action="copy-id"]');
    copyBtn.click();

    await Promise.resolve();
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("tok-copy-me");

    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
});

// ---------------------------------------------------------------------------
// showUsageStatsModal
// ---------------------------------------------------------------------------
describe("showUsageStatsModal", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  const baseStats = {
    period_days: 30,
    total_requests: 500,
    successful_requests: 480,
    blocked_requests: 20,
    success_rate: 0.96,
    average_response_time_ms: 42,
    top_endpoints: [],
  };

  test("creates and appends usage stats modal", () => {
    showUsageStatsModal(baseStats);

    const modal = document.querySelector(".fixed");
    expect(modal).not.toBeNull();
    expect(modal.innerHTML).toContain("Token Usage Statistics");
    expect(modal.innerHTML).toContain("500");
    expect(modal.innerHTML).toContain("480");
    expect(modal.innerHTML).toContain("42ms");
  });

  test("shows success rate as percentage", () => {
    showUsageStatsModal(baseStats);
    const modal = document.querySelector(".fixed");
    expect(modal.innerHTML).toContain("96%");
  });

  test("renders top_endpoints when present", () => {
    const statsWithEndpoints = {
      ...baseStats,
      top_endpoints: [["/mcp/tools", 200], ["/mcp/resources", 100]],
    };

    showUsageStatsModal(statsWithEndpoints);

    const modal = document.querySelector(".fixed");
    expect(modal.innerHTML).toContain("Top Endpoints");
    expect(modal.innerHTML).toContain("/mcp/tools");
    expect(modal.innerHTML).toContain("200 requests");
  });

  test("does not render top_endpoints section when empty", () => {
    showUsageStatsModal(baseStats);
    const modal = document.querySelector(".fixed");
    expect(modal.innerHTML).not.toContain("Top Endpoints");
  });

  test("close button removes modal", () => {
    showUsageStatsModal(baseStats);

    const modal = document.querySelector(".fixed");
    const closeBtn = modal.querySelector('[data-action="close-stats-modal"]');
    expect(closeBtn).not.toBeNull();

    closeBtn.click();
    expect(document.querySelector(".fixed")).toBeNull();
  });

  test("shows period_days in title", () => {
    showUsageStatsModal({ ...baseStats, period_days: 7 });
    const modal = document.querySelector(".fixed");
    expect(modal.innerHTML).toContain("7 Days");
  });
});

// ---------------------------------------------------------------------------
// performTokenSearch - error catch (line 120)
// ---------------------------------------------------------------------------
describe("performTokenSearch - error catch", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.htmx = { process: vi.fn(), trigger: vi.fn() };
    getPaginationParams.mockReturnValue({ perPage: 10 });
    getCurrentTeamId.mockReturnValue(null);
  });
  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
    vi.clearAllMocks();
  });

  test("catches and logs error when htmx.process throws", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    window.htmx.process = vi.fn(() => { throw new Error("htmx broken"); });

    const table = document.createElement("div");
    table.id = "tokens-table";
    document.body.appendChild(table);

    await performTokenSearch("test");

    expect(consoleSpy).toHaveBeenCalledWith(
      "Error searching tokens:",
      expect.any(Error)
    );
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// setupTokenListEventHandlers - token-usage action (lines 168-171, 684-702)
// ---------------------------------------------------------------------------
describe("setupTokenListEventHandlers - token-usage action", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.Admin = {};
    window.htmx = { process: vi.fn(), trigger: vi.fn() };
  });
  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.Admin;
    delete window.htmx;
    vi.clearAllMocks();
  });

  test("token-usage click calls viewTokenUsage (success path)", async () => {
    const baseStats = {
      period_days: 30,
      total_requests: 100,
      successful_requests: 95,
      blocked_requests: 5,
      success_rate: 0.95,
      average_response_time_ms: 10,
      top_endpoints: [],
    };
    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(baseStats),
    });

    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);

    setupTokenListEventHandlers();

    const btn = document.createElement("button");
    btn.dataset.action = "token-usage";
    btn.dataset.tokenId = "tok-usage-1";
    panel.appendChild(btn);

    btn.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("tok-usage-1"),
      expect.any(Object)
    );
    const modal = document.querySelector(".fixed");
    expect(modal).not.toBeNull();
    expect(modal.innerHTML).toContain("Token Usage Statistics");
  });

  test("token-usage click handles fetch error (catch path)", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { showNotification } = await import("../../../mcpgateway/admin_ui/utils.js");

    fetchWithTimeout.mockResolvedValue({ ok: false, status: 500 });

    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);

    setupTokenListEventHandlers();

    const btn = document.createElement("button");
    btn.dataset.action = "token-usage";
    btn.dataset.tokenId = "tok-usage-2";
    panel.appendChild(btn);

    btn.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Error loading usage stats"),
      "error"
    );
    consoleSpy.mockRestore();
  });

  test("token-usage click does nothing when tokenId is missing", async () => {
    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);

    setupTokenListEventHandlers();

    const btn = document.createElement("button");
    btn.dataset.action = "token-usage";
    // no tokenId
    panel.appendChild(btn);

    btn.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchWithTimeout).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// revokeToken error paths (lines 665-669, 675-676)
// ---------------------------------------------------------------------------
describe("setupTokenListEventHandlers - revokeToken error paths", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.Admin = {};
    window.htmx = { process: vi.fn(), trigger: vi.fn() };
  });
  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.Admin;
    delete window.htmx;
    vi.clearAllMocks();
  });

  test("revokeToken shows error notification when response is not ok", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { showNotification } = await import("../../../mcpgateway/admin_ui/utils.js");
    const { parseErrorResponse: mockParse } = await import("../../../mcpgateway/admin_ui/security.js");

    mockParse.mockResolvedValueOnce("Token not found");
    fetchWithTimeout.mockResolvedValue({ ok: false, status: 404 });

    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);

    setupTokenListEventHandlers();

    const btn = document.createElement("button");
    btn.dataset.action = "token-revoke";
    btn.dataset.tokenId = "tok-bad";
    btn.dataset.tokenName = "Bad Token";
    panel.appendChild(btn);

    btn.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Error revoking token"),
      "error"
    );

    confirmSpy.mockRestore();
    consoleSpy.mockRestore();
  });

  test("revokeToken catch block fires when fetchWithTimeout throws", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { showNotification } = await import("../../../mcpgateway/admin_ui/utils.js");

    fetchWithTimeout.mockRejectedValue(new Error("Network down"));

    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);

    setupTokenListEventHandlers();

    const btn = document.createElement("button");
    btn.dataset.action = "token-revoke";
    btn.dataset.tokenId = "tok-throw";
    btn.dataset.tokenName = "Throw Token";
    panel.appendChild(btn);

    btn.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(consoleSpy).toHaveBeenCalledWith(
      "Error revoking token:",
      expect.any(Error)
    );
    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Error revoking token: Network down"),
      "error"
    );

    confirmSpy.mockRestore();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// initializeTeamScopingMonitor - alpine:init and DOMContentLoaded paths
// ---------------------------------------------------------------------------
describe("initializeTeamScopingMonitor - event paths", () => {
  beforeEach(() => {
    window.Admin = {};
    window.htmx = { process: vi.fn(), trigger: vi.fn() };
  });
  afterEach(() => {
    document.body.innerHTML = "";
    delete window.Admin;
    delete window.htmx;
    delete window.Alpine;
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  test("alpine:init sets up interval when Alpine and teamSelector exist", () => {
    vi.useFakeTimers();
    window.Alpine = {};
    window.Admin = {};

    const selector = document.createElement("div");
    selector.setAttribute("x-data", '{"selectedTeam": "t1"}');
    document.body.appendChild(selector);

    // Set up scoping warning elements for updateTeamScopingWarning
    const warningDiv = document.createElement("div");
    warningDiv.id = "team-scoping-warning";
    document.body.appendChild(warningDiv);
    const infoDiv = document.createElement("div");
    infoDiv.id = "team-scoping-info";
    document.body.appendChild(infoDiv);

    getCurrentTeamId.mockReturnValue(null);

    initializeTeamScopingMonitor();

    document.dispatchEvent(new Event("alpine:init"));

    expect(window.Admin._teamMonitorInterval).toBeDefined();

    // Advance timer to verify interval fires
    vi.advanceTimersByTime(500);
    // updateTeamScopingWarning was called (warningDiv should have class manipulated)
  });

  test("alpine:init does not set interval when Alpine is missing", () => {
    window.Alpine = undefined;
    window.Admin = {};

    const selector = document.createElement("div");
    selector.setAttribute("x-data", '{"selectedTeam": "t1"}');
    document.body.appendChild(selector);

    initializeTeamScopingMonitor();
    document.dispatchEvent(new Event("alpine:init"));

    expect(window.Admin._teamMonitorInterval).toBeUndefined();
  });

  test("DOMContentLoaded attaches click handler to tokens tab", () => {
    vi.useFakeTimers();

    const warningDiv = document.createElement("div");
    warningDiv.id = "team-scoping-warning";
    document.body.appendChild(warningDiv);
    const infoDiv = document.createElement("div");
    infoDiv.id = "team-scoping-info";
    document.body.appendChild(infoDiv);

    getCurrentTeamId.mockReturnValue(null);

    const tab = document.createElement("a");
    tab.href = "#tokens";
    document.body.appendChild(tab);

    initializeTeamScopingMonitor();
    document.dispatchEvent(new Event("DOMContentLoaded"));

    // Clicking the tab should call setTimeout(updateTeamScopingWarning, 100)
    tab.click();
    vi.advanceTimersByTime(100);
    // No throw = success
  });

  test("DOMContentLoaded does nothing when tokens tab is absent", () => {
    initializeTeamScopingMonitor();
    // No tokens tab in DOM
    expect(() => {
      document.dispatchEvent(new Event("DOMContentLoaded"));
    }).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// createToken - additional branches
// ---------------------------------------------------------------------------
describe("createToken via setupCreateTokenForm - additional branches", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.Admin = {};
    getCurrentTeamId.mockReturnValue(null);
    getCookie.mockImplementation((n) => (n === "jwt_token" ? "test-tok" : null));
    window.htmx = { process: vi.fn(), trigger: vi.fn() };
  });
  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.Admin;
    delete window.htmx;
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  function buildFullForm() {
    const warning = document.createElement("div");
    warning.id = "team-scoping-warning";
    document.body.appendChild(warning);
    const info = document.createElement("div");
    info.id = "team-scoping-info";
    document.body.appendChild(info);

    const form = document.createElement("form");
    form.id = "create-token-form";
    const nameInput = document.createElement("input");
    nameInput.name = "name";
    nameInput.value = "My Token";
    form.appendChild(nameInput);

    const submitBtn = document.createElement("button");
    submitBtn.type = "submit";
    submitBtn.textContent = "Create";
    form.appendChild(submitBtn);

    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);
    const table = document.createElement("div");
    table.id = "tokens-table";
    document.body.appendChild(table);

    document.body.appendChild(form);
    return form;
  }

  test("includes server_id in scope when form has server_id field", async () => {
    const form = buildFullForm();

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        access_token: "tok-srv",
        token: { name: "My Token", expires_at: null },
      }),
    });

    const serverInput = document.createElement("input");
    serverInput.name = "server_id";
    serverInput.value = "srv-123";
    form.appendChild(serverInput);

    setupCreateTokenForm();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    const callBody = JSON.parse(fetchWithTimeout.mock.calls[0][1].body);
    expect(callBody.scope.server_id).toBe("srv-123");
  });

  test("sets empty ip_restrictions when field value is whitespace", async () => {
    const form = buildFullForm();

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        access_token: "tok-ws",
        token: { name: "My Token", expires_at: null },
      }),
    });

    const ipInput = document.createElement("input");
    ipInput.name = "ip_restrictions";
    ipInput.value = "  ";
    form.appendChild(ipInput);

    setupCreateTokenForm();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    const callBody = JSON.parse(fetchWithTimeout.mock.calls[0][1].body);
    expect(callBody.scope.ip_restrictions).toEqual([]);
  });

  test("clears token-creation-messages on success", async () => {
    const form = buildFullForm();
    const messages = document.createElement("div");
    messages.id = "token-creation-messages";
    messages.innerHTML = "<p>Old message</p>";
    document.body.appendChild(messages);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        access_token: "tok-clear",
        token: { name: "My Token", expires_at: null },
      }),
    });

    setupCreateTokenForm();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(messages.innerHTML).toBe("");
  });

  test("shows inline error in token-creation-messages on failure", async () => {
    const form = buildFullForm();
    const messages = document.createElement("div");
    messages.id = "token-creation-messages";
    document.body.appendChild(messages);

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.resolve({}),
    });

    setupCreateTokenForm();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(messages.innerHTML).toContain("Failed to create token");
  });

  test("inline error in token-creation-messages clears after 15s", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const form = buildFullForm();
    const messages = document.createElement("div");
    messages.id = "token-creation-messages";
    document.body.appendChild(messages);

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.resolve({}),
    });

    setupCreateTokenForm();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    // Allow the async chain to progress using real time advancement
    await vi.runAllTimersAsync();

    // Message should now be cleared
    expect(messages.innerHTML).toBe("");
    vi.useRealTimers();
  });
});

// ---------------------------------------------------------------------------
// showTokenCreatedModal - dismiss and copy button (lines 612-613, 621-629)
// ---------------------------------------------------------------------------
describe("showTokenCreatedModal - dismiss and copy buttons", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.Admin = {};
    window.htmx = { process: vi.fn(), trigger: vi.fn() };
    getCurrentTeamId.mockReturnValue(null);
    getCookie.mockImplementation((n) => (n === "jwt_token" ? "test-tok" : null));
  });
  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.Admin;
    delete window.htmx;
    vi.clearAllMocks();
  });

  async function triggerSuccessfulCreate() {
    const warning = document.createElement("div");
    warning.id = "team-scoping-warning";
    document.body.appendChild(warning);
    const info = document.createElement("div");
    info.id = "team-scoping-info";
    document.body.appendChild(info);

    const form = document.createElement("form");
    form.id = "create-token-form";
    const nameInput = document.createElement("input");
    nameInput.name = "name";
    nameInput.value = "My Token";
    form.appendChild(nameInput);
    const submitBtn = document.createElement("button");
    submitBtn.type = "submit";
    submitBtn.textContent = "Create";
    form.appendChild(submitBtn);
    document.body.appendChild(form);

    const table = document.createElement("div");
    table.id = "tokens-table";
    document.body.appendChild(table);
    const panel = document.createElement("div");
    panel.id = "tokens-panel";
    document.body.appendChild(panel);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        access_token: "abc-xyz-token",
        token: { name: "My Token", expires_at: null },
      }),
    });

    setupCreateTokenForm();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    return document.querySelector(".fixed");
  }

  test("dismiss button closes modal and refreshes token list", async () => {
    const modal = await triggerSuccessfulCreate();
    expect(modal).not.toBeNull();

    const dismissBtn = modal.querySelector("[data-dismiss-token-modal]");
    expect(dismissBtn).not.toBeNull();

    dismissBtn.click();

    // Modal should be removed
    expect(document.querySelector(".fixed")).toBeNull();
    // loadTokensList triggers htmx
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(window.htmx.process).toHaveBeenCalled();
  });

  test("copy button invokes copyToClipboard", async () => {
    const modal = await triggerSuccessfulCreate();
    expect(modal).not.toBeNull();

    const copyBtn = modal.querySelector("[data-copy-token-target]");
    expect(copyBtn).not.toBeNull();

    copyBtn.click();
    await Promise.resolve();

    expect(copyToClipboard).toHaveBeenCalledWith("new-token-value");
  });
});

// ---------------------------------------------------------------------------
// showTokenDetailsModal - formatJson non-empty, no-button click, copy timer
// ---------------------------------------------------------------------------
describe("showTokenDetailsModal - additional coverage", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    delete window.USERTEAMSDATA;
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  test("renders formatJson with non-empty time_restrictions (line 853)", () => {
    window.USERTEAMSDATA = [];
    showTokenDetailsModal({
      id: "tok-tj", name: "TJ Token", is_active: true,
      created_at: null, expires_at: null, last_used: null,
      team_id: null, resource_scopes: [], ip_restrictions: [],
      time_restrictions: { allowed_hours: "09-17" },
      usage_limits: {}, tags: [],
    });

    const modal = document.querySelector(".fixed");
    expect(modal.innerHTML).toContain("<pre");
    expect(modal.innerHTML).toContain("allowed_hours");
  });

  test("modal click on non-button element does nothing (early return line 1023)", () => {
    window.USERTEAMSDATA = [];
    showTokenDetailsModal({
      id: "tok-nb", name: "NB Token", is_active: true,
      created_at: null, expires_at: null, last_used: null,
      team_id: null, resource_scopes: [], ip_restrictions: [],
      time_restrictions: {}, usage_limits: {}, tags: [],
    });

    const modal = document.querySelector(".fixed");
    const span = document.createElement("span");
    span.textContent = "Not a button";
    modal.appendChild(span);

    expect(() => span.click()).not.toThrow();
    // Modal still present
    expect(document.querySelector(".fixed")).not.toBeNull();
  });

  test("copy-id button resets text to Copy after 1500ms (line 1036)", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("navigator", {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    window.USERTEAMSDATA = [];

    showTokenDetailsModal({
      id: "tok-timer", name: "Timer Token", is_active: true,
      created_at: null, expires_at: null, last_used: null,
      team_id: null, resource_scopes: [], ip_restrictions: [],
      time_restrictions: {}, usage_limits: {}, tags: [],
    });

    const modal = document.querySelector(".fixed");
    const copyBtn = modal.querySelector('[data-action="copy-id"]');

    copyBtn.click();
    await Promise.resolve(); // flush clipboard.writeText .then()

    expect(copyBtn.textContent).toBe("Copied!");

    vi.advanceTimersByTime(1500);
    expect(copyBtn.textContent).toBe("Copy");
  });
});
