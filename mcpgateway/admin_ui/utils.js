// ===================================================================
// UTILITY FUNCTIONS
// ===================================================================

// ===================================================================
// MEMOIZATION UTILITY - Generic pattern for initialization functions
// ===================================================================

/**
 * Creates a memoized version of an initialization function with debouncing.
 * Returns an object with the memoized function and a reset function.
 *
 * @param {Function} fn - The initialization function to memoize
 * @param {number} debounceMs - Debounce delay in milliseconds (default: 300)
 * @param {string} name - Name for logging purposes
 * @returns {Object} Object with { init, debouncedInit, reset } functions
 */
export function createMemoizedInit(fn, debounceMs = 300, name = "Init") {
  // Closure variables (private state)
  let initialized = false;
  let initializing = false;
  let debounceTimeout = null;

  /**
   * Memoized initialization function with guards and debouncing
   */
  const memoizedInit = function (...args) {
    // Guard: Prevent re-initialization if already initialized
    if (initialized) {
      console.log(`✓ ${name} already initialized, skipping...`);
      return Promise.resolve();
    }

    // Guard: Prevent concurrent initialization
    if (initializing) {
      console.log(`⏳ ${name} initialization already in progress, skipping...`);
      return Promise.resolve();
    }

    // Clear any pending debounced call
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
      debounceTimeout = null;
    }

    // Mark as initializing
    initializing = true;
    console.log(`🔍 Initializing ${name}...`);

    try {
      // Call the actual initialization function
      const result = fn.apply(this, args);

      // Mark as initialized
      initialized = true;
      console.log(`✅ ${name} initialization complete`);

      return Promise.resolve(result);
    } catch (error) {
      console.error(`❌ Error initializing ${name}:`, error);
      // Don't mark as initialized on error, allow retry
      return Promise.reject(error);
    } finally {
      initializing = false;
    }
  };

  /**
   * Debounced version of the memoized init function
   */
  const debouncedInit = function (...args) {
    // Clear any existing timeout
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }

    // Set new timeout
    debounceTimeout = setTimeout(() => {
      memoizedInit.apply(this, args);
      debounceTimeout = null;
    }, debounceMs);
  };

  /**
   * Reset the initialization state
   * Call this when you need to re-initialize (e.g., after destroying elements)
   */
  const reset = function () {
    // Clear any pending debounced call
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
      debounceTimeout = null;
    }

    initialized = false;
    initializing = false;
    console.log(`🔄 ${name} state reset`);
  };

  return {
    init: memoizedInit,
    debouncedInit,
    reset,
  };
}

// Safe element getter with logging
export function safeGetElement(id, suppressWarning = false) {
  try {
    const element = document.getElementById(id);
    if (!element && !suppressWarning) {
      console.warn(`Element with id "${id}" not found`);
    }
    return element;
  } catch (error) {
    console.error(`Error getting element "${id}":`, error);
    return null;
  }
}

export function safeSetValue(id, val) {
  const el = safeGetElement(id);
  if (el) {
    el.value = val;
  }
};

// Check for inactive items
export function isInactiveChecked(type) {
  const checkbox = safeGetElement(`show-inactive-${type}`);
  return checkbox ? checkbox.checked : false;
}

// Enhanced fetch with timeout and better error handling
export async function fetchWithTimeout(
  url,
  options = {},
  timeout = window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000
) {
  // Use configurable timeout from window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT
  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    console.warn(`Request to ${url} timed out after ${timeout}ms`);
    controller.abort();
  }, timeout);

  return fetch(url, {
    ...options,
    signal: controller.signal,
    // Add cache busting to prevent stale responses
    headers: {
      ...options.headers,
      "Cache-Control": "no-cache",
      Pragma: "no-cache",
    },
  })
    .then((response) => {
      clearTimeout(timeoutId);

      // FIX: Better handling of empty responses
      if (response.status === 0) {
        // Status 0 often indicates a network error or CORS issue
        throw new Error(
          "Network error or server is not responding. Please ensure the server is running and accessible."
        );
      }

      if (response.ok && response.status === 200) {
        const contentLength = response.headers.get("content-length");

        // Check Content-Length if present
        if (contentLength !== null && parseInt(contentLength, 10) === 0) {
          console.warn(`Empty response from ${url} (Content-Length: 0)`);
          // Don't throw error for intentionally empty responses
          return response;
        }

        // For responses without Content-Length, clone and check
        const cloned = response.clone();
        return cloned.text().then((text) => {
          if (!text || !text.trim()) {
            console.warn(`Empty response body from ${url}`);
            // Return the original response anyway
          }
          return response;
        });
      }
      return response;
    })
    .catch((error) => {
      clearTimeout(timeoutId);

      // Improve error messages for common issues
      if (error.name === "AbortError") {
        throw new Error(
          `Request timed out after ${timeout / 1000} seconds. The server may be slow or unresponsive.`
        );
      } else if (
        error.message.includes("Failed to fetch") ||
        error.message.includes("NetworkError")
      ) {
        throw new Error(
          "Unable to connect to server. Please check if the server is running on the correct port."
        );
      } else if (
        error.message.includes("empty response") ||
        error.message.includes("ERR_EMPTY_RESPONSE")
      ) {
        throw new Error(
          "Server returned an empty response. This endpoint may not be implemented yet or the server crashed."
        );
      }

      throw error;
    });
}

