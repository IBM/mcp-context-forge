/**
 * ====================================================================
 * SECURITY MODULE - XSS PROTECTION AND INPUT VALIDATION
 * ====================================================================
 */

import { HEADER_NAME_REGEX, MAX_HEADER_VALUE_LENGTH, MAX_NAME_LENGTH } from "./constants.js";
import { AppState } from "./appState.js";

// ===================================================================
// SECURITY: HTML-escape function to prevent XSS attacks
// ===================================================================

export function escapeHtml(unsafe) {
  if (unsafe === null || unsafe === undefined) {
    return "";
  }
  return String(unsafe)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;")
    .replace(/`/g, "&#x60;")
    .replace(/\//g, "&#x2F;"); // Extra protection against script injection
}

/**
 * Extract a human-readable error message from an API error response.
 * Handles both string errors and Pydantic validation error arrays.
 * @param {Object} error - The parsed JSON error response
 * @param {string} fallback - Fallback message if no detail found
 * @returns {string} Human-readable error message
 */
export function extractApiError(error, fallback = "An error occurred") {
  if (!error || (!error.detail && !error.message)) {
    return fallback;
  }
  if (error.message) {
    return error.message;
  }
  if (typeof error.detail === "string") {
    return error.detail;
  }
  if (Array.isArray(error.detail)) {
    // Pydantic validation errors - extract messages
    return error.detail.map((err) => err.msg || JSON.stringify(err)).join("; ");
  }
  return fallback;
}

/**
 * Safely parse an error response, handling both JSON and plain text bodies.
 * @param {Response} response - The fetch Response object
 * @param {string} fallback - Fallback message if parsing fails
 * @returns {Promise<string>} Human-readable error message
 */
export async function parseErrorResponse(
  response,
  fallback = "An error occurred"
) {
  try {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const error = await response.json();
      return extractApiError(error, fallback);
    }
    // Non-JSON response - try to get text
    const text = await response.text();
    if (!text) {
      return fallback;
    }
    // Detect HTML responses (proxy error pages, auth redirects) and show generic message
    if (
      text.trimStart().startsWith("<!") ||
      text.trimStart().toLowerCase().startsWith("<html")
    ) {
      return `${fallback} (HTTP ${response.status}). The server returned an HTML error page.`;
    }
    // Truncate long non-HTML text responses
    const maxLength = 200;
    if (text.length > maxLength) {
      return text.substring(0, maxLength) + "...";
    }
    return text;
  } catch {
    return fallback;
  }
}

/**
 * Safely parse a JSON response with validation.
 * Prevents "JSON.parse: unexpected character" errors when server/proxy returns HTML.
 * @param {Response} response - The fetch Response object
 * @param {string} fallbackError - Fallback error message if response is not JSON
 * @returns {Promise<Object>} Parsed JSON result
 * @throws {Error} If response is not OK or not JSON
 */
export async function safeParseJsonResponse(
  response,
  fallbackError = "Request failed",
) {
  const contentType = response.headers.get("content-type") || "";

  // Handle non-OK responses first
  if (!response.ok) {
    const errorMsg = await parseErrorResponse(
      response,
      `${fallbackError} (HTTP ${response.status})`,
    );
    throw new Error(errorMsg);
  }

  // Validate content-type before parsing
  if (!contentType.includes("application/json")) {
    throw new Error(
      "The server returned an unexpected response. " +
        "Please verify you are authenticated and the server is responding correctly.",
    );
  }

  return await response.json();
}

/**
 * Validate a passthrough header name and value
 * @param {string} name - Header name to validate
 * @param {string} value - Header value to validate
 * @returns {Object} Validation result with 'valid' boolean and 'error' message
 */
export function validatePassthroughHeader(name, value) {
  // Validate header name
  if (!HEADER_NAME_REGEX.test(name)) {
    return {
      valid: false,
      error: `Header name "${name}" contains invalid characters. Only letters, numbers, and hyphens are allowed.`,
    };
  }

  // Check for dangerous characters in value
  if (value.includes("\n") || value.includes("\r")) {
    return {
      valid: false,
      error: "Header value cannot contain newline characters",
    };
  }

  // Check value length
  if (value.length > MAX_HEADER_VALUE_LENGTH) {
    return {
      valid: false,
      error: `Header value too long (${value.length} chars, max ${MAX_HEADER_VALUE_LENGTH})`,
    };
  }

  // Check for control characters (except tab)
  const hasControlChars = Array.from(value).some((char) => {
    const code = char.charCodeAt(0);
    return code < 32 && code !== 9; // Allow tab (9) but not other control chars
  });

  if (hasControlChars) {
    return {
      valid: false,
      error: "Header value contains invalid control characters",
    };
  }

  return { valid: true };
}

/**
 * SECURITY: Validate input names to prevent XSS and ensure clean data
 */
export function validateInputName(name, type = "input") {
  if (!name || typeof name !== "string") {
    return { valid: false, error: `${type} is required` };
  }

  // Remove any HTML tags
  const cleaned = name.replace(/<[^>]*>/g, "");

  // Check for dangerous patterns
  const dangerousPatterns = [
    /<script/i,
    /javascript:/i,
    /on\w+\s*=/i,
    /data:text\/html/i,
    /vbscript:/i,
  ];

  for (const pattern of dangerousPatterns) {
    if (pattern.test(name)) {
      return {
        valid: false,
        error: `${type} contains invalid characters`,
      };
    }
  }

  // Length validation
  if (cleaned.length < 1) {
    return { valid: false, error: `${type} cannot be empty` };
  }

  if (cleaned.length > MAX_NAME_LENGTH) {
    return {
      valid: false,
      error: `${type} must be ${MAX_NAME_LENGTH} characters or less`,
    };
  }

  // For prompt names, be more restrictive
  if (type === "prompt") {
    // Only allow alphanumeric, underscore, hyphen, and spaces
    const validPattern = /^[a-zA-Z0-9_\s-]+$/;
    if (!validPattern.test(cleaned)) {
      return {
        valid: false,
        error:
          "Prompt name can only contain letters, numbers, spaces, underscores, and hyphens",
      };
    }
  }

  return { valid: true, value: cleaned };
}

/**
 * SECURITY: Validate URL inputs
 */
export function validateUrl(url, label = "") {
  if (!url || typeof url !== "string") {
    return { valid: false, error: `${label || "URL"} is required` };
  }

  try {
    const urlObj = new URL(url);
    const allowedProtocols = ["http:", "https:"];

    if (!allowedProtocols.includes(urlObj.protocol)) {
      return {
        valid: false,
        error: "Only HTTP and HTTPS URLs are allowed",
      };
    }

    return { valid: true, value: url };
  } catch (error) {
    return { valid: false, error: "Invalid URL format" };
  }
}

/**
 * SECURITY: Validate JSON input
 */
export function validateJson(jsonString, fieldName = "JSON") {
  if (!jsonString || !jsonString.trim()) {
    return { valid: true, value: {} }; // Empty is OK, defaults to empty object
  }

  try {
    const parsed = JSON.parse(jsonString);
    return { valid: true, value: parsed };
  } catch (error) {
    return {
      valid: false,
      error: `Invalid ${fieldName} format: ${error.message}`,
    };
  }
}

/**
 * SECURITY: Safely set innerHTML ONLY for trusted backend content
 * For user-generated content, use textContent instead
 */
export function safeSetInnerHTML(element, htmlContent, isTrusted = false) {
  if (!isTrusted) {
    console.error("Attempted to set innerHTML with untrusted content");
    element.textContent = htmlContent; // Fallback to safe text
    return;
  }
  element.innerHTML = htmlContent;
}

/**
 * Helper to escape HTML for safe rendering
 */
export const escapeHtmlChat = function (text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
};

// ===================================================================
// RESTRICTED CONTEXT SAFETY (sandboxed iframes)
// ===================================================================

/**
 * One-time debug log when running in a restricted context
 * (e.g. sandboxed iframes where storage/history APIs are unavailable).
 */
export function logRestrictedContext(e) {
  if (!AppState.isRestrictedContextLogged()) {
    AppState.setRestrictedContextLogged(true);
    console.debug(
      "Running in restricted context — storage/history APIs unavailable:",
      e.message,
    );
  }
}

/**
 * Safe wrapper for history.replaceState — silently skips in restricted contexts.
 */
export function safeReplaceState(data, title, url) {
  try {
    window.history.replaceState(data, title, url);
  } catch (e) {
    logRestrictedContext(e);
  }
}
