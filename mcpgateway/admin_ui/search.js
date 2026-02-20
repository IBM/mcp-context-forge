import {
  GLOBAL_SEARCH_ENTITY_CONFIG,
  PANEL_SEARCH_CONFIG,
} from "./constants.js";
import {
  filterA2AAgentsTable,
  filterGatewaysTable,
  filterPromptsTable,
  filterResourcesTable,
  filterServerTable,
  filterToolsTable,
} from "./filters.js";
import { escapeHtml, safeReplaceState } from "./security.js";
import { getUiHiddenSections, showTab } from "./tabs.js";
import { fetchWithAuth, performTokenSearch } from "./tokens.js";
import { getCurrentTeamId, isAdminUser } from "./utils.js";

const panelSearchReloadTimers = {};
let globalSearchRequestId = 0;

export const getPanelSearchConfig = function (entityType) {
  return PANEL_SEARCH_CONFIG[entityType] || null;
};

export const getPanelSearchStateFromUrl = function (tableName) {
  const params = new URLSearchParams(window.location.search);
  const prefix = `${tableName}_`;
  return {
    query: (params.get(prefix + "q") || "").trim(),
    tags: (params.get(prefix + "tags") || "").trim(),
  };
};

export const updatePanelSearchStateInUrl = function (tableName, query, tags) {
  const currentUrl = new URL(window.location.href);
  const params = new URLSearchParams(currentUrl.searchParams);
  const prefix = `${tableName}_`;
  const normalizedQuery = (query || "").trim();
  const normalizedTags = (tags || "").trim();

  if (normalizedQuery) {
    params.set(prefix + "q", normalizedQuery);
  } else {
    params.delete(prefix + "q");
  }

  if (normalizedTags) {
    params.set(prefix + "tags", normalizedTags);
  } else {
    params.delete(prefix + "tags");
  }

  // Search/filter changes always reset to first page.
  params.set(prefix + "page", "1");

  const newUrl =
    currentUrl.pathname +
    (params.toString() ? `?${params.toString()}` : "") +
    currentUrl.hash;
  safeReplaceState({}, "", newUrl);
};

export const getPanelPerPage = function (panelConfig) {
  const selector = document.querySelector(
    `#${panelConfig.tableName}-pagination-controls select`
  );
  if (!selector) {
    return panelConfig.defaultPerPage;
  }
  const parsed = parseInt(selector.value, 10);
  return Number.isNaN(parsed) ? panelConfig.defaultPerPage : parsed;
};

export const loadSearchablePanel = function (entityType) {
  const panelConfig = getPanelSearchConfig(entityType);
  if (!panelConfig) {
    return;
  }

  const searchInput = document.getElementById(panelConfig.searchInputId);
  const tagInput = document.getElementById(panelConfig.tagInputId);
  const query = (searchInput?.value || "").trim();
  const tags = (tagInput?.value || "").trim();

  // Persist search state in namespaced URL params for pagination/shareability.
  updatePanelSearchStateInUrl(panelConfig.tableName, query, tags);

  const includeInactive = Boolean(
    document.getElementById(panelConfig.inactiveCheckboxId)?.checked
  );
  const params = new URLSearchParams();
  params.set("page", "1");
  params.set("per_page", String(getPanelPerPage(panelConfig)));
  params.set("include_inactive", includeInactive ? "true" : "false");
  if (query) {
    params.set("q", query);
  }
  if (tags) {
    params.set("tags", tags);
  }
  const currentTeamId = getCurrentTeamId();
  if (currentTeamId) {
    params.set("team_id", currentTeamId);
  }

  const url = `${window.ROOT_PATH}/admin/${panelConfig.partialPath}?${params.toString()}`;
  if (window.htmx && window.htmx.ajax) {
    window.htmx.ajax("GET", url, {
      target: panelConfig.targetSelector,
      swap: "outerHTML",
      indicator: panelConfig.indicatorSelector,
    });
  }
};

export const queueSearchablePanelReload = function (entityType, delayMs = 250) {
  if (panelSearchReloadTimers[entityType]) {
    clearTimeout(panelSearchReloadTimers[entityType]);
  }
  panelSearchReloadTimers[entityType] = setTimeout(() => {
    loadSearchablePanel(entityType);
  }, delayMs);
};

export const clearSearch = function (entityType) {
  try {
    const panelConfig = getPanelSearchConfig(entityType);
    if (panelConfig) {
      const searchInput = document.getElementById(panelConfig.searchInputId);
      if (searchInput) {
        searchInput.value = "";
      }
      const tagInput = document.getElementById(panelConfig.tagInputId);
      if (tagInput) {
        tagInput.value = "";
      }
      // Keep rows visible even if HTMX reload is delayed/missed.
      if (entityType === "catalog" && typeof filterServerTable === "function") {
        filterServerTable("");
      } else if (
        entityType === "tools" &&
        typeof filterToolsTable === "function"
      ) {
        filterToolsTable("");
      } else if (
        entityType === "resources" &&
        typeof filterResourcesTable === "function"
      ) {
        filterResourcesTable("");
      } else if (
        entityType === "prompts" &&
        typeof filterPromptsTable === "function"
      ) {
        filterPromptsTable("");
      } else if (
        entityType === "gateways" &&
        typeof filterGatewaysTable === "function"
      ) {
        filterGatewaysTable("");
      } else if (
        entityType === "a2a-agents" &&
        typeof filterA2AAgentsTable === "function"
      ) {
        filterA2AAgentsTable("");
      }
      loadSearchablePanel(entityType);
      return;
    }

    if (entityType === "tokens") {
      const searchInput = document.getElementById("tokens-search-input");
      if (searchInput) {
        searchInput.value = "";
        performTokenSearch("");
      }
    }
  } catch (error) {
    console.error("Error clearing search:", error);
  }
};

