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
} from "../../../mcpgateway/admin_ui/tokens.js";
import { getCookie, getCurrentTeamId, getCurrentTeamName, fetchWithTimeout } from "../../../mcpgateway/admin_ui/utils.js";

// Mock dependencies
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  logRestrictedContext: vi.fn(),
  parseErrorResponse: vi.fn().mockResolvedValue("mocked error"),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  fetchWithTimeout: vi.fn(),
  getCookie: vi.fn(() => null),
  getCurrentTeamId: vi.fn(() => null),
  getCurrentTeamName: vi.fn(() => null),
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
    await fetchWithAuth("/api/test", { credentials: "include" });
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
