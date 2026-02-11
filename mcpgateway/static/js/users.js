// ===================================================================
// USER MANAGEMENT FUNCTIONS
// ===================================================================

import { escapeHtml } from "./security";
import { fetchWithAuth, getAuthToken } from "./tokens";
import { safeGetElement } from "./utils";

/**
 * Show user edit modal and load edit form
 */
export const showUserEditModal = function (userEmail) {
  const modal = safeGetElement("user-edit-modal");
  if (modal) {
    modal.style.display = "block";
    modal.classList.remove("hidden");
  }
};

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

// Team edit modal functions
export const showTeamEditModal = async function (teamId) {
  // Get the root path by extracting it from the current pathname
  let rootPath = window.location.pathname;
  const adminIndex = rootPath.lastIndexOf("/admin");
  if (adminIndex !== -1) {
    rootPath = rootPath.substring(0, adminIndex);
  } else {
    rootPath = "";
  }

  // Construct the full URL - ensure it starts with /
  const url = (rootPath || "") + "/admin/teams/" + teamId + "/edit";

  // Load the team edit form via HTMX
  fetch(url, {
    method: "GET",
    headers: {
      Authorization: "Bearer " + (await getAuthToken()),
    },
  })
    .then((response) => response.text())
    .then((html) => {
      safeGetElement("team-edit-modal-content").innerHTML = html;
      document.getElementById("team-edit-modal").classList.remove("hidden");
    })
    .catch((error) => {
      console.error("Error loading team edit form:", error);
    });
};

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
export const restoreUserSelections = function (container, selections, roleSelections) {
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
        const params = new URLSearchParams();
        params.set("page", "1"); // Reset to first page on action
        if (typeof getTeamsPerPage === "function") {
          params.set("per_page", Admin.getTeamsPerPage().toString());
        }
        // Preserve search query from input field
        const searchInput = safeGetElement("team-search");
        if (searchInput && searchInput.value.trim()) {
          params.set("q", searchInput.value.trim());
        }
        // Preserve relationship filter
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

export const handleAdminUserAction = function (event) {
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

  document.body.addEventListener(
    "adminTeamAction",
    handleAdminTeamAction
  );
  document.body.addEventListener(
    "adminUserAction",
    handleAdminUserAction
  );
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
      Admin.initializePasswordValidation(target);
    }
  });
};

// Logs refresh function
export const refreshLogs = function () {
  const logsSection = safeGetElement("logs");
  if (logsSection && typeof window.htmx !== "undefined") {
    // Trigger HTMX refresh on the logs section
    window.htmx.trigger(logsSection, "refresh");
  }
};

// User edit modal functions (already defined above)
// Functions are already exposed to global scope

// Team permissions functions are implemented in the admin.html template
// Remove placeholder functions to avoid overriding template functionality

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
