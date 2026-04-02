import { PANEL_SEARCH_CONFIG } from "./constants.js";
import { getSelectedGatewayIds } from "./gateways.js";
import { safeGetElement } from "./utils.js";

// ===================================================================
// SEARCH & FILTERING FUNCTIONS
// ===================================================================

/**
 * Filter server table rows based on search text
 */
export const filterServerTable = function (searchText) {
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
          const cellText = cells[index].textContent.replace(/\s+/g, " ").trim();
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
export const filterToolsTable = function (searchText) {
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

      // Get text from searchable cells (exclude Actions, S.No., and Tool ID columns)
      // Tools columns: Actions(0), S.No.(1), ToolID(2), Source(3), Name(4), RequestType(5), Description(6), Annotations(7), Tags(8), Owner(9), Team(10), Status(11)
      const cells = row.querySelectorAll("td");
      const searchableColumns = [3, 4, 5, 6, 7, 8, 9, 10, 11]; // Exclude Actions(0), S.No.(1), ToolID(2)

      searchableColumns.forEach((index) => {
        if (cells[index]) {
          // Clean the text content and make it searchable
          const cellText = cells[index].textContent.replace(/\s+/g, " ").trim();
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
export const filterResourcesTable = function (searchText) {
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
export const filterPromptsTable = function (searchText) {
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
export const filterA2AAgentsTable = function (searchText) {
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

      // Get text from searchable cells (exclude Actions, S.No., and Agent ID columns)
      // A2A Agents columns: Actions(0), S.No.(1), AgentID(2), Name(3), Description(4), Endpoint(5), Tags(6), Type(7), Status(8), Reachability(9), Owner(10), Team(11), Visibility(12)
      const cells = row.querySelectorAll("td");
      const searchableColumns = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]; // Exclude Actions(0), S.No.(1)

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
export const filterGatewaysTable = function (searchText) {
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

/**
 * Toggle "View Public" for server selectors.
 * When checked, removes team_id from HTMX URLs so public items are included.
 * When unchecked, re-adds team_id to filter to team-only items.
 *
 * @param {string} checkboxId - ID of the View Public checkbox
 * @param {string[]} containerIds - IDs of the HTMX selector containers to update
 * @param {string} teamId - The current team_id value
 */
export const toggleViewPublic = function (checkboxId, containerIds, teamId) {
  const checkbox = document.getElementById(checkboxId);
  if (!checkbox || !teamId) return;

  checkbox.onchange = function () {
    const includePublic = this.checked;

    // Capture current gateway selection so we can preserve it in reloaded URLs
    const selectedGatewayIds =
      typeof getSelectedGatewayIds === "function"
        ? getSelectedGatewayIds()
        : [];
    const gatewayIdParam =
      selectedGatewayIds.length > 0 ? selectedGatewayIds.join(",") : "";

    containerIds.forEach((containerId) => {
      const container = document.getElementById(containerId);
      if (!container) return;

      let url = container.getAttribute("hx-get");
      if (!url) return;

      if (includePublic) {
        // Keep team_id to maintain team scope, add include_public to also show public items
        if (!url.includes("team_id=")) {
          url += `&team_id=${encodeURIComponent(teamId)}`;
        }
        url = url.replace(/&include_public=[^&]*/, "");
        url += "&include_public=true";
      } else {
        // Remove include_public param and ensure team_id is set
        url = url.replace(/&include_public=[^&]*/, "");
        if (!url.includes("team_id=")) {
          url += `&team_id=${encodeURIComponent(teamId)}`;
        }
      }

      // Preserve active gateway filter so toggling View Public
      // does not drop the user's gateway selection
      url = url.replace(/&gateway_id=[^&]*/, "");
      if (gatewayIdParam) {
        url += `&gateway_id=${encodeURIComponent(gatewayIdParam)}`;
      }

      container.setAttribute("hx-get", url);
      // Re-process HTMX attributes and trigger re-fetch
      window.htmx.process(container);
      window.htmx.trigger(container, "load");
    });
  };
};

/**
 * Update visible filter-status text for each table panel.
 * Shows "Filters active" when any filter (search, tags, inactive) is active.
 */
export const updateFilterStatus = function () {
  Object.values(PANEL_SEARCH_CONFIG).forEach((config) => {
    const statusEl = document.getElementById(
      config.tableName + "-filter-status"
    );
    if (!statusEl) return;

    const params = new URLSearchParams(window.location.search);
    const prefix = config.tableName + "_";
    const hasQuery = Boolean(params.get(prefix + "q"));
    const hasTags = Boolean(params.get(prefix + "tags"));
    const hasInactive = params.get(prefix + "inactive") === "true";

    statusEl.textContent =
      hasQuery || hasTags || hasInactive ? "Filters active" : "";
  });
};
