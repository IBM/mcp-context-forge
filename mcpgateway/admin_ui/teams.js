import { AppState } from "./appState.js";
import { DEFAULT_TEAMS_PER_PAGE } from "./constants.js";
import { escapeHtml, safeReplaceState } from "./security.js";
import { fetchWithAuth, getAuthToken } from "./tokens.js";
import { performUserSearch } from "./users.js";
import {
  fetchWithTimeout,
  safeGetElement,
  showErrorMessage,
  showSuccessMessage,
} from "./utils.js";

// ============================================================================ //
//                         TEAM SEARCH AND FILTER FUNCTIONS                     //
// ============================================================================ //

/**
 * Debounce timer for team search
 */
let teamSearchDebounceTimer = null;

/**
 * Perform server-side search for teams and update the teams list
 * @param {string} searchTerm - The search query
 */
export const serverSideTeamSearch = function (searchTerm) {
  // Debounce the search to avoid excessive API calls
  if (teamSearchDebounceTimer) {
    clearTimeout(teamSearchDebounceTimer);
  }

  teamSearchDebounceTimer = setTimeout(() => {
    performTeamSearch(searchTerm);
  }, 300);
};

/**
 * Get current per_page value from pagination controls or use default
 */
export const getTeamsPerPage = function () {
  // Try to get from pagination controls select element
  const paginationControls = safeGetElement("teams-pagination-controls");
  if (paginationControls) {
    const select = paginationControls.querySelector("select");
    if (select && select.value) {
      return parseInt(select.value, 10) || DEFAULT_TEAMS_PER_PAGE;
    }
  }
  return DEFAULT_TEAMS_PER_PAGE;
};

/**
 * Actually perform the team search after debounce
 * @param {string} searchTerm - The search query
 */
const performTeamSearch = async function (searchTerm) {
  const container = safeGetElement("unified-teams-list");
  const loadingIndicator = safeGetElement("teams-loading");

  if (!container) {
    console.error("unified-teams-list container not found");
    return;
  }

  // Show loading state
  if (loadingIndicator) {
    loadingIndicator.style.display = "block";
  }

  // Build URL with search query and current relationship filter
  const params = new URLSearchParams();
  params.set("page", "1");
  params.set("per_page", getTeamsPerPage().toString());
  
  // Sync URL state so CRUD refresh reads the correct page
  const currentUrl = new URL(window.location.href);
  const urlParams = new URLSearchParams(currentUrl.searchParams);
  urlParams.set("teams_page", "1");
  urlParams.set("teams_size", getTeamsPerPage().toString());
  const newUrl =
    currentUrl.pathname + "?" + urlParams.toString() + currentUrl.hash;
  safeReplaceState({}, "", newUrl);
  if (searchTerm && searchTerm.trim() !== "") {
    params.set("q", searchTerm.trim());
  }

  const currentTeamRelationshipFilter =
    AppState.getCurrentTeamRelationshipFilter();
  if (
    currentTeamRelationshipFilter &&
    currentTeamRelationshipFilter !== "all"
  ) {
    params.set("relationship", currentTeamRelationshipFilter);
  }

  const url = `${window.ROOT_PATH || ""}/admin/teams/partial?${params.toString()}`;

  console.log(`[Team Search] Searching teams with URL: ${url}`);

  try {
    // Use HTMX to load the results
    if (window.htmx) {
      // HTMX handles the indicator automatically via the indicator option
      // Don't manually hide it - HTMX will hide it when request completes
      window.htmx.ajax("GET", url, {
        target: "#unified-teams-list",
        swap: "innerHTML",
        indicator: "#teams-loading",
      });
    } else {
      // Fallback to fetch if HTMX is not available
      const response = await fetch(url);
      if (response.ok) {
        const html = await response.text();
        container.innerHTML = html;
      } else {
        container.innerHTML =
          '<div class="text-center py-4 text-red-600">Failed to load teams</div>';
      }
      // Only hide indicator in fetch fallback path (HTMX handles its own)
      if (loadingIndicator) {
        loadingIndicator.style.display = "none";
      }
    }
  } catch (error) {
    console.error("Error searching teams:", error);
    container.innerHTML =
      '<div class="text-center py-4 text-red-600">Error searching teams</div>';
    // Hide indicator on error in fallback path
    if (loadingIndicator) {
      loadingIndicator.style.display = "none";
    }
  }
};

