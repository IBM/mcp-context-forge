import { AppState } from "./appState.js";
import {
  GLOBAL_SEARCH_ENTITY_CONFIG,
  PANEL_SEARCH_CONFIG,
  SEARCH_CONFIGS,
} from "./constants.js";
import { getSelectedGatewayIds } from "./gateways.js";
import { escapeHtml, safeReplaceState } from "./security.js";
import {
  getEditSelections,
} from "./servers.js";
import { getUiHiddenSections, showTab } from "./tabs.js";
import { fetchWithAuth, performTokenSearch } from "./tokens.js";
import { getCurrentTeamId, isAdminUser, safeGetElement } from "./utils.js";

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
      // Clear URL search params to ensure clean state
      updatePanelSearchStateInUrl(panelConfig.tableName, "", "");

      // Set up listener for HTMX afterSwap to apply client-side filter on new content
      const handleAfterSwap = (event) => {
        const target = event.detail.target;
        if (
          target &&
          target.id === panelConfig.targetSelector.replace("#", "")
        ) {
          document.body.removeEventListener("htmx:afterSwap", handleAfterSwap);
        }
      };

      document.body.addEventListener("htmx:afterSwap", handleAfterSwap);

      // Trigger HTMX reload
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
                  data-action="navigate-search-result"
                >
                  <div class="text-sm font-medium text-gray-900 dark:text-gray-100">${escapeHtml(name)}</div>
                  <div class="text-xs text-gray-500 dark:text-gray-400 truncate">${escapeHtml(summary)}</div>
                </button>
            `;
    });
    html += "</div>";
  });

  container.innerHTML = html;

  // Attach click listeners (inline onclick stripped by innerHTML sanitizer)
  container
    .querySelectorAll('[data-action="navigate-search-result"]')
    .forEach((btn) => {
      btn.addEventListener("click", () => navigateToGlobalSearchResult(btn));
    });
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
    "roots",
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

/**
 * Ensure a "no results" message element exists in the DOM for a search container.
 * If the element already exists, returns { msg, span }. Otherwise creates it
 * dynamically and inserts it right after the container so the feature works
 * regardless of template-caching state.
 *
 * @param {string} containerId  - The id of the items container (e.g. "associatedTools")
 * @param {string} msgId        - The id for the <p> message element (e.g. "noToolsMessage")
 * @param {string} spanId       - The id for the inner <span> that shows the query text
 * @param {string} entityLabel  - Human-readable label (e.g. "tool", "MCP server")
 * @returns {{ msg: HTMLElement|null, span: HTMLElement|null }}
 */
export const ensureNoResultsElement = function (
  containerId,
  msgId,
  spanId,
  entityLabel
) {
  let msg = document.getElementById(msgId);
  let span = document.getElementById(spanId);
  if (msg) {
    // Element already in the DOM – just return references
    if (!span) {
      span = msg.querySelector("span");
    }
    return { msg, span };
  }
  // Create the message element dynamically
  const container = document.getElementById(containerId);
  if (!container) {
    return { msg: null, span: null };
  }
  msg = document.createElement("p");
  msg.id = msgId;
  msg.className = "text-gray-700 dark:text-gray-300 mt-2";
  msg.style.display = "none";
  span = document.createElement("span");
  span.id = spanId;
  msg.appendChild(
    document.createTextNode(`No ${entityLabel} found containing \u201C`)
  );
  msg.appendChild(span);
  msg.appendChild(document.createTextNode("\u201D"));
  // Insert right after the container
  container.parentNode.insertBefore(msg, container.nextSibling);
  return { msg, span };
};

/**
 * Generic server-side search for tools/prompts/resources
 * @param {Object} config - Search configuration
 * @param {string} searchTerm - Search query
 */
export const serverSideSearch = async function (config, searchTerm) {
  const container = safeGetElement(config.containerId);
  const { msg: noResultsMessage, span: searchQuerySpan } =
    ensureNoResultsElement(
      config.containerId,
      config.noResultsId,
      config.searchQueryId,
      config.type
    );

  if (!container) {
    console.error(`${config.containerId} container not found`);
    return;
  }

  // Ensure container is visible
  container.style.display = "";

  // Get selected gateway IDs
  const selectedGatewayIds = getSelectedGatewayIds
    ? getSelectedGatewayIds()
    : [];
  const gatewayIdParam =
    selectedGatewayIds.length > 0 ? selectedGatewayIds.join(",") : "";

  // Flush current DOM state into persistent selection store
  const selections = getEditSelections(config.containerId);
  container
    .querySelectorAll(`input[name="${config.inputName}"]`)
    .forEach((cb) => {
      const value = String(cb.value);
      if (cb.checked) {
        selections.add(value);
      } else {
        selections.delete(value);
      }
    });

  // Capture currently checked items for backward compat
  const currentChecked =
    config.context === "edit"
      ? Array.from(
        container.querySelectorAll('input[type="checkbox"]:checked')
      ).map((cb) => cb.value)
      : [];

  // Show loading state
  container.innerHTML = `
    <div class="text-center py-4">
      <svg class="animate-spin h-5 w-5 text-${config.color}-600 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
      </svg>
      <p class="mt-2 text-sm text-gray-500">Searching ${config.type}...</p>
    </div>
  `;

  if (searchTerm.trim() === "") {
    // Reload default list
    try {
      let url = gatewayIdParam
        ? `${window.ROOT_PATH}${config.partialEndpoint}?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
        : `${window.ROOT_PATH}${config.partialEndpoint}?page=1&per_page=50&render=selector`;

      const viewPublicCb = document.getElementById(config.viewPublicCheckboxId);
      const urlTeamId = getCurrentTeamId();
      if (urlTeamId) {
        url += `&team_id=${encodeURIComponent(urlTeamId)}`;
      }
      if (viewPublicCb && viewPublicCb.checked) {
        url += "&include_public=true";
      }

      console.log(`[${config.logPrefix}] Loading defaults with URL: ${url}`);

      const response = await fetch(url);
      if (response.ok) {
        const html = await response.text();
        container.innerHTML = html;

        // Restore data attribute for edit context
        if (config.context === "edit" && config.dataAttribute) {
          const dataAttr = container.getAttribute(config.dataAttribute);
          if (dataAttr) {
            container.setAttribute(config.dataAttribute, dataAttr);
          }
        }

        if (noResultsMessage) {
          noResultsMessage.style.display = "none";
        }

        config.updateMapping(container);

        // Restore checked state
        try {
          const persistedIds = getEditSelections(config.containerId);

          if (config.context === "edit") {
            currentChecked.forEach((id) => persistedIds.add(String(id)));

            const dataAttr = container.getAttribute(config.dataAttribute);
            const serverIds = new Set();
            if (dataAttr) {
              const serverData = JSON.parse(dataAttr);
              if (Array.isArray(serverData)) {
                serverData.forEach((item) => serverIds.add(String(item)));
              }
            }

            if (persistedIds.size > 0 || serverIds.size > 0) {
              const checkboxes = container.querySelectorAll(
                `input[name="${config.inputName}"]`
              );
              checkboxes.forEach((cb) => {
                const itemId = String(cb.value);
                const itemName =
                  cb.getAttribute(config.dataNameAttr) ||
                  (window.Admin[config.mappingKey] &&
                    window.Admin[config.mappingKey][itemId]);

                if (
                  persistedIds.has(itemId) ||
                  (itemName && serverIds.has(String(itemName))) ||
                  serverIds.has(itemId)
                ) {
                  cb.checked = true;
                  persistedIds.add(itemId);
                }
              });

              const firstCb = container.querySelector('input[type="checkbox"]');
              if (firstCb) {
                firstCb.dispatchEvent(new Event("change", { bubbles: true }));
              }
            }
          } else {
            if (persistedIds.size > 0) {
              const checkboxes = container.querySelectorAll(
                `input[name="${config.inputName}"]`
              );
              checkboxes.forEach((cb) => {
                if (persistedIds.has(String(cb.value))) {
                  cb.checked = true;
                }
              });
              const firstCb = container.querySelector('input[type="checkbox"]');
              if (firstCb) {
                firstCb.dispatchEvent(new Event("change", { bubbles: true }));
              }
            }
          }
        } catch (e) {
          console.error(`Error restoring ${config.type} checked state:`, e);
        }

        config.initSelector(
          config.containerId,
          config.pillsId,
          config.warningId,
          6,
          config.selectAllBtnId,
          config.clearAllBtnId
        );
      } else {
        container.innerHTML = `<div class="text-center py-4 text-red-600">Failed to load ${config.type}</div>`;
      }
    } catch (error) {
      console.error(`Error loading ${config.type}:`, error);
      container.innerHTML = `<div class="text-center py-4 text-red-600">Error loading ${config.type}</div>`;
    }
    return;
  }

  // Perform search
  try {
    const selectedTeamId = getCurrentTeamId();
    const params = new URLSearchParams();
    params.set("q", searchTerm);
    params.set("limit", "100");
    if (gatewayIdParam) {
      params.set("gateway_id", gatewayIdParam);
    }

    const viewPublicCb = document.getElementById(config.viewPublicCheckboxId);
    if (selectedTeamId) {
      params.set("team_id", selectedTeamId);
    }
    if (viewPublicCb && viewPublicCb.checked) {
      params.set("include_public", "true");
    }

    const searchUrl = `${window.ROOT_PATH}${config.apiEndpoint}?${params.toString()}`;
    console.log(`[${config.logPrefix}] Searching with URL: ${searchUrl}`);

    const response = await fetch(searchUrl);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();

    if (data[config.dataKey] && data[config.dataKey].length > 0) {
      let searchResultsHtml = "";
      data[config.dataKey].forEach((item) => {
        const displayName = config.getDisplayName(item);
        searchResultsHtml += `
          <label
            class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 cursor-pointer hover:bg-${config.color}-50 dark:hover:bg-${config.color}-900 rounded-md p-1 ${config.itemClass}"
            data-${config.type.slice(0, -1)}-id="${escapeHtml(item.id)}"
          >
            <input
              type="checkbox"
              name="${config.inputName}"
              value="${escapeHtml(item.id)}"
              ${config.dataNameAttr}="${escapeHtml(displayName)}"
              class="${config.checkboxClass} form-checkbox h-5 w-5 text-${config.color}-600 dark:bg-gray-800 dark:border-gray-600"
            />
            <span class="select-none">${escapeHtml(displayName)}</span>
          </label>
        `;
      });

      container.innerHTML = searchResultsHtml;
      config.updateMapping(container);

      // Restore checked state
      try {
        const persistedIds = getEditSelections(config.containerId);

        if (config.context === "edit") {
          const dataAttr = container.getAttribute(config.dataAttribute);
          const serverIds = new Set();
          if (dataAttr) {
            const serverData = JSON.parse(dataAttr);
            if (Array.isArray(serverData)) {
              serverData.forEach((item) => serverIds.add(String(item)));
            }
          }

          if (persistedIds.size > 0 || serverIds.size > 0) {
            const checkboxes = container.querySelectorAll(
              `input[name="${config.inputName}"]`
            );
            checkboxes.forEach((cb) => {
              const itemId = String(cb.value);
              const itemName =
                cb.getAttribute(config.dataNameAttr) ||
                (window.Admin[config.mappingKey] &&
                  window.Admin[config.mappingKey][itemId]);

              if (
                persistedIds.has(itemId) ||
                (itemName && serverIds.has(String(itemName))) ||
                serverIds.has(itemId)
              ) {
                cb.checked = true;
                persistedIds.add(itemId);
              }
            });

            const firstCb = container.querySelector('input[type="checkbox"]');
            if (firstCb) {
              firstCb.dispatchEvent(new Event("change", { bubbles: true }));
            }
          }
        } else {
          if (persistedIds.size > 0) {
            const checkboxes = container.querySelectorAll(
              `input[name="${config.inputName}"]`
            );
            checkboxes.forEach((cb) => {
              if (persistedIds.has(String(cb.value))) {
                cb.checked = true;
              }
            });
            const firstCb = container.querySelector('input[type="checkbox"]');
            if (firstCb) {
              firstCb.dispatchEvent(new Event("change", { bubbles: true }));
            }
          }
        }
      } catch (e) {
        console.error(`Error restoring ${config.type} checked state:`, e);
      }

      config.initSelector(
        config.containerId,
        config.pillsId,
        config.warningId,
        6,
        config.selectAllBtnId,
        config.clearAllBtnId
      );

      if (noResultsMessage) {
        noResultsMessage.style.display = "none";
      }
    } else {
      container.innerHTML = "";
      container.style.display = "none";
      if (noResultsMessage) {
        if (searchQuerySpan) {
          searchQuerySpan.textContent = searchTerm;
        }
        noResultsMessage.style.display = "block";
      }
    }
  } catch (error) {
    console.error(`Error searching ${config.type}:`, error);
    container.innerHTML = `<div class="text-center py-4 text-red-600">Error searching ${config.type}</div>`;
    if (noResultsMessage) {
      noResultsMessage.style.display = "none";
    }
  }
};

