import {
  DEFAULT_TEAMS_PER_PAGE,
  PERFORMANCE_AGGREGATION_OPTIONS,
  PERFORMANCE_HISTORY_HOURS,
} from "./constants.js";
import {
  displayImportResults,
  refreshCurrentTabData,
  showImportProgress,
} from "./fileTransfer.js";
import {
  initializeSearchInputs,
  setupIntegrationTypeHandlers,
  setupSchemaModeHandlers,
} from "./initialization.js";
import { initResourceSelect } from "./resources.js";
import {
  escapeHtml,
  safeSetInnerHTML,
} from "./security.js";
import { fetchWithAuth, getAuthToken, getTeamNameById } from "./tokens.js";
import { initToolSelect } from "./tools.js";
import {
  fetchWithTimeout,
  formatTimestamp,
  getCookie,
  getRootPath,
  isAdminUser,
  safeGetElement,
  showErrorMessage,
  showNotification,
  showSuccessMessage,
  showToast,
} from "./utils.js";

((Admin) => {
  // ===================================================================
  // GLOBAL CHART.JS INSTANCE REGISTRY
  // ===================================================================
  // Centralized chart management to prevent "Canvas is already in use" errors
  Admin.chartRegistry = {
    charts: new Map(),

    register(id, chart) {
      // Destroy existing chart with same ID before registering new one
      if (this.charts.has(id)) {
        this.destroy(id);
      }
      this.charts.set(id, chart);
      console.log(`Chart registered: ${id}`);
    },

    destroy(id) {
      const chart = this.charts.get(id);
      if (chart) {
        try {
          chart.destroy();
          console.log(`Chart destroyed: ${id}`);
        } catch (e) {
          console.warn(`Failed to destroy chart ${id}:`, e);
        }
        this.charts.delete(id);
      }
    },

    destroyAll() {
      console.log(`Destroying all charts (${this.charts.size} total)`);
      this.charts.forEach((chart, id) => {
        this.destroy(id);
      });
    },

    destroyByPrefix(prefix) {
      const toDestroy = [];
      this.charts.forEach((chart, id) => {
        if (id.startsWith(prefix)) {
          toDestroy.push(id);
        }
      });
      console.log(
        `Destroying ${toDestroy.length} charts with prefix: ${prefix}`
      );
      toDestroy.forEach((id) => this.destroy(id));
    },

    has(id) {
      return this.charts.has(id);
    },

    get(id) {
      return this.charts.get(id);
    },

    size() {
      return this.charts.size;
    },
  };

  // ===================================================================
  // HTMX HANDLERS for dynamic content loading
  // ===================================================================

  // Set up HTMX handler for auto-checking newly loaded tools when Select All is active or Edit Server mode
  if (window.htmx && !window._toolsHtmxHandlerAttached) {
    Admin._toolsHtmxHandlerAttached = true;

    window.htmx.on("htmx:afterSettle", function (evt) {
      // Only handle tool pagination requests
      if (
        evt.detail.pathInfo &&
        evt.detail.pathInfo.requestPath &&
        evt.detail.pathInfo.requestPath.includes("/admin/tools/partial")
      ) {
        // Use a slight delay to ensure DOM is fully updated
        setTimeout(() => {
          // Find which container actually triggered the request by checking the target
          let container = null;
          const target = evt.detail.target;

          // Check if the target itself is the edit server tools container (most common case for infinite scroll)
          if (target && target.id === "edit-server-tools") {
            container = target;
          }
          // Or if target is the associated tools container (for add server)
          else if (target && target.id === "associatedTools") {
            container = target;
          }
          // Otherwise try to find the container using closest
          else if (target) {
            container =
              target.closest("#associatedTools") ||
              target.closest("#edit-server-tools");
          }

          // Fallback logic if container still not found
          if (!container) {
            // Check which modal/dialog is currently open to determine the correct container
            const editModal = safeGetElement("server-edit-modal");
            const isEditModalOpen =
              editModal && !editModal.classList.contains("hidden");

            if (isEditModalOpen) {
              container = safeGetElement("edit-server-tools");
            } else {
              container = safeGetElement("associatedTools");
            }
          }

          // Final safety check - use direct lookup if still not found
          if (!container) {
            const addServerContainer = safeGetElement("associatedTools");
            const editServerContainer = safeGetElement("edit-server-tools");

            // Check if edit server container has the server tools data attribute set
            if (
              editServerContainer &&
              editServerContainer.getAttribute("data-server-tools")
            ) {
              container = editServerContainer;
            } else if (
              addServerContainer &&
              addServerContainer.offsetParent !== null
            ) {
              container = addServerContainer;
            } else if (
              editServerContainer &&
              editServerContainer.offsetParent !== null
            ) {
              container = editServerContainer;
            } else {
              // Last resort: just pick one that exists
              container = addServerContainer || editServerContainer;
            }
          }

          if (container) {
            // Update tool mapping for newly loaded tools
            const newCheckboxes = container.querySelectorAll(
              "input[data-auto-check=true]"
            );

            if (!Admin.toolMapping) {
              Admin.toolMapping = {};
            }

            newCheckboxes.forEach((cb) => {
              const toolId = cb.value;
              const toolName = cb.getAttribute("data-tool-name");
              if (toolId && toolName) {
                Admin.toolMapping[toolId] = toolName;
              }
            });

            const selectAllInput = container.querySelector(
              'input[name="selectAllTools"]'
            );

            // Check if Select All is active
            if (selectAllInput && selectAllInput.value === "true") {
              newCheckboxes.forEach((cb) => {
                cb.checked = true;
                cb.removeAttribute("data-auto-check");
              });

              if (newCheckboxes.length > 0) {
                const event = new Event("change", {
                  bubbles: true,
                });
                container.dispatchEvent(event);
              }
            }
            // Check if we're in Edit Server mode and need to pre-select tools
            else if (container.id === "edit-server-tools") {
              // Try to get server tools from data attribute (primary source)
              let serverTools = null;
              const dataAttr = container.getAttribute("data-server-tools");

              if (dataAttr) {
                try {
                  serverTools = JSON.parse(dataAttr);
                } catch (e) {
                  console.error("Failed to parse data-server-tools:", e);
                }
              }

              if (serverTools && serverTools.length > 0) {
                newCheckboxes.forEach((cb) => {
                  const toolId = cb.value;
                  // Use the data attribute directly
                  const toolName = cb.getAttribute("data-tool-name");
                  if (toolId && toolName) {
                    // Check if this tool name exists in server associated tools
                    if (serverTools.includes(toolName)) {
                      cb.checked = true;
                    }
                  }
                  cb.removeAttribute("data-auto-check");
                });

                // Trigger an update to display the correct count based on server.associatedTools
                // This will make sure the pill counters reflect the total associated tools count
                const event = new Event("change", {
                  bubbles: true,
                });
                container.dispatchEvent(event);
              }
            }
            // If we're in the Add Server tools container, restore persisted selections
            else if (container.id === "associatedTools") {
              try {
                const dataAttr = container.getAttribute("data-selected-tools");
                if (dataAttr) {
                  const selectedIds = JSON.parse(dataAttr);
                  if (Array.isArray(selectedIds) && selectedIds.length > 0) {
                    newCheckboxes.forEach((cb) => {
                      if (selectedIds.includes(cb.value)) {
                        cb.checked = true;
                      }
                      cb.removeAttribute("data-auto-check");
                    });

                    const event = new Event("change", {
                      bubbles: true,
                    });
                    container.dispatchEvent(event);
                  }
                }
              } catch (e) {
                console.warn("Error restoring associatedTools selections:", e);
              }
            }
          }
        }, 10); // Small delay to ensure DOM is updated
      }
    });
  }

  // Set up HTMX handler for auto-checking newly loaded resources when Select All is active
  if (window.htmx && !window._resourcesHtmxHandlerAttached) {
    Admin._resourcesHtmxHandlerAttached = true;

    window.htmx.on("htmx:afterSettle", function (evt) {
      // Only handle resource pagination requests
      if (
        evt.detail.pathInfo &&
        evt.detail.pathInfo.requestPath &&
        evt.detail.pathInfo.requestPath.includes("/admin/resources/partial")
      ) {
        setTimeout(() => {
          // Find the container
          let container = null;
          const target = evt.detail.target;

          if (target && target.id === "edit-server-resources") {
            container = target;
          } else if (target && target.id === "associatedResources") {
            container = target;
          } else if (target) {
            container =
              target.closest("#associatedResources") ||
              target.closest("#edit-server-resources");
          }

          if (!container) {
            const editModal = safeGetElement("server-edit-modal");
            const isEditModalOpen =
              editModal && !editModal.classList.contains("hidden");

            if (isEditModalOpen) {
              container = safeGetElement("edit-server-resources");
            } else {
              container = safeGetElement("associatedResources");
            }
          }

          if (container) {
            const newCheckboxes = container.querySelectorAll(
              "input[data-auto-check=true]"
            );

            const selectAllInput = container.querySelector(
              'input[name="selectAllResources"]'
            );

            // Check if Select All is active
            if (selectAllInput && selectAllInput.value === "true") {
              newCheckboxes.forEach((cb) => {
                cb.checked = true;
                cb.removeAttribute("data-auto-check");
              });

              if (newCheckboxes.length > 0) {
                const event = new Event("change", {
                  bubbles: true,
                });
                container.dispatchEvent(event);
              }
            }

            // Also check for edit mode: pre-select items based on server's associated resources
            const dataAttr = container.getAttribute("data-server-resources");
            if (dataAttr) {
              try {
                const associatedResourceIds = JSON.parse(dataAttr);
                newCheckboxes.forEach((cb) => {
                  const checkboxValue = cb.value;
                  if (associatedResourceIds.includes(checkboxValue)) {
                    cb.checked = true;
                  }
                  cb.removeAttribute("data-auto-check");
                });

                if (newCheckboxes.length > 0) {
                  const event = new Event("change", {
                    bubbles: true,
                  });
                  container.dispatchEvent(event);
                }
              } catch (e) {
                console.error("Error parsing data-server-resources:", e);
              }
            }

            // If we're in the Add Server resources container, restore persisted selections
            else if (container.id === "associatedResources") {
              try {
                const dataAttr = container.getAttribute(
                  "data-selected-resources"
                );
                if (dataAttr) {
                  const selectedIds = JSON.parse(dataAttr);
                  if (Array.isArray(selectedIds) && selectedIds.length > 0) {
                    newCheckboxes.forEach((cb) => {
                      if (selectedIds.includes(cb.value)) {
                        cb.checked = true;
                      }
                      cb.removeAttribute("data-auto-check");
                    });

                    const event = new Event("change", {
                      bubbles: true,
                    });
                    container.dispatchEvent(event);
                  }
                }
              } catch (e) {
                console.warn(
                  "Error restoring associatedResources selections:",
                  e
                );
              }
            }
          }
        }, 10);
      }
    });
  }

  // Set up HTMX handler for auto-checking newly loaded prompts when Select All is active
  if (window.htmx && !window._promptsHtmxHandlerAttached) {
    Admin._promptsHtmxHandlerAttached = true;

    window.htmx.on("htmx:afterSettle", function (evt) {
      // Only handle prompt pagination requests
      if (
        evt.detail.pathInfo &&
        evt.detail.pathInfo.requestPath &&
        evt.detail.pathInfo.requestPath.includes("/admin/prompts/partial")
      ) {
        setTimeout(() => {
          // Find the container
          let container = null;
          const target = evt.detail.target;

          if (target && target.id === "edit-server-prompts") {
            container = target;
          } else if (target && target.id === "associatedPrompts") {
            container = target;
          } else if (target) {
            container =
              target.closest("#associatedPrompts") ||
              target.closest("#edit-server-prompts");
          }

          if (!container) {
            const editModal = safeGetElement("server-edit-modal");
            const isEditModalOpen =
              editModal && !editModal.classList.contains("hidden");

            if (isEditModalOpen) {
              container = safeGetElement("edit-server-prompts");
            } else {
              container = safeGetElement("associatedPrompts");
            }
          }

          if (container) {
            const newCheckboxes = container.querySelectorAll(
              "input[data-auto-check=true]"
            );

            const selectAllInput = container.querySelector(
              'input[name="selectAllPrompts"]'
            );

            // Check if Select All is active
            if (selectAllInput && selectAllInput.value === "true") {
              newCheckboxes.forEach((cb) => {
                cb.checked = true;
                cb.removeAttribute("data-auto-check");
              });

              if (newCheckboxes.length > 0) {
                const event = new Event("change", {
                  bubbles: true,
                });
                container.dispatchEvent(event);
              }
            }

            // Also check for edit mode: pre-select items based on server's associated prompts
            const dataAttr = container.getAttribute("data-server-prompts");
            if (dataAttr) {
              try {
                const associatedPromptIds = JSON.parse(dataAttr);
                newCheckboxes.forEach((cb) => {
                  const checkboxValue = cb.value;
                  if (associatedPromptIds.includes(checkboxValue)) {
                    cb.checked = true;
                  }
                  cb.removeAttribute("data-auto-check");
                });

                if (newCheckboxes.length > 0) {
                  const event = new Event("change", {
                    bubbles: true,
                  });
                  container.dispatchEvent(event);
                }
              } catch (e) {
                console.error("Error parsing data-server-prompts:", e);
              }
            }

            // If we're in the Add Server prompts container, restore persisted selections
            else if (container.id === "associatedPrompts") {
              try {
                const dataAttr = container.getAttribute(
                  "data-selected-prompts"
                );
                if (dataAttr) {
                  const selectedIds = JSON.parse(dataAttr);
                  if (Array.isArray(selectedIds) && selectedIds.length > 0) {
                    newCheckboxes.forEach((cb) => {
                      if (selectedIds.includes(cb.value)) {
                        cb.checked = true;
                      }
                      cb.removeAttribute("data-auto-check");
                    });

                    const event = new Event("change", {
                      bubbles: true,
                    });
                    container.dispatchEvent(event);
                  }
                }
              } catch (e) {
                console.warn(
                  "Error restoring associatedPrompts selections:",
                  e
                );
              }
            }
          }
        }, 10);
      }
    });
  }

  // ===================================================================
  // SEARCH & FILTERING FUNCTIONS
  // ===================================================================

  /**
   * Filter server table rows based on search text
   */
  Admin.filterServerTable = function (searchText) {
    try {
      // Try to find the table using multiple strategies
      let tbody = document.querySelector("#servers-table-body");

      // Fallback to data-testid selector for backward compatibility
      if (!tbody) {
        tbody = document.querySelector('tbody[data-testid="server-list"]');
      }

      if (!tbody) {
        console.warn("Server table not found");
        return;
      }

      const rows = tbody.querySelectorAll('tr[data-testid="server-item"]');
      const search = searchText.toLowerCase().trim();

      rows.forEach((row) => {
        let textContent = "";

        // Get text from all searchable cells (exclude Actions, Icon, and S.No. columns)
        // Table columns: Admin.Actions(0), Admin.Icon(1), S.No.(2), Admin.UUID(3), Admin.Name(4), Admin.Description(5), Admin.Tools(6), Admin.Resources(7), Admin.Prompts(8), Admin.Tags(9), Admin.Owner(10), Admin.Team(11), Admin.Visibility(12)
        const cells = row.querySelectorAll("td");
        // Search all columns except Admin.Actions(0), Admin.Icon(1), and S.No.(2) columns
        const searchableColumnIndices = [];
        for (let i = 3; i < cells.length; i++) {
          searchableColumnIndices.push(i);
        }

        searchableColumnIndices.forEach((index) => {
          if (cells[index]) {
            // Clean the text content and make it searchable
            const cellText = cells[index].textContent
              .replace(/\s+/g, " ")
              .trim();
            textContent += " " + cellText;
          }
        });

        if (search === "" || textContent.toLowerCase().includes(search)) {
          row.style.display = "";
        } else {
          row.style.display = "none";
        }
      });
    } catch (error) {
      console.error("Error filtering server table:", error);
    }
  };

  /**
   * Filter Tools table based on search text
   */
  Admin.filterToolsTable = function (searchText) {
    try {
      const tbody = document.querySelector("#tools-table-body");
      if (!tbody) {
        console.warn("Tools table body not found");
        return;
      }

      const rows = tbody.querySelectorAll("tr");
      const search = searchText.toLowerCase().trim();

      rows.forEach((row) => {
        let textContent = "";

        // Get text from searchable cells (exclude Actions and S.No. columns)
        // Tools columns: Admin.Actions(0), S.No.(1), Admin.Source(2), Admin.Name(3), Admin.RequestType(4), Admin.Description(5), Admin.Annotations(6), Admin.Tags(7), Admin.Owner(8), Admin.Team(9), Admin.Status(10)
        const cells = row.querySelectorAll("td");
        const searchableColumns = [2, 3, 4, 5, 6, 7, 8, 9, 10]; // Exclude Admin.Actions(0) and S.No.(1)

        searchableColumns.forEach((index) => {
          if (cells[index]) {
            // Clean the text content and make it searchable
            const cellText = cells[index].textContent
              .replace(/\s+/g, " ")
              .trim();
            textContent += " " + cellText;
          }
        });

        const isMatch =
          search === "" || textContent.toLowerCase().includes(search);
        if (isMatch) {
          row.style.display = "";
        } else {
          row.style.display = "none";
        }
      });
    } catch (error) {
      console.error("Error filtering tools table:", error);
    }
  };

  /**
   * Filter Resources table based on search text
   */
  Admin.filterResourcesTable = function (searchText) {
    try {
      const tbody = document.querySelector("#resources-table-body");
      if (!tbody) {
        console.warn("Resources table body not found");
        return;
      }

      const rows = tbody.querySelectorAll("tr");
      const search = searchText.toLowerCase().trim();

      rows.forEach((row) => {
        let textContent = "";

        // Get text from searchable cells (exclude Actions column)
        // Resources columns: Admin.Actions(0), Admin.Source(1), Admin.Name(2), Admin.Description(3), Admin.Tags(4), Admin.Owner(5), Admin.Team(6), Admin.Status(7)
        const cells = row.querySelectorAll("td");
        const searchableColumns = [1, 2, 3, 4, 5, 6, 7]; // All except Admin.Actions(0)

        searchableColumns.forEach((index) => {
          if (cells[index]) {
            textContent += " " + cells[index].textContent;
          }
        });

        if (search === "" || textContent.toLowerCase().includes(search)) {
          row.style.display = "";
        } else {
          row.style.display = "none";
        }
      });
    } catch (error) {
      console.error("Error filtering resources table:", error);
    }
  };

  /**
   * Filter Prompts table based on search text
   */
  Admin.filterPromptsTable = function (searchText) {
    try {
      const tbody = document.querySelector("#prompts-table-body");
      if (!tbody) {
        console.warn("Prompts table body not found");
        return;
      }

      const rows = tbody.querySelectorAll("tr");
      const search = searchText.toLowerCase().trim();

      rows.forEach((row) => {
        let textContent = "";

        // Get text from searchable cells (exclude Actions and S.No. columns)
        // Prompts columns: Admin.Actions(0), S.No.(1), Admin.GatewayName(2), Admin.Name(3), Admin.Description(4), Admin.Tags(5), Admin.Owner(6), Admin.Team(7), Admin.Status(8)
        const cells = row.querySelectorAll("td");
        const searchableColumns = [2, 3, 4, 5, 6, 7, 8]; // All except Admin.Actions(0) and S.No.(1)

        searchableColumns.forEach((index) => {
          if (cells[index]) {
            textContent += " " + cells[index].textContent;
          }
        });

        if (search === "" || textContent.toLowerCase().includes(search)) {
          row.style.display = "";
        } else {
          row.style.display = "none";
        }
      });
    } catch (error) {
      console.error("Error filtering prompts table:", error);
    }
  };

  /**
   * Filter A2A Agents table based on search text
   */
  Admin.filterA2AAgentsTable = function (searchText) {
    try {
      // Try to find the table using multiple strategies
      let tbody = document.querySelector("#agents-table tbody");

      // Fallback to panel selector for backward compatibility
      if (!tbody) {
        tbody = document.querySelector("#a2a-agents-panel tbody");
      }

      if (!tbody) {
        console.warn("A2A Agents table body not found");
        return;
      }

      const rows = tbody.querySelectorAll("tr");
      const search = searchText.toLowerCase().trim();

      rows.forEach((row) => {
        let textContent = "";

        // Get text from searchable cells (exclude Actions and ID columns)
        // A2A Agents columns: Admin.Actions(0), Admin.ID(1), Admin.Name(2), Admin.Description(3), Admin.Endpoint(4), Admin.Tags(5), Admin.Type(6), Admin.Status(7), Admin.Reachability(8), Admin.Owner(9), Admin.Team(10), Admin.Visibility(11)
        const cells = row.querySelectorAll("td");
        const searchableColumns = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]; // Exclude Admin.Actions(0) and Admin.ID(1)

        searchableColumns.forEach((index) => {
          if (cells[index]) {
            textContent += " " + cells[index].textContent;
          }
        });

        if (search === "" || textContent.toLowerCase().includes(search)) {
          row.style.display = "";
        } else {
          row.style.display = "none";
        }
      });
    } catch (error) {
      console.error("Error filtering A2A agents table:", error);
    }
  };

  /**
   * Filter MCP Servers (Gateways) table based on search text
   */
  Admin.filterGatewaysTable = function (searchText) {
    try {
      console.log("🔍 Starting MCP Servers search for:", searchText);

      // Find the MCP servers table - use multiple strategies
      let table = null;

      // Strategy 1: Direct selector for gateways panel
      const gatewaysPanel = document.querySelector("#gateways-panel");
      if (gatewaysPanel) {
        table = gatewaysPanel.querySelector("table");
        console.log("✅ Found table in gateways panel");
      }

      // Strategy 2: Look for table in currently visible tab
      if (!table) {
        const visiblePanel = document.querySelector(".tab-panel:not(.hidden)");
        if (visiblePanel) {
          table = visiblePanel.querySelector("table");
          console.log("✅ Found table in visible panel");
        }
      }

      // Strategy 3: Just look for any table with MCP server structure
      if (!table) {
        const allTables = document.querySelectorAll("table");
        for (const t of allTables) {
          const headers = t.querySelectorAll("thead th");
          if (headers.length >= 8) {
            // Check for MCP server specific headers
            const headerTexts = Array.from(headers).map((h) =>
              h.textContent.toLowerCase().trim()
            );
            if (
              headerTexts.includes("name") &&
              headerTexts.includes("url") &&
              headerTexts.includes("status")
            ) {
              table = t;
              console.log("✅ Found MCP table by header matching");
              break;
            }
          }
        }
      }

      if (!table) {
        console.warn("❌ No MCP servers table found");
        return;
      }

      const tbody = table.querySelector("tbody");
      if (!tbody) {
        console.warn("❌ No tbody found");
        return;
      }

      const rows = tbody.querySelectorAll("tr");
      if (rows.length === 0) {
        console.warn("❌ No rows found");
        return;
      }

      const search = searchText.toLowerCase().trim();
      console.log(`🔍 Searching ${rows.length} rows for: "${search}"`);

      let visibleCount = 0;

      rows.forEach((row, index) => {
        const cells = row.querySelectorAll("td");

        if (cells.length === 0) {
          return;
        }

        // Combine text from all cells except Admin.Actions(0) and S.No.(1) columns
        // Gateways columns: Admin.Actions(0), S.No.(1), Admin.Name(2), Admin.URL(3), Admin.Tags(4), Admin.Status(5), Admin.LastSeen(6), Admin.Owner(7), Admin.Team(8), Admin.Visibility(9)
        let searchContent = "";
        for (let i = 2; i < cells.length; i++) {
          if (cells[i]) {
            const cellText = cells[i].textContent.trim();
            searchContent += " " + cellText;
          }
        }

        const fullText = searchContent.trim().toLowerCase();
        const matchesSearch = search === "" || fullText.includes(search);

        // Check if row should be visible based on inactive filter
        const checkbox = safeGetElement("show-inactive-gateways");
        const showInactive = checkbox ? checkbox.checked : true;
        const isEnabled = row.getAttribute("data-enabled") === "true";
        const matchesFilter = showInactive || isEnabled;

        // Only show row if it matches BOTH search AND filter
        const shouldShow = matchesSearch && matchesFilter;

        // Debug first few rows
        if (index < 3) {
          console.log(
            `Row ${index + 1}: "${fullText.substring(0, 50)}..." -> Search: ${matchesSearch}, Filter: ${matchesFilter}, Show: ${shouldShow}`
          );
        }

        // Show/hide the row
        if (shouldShow) {
          row.style.removeProperty("display");
          row.style.removeProperty("visibility");
          visibleCount++;
        } else {
          row.style.display = "none";
          row.style.visibility = "hidden";
        }
      });

      console.log(
        `✅ Search complete: ${visibleCount}/${rows.length} rows visible`
      );
    } catch (error) {
      console.error("❌ Error in filterGatewaysTable:", error);
    }
  };

  // Add a test function for debugging
  Admin.testGatewaySearch = function (searchTerm = "Cou") {
    console.log("🧪 Testing gateway search with:", searchTerm);
    console.log("Available tables:", document.querySelectorAll("table").length);

    // Test the search input exists
    const searchInput = safeGetElement("gateways-search-input");
    console.log("Search input found:", !!searchInput);

    if (searchInput) {
      searchInput.value = searchTerm;
      console.log("Set search input value to:", searchInput.value);
    }

    Admin.filterGatewaysTable(searchTerm);
  };

  // Simple fallback search function
  Admin.simpleGatewaySearch = function (searchTerm) {
    console.log("🔧 Simple gateway search for:", searchTerm);

    // Find any table in the current tab/page
    const tables = document.querySelectorAll("table");
    console.log("Found tables:", tables.length);

    tables.forEach((table, tableIndex) => {
      const tbody = table.querySelector("tbody");
      if (!tbody) {
        return;
      }

      const rows = tbody.querySelectorAll("tr");
      console.log(`Table ${tableIndex}: ${rows.length} rows`);

      if (rows.length > 0) {
        // Check if this looks like the MCP servers table
        const firstRow = rows[0];
        const cells = firstRow.querySelectorAll("td");

        if (cells.length >= 8) {
          // MCP servers table should have many columns
          console.log(
            `Table ${tableIndex} looks like MCP servers table with ${cells.length} columns`
          );

          const search = searchTerm.toLowerCase().trim();
          let visibleCount = 0;

          rows.forEach((row) => {
            const cells = row.querySelectorAll("td");
            let rowText = "";

            // Get text from all cells except Admin.Actions(0) and S.No.(1)
            for (let i = 2; i < cells.length; i++) {
              rowText += " " + cells[i].textContent.trim();
            }

            const shouldShow =
              search === "" || rowText.toLowerCase().includes(search);

            if (shouldShow) {
              row.style.display = "";
              visibleCount++;
            } else {
              row.style.display = "none";
            }
          });

          console.log(
            `✅ Simple search complete: ${visibleCount}/${rows.length} rows visible`
          );
          // Found the table, stop searching
        }
      }
    });
  };

  // Add initialization test function
  Admin.testSearchInit = function () {
    console.log("🧪 Testing search initialization...");
    initializeSearchInputs();
  };

  /**
   * Clear search functionality for different entity types
   */
  Admin.clearSearch = function (entityType) {
    try {
      if (entityType === "catalog") {
        const searchInput = safeGetElement("catalog-search-input");
        if (searchInput) {
          searchInput.value = "";
          Admin.filterServerTable(""); // Clear the filter
        }
      } else if (entityType === "tools") {
        const searchInput = safeGetElement("tools-search-input");
        if (searchInput) {
          searchInput.value = "";
          Admin.filterToolsTable(""); // Clear the filter
        }
      } else if (entityType === "resources") {
        const searchInput = safeGetElement("resources-search-input");
        if (searchInput) {
          searchInput.value = "";
          Admin.filterResourcesTable(""); // Clear the filter
        }
      } else if (entityType === "prompts") {
        const searchInput = safeGetElement("prompts-search-input");
        if (searchInput) {
          searchInput.value = "";
          Admin.filterPromptsTable(""); // Clear the filter
        }
      } else if (entityType === "a2a-agents") {
        const searchInput = safeGetElement("a2a-agents-search-input");
        if (searchInput) {
          searchInput.value = "";
          Admin.filterA2AAgentsTable(""); // Clear the filter
        }
      } else if (entityType === "gateways") {
        const searchInput = safeGetElement("gateways-search-input");
        if (searchInput) {
          searchInput.value = "";
          Admin.filterGatewaysTable(""); // Clear the filter
        }
      } else if (entityType === "gateways") {
        const searchInput = safeGetElement("gateways-search-input");
        if (searchInput) {
          searchInput.value = "";
          Admin.filterGatewaysTable(""); // Clear the filter
        }
      }
    } catch (error) {
      console.error("Error clearing search:", error);
    }
  };

  // ===================================================================
  // TEAM DISCOVERY AND SELF-SERVICE FUNCTIONS
  // ===================================================================

  /**
   * Load and display public teams that the user can join
   */
  Admin.loadPublicTeams = async function () {
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
      Admin.displayPublicTeams(teams);
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
  Admin.displayPublicTeams = function (teams) {
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
  Admin.requestToJoinTeam = async function (teamId) {
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
  Admin.leaveTeam = async function (teamId, teamName) {
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
  Admin.approveJoinRequest = async function (teamId, requestId) {
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
  Admin.rejectJoinRequest = async function (teamId, requestId) {
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
          errorData?.detail ||
            `Failed to reject join request: ${response.status}`
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
  Admin.getPasswordPolicy = function () {
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

  Admin.updateRequirementIcon = function (elementId, isValid) {
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

  Admin.validatePasswordRequirements = function () {
    const policy = Admin.getPasswordPolicy();
    const passwordField = safeGetElement("password-field", true);
    if (!policy || !passwordField) {
      return;
    }

    const password = passwordField.value || "";
    const lengthCheck = password.length >= policy.minLength;
    Admin.updateRequirementIcon("edit-req-length", lengthCheck);

    const uppercaseCheck = !policy.requireUppercase || /[A-Z]/.test(password);
    Admin.updateRequirementIcon("edit-req-uppercase", uppercaseCheck);

    const lowercaseCheck = !policy.requireLowercase || /[a-z]/.test(password);
    Admin.updateRequirementIcon("edit-req-lowercase", lowercaseCheck);

    const numbersCheck = !policy.requireNumbers || /[0-9]/.test(password);
    Admin.updateRequirementIcon("edit-req-numbers", numbersCheck);

    const specialChars = "!@#$%^&*()_+-=[]{};:'\"\\|,.<>`~/?";
    const specialCheck =
      !policy.requireSpecial ||
      [...password].some((char) => specialChars.includes(char));
    Admin.updateRequirementIcon("edit-req-special", specialCheck);

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

  Admin.initializePasswordValidation = function (root = document) {
    if (
      root?.querySelector?.("#password-field") ||
      safeGetElement("password-field", true)
    ) {
      Admin.validatePasswordRequirements();
      Admin.validatePasswordMatch();
    }
  };

  Admin.validatePasswordMatch = function () {
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

  // ===================================================================
  // SELECTIVE IMPORT FUNCTIONS
  // ===================================================================

  /**
   * Display import preview with selective import options
   */
  Admin.displayImportPreview = function (preview) {
    console.log("📋 Displaying import preview:", preview);

    // Find or create preview container
    let previewContainer = safeGetElement("import-preview-container");
    if (!previewContainer) {
      previewContainer = document.createElement("div");
      previewContainer.id = "import-preview-container";
      previewContainer.className = "mt-6 border-t pt-6";

      // Insert after import options in the import section
      const importSection =
        document.querySelector("#import-drop-zone").parentElement.parentElement;
      importSection.appendChild(previewContainer);
    }

    previewContainer.innerHTML = `
              <h4 class="text-lg font-medium text-gray-900 dark:text-white mb-4">
                  📋 Selective Import - Choose What to Import
              </h4>

              <!-- Summary -->
              <div class="bg-blue-50 dark:bg-blue-900 border border-blue-200 dark:border-blue-800 rounded-lg p-4 mb-6">
                  <div class="flex items-center">
                      <div class="ml-3">
                          <h3 class="text-sm font-medium text-blue-800 dark:text-blue-200">
                              Found ${preview.summary.total_items} items in import file
                          </h3>
                          <div class="mt-1 text-sm text-blue-600 dark:text-blue-300">
                              ${Object.entries(preview.summary.by_type)
    .map(([type, count]) => `${type}: ${count}`)
    .join(", ")}
                          </div>
                      </div>
                  </div>
              </div>

              <!-- Selection Controls -->
              <div class="flex justify-between items-center mb-4">
                  <div class="space-x-4">
                      <button onclick="Admin.selectAllItems()"
                              class="text-sm text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 underline">
                          Select All
                      </button>
                      <button onclick="Admin.selectNoneItems()"
                              class="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-300 underline">
                          Select None
                      </button>
                      <button onclick="Admin.selectOnlyCustom()"
                              class="text-sm text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-300 underline">
                          Custom Items Only
                      </button>
                  </div>

                  <div class="text-sm text-gray-500 dark:text-gray-400">
                      <span id="selection-count">0 items selected</span>
                  </div>
              </div>

              <!-- Gateway Bundles -->
              ${
  Object.keys(preview.bundles || {}).length > 0
    ? `
                  <div class="mb-6">
                      <h5 class="text-md font-medium text-gray-900 dark:text-white mb-3">
                          🌐 Gateway Bundles (Gateway + Auto-discovered Items)
                      </h5>
                      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                          ${Object.entries(preview.bundles)
    .map(
      ([gatewayName, bundle]) => `
                              <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-4 hover:bg-gray-50 dark:hover:bg-gray-750">
                                  <label class="flex items-start cursor-pointer">
                                      <input type="checkbox"
                                          class="gateway-checkbox mt-1 mr-3"
                                          data-gateway="${gatewayName}"
                                          onchange="Admin.updateSelectionCount()">
                                      <div class="flex-1">
                                          <div class="font-medium text-gray-900 dark:text-white">
                                              ${bundle.gateway.name}
                                          </div>
                                          <div class="text-sm text-gray-500 dark:text-gray-400 mb-2">
                                              ${bundle.gateway.description || "No description"}
                                          </div>
                                          <div class="text-xs text-blue-600 dark:text-blue-400">
                                              Bundle includes: ${bundle.total_items} items
                                              (${Object.entries(bundle.items)
    .filter(
      ([type, items]) =>
        items.length > 0
    )
    .map(
      ([type, items]) =>
        `${items.length} ${type}`
    )
    .join(", ")})
                                          </div>
                                      </div>
                                  </label>
                              </div>
                          `
    )
    .join("")}
                      </div>
                  </div>
              `
    : ""
  }

              <!-- Custom Items by Type -->
              ${Object.entries(preview.items || {})
    .map(([entityType, items]) => {
      const customItems = items.filter((item) => item.is_custom);
      return customItems.length > 0
        ? `
                      <div class="mb-6">
                          <h5 class="text-md font-medium text-gray-900 dark:text-white mb-3 capitalize">
                              🛠️ Custom ${entityType}
                          </h5>
                          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                              ${customItems
    .map(
      (item) => `
                                  <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-3 hover:bg-gray-50 dark:hover:bg-gray-750 ${item.conflicts_with ? "border-orange-300 dark:border-orange-700 bg-orange-50 dark:bg-orange-900" : ""}">
                                      <label class="flex items-start cursor-pointer">
                                          <input type="checkbox"
                                              class="item-checkbox mt-1 mr-3"
                                              data-type="${entityType}"
                                              data-id="${item.id}"
                                              onchange="Admin.updateSelectionCount()">
                                          <div class="flex-1">
                                              <div class="text-sm font-medium text-gray-900 dark:text-white">
                                                  ${item.name}
                                                  ${
  item.conflicts_with
    ? '<span class="text-orange-600 text-xs ml-1">⚠️ Conflict</span>'
    : ""
  }
                                              </div>
                                              <div class="text-xs text-gray-500 dark:text-gray-400">
                                                  ${item.description || `Custom ${entityType} item`}
                                              </div>
                                          </div>
                                      </label>
                                  </div>
                              `
    )
    .join("")}
                          </div>
                      </div>
                  `
        : "";
    })
    .join("")}

              <!-- Conflicts Warning -->
              ${
  Object.keys(preview.conflicts || {}).length > 0
    ? `
                  <div class="mb-6">
                      <div class="bg-orange-50 dark:bg-orange-900 border border-orange-200 dark:border-orange-800 rounded-lg p-4">
                          <div class="flex items-start">
                              <div class="flex-shrink-0">
                                  <svg class="h-5 w-5 text-orange-400" fill="currentColor" viewBox="0 0 20 20">
                                      <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
                                  </svg>
                              </div>
                              <div class="ml-3">
                                  <h3 class="text-sm font-medium text-orange-800 dark:text-orange-200">
                                      Naming conflicts detected
                                  </h3>
                                  <div class="mt-1 text-sm text-orange-600 dark:text-orange-300">
                                      Some items have the same names as existing items. Use conflict strategy to resolve.
                                  </div>
                              </div>
                          </div>
                      </div>
                  </div>
              `
    : ""
  }

              <!-- Action Buttons -->
              <div class="flex justify-between pt-6 border-t border-gray-200 dark:border-gray-700">
                  <button onclick="Admin.resetImportSelection()"
                          class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-700">
                      🔄 Reset Selection
                  </button>

                  <div class="space-x-3">
                      <button onclick="Admin.handleSelectiveImport(true)"
                              class="px-4 py-2 text-sm font-medium text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-900 border border-blue-200 dark:border-blue-800 rounded-md hover:bg-blue-100 dark:hover:bg-blue-800">
                          🧪 Preview Selected
                      </button>
                      <button onclick="Admin.handleSelectiveImport(false)"
                              class="px-4 py-2 text-sm font-medium text-white bg-green-600 border border-transparent rounded-md hover:bg-green-700">
                          ✅ Import Selected Items
                      </button>
                  </div>
              </div>
          `;

    // Store preview data and show preview section
    Admin.currentImportPreview = preview;
    Admin.updateSelectionCount();
  };

  /**
   * Handle selective import based on user selections
   */
  Admin.handleSelectiveImport = async function (dryRun = false) {
    console.log(`🎯 Starting selective import (dry_run=${dryRun})`);

    if (!window.currentImportData) {
      showNotification("❌ Please select an import file first", "error");
      return;
    }

    try {
      showImportProgress(true);

      // Collect user selections
      const selectedEntities = Admin.collectUserSelections();

      if (Object.keys(selectedEntities).length === 0) {
        showNotification(
          "❌ Please select at least one item to import",
          "warning"
        );
        showImportProgress(false);
        return;
      }

      const conflictStrategy =
        safeGetElement("import-conflict-strategy")?.value || "update";
      const rekeySecret = safeGetElement("import-rekey-secret")?.value || null;

      const requestData = {
        import_data: window.currentImportData,
        conflict_strategy: conflictStrategy,
        dry_run: dryRun,
        rekey_secret: rekeySecret,
        selectedEntities,
      };

      console.log("🎯 Selected entities for import:", selectedEntities);

      const response = await fetch(
        (window.ROOT_PATH || "") + "/admin/import/configuration",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${await getAuthToken()}`,
          },
          body: JSON.stringify(requestData),
        }
      );

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(
          errorData.detail || `Import failed: ${response.statusText}`
        );
      }

      const result = await response.json();
      displayImportResults(result, dryRun);

      if (!dryRun) {
        refreshCurrentTabData();
        showNotification(
          "✅ Selective import completed successfully",
          "success"
        );
      } else {
        showNotification("✅ Import preview completed", "success");
      }
    } catch (error) {
      console.error("Selective import error:", error);
      showNotification(`❌ Import failed: ${error.message}`, "error");
    } finally {
      showImportProgress(false);
    }
  };

  /**
   * Collect user selections for selective import
   */
  Admin.collectUserSelections = function () {
    const selections = {};

    // Collect gateway selections
    document
      .querySelectorAll(".gateway-checkbox:checked")
      .forEach((checkbox) => {
        const gatewayName = checkbox.dataset.gateway;
        if (!selections.gateways) {
          selections.gateways = [];
        }
        selections.gateways.push(gatewayName);
      });

    // Collect individual item selections
    document.querySelectorAll(".item-checkbox:checked").forEach((checkbox) => {
      const entityType = checkbox.dataset.type;
      const itemId = checkbox.dataset.id;
      if (!selections[entityType]) {
        selections[entityType] = [];
      }
      selections[entityType].push(itemId);
    });

    return selections;
  };

  /**
   * Update selection count display
   */
  Admin.updateSelectionCount = function () {
    const gatewayCount = document.querySelectorAll(
      ".gateway-checkbox:checked"
    ).length;
    const itemCount = document.querySelectorAll(
      ".item-checkbox:checked"
    ).length;
    const totalCount = gatewayCount + itemCount;

    const countElement = safeGetElement("selection-count");
    if (countElement) {
      countElement.textContent = `${totalCount} items selected (${gatewayCount} gateways, ${itemCount} individual items)`;
    }
  };

  /**
   * Select all items
   */
  Admin.selectAllItems = function () {
    document
      .querySelectorAll(".gateway-checkbox, .item-checkbox")
      .forEach((checkbox) => {
        checkbox.checked = true;
      });
    Admin.updateSelectionCount();
  };

  /**
   * Select no items
   */
  Admin.selectNoneItems = function () {
    document
      .querySelectorAll(".gateway-checkbox, .item-checkbox")
      .forEach((checkbox) => {
        checkbox.checked = false;
      });
    Admin.updateSelectionCount();
  };

  /**
   * Select only custom items (not gateway items)
   */
  Admin.selectOnlyCustom = function () {
    document.querySelectorAll(".gateway-checkbox").forEach((checkbox) => {
      checkbox.checked = false;
    });
    document.querySelectorAll(".item-checkbox").forEach((checkbox) => {
      checkbox.checked = true;
    });
    Admin.updateSelectionCount();
  };

  /**
   * Reset import selection
   */
  Admin.resetImportSelection = function () {
    const previewContainer = safeGetElement("import-preview-container");
    if (previewContainer) {
      previewContainer.remove();
    }
    Admin.currentImportPreview = null;
  };

  /* ---------------------------------------------------------------------------
  Robust reloadAllResourceSections
  - Replaces each section's full innerHTML with a server-rendered partial
  - Restores saved initial markup on failure
  - Re-runs initializers (Alpine, CodeMirror, select/pills, event handlers)
  --------------------------------------------------------------------------- */

  Admin.registerReloadAllResourceSections = function () {
    // list of sections we manage
    const SECTION_NAMES = [
      "tools",
      "resources",
      "prompts",
      "servers",
      "gateways",
      "catalog",
    ];

    // Save initial markup on first full load so we can restore exactly if needed
    document.addEventListener("DOMContentLoaded", () => {
      Admin.__initialSectionMarkup = window.__initialSectionMarkup || {};
      SECTION_NAMES.forEach((s) => {
        const el = safeGetElement(`${s}-section`);
        if (el && !(s in window.__initialSectionMarkup)) {
          // store the exact innerHTML produced by the server initially
          Admin.__initialSectionMarkup[s] = el.innerHTML;
        }
      });
    });

    // Helper: try to re-run common initializers after a section's DOM is replaced
    Admin.reinitializeSection = function (sectionEl, sectionName) {
      try {
        if (!sectionEl) {
          return;
        }

        // 1) Re-init Alpine for the new subtree (if Alpine is present)
        try {
          if (window.Alpine) {
            // For Alpine 3 use initTree if available
            if (typeof window.Alpine.initTree === "function") {
              window.Alpine.initTree(sectionEl);
            } else if (
              typeof window.Alpine.discoverAndRegisterComponents === "function"
            ) {
              // fallback: attempt a component discovery if available
              window.Alpine.discoverAndRegisterComponents(sectionEl);
            }
          }
        } catch (err) {
          console.warn("Alpine re-init failed for section", sectionName, err);
        }

        // 2) Re-initialize tool/resource/pill helpers that expect DOM structure
        try {
          // these functions exist elsewhere in admin.js; call them if present
          if (typeof initResourceSelect === "function") {
            // Many panels use specific ids — attempt to call generic initializers if they exist
            initResourceSelect(
              "associatedResources",
              "selectedResourcePills",
              "selectedResourceWarning",
              10,
              null,
              null
            );
          }
          if (typeof initToolSelect === "function") {
            initToolSelect(
              "associatedTools",
              "selectedToolsPills",
              "selectedToolsWarning",
              10,
              null,
              null
            );
          }
          // restore generic tool/resource selection areas if present
          if (typeof initResourceSelect === "function") {
            // try specific common containers if present (safeGetElement suppresses warnings)
            const containers = ["edit-server-resources", "edit-server-tools"];
            containers.forEach((cid) => {
              const c = safeGetElement(cid);
              if (c && typeof initResourceSelect === "function") {
                // caller may have different arg signature — best-effort call is OK
                // we don't want to throw here if arguments mismatch
                try {
                  /* no args: assume function will find DOM by ids */ initResourceSelect();
                } catch (e) {
                  /* ignore */
                }
              }
            });
          }
        } catch (err) {
          console.warn("Select/pill reinit error", err);
        }

        // 3) Re-run integration & schema handlers which attach behaviour to new inputs
        try {
          if (typeof setupIntegrationTypeHandlers === "function") {
            setupIntegrationTypeHandlers();
          }
          if (typeof setupSchemaModeHandlers === "function") {
            setupSchemaModeHandlers();
          }
        } catch (err) {
          console.warn("Integration/schema handler reinit failed", err);
        }

        // 4) Reinitialize CodeMirror editors within the replaced DOM (if CodeMirror used)
        try {
          if (window.CodeMirror) {
            // For any <textarea class="codemirror"> re-create or refresh editors
            const textareas = sectionEl.querySelectorAll("textarea");
            textareas.forEach((ta) => {
              // If the page previously attached a CodeMirror instance on same textarea,
              // the existing instance may have been stored on the element. If refresh available, refresh it.
              if (
                ta.CodeMirror &&
                typeof ta.CodeMirror.refresh === "function"
              ) {
                ta.CodeMirror.refresh();
              } else {
                // Create a new CodeMirror instance only when an explicit init function is present on page
                if (typeof window.createCodeMirrorForTextarea === "function") {
                  try {
                    window.createCodeMirrorForTextarea(ta);
                  } catch (e) {
                    // ignore - not all textareas need CodeMirror
                  }
                }
              }
            });
          }
        } catch (err) {
          console.warn("CodeMirror reinit failed", err);
        }

        // 5) Re-attach generic event wiring that is expected by the UI (checkboxes, buttons)
        try {
          // checkbox-driven pill updates
          const checkboxChangeEvent = new Event("change", {
            bubbles: true,
          });
          sectionEl.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
            // If there were checkbox-specific change functions on page, they will now re-run
            cb.dispatchEvent(checkboxChangeEvent);
          });

          // Reconnect any HTMX triggers that expect a load event
          if (window.htmx && typeof window.htmx.trigger === "function") {
            // find elements with data-htmx or that previously had an HTMX load
            const htmxTargets = sectionEl.querySelectorAll(
              "[hx-get], [hx-post], [data-hx-load]"
            );
            htmxTargets.forEach((el) => {
              try {
                window.htmx.trigger(el, "load");
              } catch (e) {
                /* ignore */
              }
            });
          }
        } catch (err) {
          console.warn("Event wiring re-attach failed", err);
        }

        // 6) Accessibility / visual: force a small layout reflow, useful in some browsers
        try {
          // eslint-disable-next-line no-unused-expressions
          sectionEl.offsetHeight; // read to force reflow
        } catch (e) {
          /* ignore */
        }
      } catch (err) {
        console.error("Error reinitializing section", sectionName, err);
      }
    };

    Admin.updateSectionHeaders = function (teamId) {
      const sections = ["tools", "resources", "prompts", "servers", "gateways"];

      sections.forEach((section) => {
        const header = document.querySelector("#" + section + "-section h2");
        if (header) {
          // Remove existing team badge
          const existingBadge = header.querySelector(".team-badge");
          if (existingBadge) {
            existingBadge.remove();
          }

          // Add team badge if team is selected
          if (teamId && teamId !== "") {
            const teamName = getTeamNameById(teamId);
            if (teamName) {
              const badge = document.createElement("span");
              badge.className =
                "team-badge inline-flex items-center px-2 py-1 ml-2 text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 rounded-full";
              badge.textContent = teamName;
              header.appendChild(badge);
            }
          }
        }
      });
    };

    // The exported function: reloadAllResourceSections
    Admin.reloadAllResourceSections = async function (teamId) {
      const sections = ["tools", "resources", "prompts", "servers", "gateways"];

      // ensure there is a ROOT_PATH set
      if (!window.ROOT_PATH) {
        console.warn(
          "ROOT_PATH not defined; aborting reloadAllResourceSections"
        );
        return;
      }

      // Iterate sections sequentially to avoid overloading the server and to ensure consistent order.
      for (const section of sections) {
        const sectionEl = safeGetElement(`${section}-section`);
        if (!sectionEl) {
          console.warn(`Section element not found: ${section}-section`);
          continue;
        }

        // Build server partial URL (server should return the *full HTML fragment* for the section)
        // Server endpoint pattern: /admin/sections/{section}?partial=true
        let url = `${window.ROOT_PATH}/admin/sections/${section}?partial=true`;
        if (teamId && teamId !== "") {
          url += `&team_id=${encodeURIComponent(teamId)}`;
        }

        try {
          const resp = await fetchWithTimeout(
            url,
            { credentials: "same-origin" },
            window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000
          );
          if (!resp.ok) {
            throw new Error(`HTTP ${resp.status}`);
          }
          const html = await resp.text();

          // Replace entire section's innerHTML with server-provided HTML to keep DOM identical.
          // Use safeSetInnerHTML with isTrusted = true because this is server-rendered trusted content.
          safeSetInnerHTML(sectionEl, html, true);

          // After replacement, re-run local initializers so the new DOM behaves like initial load
          Admin.reinitializeSection(sectionEl, section);
        } catch (err) {
          console.error(`Failed to load section ${section} from server:`, err);

          // Restore the original markup exactly as it was on initial load (fallback)
          if (
            window.__initialSectionMarkup &&
            window.__initialSectionMarkup[section]
          ) {
            sectionEl.innerHTML = window.__initialSectionMarkup[section];
            // Re-run initializers on restored markup as well
            Admin.reinitializeSection(sectionEl, section);
            console.log(`Restored initial markup for section ${section}`);
          } else {
            // No fallback available: leave existing DOM intact and show error to console
            console.warn(
              `No saved initial markup for section ${section}; leaving DOM untouched`
            );
          }
        }
      }

      // Update headers (team badges) after reload
      try {
        if (typeof updateSectionHeaders === "function") {
          Admin.updateSectionHeaders(teamId);
        }
      } catch (err) {
        console.warn("updateSectionHeaders failed after reload", err);
      }

      console.log("✓ reloadAllResourceSections completed");
    };
  };

  Admin.registerReloadAllResourceSections();

  // Plugin management functions
  Admin.initializePluginFunctions = function () {
    // Populate hook, tag, and author filters on page load
    Admin.populatePluginFilters = function () {
      const cards = document.querySelectorAll(".plugin-card");
      const hookSet = new Set();
      const tagSet = new Set();
      const authorSet = new Set();

      cards.forEach((card) => {
        const hooks = card.dataset.hooks ? card.dataset.hooks.split(",") : [];
        const tags = card.dataset.tags ? card.dataset.tags.split(",") : [];
        const author = card.dataset.author;

        hooks.forEach((hook) => {
          if (hook.trim()) {
            hookSet.add(hook.trim());
          }
        });
        tags.forEach((tag) => {
          if (tag.trim()) {
            tagSet.add(tag.trim());
          }
        });
        if (author && author.trim()) {
          authorSet.add(author.trim());
        }
      });

      const hookFilter = safeGetElement("plugin-hook-filter");
      const tagFilter = safeGetElement("plugin-tag-filter");
      const authorFilter = safeGetElement("plugin-author-filter");

      if (hookFilter) {
        hookSet.forEach((hook) => {
          const option = document.createElement("option");
          option.value = hook;
          option.textContent = hook
            .replace(/_/g, " ")
            .replace(/\b\w/g, (l) => l.toUpperCase());
          hookFilter.appendChild(option);
        });
      }

      if (tagFilter) {
        tagSet.forEach((tag) => {
          const option = document.createElement("option");
          option.value = tag;
          option.textContent = tag;
          tagFilter.appendChild(option);
        });
      }

      if (authorFilter) {
        // Convert authorSet to array and sort for consistent ordering
        const sortedAuthors = Array.from(authorSet).sort();
        sortedAuthors.forEach((author) => {
          const option = document.createElement("option");
          // Value is lowercase (matches data-author), text is capitalized for display
          option.value = author.toLowerCase();
          option.textContent = author.charAt(0).toUpperCase() + author.slice(1);
          authorFilter.appendChild(option);
        });
      }
    };

    // Filter plugins based on search and filters
    Admin.filterPlugins = function () {
      const searchInput = safeGetElement("plugin-search");
      const modeFilter = safeGetElement("plugin-mode-filter");
      const statusFilter = safeGetElement("plugin-status-filter");
      const hookFilter = safeGetElement("plugin-hook-filter");
      const tagFilter = safeGetElement("plugin-tag-filter");
      const authorFilter = safeGetElement("plugin-author-filter");

      const searchQuery = searchInput ? searchInput.value.toLowerCase() : "";
      const selectedMode = modeFilter ? modeFilter.value : "";
      const selectedStatus = statusFilter ? statusFilter.value : "";
      const selectedHook = hookFilter ? hookFilter.value : "";
      const selectedTag = tagFilter ? tagFilter.value : "";
      const selectedAuthor = authorFilter ? authorFilter.value : "";

      // Update visual highlighting for all filter types
      Admin.updateBadgeHighlighting("hook", selectedHook);
      Admin.updateBadgeHighlighting("tag", selectedTag);
      Admin.updateBadgeHighlighting("author", selectedAuthor);

      const cards = document.querySelectorAll(".plugin-card");

      cards.forEach((card) => {
        const name = card.dataset.name ? card.dataset.name.toLowerCase() : "";
        const description = card.dataset.description
          ? card.dataset.description.toLowerCase()
          : "";
        const author = card.dataset.author
          ? card.dataset.author.toLowerCase()
          : "";
        const mode = card.dataset.mode;
        const status = card.dataset.status;
        const hooks = card.dataset.hooks ? card.dataset.hooks.split(",") : [];
        const tags = card.dataset.tags ? card.dataset.tags.split(",") : [];

        let visible = true;

        // Search filter
        if (
          searchQuery &&
          !name.includes(searchQuery) &&
          !description.includes(searchQuery) &&
          !author.includes(searchQuery)
        ) {
          visible = false;
        }

        // Mode filter
        if (selectedMode && mode !== selectedMode) {
          visible = false;
        }

        // Status filter
        if (selectedStatus && status !== selectedStatus) {
          visible = false;
        }

        // Hook filter
        if (selectedHook && !hooks.includes(selectedHook)) {
          visible = false;
        }

        // Tag filter
        if (selectedTag && !tags.includes(selectedTag)) {
          visible = false;
        }

        // Author filter
        if (
          selectedAuthor &&
          author.trim() !== selectedAuthor.toLowerCase().trim()
        ) {
          visible = false;
        }

        if (visible) {
          card.style.display = "block";
        } else {
          card.style.display = "none";
        }
      });
    };

    // Filter by hook when clicking on hook point
    Admin.filterByHook = function (hook) {
      const hookFilter = safeGetElement("plugin-hook-filter");
      if (hookFilter) {
        hookFilter.value = hook;
        Admin.filterPlugins();
        hookFilter.scrollIntoView({ behavior: "smooth", block: "nearest" });

        // Update visual highlighting
        Admin.updateBadgeHighlighting("hook", hook);
      }
    };

    // Filter by tag when clicking on tag
    Admin.filterByTag = function (tag) {
      const tagFilter = safeGetElement("plugin-tag-filter");
      if (tagFilter) {
        tagFilter.value = tag;
        Admin.filterPlugins();
        tagFilter.scrollIntoView({ behavior: "smooth", block: "nearest" });

        // Update visual highlighting
        Admin.updateBadgeHighlighting("tag", tag);
      }
    };

    // Filter by author when clicking on author
    Admin.filterByAuthor = function (author) {
      const authorFilter = safeGetElement("plugin-author-filter");
      if (authorFilter) {
        // Convert to lowercase to match data-author attribute
        authorFilter.value = author.toLowerCase();
        Admin.filterPlugins();
        authorFilter.scrollIntoView({
          behavior: "smooth",
          block: "nearest",
        });

        // Update visual highlighting
        Admin.updateBadgeHighlighting("author", author);
      }
    };

    // Helper function to update badge highlighting
    Admin.updateBadgeHighlighting = function (type, value) {
      // Define selectors for each type
      const selectors = {
        hook: "[onclick^='filterByHook']",
        tag: "[onclick^='filterByTag']",
        author: "[onclick^='filterByAuthor']",
      };

      const selector = selectors[type];
      if (!selector) {
        return;
      }

      // Get all badges of this type
      const badges = document.querySelectorAll(selector);

      badges.forEach((badge) => {
        // Check if this is the "All" badge (empty value)
        const isAllBadge = badge.getAttribute("onclick").includes("('')");

        // Check if this badge matches the selected value
        const badgeValue = badge
          .getAttribute("onclick")
          .match(/'([^']*)'/)?.[1];
        const isSelected =
          value === ""
            ? isAllBadge
            : badgeValue?.toLowerCase() === value?.toLowerCase();

        if (isSelected) {
          // Apply active/selected styling
          badge.classList.remove(
            "bg-gray-100",
            "text-gray-800",
            "hover:bg-gray-200"
          );
          badge.classList.remove(
            "dark:bg-gray-700",
            "dark:text-gray-200",
            "dark:hover:bg-gray-600"
          );
          badge.classList.add(
            "bg-indigo-100",
            "text-indigo-800",
            "border",
            "border-indigo-300"
          );
          badge.classList.add(
            "dark:bg-indigo-900",
            "dark:text-indigo-200",
            "dark:border-indigo-700"
          );
        } else if (!isAllBadge) {
          // Reset to default styling for non-All badges
          badge.classList.remove(
            "bg-indigo-100",
            "text-indigo-800",
            "border",
            "border-indigo-300"
          );
          badge.classList.remove(
            "dark:bg-indigo-900",
            "dark:text-indigo-200",
            "dark:border-indigo-700"
          );
          badge.classList.add(
            "bg-gray-100",
            "text-gray-800",
            "hover:bg-gray-200"
          );
          badge.classList.add(
            "dark:bg-gray-700",
            "dark:text-gray-200",
            "dark:hover:bg-gray-600"
          );
        }
      });
    };

    // Show plugin details modal
    Admin.showPluginDetails = async function (pluginName) {
      const modal = safeGetElement("plugin-details-modal");
      const modalName = safeGetElement("modal-plugin-name");
      const modalContent = safeGetElement("modal-plugin-content");

      if (!modal || !modalName || !modalContent) {
        console.error("Plugin details modal elements not found");
        return;
      }

      // Show loading state
      modalName.textContent = pluginName;
      modalContent.innerHTML = '<div class="text-center py-4">Loading...</div>';
      modal.classList.remove("hidden");

      try {
        const rootPath = window.ROOT_PATH || "";
        // Fetch plugin details
        const response = await fetch(
          `${rootPath}/admin/plugins/${encodeURIComponent(pluginName)}`,
          {
            credentials: "same-origin",
            headers: {
              Accept: "application/json",
            },
          }
        );

        if (!response.ok) {
          throw new Error(
            `Failed to load plugin details: ${response.statusText}`
          );
        }

        const plugin = await response.json();

        // Render plugin details
        modalContent.innerHTML = `
                      <div class="space-y-4">
                          <div>
                              <h4 class="font-medium text-gray-700 dark:text-gray-300">Description</h4>
                              <p class="mt-1">${plugin.description || "No description available"}</p>
                          </div>

                          <div class="grid grid-cols-2 gap-4">
                              <div>
                                  <h4 class="font-medium text-gray-700 dark:text-gray-300">Author</h4>
                                  <p class="mt-1">${plugin.author || "Unknown"}</p>
                              </div>
                              <div>
                                  <h4 class="font-medium text-gray-700 dark:text-gray-300">Version</h4>
                                  <p class="mt-1">${plugin.version || "0.0.0"}</p>
                              </div>
                          </div>

                          <div class="grid grid-cols-2 gap-4">
                              <div>
                                  <h4 class="font-medium text-gray-700 dark:text-gray-300">Mode</h4>
                                  <p class="mt-1">
                                      <span class="px-2 py-1 text-xs rounded-full ${
  plugin.mode === "enforce"
    ? "bg-red-100 text-red-800"
    : plugin.mode === "permissive"
      ? "bg-yellow-100 text-yellow-800"
      : "bg-gray-100 text-gray-800"
  }">
                                          ${plugin.mode}
                                      </span>
                                  </p>
                              </div>
                              <div>
                                  <h4 class="font-medium text-gray-700 dark:text-gray-300">Priority</h4>
                                  <p class="mt-1">${plugin.priority}</p>
                              </div>
                          </div>

                          <div>
                              <h4 class="font-medium text-gray-700 dark:text-gray-300">Hooks</h4>
                              <div class="mt-1 flex flex-wrap gap-1">
                                  ${(plugin.hooks || [])
    .map(
      (hook) =>
        `<span class="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">${hook}</span>`
    )
    .join("")}
                              </div>
                          </div>

                          <div>
                              <h4 class="font-medium text-gray-700 dark:text-gray-300">Tags</h4>
                              <div class="mt-1 flex flex-wrap gap-1">
                                  ${(plugin.tags || [])
    .map(
      (tag) =>
        `<span class="px-2 py-1 text-xs bg-gray-100 text-gray-700 rounded">${tag}</span>`
    )
    .join("")}
                              </div>
                          </div>

                          ${
  plugin.config &&
                            Object.keys(plugin.config).length > 0
    ? `
                              <div>
                                  <h4 class="font-medium text-gray-700 dark:text-gray-300">Configuration</h4>
                                  <pre class="mt-1 p-2 bg-gray-50 dark:bg-gray-800 rounded text-xs overflow-x-auto">${JSON.stringify(plugin.config, null, 2)}</pre>
                              </div>
                          `
    : ""
  }
                      </div>
                  `;
      } catch (error) {
        console.error("Error loading plugin details:", error);
        modalContent.innerHTML = `
                      <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
                          <strong class="font-bold">Error:</strong>
                          <span class="block sm:inline">${error.message}</span>
                      </div>
                  `;
      }
    };

    // Close plugin details modal
    Admin.closePluginDetails = function () {
      const modal = safeGetElement("plugin-details-modal");
      if (modal) {
        modal.classList.add("hidden");
      }
    };
  };

  // Initialize plugin functions if plugins panel exists
  if (isAdminUser() && safeGetElement("plugins-panel")) {
    Admin.initializePluginFunctions();
    // Populate filter dropdowns on initial load
    if (Admin.populatePluginFilters) {
      Admin.populatePluginFilters();
    }
  }

  // ===================================================================
  // MCP REGISTRY MODAL FUNCTIONS
  // ===================================================================

  // Define modal functions in global scope for MCP Registry
  Admin.showApiKeyModal = function (serverId, serverName, serverUrl) {
    const modal = safeGetElement("api-key-modal");
    if (modal) {
      safeGetElement("modal-server-id").value = serverId;
      safeGetElement("modal-server-name").textContent = serverName;
      safeGetElement("modal-custom-name").placeholder = serverName;
      modal.classList.remove("hidden");
    }
  };

  Admin.closeApiKeyModal = function () {
    const modal = safeGetElement("api-key-modal");
    if (modal) {
      modal.classList.add("hidden");
    }
    const form = safeGetElement("api-key-form");
    if (form) {
      form.reset();
    }
  };

  Admin.submitApiKeyForm = function (event) {
    event.preventDefault();
    const serverId = safeGetElement("modal-server-id").value;
    const customName = safeGetElement("modal-custom-name").value;
    const apiKey = safeGetElement("modal-api-key").value;

    // Prepare request data
    const requestData = {};
    if (customName) {
      requestData.name = customName;
    }
    if (apiKey) {
      requestData.api_key = apiKey;
    }

    const rootPath = window.ROOT_PATH || "";

    // Send registration request
    fetch(`${rootPath}/admin/mcp-registry/${serverId}/register`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + (getCookie("jwt_token") || ""),
      },
      body: JSON.stringify(requestData),
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.success) {
          Admin.closeApiKeyModal();
          // Reload the catalog
          if (window.htmx && window.htmx.ajax) {
            window.htmx.ajax("GET", `${rootPath}/admin/mcp-registry/partial`, {
              target: "#mcp-registry-content",
              swap: "innerHTML",
            });
          }
        } else {
          alert("Registration failed: " + (data.error || data.message));
        }
      })
      .catch((error) => {
        alert("Error registering server: " + error);
      });
  };

  // gRPC Services Functions

  /**
   * Toggle visibility of TLS certificate/key fields based on TLS checkbox
   */
  Admin.toggleGrpcTlsFields = function () {
    const tlsEnabled = safeGetElement("grpc-tls-enabled")?.checked || false;
    const certField = safeGetElement("grpc-tls-cert-field");
    const keyField = safeGetElement("grpc-tls-key-field");

    if (tlsEnabled) {
      certField?.classList.remove("hidden");
      keyField?.classList.remove("hidden");
    } else {
      certField?.classList.add("hidden");
      keyField?.classList.add("hidden");
    }
  };

  /**
   * View gRPC service methods in a modal or alert
   * @param {string} serviceId - The gRPC service ID
   */
  Admin.viewGrpcMethods = function (serviceId) {
    const rootPath = window.ROOT_PATH || "";

    fetch(`${rootPath}/grpc/${serviceId}/methods`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + (getCookie("jwt_token") || ""),
      },
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.methods && data.methods.length > 0) {
          let methodsList = "gRPC Methods:\n\n";
          data.methods.forEach((method) => {
            methodsList += `${method.full_name}\n`;
            methodsList += `  Input: ${method.input_type || "N/A"}\n`;
            methodsList += `  Output: ${method.output_type || "N/A"}\n`;
            if (method.client_streaming || method.server_streaming) {
              methodsList += `  Streaming: ${method.client_streaming ? "Client" : ""} ${method.server_streaming ? "Server" : ""}\n`;
            }
            methodsList += "\n";
          });
          alert(methodsList);
        } else {
          alert(
            "No methods discovered for this service. Try re-reflecting the service."
          );
        }
      })
      .catch((error) => {
        alert("Error fetching methods: " + error);
      });
  };

  // ============================================================================
  // CA Certificate Validation Functions
  // ============================================================================

  /**
   * Validate CA certificate file on upload (supports multiple files)
   * @param {Event} event - The file input change event
   */
  Admin.validateCACertFiles = async function (event) {
    const files = Array.from(event.target.files);
    const feedbackEl = safeGetElement("ca-certificate-feedback");

    if (!files.length) {
      feedbackEl.textContent = "No files selected.";
      return;
    }

    // Check file size (max 10MB for cert files)
    const maxSize = 10 * 1024 * 1024; // 10MB
    const oversizedFiles = files.filter((f) => f.size > maxSize);
    if (oversizedFiles.length > 0) {
      if (feedbackEl) {
        feedbackEl.innerHTML = `
  <div class="flex items-center text-red-600">
  <svg class="w-6 h-6 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
  <span>Certificate file(s) too large. Maximum size is 10MB per file.</span>
  </div>
  `;
        feedbackEl.className = "mt-2 text-sm";
      }
      event.target.value = "";
      return;
    }

    // Check file extensions
    const validExtensions = [".pem", ".crt", ".cer", ".cert"];
    const invalidFiles = files.filter((file) => {
      const fileName = file.name.toLowerCase();
      return !validExtensions.some((ext) => fileName.endsWith(ext));
    });

    if (invalidFiles.length > 0) {
      if (feedbackEl) {
        feedbackEl.innerHTML = `
  <div class="flex items-center text-red-600">
  <svg class="w-6 h-6 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
  <span>Invalid file type. Please upload valid certificate files (.pem, .crt, .cer, .cert)</span>
  </div>
  `;
        feedbackEl.className = "mt-2 text-sm";
      }
      event.target.value = "";
      return;
    }

    // Read and validate all files
    const certResults = [];
    for (const file of files) {
      try {
        const content = await Admin.readFileAsync(file);
        const isValid = Admin.isValidCertificate(content);
        const certInfo = isValid ? Admin.parseCertificateInfo(content) : null;

        certResults.push({
          file,
          content,
          isValid,
          certInfo,
        });
      } catch (error) {
        certResults.push({
          file,
          content: null,
          isValid: false,
          certInfo: null,
          error: error.message,
        });
      }
    }

    // Display per-file validation results
    Admin.displayCertValidationResults(certResults, feedbackEl);

    // If all valid, order and concatenate
    const allValid = certResults.every((r) => r.isValid);
    if (allValid) {
      const orderedCerts = Admin.orderCertificateChain(certResults);
      const concatenated = orderedCerts.map((r) => r.content.trim()).join("\n");

      // Store concatenated result in a hidden field
      let hiddenInput = safeGetElement("ca_certificate_concatenated");
      if (!hiddenInput) {
        hiddenInput = document.createElement("input");
        hiddenInput.type = "hidden";
        hiddenInput.id = "ca_certificate_concatenated";
        hiddenInput.name = "ca_certificate";
        event.target.form.appendChild(hiddenInput);
      }
      hiddenInput.value = concatenated;

      // Update drop zone
      Admin.updateDropZoneWithFiles(files);
    } else {
      event.target.value = "";
    }
  };

  /**
   * Helper function to read file as text asynchronously
   * @param {File} file - The file to read
   * @returns {Promise<string>} - Promise resolving to file content
   */
  Admin.readFileAsync = function (file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = (e) => Admin.resolve(e.target.result);
      reader.onerror = () => Admin.reject(new Error("Error reading file"));
      reader.readAsText(file);
    });
  };

  /**
   * Parse certificate information to determine if it's self-signed (root CA)
   * @param {string} content - PEM certificate content
   * @returns {Object} - Certificate info with isRoot flag
   */
  Admin.parseCertificateInfo = function (content) {
    // Basic heuristic: check if Subject and Issuer appear the same
    // In a real implementation, you'd parse the ASN.1 structure properly
    const subjectMatch = content.match(/Subject:([^\n]+)/i);
    const issuerMatch = content.match(/Issuer:([^\n]+)/i);

    // If we can't parse, assume it's an intermediate
    if (!subjectMatch || !issuerMatch) {
      return { isRoot: false };
    }

    const subject = subjectMatch[1].trim();
    const issuer = issuerMatch[1].trim();

    return {
      isRoot: subject === issuer,
      subject,
      issuer,
    };
  };

  /**
   * Order certificates in chain: root CA first, then intermediates, then leaf
   * @param {Array} certResults - Array of certificate result objects
   * @returns {Array} - Ordered array of certificate results
   */
  Admin.orderCertificateChain = function (certResults) {
    const roots = certResults.filter((r) => r.certInfo && r.certInfo.isRoot);
    const nonRoots = certResults.filter(
      (r) => r.certInfo && !r.certInfo.isRoot
    );

    // Simple ordering: roots first, then rest
    // In production, you'd build a proper chain by matching issuer/subject
    return [...roots, ...nonRoots];
  };

  /**
   * Display validation results for each certificate file
   * @param {Array} certResults - Array of validation result objects
   * @param {HTMLElement} feedbackEl - Element to display feedback
   */
  Admin.displayCertValidationResults = function (certResults, feedbackEl) {
    const allValid = certResults.every((r) => r.isValid);

    let html = '<div class="space-y-2">';

    // Overall status
    if (allValid) {
      html += `
  <div class="flex items-center text-green-600 font-semibold text-lg">
  <svg class="w-8 h-8 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
  <span>All certificates validated successfully!</span>
  </div>
  `;
    } else {
      html += `
  <div class="flex items-center text-red-600 font-semibold text-lg">
  <svg class="w-8 h-8 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
  <span>Some certificates failed validation</span>
  </div>
  `;
    }

    // Per-file results
    html += '<div class="mt-3 space-y-1">';
    for (const result of certResults) {
      const icon = result.isValid
        ? '<svg class="w-5 h-5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>'
        : '<svg class="w-5 h-5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>';

      const statusClass = result.isValid ? "text-gray-700" : "text-red-700";
      const typeLabel =
        result.certInfo && result.certInfo.isRoot ? " (Root CA)" : "";

      html += `
  <div class="flex items-center ${statusClass}">
  ${icon}
  <span class="ml-2">${escapeHtml(result.file.name)}${typeLabel} - ${formatFileSize(result.file.size)}</span>
  </div>
  `;
    }
    html += "</div></div>";

    feedbackEl.innerHTML = html;
    feedbackEl.className = "mt-2 text-sm";
  };

  /**
   * Validate certificate content (PEM format)
   * @param {string} content - The certificate file content
   * @returns {boolean} - True if valid certificate
   */
  Admin.isValidCertificate = function (content) {
    // Trim whitespace
    content = content.trim();

    // Check for PEM certificate markers
    const beginCertPattern = /-----BEGIN CERTIFICATE-----/;
    const endCertPattern = /-----END CERTIFICATE-----/;

    if (!beginCertPattern.test(content) || !endCertPattern.test(content)) {
      return false;
    }

    // Check for proper structure
    const certPattern =
      /-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g;
    const matches = content.match(certPattern);

    if (!matches || matches.length === 0) {
      return false;
    }

    // Validate base64 content between markers
    for (const cert of matches) {
      const base64Content = cert
        .replace(/-----BEGIN CERTIFICATE-----/, "")
        .replace(/-----END CERTIFICATE-----/, "")
        .replace(/\s/g, "");

      // Check if content is valid base64
      if (!isValidBase64(base64Content)) {
        return false;
      }

      // Basic length check (certificates are typically > 100 chars of base64)
      if (base64Content.length < 100) {
        return false;
      }
    }

    return true;
  };

  /**
   * Check if string is valid base64
   * @param {string} str - The string to validate
   * @returns {boolean} - True if valid base64
   */
  Admin.isValidBase64 = function (str) {
    if (str.length === 0) {
      return false;
    }

    // Base64 regex pattern
    const base64Pattern = /^[A-Za-z0-9+/]*={0,2}$/;
    return base64Pattern.test(str);
  };

  /**
   * Update drop zone UI with selected file info
   * @param {File} file - The selected file
   */
  Admin.updateDropZoneWithFiles = function (files) {
    const dropZone = safeGetElement("ca-certificate-upload-drop-zone");
    if (!dropZone) {
      return;
    }

    const fileListHTML = Array.from(files)
      .map(
        (file) =>
          `<div>${escapeHtml(file.name)} • ${formatFileSize(file.size)}</div>`
      )
      .join("");

    dropZone.innerHTML = `
        <div class="space-y-2">
            <svg class="mx-auto h-12 w-12 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
            <div class="text-sm text-gray-700 dark:text-gray-300">
                <span class="font-medium">Selected Certificates:</span>
            </div>
            <div class="text-xs text-gray-500 dark:text-gray-400">${fileListHTML}</div>
        </div>
    `;
  };

  /**
   * Format file size for display
   * @param {number} bytes - File size in bytes
   * @returns {string} - Formatted file size
   */
  Admin.formatFileSize = function (bytes) {
    if (bytes === 0) {
      return "0 Bytes";
    }
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + " " + sizes[i];
  };

  /**
   * Initialize drag and drop for CA cert upload
   * Called on DOMContentLoaded
   */
  Admin.initializeCACertUpload = function () {
    const dropZone = safeGetElement("ca-certificate-upload-drop-zone");
    const fileInput = safeGetElement("upload-ca-certificate");

    if (dropZone && fileInput) {
      // Click to upload
      dropZone.addEventListener("click", function (e) {
        fileInput.click();
      });

      // Drag and drop handlers
      dropZone.addEventListener("dragover", function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add(
          "border-indigo-500",
          "bg-indigo-50",
          "dark:bg-indigo-900/20"
        );
      });

      dropZone.addEventListener("dragleave", function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove(
          "border-indigo-500",
          "bg-indigo-50",
          "dark:bg-indigo-900/20"
        );
      });

      dropZone.addEventListener("drop", function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove(
          "border-indigo-500",
          "bg-indigo-50",
          "dark:bg-indigo-900/20"
        );

        const files = e.dataTransfer.files;
        if (files.length > 0) {
          fileInput.files = files;
          // Trigger the validation
          const event = new Event("change", { bubbles: true });
          fileInput.dispatchEvent(event);
        }
      });
    }
  };

  // Function to update body label based on content type selection
  Admin.updateBodyLabel = function () {
    const bodyLabel = safeGetElement("gateway-test-body-label");
    const contentType = safeGetElement("gateway-test-content-type")?.value;

    if (bodyLabel) {
      bodyLabel.innerHTML =
        contentType === "application/x-www-form-urlencoded"
          ? 'Body (JSON)<br><small class="text-gray-500">Auto-converts to form data</small>'
          : "Body (JSON)";
    }
  };

  /**
   * ====================================================================
   * REAL-TIME GATEWAY & TOOL MONITORING (SSE)
   * Handles live status updates for Gateways and Tools
   * ====================================================================
   */

  document.addEventListener("DOMContentLoaded", function () {
    Admin.initializeRealTimeMonitoring();
  });

  Admin.initializeRealTimeMonitoring = function () {
    if (!window.EventSource) {
      return;
    }

    // Connect to the admin events endpoint
    const eventSource = new EventSource(`${window.ROOT_PATH}/admin/events`);

    // --- Gateway Events ---
    // Handlers for specific states

    // eventSource.addEventListener("gateway_deactivated", (e) => Admin.handleEntityEvent("gateway", e));
    eventSource.addEventListener("gateway_activated", (e) =>
      Admin.handleEntityEvent("gateway", e)
    );
    eventSource.addEventListener("gateway_offline", (e) =>
      Admin.handleEntityEvent("gateway", e)
    );

    // --- Tool Events ---
    // Handlers for specific states

    // eventSource.addEventListener("tool_deactivated", (e) => Admin.handleEntityEvent("tool", e));
    eventSource.addEventListener("tool_activated", (e) =>
      Admin.handleEntityEvent("tool", e)
    );
    eventSource.addEventListener("tool_offline", (e) =>
      Admin.handleEntityEvent("tool", e)
    );

    eventSource.onopen = () =>
      console.log("✅ SSE Connected for Real-time Monitoring");
    eventSource.onerror = (err) =>
      console.warn("⚠️ SSE Connection issue, retrying...", err);
  };

  /**
   * Generic handler for entity events
   */
  Admin.handleEntityEvent = function (type, event) {
    try {
      const data = JSON.parse(event.data);
      // Log the specific event type for debugging
      // console.log(`Received ${type} event [${event.type}]:`, data);
      Admin.updateEntityStatus(type, data);
    } catch (err) {
      console.error(`Error processing ${type} event:`, err);
    }
  };

  /**
   * Updates the status badge and action buttons for a row
   */

  Admin.updateEntityStatus = function (type, data) {
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

      statusCell.innerHTML = Admin.generateStatusBadgeHtml(
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
      Admin.updateEntityActionButtons(actionCell, type, data.id, isEnabled);
    }
  };
  // ============================================================================
  // Structured Logging UI Functions
  // ============================================================================

  // Current log search state
  let currentLogPage = 0;
  const currentLogLimit = 50;
  // eslint-disable-next-line no-unused-vars
  let currentLogFilters = {};
  let currentPerformanceAggregationKey = "5m";

  Admin.getPerformanceAggregationConfig = function (
    rangeKey = currentPerformanceAggregationKey
  ) {
    return (
      PERFORMANCE_AGGREGATION_OPTIONS[rangeKey] ||
      PERFORMANCE_AGGREGATION_OPTIONS["5m"]
    );
  };

  Admin.getPerformanceAggregationLabel = function (
    rangeKey = currentPerformanceAggregationKey
  ) {
    return Admin.getPerformanceAggregationConfig(rangeKey).label;
  };

  Admin.getPerformanceAggregationQuery = function (
    rangeKey = currentPerformanceAggregationKey
  ) {
    return Admin.getPerformanceAggregationConfig(rangeKey).query;
  };

  Admin.syncPerformanceAggregationSelect = function () {
    const select = safeGetElement("performance-aggregation-select");
    if (select && select.value !== currentPerformanceAggregationKey) {
      select.value = currentPerformanceAggregationKey;
    }
  };

  Admin.setPerformanceAggregationVisibility = function (shouldShow) {
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

  Admin.setLogFiltersVisibility = function (shouldShow) {
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

  Admin.handlePerformanceAggregationChange = function (event) {
    const selectedKey = event?.target?.value;
    if (selectedKey && PERFORMANCE_AGGREGATION_OPTIONS[selectedKey]) {
      Admin.showPerformanceMetrics(selectedKey);
    }
  };

  /**
   * Search structured logs with filters
   */
  Admin.searchStructuredLogs = async function () {
    Admin.setPerformanceAggregationVisibility(false);
    Admin.setLogFiltersVisibility(true);
    const levelFilter = safeGetElement("log-level-filter")?.value;
    const componentFilter = safeGetElement("log-component-filter")?.value;
    const searchQuery = safeGetElement("log-search")?.value;

    // Restore default log table headers (in case we're coming from performance metrics view)
    Admin.restoreLogTableHeaders();

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
      Admin.displayLogResults(data);
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
  Admin.displayLogResults = function (data) {
    const tbody = safeGetElement("logs-tbody");
    const logCount = safeGetElement("log-count");
    const logStats = safeGetElement("log-stats");
    const prevButton = safeGetElement("prev-page");
    const nextButton = safeGetElement("next-page");

    // Ensure default headers are shown for log view
    Admin.restoreLogTableHeaders();

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
        const levelClass = Admin.getLogLevelClass(log.level);
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
            ${escapeHtml(Admin.truncateText(log.message, 80))}
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
                    ${escapeHtml(Admin.truncateText(correlationId, 12))}
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
  Admin.getLogLevelClass = function (level) {
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
   * Truncate text with ellipsis
   */
  Admin.truncateText = function (text, maxLength) {
    if (!text) {
      return "";
    }
    return text.length > maxLength
      ? text.substring(0, maxLength) + "..."
      : text;
  };

  /**
   * Show detailed log entry (future enhancement - modal)
   */
  Admin.showLogDetails = function (logId, correlationId) {
    if (correlationId) {
      Admin.showCorrelationTrace(correlationId);
    } else {
      console.log("Log details:", logId);
      showToast("Full log details view coming soon", "info");
    }
  };

  /**
   * Restore default log table headers
   */
  Admin.restoreLogTableHeaders = function () {
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
  Admin.showCorrelationTrace = async function (correlationId) {
    Admin.setPerformanceAggregationVisibility(false);
    Admin.setLogFiltersVisibility(true);
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
      Admin.displayCorrelationTrace(trace);
    } catch (error) {
      console.error("Error fetching correlation trace:", error);
      showToast("Failed to fetch correlation trace: " + error.message, "error");
    }
  };

  /**
   * Generates the HTML for the status badge (Active/Inactive/Offline)
   */
  Admin.generateStatusBadgeHtml = function (enabled, reachable, typeLabel) {
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
  Admin.updateEntityActionButtons = function (cell, type, id, isEnabled) {
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
  Admin.emergencyFixMCPSearch = function () {
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
      Admin.filterGatewaysTable(e.target.value);
    });

    console.log(
      "✅ Emergency fix applied - test by typing in MCP Servers search box"
    );
    return true;
  };

  // Manual test function
  Admin.testMCPSearchManually = function (searchTerm = "github") {
    console.log("🧪 MANUAL TEST: Testing MCP search with:", searchTerm);
    Admin.filterGatewaysTable(searchTerm);
  };

  // Debug current state function
  Admin.debugMCPSearchState = function () {
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

  // Auto-fix on page load
  setTimeout(function () {
    console.log("🔄 AUTO-FIX: Attempting to fix MCP search after page load...");
    if (Admin.emergencyFixMCPSearch) {
      Admin.emergencyFixMCPSearch();
    }
  }, 1000);

  console.log("🔧 MCP SERVERS SEARCH DEBUG FUNCTIONS LOADED!");
  console.log("💡 Use: Admin.emergencyFixMCPSearch() to fix search");
  console.log("💡 Use: Admin.testMCPSearchManually('github') to test search");
  console.log("💡 Use: Admin.debugMCPSearchState() to check current state");

  /**
   * Display correlation trace results
   */
  Admin.displayCorrelationTrace = function (trace) {
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
      const levelClass = Admin.getLogLevelClass(log.level);
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
      const severityClass = Admin.getSeverityClass(event.severity);
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
  Admin.showSecurityEvents = async function () {
    Admin.setPerformanceAggregationVisibility(false);
    Admin.setLogFiltersVisibility(false);
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
      Admin.displaySecurityEvents(events);
    } catch (error) {
      console.error("Error fetching security events:", error);
      showToast("Failed to fetch security events: " + error.message, "error");
    }
  };

  /**
   * Display security events
   */
  Admin.displaySecurityEvents = function (events) {
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
        const severityClass = Admin.getSeverityClass(event.severity);
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
                        ${escapeHtml(Admin.truncateText(event.correlation_id, 12))}
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
  Admin.getSeverityClass = function (severity) {
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
  Admin.showAuditTrail = async function () {
    Admin.setPerformanceAggregationVisibility(false);
    Admin.setLogFiltersVisibility(false);
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
      Admin.displayAuditTrail(trails);
    } catch (error) {
      console.error("Error fetching audit trails:", error);
      showToast("Failed to fetch audit trails: " + error.message, "error");
    }
  };

  /**
   * Display audit trail entries
   */
  Admin.displayAuditTrail = function (trails) {
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
          update:
            "bg-blue-200 text-blue-800 dark:bg-blue-800 dark:text-blue-200",
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
                          ${escapeHtml(Admin.truncateText(trail.correlation_id, 12))}
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
  Admin.showPerformanceMetrics = async function (rangeKey) {
    if (rangeKey && PERFORMANCE_AGGREGATION_OPTIONS[rangeKey]) {
      currentPerformanceAggregationKey = rangeKey;
    } else {
      const select = safeGetElement("performance-aggregation-select");
      if (select?.value && PERFORMANCE_AGGREGATION_OPTIONS[select.value]) {
        currentPerformanceAggregationKey = select.value;
      }
    }

    Admin.syncPerformanceAggregationSelect();
    Admin.setPerformanceAggregationVisibility(true);
    Admin.setLogFiltersVisibility(false);
    const hoursParam = encodeURIComponent(PERFORMANCE_HISTORY_HOURS.toString());
    const aggregationParam = encodeURIComponent(
      Admin.getPerformanceAggregationQuery()
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
      Admin.displayPerformanceMetrics(metrics);
    } catch (error) {
      console.error("Error fetching performance metrics:", error);
      showToast(
        "Failed to fetch performance metrics: " + error.message,
        "error"
      );
    }
  };

  /**
   * Display performance metrics
   */
  Admin.displayPerformanceMetrics = function (metrics) {
    const tbody = safeGetElement("logs-tbody");
    const thead = safeGetElement("logs-thead");
    const logCount = safeGetElement("log-count");
    const logStats = safeGetElement("log-stats");
    const aggregationLabel = Admin.getPerformanceAggregationLabel();

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
  Admin.previousLogPage = function () {
    if (currentLogPage > 0) {
      currentLogPage--;
      Admin.searchStructuredLogs();
    }
  };

  /**
   * Navigate to next log page
   */
  Admin.nextLogPage = function () {
    currentLogPage++;
    Admin.searchStructuredLogs();
  };

  // ============================================================================ //
  //                         TEAM SEARCH AND FILTER FUNCTIONS                      //
  // ============================================================================ //

  /**
   * Debounce timer for team search
   */
  let teamSearchDebounceTimer = null;

  /**
   * Current relationship filter state
   */
  let currentTeamRelationshipFilter = "all";

  /**
   * Perform server-side search for teams and update the teams list
   * @param {string} searchTerm - The search query
   */
  Admin.serverSideTeamSearch = function (searchTerm) {
    // Debounce the search to avoid excessive API calls
    if (teamSearchDebounceTimer) {
      clearTimeout(teamSearchDebounceTimer);
    }

    teamSearchDebounceTimer = setTimeout(() => {
      Admin.performTeamSearch(searchTerm);
    }, 300);
  };

  /**
   * Get current per_page value from pagination controls or use default
   */
  Admin.getTeamsPerPage = function () {
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
  Admin.performTeamSearch = async function (searchTerm) {
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
    params.set("per_page", Admin.getTeamsPerPage().toString());

    if (searchTerm && searchTerm.trim() !== "") {
      params.set("q", searchTerm.trim());
    }

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
  Admin.filterByRelationship = function (filter) {
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
    currentTeamRelationshipFilter = filter;

    // Get current search query
    const searchInput = safeGetElement("team-search");
    const searchQuery = searchInput ? searchInput.value.trim() : "";

    // Perform search with new filter
    Admin.performTeamSearch(searchQuery);
  };

  /**
   * Legacy filterTeams function - redirects to serverSideTeamSearch
   * @param {string} searchValue - The search query
   */
  Admin.filterTeams = function (searchValue) {
    Admin.serverSideTeamSearch(searchValue);
  };
})(window.Admin);