/**
 * Filter teams by relationship (owner, member, public, all)
 * @param {string} filter - The relationship filter value
 */
export const filterByRelationship = function (filter) {
  // Update button states
  const filterButtons = document.querySelectorAll(".filter-btn");
  filterButtons.forEach((btn) => {
    if (btn.getAttribute("data-filter") === filter) {
      btn.classList.add(
        "active",
        "bg-indigo-100",
        "dark:bg-indigo-900",
        "text-indigo-700",
        "dark:text-indigo-300",
        "border-indigo-300",
        "dark:border-indigo-600"
      );
      btn.classList.remove(
        "bg-white",
        "dark:bg-gray-700",
        "text-gray-700",
        "dark:text-gray-300"
      );
    } else {
      btn.classList.remove(
        "active",
        "bg-indigo-100",
        "dark:bg-indigo-900",
        "text-indigo-700",
        "dark:text-indigo-300",
        "border-indigo-300",
        "dark:border-indigo-600"
      );
      btn.classList.add(
        "bg-white",
        "dark:bg-gray-700",
        "text-gray-700",
        "dark:text-gray-300"
      );
    }
  });

  // Update current filter state
  AppState.setCurrentTeamRelationshipFilter(filter);

  // Get current search query
  const searchInput = safeGetElement("team-search");
  const searchQuery = searchInput ? searchInput.value.trim() : "";

  // Perform search with new filter
  performTeamSearch(searchQuery);
};

/**
 * Legacy filterTeams function - redirects to serverSideTeamSearch
 * @param {string} searchValue - The search query
 */
export const filterTeams = function (searchValue) {
  serverSideTeamSearch(searchValue);
};

// ===================================================================
// TEAM DISCOVERY AND SELF-SERVICE FUNCTIONS
// ===================================================================

/**
 * Load and display public teams that the user can join
 */