/**
 * Perform server-side search for tools and update the tool list
 */
export const serverSideToolSearch = async function (searchTerm) {
  return serverSideSearch(SEARCH_CONFIGS.toolsAdd, searchTerm);
};

/**
 * Perform server-side search for prompts and update the prompt list
 */
export const serverSidePromptSearch = async function (searchTerm) {
  return serverSideSearch(SEARCH_CONFIGS.promptsAdd, searchTerm);
};

/**
 * Perform server-side search for resources and update the resources list
 */
export const serverSideResourceSearch = async function (searchTerm) {
  return serverSideSearch(SEARCH_CONFIGS.resourcesAdd, searchTerm);
};

/**
 * Perform server-side search for tools in the edit-server selector and update the list
 */
export const serverSideEditToolSearch = async function (searchTerm) {
  return serverSideSearch(SEARCH_CONFIGS.toolsEdit, searchTerm);
};

/**
 * Perform server-side search for prompts in the edit-server selector and update the list
 */
export const serverSideEditPromptsSearch = async function (searchTerm) {
  return serverSideSearch(SEARCH_CONFIGS.promptsEdit, searchTerm);
};

/**
 * Perform server-side search for resources in the edit-server selector and update the list
 */
export const serverSideEditResourcesSearch = async function (searchTerm) {
  return serverSideSearch(SEARCH_CONFIGS.resourcesEdit, searchTerm);
};

