/**
 * Unit tests for users.js module
 * Tests: hideUserEditModal, performUserSearch, registerAdminActionListeners,
 *        initializePermissionsPanel
 * (formatDate is already tested in tests/js/)
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import {
  hideUserEditModal,
  performUserSearch,
  registerAdminActionListeners,
  initializePermissionsPanel,
} from "../../../mcpgateway/admin_ui/users.js";
import { fetchWithAuth } from "../../../mcpgateway/admin_ui/tokens.js";

// Mock dependencies
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
}));
vi.mock("../../../mcpgateway/admin_ui/teams.js", () => ({
  dedupeSelectorItems: vi.fn(),
  extractTeamId: vi.fn(),
  handleAdminTeamAction: vi.fn(),
  initializeAddMembersForms: vi.fn(),
  initializePasswordValidation: vi.fn(),
  updateAddMembersCount: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  fetchWithAuth: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));

// ---------------------------------------------------------------------------
// hideUserEditModal
// ---------------------------------------------------------------------------
describe("hideUserEditModal", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("hides the modal when it exists", () => {
    const modal = document.createElement("div");
    modal.id = "user-edit-modal";
    modal.style.display = "block";
    document.body.appendChild(modal);

    hideUserEditModal();

    expect(modal.style.display).toBe("none");
    expect(modal.classList.contains("hidden")).toBe(true);
  });

  test("does nothing when modal does not exist", () => {
    expect(() => hideUserEditModal()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// performUserSearch
// ---------------------------------------------------------------------------
describe("performUserSearch", () => {
  let container;

  beforeEach(() => {
    container = document.createElement("div");
    window.ROOT_PATH = "";
    vi.clearAllMocks();
  });

  afterEach(() => {
    delete window.ROOT_PATH;
  });

  test("shows loading state and loads default list for empty query", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    fetchWithAuth.mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('<div class="user-item">user1</div>'),
    });

    await performUserSearch("team-1", "", container, {});

    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("/admin/users/partial")
    );
    consoleSpy.mockRestore();
  });

  test("shows error on fetch failure for empty query", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    fetchWithAuth.mockRejectedValue(new Error("Network error"));

    await performUserSearch("team-1", "", container, {});

    expect(container.innerHTML).toContain("Error loading users");
    consoleSpy.mockRestore();
  });

  test("searches users via API for non-empty query", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          users: [
            { email: "test@test.com", full_name: "Test User" },
          ],
        }),
    });

    await performUserSearch("team-1", "test", container, {});

    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("/admin/users/search?q=test")
    );
    expect(container.innerHTML).toContain("test@test.com");
    consoleSpy.mockRestore();
  });

  test("shows no users found when search returns empty", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ users: [] }),
    });

    await performUserSearch("team-1", "nonexistent", container, {});

    expect(container.innerHTML).toContain("No users found");
    consoleSpy.mockRestore();
  });

  test("shows error when search API fails", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    fetchWithAuth.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
    });

    await performUserSearch("team-1", "query", container, {});

    expect(container.innerHTML).toContain("Error searching users");
    consoleSpy.mockRestore();
  });

  test("preserves existing selections during search", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    // Pre-populate container with a checked user item
    container.innerHTML = `
      <div class="user-item" data-user-email="old@test.com">
        <input type="checkbox" name="associatedUsers" checked />
        <select class="role-select"><option value="owner" selected>Owner</option></select>
      </div>
    `;

    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          users: [
            { email: "old@test.com", full_name: "Old User" },
          ],
        }),
    });

    await performUserSearch("team-1", "old", container, {
      "old@test.com": { role: "owner" },
    });

    // The search result should show the user with their previous selections preserved
    expect(container.innerHTML).toContain("old@test.com");
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// registerAdminActionListeners
// ---------------------------------------------------------------------------
describe("registerAdminActionListeners", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    delete document.body.dataset.adminActionListeners;
  });

  test("registers event listeners on document.body", () => {
    const spy = vi.spyOn(document.body, "addEventListener");
    registerAdminActionListeners();

    const eventNames = spy.mock.calls.map((c) => c[0]);
    expect(eventNames).toContain("adminTeamAction");
    expect(eventNames).toContain("adminUserAction");
    expect(eventNames).toContain("userCreated");
    expect(eventNames).toContain("htmx:afterSwap");
    expect(eventNames).toContain("htmx:load");
    spy.mockRestore();
  });

  test("sets guard attribute to prevent duplicate registration", () => {
    registerAdminActionListeners();
    expect(document.body.dataset.adminActionListeners).toBe("1");
  });

  test("does not register twice when guard is set", () => {
    document.body.dataset.adminActionListeners = "1";
    const spy = vi.spyOn(document.body, "addEventListener");

    registerAdminActionListeners();
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// initializePermissionsPanel
// ---------------------------------------------------------------------------
describe("initializePermissionsPanel", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    delete window.USER_TEAMS;
  });

  test("populates members list when USER_TEAMS is available", () => {
    window.USER_TEAMS = [{ id: "t1", name: "Team1" }];

    const members = document.createElement("div");
    members.id = "team-members-list";
    document.body.appendChild(members);

    const roles = document.createElement("div");
    roles.id = "role-assignments-list";
    document.body.appendChild(roles);

    initializePermissionsPanel();

    expect(members.innerHTML).toContain("Teams Management tab");
    expect(roles.innerHTML).toContain("Teams Management tab");
  });

  test("does nothing when USER_TEAMS is empty", () => {
    window.USER_TEAMS = [];
    const members = document.createElement("div");
    members.id = "team-members-list";
    members.innerHTML = "original";
    document.body.appendChild(members);

    initializePermissionsPanel();
    expect(members.innerHTML).toBe("original");
  });

  test("does nothing when USER_TEAMS is not set", () => {
    expect(() => initializePermissionsPanel()).not.toThrow();
  });
});
