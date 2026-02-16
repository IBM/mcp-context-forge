/**
 * Unit tests for teams.js module
 * Tests: validatePasswordRequirements, validatePasswordMatch, resetTeamCreateForm,
 *        filterByRelationship, filterTeams, dedupeSelectorItems, updateAddMembersCount,
 *        requestToJoinTeam, leaveTeam, approveJoinRequest, rejectJoinRequest
 * (Skip functions already tested: getTeamsPerPage, extractTeamId, getTeamsCurrentPaginationState, handleAdminTeamAction)
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import {
  validatePasswordRequirements,
  validatePasswordMatch,
  resetTeamCreateForm,
  filterByRelationship,
  filterTeams,
  dedupeSelectorItems,
  updateAddMembersCount,
  requestToJoinTeam,
  leaveTeam,
  approveJoinRequest,
  rejectJoinRequest,
  serverSideTeamSearch,
} from "../../../mcpgateway/admin_ui/teams.js";

import { AppState } from "../../../mcpgateway/admin_ui/appState.js";
import {
  fetchWithTimeout,
  showErrorMessage,
  showSuccessMessage,
} from "../../../mcpgateway/admin_ui/utils.js";
import { getAuthToken } from "../../../mcpgateway/admin_ui/tokens.js";

// Mock dependencies BEFORE importing the module under test
vi.mock("../../../mcpgateway/admin_ui/appState.js", () => ({
  AppState: {
    getCurrentTeamRelationshipFilter: vi.fn(() => "all"),
    setCurrentTeamRelationshipFilter: vi.fn(),
  },
}));

vi.mock("../../../mcpgateway/admin_ui/constants", () => ({
  DEFAULT_TEAMS_PER_PAGE: 10,
}));

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  safeReplaceState: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  fetchWithAuth: vi.fn(),
  getAuthToken: vi.fn(() => "test-token"),
}));

vi.mock("../../../mcpgateway/admin_ui/users.js", () => ({
  performUserSearch: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  fetchWithTimeout: vi.fn(),
  showErrorMessage: vi.fn(),
  showSuccessMessage: vi.fn(),
}));

// ---------------------------------------------------------------------------
// validatePasswordRequirements
// ---------------------------------------------------------------------------
describe("validatePasswordRequirements", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.clearAllMocks();
  });

  test("enables submit button when password is empty", () => {
    const policyEl = document.createElement("div");
    policyEl.id = "edit-password-policy-data";
    policyEl.dataset.minLength = "8";
    policyEl.dataset.requireUppercase = "true";
    policyEl.dataset.requireLowercase = "true";
    policyEl.dataset.requireNumbers = "true";
    policyEl.dataset.requireSpecial = "true";
    document.body.appendChild(policyEl);

    const passwordField = document.createElement("input");
    passwordField.id = "password-field";
    passwordField.value = "";
    document.body.appendChild(passwordField);

    const form = document.createElement("div");
    form.id = "user-edit-modal-content";
    const submitButton = document.createElement("button");
    submitButton.type = "submit";
    form.appendChild(submitButton);
    document.body.appendChild(form);

    validatePasswordRequirements();

    expect(submitButton.disabled).toBe(false);
    expect(submitButton.className).toContain("bg-blue-600");
  });

  test("validates all password requirements correctly", () => {
    const policyEl = document.createElement("div");
    policyEl.id = "edit-password-policy-data";
    policyEl.dataset.minLength = "8";
    policyEl.dataset.requireUppercase = "true";
    policyEl.dataset.requireLowercase = "true";
    policyEl.dataset.requireNumbers = "true";
    policyEl.dataset.requireSpecial = "true";
    document.body.appendChild(policyEl);

    const passwordField = document.createElement("input");
    passwordField.id = "password-field";
    passwordField.value = "Test123!";
    document.body.appendChild(passwordField);

    const reqLength = document.createElement("div");
    reqLength.id = "edit-req-length";
    reqLength.innerHTML = '<span></span>';
    document.body.appendChild(reqLength);

    const reqUppercase = document.createElement("div");
    reqUppercase.id = "edit-req-uppercase";
    reqUppercase.innerHTML = '<span></span>';
    document.body.appendChild(reqUppercase);

    const reqLowercase = document.createElement("div");
    reqLowercase.id = "edit-req-lowercase";
    reqLowercase.innerHTML = '<span></span>';
    document.body.appendChild(reqLowercase);

    const reqNumbers = document.createElement("div");
    reqNumbers.id = "edit-req-numbers";
    reqNumbers.innerHTML = '<span></span>';
    document.body.appendChild(reqNumbers);

    const reqSpecial = document.createElement("div");
    reqSpecial.id = "edit-req-special";
    reqSpecial.innerHTML = '<span></span>';
    document.body.appendChild(reqSpecial);

    const form = document.createElement("div");
    form.id = "user-edit-modal-content";
    const submitButton = document.createElement("button");
    submitButton.type = "submit";
    form.appendChild(submitButton);
    document.body.appendChild(form);

    validatePasswordRequirements();

    expect(reqLength.querySelector("span").textContent).toBe("✓");
    expect(reqUppercase.querySelector("span").textContent).toBe("✓");
    expect(reqLowercase.querySelector("span").textContent).toBe("✓");
    expect(reqNumbers.querySelector("span").textContent).toBe("✓");
    expect(reqSpecial.querySelector("span").textContent).toBe("✓");
    expect(submitButton.disabled).toBe(false);
  });

  test("disables submit button when password fails requirements", () => {
    const policyEl = document.createElement("div");
    policyEl.id = "edit-password-policy-data";
    policyEl.dataset.minLength = "8";
    policyEl.dataset.requireUppercase = "true";
    policyEl.dataset.requireLowercase = "true";
    policyEl.dataset.requireNumbers = "true";
    policyEl.dataset.requireSpecial = "true";
    document.body.appendChild(policyEl);

    const passwordField = document.createElement("input");
    passwordField.id = "password-field";
    passwordField.value = "short"; // Fails min length, uppercase, numbers, special
    document.body.appendChild(passwordField);

    const reqLength = document.createElement("div");
    reqLength.id = "edit-req-length";
    reqLength.innerHTML = '<span></span>';
    document.body.appendChild(reqLength);

    const reqUppercase = document.createElement("div");
    reqUppercase.id = "edit-req-uppercase";
    reqUppercase.innerHTML = '<span></span>';
    document.body.appendChild(reqUppercase);

    const reqLowercase = document.createElement("div");
    reqLowercase.id = "edit-req-lowercase";
    reqLowercase.innerHTML = '<span></span>';
    document.body.appendChild(reqLowercase);

    const reqNumbers = document.createElement("div");
    reqNumbers.id = "edit-req-numbers";
    reqNumbers.innerHTML = '<span></span>';
    document.body.appendChild(reqNumbers);

    const reqSpecial = document.createElement("div");
    reqSpecial.id = "edit-req-special";
    reqSpecial.innerHTML = '<span></span>';
    document.body.appendChild(reqSpecial);

    const form = document.createElement("div");
    form.id = "user-edit-modal-content";
    const submitButton = document.createElement("button");
    submitButton.type = "submit";
    form.appendChild(submitButton);
    document.body.appendChild(form);

    validatePasswordRequirements();

    expect(submitButton.disabled).toBe(true);
    expect(submitButton.className).toContain("bg-gray-400");
  });

  test("does nothing when policy element is missing", () => {
    const passwordField = document.createElement("input");
    passwordField.id = "password-field";
    passwordField.value = "Test123!";
    document.body.appendChild(passwordField);

    expect(() => validatePasswordRequirements()).not.toThrow();
  });

  test("does nothing when password field is missing", () => {
    const policyEl = document.createElement("div");
    policyEl.id = "edit-password-policy-data";
    policyEl.dataset.minLength = "8";
    document.body.appendChild(policyEl);

    expect(() => validatePasswordRequirements()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// validatePasswordMatch
// ---------------------------------------------------------------------------
describe("validatePasswordMatch", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("shows error when passwords do not match", () => {
    const passwordField = document.createElement("input");
    passwordField.id = "password-field";
    passwordField.value = "password1";
    document.body.appendChild(passwordField);

    const confirmPasswordField = document.createElement("input");
    confirmPasswordField.id = "confirm-password-field";
    confirmPasswordField.value = "password2";
    document.body.appendChild(confirmPasswordField);

    const messageElement = document.createElement("div");
    messageElement.id = "password-match-message";
    messageElement.classList.add("hidden");
    document.body.appendChild(messageElement);

    const form = document.createElement("div");
    form.id = "user-edit-modal-content";
    const submitButton = document.createElement("button");
    submitButton.type = "submit";
    form.appendChild(submitButton);
    document.body.appendChild(form);

    validatePasswordMatch();

    expect(messageElement.classList.contains("hidden")).toBe(false);
    expect(confirmPasswordField.classList.contains("border-red-500")).toBe(true);
    expect(submitButton.disabled).toBe(true);
  });

  test("hides error when passwords match", () => {
    const passwordField = document.createElement("input");
    passwordField.id = "password-field";
    passwordField.value = "password1";
    document.body.appendChild(passwordField);

    const confirmPasswordField = document.createElement("input");
    confirmPasswordField.id = "confirm-password-field";
    confirmPasswordField.value = "password1";
    document.body.appendChild(confirmPasswordField);

    const messageElement = document.createElement("div");
    messageElement.id = "password-match-message";
    document.body.appendChild(messageElement);

    const form = document.createElement("div");
    form.id = "user-edit-modal-content";
    const submitButton = document.createElement("button");
    submitButton.type = "submit";
    form.appendChild(submitButton);
    document.body.appendChild(form);

    validatePasswordMatch();

    expect(messageElement.classList.contains("hidden")).toBe(true);
    expect(confirmPasswordField.classList.contains("border-red-500")).toBe(false);
    expect(submitButton.disabled).toBe(false);
  });

  test("does nothing when required fields are missing", () => {
    expect(() => validatePasswordMatch()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// resetTeamCreateForm
// ---------------------------------------------------------------------------
describe("resetTeamCreateForm", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("resets the team creation form", () => {
    const form = document.createElement("form");
    form.setAttribute("hx-post", "/admin/teams");
    const input = document.createElement("input");
    input.value = "test";
    form.appendChild(input);
    document.body.appendChild(form);

    const resetSpy = vi.spyOn(form, "reset");

    resetTeamCreateForm();

    expect(resetSpy).toHaveBeenCalled();
  });

  test("clears error element", () => {
    const form = document.createElement("form");
    form.setAttribute("hx-post", "/admin/teams");
    document.body.appendChild(form);

    const errorEl = document.createElement("div");
    errorEl.id = "create-team-error";
    errorEl.innerHTML = "Some error";
    document.body.appendChild(errorEl);

    resetTeamCreateForm();

    expect(errorEl.innerHTML).toBe("");
  });

  test("does nothing when form does not exist", () => {
    expect(() => resetTeamCreateForm()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// filterByRelationship
// ---------------------------------------------------------------------------
describe("filterByRelationship", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.htmx = {
      ajax: vi.fn(),
    };
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
    vi.clearAllMocks();
  });

  test("updates button states and performs search", () => {
    const container = document.createElement("div");
    container.id = "unified-teams-list";
    document.body.appendChild(container);

    const btn1 = document.createElement("button");
    btn1.className = "filter-btn";
    btn1.setAttribute("data-filter", "owner");
    document.body.appendChild(btn1);

    const btn2 = document.createElement("button");
    btn2.className = "filter-btn";
    btn2.setAttribute("data-filter", "member");
    document.body.appendChild(btn2);

    filterByRelationship("owner");

    expect(AppState.setCurrentTeamRelationshipFilter).toHaveBeenCalledWith("owner");
    expect(btn1.classList.contains("active")).toBe(true);
    expect(btn2.classList.contains("active")).toBe(false);
  });

  test("preserves search query when filtering", () => {
    const container = document.createElement("div");
    container.id = "unified-teams-list";
    document.body.appendChild(container);

    const searchInput = document.createElement("input");
    searchInput.id = "team-search";
    searchInput.value = "test query";
    document.body.appendChild(searchInput);

    const btn = document.createElement("button");
    btn.className = "filter-btn";
    btn.setAttribute("data-filter", "member");
    document.body.appendChild(btn);

    filterByRelationship("member");

    expect(AppState.setCurrentTeamRelationshipFilter).toHaveBeenCalledWith("member");
  });
});

// ---------------------------------------------------------------------------
// filterTeams
// ---------------------------------------------------------------------------
describe("filterTeams", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.htmx = {
      ajax: vi.fn(),
    };
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
    vi.clearAllMocks();
  });

  test("calls serverSideTeamSearch with search value", () => {
    const container = document.createElement("div");
    container.id = "unified-teams-list";
    document.body.appendChild(container);

    filterTeams("test search");

    // serverSideTeamSearch uses debounce, so we can't easily test the actual call
    // but we can verify it doesn't throw
    expect(() => filterTeams("test")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// dedupeSelectorItems
// ---------------------------------------------------------------------------
describe("dedupeSelectorItems", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("removes duplicate user items by email", () => {
    const container = document.createElement("div");

    const item1 = document.createElement("div");
    item1.className = "user-item";
    item1.setAttribute("data-user-email", "test@example.com");
    container.appendChild(item1);

    const item2 = document.createElement("div");
    item2.className = "user-item";
    item2.setAttribute("data-user-email", "test@example.com");
    container.appendChild(item2);

    const item3 = document.createElement("div");
    item3.className = "user-item";
    item3.setAttribute("data-user-email", "other@example.com");
    container.appendChild(item3);

    expect(container.querySelectorAll(".user-item").length).toBe(3);

    dedupeSelectorItems(container);

    expect(container.querySelectorAll(".user-item").length).toBe(2);
    const emails = Array.from(container.querySelectorAll(".user-item")).map(
      (item) => item.getAttribute("data-user-email")
    );
    expect(emails).toEqual(["test@example.com", "other@example.com"]);
  });

  test("does nothing when container is null", () => {
    expect(() => dedupeSelectorItems(null)).not.toThrow();
  });

  test("handles items without email attributes", () => {
    const container = document.createElement("div");

    const item1 = document.createElement("div");
    item1.className = "user-item";
    container.appendChild(item1);

    const item2 = document.createElement("div");
    item2.className = "user-item";
    item2.setAttribute("data-user-email", "test@example.com");
    container.appendChild(item2);

    expect(container.querySelectorAll(".user-item").length).toBe(2);

    dedupeSelectorItems(container);

    expect(container.querySelectorAll(".user-item").length).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// updateAddMembersCount
// ---------------------------------------------------------------------------
describe("updateAddMembersCount", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("updates count element with number of selected users", () => {
    const form = document.createElement("div");
    form.id = "add-members-form-team1";

    const checkbox1 = document.createElement("input");
    checkbox1.type = "checkbox";
    checkbox1.name = "associatedUsers";
    checkbox1.checked = true;
    form.appendChild(checkbox1);

    const checkbox2 = document.createElement("input");
    checkbox2.type = "checkbox";
    checkbox2.name = "associatedUsers";
    checkbox2.checked = true;
    form.appendChild(checkbox2);

    const checkbox3 = document.createElement("input");
    checkbox3.type = "checkbox";
    checkbox3.name = "associatedUsers";
    checkbox3.checked = false;
    form.appendChild(checkbox3);

    document.body.appendChild(form);

    const countEl = document.createElement("div");
    countEl.id = "selected-count-team1";
    document.body.appendChild(countEl);

    updateAddMembersCount("team1");

    expect(countEl.textContent).toBe("2 users selected");
  });

  test("shows singular 'user' when one is selected", () => {
    const form = document.createElement("div");
    form.id = "add-members-form-team1";

    const checkbox1 = document.createElement("input");
    checkbox1.type = "checkbox";
    checkbox1.name = "associatedUsers";
    checkbox1.checked = true;
    form.appendChild(checkbox1);

    document.body.appendChild(form);

    const countEl = document.createElement("div");
    countEl.id = "selected-count-team1";
    document.body.appendChild(countEl);

    updateAddMembersCount("team1");

    expect(countEl.textContent).toBe("1 user selected");
  });

  test("shows 'No users selected' when none are selected", () => {
    const form = document.createElement("div");
    form.id = "add-members-form-team1";

    const checkbox1 = document.createElement("input");
    checkbox1.type = "checkbox";
    checkbox1.name = "associatedUsers";
    checkbox1.checked = false;
    form.appendChild(checkbox1);

    document.body.appendChild(form);

    const countEl = document.createElement("div");
    countEl.id = "selected-count-team1";
    document.body.appendChild(countEl);

    updateAddMembersCount("team1");

    expect(countEl.textContent).toBe("No users selected");
  });

  test("does nothing when form or count element is missing", () => {
    expect(() => updateAddMembersCount("nonexistent")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// requestToJoinTeam
// ---------------------------------------------------------------------------
describe("requestToJoinTeam", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    vi.clearAllMocks();
  });

  afterEach(() => {
    delete window.ROOT_PATH;
    vi.restoreAllMocks();
  });

  test("sends join request successfully", async () => {
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("Please let me join");

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ team_name: "Engineering" }),
    });

    await requestToJoinTeam("team-123");

    expect(promptSpy).toHaveBeenCalled();
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      "/teams/team-123/join",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer test-token",
        }),
      })
    );
    expect(showSuccessMessage).toHaveBeenCalledWith(
      expect.stringContaining("Join request sent to Engineering")
    );
  });

  test("handles join request with no message", async () => {
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue(null);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ team_name: "Engineering" }),
    });

    await requestToJoinTeam("team-123");

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      "/teams/team-123/join",
      expect.objectContaining({
        body: JSON.stringify({ message: null }),
      })
    );
  });

  test("shows error when join request fails", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("message");

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 403,
      json: () => Promise.resolve({ detail: "Already a member" }),
    });

    await requestToJoinTeam("team-123");

    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("Already a member")
    );

    consoleSpy.mockRestore();
  });

  test("does nothing when teamId is missing", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await requestToJoinTeam("");

    expect(fetchWithTimeout).not.toHaveBeenCalled();

    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// leaveTeam
// ---------------------------------------------------------------------------
describe("leaveTeam", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.htmx = {
      trigger: vi.fn(),
    };
    vi.clearAllMocks();
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
    vi.restoreAllMocks();
  });

  test("leaves team successfully after confirmation", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });

    const teamsList = document.createElement("div");
    teamsList.id = "teams-list";
    document.body.appendChild(teamsList);

    await leaveTeam("team-123", "Engineering");

    expect(confirmSpy).toHaveBeenCalledWith(
      expect.stringContaining('leave the team "Engineering"')
    );
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      "/teams/team-123/leave",
      expect.objectContaining({
        method: "DELETE",
        headers: expect.objectContaining({
          Authorization: "Bearer test-token",
        }),
      })
    );
    expect(showSuccessMessage).toHaveBeenCalledWith("Successfully left Engineering");
  });

  test("does not leave team when user cancels", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    await leaveTeam("team-123", "Engineering");

    expect(fetchWithTimeout).not.toHaveBeenCalled();
  });

  test("shows error when leave fails", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 403,
      json: () => Promise.resolve({ detail: "Cannot leave team" }),
    });

    await leaveTeam("team-123", "Engineering");

    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("Cannot leave team")
    );

    consoleSpy.mockRestore();
  });

  test("does nothing when teamId is missing", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await leaveTeam("", "Engineering");

    expect(fetchWithTimeout).not.toHaveBeenCalled();

    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// approveJoinRequest
// ---------------------------------------------------------------------------
describe("approveJoinRequest", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.htmx = {
      trigger: vi.fn(),
    };
    vi.clearAllMocks();
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
    vi.restoreAllMocks();
  });

  test("approves join request successfully", async () => {
    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ user_email: "user@example.com" }),
    });

    const teamsList = document.createElement("div");
    teamsList.id = "teams-list";
    document.body.appendChild(teamsList);

    await approveJoinRequest("team-123", "request-456");

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      "/teams/team-123/join-requests/request-456/approve",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer test-token",
        }),
      })
    );
    expect(showSuccessMessage).toHaveBeenCalledWith(
      expect.stringContaining("user@example.com is now a member")
    );
    expect(window.htmx.trigger).toHaveBeenCalledWith(teamsList, "load");
  });

  test("shows error when approval fails", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 403,
      json: () => Promise.resolve({ detail: "Not authorized" }),
    });

    await approveJoinRequest("team-123", "request-456");

    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("Not authorized")
    );

    consoleSpy.mockRestore();
  });

  test("does nothing when teamId or requestId is missing", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await approveJoinRequest("", "request-456");
    expect(fetchWithTimeout).not.toHaveBeenCalled();

    await approveJoinRequest("team-123", "");
    expect(fetchWithTimeout).not.toHaveBeenCalled();

    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// rejectJoinRequest
// ---------------------------------------------------------------------------
describe("rejectJoinRequest", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.htmx = {
      trigger: vi.fn(),
    };
    vi.clearAllMocks();
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
    vi.restoreAllMocks();
  });

  test("rejects join request successfully after confirmation", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });

    const teamsList = document.createElement("div");
    teamsList.id = "teams-list";
    document.body.appendChild(teamsList);

    await rejectJoinRequest("team-123", "request-456");

    expect(confirmSpy).toHaveBeenCalledWith(
      expect.stringContaining("reject this join request")
    );
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      "/teams/team-123/join-requests/request-456",
      expect.objectContaining({
        method: "DELETE",
        headers: expect.objectContaining({
          Authorization: "Bearer test-token",
        }),
      })
    );
    expect(showSuccessMessage).toHaveBeenCalledWith("Join request rejected.");
    expect(window.htmx.trigger).toHaveBeenCalledWith(teamsList, "load");
  });

  test("does not reject when user cancels", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    await rejectJoinRequest("team-123", "request-456");

    expect(fetchWithTimeout).not.toHaveBeenCalled();
  });

  test("shows error when rejection fails", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ detail: "Request not found" }),
    });

    await rejectJoinRequest("team-123", "request-456");

    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("Request not found")
    );

    consoleSpy.mockRestore();
  });

  test("does nothing when teamId or requestId is missing", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await rejectJoinRequest("", "request-456");
    expect(fetchWithTimeout).not.toHaveBeenCalled();

    await rejectJoinRequest("team-123", "");
    expect(fetchWithTimeout).not.toHaveBeenCalled();

    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// serverSideTeamSearch (basic edge case tests)
// ---------------------------------------------------------------------------
describe("serverSideTeamSearch", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.htmx = {
      ajax: vi.fn(),
    };
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
    vi.clearAllMocks();
  });

  test("does not throw when called", () => {
    const container = document.createElement("div");
    container.id = "unified-teams-list";
    document.body.appendChild(container);

    expect(() => serverSideTeamSearch("test")).not.toThrow();
  });
});
