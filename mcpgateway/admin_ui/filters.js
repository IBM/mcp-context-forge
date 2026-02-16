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

      // Get text from searchable cells (exclude Actions and S.No. columns)
      // Tools columns: Admin.Actions(0), S.No.(1), Admin.Source(2), Admin.Name(3), Admin.RequestType(4), Admin.Description(5), Admin.Annotations(6), Admin.Tags(7), Admin.Owner(8), Admin.Team(9), Admin.Status(10)
      const cells = row.querySelectorAll("td");
      const searchableColumns = [2, 3, 4, 5, 6, 7, 8, 9, 10]; // Exclude Admin.Actions(0) and S.No.(1)

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
 * Clear search functionality for different entity types
 */
export const clearSearch = function (entityType) {
  try {
    if (entityType === "catalog") {
      const searchInput = safeGetElement("catalog-search-input");
      if (searchInput) {
        searchInput.value = "";
        filterServerTable(""); // Clear the filter
      }
    } else if (entityType === "tools") {
      const searchInput = safeGetElement("tools-search-input");
      if (searchInput) {
        searchInput.value = "";
        filterToolsTable(""); // Clear the filter
      }
    } else if (entityType === "resources") {
      const searchInput = safeGetElement("resources-search-input");
      if (searchInput) {
        searchInput.value = "";
        filterResourcesTable(""); // Clear the filter
      }
    } else if (entityType === "prompts") {
      const searchInput = safeGetElement("prompts-search-input");
      if (searchInput) {
        searchInput.value = "";
        filterPromptsTable(""); // Clear the filter
      }
    } else if (entityType === "a2a-agents") {
      const searchInput = safeGetElement("a2a-agents-search-input");
      if (searchInput) {
        searchInput.value = "";
        filterA2AAgentsTable(""); // Clear the filter
      }
    } else if (entityType === "gateways") {
      const searchInput = safeGetElement("gateways-search-input");
      if (searchInput) {
        searchInput.value = "";
        filterGatewaysTable(""); // Clear the filter
      }
    } else if (entityType === "gateways") {
      const searchInput = safeGetElement("gateways-search-input");
      if (searchInput) {
        searchInput.value = "";
        filterGatewaysTable(""); // Clear the filter
      }
    }
  } catch (error) {
    console.error("Error clearing search:", error);
  }
};
