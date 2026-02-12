import {
  PERFORMANCE_AGGREGATION_OPTIONS,
  PERFORMANCE_HISTORY_HOURS,
} from "./constants.js";
import { filterGatewaysTable } from "./filters.js";
import { escapeHtml } from "./security.js";
import { fetchWithAuth } from "./tokens.js";
import {
  formatTimestamp,
  getRootPath,
  safeGetElement,
  showToast,
  truncateText,
} from "./utils.js";

// ============================================================================
// Structured Logging UI Functions
// ============================================================================

// Current log search state
let currentLogPage = 0;
const currentLogLimit = 50;
// eslint-disable-next-line no-unused-vars
let currentLogFilters = {};
let currentPerformanceAggregationKey = "5m";

export const getPerformanceAggregationConfig = function (
  rangeKey = currentPerformanceAggregationKey
) {
  return (
    PERFORMANCE_AGGREGATION_OPTIONS[rangeKey] ||
    PERFORMANCE_AGGREGATION_OPTIONS["5m"]
  );
};

export const getPerformanceAggregationLabel = function (
  rangeKey = currentPerformanceAggregationKey
) {
  return getPerformanceAggregationConfig(rangeKey).label;
};

export const getPerformanceAggregationQuery = function (
  rangeKey = currentPerformanceAggregationKey
) {
  return getPerformanceAggregationConfig(rangeKey).query;
};

export const syncPerformanceAggregationSelect = function () {
  const select = safeGetElement("performance-aggregation-select");
  if (select && select.value !== currentPerformanceAggregationKey) {
    select.value = currentPerformanceAggregationKey;
  }
};

export const setPerformanceAggregationVisibility = function (shouldShow) {
  const controls = safeGetElement("performance-aggregation-controls");
  if (!controls) {
    return;
  }
  if (shouldShow) {
    controls.classList.remove("hidden");
  } else {
    controls.classList.add("hidden");
  }
};

export const setLogFiltersVisibility = function (shouldShow) {
  const filters = safeGetElement("log-filters");
  if (!filters) {
    return;
  }
  if (shouldShow) {
    filters.classList.remove("hidden");
  } else {
    filters.classList.add("hidden");
  }
};

export const handlePerformanceAggregationChange = function (event) {
  const selectedKey = event?.target?.value;
  if (selectedKey && PERFORMANCE_AGGREGATION_OPTIONS[selectedKey]) {
    showPerformanceMetrics(selectedKey);
  }
};

/**
 * Search structured logs with filters
 */
