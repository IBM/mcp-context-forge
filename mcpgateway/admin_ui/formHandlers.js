import { TOGGLE_FRAGMENT_MAP } from "./constants.js";
import { navigateAdmin } from "./navigation.js";
import { getCookie, isInactiveChecked } from "./utils.js";

// ===================================================================
// INACTIVE ITEMS HANDLING
// ===================================================================
export const handleToggleSubmit = async function (event, type) {
  event.preventDefault();

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
    const params = new URLSearchParams();
    if (isInactiveCheckedBool) {
      params.set("include_inactive", "true");
    }
    if (teamId) {
      params.set("team_id", teamId);
    }

    // Trigger HTMX request to refresh the table
    const tableId = `${type}-table`;
    const partialUrl = `${window.ROOT_PATH}/admin/${type}/partial?${params.toString()}`;

    if (window.htmx) {
      window.htmx.ajax('GET', partialUrl, {
        target: `#${tableId}`,
        swap: 'outerHTML'
      });
    } else {
      // Fallback to full reload if HTMX not available
      navigateAdmin(fragment, params);
    }
  } catch (e) {
    // Network error — still navigate so the user sees refreshed state.
    console.error("Toggle submit error:", e);
    const fragment = TOGGLE_FRAGMENT_MAP[type] || type;
    const params = new URLSearchParams();
    if (teamId) {
      params.set("team_id", teamId);
    }
    navigateAdmin(fragment, params);
  }
};

export const handleSubmitWithConfirmation = function (event, type) {
  event.preventDefault();

  const confirmationMessage = `Are you sure you want to permanently delete this ${type}? (Deactivation is reversible, deletion is permanent)`;
  const confirmation = confirm(confirmationMessage);
  if (!confirmation) {
    return false;
  }

  return handleToggleSubmit(event, type);
};

export const handleDeleteSubmit = function (
  event,
  type,
  name = "",
  inactiveType = ""
) {
  event.preventDefault();

  const targetName = name ? `${type} "${name}"` : `this ${type}`;
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
  return handleToggleSubmit(event, toggleType);
};