// Enhanced error handler for fetch operations
export function handleFetchError(error, operation = "operation") {
  console.error(`Error during ${operation}:`, error);

  if (error.name === "AbortError") {
    return `Request timed out while trying to ${operation}. Please try again.`;
  } else if (error.message.includes("HTTP")) {
    return `Server error during ${operation}: ${error.message}`;
  } else if (
    error.message.includes("NetworkError") ||
    error.message.includes("Failed to fetch")
  ) {
    return `Network error during ${operation}. Please check your connection and try again.`;
  } else {
    return `Failed to ${operation}: ${error.message}`;
  }
}

// Show user-friendly error messages
export function showErrorMessage(message, elementId = null) {
  console.error("Error:", message);

  if (elementId) {
    const element = safeGetElement(elementId);
    if (element) {
      element.textContent = message;
      element.classList.add("error-message", "text-red-600", "mt-2");
    }
  } else {
    // Show global error notification
    const errorDiv = document.createElement("div");
    errorDiv.className =
      "fixed top-4 right-4 bg-red-600 text-white px-4 py-2 rounded shadow-lg z-50";
    errorDiv.textContent = message;
    document.body.appendChild(errorDiv);

    setTimeout(() => {
      if (errorDiv.parentNode) {
        errorDiv.parentNode.removeChild(errorDiv);
      }
    }, 5000);
  }
}

// Show success messages
export function showSuccessMessage(message) {
  const successDiv = document.createElement("div");
  successDiv.className =
    "fixed top-4 right-4 bg-green-600 text-white px-4 py-2 rounded shadow-lg z-50";
  successDiv.textContent = message;
  document.body.appendChild(successDiv);

  setTimeout(() => {
    if (successDiv.parentNode) {
      successDiv.parentNode.removeChild(successDiv);
    }
  }, 3000);
}

// ----- URI Template Parsing -------------- //
export function parseUriTemplate(template) {
  const regex = /{([^}]+)}/g;
  const fields = [];
  let match;

  while ((match = regex.exec(template)) !== null) {
    fields.push(match[1]); // capture inside {}
  }
  return fields;
}

export const isAdminUser = function () {
  return Boolean(window.IS_ADMIN);
};

/**
 * Copy text to clipboard
 */
export const copyToClipboard = function (elementId) {
  const element = safeGetElement(elementId);
  if (element) {
    element.select();
    document.execCommand("copy");
    showNotification("Token copied to clipboard", "success");
  }
};

export const copyJsonToClipboard = function (sourceId) {
  const el = safeGetElement(sourceId);
  if (!el) {
    console.warn(
      `[copyJsonToClipboard] Source element "${sourceId}" not found.`
    );
    return;
  }

  const text = "value" in el ? el.value : el.textContent;

  navigator.clipboard.writeText(text).then(
    () => {
      console.info("JSON copied to clipboard ✔️");
      if (el.dataset.toast !== "off") {
        showSuccessMessage("Copied!");
      }
    },
    (err) => {
      console.error("Clipboard write failed:", err);
      showErrorMessage("Unable to copy to clipboard");
    }
  );
};

/**
 * Utility function to get cookie value
 */
export const getCookie = function (name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) {
    return parts.pop().split(";").shift();
  }
  return "";
};

/**
 * Get the currently selected team ID from the team selector
 */
export const getCurrentTeamId = function () {
  // First, try to get from Alpine.js component (most reliable)
  const teamSelector = document.querySelector('[x-data*="selectedTeam"]');
  if (
    teamSelector &&
    teamSelector._x_dataStack &&
    teamSelector._x_dataStack[0]
  ) {
    const alpineData = teamSelector._x_dataStack[0];
    const selectedTeam = alpineData.selectedTeam;

    // Return null if empty string or falsy (means "All Teams")
    if (!selectedTeam || selectedTeam === "" || selectedTeam === "all") {
      return null;
    }

    return selectedTeam;
  }

  // Fallback: check URL parameters
  const urlParams = new URLSearchParams(window.location.search);
  const teamId = urlParams.get("team_id");

  if (!teamId || teamId === "" || teamId === "all") {
    return null;
  }

  return teamId;
};

/**
 * Get the currently selected team name from Alpine.js team selector
 * @returns {string|null} Team name or null if not found
 */