export const searchStructuredLogs = async function () {
  setPerformanceAggregationVisibility(false);
  setLogFiltersVisibility(true);
  const levelFilter = safeGetElement("log-level-filter")?.value;
  const componentFilter = safeGetElement("log-component-filter")?.value;
  const searchQuery = safeGetElement("log-search")?.value;

  // Restore default log table headers (in case we're coming from performance metrics view)
  restoreLogTableHeaders();

  // Build search request
  const searchRequest = {
    limit: currentLogLimit,
    offset: currentLogPage * currentLogLimit,
    sort_by: "timestamp",
    sort_order: "desc",
  };

  // Only add filters if they have actual values (not empty strings)
  if (searchQuery && searchQuery.trim() !== "") {
    const trimmedSearch = searchQuery.trim();
    // Check if search is a correlation ID (32 hex chars or UUID format) or text search
    const correlationIdPattern =
      /^([0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;
    if (correlationIdPattern.test(trimmedSearch)) {
      searchRequest.correlation_id = trimmedSearch;
    } else {
      searchRequest.search_text = trimmedSearch;
    }
  }
  if (levelFilter && levelFilter !== "") {
    searchRequest.level = [levelFilter];
  }
  if (componentFilter && componentFilter !== "") {
    searchRequest.component = [componentFilter];
  }

  // Store filters for pagination
  currentLogFilters = searchRequest;

  try {
    const response = await fetchWithAuth(`${getRootPath()}/api/logs/search`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(searchRequest),
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error("API Error Response:", errorText);
      throw new Error(
        `Failed to search logs: ${response.statusText} - ${errorText}`
      );
    }

    const data = await response.json();
    displayLogResults(data);
  } catch (error) {
    console.error("Error searching logs:", error);
    showToast("Failed to search logs: " + error.message, "error");
    safeGetElement("logs-tbody").innerHTML = `
<tr><td colspan="7" class="px-4 py-4 text-center text-red-600 dark:text-red-400">
❌ Error: ${escapeHtml(error.message)}
</td></tr>
`;
  }
};

/**
 * Display log search results
 */
export const displayLogResults = function (data) {
  const tbody = safeGetElement("logs-tbody");
  const logCount = safeGetElement("log-count");
  const logStats = safeGetElement("log-stats");
  const prevButton = safeGetElement("prev-page");
  const nextButton = safeGetElement("next-page");

  // Ensure default headers are shown for log view
  restoreLogTableHeaders();

  if (!data.results || data.results.length === 0) {
    tbody.innerHTML = `
      <tr><td colspan="7" class="px-4 py-8 text-center text-gray-500 dark:text-gray-400">
        📭 No logs found matching your criteria
      </td></tr>
    `;
    logCount.textContent = "0 logs";
    logStats.innerHTML = '<span class="text-sm">No results</span>';
    return;
  }

  // Update stats
  logCount.textContent = `${data.total.toLocaleString()} logs`;
  const start = currentLogPage * currentLogLimit + 1;
  const end = Math.min(start + data.results.length - 1, data.total);
  logStats.innerHTML = `
    <span class="text-sm">
      Showing ${start}-${end} of ${data.total.toLocaleString()} logs
    </span>
  `;

  // Update pagination buttons
  prevButton.disabled = currentLogPage === 0;
  nextButton.disabled = end >= data.total;

  // Render log entries
  tbody.innerHTML = data.results
    .map((log) => {
      const levelClass = getLogLevelClass(log.level);
      const durationDisplay = log.duration_ms
        ? `${log.duration_ms.toFixed(2)}ms`
        : "-";
      const correlationId = log.correlation_id || "-";
      const userDisplay = log.user_email || log.user_id || "-";

      return `
      <tr class="hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
        onclick="Admin.showLogDetails('${log.id}', '${escapeHtml(log.correlation_id || "")}')">
        <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
          ${formatTimestamp(log.timestamp)}
        </td>
        <td class="px-4 py-3">
          <span class="px-2 py-1 text-xs font-semibold rounded ${levelClass}">
            ${log.level}
          </span>
        </td>
        <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
          ${escapeHtml(log.component || "-")}
        </td>
        <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
          ${escapeHtml(truncateText(log.message, 80))}
          ${log.error_details ? '<span class="text-red-600">⚠️</span>' : ""}
        </td>
        <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
          ${escapeHtml(userDisplay)}
        </td>
        <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
          ${durationDisplay}
        </td>
        <td class="px-4 py-3 text-sm">
          ${
  correlationId !== "-"
    ? `
                <button onclick="event.stopPropagation(); Admin.showCorrelationTrace('${escapeHtml(correlationId)}')"
                  class="text-blue-600 dark:text-blue-400 hover:underline"
                >
                  ${escapeHtml(truncateText(correlationId, 12))}
                </button>
            `
    : "-"
}
        </td>
      </tr>
    `;
    })
    .join("");
};

/**
 * Get CSS class for log level badge
 */
export const getLogLevelClass = function (level) {
  const classes = {
    DEBUG: "bg-gray-200 text-gray-800 dark:bg-gray-600 dark:text-gray-200",
    INFO: "bg-blue-200 text-blue-800 dark:bg-blue-800 dark:text-blue-200",
    WARNING:
      "bg-yellow-200 text-yellow-800 dark:bg-yellow-800 dark:text-yellow-200",
    ERROR: "bg-red-200 text-red-800 dark:bg-red-800 dark:text-red-200",
    CRITICAL:
      "bg-purple-200 text-purple-800 dark:bg-purple-800 dark:text-purple-200",
  };
  return classes[level] || classes.INFO;
};

/**
 * Show detailed log entry (future enhancement - modal)
 */
export const showLogDetails = function (logId, correlationId) {
  if (correlationId) {
    showCorrelationTrace(correlationId);
  } else {
    console.log("Log details:", logId);
    showToast("Full log details view coming soon", "info");
  }
};

/**
 * Restore default log table headers
 */
export const restoreLogTableHeaders = function () {
  const thead = safeGetElement("logs-thead");
  if (thead) {
    thead.innerHTML = `
      <tr>
        <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
          Time
        </th>
        <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
          Level
        </th>
        <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
          Component
        </th>
        <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
          Message
        </th>
        <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
          User
        </th>
        <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
          Duration
        </th>
        <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
          Correlation ID
        </th>
      </tr>
    `;
  }
};

/**
 * Trace all logs for a correlation ID
 */
export const showCorrelationTrace = async function (correlationId) {
  setPerformanceAggregationVisibility(false);
  setLogFiltersVisibility(true);
  if (!correlationId) {
    const searchInput = safeGetElement("log-search");
    correlationId = prompt(
      "Enter Correlation ID to trace:",
      searchInput?.value || ""
    );
    if (!correlationId) {
      return;
    }
  }

  try {
    const response = await fetchWithAuth(
      `${getRootPath()}/api/logs/trace/${encodeURIComponent(correlationId)}`,
      {
        method: "GET",
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to fetch trace: ${response.statusText}`);
    }

    const trace = await response.json();
    displayCorrelationTrace(trace);
  } catch (error) {
    console.error("Error fetching correlation trace:", error);
    showToast("Failed to fetch correlation trace: " + error.message, "error");
  }
};

/**
 * Generates the HTML for the status badge (Active/Inactive/Offline)
 */
export const generateStatusBadgeHtml = function (
  enabled,
  reachable,
  typeLabel
) {
  const label = typeLabel
    ? typeLabel.charAt(0).toUpperCase() + typeLabel.slice(1)
    : "Item";

  if (!enabled) {
    // CASE 1: Inactive (Manually disabled) -> RED
    return `
      <div class="relative group inline-block">
          <span class="px-2 inline-flex items-center text-xs leading-5 font-semibold rounded-full bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200">
              Inactive
              <svg class="ml-1 h-4 w-4 text-red-600 dark:text-red-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M6.293 6.293a1 1 0 011.414 0L10 8.586l2.293-2.293a1 1 0 111.414 1.414L11.414 10l2.293 2.293a1 1 0 11-1.414 1.414L10 11.414l-2.293 2.293a1 1 0 11-1.414-1.414L8.586 10 6.293 7.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
          </span>
          <div class="absolute left-full top-1/2 -translate-y-1/2 ml-2 hidden group-hover:block bg-gray-800 text-white text-xs rounded py-1 px-2 z-10 whitespace-nowrap shadow">💡${label} is Manually Deactivated</div>
      </div>`;
  } else if (!reachable) {
    // CASE 2: Offline (Enabled but Unreachable/Health Check Failed) -> YELLOW
    return `
      <div class="relative group inline-block">
          <span class="px-2 inline-flex items-center text-xs leading-5 font-semibold rounded-full bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200">
              Offline
              <svg class="ml-1 h-4 w-4 text-yellow-600 dark:text-yellow-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-10h2v4h-2V8zm0 6h2v2h-2v-2z" clip-rule="evenodd"/></svg>
          </span>
          <div class="absolute left-full top-1/2 -translate-y-1/2 ml-2 hidden group-hover:block bg-gray-800 text-white text-xs rounded py-1 px-2 z-10 whitespace-nowrap shadow">💡${label} is Not Reachable (Health Check Failed)</div>
      </div>`;
  } else {
    // CASE 3: Active (Enabled and Reachable) -> GREEN
    return `
      <div class="relative group inline-block">
          <span class="px-2 inline-flex items-center text-xs leading-5 font-semibold rounded-full bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
              Active
              <svg class="ml-1 h-4 w-4 text-green-600 dark:text-green-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-4.586l5.293-5.293-1.414-1.414L9 11.586 7.121 9.707 5.707 11.121 9 14.414z" clip-rule="evenodd"/></svg>
          </span>
          <div class="absolute left-full top-1/2 -translate-y-1/2 ml-2 hidden group-hover:block bg-gray-800 text-white text-xs rounded py-1 px-2 z-10 whitespace-nowrap shadow">💡${label} is Active</div>
      </div>`;
  }
};

/**
 * Dynamically updates the action buttons (Activate/Deactivate) inside the table cell
 */
export const updateEntityActionButtons = function (cell, type, id, isEnabled) {
  // We look for the form that toggles activation inside the cell
  const form = cell.querySelector('form[action*="/state"]');
  if (!form) {
    return;
  }

  // The HTML structure for the button
  // Ensure we are flipping the button state correctly based on isEnabled

  if (isEnabled) {
    // If Enabled -> Show Deactivate Button
    form.innerHTML = `
      <input type="hidden" name="activate" value="false" />
      <button type="submit" class="flex items-center justify-center px-2 py-1 text-xs font-medium rounded-md text-yellow-600 hover:text-yellow-900 hover:bg-yellow-50 dark:text-yellow-400 dark:hover:bg-yellow-900/20 transition-colors" x-tooltip="'💡Temporarily disable this item'">
          Deactivate
      </button>
    `;
  } else {
    // If Disabled -> Show Activate Button
    form.innerHTML = `
      <input type="hidden" name="activate" value="true" />
      <button type="submit" class="flex items-center justify-center px-2 py-1 text-xs font-medium rounded-md text-blue-600 hover:text-blue-900 hover:bg-blue-50 dark:text-blue-400 dark:hover:bg-blue-900/20 transition-colors" x-tooltip="'💡Re-enable this item'">
          Activate
      </button>
    `;
  }
};

// CRITICAL DEBUG AND FIX FOR MCP SERVERS SEARCH
console.log("🔧 LOADING MCP SERVERS SEARCH DEBUG FUNCTIONS...");

// Emergency fix function for MCP Servers search
export const emergencyFixMCPSearch = function () {
  console.log("🚨 EMERGENCY FIX: Attempting to fix MCP Servers search...");

  // Find the search input
  const searchInput = safeGetElement("gateways-search-input");
  if (!searchInput) {
    console.error("❌ Cannot find gateways-search-input element");
    return false;
  }

  console.log("✅ Found search input:", searchInput);

  // Remove all existing event listeners by cloning
  const newSearchInput = searchInput.cloneNode(true);
  searchInput.parentNode.replaceChild(newSearchInput, searchInput);

  // Add fresh event listener
  const finalSearchInput = safeGetElement("gateways-search-input");
  finalSearchInput.addEventListener("input", function (e) {
    console.log("🔍 EMERGENCY SEARCH EVENT:", e.target.value);
    filterGatewaysTable(e.target.value);
  });

  console.log(
    "✅ Emergency fix applied - test by typing in MCP Servers search box"
  );
  return true;
};

// Manual test function
export const testMCPSearchManually = function (searchTerm = "github") {
  console.log("🧪 MANUAL TEST: Testing MCP search with:", searchTerm);
  filterGatewaysTable(searchTerm);
};

// Debug current state function
export const debugMCPSearchState = function () {
  console.log("🔍 DEBUGGING MCP SEARCH STATE:");

  const searchInput = safeGetElement("gateways-search-input");
  console.log("Search input:", searchInput);
  console.log(
    "Search input value:",
    searchInput ? searchInput.value : "NOT FOUND"
  );

  const panel = safeGetElement("gateways-panel");
  console.log("Gateways panel:", panel);

  const table = panel ? panel.querySelector("table") : null;
  console.log("Table in panel:", table);

  const rows = table ? table.querySelectorAll("tbody tr") : [];
  console.log("Rows found:", rows.length);

  if (rows.length > 0) {
    console.log("First row content:", rows[0].textContent);
  }

  return {
    searchInput: !!searchInput,
    panel: !!panel,
    table: !!table,
    rowCount: rows.length,
  };
};

console.log("🔧 MCP SERVERS SEARCH DEBUG FUNCTIONS LOADED!");
console.log("💡 Use: Admin.emergencyFixMCPSearch() to fix search");
console.log("💡 Use: Admin.testMCPSearchManually('github') to test search");
console.log("💡 Use: Admin.debugMCPSearchState() to check current state");

/**
 * Display correlation trace results
 */
export const displayCorrelationTrace = function (trace) {
  const tbody = safeGetElement("logs-tbody");
  const thead = safeGetElement("logs-thead");
  const logCount = safeGetElement("log-count");
  const logStats = safeGetElement("log-stats");

  // Calculate total events
  const totalEvents =
    (trace.logs?.length || 0) +
    (trace.security_events?.length || 0) +
    (trace.audit_trails?.length || 0);

  // Update table headers for trace view
  if (thead) {
    thead.innerHTML = `
      <tr>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Time
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Event Type
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Component
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Message/Description
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              User
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Duration
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Status/Severity
          </th>
      </tr>
    `;
  }

  // Update stats
  logCount.textContent = `${totalEvents} events`;
  logStats.innerHTML = `
    <div class="grid grid-cols-2 md:grid-cols-5 gap-4 text-sm">
        <div>
            <strong>Correlation ID:</strong><br>
            <code class="text-xs bg-gray-200 dark:bg-gray-700 px-2 py-1 rounded">${escapeHtml(trace.correlation_id)}</code>
        </div>
        <div>
            <strong>Logs:</strong> <span class="text-blue-600">${trace.log_count || 0}</span>
        </div>
        <div>
            <strong>Security:</strong> <span class="text-red-600">${trace.security_events?.length || 0}</span>
        </div>
        <div>
            <strong>Audit:</strong> <span class="text-yellow-600">${trace.audit_trails?.length || 0}</span>
        </div>
        <div>
            <strong>Duration:</strong> ${trace.total_duration_ms ? trace.total_duration_ms.toFixed(2) + "ms" : "N/A"}
        </div>
    </div>
`;

  if (totalEvents === 0) {
    tbody.innerHTML = `
        <tr><td colspan="7" class="px-4 py-8 text-center text-gray-500 dark:text-gray-400">
            📭 No events found for this correlation ID
        </td></tr>
    `;
    return;
  }

  // Combine all events into a unified timeline
  const allEvents = [];

  // Add logs
  (trace.logs || []).forEach((log) => {
    const levelClass = getLogLevelClass(log.level);
    allEvents.push({
      timestamp: new Date(log.timestamp),
      html: `
          <tr class="hover:bg-gray-50 dark:hover:bg-gray-700 border-l-4 border-blue-500">
              <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                  ${formatTimestamp(log.timestamp)}
              </td>
              <td class="px-4 py-3">
                  <span class="px-2 py-1 text-xs font-semibold rounded bg-blue-200 text-blue-800 dark:bg-blue-800 dark:text-blue-200">
                      📝 Log
                  </span>
              </td>
              <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                  ${escapeHtml(log.component || "-")}
              </td>
              <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                  ${escapeHtml(log.message)}
                  ${log.error_details ? `<br><small class="text-red-600">⚠️ ${escapeHtml(log.error_details.error_message || JSON.stringify(log.error_details))}</small>` : ""}
              </td>
              <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                  ${escapeHtml(log.user_email || log.user_id || "-")}
              </td>
              <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                  ${log.duration_ms ? log.duration_ms.toFixed(2) + "ms" : "-"}
              </td>
              <td class="px-4 py-3">
                  <span class="px-2 py-1 text-xs font-semibold rounded ${levelClass}">
                      ${log.level}
                  </span>
              </td>
          </tr>
      `,
    });
  });

  // Add security events
  (trace.security_events || []).forEach((event) => {
    const severityClass = getSeverityClass(event.severity);
    const threatScore = event.threat_score
      ? (event.threat_score * 100).toFixed(0)
      : 0;
    allEvents.push({
      timestamp: new Date(event.timestamp),
      html: `
          <tr class="hover:bg-gray-50 dark:hover:bg-gray-700 border-l-4 border-red-500 bg-red-50 dark:bg-red-900/10">
              <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                  ${formatTimestamp(event.timestamp)}
              </td>
              <td class="px-4 py-3">
                  <span class="px-2 py-1 text-xs font-semibold rounded bg-red-200 text-red-800 dark:bg-red-800 dark:text-red-200">
                      🛡️ Security
                  </span>
              </td>
              <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                  ${escapeHtml(event.event_type || "-")}
              </td>
              <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                  ${escapeHtml(event.description || "-")}
              </td>
              <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                  ${escapeHtml(event.user_email || event.user_id || "-")}
              </td>
              <td class="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                  -
              </td>
              <td class="px-4 py-3">
                  <div class="flex flex-col gap-1">
                      <span class="px-2 py-1 text-xs font-semibold rounded ${severityClass} w-fit">
                          ${event.severity}
                      </span>
                      <div class="flex items-center gap-1">
                          <span class="text-xs text-gray-600 dark:text-gray-400">Threat:</span>
                          <div class="w-16 bg-gray-200 dark:bg-gray-600 rounded-full h-2">
                              <div class="bg-red-600 h-2 rounded-full" style="width: ${threatScore}%"></div>
                          </div>
                          <span class="text-xs font-medium text-gray-700 dark:text-gray-300">${threatScore}%</span>
                      </div>
                  </div>
              </td>
          </tr>
      `,
    });
  });

  // Add audit trails
  (trace.audit_trails || []).forEach((audit) => {
    const actionBadgeColors = {
      create: "bg-green-200 text-green-800",
      update: "bg-blue-200 text-blue-800",
      delete: "bg-red-200 text-red-800",
      read: "bg-gray-200 text-gray-800",
    };
    const actionBadge =
      actionBadgeColors[audit.action?.toLowerCase()] ||
      "bg-purple-200 text-purple-800";
    const statusIcon = audit.success ? "✓" : "✗";
    const statusClass = audit.success ? "text-green-600" : "text-red-600";
    const statusBg = audit.success
      ? "bg-green-100 dark:bg-green-900"
      : "bg-red-100 dark:bg-red-900";

    allEvents.push({
      timestamp: new Date(audit.timestamp),
      html: `
        <tr class="hover:bg-gray-50 dark:hover:bg-gray-700 border-l-4 border-yellow-500 bg-yellow-50 dark:bg-yellow-900/10">
            <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                ${formatTimestamp(audit.timestamp)}
            </td>
            <td class="px-4 py-3">
                <span class="px-2 py-1 text-xs font-semibold rounded ${actionBadge}">
                    📋 ${audit.action?.toUpperCase()}
                </span>
            </td>
            <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                ${escapeHtml(audit.resource_type || "-")}
            </td>
            <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                <strong>${audit.action}:</strong> ${audit.resource_type}
                <code class="text-xs bg-gray-200 px-1 rounded">${escapeHtml(audit.resource_id || "-")}</code>
            </td>
            <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                ${escapeHtml(audit.user_email || audit.user_id || "-")}
            </td>
            <td class="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                -
            </td>
            <td class="px-4 py-3">
                <span class="px-2 py-1 text-xs font-semibold rounded ${statusBg} ${statusClass}">
                    ${statusIcon} ${audit.success ? "Success" : "Failed"}
                </span>
            </td>
        </tr>
      `,
    });
  });

  // Sort all events chronologically
  allEvents.sort((a, b) => a.timestamp - b.timestamp);

  // Render sorted events
  tbody.innerHTML = allEvents.map((event) => event.html).join("");
};

/**
 * Show security events
 */
export const showSecurityEvents = async function () {
  setPerformanceAggregationVisibility(false);
  setLogFiltersVisibility(false);
  try {
    const response = await fetchWithAuth(
      `${getRootPath()}/api/logs/security-events?limit=50&resolved=false`,
      {
        method: "GET",
      }
    );

    if (!response.ok) {
      throw new Error(
        `Failed to fetch security events: ${response.statusText}`
      );
    }

    const events = await response.json();
    displaySecurityEvents(events);
  } catch (error) {
    console.error("Error fetching security events:", error);
    showToast("Failed to fetch security events: " + error.message, "error");
  }
};

/**
 * Display security events
 */
export const displaySecurityEvents = function (events) {
  const tbody = safeGetElement("logs-tbody");
  const thead = safeGetElement("logs-thead");
  const logCount = safeGetElement("log-count");
  const logStats = safeGetElement("log-stats");

  // Update table headers for security events
  if (thead) {
    thead.innerHTML = `
        <tr>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Time
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Severity
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Event Type
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Description
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              User/Source
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Threat Score
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Correlation ID
          </th>
      </tr>
    `;
  }

  logCount.textContent = `${events.length} security events`;
  logStats.innerHTML = `
      <span class="text-sm text-red-600 dark:text-red-400">
          🛡️ Unresolved Security Events
      </span>
  `;

  if (events.length === 0) {
    tbody.innerHTML = `
        <tr><td colspan="7" class="px-4 py-8 text-center text-green-600 dark:text-green-400">
            ✅ No unresolved security events
        </td></tr>
    `;
    return;
  }

  tbody.innerHTML = events
    .map((event) => {
      const severityClass = getSeverityClass(event.severity);
      const threatScore = (event.threat_score * 100).toFixed(0);

      return `
      <tr class="hover:bg-gray-50 dark:hover:bg-gray-700">
          <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
              ${formatTimestamp(event.timestamp)}
          </td>
          <td class="px-4 py-3">
              <span class="px-2 py-1 text-xs font-semibold rounded ${severityClass}">
                  ${event.severity}
              </span>
          </td>
          <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
              ${escapeHtml(event.event_type)}
          </td>
          <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
              ${escapeHtml(event.description)}
          </td>
          <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
              ${escapeHtml(event.user_email || event.user_id || "-")}
          </td>
          <td class="px-4 py-3 text-sm">
              <div class="flex items-center">
                  <div class="w-16 bg-gray-200 dark:bg-gray-600 rounded-full h-2 mr-2">
                      <div class="bg-red-600 h-2 rounded-full" style="width: ${threatScore}%"></div>
                  </div>
                  <span class="text-xs">${threatScore}%</span>
              </div>
          </td>
          <td class="px-4 py-3 text-sm">
              ${
  event.correlation_id
    ? `
                  <button onclick="event.stopPropagation(); Admin.showCorrelationTrace('${escapeHtml(event.correlation_id)}')"
                          class="text-blue-600 dark:text-blue-400 hover:underline">
                      ${escapeHtml(truncateText(event.correlation_id, 12))}
                  </button>
              `
    : "-"
}
          </td>
      </tr>
    `;
    })
    .join("");
};

/**
 * Get CSS class for severity badge
 */
export const getSeverityClass = function (severity) {
  const classes = {
    LOW: "bg-blue-200 text-blue-800 dark:bg-blue-800 dark:text-blue-200",
    MEDIUM:
      "bg-yellow-200 text-yellow-800 dark:bg-yellow-800 dark:text-yellow-200",
    HIGH: "bg-orange-200 text-orange-800 dark:bg-orange-800 dark:text-orange-200",
    CRITICAL: "bg-red-200 text-red-800 dark:bg-red-800 dark:text-red-200",
  };
  return classes[severity] || classes.MEDIUM;
};

/**
 * Show audit trail
 */
export const showAuditTrail = async function () {
  setPerformanceAggregationVisibility(false);
  setLogFiltersVisibility(false);
  try {
    const response = await fetchWithAuth(
      `${getRootPath()}/api/logs/audit-trails?limit=50&requires_review=true`,
      {
        method: "GET",
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to fetch audit trails: ${response.statusText}`);
    }

    const trails = await response.json();
    displayAuditTrail(trails);
  } catch (error) {
    console.error("Error fetching audit trails:", error);
    showToast("Failed to fetch audit trails: " + error.message, "error");
  }
};

/**
 * Display audit trail entries
 */
export const displayAuditTrail = function (trails) {
  const tbody = safeGetElement("logs-tbody");
  const thead = safeGetElement("logs-thead");
  const logCount = safeGetElement("log-count");
  const logStats = safeGetElement("log-stats");

  // Update table headers for audit trail
  if (thead) {
    thead.innerHTML = `
        <tr>
            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Time
            </th>
            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Action
            </th>
            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Resource Type
            </th>
            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Resource
            </th>
            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                User
            </th>
            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Status
            </th>
            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Correlation ID
            </th>
        </tr>
    `;
  }

  logCount.textContent = `${trails.length} audit entries`;
  logStats.innerHTML = `
    <span class="text-sm text-yellow-600 dark:text-yellow-400">
        📝 Audit Trail Entries Requiring Review
    </span>
  `;

  if (trails.length === 0) {
    tbody.innerHTML = `
        <tr><td colspan="7" class="px-4 py-8 text-center text-green-600 dark:text-green-400">
            ✅ No audit entries require review
        </td></tr>
    `;
    return;
  }

  tbody.innerHTML = trails
    .map((trail) => {
      const actionClass = trail.success ? "text-green-600" : "text-red-600";
      const actionIcon = trail.success ? "✓" : "✗";

      // Determine action badge color
      const actionBadgeColors = {
        create:
          "bg-green-200 text-green-800 dark:bg-green-800 dark:text-green-200",
        update: "bg-blue-200 text-blue-800 dark:bg-blue-800 dark:text-blue-200",
        delete: "bg-red-200 text-red-800 dark:bg-red-800 dark:text-red-200",
        read: "bg-gray-200 text-gray-800 dark:bg-gray-600 dark:text-gray-200",
        activate:
          "bg-teal-200 text-teal-800 dark:bg-teal-800 dark:text-teal-200",
        deactivate:
          "bg-orange-200 text-orange-800 dark:bg-orange-800 dark:text-orange-200",
      };
      const actionBadge =
        actionBadgeColors[trail.action.toLowerCase()] ||
        "bg-purple-200 text-purple-800 dark:bg-purple-800 dark:text-purple-200";

      // Format resource name with ID
      const resourceName = trail.resource_name || trail.resource_id || "-";
      const resourceDisplay = `
        <div class="font-medium">${escapeHtml(resourceName)}</div>
        ${trail.resource_id && trail.resource_name ? `<div class="text-xs text-gray-500">UUID: ${escapeHtml(trail.resource_id)}</div>` : ""}
        ${trail.data_classification ? `<div class="text-xs text-orange-600 mt-1">🔒 ${escapeHtml(trail.data_classification)}</div>` : ""}
    `;

      return `
        <tr class="hover:bg-gray-50 dark:hover:bg-gray-700">
            <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                ${formatTimestamp(trail.timestamp)}
            </td>
            <td class="px-4 py-3">
                <span class="px-2 py-1 text-xs font-semibold rounded ${actionBadge}">
                    ${trail.action.toUpperCase()}
                </span>
            </td>
            <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                ${escapeHtml(trail.resource_type || "-")}
            </td>
            <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                ${resourceDisplay}
            </td>
            <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                ${escapeHtml(trail.user_email || trail.user_id || "-")}
            </td>
            <td class="px-4 py-3 text-sm ${actionClass}">
                ${actionIcon} ${trail.success ? "Success" : "Failed"}
            </td>
            <td class="px-4 py-3 text-sm">
                ${
  trail.correlation_id
    ? `
                    <button onclick="event.stopPropagation(); Admin.showCorrelationTrace('${escapeHtml(trail.correlation_id)}')"
                            class="text-blue-600 dark:text-blue-400 hover:underline">
                        ${escapeHtml(truncateText(trail.correlation_id, 12))}
                    </button>
                `
    : "-"
}
            </td>
        </tr>
    `;
    })
    .join("");
};

/**
 * Show performance metrics
 */
export const showPerformanceMetrics = async function (rangeKey) {
  if (rangeKey && PERFORMANCE_AGGREGATION_OPTIONS[rangeKey]) {
    currentPerformanceAggregationKey = rangeKey;
  } else {
    const select = safeGetElement("performance-aggregation-select");
    if (select?.value && PERFORMANCE_AGGREGATION_OPTIONS[select.value]) {
      currentPerformanceAggregationKey = select.value;
    }
  }

  syncPerformanceAggregationSelect();
  setPerformanceAggregationVisibility(true);
  setLogFiltersVisibility(false);
  const hoursParam = encodeURIComponent(PERFORMANCE_HISTORY_HOURS.toString());
  const aggregationParam = encodeURIComponent(
    getPerformanceAggregationQuery()
  );

  try {
    const response = await fetchWithAuth(
      `${getRootPath()}/api/logs/performance-metrics?hours=${hoursParam}&aggregation=${aggregationParam}`,
      {
        method: "GET",
      }
    );

    if (!response.ok) {
      throw new Error(
        `Failed to fetch performance metrics: ${response.statusText}`
      );
    }

    const metrics = await response.json();
    displayPerformanceMetrics(metrics);
  } catch (error) {
    console.error("Error fetching performance metrics:", error);
    showToast("Failed to fetch performance metrics: " + error.message, "error");
  }
};

/**
 * Display performance metrics
 */
export const displayPerformanceMetrics = function (metrics) {
  const tbody = safeGetElement("logs-tbody");
  const thead = safeGetElement("logs-thead");
  const logCount = safeGetElement("log-count");
  const logStats = safeGetElement("log-stats");
  const aggregationLabel = getPerformanceAggregationLabel();

  // Update table headers for performance metrics
  if (thead) {
    thead.innerHTML = `
      <tr>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Time
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Component
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Operation
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Avg Duration
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Requests
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              Error Rate
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
              P99 Duration
          </th>
      </tr>
    `;
  }

  logCount.textContent = `${metrics.length} metrics`;
  logStats.innerHTML = `
      <span class="text-sm text-green-600 dark:text-green-400">
          ⚡ Performance Metrics (${aggregationLabel})
      </span>
  `;

  if (metrics.length === 0) {
    tbody.innerHTML = `
        <tr><td colspan="7" class="px-4 py-8 text-center text-gray-500 dark:text-gray-400">
            📊 No performance metrics available for ${aggregationLabel.toLowerCase()}
        </td></tr>
    `;
    return;
  }

  tbody.innerHTML = metrics
    .map((metric) => {
      const errorRatePercent = (metric.error_rate * 100).toFixed(2);
      const errorClass =
        metric.error_rate > 0.1 ? "text-red-600" : "text-green-600";

      return `
        <tr class="hover:bg-gray-50 dark:hover:bg-gray-700">
            <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                ${formatTimestamp(metric.window_start)}
            </td>
            <td class="px-4 py-3 text-sm font-semibold text-gray-900 dark:text-gray-300">
                ${escapeHtml(metric.component || "-")}
            </td>
            <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                ${escapeHtml(metric.operation_type || "-")}
            </td>
            <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                <div class="text-xs">
                    <div>Avg: <strong>${metric.avg_duration_ms.toFixed(2)}ms</strong></div>
                    <div class="text-gray-500">P95: ${metric.p95_duration_ms.toFixed(2)}ms</div>
                </div>
            </td>
            <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                ${metric.request_count.toLocaleString()} requests
            </td>
            <td class="px-4 py-3 text-sm ${errorClass}">
                ${errorRatePercent}%
                ${metric.error_rate > 0.1 ? "⚠️" : ""}
            </td>
            <td class="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                <div class="text-xs">
                    P99: ${metric.p99_duration_ms.toFixed(2)}ms
                </div>
            </td>
        </tr>
    `;
    })
    .join("");
};

/**
 * Navigate to previous log page
 */
export const previousLogPage = function () {
  if (currentLogPage > 0) {
    currentLogPage--;
    searchStructuredLogs();
  }
};

/**
 * Navigate to next log page
 */
export const nextLogPage = function () {
  currentLogPage++;
  searchStructuredLogs();
};
