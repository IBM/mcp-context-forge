import { initPromptSelect } from "./prompts";
import { initResourceSelect } from "./resources";
import { updatePromptMapping, updateResourceMapping, updateToolMapping } from "./servers";
import { initToolSelect } from "./tools";

// Constants
export const MASKED_AUTH_VALUE = "*****";

/**
 * Tag filtering
 */
export const INVALID_TAG_VALUES = new Set(["no tags", "none", "n/a"]);

/**
 * Header validation constants
 */
export const HEADER_NAME_REGEX = /^[A-Za-z0-9-]+$/;
export const MAX_HEADER_VALUE_LENGTH = 4096;
export const MAX_NAME_LENGTH = 255;

/**
 * Performance aggregation
 */
export const PERFORMANCE_HISTORY_HOURS = 24;
export const PERFORMANCE_AGGREGATION_OPTIONS = {
  "5m": { label: "5-minute aggregation", query: "5m" },
  "24h": { label: "24-hour aggregation", query: "24h" },
};

/**
* Default per_page for teams list
*/
export const DEFAULT_TEAMS_PER_PAGE = 10;

/**
 * Clear search functionality for different entity types
 */
export const PANEL_SEARCH_CONFIG = {
  catalog: {
    tableName: "servers",
    partialPath: "servers/partial",
    targetSelector: "#servers-table",
    indicatorSelector: "#servers-loading",
    searchInputId: "servers-search-input",
    tagInputId: "servers-tag-filter",
    inactiveCheckboxId: "show-inactive-servers",
    defaultPerPage: 50,
  },
  tools: {
    tableName: "tools",
    partialPath: "tools/partial",
    targetSelector: "#tools-table",
    indicatorSelector: "#tools-loading",
    searchInputId: "tools-search-input",
    tagInputId: "tools-tag-filter",
    inactiveCheckboxId: "show-inactive-tools",
    defaultPerPage: 50,
  },
  resources: {
    tableName: "resources",
    partialPath: "resources/partial",
    targetSelector: "#resources-table",
    indicatorSelector: "#resources-loading",
    searchInputId: "resources-search-input",
    tagInputId: "resources-tag-filter",
    inactiveCheckboxId: "show-inactive-resources",
    defaultPerPage: 50,
  },
  prompts: {
    tableName: "prompts",
    partialPath: "prompts/partial",
    targetSelector: "#prompts-table",
    indicatorSelector: "#prompts-loading",
    searchInputId: "prompts-search-input",
    tagInputId: "prompts-tag-filter",
    inactiveCheckboxId: "show-inactive-prompts",
    defaultPerPage: 50,
  },
  gateways: {
    tableName: "gateways",
    partialPath: "gateways/partial",
    targetSelector: "#gateways-table",
    indicatorSelector: "#gateways-loading",
    searchInputId: "gateways-search-input",
    tagInputId: "gateways-tag-filter",
    inactiveCheckboxId: "show-inactive-gateways",
    defaultPerPage: 50,
  },
  "a2a-agents": {
    tableName: "agents",
    partialPath: "a2a/partial",
    targetSelector: "#agents-table",
    indicatorSelector: "#agents-loading",
    searchInputId: "a2a-agents-search-input",
    tagInputId: "a2a-agents-tag-filter",
    inactiveCheckboxId: "show-inactive-a2a-agents",
    defaultPerPage: 50,
  },
};

export const GLOBAL_SEARCH_ENTITY_CONFIG = {
  servers: { label: "Servers", tab: "catalog", viewFunction: "viewServer" },
  gateways: {
    label: "Gateways",
    tab: "gateways",
    viewFunction: "viewGateway",
  },
  tools: { label: "Tools", tab: "tools", viewFunction: "viewTool" },
  resources: {
    label: "Resources",
    tab: "resources",
    viewFunction: "viewResource",
  },
  prompts: { label: "Prompts", tab: "prompts", viewFunction: "viewPrompt" },
  agents: {
    label: "A2A Agents",
    tab: "a2a-agents",
    viewFunction: "viewA2AAgent",
  },
  teams: { label: "Teams", tab: "teams", viewFunction: "showTeamEditModal" },
  users: { label: "Users", tab: "users", viewFunction: "showUserEditModal" },
  roots: { label: "Roots", tab: "roots", viewFunction: "viewRoot" },
};

