import { PANEL_SEARCH_CONFIG, TOGGLE_FRAGMENT_MAP } from "./constants.js";
import { navigateAdmin } from "./navigation.js";
import { buildTableUrl, getCookie, isInactiveChecked } from "./utils.js";

// ===================================================================
// ENTITY TYPE DISPLAY NAMES
// ===================================================================
// Maps entity type keys (plural/kebab-case) to singular display names for UI messages
const ENTITY_DISPLAY_NAMES = {
  tools: "tool",
  resources: "resource",
  prompts: "prompt",
  gateways: "gateway",
  catalog: "server",
  "a2a-agents": "agent",
  agent: "agent",
  servers: "server",
  teams: "team",
  users: "user",
};

// ===================================================================
// FORM SUBMISSION AND REFRESH HANDLING
// ===================================================================
// Handles form submission (toggle/delete operations) and refreshes the table
// via HTMX. Used by both handleSubmitWithConfirmation and handleDeleteSubmit.
export const handleFormSubmitAndRefresh = async function (event, type) {
  event.preventDefault();

  // Validate PANEL_SEARCH_CONFIG registration before proceeding
  const panelConfig = PANEL_SEARCH_CONFIG[type];
  if (!panelConfig) {
    throw new Error(`No PANEL_SEARCH_CONFIG found for type: ${type}. All entity types must be registered in PANEL_SEARCH_CONFIG (constants.js) with partialPath and targetSelector.`);
  }

  const isInactiveCheckedBool = isInactiveChecked(type);
  const form = event.target;
  const teamId = new URL(window.location.href).searchParams.get("team_id");

  // Build FormData from current form state (captures any fields already
  // appended by handleDeleteSubmit such as purge_metrics).
  const formData = new FormData(form);
  formData.set("is_inactive_checked", String(isInactiveCheckedBool));
  if (teamId && !formData.has("team_id")) {
    formData.set("team_id", teamId);
  }
  const csrfToken =
    typeof getCookie === "function"
      ? getCookie("mcpgateway_csrf_token") || ""
      : "";
  if (csrfToken) {
    formData.set("csrf_token", csrfToken);
  }

  try {
    // Use redirect:'manual' so the browser does not follow the 303
    // redirect to the backend-direct URL (which bypasses the proxy).
    await fetch(form.action, {
      method: "POST",
      body: formData,
      credentials: "include", // pragma: allowlist secret
      redirect: "manual",
    });

    // Use HTMX to refresh the table instead of full page reload
    const fragment = TOGGLE_FRAGMENT_MAP[type] || type;

    // Build refresh params preserving search, tags, pagination, and filters
    const refreshParams = {
      include_inactive: isInactiveCheckedBool.toString(),
    };

    // Read current search query from DOM
    const searchInput = document.getElementById(panelConfig.searchInputId);
    if (searchInput?.value) {
      refreshParams.q = searchInput.value;
    }

    // Read current tag filter from DOM
    const tagInput = document.getElementById(panelConfig.tagInputId);
    if (tagInput?.value) {
      refreshParams.tags = tagInput.value;
    }

    // Add team_id if present
    if (teamId) {
      refreshParams.team_id = teamId;
    }

    // Trigger HTMX request to refresh the table using PANEL_SEARCH_CONFIG
    const partialPath = panelConfig.partialPath;
    const targetSelector = panelConfig.targetSelector;
    const tableName = panelConfig.tableName;

    // Use buildTableUrl to preserve pagination state
    const partialUrl = buildTableUrl(
      tableName,
      `${window.ROOT_PATH}/admin/${partialPath}`,
      refreshParams
    );

    if (window.htmx) {
      window.htmx.ajax('GET', partialUrl, {
        target: targetSelector,
        swap: 'outerHTML'
      });
    } else {
      // Fallback to full reload if HTMX not available
      const fallbackParams = new URLSearchParams();
      if (teamId) {
        fallbackParams.set("team_id", teamId);
      }
      navigateAdmin(fragment, fallbackParams);
    }
  } catch (error) {
    // Network error — still navigate so the user sees refreshed state.
    console.error("Form submit error:", error);
    const fragment = TOGGLE_FRAGMENT_MAP[type] || type;
    const params = new URLSearchParams();
    if (teamId) {
      params.set("team_id", teamId);
    }
    navigateAdmin(fragment, params);
  }
};

// Legacy alias for backward compatibility
export const handleToggleSubmit = handleFormSubmitAndRefresh;

export const handleSubmitWithConfirmation = function (event, type) {
  event.preventDefault();

  const displayName = ENTITY_DISPLAY_NAMES[type] || type;
  const confirmationMessage = `Are you sure you want to permanently delete this ${displayName}? (Deactivation is reversible, deletion is permanent)`;
  const confirmation = confirm(confirmationMessage);
  if (!confirmation) {
    return false;
  }

  return handleFormSubmitAndRefresh(event, type);
};

export const handleDeleteSubmit = function (
  event,
  type,
  name = "",
  inactiveType = ""
) {
  event.preventDefault();

  const displayName = ENTITY_DISPLAY_NAMES[type] || type;
  const targetName = name ? `${displayName} "${name}"` : `this ${displayName}`;
  const confirmationMessage = `Are you sure you want to permanently delete ${targetName}? (Deactivation is reversible, deletion is permanent)`;
  const confirmation = confirm(confirmationMessage);
  if (!confirmation) {
    return false;
  }

  const purgeConfirmation = confirm(
    `Also purge ALL metrics history for ${targetName}? This deletes raw metrics and hourly rollups and cannot be undone.`
  );
  if (purgeConfirmation) {
    const form = event.target;
    const purgeField = document.createElement("input");
    purgeField.type = "hidden";
    purgeField.name = "purge_metrics";
    purgeField.value = "true";
    form.appendChild(purgeField);
  }

  const toggleType = inactiveType || type;
  return handleFormSubmitAndRefresh(event, toggleType);
};