const loadPublicTeams = async function () {
  const container = safeGetElement("public-teams-list");
  if (!container) {
    console.error("Public teams list container not found");
    return;
  }

  // Show loading state
  container.innerHTML =
    '<div class="animate-pulse text-gray-500 dark:text-gray-400">Loading public teams...</div>';

  try {
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH || ""}/teams/discover`,
      {
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
          "Content-Type": "application/json",
        },
      }
    );
    if (!response.ok) {
      throw new Error(`Failed to load teams: ${response.status}`);
    }

    const teams = await response.json();
    displayPublicTeams(teams);
  } catch (error) {
    console.error("Error loading public teams:", error);
    container.innerHTML = `
                  <div class="bg-red-50 dark:bg-red-900 border border-red-200 dark:border-red-700 rounded-md p-4">
                      <div class="flex">
                          <div class="flex-shrink-0">
                              <svg class="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clip-rule="evenodd" />
                              </svg>
                          </div>
                          <div class="ml-3">
                              <h3 class="text-sm font-medium text-red-800 dark:text-red-200">
                                  Failed to load public teams
                              </h3>
                              <div class="mt-2 text-sm text-red-700 dark:text-red-300">
                                  ${escapeHtml(error.message)}
                              </div>
                          </div>
                      </div>
                  </div>
              `;
  }
};

/**
 * Display public teams in the UI
 * @param {Array} teams - Array of team objects
 */
const displayPublicTeams = function (teams) {
  const container = safeGetElement("public-teams-list");
  if (!container) {
    return;
  }

  if (!teams || teams.length === 0) {
    container.innerHTML = `
                  <div class="text-center py-8">
                      <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.83-1M17 20H7m10 0v-2c0-1.09-.29-2.11-.83-3M7 20v2m0-2v-2a3 3 0 011.87-2.77m0 0A3 3 0 017 12m0 0a3 3 0 013-3m-3 3h6.4M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      <h3 class="mt-2 text-sm font-medium text-gray-900 dark:text-gray-100">No public teams found</h3>
                      <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">There are no public teams available to join at the moment.</p>
                  </div>
              `;
    return;
  }

  // Create teams grid
  const teamsHtml = teams
    .map(
      (team) => `
              <div class="bg-white dark:bg-gray-700 shadow rounded-lg p-6 hover:shadow-lg transition-shadow">
                  <div class="flex items-center justify-between">
                      <h3 class="text-lg font-medium text-gray-900 dark:text-white">
                          ${escapeHtml(team.name)}
                      </h3>
                      <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                          Public
                      </span>
                  </div>

                  ${
  team.description
    ? `
                      <p class="mt-2 text-sm text-gray-600 dark:text-gray-300">
                          ${escapeHtml(team.description)}
                      </p>
                  `
    : ""
}

                  <div class="mt-4 flex items-center justify-between">
                      <div class="flex items-center text-sm text-gray-500 dark:text-gray-400">
                          <svg class="flex-shrink-0 mr-1.5 h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                              <path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z"/>
                          </svg>
                          ${team.member_count} members
                      </div>
                      <button
                          onclick="Admin.requestToJoinTeam('${escapeHtml(team.id)}')"
                          class="px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
                      >
                          Request to Join
                      </button>
                  </div>
              </div>
          `
    )
    .join("");

  container.innerHTML = `
              <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  ${teamsHtml}
              </div>
          `;
};

/**
 * Request to join a public team
 * @param {string} teamId - ID of the team to join
 */
export const requestToJoinTeam = async function (teamId) {
  if (!teamId) {
    console.error("Team ID is required");
    return;
  }

  // Show confirmation dialog
  const message = prompt("Optional: Enter a message to the team owners:");

  try {
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH || ""}/teams/${teamId}/join`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: message || null,
        }),
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      throw new Error(
        errorData?.detail || `Failed to request join: ${response.status}`
      );
    }

    const result = await response.json();

    // Show success message
    showSuccessMessage(
      `Join request sent to ${result.team_name}! Team owners will review your request.`
    );

    // Refresh the public teams list
    setTimeout(loadPublicTeams, 1000);
  } catch (error) {
    console.error("Error requesting to join team:", error);
    showErrorMessage(`Failed to send join request: ${error.message}`);
  }
};

/**
 * Leave a team
 * @param {string} teamId - ID of the team to leave
 * @param {string} teamName - Name of the team (for confirmation)
 */
export const leaveTeam = async function (teamId, teamName) {
  if (!teamId) {
    console.error("Team ID is required");
    return;
  }

  // Show confirmation dialog
  const confirmed = confirm(
    `Are you sure you want to leave the team "${teamName}"? This action cannot be undone.`
  );
  if (!confirmed) {
    return;
  }

  try {
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH || ""}/teams/${teamId}/leave`,
      {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
          "Content-Type": "application/json",
        },
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      throw new Error(
        errorData?.detail || `Failed to leave team: ${response.status}`
      );
    }

    await response.json();

    // Show success message
    showSuccessMessage(`Successfully left ${teamName}`);

    // Refresh teams list
    const teamsList = safeGetElement("teams-list");
    if (teamsList && window.htmx) {
      window.htmx.trigger(teamsList, "load");
    }

    // Refresh team selector if available
    if (typeof updateTeamContext === "function") {
      // Force reload teams data
      setTimeout(() => {
        window.location.reload();
      }, 1500);
    }
  } catch (error) {
    console.error("Error leaving team:", error);
    showErrorMessage(`Failed to leave team: ${error.message}`);
  }
};

/**
 * Approve a join request
 * @param {string} teamId - ID of the team
 * @param {string} requestId - ID of the join request
 */
export const approveJoinRequest = async function (teamId, requestId) {
  if (!teamId || !requestId) {
    console.error("Team ID and request ID are required");
    return;
  }

  try {
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH || ""}/teams/${teamId}/join-requests/${requestId}/approve`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
          "Content-Type": "application/json",
        },
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      throw new Error(
        errorData?.detail ||
          `Failed to approve join request: ${response.status}`
      );
    }

    const result = await response.json();

    // Show success message
    showSuccessMessage(
      `Join request approved! ${result.user_email} is now a member.`
    );

    // Refresh teams list
    const teamsList = safeGetElement("teams-list");
    if (teamsList && window.htmx) {
      window.htmx.trigger(teamsList, "load");
    }
  } catch (error) {
    console.error("Error approving join request:", error);
    showErrorMessage(`Failed to approve join request: ${error.message}`);
  }
};