// Configuration objects for each search type
export const SEARCH_CONFIGS = {
  toolsAdd: {
    type: "tools",
    context: "add",
    containerId: "associatedTools",
    inputName: "associatedTools",
    apiEndpoint: "/admin/tools/search",
    partialEndpoint: "/admin/tools/partial",
    dataKey: "tools",
    updateMapping: updateToolMapping,
    initSelector: initToolSelect,
    color: "indigo",
    itemClass: "tool-item",
    checkboxClass: "tool-checkbox",
    noResultsId: "noToolsMessage",
    searchQueryId: "searchQueryTools",
    pillsId: "selectedToolsPills",
    warningId: "selectedToolsWarning",
    selectAllBtnId: "selectAllToolsBtn",
    clearAllBtnId: "clearAllToolsBtn",
    viewPublicCheckboxId: "add-server-view-public",
    dataNameAttr: "data-tool-name",
    mappingKey: "toolMapping",
    logPrefix: "Tool Search",
    getDisplayName: (tool) =>
      tool.display_name || tool.custom_name || tool.name || tool.id,
  },
  promptsAdd: {
    type: "prompts",
    context: "add",
    containerId: "associatedPrompts",
    inputName: "associatedPrompts",
    apiEndpoint: "/admin/prompts/search",
    partialEndpoint: "/admin/prompts/partial",
    dataKey: "prompts",
    updateMapping: updatePromptMapping,
    initSelector: initPromptSelect,
    color: "purple",
    itemClass: "prompt-item",
    checkboxClass: "prompt-checkbox",
    noResultsId: "noPromptsMessage",
    searchQueryId: "searchPromptsQuery",
    pillsId: "selectedPromptsPills",
    warningId: "selectedPromptsWarning",
    selectAllBtnId: "selectAllPromptsBtn",
    clearAllBtnId: "clearAllPromptsBtn",
    viewPublicCheckboxId: "add-server-view-public",
    dataNameAttr: "data-prompt-name",
    mappingKey: "promptMapping",
    logPrefix: "Prompt Search",
    getDisplayName: (prompt) =>
      prompt.displayName ||
      prompt.display_name ||
      prompt.originalName ||
      prompt.original_name ||
      prompt.name ||
      prompt.id,
  },
  resourcesAdd: {
    type: "resources",
    context: "add",
    containerId: "associatedResources",
    inputName: "associatedResources",
    apiEndpoint: "/admin/resources/search",
    partialEndpoint: "/admin/resources/partial",
    dataKey: "resources",
    updateMapping: updateResourceMapping,
    initSelector: initResourceSelect,
    color: "purple",
    itemClass: "resource-item",
    checkboxClass: "resource-checkbox",
    noResultsId: "noResourcesMessage",
    searchQueryId: "searchResourcesQuery",
    pillsId: "selectedResourcesPills",
    warningId: "selectedResourcesWarning",
    selectAllBtnId: "selectAllResourcesBtn",
    clearAllBtnId: "clearAllResourcesBtn",
    viewPublicCheckboxId: "add-server-view-public",
    dataNameAttr: "data-resource-name",
    mappingKey: "resourceMapping",
    logPrefix: "Resource Search",
    getDisplayName: (resource) => resource.name || resource.id,
  },
  toolsEdit: {
    type: "tools",
    context: "edit",
    containerId: "edit-server-tools",
    inputName: "associatedTools",
    apiEndpoint: "/admin/tools/search",
    partialEndpoint: "/admin/tools/partial",
    dataKey: "tools",
    dataAttribute: "data-server-tools",
    updateMapping: updateToolMapping,
    initSelector: initToolSelect,
    color: "indigo",
    itemClass: "tool-item",
    checkboxClass: "tool-checkbox",
    noResultsId: "noEditToolsMessage",
    searchQueryId: "searchQueryEditTools",
    pillsId: "selectedEditToolsPills",
    warningId: "selectedEditToolsWarning",
    selectAllBtnId: "selectAllEditToolsBtn",
    clearAllBtnId: "clearAllEditToolsBtn",
    viewPublicCheckboxId: "edit-server-view-public",
    dataNameAttr: "data-tool-name",
    mappingKey: "toolMapping",
    logPrefix: "Edit Tool Search",
    getDisplayName: (tool) =>
      tool.display_name || tool.custom_name || tool.name || tool.id,
  },
  promptsEdit: {
    type: "prompts",
    context: "edit",
    containerId: "edit-server-prompts",
    inputName: "associatedPrompts",
    apiEndpoint: "/admin/prompts/search",
    partialEndpoint: "/admin/prompts/partial",
    dataKey: "prompts",
    dataAttribute: "data-server-prompts",
    updateMapping: updatePromptMapping,
    initSelector: initPromptSelect,
    color: "indigo",
    itemClass: "prompt-item",
    checkboxClass: "prompt-checkbox",
    noResultsId: "noEditPromptsMessage",
    searchQueryId: "searchQueryEditPrompts",
    pillsId: "selectedEditPromptsPills",
    warningId: "selectedEditPromptsWarning",
    selectAllBtnId: "selectAllEditPromptsBtn",
    clearAllBtnId: "clearAllEditPromptsBtn",
    viewPublicCheckboxId: "edit-server-view-public",
    dataNameAttr: "data-prompt-name",
    mappingKey: "promptMapping",
    logPrefix: "Edit Prompt Search",
    getDisplayName: (prompt) =>
      prompt.displayName ||
      prompt.display_name ||
      prompt.originalName ||
      prompt.original_name ||
      prompt.name ||
      prompt.id,
  },
  resourcesEdit: {
    type: "resources",
    context: "edit",
    containerId: "edit-server-resources",
    inputName: "associatedResources",
    apiEndpoint: "/admin/resources/search",
    partialEndpoint: "/admin/resources/partial",
    dataKey: "resources",
    dataAttribute: "data-server-resources",
    updateMapping: updateResourceMapping,
    initSelector: initResourceSelect,
    color: "indigo",
    itemClass: "resource-item",
    checkboxClass: "resource-checkbox",
    noResultsId: "noEditResourcesMessage",
    searchQueryId: "searchQueryEditResources",
    pillsId: "selectedEditResourcesPills",
    warningId: "selectedEditResourcesWarning",
    selectAllBtnId: "selectAllEditResourcesBtn",
    clearAllBtnId: "clearAllEditResourcesBtn",
    viewPublicCheckboxId: "edit-server-view-public",
    dataNameAttr: "data-resource-name",
    mappingKey: "resourceMapping",
    logPrefix: "Edit Resource Search",
    getDisplayName: (resource) => resource.name || resource.id,
  },
};


export const TABLE_TO_ENTITY_TYPE = {
  "servers-table": "catalog",
  "tools-table": "tools",
  "resources-table": "resources",
  "prompts-table": "prompts",
  "gateways-table": "gateways",
  "agents-table": "a2a-agents",
};

/**
 * Fragment names differ from entity type names for some entities.
 * e.g. the "servers" toggle navigates to the #catalog tab.
 */
export const TOGGLE_FRAGMENT_MAP = { servers: "catalog" };