export const captureNonMemberSelections = function (teamId) {
  const container = document.getElementById(
    `team-non-members-container-${teamId}`
  );
  if (!container) return;
  if (!AppState.nonMemberSelectionsCache[teamId]) {
    AppState.nonMemberSelectionsCache[teamId] = {};
  }
  container.querySelectorAll(".user-item").forEach((item) => {
    const email = item.getAttribute("data-user-email");
    if (!email) return;
    const cb = item.querySelector('input[name="associatedUsers"]');
    const roleSelect = item.querySelector(".role-select");
    if (cb && cb.checked && !cb.getAttribute("data-auto-check")) {
      AppState.nonMemberSelectionsCache[teamId][email] = roleSelect
        ? roleSelect.value
        : "member";
    } else if (cb && !cb.checked && !cb.getAttribute("data-auto-check")) {
      delete AppState.nonMemberSelectionsCache[teamId][email];
    }
  });
}

export const restoreNonMemberSelections = function (teamId) {
  const container = document.getElementById(
    `team-non-members-container-${teamId}`
  );
  if (!container || !AppState.nonMemberSelectionsCache[teamId]) return;
  const cache = AppState.nonMemberSelectionsCache[teamId];
  const visibleEmails = new Set();
  container.querySelectorAll(".user-item").forEach((item) => {
    const email = item.getAttribute("data-user-email");
    if (!email) return;
    visibleEmails.add(email);
    if (cache[email] !== undefined) {
      const cb = item.querySelector('input[name="associatedUsers"]');
      const roleSelect = item.querySelector(".role-select");
      if (cb) cb.checked = true;
      if (roleSelect) roleSelect.value = cache[email];
    }
  });
  container.querySelectorAll(".cached-selection").forEach((el) => el.remove());
  for (const [email, role] of Object.entries(cache)) {
    if (!visibleEmails.has(email)) {
      const wrapper = document.createElement("div");
      wrapper.className = "cached-selection hidden";
      const cbHidden = document.createElement("input");
      cbHidden.type = "checkbox";
      cbHidden.name = "associatedUsers";
      cbHidden.value = email;
      cbHidden.checked = true;
      cbHidden.className = "hidden";
      const roleHidden = document.createElement("input");
      roleHidden.type = "hidden";
      roleHidden.name = "role_" + encodeURIComponent(email);
      roleHidden.value = role;
      wrapper.appendChild(cbHidden);
      wrapper.appendChild(roleHidden);
      container.appendChild(wrapper);
    }
  }
}

