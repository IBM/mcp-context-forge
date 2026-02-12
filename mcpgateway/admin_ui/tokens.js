import { escapeHtml, parseErrorResponse } from "./security.js";
import {
  fetchWithTimeout,
  getCookie,
  getCurrentTeamId,
  getCurrentTeamName,
  safeGetElement,
  showNotification,
} from "./utils";

/**
 * Load tokens list from API
 */
export const loadTokensList = async function () {
  const tokensList = safeGetElement("tokens-list");
  if (!tokensList) {
    return;
  }

  try {
    tokensList.innerHTML =
      '<p class="text-gray-500 dark:text-gray-400">Loading tokens...</p>';

    const response = await fetchWithTimeout(`${window.ROOT_PATH}/tokens`, {
      headers: {
        Authorization: `Bearer ${await getAuthToken()}`,
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to load tokens: (${response.status})`);
    }

    const data = await response.json();
    displayTokensList(data.tokens);
  } catch (error) {
    console.error("Error loading tokens:", error);
    tokensList.innerHTML =
      '<div class="text-red-500">Error loading tokens: ' +
      escapeHtml(error.message) +
      "</div>";
  }
};

/**
 * Display tokens list in the UI
 */
export const displayTokensList = function (tokens) {
  const tokensList = safeGetElement("tokens-list");
  if (!tokensList) {
    return;
  }

  if (!tokens || tokens.length === 0) {
    tokensList.innerHTML =
      '<p class="text-gray-500 dark:text-gray-400">No tokens found. Create your first token above.</p>';
    return;
  }

  let tokensHTML = "";
  tokens.forEach((token) => {
    const expiresText = token.expires_at
      ? new Date(token.expires_at).toLocaleDateString()
      : "Never";
    const createdText = token.created_at
      ? new Date(token.created_at).toLocaleDateString()
      : "Never";
    const lastUsedText = token.last_used
      ? new Date(token.last_used).toLocaleDateString()
      : "Never";
    const statusBadge = token.is_active
      ? '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-100">Active</span>'
      : '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-800 dark:text-red-100">Inactive</span>';

    // Build scope badges
    const teamName = token.team_id ? getTeamNameById(token.team_id) : null;
    const teamBadge = teamName
      ? `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-800 dark:bg-purple-800 dark:text-purple-100">Team: ${escapeHtml(teamName)}</span>`
      : '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">Public-only</span>';

    const ipBadge =
      token.ip_restrictions && token.ip_restrictions.length > 0
        ? `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800 dark:bg-orange-800 dark:text-orange-100">${token.ip_restrictions.length} IP${token.ip_restrictions.length > 1 ? "s" : ""}</span>`
        : "";

    const serverBadge = token.server_id
      ? '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-800 dark:text-blue-100">Server-scoped</span>'
      : "";

    // Safely encode token data for data attribute (URL encoding preserves all characters)
    const tokenDataEncoded = encodeURIComponent(JSON.stringify(token));

    tokensHTML += `
      <div class="border border-gray-200 dark:border-gray-600 rounded-lg p-4 mb-4">
        <div class="flex justify-between items-start">
          <div class="flex-1">
            <div class="flex items-center flex-wrap gap-2">
              <h4 class="text-lg font-medium text-gray-900 dark:text-white">${escapeHtml(token.name)}</h4>
              ${statusBadge}
              ${teamBadge}
              ${serverBadge}
              ${ipBadge}
            </div>
            ${token.description ? `<p class="text-sm text-gray-600 dark:text-gray-400 mt-1">${escapeHtml(token.description)}</p>` : ""}
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-3 text-sm text-gray-500 dark:text-gray-400">
                <div>
                  <span class="font-medium">Created:</span> ${createdText}
                </div>
                <div>
                  <span class="font-medium">Expires:</span> ${expiresText}
                </div>
                <div>
                  <span class="font-medium">Last Used:</span> ${lastUsedText}
                </div>
            </div>
            ${token.server_id ? `<div class="mt-2 text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Scoped to Server:</span> ${escapeHtml(token.server_id)}</div>` : ""}
            ${token.resource_scopes && token.resource_scopes.length > 0 ? `<div class="mt-1 text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Permissions:</span> ${token.resource_scopes.map((p) => escapeHtml(p)).join(", ")}</div>` : ""}
          </div>
          <div class="flex flex-wrap gap-2 ml-4">
            <button
                data-action="token-details"
                data-token="${tokenDataEncoded}"
                class="px-3 py-1 text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 border border-gray-300 dark:border-gray-600 hover:border-gray-500 dark:hover:border-gray-400 rounded-md"
            >
              Details
            </button>
            <button
                data-action="token-usage"
                data-token-id="${escapeHtml(token.id)}"
                class="px-3 py-1 text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 border border-blue-300 dark:border-blue-600 hover:border-blue-500 dark:hover:border-blue-400 rounded-md"
            >
              Usage Stats
            </button>
            <button
                data-action="token-revoke"
                data-token-id="${escapeHtml(token.id)}"
                data-token-name="${escapeHtml(token.name)}"
                class="px-3 py-1 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 border border-red-300 dark:border-red-600 hover:border-red-500 dark:hover:border-red-400 rounded-md"
            >
              Revoke
            </button>
          </div>
        </div>
      </div>
    `;
  });

  tokensList.innerHTML = tokensHTML;

  // Attach event handlers via delegation (avoids inline JS and XSS risks)
  setupTokenListEventHandlers(tokensList);
};

/**
 * Set up event handlers for token list buttons using event delegation.
 * This avoids inline onclick handlers and associated XSS risks.
 * Uses a one-time guard to prevent duplicate handlers on repeated renders.
 * @param {HTMLElement} container - The tokens list container element
 */
const setupTokenListEventHandlers = function (container) {
  // Guard against duplicate handlers on repeated renders
  if (container.dataset.handlersAttached === "true") {
    return;
  }
  container.dataset.handlersAttached = "true";

  container.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) {
      return;
    }

    const action = button.dataset.action;

    if (action === "token-details") {
      const tokenData = button.dataset.token;
      if (tokenData) {
        try {
          const token = JSON.parse(decodeURIComponent(tokenData));
          showTokenDetailsModal(token);
        } catch (e) {
          console.error("Failed to parse token data:", e);
        }
      }
    } else if (action === "token-usage") {
      const tokenId = button.dataset.tokenId;
      if (tokenId) {
        viewTokenUsage(tokenId);
      }
    } else if (action === "token-revoke") {
      const tokenId = button.dataset.tokenId;
      const tokenName = button.dataset.tokenName;
      if (tokenId) {
        revokeToken(tokenId, tokenName || "");
      }
    }
  });
};

/**
 * Update the team scoping warning/info visibility based on team selection
 */
export const updateTeamScopingWarning = function () {
  const warningDiv = safeGetElement("team-scoping-warning");
  const infoDiv = safeGetElement("team-scoping-info");
  const teamNameSpan = safeGetElement("selected-team-name");

  if (!warningDiv || !infoDiv) {
    return;
  }

  const currentTeamId = getCurrentTeamId();

  if (!currentTeamId) {
    // Show warning when "All Teams" is selected
    warningDiv.classList.remove("hidden");
    infoDiv.classList.add("hidden");
  } else {
    // Hide warning and show info when a specific team is selected
    warningDiv.classList.add("hidden");
    infoDiv.classList.remove("hidden");

    // Get team name to display
    const teamName = getCurrentTeamName() || currentTeamId;
    if (teamNameSpan) {
      teamNameSpan.textContent = teamName;
    }
  }
};

/**
 * Monitor team selection changes using Alpine.js watcher
 */
export const initializeTeamScopingMonitor = function () {
  // Use Alpine.js $watch to monitor team selection changes
  document.addEventListener("alpine:init", () => {
    const teamSelector = document.querySelector('[x-data*="selectedTeam"]');
    if (teamSelector && window.Alpine) {
      // The Alpine component will notify us of changes
      const checkInterval = setInterval(() => {
        updateTeamScopingWarning();
      }, 500); // Check every 500ms

      // Store interval ID for cleanup if needed
      window.Admin._teamMonitorInterval = checkInterval;
    }
  });

  // Also update when tokens tab is shown
  document.addEventListener("DOMContentLoaded", () => {
    const tokensTab = document.querySelector('a[href="#tokens"]');
    if (tokensTab) {
      tokensTab.addEventListener("click", () => {
        setTimeout(updateTeamScopingWarning, 100);
      });
    }
  });
};

/**
 * Set up create token form handling
 */
export const setupCreateTokenForm = function () {
  const form = safeGetElement("create-token-form");
  if (!form) {
    return;
  }

  // Update team scoping warning/info display
  updateTeamScopingWarning();

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    // User can create public-only tokens in that context
    await createToken(form);
  });
};

/**
 * Validate an IP address or CIDR notation string.
 * @param {string} value - The IP/CIDR string to validate
 * @returns {boolean} True if valid IPv4/IPv6 address or CIDR notation
 */
const isValidIpOrCidr = function (value) {
  if (!value || typeof value !== "string") {
    return false;
  }

  const trimmed = value.trim();

  // IPv4 with optional CIDR (e.g., 192.168.1.0/24 or 192.168.1.1)
  const ipv4Segment = "(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)";
  const ipv4Pattern = new RegExp(
    `^(?:${ipv4Segment}\\.){3}${ipv4Segment}(?:\\/(?:[0-9]|[1-2][0-9]|3[0-2]))?$`
  );

  // IPv6 with optional CIDR (supports compressed forms and IPv4-embedded)
  const ipv6Segment = "[0-9A-Fa-f]{1,4}";
  const ipv4Embedded = `(?:${ipv4Segment}\\.){3}${ipv4Segment}`;
  const ipv6Pattern = new RegExp(
    "^(?:" +
      `(?:${ipv6Segment}:){7}${ipv6Segment}|` +
      `(?:${ipv6Segment}:){1,7}:|` +
      `(?:${ipv6Segment}:){1,6}:${ipv6Segment}|` +
      `(?:${ipv6Segment}:){1,5}(?::${ipv6Segment}){1,2}|` +
      `(?:${ipv6Segment}:){1,4}(?::${ipv6Segment}){1,3}|` +
      `(?:${ipv6Segment}:){1,3}(?::${ipv6Segment}){1,4}|` +
      `(?:${ipv6Segment}:){1,2}(?::${ipv6Segment}){1,5}|` +
      `${ipv6Segment}:(?::${ipv6Segment}){1,6}|` +
      `:(?::${ipv6Segment}){1,7}|` +
      "::|" +
      `(?:${ipv6Segment}:){1,4}:${ipv4Embedded}|` +
      `::(?:ffff(?::0{1,4}){0,1}:)?${ipv4Embedded}` +
      ")(?:\\/(?:[0-9]|[1-9][0-9]|1[01][0-9]|12[0-8]))?$"
  );

  return ipv4Pattern.test(trimmed) || ipv6Pattern.test(trimmed);
};

/**
 * Validate a permission scope string.
 * Permissions should follow format: resource.action (e.g., tools.read, resources.write)
 * Also allows wildcard (*) for full access.
 * @param {string} value - The permission string to validate
 * @returns {boolean} True if valid permission format
 */
const isValidPermission = function (value) {
  if (!value || typeof value !== "string") {
    return false;
  }

  const trimmed = value.trim();

  // Allow wildcard
  if (trimmed === "*") {
    return true;
  }

  // Permission format: resource.action (alphanumeric with underscores, dot-separated)
  // Examples: tools.read, resources.write, prompts.list, tools.execute
  const permissionPattern = /^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/i;

  return permissionPattern.test(trimmed);
};

/**
 * Create a new API token
 */
// Create a new API token
const createToken = async function (form) {
  const formData = new FormData(form);
  const submitButton = form.querySelector('button[type="submit"]');
  const originalText = submitButton.textContent;

  try {
    submitButton.textContent = "Creating...";
    submitButton.disabled = true;

    // Get current team ID (null means "All Teams" = public-only token)
    const currentTeamId = getCurrentTeamId();

    // Build request payload
    const payload = {
      name: formData.get("name"),
      description: formData.get("description") || null,
      expires_in_days: formData.get("expires_in_days")
        ? parseInt(formData.get("expires_in_days"))
        : null,
      tags: [],
      team_id: currentTeamId || null, // null = public-only token
    };

    // Add scoping if provided
    const scope = {};

    if (formData.get("server_id")) {
      scope.server_id = formData.get("server_id");
    }

    // Parse and validate IP restrictions
    if (formData.get("ip_restrictions")) {
      const ipRestrictions = formData.get("ip_restrictions").trim();
      if (ipRestrictions) {
        const ipList = ipRestrictions
          .split(",")
          .map((ip) => ip.trim())
          .filter((ip) => ip.length > 0);

        // Validate each IP/CIDR
        const invalidIps = ipList.filter((ip) => !isValidIpOrCidr(ip));
        if (invalidIps.length > 0) {
          throw new Error(
            `Invalid IP address or CIDR format: ${invalidIps.join(", ")}. ` +
              "Use formats like 192.168.1.0/24 or 10.0.0.1"
          );
        }
        scope.ip_restrictions = ipList;
      } else {
        scope.ip_restrictions = [];
      }
    } else {
      scope.ip_restrictions = [];
    }

    // Parse and validate permissions
    if (formData.get("permissions")) {
      const permList = formData
        .get("permissions")
        .split(",")
        .map((p) => p.trim())
        .filter((p) => p.length > 0);

      // Validate each permission
      const invalidPerms = permList.filter((p) => !isValidPermission(p));
      if (invalidPerms.length > 0) {
        throw new Error(
          `Invalid permission format: ${invalidPerms.join(", ")}. ` +
            "Use formats like tools.read, resources.write, or * for full access"
        );
      }
      scope.permissions = permList;
    } else {
      scope.permissions = [];
    }

    scope.time_restrictions = {};
    scope.usage_limits = {};
    payload.scope = scope;

    const response = await fetchWithTimeout(`${window.ROOT_PATH}/tokens`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${await getAuthToken()}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errorMsg = await parseErrorResponse(
        response,
        `Failed to create token (${response.status})`
      );
      throw new Error(errorMsg);
    }

    const result = await response.json();
    showTokenCreatedModal(result);
    form.reset();
    await loadTokensList();

    // Show appropriate success message
    const tokenType = currentTeamId ? "team-scoped" : "public-only";
    showNotification(`${tokenType} token created successfully!`, "success");
  } catch (error) {
    console.error("Error creating token:", error);
    showNotification(`Error creating token: ${error.message}`, "error");
  } finally {
    submitButton.textContent = originalText;
    submitButton.disabled = false;
  }
};

/**
 * Show modal with new token (one-time display)
 */
const showTokenCreatedModal = function (tokenData) {
  const modal = document.createElement("div");
  modal.className =
    "fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50";
  modal.innerHTML = `
            <div class="relative top-20 mx-auto p-5 border w-11/12 max-w-lg shadow-lg rounded-md bg-white dark:bg-gray-800">
                <div class="mt-3">
                    <div class="flex items-center justify-between mb-4">
                        <h3 class="text-lg font-medium text-gray-900 dark:text-white">Token Created Successfully</h3>
                        <button onclick="this.closest('.fixed').remove()" class="text-gray-400 hover:text-gray-600">
                            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                            </svg>
                        </button>
                    </div>

                    <div class="bg-yellow-50 dark:bg-yellow-900 border border-yellow-200 dark:border-yellow-700 rounded-md p-4 mb-4">
                        <div class="flex">
                            <div class="flex-shrink-0">
                                <svg class="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                                    <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
                                </svg>
                            </div>
                            <div class="ml-3">
                                <h3 class="text-sm font-medium text-yellow-800 dark:text-yellow-200">
                                    Important: Save your token now!
                                </h3>
                                <div class="mt-2 text-sm text-yellow-700 dark:text-yellow-300">
                                    This is the only time you will be able to see this token. Make sure to save it in a secure location.
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                            Your API Token:
                        </label>
                        <div class="flex">
                            <input
                                type="text"
                                value="${tokenData.access_token}"
                                readonly
                                class="flex-1 p-2 border border-gray-300 dark:border-gray-600 rounded-l-md bg-gray-50 dark:bg-gray-700 text-sm font-mono"
                                id="new-token-value"
                            />
                            <button
                                onclick="Admin.copyToClipboard('new-token-value')"
                                class="px-3 py-2 bg-indigo-600 text-white text-sm rounded-r-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                            >
                                Copy
                            </button>
                        </div>
                    </div>

                    <div class="text-sm text-gray-600 dark:text-gray-400 mb-4">
                        <strong>Token Name:</strong> ${escapeHtml(tokenData.token.name || "Unnamed Token")}<br/>
                        <strong>Expires:</strong> ${tokenData.token.expires_at ? new Date(tokenData.token.expires_at).toLocaleDateString() : "Never"}
                    </div>

                    <div class="flex justify-end">
                        <button
                            onclick="this.closest('.fixed').remove()"
                            class="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        >
                            I've Saved It
                        </button>
                    </div>
                </div>
            </div>
        `;

  document.body.appendChild(modal);

  // Focus the token input for easy selection
  const tokenInput = modal.querySelector("#new-token-value");
  tokenInput.focus();
  tokenInput.select();
};

/**
 * Revoke a token
 */
const revokeToken = async function (tokenId, tokenName) {
  if (
    !confirm(
      `Are you sure you want to revoke the token "${tokenName}"? This action cannot be undone.`
    )
  ) {
    return;
  }

  try {
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/tokens/${tokenId}`,
      {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          reason: "Revoked by user via admin interface",
        }),
      }
    );

    if (!response.ok) {
      const errorMsg = await parseErrorResponse(
        response,
        `Failed to revoke token: ${response.status}`
      );
      throw new Error(errorMsg);
    }

    showNotification("Token revoked successfully", "success");
    await loadTokensList();
  } catch (error) {
    console.error("Error revoking token:", error);
    showNotification(`Error revoking token: ${error.message}`, "error");
  }
};