/**
 * Reject a join request
 * @param {string} teamId - ID of the team
 * @param {string} requestId - ID of the join request
 */
export const rejectJoinRequest = async function (teamId, requestId) {
  if (!teamId || !requestId) {
    console.error("Team ID and request ID are required");
    return;
  }

  const confirmed = confirm(
    "Are you sure you want to reject this join request?"
  );
  if (!confirmed) {
    return;
  }

  try {
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH || ""}/teams/${teamId}/join-requests/${requestId}`,
      {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
          "Content-Type": "application/json",
        },
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      throw new Error(
        errorData?.detail || `Failed to reject join request: ${response.status}`
      );
    }

    // Show success message
    showSuccessMessage("Join request rejected.");

    // Refresh teams list
    const teamsList = safeGetElement("teams-list");
    if (teamsList && window.htmx) {
      window.htmx.trigger(teamsList, "load");
    }
  } catch (error) {
    console.error("Error rejecting join request:", error);
    showErrorMessage(`Failed to reject join request: ${error.message}`);
  }
};

/**
 * Validate password match in user edit form
 */
const getPasswordPolicy = function () {
  const policyEl = safeGetElement("edit-password-policy-data");
  if (!policyEl) {
    return null;
  }
  return {
    minLength: parseInt(policyEl.dataset.minLength || "0", 10),
    requireUppercase: policyEl.dataset.requireUppercase === "true",
    requireLowercase: policyEl.dataset.requireLowercase === "true",
    requireNumbers: policyEl.dataset.requireNumbers === "true",
    requireSpecial: policyEl.dataset.requireSpecial === "true",
  };
};

const updateRequirementIcon = function (elementId, isValid) {
  const req = safeGetElement(elementId);
  if (!req) {
    return;
  }
  const icon = req.querySelector("span");
  if (!icon) {
    return;
  }
  if (isValid) {
    icon.className =
      "inline-flex items-center justify-center w-4 h-4 bg-green-500 text-white rounded-full text-xs mr-2";
    icon.textContent = "✓";
  } else {
    icon.className =
      "inline-flex items-center justify-center w-4 h-4 bg-gray-400 text-white rounded-full text-xs mr-2";
    icon.textContent = "✗";
  }
};

export const validatePasswordRequirements = function () {
  const policy = getPasswordPolicy();
  const passwordField = safeGetElement("password-field", true);
  if (!policy || !passwordField) {
    return;
  }

  const password = passwordField.value || "";
  const lengthCheck = password.length >= policy.minLength;
  updateRequirementIcon("edit-req-length", lengthCheck);

  const uppercaseCheck = !policy.requireUppercase || /[A-Z]/.test(password);
  updateRequirementIcon("edit-req-uppercase", uppercaseCheck);

  const lowercaseCheck = !policy.requireLowercase || /[a-z]/.test(password);
  updateRequirementIcon("edit-req-lowercase", lowercaseCheck);

  const numbersCheck = !policy.requireNumbers || /[0-9]/.test(password);
  updateRequirementIcon("edit-req-numbers", numbersCheck);

  const specialChars = "!@#$%^&*()_+-=[]{};:'\"\\|,.<>`~/?";
  const specialCheck =
    !policy.requireSpecial ||
    [...password].some((char) => specialChars.includes(char));
  updateRequirementIcon("edit-req-special", specialCheck);

  const submitButton = document.querySelector(
    '#user-edit-modal-content button[type="submit"]'
  );
  const allRequirementsMet =
    lengthCheck &&
    uppercaseCheck &&
    lowercaseCheck &&
    numbersCheck &&
    specialCheck;
  const passwordEmpty = password.length === 0;

  if (submitButton) {
    if (passwordEmpty || allRequirementsMet) {
      submitButton.disabled = false;
      submitButton.className =
        "px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500";
    } else {
      submitButton.disabled = true;
      submitButton.className =
        "px-4 py-2 text-sm font-medium text-white bg-gray-400 border border-transparent rounded-md cursor-not-allowed";
    }
  }
};