export const getCurrentTeamName = function () {
  const currentTeamId = getCurrentTeamId();

  if (!currentTeamId) {
    return null;
  }

  // Method 1: Try from window.USERTEAMSDATA (most reliable)
  if (window.USERTEAMSDATA && Array.isArray(window.USERTEAMSDATA)) {
    const teamObj = window.USERTEAMSDATA.find((t) => t.id === currentTeamId);
    if (teamObj) {
      // Return the personal team name format if it's a personal team
      return teamObj.ispersonal ? `${teamObj.name}` : teamObj.name;
    }
  }

  // Method 2: Try from Alpine.js component
  const teamSelector = document.querySelector('[x-data*="selectedTeam"]');
  if (
    teamSelector &&
    teamSelector._x_dataStack &&
    teamSelector._x_dataStack[0]
  ) {
    const alpineData = teamSelector._x_dataStack[0];

    // Get the selected team name directly from Alpine
    if (
      alpineData.selectedTeamName &&
      alpineData.selectedTeamName !== "All Teams"
    ) {
      return alpineData.selectedTeamName;
    }

    // Try to find in teams array
    if (alpineData.teams && Array.isArray(alpineData.teams)) {
      const selectedTeamObj = alpineData.teams.find(
        (t) => t.id === currentTeamId
      );
      if (selectedTeamObj) {
        return selectedTeamObj.ispersonal
          ? `${selectedTeamObj.name}`
          : selectedTeamObj.name;
      }
    }
  }

  // Fallback: return the team ID if name not found
  return currentTeamId;
};

// Make URL field read-only for integration type MCP
export const updateEditToolUrl = function () {
  const editTypeField = safeGetElement("edit-tool-type");
  const editurlField = safeGetElement("edit-tool-url");
  if (editTypeField && editurlField) {
    if (editTypeField.value === "MCP") {
      editurlField.readOnly = true;
    } else {
      editurlField.readOnly = false;
    }
  }
};

/**
 * Format timestamp for display
 */
export const formatTimestamp = function (timestamp) {
  const date = new Date(timestamp);
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
};

/**
 * Handle keydown event when Enter or Space key is pressed
 *
 * @param {KeyboardEvent} event - the keyboard event triggered
 * @param {function} callback - the function to call when Enter or Space is pressed
 */
export const handleKeydown = (event, callback) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    callback(event);
  }
};

/**
 * Get root path for API calls
 */
export const getRootPath = function () {
  return window.ROOT_PATH || "";
};

/**
 * Show toast notification
 */
export const showToast = function (message, type = "info") {
  // Check if showMessage function exists (from existing admin.js)
  if (typeof showNotification === "function") {
    showNotification(message, type === "error" ? "danger" : type);
  } else {
    console.log(`[${type.toUpperCase()}] ${message}`);
  }
};

/**
 * Show notification (simple implementation)
 */
export const showNotification = function (message, type = "info") {
  console.log(`${type.toUpperCase()}: ${message}`);

  // Create a simple toast notification
  const toast = document.createElement("div");
  toast.className = `fixed top-4 right-4 z-50 px-4 py-3 rounded-md text-sm font-medium max-w-sm ${
    type === "success"
      ? "bg-green-100 text-green-800 border border-green-400"
      : type === "error"
        ? "bg-red-100 text-red-800 border border-red-400"
        : "bg-blue-100 text-blue-800 border border-blue-400"
  }`;
  toast.textContent = message;

  document.body.appendChild(toast);

  // Auto-remove after 5 seconds
  setTimeout(() => {
    if (toast.parentNode) {
      toast.parentNode.removeChild(toast);
    }
  }, 5000);
};

/**
 * Check if string is valid base64
 * @param {string} str - The string to validate
 * @returns {boolean} - True if valid base64
 */
export const isValidBase64 = function (str) {
  if (str.length === 0) {
    return false;
  }

  // Base64 regex pattern
  const base64Pattern = /^[A-Za-z0-9+/]*={0,2}$/;
  return base64Pattern.test(str);
};

// Logs refresh function
export const refreshLogs = function () {
  const logsSection = safeGetElement("logs");
  if (logsSection && typeof window.htmx !== "undefined") {
    // Trigger HTMX refresh on the logs section
    window.htmx.trigger(logsSection, "refresh");
  }
};

/**
 * Truncate text with ellipsis
 */
export const truncateText = function (text, maxLength) {
  if (!text) {
    return "";
  }
  return text.length > maxLength
    ? text.substring(0, maxLength) + "..."
    : text;
};

/**
 * Decode HTML entities back to their original characters.
 * Used when populating form fields to prevent double-encoding.
 * @param {string} html - The HTML-encoded string
 * @returns {string} Decoded string
 */
export const decodeHtml = function(html) {
  if (html === null || html === undefined) {
    return "";
  }
  const txt = document.createElement("textarea");
  txt.innerHTML = html;
  return txt.value;
}