/**
 * View token usage statistics
 */
const viewTokenUsage = async function (tokenId) {
  try {
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/tokens/${tokenId}/usage`,
      {
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
          "Content-Type": "application/json",
        },
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to load usage stats: ${response.status}`);
    }

    const stats = await response.json();
    showUsageStatsModal(stats);
  } catch (error) {
    console.error("Error loading usage stats:", error);
    showNotification(`Error loading usage stats: ${error.message}`, "error");
  }
};

/**
 * Show usage statistics modal
 */
const showUsageStatsModal = function (stats) {
  const modal = document.createElement("div");
  modal.className =
    "fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50";
  modal.innerHTML = `
            <div class="relative top-20 mx-auto p-5 border w-11/12 max-w-2xl shadow-lg rounded-md bg-white dark:bg-gray-800">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-lg font-medium text-gray-900 dark:text-white">Token Usage Statistics (Last ${stats.period_days} Days)</h3>
                    <button onclick="this.closest('.fixed').remove()" class="text-gray-400 hover:text-gray-600">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                    <div class="bg-blue-50 dark:bg-blue-900 p-4 rounded-lg">
                        <div class="text-2xl font-bold text-blue-600 dark:text-blue-300">${stats.total_requests}</div>
                        <div class="text-sm text-blue-600 dark:text-blue-400">Total Requests</div>
                    </div>
                    <div class="bg-green-50 dark:bg-green-900 p-4 rounded-lg">
                        <div class="text-2xl font-bold text-green-600 dark:text-green-300">${stats.successful_requests}</div>
                        <div class="text-sm text-green-600 dark:text-green-400">Successful</div>
                    </div>
                    <div class="bg-red-50 dark:bg-red-900 p-4 rounded-lg">
                        <div class="text-2xl font-bold text-red-600 dark:text-red-300">${stats.blocked_requests}</div>
                        <div class="text-sm text-red-600 dark:text-red-400">Blocked</div>
                    </div>
                    <div class="bg-purple-50 dark:bg-purple-900 p-4 rounded-lg">
                        <div class="text-2xl font-bold text-purple-600 dark:text-purple-300">${Math.round(stats.success_rate * 100)}%</div>
                        <div class="text-sm text-purple-600 dark:text-purple-400">Success Rate</div>
                    </div>
                </div>

                <div class="mb-4">
                    <h4 class="text-md font-medium text-gray-900 dark:text-white mb-2">Average Response Time</h4>
                    <div class="text-lg text-gray-700 dark:text-gray-300">${stats.average_response_time_ms}ms</div>
                </div>

                ${
  stats.top_endpoints && stats.top_endpoints.length > 0
    ? `
                    <div class="mb-4">
                        <h4 class="text-md font-medium text-gray-900 dark:text-white mb-2">Top Endpoints</h4>
                        <div class="space-y-2">
                            ${stats.top_endpoints
    .map(
      ([endpoint, count]) => `
                                <div class="flex justify-between items-center p-2 bg-gray-50 dark:bg-gray-700 rounded">
                                    <span class="font-mono text-sm">${escapeHtml(endpoint)}</span>
                                    <span class="text-sm font-medium">${count} requests</span>
                                </div>
                            `
    )
    .join("")}
                        </div>
                    </div>
                `
    : ""
}

                <div class="flex justify-end">
                    <button
                        onclick="this.closest('.fixed').remove()"
                        class="px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-500"
                    >
                        Close
                    </button>
                </div>
            </div>
        `;

  document.body.appendChild(modal);
};