export const captureMemberOverrides = function (teamId) {
  const container = document.getElementById(`team-members-container-${teamId}`);
  if (!container) return;
  if (!AppState.memberOverridesCache[teamId]) {
    AppState.memberOverridesCache[teamId] = {};
  }
  container.querySelectorAll(".user-item").forEach((item) => {
    const email = item.getAttribute("data-user-email");
    if (!email) return;
    const cb = item.querySelector('input[name="associatedUsers"]');
    const roleSelect = item.querySelector(".role-select");
    if (cb && cb.getAttribute("data-auto-check") === "true") {
      if (!cb.checked || (roleSelect && roleSelect.value)) {
        AppState.memberOverridesCache[teamId][email] = {
          checked: cb.checked,
          role: roleSelect ? roleSelect.value : "member",
        };
      }
    }
  });
}

export const restoreMemberOverrides = function (teamId) {
  const container = document.getElementById(`team-members-container-${teamId}`);
  if (!container || !AppState.memberOverridesCache[teamId]) return;
  const cache = AppState.memberOverridesCache[teamId];
  container.querySelectorAll(".user-item").forEach((item) => {
    const email = item.getAttribute("data-user-email");
    if (!email || !cache[email]) return;
    const cb = item.querySelector('input[name="associatedUsers"]');
    const roleSelect = item.querySelector(".role-select");
    if (cb) cb.checked = cache[email].checked;
    if (roleSelect) roleSelect.value = cache[email].role;
  });
}

