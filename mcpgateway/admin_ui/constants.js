// Constants
export const MASKED_AUTH_VALUE = "*****";

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
    searchInputId: "catalog-search-input",
    tagInputId: "catalog-tag-filter",
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
    viewFunction: "viewAgent",
  },
  teams: { label: "Teams", tab: "teams", viewFunction: "showTeamEditModal" },
  users: { label: "Users", tab: "users", viewFunction: "showUserEditModal" },
};