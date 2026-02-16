import { isInactiveChecked } from "./utils.js";

// ===================================================================
// INACTIVE ITEMS HANDLING
// ===================================================================
export const handleToggleSubmit = function (event, type) {
  event.preventDefault();

  const isInactiveCheckedBool = isInactiveChecked(type);
  const form = event.target;
  const hiddenField = document.createElement("input");
  hiddenField.type = "hidden";
  hiddenField.name = "is_inactive_checked";
  hiddenField.value = isInactiveCheckedBool;

  form.appendChild(hiddenField);
  form.submit();
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

  // Inject team_id from URL for RBAC team context derivation (defense-in-depth)
  const teamId = new URL(window.location.href).searchParams.get("team_id");
  if (teamId) {
    const form = event.target;
    const teamField = document.createElement("input");
    teamField.type = "hidden";
    teamField.name = "team_id";
    teamField.value = teamId;
    form.appendChild(teamField);
  }

  const toggleType = inactiveType || type;
  return handleToggleSubmit(event, toggleType);
};