export const debouncedMemberSearch = function (teamId, searchTerm, delay = 300) {
  if (AppState.memberSearchTimers[teamId]) {
    clearTimeout(AppState.memberSearchTimers[teamId]);
  }
  AppState.memberSearchTimers[teamId] = setTimeout(() => {
    serverSideMemberSearch(teamId, searchTerm);
  }, delay);
}

export const debouncedNonMemberSearch = function (teamId, searchTerm, delay = 300) {
  if (AppState.nonMemberSearchTimers[teamId]) {
    clearTimeout(AppState.nonMemberSearchTimers[teamId]);
  }
  AppState.nonMemberSearchTimers[teamId] = setTimeout(() => {
    serverSideNonMemberSearch(teamId, searchTerm);
  }, delay);
}

// Search current team members via server-side filtering
export const serverSideMemberSearch = async function (teamId, searchTerm) {
  const container = document.getElementById(`team-members-container-${teamId}`);
  if (!container) {
    return;
  }
  captureMemberOverrides(teamId);
  const perPage =
    container.dataset.perPage || container.getAttribute("data-per-page") || 50;
  try {
    const searchParam =
      searchTerm && searchTerm.trim() !== ""
        ? `&search=${encodeURIComponent(searchTerm.trim())}`
        : "";
    const response = await fetchWithAuth(
      `${window.ROOT_PATH}/admin/teams/${teamId}/members/partial?page=1&per_page=${perPage}${searchParam}`
    );
    if (response.ok) {
      container.innerHTML = await response.text();
      if (typeof htmx !== "undefined") {
        window.htmx.process(container);
      }
      restoreMemberOverrides(teamId);
    }
  } catch (error) {
    console.error("Error searching members:", error);
    container.innerHTML =
      '<div class="text-center py-4 text-red-600">Error searching members</div>';
  }
}

// Search non-members (users not in team) via server-side filtering
export const serverSideNonMemberSearch = async function (teamId, searchTerm) {
  const container = document.getElementById(
    `team-non-members-container-${teamId}`
  );
  if (!container) {
    return;
  }

  captureNonMemberSelections(teamId);

  // Require at least 2 characters for non-member search
  if (!searchTerm || searchTerm.trim().length < 2) {
    container.innerHTML =
      '<div class="text-center py-4 text-gray-500 dark:text-gray-400">Type at least 2 characters to search for users.</div>';
    restoreNonMemberSelections(teamId);
    return;
  }

  try {
    const response = await fetchWithAuth(
      `${window.ROOT_PATH}/admin/teams/${teamId}/non-members/partial?page=1&per_page=50&search=${encodeURIComponent(searchTerm.trim())}`
    );
    if (response.ok) {
      container.innerHTML = await response.text();
      if (typeof htmx !== "undefined") {
        window.htmx.process(container);
      }
      restoreNonMemberSelections(teamId);
    }
  } catch (error) {
    console.error("Error searching non-members:", error);
    container.innerHTML =
      '<div class="text-center py-4 text-red-600">Error searching users</div>';
  }
}