export const initializePasswordValidation = function (root = document) {
  if (
    root?.querySelector?.("#password-field") ||
    safeGetElement("password-field", true)
  ) {
    validatePasswordRequirements();
    validatePasswordMatch();
  }
};

export const validatePasswordMatch = function () {
  const passwordField = safeGetElement("password-field", true);
  const confirmPasswordField = safeGetElement("confirm-password-field", true);
  const messageElement = safeGetElement("password-match-message", true);
  const submitButton = document.querySelector(
    '#user-edit-modal-content button[type="submit"]'
  );

  if (!passwordField || !confirmPasswordField || !messageElement) {
    return;
  }

  const password = passwordField.value;
  const confirmPassword = confirmPasswordField.value;

  // Only show validation if both fields have content or if confirm field has content
  if (
    (password.length > 0 || confirmPassword.length > 0) &&
    password !== confirmPassword
  ) {
    messageElement.classList.remove("hidden");
    confirmPasswordField.classList.add("border-red-500");
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.classList.add("opacity-50", "cursor-not-allowed");
    }
  } else {
    messageElement.classList.add("hidden");
    confirmPasswordField.classList.remove("border-red-500");
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.classList.remove("opacity-50", "cursor-not-allowed");
    }
  }
};

// ===================================================================
// TEAM MANAGEMENT FUNCTIONS
// ===================================================================
// Team edit modal functions
export const hideTeamEditModal = function () {
  safeGetElement("team-edit-modal").classList.add("hidden");
};

// Team member management functions
export const showAddMemberForm = function (teamId) {
  const form = safeGetElement("add-member-form-" + teamId);
  if (form) {
    form.classList.remove("hidden");
  }
};

export const hideAddMemberForm = function (teamId) {
  const form = safeGetElement("add-member-form-" + teamId);
  if (form) {
    form.classList.add("hidden");
    // Reset form
    const formElement = form.querySelector("form");
    if (formElement) {
      formElement.reset();
    }
  }
};

// Reset team creation form after successful HTMX actions
export const resetTeamCreateForm = function () {
  const form = document.querySelector('form[hx-post*="/admin/teams"]');
  if (form) {
    form.reset();
  }
  const errorEl = safeGetElement("create-team-error");
  if (errorEl) {
    errorEl.innerHTML = "";
  }
};

// Normalize team ID from element IDs like "add-members-form-<id>"
export const extractTeamId = function (prefix, elementId) {
  if (!elementId || !elementId.startsWith(prefix)) {
    return null;
  }
  return elementId.slice(prefix.length);
};

export const updateAddMembersCount = function (teamId) {
  const form = safeGetElement(`add-members-form-${teamId}`);
  const countEl = safeGetElement(`selected-count-${teamId}`);
  if (!form || !countEl) {
    return;
  }
  const checked = form.querySelectorAll(
    'input[name="associatedUsers"]:checked'
  );
  countEl.textContent =
    checked.length === 0
      ? "No users selected"
      : `${checked.length} user${checked.length !== 1 ? "s" : ""} selected`;
};

