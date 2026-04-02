import { updateEntityActionButtons } from "./logging.js";
import { safeGetElement } from  "./utils.js";


/**
 * ====================================================================
 * REAL-TIME GATEWAY & TOOL MONITORING (SSE)
 * Handles live status updates for Gateways and Tools
 * ====================================================================
 */


export const initializeRealTimeMonitoring = function () {
  if (!window.EventSource) {
    return;
  }

  // Connect to the admin events endpoint
  const eventSource = new EventSource(`${window.ROOT_PATH}/admin/events`);

  // --- Gateway Events ---
  // Handlers for specific states

  // eventSource.addEventListener("gateway_deactivated", (e) => handleEntityEvent("gateway", e));
  eventSource.addEventListener("gateway_activated", (e) =>
    handleEntityEvent("gateway", e)
  );
  eventSource.addEventListener("gateway_offline", (e) =>
    handleEntityEvent("gateway", e)
  );

  // --- Tool Events ---
  // Handlers for specific states

  // eventSource.addEventListener("tool_deactivated", (e) => handleEntityEvent("tool", e));
  eventSource.addEventListener("tool_activated", (e) =>
    handleEntityEvent("tool", e)
  );
  eventSource.addEventListener("tool_offline", (e) =>
    handleEntityEvent("tool", e)
  );

  eventSource.onopen = () =>
    console.log("✅ SSE Connected for Real-time Monitoring");
  eventSource.onerror = (err) =>
    console.warn("⚠️ SSE Connection issue, retrying...", err);
};

/**
 * Generic handler for entity events
 */
const handleEntityEvent = function (type, event) {
  try {
    const data = JSON.parse(event.data);
    // Log the specific event type for debugging
    // console.log(`Received ${type} event [${event.type}]:`, data);
    updateEntityStatus(type, data);
  } catch (err) {
    console.error(`Error processing ${type} event:`, err);
  }
};

/**
 * Updates the status badge and action buttons for a row
 */

const updateEntityStatus = function (type, data) {
  let row = null;

  if (type === "gateway") {
    // Gateways usually have explicit IDs
    row = safeGetElement(`gateway-row-${data.id}`);
  } else if (type === "tool") {
    // 1. Try explicit ID (fastest)
    row = safeGetElement(`tool-row-${data.id}`);

    // 2. Fallback: Search rows by looking for the ID in Action buttons
    if (!row) {
      const panel = safeGetElement("tools-panel");
      if (panel) {
        const rows = panel.querySelectorAll("table tbody tr");
        for (const tr of rows) {
          // Check data attribute if present
          if (tr.dataset.toolId === data.id) {
            row = tr;
            break;
          }

          // Check innerHTML for the UUID in action attributes
          const html = tr.innerHTML;
          if (html.includes(data.id)) {
            // Verify it's likely an ID usage (in quotes or url path)
            if (
              html.includes(`'${data.id}'`) ||
              html.includes(`"${data.id}"`) ||
              html.includes(`/${data.id}/`)
            ) {
              row = tr;
              // Optimization: Set ID on row for next time
              tr.id = `tool-row-${data.id}`;
              break;
            }
          }
        }
      }
    }
  }

  if (!row) {
    console.warn(`Could not find row for ${type} id: ${data.id}`);
    return;
  }

  // Dynamically find Status and Action columns
  const table = row.closest("table");
  let statusIndex = -1;
  let actionIndex = -1;

  if (table) {
    const headers = table.querySelectorAll("thead th");
    headers.forEach((th, index) => {
      const text = th.textContent.trim().toLowerCase();
      if (text === "status") {
        statusIndex = index;
      }
      if (text === "actions") {
        actionIndex = index;
      }
    });
  }

  // Fallback indices if headers aren't found
  if (statusIndex === -1) {
    statusIndex = type === "gateway" ? 4 : 5;
  }
  if (actionIndex === -1) {
    actionIndex = type === "gateway" ? 9 : 6;
  }

  const statusCell = row.children[statusIndex];
  const actionCell = row.children[actionIndex];

  // --- 1. Update Status Badge ---
  if (statusCell) {
    const isEnabled =
      data.enabled !== undefined ? data.enabled : data.isActive;
    const isReachable = data.reachable !== undefined ? data.reachable : true;

    statusCell.innerHTML = window.Admin.generateStatusBadgeHtml(
      isEnabled,
      isReachable,
      type
    );

    // Flash effect
    statusCell.classList.add(
      "bg-blue-50",
      "dark:bg-blue-900",
      "transition-colors",
      "duration-500"
    );
    setTimeout(() => {
      statusCell.classList.remove("bg-blue-50", "dark:bg-blue-900");
    }, 1000);
  }

  // --- 2. Update Action Buttons ---
  if (actionCell) {
    const isEnabled =
      data.enabled !== undefined ? data.enabled : data.isActive;
    updateEntityActionButtons(actionCell, type, data.id, isEnabled);
  }
};
