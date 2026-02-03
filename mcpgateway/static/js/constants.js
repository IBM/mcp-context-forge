/* global marked, DOMPurify */

// Constants
export const MASKED_AUTH_VALUE = "*****";

/**
 * Header validation constants
 */
export const HEADER_NAME_REGEX = /^[A-Za-z0-9-]+$/;
export const MAX_HEADER_VALUE_LENGTH = 4096;

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