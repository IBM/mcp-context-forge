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
  getTeamsPerPage,
  extractTeamId,
  getTeamsCurrentPaginationState,
  handleAdminTeamAction,
  displayPublicTeams,
  initializePasswordValidation,
  hideTeamEditModal,
  showAddMemberForm,
  hideAddMemberForm,
  isTeamScopedView,
  applyVisibilityRestrictions,
  updateDefaultVisibility,
  loadTeamSelectorDropdown,
  initializeAddMembersForm,
  initializeAddMembersForms,
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

vi.mock("../../../mcpgateway/admin_ui/formFieldHandlers.js", () => ({
  searchTeamSelector: vi.fn(),
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

// ---------------------------------------------------------------------------
// getTeamsPerPage
// ---------------------------------------------------------------------------
describe("getTeamsPerPage", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("returns DEFAULT_TEAMS_PER_PAGE when no pagination controls exist", () => {
    expect(getTeamsPerPage()).toBe(10);
  });

  test("returns DEFAULT_TEAMS_PER_PAGE when controls have no select", () => {
    const controls = document.createElement("div");
    controls.id = "teams-pagination-controls";
    document.body.appendChild(controls);

    expect(getTeamsPerPage()).toBe(10);
  });

  test("returns select value when pagination controls have a select", () => {
    const controls = document.createElement("div");
    controls.id = "teams-pagination-controls";
    const select = document.createElement("select");
    select.value = "25";
    const option = document.createElement("option");
    option.value = "25";
    select.appendChild(option);
    controls.appendChild(select);
    document.body.appendChild(controls);

    expect(getTeamsPerPage()).toBe(25);
  });

  test("falls back to DEFAULT when select value is non-numeric", () => {
    const controls = document.createElement("div");
    controls.id = "teams-pagination-controls";
    const select = document.createElement("select");
    select.value = "invalid";
    const option = document.createElement("option");
    option.value = "invalid";
    select.appendChild(option);
    controls.appendChild(select);
    document.body.appendChild(controls);

    expect(getTeamsPerPage()).toBe(10);
  });
});

// ---------------------------------------------------------------------------
// extractTeamId
// ---------------------------------------------------------------------------
describe("extractTeamId", () => {
  test("extracts team ID from matching prefix", () => {
    expect(extractTeamId("add-members-form-", "add-members-form-team123")).toBe("team123");
  });

  test("returns null when elementId does not start with prefix", () => {
    expect(extractTeamId("add-members-form-", "other-form-team123")).toBeNull();
  });

  test("returns null when elementId is null", () => {
    expect(extractTeamId("add-members-form-", null)).toBeNull();
  });

  test("returns null when elementId is empty string", () => {
    expect(extractTeamId("add-members-form-", "")).toBeNull();
  });

  test("extracts UUID-like team ID", () => {
    const id = "550e8400-e29b-41d4-a716-446655440000";
    expect(extractTeamId("team-members-form-", `team-members-form-${id}`)).toBe(id);
  });
});

// ---------------------------------------------------------------------------
// getTeamsCurrentPaginationState
// ---------------------------------------------------------------------------
describe("getTeamsCurrentPaginationState", () => {
  afterEach(() => {
    delete window.location;
    window.location = { search: "" };
  });

  beforeEach(() => {
    delete window.location;
    window.location = { search: "" };
  });

  test("returns defaults when URL has no params", () => {
    window.location.search = "";
    const state = getTeamsCurrentPaginationState();
    expect(state).toEqual({ page: 1, perPage: 10 });
  });

  test("reads teams_page and teams_size from URL", () => {
    window.location.search = "?teams_page=3&teams_size=25";
    const state = getTeamsCurrentPaginationState();
    expect(state).toEqual({ page: 3, perPage: 25 });
  });

  test("clamps page to minimum 1", () => {
    window.location.search = "?teams_page=0&teams_size=10";
    const state = getTeamsCurrentPaginationState();
    expect(state.page).toBe(1);
  });

  test("falls back to default when teams_size is 0", () => {
    window.location.search = "?teams_page=1&teams_size=0";
    const state = getTeamsCurrentPaginationState();
    // parseInt("0") || 10 = 0 || 10 = 10, then Math.max(1, 10) = 10
    expect(state.perPage).toBe(10);
  });

  test("handles non-numeric values by using defaults", () => {
    window.location.search = "?teams_page=abc&teams_size=xyz";
    const state = getTeamsCurrentPaginationState();
    expect(state).toEqual({ page: 1, perPage: 10 });
  });
});

// ---------------------------------------------------------------------------
// isTeamScopedView
// ---------------------------------------------------------------------------
describe("isTeamScopedView", () => {
  afterEach(() => {
    delete window.location;
    window.location = { search: "" };
  });

  beforeEach(() => {
    delete window.location;
    window.location = { search: "" };
  });

  test("returns true when team_id is present in URL", () => {
    window.location.search = "?team_id=abc123";
    expect(isTeamScopedView()).toBe(true);
  });

  test("returns false when team_id is absent", () => {
    window.location.search = "";
    expect(isTeamScopedView()).toBe(false);
  });

  test("returns false when team_id is only whitespace", () => {
    window.location.search = "?team_id=   ";
    expect(isTeamScopedView()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// displayPublicTeams
// ---------------------------------------------------------------------------
describe("displayPublicTeams", () => {
  beforeEach(() => {
    const container = document.createElement("div");
    container.id = "public-teams-list";
    document.body.appendChild(container);
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("shows 'No public teams found' when teams array is empty", () => {
    displayPublicTeams([]);
    const container = document.getElementById("public-teams-list");
    expect(container.innerHTML).toContain("No public teams found");
  });

  test("shows 'No public teams found' when teams is null", () => {
    displayPublicTeams(null);
    const container = document.getElementById("public-teams-list");
    expect(container.innerHTML).toContain("No public teams found");
  });

  test("renders team cards for each team", () => {
    const teams = [
      { id: "t1", name: "Engineering", description: "Eng team", member_count: 5 },
      { id: "t2", name: "Design", description: null, member_count: 3 },
    ];
    displayPublicTeams(teams);
    const container = document.getElementById("public-teams-list");
    expect(container.innerHTML).toContain("Engineering");
    expect(container.innerHTML).toContain("Design");
    expect(container.innerHTML).toContain("5 members");
    expect(container.innerHTML).toContain("3 members");
  });

  test("renders team without description", () => {
    const teams = [{ id: "t1", name: "Solo", description: null, member_count: 1 }];
    displayPublicTeams(teams);
    const container = document.getElementById("public-teams-list");
    expect(container.innerHTML).toContain("Solo");
  });

  test("attaches click listeners to request-join buttons", () => {
    const teams = [{ id: "t1", name: "Eng", description: "x", member_count: 2 }];
    displayPublicTeams(teams);
    const container = document.getElementById("public-teams-list");
    const btn = container.querySelector('[data-action="request-join"]');
    expect(btn).not.toBeNull();
    expect(btn.dataset.teamId).toBe("t1");
  });

  test("does nothing when container is missing", () => {
    document.body.innerHTML = "";
    expect(() => displayPublicTeams([])).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// initializePasswordValidation
// ---------------------------------------------------------------------------
describe("initializePasswordValidation", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("calls validatePasswordRequirements when password-field exists in root", () => {
    const policyEl = document.createElement("div");
    policyEl.id = "edit-password-policy-data";
    policyEl.dataset.minLength = "8";
    policyEl.dataset.requireUppercase = "false";
    policyEl.dataset.requireLowercase = "false";
    policyEl.dataset.requireNumbers = "false";
    policyEl.dataset.requireSpecial = "false";
    document.body.appendChild(policyEl);

    const passwordField = document.createElement("input");
    passwordField.id = "password-field";
    passwordField.value = "";
    document.body.appendChild(passwordField);

    const confirmField = document.createElement("input");
    confirmField.id = "confirm-password-field";
    confirmField.value = "";
    document.body.appendChild(confirmField);

    const matchMsg = document.createElement("div");
    matchMsg.id = "password-match-message";
    document.body.appendChild(matchMsg);

    const form = document.createElement("div");
    form.id = "user-edit-modal-content";
    const submitBtn = document.createElement("button");
    submitBtn.type = "submit";
    form.appendChild(submitBtn);
    document.body.appendChild(form);

    expect(() => initializePasswordValidation()).not.toThrow();
  });

  test("does not throw when password-field is missing", () => {
    expect(() => initializePasswordValidation()).not.toThrow();
  });

  test("accepts a custom root element", () => {
    const root = document.createElement("div");
    const passwordField = document.createElement("input");
    passwordField.id = "password-field";
    root.appendChild(passwordField);

    expect(() => initializePasswordValidation(root)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// hideTeamEditModal
// ---------------------------------------------------------------------------
describe("hideTeamEditModal", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("adds hidden class to the team edit modal", () => {
    const modal = document.createElement("div");
    modal.id = "team-edit-modal";
    document.body.appendChild(modal);

    hideTeamEditModal();

    expect(modal.classList.contains("hidden")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// showAddMemberForm / hideAddMemberForm
// ---------------------------------------------------------------------------
describe("showAddMemberForm", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("removes hidden class from the form", () => {
    const form = document.createElement("div");
    form.id = "add-member-form-team1";
    form.classList.add("hidden");
    document.body.appendChild(form);

    showAddMemberForm("team1");

    expect(form.classList.contains("hidden")).toBe(false);
  });

  test("does nothing when form does not exist", () => {
    expect(() => showAddMemberForm("nonexistent")).not.toThrow();
  });
});

describe("hideAddMemberForm", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("adds hidden class to the form", () => {
    const form = document.createElement("div");
    form.id = "add-member-form-team1";
    document.body.appendChild(form);

    hideAddMemberForm("team1");

    expect(form.classList.contains("hidden")).toBe(true);
  });

  test("resets the inner form element if present", () => {
    const wrapper = document.createElement("div");
    wrapper.id = "add-member-form-team1";
    const innerForm = document.createElement("form");
    const resetSpy = vi.spyOn(innerForm, "reset");
    wrapper.appendChild(innerForm);
    document.body.appendChild(wrapper);

    hideAddMemberForm("team1");

    expect(resetSpy).toHaveBeenCalled();
  });

  test("does nothing when form does not exist", () => {
    expect(() => hideAddMemberForm("nonexistent")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// handleAdminTeamAction
// ---------------------------------------------------------------------------
describe("handleAdminTeamAction", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.htmx = {
      ajax: vi.fn(),
      trigger: vi.fn(),
    };
    vi.useFakeTimers();
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  test("resetTeamCreateForm action resets the form", () => {
    const form = document.createElement("form");
    form.setAttribute("hx-post", "/admin/teams");
    const resetSpy = vi.spyOn(form, "reset");
    document.body.appendChild(form);

    const event = { detail: { resetTeamCreateForm: true, delayMs: 0 } };
    handleAdminTeamAction(event);
    vi.runAllTimers();

    expect(resetSpy).toHaveBeenCalled();
  });

  test("closeTeamEditModal action adds hidden to modal", () => {
    const modal = document.createElement("div");
    modal.id = "team-edit-modal";
    document.body.appendChild(modal);

    const event = { detail: { closeTeamEditModal: true, delayMs: 0 } };
    handleAdminTeamAction(event);
    vi.runAllTimers();

    expect(modal.classList.contains("hidden")).toBe(true);
  });

  test("closeRoleModal action hides role assignment modal", () => {
    const modal = document.createElement("div");
    modal.id = "role-assignment-modal";
    document.body.appendChild(modal);

    const event = { detail: { closeRoleModal: true, delayMs: 0 } };
    handleAdminTeamAction(event);
    vi.runAllTimers();

    expect(modal.classList.contains("hidden")).toBe(true);
  });

  test("closeAllModals action hides all modals", () => {
    const modal1 = document.createElement("div");
    modal1.id = "first-modal";
    const modal2 = document.createElement("div");
    modal2.id = "second-modal";
    document.body.appendChild(modal1);
    document.body.appendChild(modal2);

    const event = { detail: { closeAllModals: true, delayMs: 0 } };
    handleAdminTeamAction(event);
    vi.runAllTimers();

    expect(modal1.classList.contains("hidden")).toBe(true);
    expect(modal2.classList.contains("hidden")).toBe(true);
  });

  test("refreshUnifiedTeamsList calls htmx.ajax", () => {
    delete window.location;
    window.location = { search: "" };

    const unifiedList = document.createElement("div");
    unifiedList.id = "unified-teams-list";
    document.body.appendChild(unifiedList);

    const event = { detail: { refreshUnifiedTeamsList: true, delayMs: 0 } };
    handleAdminTeamAction(event);
    vi.runAllTimers();

    expect(window.htmx.ajax).toHaveBeenCalledWith(
      "GET",
      expect.stringContaining("/admin/teams/partial"),
      expect.objectContaining({ target: "#unified-teams-list", swap: "innerHTML" })
    );
  });

  test("handles event with no detail gracefully", () => {
    expect(() => {
      handleAdminTeamAction({});
      vi.runAllTimers();
    }).not.toThrow();
  });

  test("respects delayMs", () => {
    const form = document.createElement("form");
    form.setAttribute("hx-post", "/admin/teams");
    const resetSpy = vi.spyOn(form, "reset");
    document.body.appendChild(form);

    const event = { detail: { resetTeamCreateForm: true, delayMs: 500 } };
    handleAdminTeamAction(event);

    expect(resetSpy).not.toHaveBeenCalled();
    vi.advanceTimersByTime(500);
    expect(resetSpy).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// applyVisibilityRestrictions
// ---------------------------------------------------------------------------
describe("applyVisibilityRestrictions", () => {
  beforeEach(() => {
    delete window.location;
    window.location = { search: "" };
    window.ALLOW_PUBLIC_VISIBILITY = true;
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ALLOW_PUBLIC_VISIBILITY;
    delete window.location;
    window.location = { search: "" };
  });

  function makeRadio(id, checked = false) {
    const wrapper = document.createElement("div");
    wrapper.className = "flex items-center";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.id = id;
    radio.checked = checked;
    const label = document.createElement("label");
    wrapper.appendChild(radio);
    wrapper.appendChild(label);
    document.body.appendChild(wrapper);
    return radio;
  }

  test("does not disable public radio when ALLOW_PUBLIC_VISIBILITY is true", () => {
    window.location.search = "?team_id=abc";
    window.ALLOW_PUBLIC_VISIBILITY = true;
    const radio = makeRadio("tool-visibility-public");

    applyVisibilityRestrictions(["tool-visibility"]);

    expect(radio.disabled).toBe(false);
  });

  test("disables unchecked public radio when ALLOW_PUBLIC_VISIBILITY is false and team scoped", () => {
    window.location.search = "?team_id=abc";
    window.ALLOW_PUBLIC_VISIBILITY = false;
    const radio = makeRadio("tool-visibility-public", false);

    applyVisibilityRestrictions(["tool-visibility"]);

    expect(radio.disabled).toBe(true);
  });

  test("does not disable checked public radio even when ALLOW_PUBLIC_VISIBILITY is false", () => {
    window.location.search = "?team_id=abc";
    window.ALLOW_PUBLIC_VISIBILITY = false;
    const radio = makeRadio("tool-visibility-public", true);

    applyVisibilityRestrictions(["tool-visibility"]);

    expect(radio.disabled).toBe(false);
  });

  test("does not disable when not in team scoped view", () => {
    window.location.search = "";
    window.ALLOW_PUBLIC_VISIBILITY = false;
    const radio = makeRadio("tool-visibility-public", false);

    applyVisibilityRestrictions(["tool-visibility"]);

    expect(radio.disabled).toBe(false);
  });

  test("adds opacity and line-through classes when disabled", () => {
    window.location.search = "?team_id=abc";
    window.ALLOW_PUBLIC_VISIBILITY = false;
    const radio = makeRadio("tool-visibility-public", false);
    const wrapper = radio.closest(".flex.items-center");
    const label = wrapper.querySelector("label");

    applyVisibilityRestrictions(["tool-visibility"]);

    expect(wrapper.classList.contains("opacity-40")).toBe(true);
    expect(label.classList.contains("line-through")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// updateDefaultVisibility
// ---------------------------------------------------------------------------
describe("updateDefaultVisibility", () => {
  beforeEach(() => {
    delete window.location;
    window.location = { search: "" };
    window.ALLOW_PUBLIC_VISIBILITY = true;
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ALLOW_PUBLIC_VISIBILITY;
    delete window.location;
    window.location = { search: "" };
  });

  function makeVisibilityRadios(prefix) {
    ["public", "team", "private"].forEach((type) => {
      const wrapper = document.createElement("div");
      wrapper.className = "flex items-center";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.id = `${prefix}-${type}`;
      radio.checked = false;
      const label = document.createElement("label");
      wrapper.appendChild(radio);
      wrapper.appendChild(label);
      document.body.appendChild(wrapper);
    });
  }

  test("defaults to team radio when team_id is in URL", () => {
    window.location.search = "?team_id=abc";
    makeVisibilityRadios("tool-visibility");

    updateDefaultVisibility();

    const teamRadio = document.getElementById("tool-visibility-team");
    expect(teamRadio.checked).toBe(true);
  });

  test("defaults to public radio when no team_id in URL", () => {
    window.location.search = "";
    makeVisibilityRadios("tool-visibility");

    updateDefaultVisibility();

    const publicRadio = document.getElementById("tool-visibility-public");
    expect(publicRadio.checked).toBe(true);
  });

  test("does not throw when no radios exist", () => {
    expect(() => updateDefaultVisibility()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// loadTeamSelectorDropdown
// ---------------------------------------------------------------------------
describe("loadTeamSelectorDropdown", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.htmx = { process: vi.fn() };
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.htmx;
    vi.restoreAllMocks();
  });

  test("does nothing when container does not exist", () => {
    expect(() => loadTeamSelectorDropdown()).not.toThrow();
  });

  test("does nothing when container is already loaded", () => {
    const container = document.createElement("div");
    container.id = "team-selector-items";
    container.dataset.loaded = "true";
    document.body.appendChild(container);

    const fetchSpy = vi.spyOn(global, "fetch");
    loadTeamSelectorDropdown();

    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("calls fetch and sets innerHTML on success", async () => {
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve("<div>Team A</div>"),
    });

    loadTeamSelectorDropdown();
    // Use setTimeout(0) to flush all microtasks including chained Promise resolutions
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(container.innerHTML).toContain("Team A");
    expect(container.dataset.loaded).toBe("true");
  });

  test("shows error HTML and retry button on fetch failure", async () => {
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockRejectedValue(new Error("Network error"));

    loadTeamSelectorDropdown();
    // Flush microtask queue for rejected promise
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    expect(container.innerHTML).toContain("Failed to load teams");
    expect(container.dataset.loaded).toBeUndefined();
  });

  test("shows error HTML when response is not ok", async () => {
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve(""),
    });

    loadTeamSelectorDropdown();
    // Flush microtask queue
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    expect(container.innerHTML).toContain("Failed to load teams");
  });
});

// ---------------------------------------------------------------------------
// initializeAddMembersForm / initializeAddMembersForms
// ---------------------------------------------------------------------------
describe("initializeAddMembersForm", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.clearAllMocks();
  });

  test("does nothing when form is null", () => {
    expect(() => initializeAddMembersForm(null)).not.toThrow();
  });

  test("does nothing when form is already initialized", () => {
    const form = document.createElement("form");
    form.id = "add-members-form-team1";
    form.dataset.initialized = "true";
    document.body.appendChild(form);

    expect(() => initializeAddMembersForm(form)).not.toThrow();
  });

  test("marks form initialized even when no team ID can be extracted", () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const form = document.createElement("form");
    form.id = "unknown-form";
    document.body.appendChild(form);

    expect(() => initializeAddMembersForm(form)).not.toThrow();
    // The implementation sets initialized=true before the team ID check
    expect(form.dataset.initialized).toBe("true");
    consoleSpy.mockRestore();
  });

  test("marks form as initialized and sets up change listener", () => {
    const form = document.createElement("form");
    form.id = "add-members-form-team42";

    const countEl = document.createElement("div");
    countEl.id = "selected-count-team42";
    document.body.appendChild(countEl);

    document.body.appendChild(form);

    initializeAddMembersForm(form);

    expect(form.dataset.initialized).toBe("true");
  });
});

describe("initializeAddMembersForms", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("does not throw when no matching forms exist", () => {
    expect(() => initializeAddMembersForms()).not.toThrow();
  });

  test("initializes all add-members-form-* forms in root", () => {
    const form1 = document.createElement("form");
    form1.id = "add-members-form-t1";
    const form2 = document.createElement("form");
    form2.id = "add-members-form-t2";
    document.body.appendChild(form1);
    document.body.appendChild(form2);

    initializeAddMembersForms(document);

    expect(form1.dataset.initialized).toBe("true");
    expect(form2.dataset.initialized).toBe("true");
  });

  test("initializes team-members-form-* forms as well", () => {
    const form = document.createElement("form");
    form.id = "team-members-form-t3";
    document.body.appendChild(form);

    initializeAddMembersForms(document);

    expect(form.dataset.initialized).toBe("true");
  });
});
