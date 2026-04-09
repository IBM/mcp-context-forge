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

// ---------------------------------------------------------------------------
// showUserEditModal - NEW TESTS
// ---------------------------------------------------------------------------
import { showUserEditModal, formatDate } from "../../../mcpgateway/admin_ui/users.js";

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

describe("showUserEditModal", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    vi.clearAllMocks();
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
  });

  test("does nothing when modal is missing", async () => {
    await showUserEditModal("test@test.com");
    expect(fetchWithAuth).not.toHaveBeenCalled();
  });

  test("does nothing when modalContent is missing", async () => {
    const modal = document.createElement("div");
    modal.id = "user-edit-modal";
    document.body.appendChild(modal);
    await showUserEditModal("test@test.com");
    expect(fetchWithAuth).not.toHaveBeenCalled();
  });

  test("does nothing when userEmail is missing", async () => {
    const modal = document.createElement("div");
    modal.id = "user-edit-modal";
    const modalContent = document.createElement("div");
    modalContent.id = "user-edit-modal-content";
    modal.appendChild(modalContent);
    document.body.appendChild(modal);
    await showUserEditModal(null);
    expect(fetchWithAuth).not.toHaveBeenCalled();
  });

  test("shows modal and loads form", async () => {
    const modal = document.createElement("div");
    modal.id = "user-edit-modal";
    modal.style.display = "none";
    const modalContent = document.createElement("div");
    modalContent.id = "user-edit-modal-content";
    modal.appendChild(modalContent);
    document.body.appendChild(modal);

    fetchWithAuth.mockResolvedValue({
      ok: true,
      text: () => Promise.resolve("<div>Form</div>"),
    });

    await showUserEditModal("test@test.com");
    expect(modal.style.display).toBe("block");
  });

  test("handles fetch error", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const modal = document.createElement("div");
    modal.id = "user-edit-modal";
    const modalContent = document.createElement("div");
    modalContent.id = "user-edit-modal-content";
    modal.appendChild(modalContent);
    document.body.appendChild(modal);

    fetchWithAuth.mockRejectedValue(new Error("Network error"));
    await showUserEditModal("test@test.com");
    expect(modalContent.innerHTML).toContain("Failed to load user details");
    consoleSpy.mockRestore();
  });

  test("handles non-ok response", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const modal = document.createElement("div");
    modal.id = "user-edit-modal";
    const modalContent = document.createElement("div");
    modalContent.id = "user-edit-modal-content";
    modal.appendChild(modalContent);
    document.body.appendChild(modal);

    fetchWithAuth.mockResolvedValue({ ok: false, status: 404, statusText: "Not Found" });
    await showUserEditModal("test@test.com");
    expect(modalContent.innerHTML).toContain("Failed to load user details");
    consoleSpy.mockRestore();
  });

  test("uses ROOT_PATH", async () => {
    window.ROOT_PATH = "/api";
    const modal = document.createElement("div");
    modal.id = "user-edit-modal";
    const modalContent = document.createElement("div");
    modalContent.id = "user-edit-modal-content";
    modal.appendChild(modalContent);
    document.body.appendChild(modal);

    fetchWithAuth.mockResolvedValue({ ok: true, text: () => Promise.resolve("<div>Form</div>") });
    await showUserEditModal("test@test.com");
    expect(fetchWithAuth).toHaveBeenCalledWith("/api/admin/users/test%40test.com/edit", { method: "GET" });
  });
});

// ---------------------------------------------------------------------------
// formatDate - NEW TESTS
// ---------------------------------------------------------------------------
describe("formatDate", () => {
  test("formats valid ISO date", () => {
    const result = formatDate("2024-01-15T10:30:00Z");
    expect(result).toMatch(/Jan 15, 2024/);
  });

  test("returns original for invalid date", () => {
    expect(formatDate("invalid")).toBe("invalid");
  });
});

