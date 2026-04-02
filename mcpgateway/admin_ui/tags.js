// ===============================================
// TAG FILTERING FUNCTIONALITY
// ===============================================

import { INVALID_TAG_VALUES } from "./constants.js";
import { getPanelSearchConfig, loadSearchablePanel, queueSearchablePanelReload, updatePanelSearchStateInUrl } from "./search.js";
import { safeGetElement } from "./utils.js";

/**
 * Extract all unique tags from entities in a given entity type
 * @param {string} entityType - The entity type (tools, resources, prompts, servers, gateways)
 * @returns {Array<string>} - Array of unique tags
 */
const isValidTag = (t) =>
  t && t.length >= 2 && t.length <= 50 && !INVALID_TAG_VALUES.has(t.toLowerCase());

export const extractAvailableTags = function (entityType) {
  const tags = new Set();

  if (entityType === "catalog") {
    document
      .querySelectorAll("#servers-table-body [data-tag]")
      .forEach((el) => {
        const t = el.getAttribute("data-tag").trim();
        if (isValidTag(t)) tags.add(t);
      });
    return Array.from(tags).sort();
  }

  const tableSelector = `#${entityType}-panel tbody tr:not(.inactive-row)`;
  const rows = document.querySelectorAll(tableSelector);

  // Find the Tags column index by examining the table header
  const tableHeaderSelector = `#${entityType}-panel thead tr th`;
  const headerCells = document.querySelectorAll(tableHeaderSelector);
  let tagsColumnIndex = -1;

  headerCells.forEach((header, index) => {
    const headerText = header.textContent.trim().toLowerCase();
    if (headerText === "tags") {
      tagsColumnIndex = index;
    }
  });

  if (tagsColumnIndex === -1) {
    console.log(`[DEBUG] Could not find Tags column for ${entityType}`);
    return [];
  }

  rows.forEach((row, index) => {
    const cells = row.querySelectorAll("td");

    if (tagsColumnIndex < cells.length) {
      const tagsCell = cells[tagsColumnIndex];
      tagsCell.querySelectorAll("[data-tag]").forEach((el) => {
        const t = el.getAttribute("data-tag").trim();
        if (isValidTag(t)) tags.add(t);
      });
    }
  });

  return Array.from(tags).sort();
};

/**
 * Update the available tags display for an entity type
 * @param {string} entityType - The entity type
 */
export const updateAvailableTags = function (entityType) {
  const availableTagsContainer = safeGetElement(`${entityType}-available-tags`);
  if (!availableTagsContainer) {
    return;
  }

  const tags = extractAvailableTags(entityType);
  availableTagsContainer.innerHTML = "";

  if (tags.length === 0) {
    availableTagsContainer.innerHTML =
      '<span class="text-sm text-gray-500">No tags found</span>';
    return;
  }

  tags.forEach((tag) => {
    const tagButton = document.createElement("button");
    tagButton.type = "button";
    tagButton.className =
      "inline-flex items-center px-2 py-1 text-xs font-medium rounded-full text-blue-700 bg-blue-100 hover:bg-blue-200 cursor-pointer";
    tagButton.textContent = tag;
    tagButton.title = `Click to filter by "${tag}"`;
    tagButton.onclick = () => addTagToFilter(entityType, tag);
    availableTagsContainer.appendChild(tagButton);
  });
};

/**
 * Filter entities by tags
 * @param {string} entityType - The entity type (tools, resources, prompts, servers, gateways)
 * @param {string} tagsInput - Comma-separated string of tags to filter by
 */
export const filterEntitiesByTags = function (entityType, tagsInput) {
  const filterTags = tagsInput
    .split(",")
    .map((tag) => tag.trim().toLowerCase())
    .filter((tag) => tag);

  const tableSelector = `#${entityType}-panel tbody tr`;
  const rows = document.querySelectorAll(tableSelector);

  let visibleCount = 0;

  rows.forEach((row) => {
    if (filterTags.length === 0) {
      // Show all rows when no filter is applied
      row.style.display = "";
      visibleCount++;
      return;
    }

    // Extract tags from this row using data-tag attributes
    const rowTags = new Set();
    row.querySelectorAll("[data-tag]").forEach((el) => {
      const t = el.getAttribute("data-tag").trim().toLowerCase();
      if (t) rowTags.add(t);
    });

    // Check if any of the filter tags match any of the row tags (OR logic)
    const hasMatchingTag = filterTags.some((filterTag) =>
      Array.from(rowTags).some(
        (rowTag) => rowTag.includes(filterTag) || filterTag.includes(rowTag)
      )
    );

    if (hasMatchingTag) {
      row.style.display = "";
      visibleCount++;
    } else {
      row.style.display = "none";
    }
  });

  // Update empty state message
  updateFilterEmptyState(entityType, visibleCount, filterTags.length > 0);
};

