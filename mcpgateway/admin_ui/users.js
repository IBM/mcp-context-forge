import { escapeHtml } from "./security.js";
import {
  dedupeSelectorItems,
  extractTeamId,
  handleAdminTeamAction,
  initializeAddMembersForms,
  initializePasswordValidation,
  updateAddMembersCount,
} from "./teams.js";
import { fetchWithAuth } from "./tokens.js";
import { safeGetElement } from "./utils.js";

// ===================================================================
// USER MANAGEMENT FUNCTIONS
// ===================================================================

/**
 * Show user edit modal and load edit form
 */
export const showUserEditModal = async function (userEmail) {
  const modal = document.getElementById("user-edit-modal");
  const modalContent = document.getElementById("user-edit-modal-content");
  if (!modal || !modalContent || !userEmail) {
    return;
  }

  modalContent.innerHTML = `
        <div class="flex items-center justify-center py-8 text-sm text-gray-500 dark:text-gray-400">
            Loading user details...
        </div>
    `;

  if (modal) {
    modal.style.display = "block";
    modal.classList.remove("hidden");
  }

  const rootPath = window.ROOT_PATH || "";
  const url = `${rootPath}/admin/users/${encodeURIComponent(userEmail)}/edit`;

  try {
    if (window.htmx && typeof window.htmx.ajax === "function") {
      await window.htmx.ajax("GET", url, {
        target: "#user-edit-modal-content",
        swap: "innerHTML",
      });
      return;
    }

    const response = await fetchWithAuth(url, { method: "GET" });
    if (!response.ok) {
      throw new Error(
        `Failed to load user edit form (${response.status} ${response.statusText})`
      );
    }

    modalContent.innerHTML = await response.text();
  } catch (error) {
    console.error("Error loading user edit form:", error);
    modalContent.innerHTML = `
            <div class="p-4 text-sm text-red-600 dark:text-red-400">
                Failed to load user details.
            </div>
        `;
  }
}

/**
 * Hide user edit modal
 */
export const hideUserEditModal = function () {
  const modal = safeGetElement("user-edit-modal");
  if (modal) {
    modal.style.display = "none";
    modal.classList.add("hidden");
  }
};