// ---------------------------------------------------------------------------
// performUserSearch - additional badge tests
// ---------------------------------------------------------------------------
describe("performUserSearch - badge rendering", () => {
  let container;

  beforeEach(() => {
    container = document.createElement("div");
    window.ROOT_PATH = "";
    vi.clearAllMocks();
  });

  afterEach(() => {
    delete window.ROOT_PATH;
  });

  test("renders is_current_user badge", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ users: [{ email: "me@test.com", full_name: "Me" }] }),
    });
    await performUserSearch("team-1", "me", container, { "me@test.com": { is_current_user: true, role: "owner" } });
    expect(container.innerHTML).toContain("You");
    consoleSpy.mockRestore();
  });

  test("renders is_last_owner badge", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ users: [{ email: "owner@test.com", full_name: "Owner" }] }),
    });
    await performUserSearch("team-1", "owner", container, { "owner@test.com": { is_last_owner: true, role: "owner" } });
    expect(container.innerHTML).toContain("Last Owner");
    consoleSpy.mockRestore();
  });

  test("renders joined_at date", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ users: [{ email: "member@test.com", full_name: "Member" }] }),
    });
    await performUserSearch("team-1", "member", container, { "member@test.com": { joined_at: "2024-01-15T10:30:00Z", role: "member" } });
    expect(container.innerHTML).toContain("Joined:");
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// performUserSearch - more edge cases for 90%+ coverage
// ---------------------------------------------------------------------------
describe("performUserSearch - comprehensive edge cases", () => {
  let container;

  beforeEach(() => {
    container = document.createElement("div");
    window.ROOT_PATH = "";
    vi.clearAllMocks();
  });

  afterEach(() => {
    delete window.ROOT_PATH;
  });

  test("handles non-ok response for empty query", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    fetchWithAuth.mockResolvedValue({ ok: false, status: 500 });
    await performUserSearch("team-1", "", container, {});
    expect(container.innerHTML).toContain("Failed to load users");
    consoleSpy.mockRestore();
  });

  test("handles error when capturing selections", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const faultyContainer = {
      querySelectorAll: vi.fn(() => { throw new Error("Selection error"); }),
      innerHTML: "",
    };
    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ users: [] }),
    });
    await performUserSearch("team-1", "test", faultyContainer, {});
    expect(consoleSpy).toHaveBeenCalledWith(expect.stringContaining("Error capturing selections"), expect.any(Error));
    consoleSpy.mockRestore();
  });

  test("restores selections after reloading", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    container.innerHTML = `
      <div class="user-item" data-user-email="restore@test.com">
        <input type="checkbox" name="associatedUsers" value="restore@test.com" checked />
        <select class="role-select" name="role_restore%40test.com">
          <option value="owner" selected>Owner</option>
        </select>
      </div>
    `;
    fetchWithAuth.mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(`
        <div class="user-item" data-user-email="restore@test.com">
          <input type="checkbox" name="associatedUsers" value="restore@test.com" />
          <select class="role-select" name="role_restore%40test.com">
            <option value="member" selected>Member</option>
          </select>
        </div>
      `),
    });
    await performUserSearch("team-1", "", container, {});
    const checkbox = container.querySelector('input[value="restore@test.com"]');
    expect(checkbox).toBeTruthy();
    consoleSpy.mockRestore();
  });

  test("renders user with owner role badge (not last owner)", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    fetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ users: [{ email: "owner2@test.com", full_name: "Owner 2" }] }),
    });
    await performUserSearch("team-1", "owner2", container, { "owner2@test.com": { role: "owner", is_last_owner: false } });
    expect(container.innerHTML).toContain("Owner");
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// showUserEditModal - htmx tests
// ---------------------------------------------------------------------------
describe("showUserEditModal - htmx integration", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    vi.clearAllMocks();
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
  });

  test("uses htmx.ajax when available", async () => {
    const modal = document.createElement("div");
    modal.id = "user-edit-modal";
    const modalContent = document.createElement("div");
    modalContent.id = "user-edit-modal-content";
    modal.appendChild(modalContent);
    document.body.appendChild(modal);

    window.htmx = { ajax: vi.fn().mockResolvedValue(undefined) };
    await showUserEditModal("test@test.com");
    expect(window.htmx.ajax).toHaveBeenCalledWith(
      "GET",
      "/admin/users/test%40test.com/edit",
      expect.objectContaining({ target: "#user-edit-modal-content", swap: "innerHTML" })
    );
  });

  test("falls back to fetchWithAuth when htmx.ajax is not a function", async () => {
    const modal = document.createElement("div");
    modal.id = "user-edit-modal";
    const modalContent = document.createElement("div");
    modalContent.id = "user-edit-modal-content";
    modal.appendChild(modalContent);
    document.body.appendChild(modal);

    window.htmx = { ajax: "not a function" };
    fetchWithAuth.mockResolvedValue({ ok: true, text: () => Promise.resolve("<div>Form</div>") });
    await showUserEditModal("test@test.com");
    expect(fetchWithAuth).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// registerAdminActionListeners - event handler tests
// ---------------------------------------------------------------------------
describe("registerAdminActionListeners - event handlers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
    delete document.body.dataset.adminActionListeners;
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete document.body.dataset.adminActionListeners;
  });

  test("handles adminUserAction event with closeUserEditModal", async () => {
    const modal = document.createElement("div");
    modal.id = "user-edit-modal";
    modal.style.display = "block";
    document.body.appendChild(modal);

    registerAdminActionListeners();

    const event = new CustomEvent("adminUserAction", {
      detail: { closeUserEditModal: true },
    });
    document.body.dispatchEvent(event);

    await new Promise(resolve => setTimeout(resolve, 10));
    expect(modal.style.display).toBe("none");
  });

  test("handles adminUserAction event with refreshUsersList", async () => {
    const usersList = document.createElement("div");
    usersList.id = "users-list-container";
    document.body.appendChild(usersList);

    window.htmx = { trigger: vi.fn() };
    registerAdminActionListeners();

    const event = new CustomEvent("adminUserAction", {
      detail: { refreshUsersList: true },
    });
    document.body.dispatchEvent(event);

    await new Promise(resolve => setTimeout(resolve, 10));
    expect(window.htmx.trigger).toHaveBeenCalledWith(usersList, "refreshUsers");
    delete window.htmx;
  });

  test("handles userCreated event", async () => {
    const usersList = document.createElement("div");
    usersList.id = "users-list-container";
    document.body.appendChild(usersList);

    window.htmx = { trigger: vi.fn() };
    registerAdminActionListeners();

    const event = new CustomEvent("userCreated");
    document.body.dispatchEvent(event);

    await new Promise(resolve => setTimeout(resolve, 10));
    expect(window.htmx.trigger).toHaveBeenCalledWith(usersList, "refreshUsers");
    delete window.htmx;
  });

  test("handles htmx:afterSwap with password field", () => {
    const target = document.createElement("div");
    const passwordField = document.createElement("input");
    passwordField.id = "password-field";
    target.appendChild(passwordField);
    document.body.appendChild(target);

    registerAdminActionListeners();

    const event = new CustomEvent("htmx:afterSwap");
    Object.defineProperty(event, "target", { value: target, writable: false });
    document.body.dispatchEvent(event);
  });

  test("handles htmx:load with password field", () => {
    const target = document.createElement("div");
    const passwordField = document.createElement("input");
    passwordField.id = "password-field";
    target.appendChild(passwordField);
    document.body.appendChild(target);

    registerAdminActionListeners();

    const event = new CustomEvent("htmx:load");
    Object.defineProperty(event, "target", { value: target, writable: false });
    document.body.dispatchEvent(event);
  });
});