/**
 * Add a tag to the filter input
 * @param {string} entityType - The entity type
 * @param {string} tag - The tag to add
 */
export const addTagToFilter = function (entityType, tag) {
  const panelConfig = getPanelSearchConfig(entityType);
  const tagInputId = panelConfig
    ? panelConfig.tagInputId
    : `${entityType}-tag-filter`;
  const filterInput = document.getElementById(tagInputId);
  if (!filterInput) {
    return;
  }

  const currentTags = filterInput.value
    .split(",")
    .map((t) => t.trim())
    .filter((t) => t);
  if (!currentTags.includes(tag)) {
    currentTags.push(tag);
    filterInput.value = currentTags.join(", ");
    if (panelConfig) {
      const searchInput = document.getElementById(
        panelConfig.searchInputId,
      );
      updatePanelSearchStateInUrl(
        panelConfig.tableName,
        searchInput?.value || "",
        filterInput.value,
      );
      queueSearchablePanelReload(entityType, 0);
    } else {
      filterEntitiesByTags(entityType, filterInput.value);
    }
  }
};

/**
 * Update empty state message when filtering
 * @param {string} entityType - The entity type
 * @param {number} visibleCount - Number of visible entities
 * @param {boolean} isFiltering - Whether filtering is active
 */
export const updateFilterEmptyState = function (
  entityType,
  visibleCount,
  isFiltering
) {
  const tableContainer = document.querySelector(
    `#${entityType}-panel .overflow-x-auto`
  );
  if (!tableContainer) {
    return;
  }

  let emptyMessage = tableContainer.querySelector(".tag-filter-empty-message");

  if (visibleCount === 0 && isFiltering) {
    if (!emptyMessage) {
      emptyMessage = document.createElement("div");
      emptyMessage.className =
        "tag-filter-empty-message text-center py-8 text-gray-500";
      emptyMessage.innerHTML = `
              <div class="flex flex-col items-center">
                  <svg class="w-12 h-12 text-gray-400 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                  </svg>
                  <h3 class="text-lg font-medium text-gray-900 dark:text-gray-100 mb-2">No matching ${entityType}</h3>
                  <p class="text-gray-500 dark:text-gray-400">No ${entityType} found with the specified tags. Try adjusting your filter or <button data-action="clear-tag-filter" class="text-indigo-600 hover:text-indigo-500 underline">clear the filter</button>.</p>
              </div>
          `;
      const clearBtn = emptyMessage.querySelector(
        '[data-action="clear-tag-filter"]',
      );
      if (clearBtn) {
        clearBtn.addEventListener("click", () =>
          clearTagFilter(entityType),
        );
      }
      tableContainer.appendChild(emptyMessage);
    }
    emptyMessage.style.display = "block";
  } else if (emptyMessage) {
    emptyMessage.style.display = "none";
  }
};

/**
 * Clear the tag filter for an entity type
 * @param {string} entityType - The entity type
 */
export const clearTagFilter = function (entityType) {
  const panelConfig = getPanelSearchConfig(entityType);
  const tagInputId = panelConfig
    ? panelConfig.tagInputId
    : `${entityType}-tag-filter`;
  const filterInput = document.getElementById(tagInputId);
  if (filterInput) {
    filterInput.value = "";
    // Apply immediate local reset for responsive UX and test compatibility.
    filterEntitiesByTags(entityType, "");
    if (panelConfig) {
      loadSearchablePanel(entityType);
    }
  }
};

/**
 * Initialize tag filtering for all entity types on page load
 */
export const initializeTagFiltering = function () {
  const entityTypes = [
    "catalog",
    "tools",
    "resources",
    "prompts",
    "servers",
    "gateways",
    "a2a-agents",
  ];

  entityTypes.forEach((entityType) => {
    // Update available tags on page load
    updateAvailableTags(entityType);

    // Set up event listeners for tab switching to refresh tags
    const tabButton = safeGetElement(`tab-${entityType}`);
    if (tabButton) {
      tabButton.addEventListener("click", () => {
        // Delay to ensure tab content is visible
        setTimeout(() => updateAvailableTags(entityType), 100);
      });
    }
  });
};