export const renderGlobalSearchMessage = function (message) {
  const container = document.getElementById("global-search-results");
  if (!container) {
    return;
  }
  container.innerHTML = `<div class="p-4 text-sm text-gray-500 dark:text-gray-400">${escapeHtml(message)}</div>`;
};

export const renderGlobalSearchResults = function (payload) {
  const container = document.getElementById("global-search-results");
  if (!container) {
    return;
  }

  const groups = Array.isArray(payload?.groups) ? payload.groups : [];
  const hiddenSections = getUiHiddenSections();
  const visibleGroups = groups.filter(
    (group) =>
      Array.isArray(group.items) &&
      group.items.length > 0 &&
      !hiddenSections.has(group.entity_type)
  );

  if (visibleGroups.length === 0) {
    renderGlobalSearchMessage("No matching results.");
    return;
  }

  let html = "";
  visibleGroups.forEach((group) => {
    const entityType = group.entity_type;
    const config = GLOBAL_SEARCH_ENTITY_CONFIG[entityType] || {
      label: entityType,
    };
    html += `<div class="border-b border-gray-200 dark:border-gray-700">`;
    html += `<div class="px-4 py-2 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">${escapeHtml(config.label)} (${group.items.length})</div>`;

    group.items.forEach((item) => {
      const itemId = item.id || item.email || item.slug || "";
      const name =
        item.display_name ||
        item.original_name ||
        item.name ||
        item.full_name ||
        item.email ||
        item.slug ||
        item.id ||
        "Unnamed";
      const summary =
        item.description ||
        item.email ||
        item.slug ||
        item.url ||
        item.endpoint_url ||
        item.original_name ||
        item.id ||
        "";
      html += `
                <button
                  type="button"
                  class="global-search-result-item w-full text-left px-4 py-2 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                  data-entity="${escapeHtml(entityType)}"
                  data-id="${escapeHtml(itemId)}"
                  onclick="Admin.navigateToGlobalSearchResult(this)"
                >
                  <div class="text-sm font-medium text-gray-900 dark:text-gray-100">${escapeHtml(name)}</div>
                  <div class="text-xs text-gray-500 dark:text-gray-400 truncate">${escapeHtml(summary)}</div>
                </button>
            `;
    });
    html += "</div>";
  });

  container.innerHTML = html;
};

export const runGlobalSearch = async function (query) {
  const normalizedQuery = (query || "").trim();
  const requestId = ++globalSearchRequestId;

  if (!normalizedQuery) {
    renderGlobalSearchMessage("Start typing to search all entities.");
    return;
  }

  renderGlobalSearchMessage("Searching...");
  const params = new URLSearchParams();
  params.set("q", normalizedQuery);
  params.set("limit_per_type", "8");
  const searchableEntityTypes = [
    "servers",
    "gateways",
    "tools",
    "resources",
    "prompts",
    "agents",
    "teams",
    "users",
  ];
  const visibleEntityTypes = searchableEntityTypes.filter((entityType) => {
    if (entityType === "users" && !isAdminUser()) {
      return false;
    }
    return !getUiHiddenSections().has(entityType);
  });
  if (visibleEntityTypes.length === 0) {
    renderGlobalSearchMessage("No searchable sections are visible.");
    return;
  }
  params.set("entity_types", visibleEntityTypes.join(","));

  const currentTeamId = getCurrentTeamId();
  if (currentTeamId) {
    params.set("team_id", currentTeamId);
  }

  try {
    const response = await fetchWithAuth(
      `${window.ROOT_PATH}/admin/search?${params.toString()}`
    );
    if (!response.ok) {
      throw new Error(
        `Search request failed (${response.status} ${response.statusText})`
      );
    }

    const payload = await response.json();
    // Ignore out-of-order responses.
    if (requestId !== globalSearchRequestId) {
      return;
    }
    renderGlobalSearchResults(payload);
  } catch (error) {
    if (requestId !== globalSearchRequestId) {
      return;
    }
    console.error("Error running global search:", error);
    renderGlobalSearchMessage("Search failed. Please try again.");
  }
};

export const openGlobalSearchModal = function () {
  const modal = document.getElementById("global-search-modal");
  const input = document.getElementById("global-search-input");
  if (!modal || !input) {
    return;
  }

  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  input.focus();
  if (input.value.trim()) {
    runGlobalSearch(input.value);
  } else {
    renderGlobalSearchMessage("Start typing to search all entities.");
  }
};

export const closeGlobalSearchModal = function () {
  const modal = document.getElementById("global-search-modal");
  if (!modal) {
    return;
  }

  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
};

export const navigateToGlobalSearchResult = function (button) {
  if (!button) {
    return;
  }

  const entityType = button.dataset.entity;
  const entityId = button.dataset.id;
  if (!entityType || !entityId) {
    return;
  }

  const config = GLOBAL_SEARCH_ENTITY_CONFIG[entityType];
  closeGlobalSearchModal();
  if (!config) {
    return;
  }

  showTab(config.tab);
  const viewFunction = window[config.viewFunction];
  if (typeof viewFunction === "function") {
    setTimeout(() => {
      viewFunction(entityId);
    }, 120);
  }
};