export const dedupeSelectorItems = function (container) {
  if (!container) {
    return;
  }
  const seen = new Set();
  const items = Array.from(container.querySelectorAll(".user-item"));
  items.forEach((item) => {
    const email = item.getAttribute("data-user-email") || "";
    if (!email) {
      return;
    }
    if (seen.has(email)) {
      item.remove();
      return;
    }
    seen.add(email);
  });
};

export const handleAdminTeamAction = function (event) {
  const detail = event.detail || {};
  const delayMs = Number(detail.delayMs) || 0;
  setTimeout(() => {
    if (detail.resetTeamCreateForm) {
      resetTeamCreateForm();
    }
    if (detail.closeTeamEditModal && typeof hideTeamEditModal === "function") {
      hideTeamEditModal();
    }
    if (detail.closeRoleModal) {
      const roleModal = safeGetElement("role-assignment-modal");
      if (roleModal) {
        roleModal.classList.add("hidden");
      }
    }
    if (detail.closeAllModals) {
      const modals = document.querySelectorAll('[id$="-modal"]');
      modals.forEach((modal) => modal.classList.add("hidden"));
    }
    if (detail.refreshUnifiedTeamsList && window.htmx) {
      const unifiedList = safeGetElement("unified-teams-list");
      if (unifiedList) {
        // Preserve current pagination/filter state on refresh
        const paginationState = getTeamsCurrentPaginationState();
        const params = new URLSearchParams();
        params.set("page", paginationState.page);
        params.set("per_page", paginationState.perPage);
        // Preserve search query from input field
        const searchInput = safeGetElement("team-search");
        if (searchInput && searchInput.value.trim()) {
          params.set("q", searchInput.value.trim());
        }
        // Preserve relationship filter
        const currentTeamRelationshipFilter = AppState.getCurrentTeamRelationshipFilter();
        if (
          typeof currentTeamRelationshipFilter !== "undefined" &&
          currentTeamRelationshipFilter &&
          currentTeamRelationshipFilter !== "all"
        ) {
          params.set("relationship", currentTeamRelationshipFilter);
        }
        const url = `${window.ROOT_PATH || ""}/admin/teams/partial?${params.toString()}`;
        window.htmx.ajax("GET", url, {
          target: "#unified-teams-list",
          swap: "innerHTML",
        });
      }
    }
    if (detail.refreshTeamMembers && detail.teamId) {
      if (typeof window.loadTeamMembersView === "function") {
        window.loadTeamMembersView(detail.teamId);
      } else if (window.htmx) {
        const modalContent = safeGetElement("team-edit-modal-content");
        if (modalContent) {
          window.htmx.ajax(
            "GET",
            `${window.ROOT_PATH || ""}/admin/teams/${detail.teamId}/members`,
            {
              target: "#team-edit-modal-content",
              swap: "innerHTML",
            }
          );
        }
      }
    }
    if (detail.refreshJoinRequests && detail.teamId && window.htmx) {
      const joinRequests = safeGetElement("team-join-requests-modal-content");
      if (joinRequests) {
        window.htmx.ajax(
          "GET",
          `${window.ROOT_PATH || ""}/admin/teams/${detail.teamId}/join-requests`,
          {
            target: "#team-join-requests-modal-content",
            swap: "innerHTML",
          }
        );
      }
    }
  }, delayMs);
};

// Get current pagination state from URL parameters
export const  getTeamsCurrentPaginationState = function() {
  const urlParams = new URLSearchParams(window.location.search);
  return {
    page: Math.max(1, parseInt(urlParams.get("teams_page"), 10) || 1),
    perPage: Math.max(1, parseInt(urlParams.get("teams_size"), 10) || 10),
  };
}