/**
 * Get team name by team ID from cached team data
 * @param {string} teamId - The team ID to look up
 * @returns {string} Team name or truncated ID if not found
 */
export const getTeamNameById = function (teamId) {
  if (!teamId) {
    return null;
  }

  // Try from window.USERTEAMSDATA (most reliable source)
  if (window.USERTEAMSDATA && Array.isArray(window.USERTEAMSDATA)) {
    const teamObj = window.USERTEAMSDATA.find((t) => t.id === teamId);
    if (teamObj) {
      return teamObj.name;
    }
  }

  // Try from Alpine.js component
  const teamSelector = document.querySelector('[x-data*="selectedTeam"]');
  if (
    teamSelector &&
    teamSelector._x_dataStack &&
    teamSelector._x_dataStack[0]
  ) {
    const alpineData = teamSelector._x_dataStack[0];
    if (alpineData.teams && Array.isArray(alpineData.teams)) {
      const teamObj = alpineData.teams.find((t) => t.id === teamId);
      if (teamObj) {
        return teamObj.name;
      }
    }
  }

  // Fallback: return truncated ID
  return teamId.substring(0, 8) + "...";
};

/**
 * Show token details modal with full token information
 * @param {Object} token - The token object with all fields
 */
export const showTokenDetailsModal = function (token) {
  const formatDate = (dateStr) => {
    if (!dateStr) {
      return "Never";
    }
    return new Date(dateStr).toLocaleString();
  };

  const formatList = (list) => {
    if (!list || list.length === 0) {
      return "None";
    }
    return list
      .map((item) => `<li class="ml-4">• ${escapeHtml(item)}</li>`)
      .join("");
  };

  const formatJson = (obj) => {
    if (!obj || Object.keys(obj).length === 0) {
      return "None";
    }
    return `<pre class="bg-gray-100 dark:bg-gray-700 p-2 rounded text-xs overflow-x-auto">${escapeHtml(JSON.stringify(obj, null, 2))}</pre>`;
  };

  const teamName = token.team_id ? getTeamNameById(token.team_id) : null;
  const statusClass = token.is_active
    ? "bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-100"
    : "bg-red-100 text-red-800 dark:bg-red-800 dark:text-red-100";
  const statusText = token.is_active ? "Active" : "Inactive";

  const modal = document.createElement("div");
  modal.className =
    "fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50";
  modal.innerHTML = `
            <div class="relative top-10 mx-auto p-5 border w-11/12 max-w-2xl shadow-lg rounded-md bg-white dark:bg-gray-800 mb-10">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-lg font-medium text-gray-900 dark:text-white">Token Details</h3>
                    <button data-action="close-modal" class="text-gray-400 hover:text-gray-600">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <!-- Basic Information -->
                <div class="mb-6">
                    <h4 class="text-md font-semibold text-gray-900 dark:text-white mb-3 border-b border-gray-200 dark:border-gray-600 pb-2">Basic Information</h4>
                    <div class="grid grid-cols-1 gap-2 text-sm">
                        <div class="flex items-center">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">ID:</span>
                            <code class="bg-gray-100 dark:bg-gray-700 px-2 py-0.5 rounded text-xs flex-1 overflow-hidden text-ellipsis">${escapeHtml(token.id)}</code>
                            <button data-action="copy-id" data-copy-value="${escapeHtml(token.id)}"
                                    class="ml-2 px-2 py-0.5 text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 border border-blue-300 dark:border-blue-600 rounded">
                                Copy
                            </button>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Name:</span>
                            <span class="text-gray-900 dark:text-white">${escapeHtml(token.name)}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Description:</span>
                            <span class="text-gray-600 dark:text-gray-400">${token.description ? escapeHtml(token.description) : "None"}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Created by:</span>
                            <span class="text-gray-900 dark:text-white">${escapeHtml(token.user_email || "Unknown")}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Team:</span>
                            <span class="text-gray-900 dark:text-white">${teamName ? `${escapeHtml(teamName)} <code class="text-xs text-gray-500">(${escapeHtml(token.team_id.substring(0, 8))}...)</code>` : "None (Public-only)"}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Created:</span>
                            <span class="text-gray-600 dark:text-gray-400">${formatDate(token.created_at)}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Expires:</span>
                            <span class="text-gray-600 dark:text-gray-400">${formatDate(token.expires_at)}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Last Used:</span>
                            <span class="text-gray-600 dark:text-gray-400">${formatDate(token.last_used)}</span>
                        </div>
                        <div class="flex items-center">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Status:</span>
                            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusClass}">${statusText}</span>
                        </div>
                    </div>
                </div>

                <!-- Scope & Restrictions -->
                <div class="mb-6">
                    <h4 class="text-md font-semibold text-gray-900 dark:text-white mb-3 border-b border-gray-200 dark:border-gray-600 pb-2">Scope & Restrictions</h4>
                    <div class="grid grid-cols-1 gap-3 text-sm">
                        <div>
                            <span class="font-medium text-gray-700 dark:text-gray-300">Server:</span>
                            <span class="ml-2 text-gray-600 dark:text-gray-400">${token.server_id ? escapeHtml(token.server_id) : "All servers"}</span>
                        </div>
                        <div>
                            <span class="font-medium text-gray-700 dark:text-gray-300">Permissions:</span>
                            ${
  token.resource_scopes &&
                              token.resource_scopes.length > 0
    ? `<ul class="mt-1 text-gray-600 dark:text-gray-400">${formatList(token.resource_scopes)}</ul>`
    : '<span class="ml-2 text-gray-600 dark:text-gray-400">All (no restrictions)</span>'
}
                        </div>
                        <div>
                            <span class="font-medium text-gray-700 dark:text-gray-300">IP Restrictions:</span>
                            ${
  token.ip_restrictions &&
                              token.ip_restrictions.length > 0
    ? `<ul class="mt-1 text-gray-600 dark:text-gray-400">${formatList(token.ip_restrictions)}</ul>`
    : '<span class="ml-2 text-gray-600 dark:text-gray-400">None</span>'
}
                        </div>
                        <div>
                            <span class="font-medium text-gray-700 dark:text-gray-300">Time Restrictions:</span>
                            <div class="mt-1">${formatJson(token.time_restrictions)}</div>
                        </div>
                        <div>
                            <span class="font-medium text-gray-700 dark:text-gray-300">Usage Limits:</span>
                            <div class="mt-1">${formatJson(token.usage_limits)}</div>
                        </div>
                    </div>
                </div>

                <!-- Tags -->
                ${
  token.tags && token.tags.length > 0
    ? `
                <div class="mb-6">
                    <h4 class="text-md font-semibold text-gray-900 dark:text-white mb-3 border-b border-gray-200 dark:border-gray-600 pb-2">Tags</h4>
                    <div class="flex flex-wrap gap-2">
                        ${token.tags
    .map((tag) => {
      const raw =
                              typeof tag === "object" && tag !== null
                                ? tag.id || tag.label || JSON.stringify(tag)
                                : tag;
      return `<span class="px-2 py-1 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 text-xs rounded">${escapeHtml(raw)}</span>`;
    })
    .join("")}
                    </div>
                </div>
                `
    : ""
}

                <!-- Revocation Details (if revoked) -->
                ${
  token.is_revoked
    ? `
                <div class="mb-6">
                    <h4 class="text-md font-semibold text-red-600 dark:text-red-400 mb-3 border-b border-red-200 dark:border-red-600 pb-2">Revocation Details</h4>
                    <div class="grid grid-cols-1 gap-2 text-sm bg-red-50 dark:bg-red-900/20 p-3 rounded">
                        <div class="flex">
                            <span class="font-medium text-red-700 dark:text-red-300 w-28">Revoked at:</span>
                            <span class="text-red-600 dark:text-red-400">${formatDate(token.revoked_at)}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-red-700 dark:text-red-300 w-28">Revoked by:</span>
                            <span class="text-red-600 dark:text-red-400">${token.revoked_by ? escapeHtml(token.revoked_by) : "Unknown"}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-red-700 dark:text-red-300 w-28">Reason:</span>
                            <span class="text-red-600 dark:text-red-400">${token.revocation_reason ? escapeHtml(token.revocation_reason) : "No reason provided"}</span>
                        </div>
                    </div>
                </div>
                `
    : ""
}

                <div class="flex justify-end">
                    <button
                        data-action="close-modal"
                        class="px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-500"
                    >
                        Close
                    </button>
                </div>
            </div>
        `;

  document.body.appendChild(modal);
  // Attach event handlers (avoids inline JS and XSS risks)
  modal.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) {
      return;
    }

    const action = button.dataset.action;

    if (action === "close-modal") {
      modal.remove();
    } else if (action === "copy-id") {
      const value = button.dataset.copyValue;
      if (value) {
        navigator.clipboard.writeText(value).then(() => {
          button.textContent = "Copied!";
          setTimeout(() => {
            button.textContent = "Copy";
          }, 1500);
        });
      }
    }
  });
};

/**
 * Get auth token from storage or user input
 */
export const getAuthToken = async function () {
  // Use the same authentication method as the rest of the admin interface
  let token = getCookie("jwt_token");

  // Try alternative cookie names if primary not found
  if (!token) {
    token = getCookie("token");
  }

  // Fallback to localStorage for compatibility
  if (!token) {
    token = localStorage.getItem("auth_token");
  }
  return token || "";
};

/**
 * Fetch helper that always includes auth context.
 * Ensures HTTP-only cookies are sent even when JS cannot read them.
 */
export const fetchWithAuth = async function (url, options = {}) {
  const opts = { ...options };
  // Always send same-origin cookies unless caller overrides explicitly
  opts.credentials = options.credentials || "same-origin";

  // Clone headers to avoid mutating caller-provided object
  const headers = new Headers(options.headers || {});
  const token = await getAuthToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  opts.headers = headers;

  return fetch(url, opts);
};