// Perform server-side user search and build HTML from JSON (like tools search)
export const performUserSearch = async function (
  teamId,
  query,
  container,
  teamMemberData
) {
  console.log(`[Team ${teamId}] Performing user search: "${query}"`);

  // Step 1: Capture current selections before replacing HTML
  const selections = {};
  const roleSelections = {};
  try {
    const userItems = container.querySelectorAll(".user-item");
    userItems.forEach((item) => {
      const email = item.dataset.userEmail || "";
      const checkbox = item.querySelector('input[name="associatedUsers"]');
      const roleSelect = item.querySelector(".role-select");
      if (checkbox && email) {
        selections[email] = checkbox.checked;
      }
      if (roleSelect && email) {
        roleSelections[email] = roleSelect.value;
      }
    });
    console.log(
      `[Team ${teamId}] Captured ${Object.keys(selections).length} selections and ${Object.keys(roleSelections).length} role selections`
    );
  } catch (e) {
    console.error(`[Team ${teamId}] Error capturing selections:`, e);
  }

  // Step 2: Show loading state
  container.innerHTML = `
              <div class="text-center py-4">
                  <svg class="animate-spin h-5 w-5 text-indigo-600 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  <p class="mt-2 text-sm text-gray-500">Searching users...</p>
              </div>
          `;

  // Step 3: If query is empty, reload default list from /admin/users/partial
  if (query === "") {
    try {
      const usersUrl = `${window.ROOT_PATH}/admin/users/partial?page=1&per_page=50&render=selector&team_id=${encodeURIComponent(teamId)}`;
      console.log(
        `[Team ${teamId}] Loading default users with URL: ${usersUrl}`
      );

      const response = await fetchWithAuth(usersUrl);
      if (response.ok) {
        const html = await response.text();
        container.innerHTML = html;

        // Restore selections
        restoreUserSelections(container, selections, roleSelections);
      } else {
        console.error(
          `[Team ${teamId}] Failed to load users: ${response.status}`
        );
        container.innerHTML =
          '<div class="text-center py-4 text-red-600">Failed to load users</div>';
      }
    } catch (error) {
      console.error(`[Team ${teamId}] Error loading users:`, error);
      container.innerHTML =
        '<div class="text-center py-4 text-red-600">Error loading users</div>';
    }
    return;
  }

  // Step 4: Call /admin/users/search API
  try {
    const searchUrl = `${window.ROOT_PATH}/admin/users/search?q=${encodeURIComponent(query)}&limit=50`;
    console.log(`[Team ${teamId}] Searching users with URL: ${searchUrl}`);

    const response = await fetchWithAuth(searchUrl);
    if (!response.ok) {
      console.error(
        `[Team ${teamId}] Search failed: ${response.status} ${response.statusText}`
      );
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();

    if (data.users && data.users.length > 0) {
      // Step 5: Build HTML manually from JSON
      let searchResultsHtml = "";
      data.users.forEach((user) => {
        const memberData = teamMemberData[user.email] || {};
        const isMember = Object.keys(memberData).length > 0;
        const memberRole = memberData.role || "member";
        const joinedAt = memberData.joined_at;
        const isCurrentUser = memberData.is_current_user || false;
        const isLastOwner = memberData.is_last_owner || false;
        const isChecked =
          selections[user.email] !== undefined
            ? selections[user.email]
            : isMember;
        const selectedRole = roleSelections[user.email] || memberRole;

        const borderClass = isMember
          ? "border-indigo-200 dark:border-indigo-800 bg-indigo-50/50 dark:bg-indigo-900/20"
          : "border-transparent";

        searchResultsHtml += `
                          <div class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 p-3 hover:bg-indigo-50 dark:hover:bg-indigo-900 rounded-md user-item border ${borderClass}" data-user-email="${escapeHtml(user.email)}">
                              <!-- Avatar Circle -->
                              <div class="flex-shrink-0">
                                  <div class="w-8 h-8 bg-gray-300 dark:bg-gray-600 rounded-full flex items-center justify-center">
                                      <span class="text-sm font-medium text-gray-700 dark:text-gray-300">${escapeHtml(user.email[0].toUpperCase())}</span>
                                  </div>
                              </div>

                              <!-- Checkbox -->
                              <input
                                  type="checkbox"
                                  name="associatedUsers"
                                  value="${escapeHtml(user.email)}"
                                  data-user-name="${escapeHtml(user.full_name || user.email)}"
                                  class="user-checkbox form-checkbox h-5 w-5 text-indigo-600 dark:bg-gray-800 dark:border-gray-600 flex-shrink-0"
                                  data-auto-check="true"
                                  ${isChecked ? "checked" : ""}
                              />

                              <!-- User Info with Badges -->
                              <div class="flex-grow min-w-0">
                                  <div class="flex items-center gap-2 flex-wrap">
                                      <span class="select-none font-medium text-gray-900 dark:text-white truncate">${escapeHtml(user.full_name || user.email)}</span>
                                      ${isCurrentUser ? '<span class="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-800 rounded-full dark:bg-blue-900 dark:text-blue-200">You</span>' : ""}
                                      ${isLastOwner ? '<span class="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-800 rounded-full dark:bg-yellow-900 dark:text-yellow-200">Last Owner</span>' : ""}
                                      ${isMember && memberRole === "owner" && !isLastOwner ? '<span class="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-800 rounded-full dark:bg-purple-900 dark:text-purple-200">Owner</span>' : ""}
                                  </div>
                                  <div class="text-sm text-gray-500 dark:text-gray-400 truncate">${escapeHtml(user.email)}</div>
                                  ${isMember && joinedAt ? `<div class="text-xs text-gray-400 dark:text-gray-500">Joined: ${formatDate(joinedAt)}</div>` : ""}
                              </div>

                              <!-- Role Selector -->
                              <select
                                  name="role_${encodeURIComponent(user.email)}"
                                  class="role-select text-sm px-2 py-1 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-white flex-shrink-0"
                              >
                                  <option value="member" ${selectedRole === "member" ? "selected" : ""}>Member</option>
                                  <option value="owner" ${selectedRole === "owner" ? "selected" : ""}>Owner</option>
                              </select>
                          </div>
                      `;
      });

      // Step 6: Replace container innerHTML
      container.innerHTML = searchResultsHtml;

      // Step 7: No need to restore selections - they're already built into the HTML
      console.log(
        `[Team ${teamId}] Rendered ${data.users.length} users from search`
      );
    } else {
      container.innerHTML =
        '<div class="text-center py-4 text-gray-500">No users found</div>';
    }
  } catch (error) {
    console.error(`[Team ${teamId}] Error searching users:`, error);
    container.innerHTML =
      '<div class="text-center py-4 text-red-600">Error searching users</div>';
  }
};

// Restore user selections after loading default list
const restoreUserSelections = function (container, selections, roleSelections) {
  try {
    const checkboxes = container.querySelectorAll(
      'input[name="associatedUsers"]'
    );
    checkboxes.forEach((cb) => {
      if (selections[cb.value] !== undefined) {
        cb.checked = selections[cb.value];
      }
    });

    const roleSelects = container.querySelectorAll(".role-select");
    roleSelects.forEach((select) => {
      const email = select.name.replace("role_", "");
      const decodedEmail = decodeURIComponent(email);
      if (roleSelections[decodedEmail]) {
        select.value = roleSelections[decodedEmail];
      }
    });

    console.log(`Restored ${Object.keys(selections).length} selections`);
  } catch (e) {
    console.error("Error restoring selections:", e);
  }
};

// Helper to format date (similar to Python strftime "%b %d, %Y")
export const formatDate = function (dateString) {
  try {
    const date = new Date(dateString);
    return date.toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch (e) {
    return dateString;
  }
};

const handleAdminUserAction = function (event) {
  const detail = event.detail || {};
  const delayMs = Number(detail.delayMs) || 0;
  setTimeout(() => {
    if (detail.closeUserEditModal && typeof hideUserEditModal === "function") {
      hideUserEditModal();
    }
    if (detail.refreshUsersList) {
      const usersList = safeGetElement("users-list-container");
      if (usersList && window.htmx) {
        window.htmx.trigger(usersList, "refreshUsers");
      }
    }
  }, delayMs);
};

export const registerAdminActionListeners = function () {
  if (!document.body) {
    return;
  }
  if (document.body.dataset.adminActionListeners === "1") {
    return;
  }
  document.body.dataset.adminActionListeners = "1";

  document.body.addEventListener("adminTeamAction", handleAdminTeamAction);
  document.body.addEventListener("adminUserAction", handleAdminUserAction);
  document.body.addEventListener("userCreated", function () {
    handleAdminUserAction({ detail: { refreshUsersList: true } });
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    const target = event.target;
    initializeAddMembersForms(target);
    // Only initialize password validation if the swapped content contains password fields
    if (target?.querySelector?.("#password-field")) {
      initializePasswordValidation(target);
    }
    if (
      target &&
      target.id &&
      target.id.startsWith("user-selector-container-")
    ) {
      const teamId = extractTeamId("user-selector-container-", target.id);
      if (teamId) {
        dedupeSelectorItems(target);
        updateAddMembersCount(teamId);
      }
    }
  });

  document.body.addEventListener("htmx:load", function (event) {
    const target = event.target;
    initializeAddMembersForms(target);
    // Only initialize password validation if the loaded content contains password fields
    if (target?.querySelector?.("#password-field")) {
      initializePasswordValidation(target);
    }
  });
};

export const initializePermissionsPanel = function () {
  // Load team data if available
  if (window.USER_TEAMS && window.USER_TEAMS.length > 0) {
    const membersList = safeGetElement("team-members-list");
    const rolesList = safeGetElement("role-assignments-list");

    if (membersList) {
      membersList.innerHTML =
        '<div class="text-sm text-gray-500 dark:text-gray-400">Use the Teams Management tab to view and manage team members.</div>';
    }

    if (rolesList) {
      rolesList.innerHTML =
        '<div class="text-sm text-gray-500 dark:text-gray-400">Use the Teams Management tab to assign roles to team members.</div>';
    }
  }
};