export const initializeAddMembersForm = function (form) {
  if (!form || form.dataset.initialized === "true") {
    return;
  }
  form.dataset.initialized = "true";

  // Support both old add-members-form pattern and new team-members-form pattern
  const teamId =
    form.dataset.teamId ||
    extractTeamId("add-members-form-", form.id) ||
    extractTeamId("team-members-form-", form.id) ||
    "";

  console.log(
    `[initializeAddMembersForm] Form ID: ${form.id}, Team ID: ${teamId}`
  );

  if (!teamId) {
    console.warn(`[initializeAddMembersForm] No team ID found for form:`, form);
    return;
  }

  const searchInput = safeGetElement(`user-search-${teamId}`);
  const searchResults = safeGetElement(`user-search-results-${teamId}`);
  const searchLoading = safeGetElement(`user-search-loading-${teamId}`);

  // For unified view, find the list container for client-side filtering
  const userListContainer = safeGetElement(`team-members-list-${teamId}`);

  console.log(
    `[Team ${teamId}] Form initialization - searchInput: ${!!searchInput}, userListContainer: ${!!userListContainer}, searchResults: ${!!searchResults}`
  );

  const memberEmails = [];
  if (searchResults?.dataset.memberEmails) {
    try {
      const parsed = JSON.parse(searchResults.dataset.memberEmails);
      if (Array.isArray(parsed)) {
        memberEmails.push(...parsed);
      }
    } catch (error) {
      console.warn("Failed to parse member emails", error);
    }
  }
  const memberEmailSet = new Set(memberEmails);

  form.addEventListener("change", function (event) {
    if (event.target?.name === "associatedUsers") {
      updateAddMembersCount(teamId);
      // Role dropdown state is not managed client-side - all logic is server-side
    }
  });

  updateAddMembersCount(teamId);

  // If we have searchInput and userListContainer, use server-side search like tools (unified view)
  if (searchInput && userListContainer) {
    console.log(
      `[Team ${teamId}] Initializing server-side search for unified view`
    );

    // Get team member data from the initial page load (embedded in the form)
    const teamMemberDataScript = safeGetElement(`team-member-data-${teamId}`);
    let teamMemberData = {};
    if (teamMemberDataScript) {
      try {
        teamMemberData = JSON.parse(teamMemberDataScript.textContent || "{}");
        console.log(
          `[Team ${teamId}] Loaded team member data for ${Object.keys(teamMemberData).length} members`
        );
      } catch (e) {
        console.error(`[Team ${teamId}] Failed to parse team member data:`, e);
      }
    }

    let searchTimeout;
    searchInput.addEventListener("input", function () {
      clearTimeout(searchTimeout);
      const query = this.value.trim();

      searchTimeout = setTimeout(async () => {
        await performUserSearch(
          teamId,
          query,
          userListContainer,
          teamMemberData
        );
      }, 300);
    });

    return;
  }

  if (!searchInput || !searchResults) {
    return;
  }

  let searchTimeout;
  searchInput.addEventListener("input", function () {
    clearTimeout(searchTimeout);
    const query = this.value.trim();

    if (query.length < 2) {
      searchResults.innerHTML = "";
      if (searchLoading) {
        searchLoading.classList.add("hidden");
      }
      return;
    }

    searchTimeout = setTimeout(async () => {
      if (searchLoading) {
        searchLoading.classList.remove("hidden");
      }
      try {
        const searchUrl = searchInput.dataset.searchUrl || "";
        const limit = searchInput.dataset.searchLimit || "10";
        if (!searchUrl) {
          throw new Error("Search URL missing");
        }
        const response = await fetchWithAuth(
          `${searchUrl}?q=${encodeURIComponent(query)}&limit=${limit}`
        );
        if (!response.ok) {
          throw new Error(`Search failed: ${response.status}`);
        }
        const data = await response.json();

        searchResults.innerHTML = "";
        if (data.users && data.users.length > 0) {
          const container = document.createElement("div");
          container.className =
            "bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-md p-2 mt-1";

          data.users.forEach((user) => {
            if (memberEmailSet.has(user.email)) {
              return;
            }
            const item = document.createElement("div");
            item.className =
              "p-2 hover:bg-gray-50 dark:hover:bg-gray-700 rounded cursor-pointer text-sm";
            item.textContent = `${user.full_name || ""} (${user.email})`;
            item.addEventListener("click", () => {
              const container = safeGetElement(
                `user-selector-container-${teamId}`
              );
              if (!container) {
                return;
              }
              const checkbox = container.querySelector(
                `input[value="${user.email}"]`
              );

              if (checkbox) {
                checkbox.checked = true;
                checkbox.dispatchEvent(new Event("change", { bubbles: true }));
              } else {
                const userItem = document.createElement("div");
                userItem.className =
                  "flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 p-2 hover:bg-indigo-50 dark:hover:bg-indigo-900 rounded-md user-item";
                userItem.setAttribute("data-user-email", user.email);

                const newCheckbox = document.createElement("input");
                newCheckbox.type = "checkbox";
                newCheckbox.name = "associatedUsers";
                newCheckbox.value = user.email;
                newCheckbox.setAttribute(
                  "data-user-name",
                  user.full_name || ""
                );
                newCheckbox.className =
                  "user-checkbox form-checkbox h-5 w-5 text-indigo-600 dark:bg-gray-800 dark:border-gray-600 flex-shrink-0";
                newCheckbox.setAttribute("data-auto-check", "true");
                newCheckbox.checked = true;

                const label = document.createElement("span");
                label.className = "select-none flex-grow";
                label.textContent = `${user.full_name || ""} (${user.email})`;

                const roleSelect = document.createElement("select");
                roleSelect.name = `role_${encodeURIComponent(user.email)}`;
                roleSelect.className =
                  "role-select text-sm px-2 py-1 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-white flex-shrink-0";

                const memberOption = document.createElement("option");
                memberOption.value = "member";
                memberOption.textContent = "Member";
                memberOption.selected = true;

                const ownerOption = document.createElement("option");
                ownerOption.value = "owner";
                ownerOption.textContent = "Owner";

                roleSelect.appendChild(memberOption);
                roleSelect.appendChild(ownerOption);

                userItem.appendChild(newCheckbox);
                userItem.appendChild(label);
                userItem.appendChild(roleSelect);

                const firstChild = container.firstChild;
                if (firstChild) {
                  container.insertBefore(userItem, firstChild);
                } else {
                  container.appendChild(userItem);
                }

                newCheckbox.dispatchEvent(
                  new Event("change", { bubbles: true })
                );
              }

              searchInput.value = "";
              searchResults.innerHTML = "";
            });
            container.appendChild(item);
          });

          if (container.childElementCount > 0) {
            searchResults.appendChild(container);
          } else {
            const empty = document.createElement("div");
            empty.className = "text-sm text-gray-500 dark:text-gray-400 mt-1";
            empty.textContent = "No users found";
            searchResults.appendChild(empty);
          }
        } else {
          const empty = document.createElement("div");
          empty.className = "text-sm text-gray-500 dark:text-gray-400 mt-1";
          empty.textContent = "No users found";
          searchResults.appendChild(empty);
        }
      } catch (error) {
        console.error("Search error:", error);
        searchResults.innerHTML = "";
        const errorEl = document.createElement("div");
        errorEl.className = "text-sm text-red-500 mt-1";
        errorEl.textContent = "Search failed";
        searchResults.appendChild(errorEl);
      } finally {
        if (searchLoading) {
          searchLoading.classList.add("hidden");
        }
      }
    }, 300);
  });
};

export const initializeAddMembersForms = function (root = document) {
  // Support both old add-members-form pattern and new unified team-members-form pattern
  const addMembersForms =
    root?.querySelectorAll?.('[id^="add-members-form-"]') || [];
  const teamMembersForms =
    root?.querySelectorAll?.('[id^="team-members-form-"]') || [];
  const allForms = [...addMembersForms, ...teamMembersForms];
  allForms.forEach((form) => initializeAddMembersForm(form));
};