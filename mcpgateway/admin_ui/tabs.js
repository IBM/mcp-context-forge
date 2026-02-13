// ===================================================================
// ENHANCED TAB HANDLING with Better Error Management

import { loadRecentImports } from "./fileTransfer.js";
import { initializeExportImport } from "./initialization.js";
import { initializeLLMChat } from "./llmChat.js";
import { searchStructuredLogs } from "./logging.js";
import { loadAggregatedMetrics } from "./metrics";
import { populatePluginFilters } from "./plugins";
import { escapeHtml, safeReplaceState, safeSetInnerHTML } from "./security.js";
import {
  loadTokensList,
  setupCreateTokenForm,
  updateTeamScopingWarning,
} from "./tokens";
import { initializePermissionsPanel } from "./users";
import {
  fetchWithTimeout,
  isAdminUser,
  safeGetElement,
  showErrorMessage,
} from "./utils";

// ===================================================================
export const ADMIN_ONLY_TABS = new Set([
  "users",
  "metrics",
  "performance",
  "observability",
  "plugins",
  "logs",
  "export-import",
  "version-info",
  "maintenance",
]);

export const isAdminOnlyTab = function (tabName) {
  return ADMIN_ONLY_TABS.has(tabName);
};

export const getDefaultTabName = function () {
  return safeGetElement("overview-panel", true) ? "overview" : "gateways";
};

let tabSwitchTimeout = null;

/**
 * Dynamically detects which pagination table names belong to a given tab panel
 * by scanning for pagination control elements within that panel.
 * Returns array of table names (e.g., ['tools'], ['servers'], etc.)
 */
export const getTableNamesForTab = function (tabName) {
  const panel = safeGetElement(`${tabName}-panel`);
  if (!panel) {
    return [];
  }

  // Find all pagination control elements within this panel
  // Pattern: id="<tableName>-pagination-controls"
  const paginationControls = panel.querySelectorAll(
    '[id$="-pagination-controls"]',
  );

  const tableNames = [];
  paginationControls.forEach((control) => {
    // Extract table name from id: "tools-pagination-controls" -> "tools"
    const match = control.id.match(/^(.+)-pagination-controls$/);
    if (match) {
      tableNames.push(match[1]);
    }
  });

  return tableNames;
};

/**
 * Cleans up URL params for tables not belonging to the target tab
 * Keeps only params for the current tab's tables and global params (team_id)
 * Automatically detects which tables belong to the tab by scanning the DOM.
 */
export const cleanUpUrlParamsForTab = function (targetTabName) {
  const currentUrl = new URL(window.location.href);
  const newParams = new URLSearchParams();

  // Dynamically detect which tables belong to this tab
  const targetTables = getTableNamesForTab(targetTabName);

  // Preserve global params
  if (currentUrl.searchParams.has("team_id")) {
    newParams.set("team_id", currentUrl.searchParams.get("team_id"));
  }

  // Only keep params for tables that belong to the target tab
  currentUrl.searchParams.forEach((value, key) => {
    // Check if this param belongs to one of the target tab's tables
    for (const tableName of targetTables) {
      const prefix = tableName + "_";
      if (key.startsWith(prefix)) {
        newParams.set(key, value);
        break;
      }
    }
  });

  // Update URL
  const newUrl =
    currentUrl.pathname +
    (newParams.toString() ? "?" + newParams.toString() : "") +
    currentUrl.hash;
  safeReplaceState({}, "", newUrl);
};

