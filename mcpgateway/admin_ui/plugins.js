import { safeGetElement } from "./utils.js";

// Populate hook, tag, and author filters on page load
export const populatePluginFilters = function () {
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
export const filterPlugins = function () {
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
  updateBadgeHighlighting("hook", selectedHook);
  updateBadgeHighlighting("tag", selectedTag);
  updateBadgeHighlighting("author", selectedAuthor);

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
export const filterByHook = function (hook) {
  const hookFilter = safeGetElement("plugin-hook-filter");
  if (hookFilter) {
    hookFilter.value = hook;
    filterPlugins();
    hookFilter.scrollIntoView({ behavior: "smooth", block: "nearest" });

    // Update visual highlighting
    updateBadgeHighlighting("hook", hook);
  }
};

// Filter by tag when clicking on tag
export const filterByTag = function (tag) {
  const tagFilter = safeGetElement("plugin-tag-filter");
  if (tagFilter) {
    tagFilter.value = tag;
    filterPlugins();
    tagFilter.scrollIntoView({ behavior: "smooth", block: "nearest" });

    // Update visual highlighting
    updateBadgeHighlighting("tag", tag);
  }
};

// Filter by author when clicking on author
export const filterByAuthor = function (author) {
  const authorFilter = safeGetElement("plugin-author-filter");
  if (authorFilter) {
    // Convert to lowercase to match data-author attribute
    authorFilter.value = author.toLowerCase();
    filterPlugins();
    authorFilter.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
    });

    // Update visual highlighting
    updateBadgeHighlighting("author", author);
  }
};

// Helper function to update badge highlighting
const updateBadgeHighlighting = function (type, value) {
  // Define selectors for each type
  const selectors = {
    hook: "[onclick^='Admin.filterByHook']",
    tag: "[onclick^='Admin.filterByTag']",
    author: "[onclick^='Admin.filterByAuthor']",
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
export const showPluginDetails = async function (pluginName) {
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
  plugin.config && Object.keys(plugin.config).length > 0
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
export const closePluginDetails = function () {
  const modal = safeGetElement("plugin-details-modal");
  if (modal) {
    modal.classList.add("hidden");
  }
};
