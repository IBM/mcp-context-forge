// ===============================================
// TAG FILTERING FUNCTIONALITY
// ===============================================

import { safeGetElement } from "./utils";

/**
* Extract all unique tags from entities in a given entity type
* @param {string} entityType - The entity type (tools, resources, prompts, servers, gateways)
* @returns {Array<string>} - Array of unique tags
*/
export const extractAvailableTags = function (entityType) {
  const tags = new Set();
  const tableSelector = `#${entityType}-panel tbody tr:not(.inactive-row)`;
  const rows = document.querySelectorAll(tableSelector);
  
  console.log(
    `[DEBUG] extractAvailableTags for ${entityType}: Found ${rows.length} rows`,
  );
  
  // Find the Tags column index by examining the table header
  const tableHeaderSelector = `#${entityType}-panel thead tr th`;
  const headerCells = document.querySelectorAll(tableHeaderSelector);
  let tagsColumnIndex = -1;
  
  headerCells.forEach((header, index) => {
    const headerText = header.textContent.trim().toLowerCase();
    if (headerText === "tags") {
      tagsColumnIndex = index;
      console.log(
        `[DEBUG] Found Tags column at index ${index} for ${entityType}`,
      );
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
      
      // Look for tag badges ONLY within the Tags column
      const tagElements = tagsCell.querySelectorAll(`
          span.inline-flex.items-center.px-2.py-0\\.5.rounded.text-xs.font-medium.bg-blue-100.text-blue-800,
          span.inline-block.bg-blue-100.text-blue-800.text-xs.px-2.py-1.rounded-full
      `);
        
      console.log(
        `[DEBUG] Row ${index}: Found ${tagElements.length} tag elements in Tags column`,
      );
      
      tagElements.forEach((tagEl) => {
        const tagText = tagEl.textContent.trim();
        console.log(
          `[DEBUG] Row ${index}: Tag element text: "${tagText}"`,
        );
        
        // Basic validation for tag content
        if (
          tagText &&
          tagText !== "No tags" &&
          tagText !== "None" &&
          tagText !== "N/A" &&
          tagText.length >= 2 &&
          tagText.length <= 50
        ) {
          tags.add(tagText);
          console.log(
            `[DEBUG] Row ${index}: Added tag: "${tagText}"`,
          );
        } else {
          console.log(
            `[DEBUG] Row ${index}: Filtered out: "${tagText}"`,
          );
        }
      });
    }
  });
    
  const result = Array.from(tags).sort();
  console.log(
    `[DEBUG] extractAvailableTags for ${entityType}: Final result:`,
    result,
  );
  return result;
}

/**
* Update the available tags display for an entity type
* @param {string} entityType - The entity type
*/
export const updateAvailableTags = function (entityType) {
  const availableTagsContainer = safeGetElement(
    `${entityType}-available-tags`,
  );
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
}

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
    
    // Extract tags from this row using specific tag selectors (not status badges)
    const rowTags = new Set();
    
    const tagElements = row.querySelectorAll(`
          /* Gateways */
          span.inline-block.bg-blue-100.text-blue-800.text-xs.px-2.py-1.rounded-full,
          /* A2A Agents */
          span.inline-flex.items-center.px-2.py-1.rounded.text-xs.bg-gray-100.text-gray-700,
          /* Prompts & Resources */
          span.inline-flex.items-center.px-2.py-0\\.5.rounded.text-xs.font-medium.bg-blue-100.text-blue-800,
          /* Gray tags for A2A agent metadata */
          span.inline-flex.items-center.px-2\\.5.py-0\\.5.rounded-full.text-xs.font-medium.bg-gray-100.text-gray-700
      `);
      
      tagElements.forEach((tagEl) => {
        const tagText = tagEl.textContent.trim().toLowerCase();
        // Filter out any remaining non-tag content
        if (
          tagText &&
          tagText !== "no tags" &&
          tagText !== "none" &&
          tagText !== "active" &&
          tagText !== "inactive" &&
          tagText !== "online" &&
          tagText !== "offline"
        ) {
          rowTags.add(tagText);
        }
      });
      
      // Check if any of the filter tags match any of the row tags (OR logic)
      const hasMatchingTag = filterTags.some((filterTag) =>
        Array.from(rowTags).some(
        (rowTag) =>
          rowTag.includes(filterTag) || filterTag.includes(rowTag),
      ),
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
}

/**
* Add a tag to the filter input
* @param {string} entityType - The entity type
* @param {string} tag - The tag to add
*/
export const addTagToFilter = function (entityType, tag) {
  const filterInput = safeGetElement(`${entityType}-tag-filter`);
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
    filterEntitiesByTags(entityType, filterInput.value);
  }
}

/**
* Update empty state message when filtering
* @param {string} entityType - The entity type
* @param {number} visibleCount - Number of visible entities
* @param {boolean} isFiltering - Whether filtering is active
*/
export const updateFilterEmptyState = function (entityType, visibleCount, isFiltering) {
  const tableContainer = document.querySelector(
    `#${entityType}-panel .overflow-x-auto`,
  );
  if (!tableContainer) {
    return;
  }
  
  let emptyMessage = tableContainer.querySelector(
    ".tag-filter-empty-message",
  );
  
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
                  <p class="text-gray-500 dark:text-gray-400">No ${entityType} found with the specified tags. Try adjusting your filter or <button onclick="Admin.clearTagFilter('${entityType}')" class="text-indigo-600 hover:text-indigo-500 underline">clear the filter</button>.</p>
              </div>
          `;
      tableContainer.appendChild(emptyMessage);
    }
    emptyMessage.style.display = "block";
  } else if (emptyMessage) {
    emptyMessage.style.display = "none";
  }
}

/**
* Clear the tag filter for an entity type
* @param {string} entityType - The entity type
*/
export const clearTagFilter = function (entityType) {
  const filterInput = safeGetElement(`${entityType}-tag-filter`);
  if (filterInput) {
    filterInput.value = "";
    filterEntitiesByTags(entityType, "");
  }
}

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
}