export const showTab = function (tabName) {
  try {
    if (!isAdminUser() && isAdminOnlyTab(tabName)) {
      console.warn(`Blocked non-admin access to tab: ${tabName}`);
      const fallbackTab = getDefaultTabName();
      if (tabName !== fallbackTab) {
        showTab(fallbackTab);
      }
      return;
    }
    console.log(`Switching to tab: ${tabName}`);

    // Clear any pending tab switch
    if (tabSwitchTimeout) {
      clearTimeout(tabSwitchTimeout);
    }

    // Cleanup observability tab when leaving
    const currentPanel = document.querySelector(".tab-panel:not(.hidden)");
    if (
      currentPanel?.id === "observability-panel" &&
      tabName !== "observability"
    ) {
      console.log("Leaving observability tab, triggering cleanup...");
      // Destroy all observability charts
      window.Admin.chartRegistry.destroyByPrefix("metrics-");
      window.Admin.chartRegistry.destroyByPrefix("tools-");
      window.Admin.chartRegistry.destroyByPrefix("prompts-");
      window.Admin.chartRegistry.destroyByPrefix("resources-");
      // Dispatch event so Alpine components can stop intervals and reset state
      document.dispatchEvent(new CustomEvent("observability:leave"));
    }

    // Clean up URL params from other tabs when switching tabs
    cleanUpUrlParamsForTab(tabName);

    // Navigation styling (immediate)
    document.querySelectorAll(".tab-panel").forEach((p) => {
      if (p) {
        p.classList.add("hidden");
      }
    });

    document.querySelectorAll(".sidebar-link").forEach((l) => {
      if (l) {
        l.classList.remove("active");
      }
    });

    // Reveal chosen panel
    const panel = safeGetElement(`${tabName}-panel`);
    if (panel) {
      panel.classList.remove("hidden");
    } else {
      console.error(`Panel ${tabName}-panel not found`);
      return;
    }

    const nav = document.querySelector(`.sidebar-link[href="#${tabName}"]`);
    if (nav) {
      nav.classList.add("active");
    }

    // Debounced content loading
    tabSwitchTimeout = setTimeout(() => {
      try {
        if (tabName === "overview") {
          // Load overview content if not already loaded
          const overviewPanel = safeGetElement("overview-panel");
          if (overviewPanel) {
            const hasLoadingMessage =
              overviewPanel.innerHTML.includes("Loading overview");
            if (hasLoadingMessage) {
              // Trigger HTMX load manually if HTMX is available
              if (window.htmx && window.htmx.trigger) {
                window.htmx.trigger(overviewPanel, "load");
              }
            }
          }
        }

        if (tabName === "metrics") {
          // Only load if we're still on the metrics tab
          if (!panel.classList.contains("hidden")) {
            loadAggregatedMetrics();
          }
        }
        if (tabName === "llm-chat") {
          initializeLLMChat();
        }

        if (tabName === "logs") {
          // Load structured logs when tab is first opened
          const logsTbody = safeGetElement("logs-tbody");
          if (logsTbody && logsTbody.children.length === 0) {
            searchStructuredLogs();
          }
        }

        if (tabName === "teams") {
          // Load Teams list if not already loaded
          const teamsList = safeGetElement("teams-list");
          if (teamsList) {
            // Check if it's still showing the loading message or is empty
            const hasLoadingMessage =
              teamsList.innerHTML.includes("Loading teams...");
            const isEmpty = teamsList.innerHTML.trim() === "";
            if (hasLoadingMessage || isEmpty) {
              // Trigger HTMX load manually if HTMX is available
              if (window.htmx && window.htmx.trigger) {
                window.htmx.trigger(teamsList, "load");
              }
            }
          }
        }

        if (tabName === "gateways") {
          // Load Gateways table if not already loaded
          const gatewaysTable = safeGetElement("gateways-table");
          if (gatewaysTable) {
            const hasLoadingMessage = gatewaysTable.innerHTML.includes(
              "Loading gateways...",
            );
            const isEmpty = gatewaysTable.innerHTML.trim() === "";
            if (hasLoadingMessage || isEmpty) {
              // Trigger HTMX load manually if HTMX is available
              if (window.htmx && window.htmx.trigger) {
                window.htmx.trigger(gatewaysTable, "load");
              }
            }
          }
        }

        if (tabName === "tokens") {
          // Load Tokens list and set up form handling
          const tokensList = safeGetElement("tokens-list");
          if (tokensList) {
            const hasLoadingMessage =
              tokensList.innerHTML.includes("Loading tokens...");
            const isEmpty = !tokensList.innerHTML.trim();
            if (hasLoadingMessage || isEmpty) {
              loadTokensList();
            }
          }

          // Set up create token form if not already set up
          const createForm = safeGetElement("create-token-form");
          if (createForm && !createForm.hasAttribute("data-setup")) {
            setupCreateTokenForm();
            createForm.setAttribute("data-setup", "true");
          }

          // Update team scoping warning when switching to tokens tab
          updateTeamScopingWarning();
        }

        if (tabName === "catalog") {
          // Load servers list if not already loaded
          const serversList = safeGetElement("servers-table");
          if (serversList) {
            const hasLoadingMessage =
              serversList.innerHTML.includes("Loading servers...");
            if (hasLoadingMessage) {
              // Trigger HTMX load manually if HTMX is available
              if (window.htmx && window.htmx.trigger) {
                window.htmx.trigger(serversList, "load");
              }
            }
          }
        }

        if (tabName === "a2a-agents") {
          // Load A2A agents list if not already loaded
          const agentsList = safeGetElement("agents-table");
          if (agentsList) {
            const hasLoadingMessage =
              agentsList.innerHTML.includes("Loading agents...");
            if (hasLoadingMessage) {
              // Trigger HTMX load manually if HTMX is available
              if (window.htmx && window.htmx.trigger) {
                window.htmx.trigger(agentsList, "load");
              }
            }
          }
        }

        if (tabName === "mcp-registry") {
          // Load MCP Registry content
          const registryContent = safeGetElement("mcp-registry-servers");
          if (registryContent) {
            const newLocal = "Loading MCP Registry servers...";
            // Always load on first visit or if showing loading message
            const hasLoadingMessage =
              registryContent.innerHTML.includes(newLocal);
            const needsLoad =
              hasLoadingMessage || !registryContent.getAttribute("data-loaded");

            if (needsLoad) {
              const rootPath = window.ROOT_PATH || "";

              // Use HTMX if available
              if (window.htmx && window.htmx.ajax) {
                window.htmx
                  .ajax("GET", `${rootPath}/admin/mcp-registry/partial`, {
                    target: "#mcp-registry-servers",
                    swap: "innerHTML",
                  })
                  .then(() => {
                    registryContent.setAttribute("data-loaded", "true");
                  });
              } else {
                // Fallback to fetch if HTMX is not available
                fetch(`${rootPath}/admin/mcp-registry/partial`)
                  .then((response) => response.text())
                  .then((html) => {
                    registryContent.innerHTML = html;
                    registryContent.setAttribute("data-loaded", "true");
                    // Process any HTMX attributes in the new content
                    if (window.htmx) {
                      window.htmx.process(registryContent);
                    }
                  })
                  .catch((error) => {
                    console.error("Failed to load MCP Registry:", error);
                    registryContent.innerHTML =
                      '<div class="text-center text-red-600 py-8">Failed to load MCP Registry servers</div>';
                  });
              }
            }
          }
        }

        if (tabName === "gateways") {
          // Load gateways list if not already loaded
          const gatewaysList = safeGetElement("gateways-table");
          if (gatewaysList) {
            const hasLoadingMessage = gatewaysList.innerHTML.includes(
              "Loading gateways...",
            );
            if (hasLoadingMessage) {
              // Trigger HTMX load manually if HTMX is available
              if (window.htmx && window.htmx.trigger) {
                window.htmx.trigger(gatewaysList, "load");
              } else {
                // Fallback: reload the page section via fetch
                const rootPath = window.ROOT_PATH || "";
                fetch(`${rootPath}/admin`)
                  .then((response) => response.text())
                  .then((html) => {
                    // Parse the HTML and extract just the gateways table
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(html, "text/html");
                    const newTable = doc.querySelector("#gateways-table");
                    if (newTable) {
                      gatewaysList.innerHTML = newTable.innerHTML;
                      // Process any HTMX attributes in the new content
                      if (window.htmx) {
                        window.htmx.process(gatewaysList);
                      }
                    }
                  })
                  .catch((error) => {
                    console.error("Failed to reload gateways:", error);
                  });
              }
            }
          }
        }

        // Note: Charts are already destroyed when leaving observability tab (see above),
        // so we don't need to destroy them again on entry. The loaded partials will
        // re-render charts on their next auto-refresh cycle or when the partial is reloaded.
        if (tabName === "plugins") {
          const pluginsPanel = safeGetElement("plugins-panel");
          if (pluginsPanel && pluginsPanel.innerHTML.trim() === "") {
            const rootPath = window.ROOT_PATH || "";
            fetchWithTimeout(
              `${rootPath}/admin/plugins/partial`,
              {
                method: "GET",
                credentials: "same-origin",
                headers: {
                  Accept: "text/html",
                },
              },
              5000,
            )
              .then((response) => {
                if (!response.ok) {
                  throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.text();
              })
              .then((html) => {
                pluginsPanel.innerHTML = html;
                // Populate filter dropdowns
                if (populatePluginFilters) {
                  populatePluginFilters();
                }
              })
              .catch((error) => {
                console.error("Error loading plugins partial:", error);
                pluginsPanel.innerHTML = `
                                        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
                                            <strong class="font-bold">Error loading plugins:</strong>
                                            <span class="block sm:inline">${escapeHtml(error.message)}</span>
                                        </div>
                                    `;
              });
          }
        }

        if (tabName === "version-info") {
          const versionPanel = safeGetElement("version-info-panel");
          if (versionPanel && versionPanel.innerHTML.trim() === "") {
            fetchWithTimeout(
              `${window.ROOT_PATH}/version?partial=true`,
              {},
              window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000,
            )
              .then((resp) => {
                if (!resp.ok) {
                  throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
                }
                return resp.text();
              })
              .then((html) => {
                safeSetInnerHTML(versionPanel, html, true);
                console.log("✓ Version info loaded");
              })
              .catch((err) => {
                console.error("Failed to load version info:", err);
                const errorDiv = document.createElement("div");
                errorDiv.className = "text-red-600 p-4";
                errorDiv.textContent =
                  "Failed to load version info. Please try again.";
                versionPanel.innerHTML = "";
                versionPanel.appendChild(errorDiv);
              });
          }
        }

        if (tabName === "maintenance") {
          const maintenancePanel = safeGetElement("maintenance-panel");
          if (maintenancePanel && maintenancePanel.innerHTML.trim() === "") {
            fetchWithTimeout(
              `${window.ROOT_PATH}/admin/maintenance/partial`,
              {},
              window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000,
            )
              .then((resp) => {
                if (!resp.ok) {
                  if (resp.status === 403) {
                    throw new Error("Platform administrator access required");
                  }
                  throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
                }
                return resp.text();
              })
              .then((html) => {
                safeSetInnerHTML(maintenancePanel, html, true);
                console.log("✓ Maintenance panel loaded");
              })
              .catch((err) => {
                console.error("Failed to load maintenance panel:", err);
                const errorDiv = document.createElement("div");
                errorDiv.className = "text-red-600 p-4";
                errorDiv.textContent =
                  err.message ||
                  "Failed to load maintenance panel. Please try again.";
                maintenancePanel.innerHTML = "";
                maintenancePanel.appendChild(errorDiv);
              });
          }
        }

        if (tabName === "export-import") {
          // Initialize export/import functionality when tab is shown
          if (!panel.classList.contains("hidden")) {
            console.log("🔄 Initializing export/import tab content");
            try {
              // Ensure the export/import functionality is initialized
              if (typeof initializeExportImport === "function") {
                initializeExportImport();
              }
              // Load recent imports
              if (typeof loadRecentImports === "function") {
                loadRecentImports();
              }
            } catch (error) {
              console.error("Error loading export/import content:", error);
            }
          }
        }

        if (tabName === "permissions") {
          // Initialize permissions panel when tab is shown
          if (!panel.classList.contains("hidden")) {
            console.log("🔄 Initializing permissions tab content");
            try {
              // Check if initializePermissionsPanel function exists
              if (typeof initializePermissionsPanel === "function") {
                initializePermissionsPanel();
              } else {
                console.warn(
                  "initializePermissionsPanel function not found",
                );
              }
            } catch (error) {
              console.error("Error initializing permissions panel:", error);
            }
          }
        }
      } catch (error) {
        console.error(`Error in tab ${tabName} content loading:`, error);
      }
    }, 300); // 300ms debounce

    console.log(`✓ Successfully switched to tab: ${tabName}`);
  } catch (error) {
    console.error(`Error switching to tab ${tabName}:`, error);
    showErrorMessage(`Failed to switch to ${tabName} tab`);
  }
};
