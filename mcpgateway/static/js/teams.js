import { AppState } from "./appState";
import { DEFAULT_TEAMS_PER_PAGE } from "./constants";
import { escapeHtml } from "./security";
import { getAuthToken } from "./tokens";
import {
  fetchWithTimeout,
  safeGetElement,
  showErrorMessage,
  showSuccessMessage,
} from "./utils";

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

const validatePasswordRequirements = function () {
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
