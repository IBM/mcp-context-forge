// Make URL field read-only for integration type MCP
function updateEditToolUrl() {
    const editTypeField = document.getElementById("edit-tool-type");
    const editurlField = document.getElementById("edit-tool-url");
    if (editTypeField && editurlField) {
        if (editTypeField.value === "MCP") {
            editurlField.readOnly = true;
        } else {
            editurlField.readOnly = false;
        }
    }
}

// Attach event listener after DOM is loaded or when modal opens
document.addEventListener("DOMContentLoaded", function () {
    const TypeField = document.getElementById("edit-tool-type");
    if (TypeField) {
        TypeField.addEventListener("change", updateEditToolUrl);
        // Set initial state
        updateEditToolUrl();
    }
});
/**
 * ====================================================================
 * SECURE ADMIN.JS - COMPLETE VERSION WITH XSS PROTECTION
 * ====================================================================
 *
 * SECURITY FEATURES:
 * - XSS prevention with comprehensive input sanitization
 * - Input validation for all form fields
 * - Safe DOM manipulation only
 * - No innerHTML usage with user data
 * - Comprehensive error handling and timeouts
 *
 * PERFORMANCE FEATURES:
 * - Centralized state management
 * - Memory leak prevention
 * - Proper event listener cleanup
 * - Race condition elimination
 */

// ===================================================================
// SECURITY: HTML-escape function to prevent XSS attacks
// ===================================================================

function escapeHtml(unsafe) {
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
 * Header validation constants and functions
 */
const HEADER_NAME_REGEX = /^[A-Za-z0-9-]+$/;
const MAX_HEADER_VALUE_LENGTH = 4096;

/**
 * Validate a passthrough header name and value
 * @param {string} name - Header name to validate
 * @param {string} value - Header value to validate
 * @returns {Object} Validation result with 'valid' boolean and 'error' message
 */
function validatePassthroughHeader(name, value) {
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
function validateInputName(name, type = "input") {
    if (!name || typeof name !== "string") {
        return { valid: false, error: `${type} name is required` };
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
                error: `${type} name contains invalid characters`,
            };
        }
    }

    // Length validation
    if (cleaned.length < 1) {
        return { valid: false, error: `${type} name cannot be empty` };
    }

    if (cleaned.length > window.MAX_NAME_LENGTH) {
        return {
            valid: false,
            error: `${type} name must be ${window.MAX_NAME_LENGTH} characters or less`,
        };
    }

    // For prompt names, be more restrictive
    if (type === "prompt") {
        // Only allow alphanumeric, underscore, hyphen, and spaces
        const validPattern = /^[a-zA-Z0-9_\s-]+$/;
        if (!validPattern.test(cleaned)) {
            return {
                valid: false,
                error: "Prompt name can only contain letters, numbers, spaces, underscores, and hyphens",
            };
        }
    }

    return { valid: true, value: cleaned };
}

/**
 * Extracts content from various formats with fallback
 */
function extractContent(content, fallback = "") {
    if (typeof content === "object" && content !== null) {
        if (content.text !== undefined && content.text !== null) {
            return content.text;
        } else if (content.blob !== undefined && content.blob !== null) {
            return content.blob;
        } else if (content.content !== undefined && content.content !== null) {
            return content.content;
        } else {
            return JSON.stringify(content, null, 2);
        }
    }
    return String(content || fallback);
}

/**
 * SECURITY: Validate URL inputs
 */
function validateUrl(url) {
    if (!url || typeof url !== "string") {
        return { valid: false, error: "URL is required" };
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
function validateJson(jsonString, fieldName = "JSON") {
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
function safeSetInnerHTML(element, htmlContent, isTrusted = false) {
    if (!isTrusted) {
        console.error("Attempted to set innerHTML with untrusted content");
        element.textContent = htmlContent; // Fallback to safe text
        return;
    }
    element.innerHTML = htmlContent;
}

// ===================================================================
// UTILITY FUNCTIONS - Define these FIRST before anything else
// ===================================================================

// Check for inative items
function isInactiveChecked(type) {
    const checkbox = safeGetElement(`show-inactive-${type}`);
    return checkbox ? checkbox.checked : false;
}

// Enhanced fetch with timeout and better error handling
function fetchWithTimeout(
    url,
    options = {},
    timeout = window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000,
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
                    "Network error or server is not responding. Please ensure the server is running and accessible.",
                );
            }

            if (response.ok && response.status === 200) {
                const contentLength = response.headers.get("content-length");

                // Check Content-Length if present
                if (
                    contentLength !== null &&
                    parseInt(contentLength, 10) === 0
                ) {
                    console.warn(
                        `Empty response from ${url} (Content-Length: 0)`,
                    );
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
                    `Request timed out after ${timeout / 1000} seconds. The server may be slow or unresponsive.`,
                );
            } else if (
                error.message.includes("Failed to fetch") ||
                error.message.includes("NetworkError")
            ) {
                throw new Error(
                    "Unable to connect to server. Please check if the server is running on the correct port.",
                );
            } else if (
                error.message.includes("empty response") ||
                error.message.includes("ERR_EMPTY_RESPONSE")
            ) {
                throw new Error(
                    "Server returned an empty response. This endpoint may not be implemented yet or the server crashed.",
                );
            }

            throw error;
        });
}

// Safe element getter with logging
function safeGetElement(id, suppressWarning = false) {
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

// Enhanced error handler for fetch operations
function handleFetchError(error, operation = "operation") {
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
function showErrorMessage(message, elementId = null) {
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
function showSuccessMessage(message) {
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

// ===================================================================
// ENHANCED GLOBAL STATE MANAGEMENT
// ===================================================================

const AppState = {
    parameterCount: 0,
    currentTestTool: null,
    toolTestResultEditor: null,
    isInitialized: false,
    pendingRequests: new Set(),
    editors: {
        gateway: {
            headers: null,
            body: null,
            formHandler: null,
            closeHandler: null,
        },
    },

    // Track active modals to prevent multiple opens
    activeModals: new Set(),

    // Safe method to reset state
    reset() {
        this.parameterCount = 0;
        this.currentTestTool = null;
        this.toolTestResultEditor = null;
        this.activeModals.clear();

        // Cancel pending requests
        this.pendingRequests.forEach((controller) => {
            try {
                controller.abort();
            } catch (error) {
                console.warn("Error aborting request:", error);
            }
        });
        this.pendingRequests.clear();

        // Clean up editors
        Object.keys(this.editors.gateway).forEach((key) => {
            this.editors.gateway[key] = null;
        });

        // ADD THIS LINE: Clean up tool test state
        if (typeof cleanupToolTestState === "function") {
            cleanupToolTestState();
        }

        console.log("✓ Application state reset");
    },

    // Track requests for cleanup
    addPendingRequest(controller) {
        this.pendingRequests.add(controller);
    },

    removePendingRequest(controller) {
        this.pendingRequests.delete(controller);
    },

    // Safe parameter count management
    getParameterCount() {
        return this.parameterCount;
    },

    incrementParameterCount() {
        return ++this.parameterCount;
    },

    decrementParameterCount() {
        if (this.parameterCount > 0) {
            return --this.parameterCount;
        }
        return 0;
    },

    // Modal management
    isModalActive(modalId) {
        return this.activeModals.has(modalId);
    },

    setModalActive(modalId) {
        this.activeModals.add(modalId);
    },

    setModalInactive(modalId) {
        this.activeModals.delete(modalId);
    },
};

// Make state available globally but controlled
window.AppState = AppState;

// ===================================================================
// ENHANCED MODAL FUNCTIONS with Security and State Management
// ===================================================================

function openModal(modalId) {
    try {
        if (AppState.isModalActive(modalId)) {
            console.warn(`Modal ${modalId} is already active`);
            return;
        }

        const modal = safeGetElement(modalId);
        if (!modal) {
            console.error(`Modal ${modalId} not found`);
            return;
        }

        // Reset modal state
        const resetModelVariable = false;
        if (resetModelVariable) {
            resetModalState(modalId);
        }

        modal.classList.remove("hidden");
        AppState.setModalActive(modalId);

        console.log(`✓ Opened modal: ${modalId}`);
    } catch (error) {
        console.error(`Error opening modal ${modalId}:`, error);
    }
}

// Global event handler for Escape key
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        // Find any active modal
        const activeModal = Array.from(AppState.activeModals)[0];
        if (activeModal) {
            closeModal(activeModal);
        }
    }
});

function closeModal(modalId, clearId = null) {
    try {
        const modal = safeGetElement(modalId);
        if (!modal) {
            console.error(`Modal ${modalId} not found`);
            return;
        }

        // Clear specified content if provided
        if (clearId) {
            const resultEl = safeGetElement(clearId);
            if (resultEl) {
                resultEl.innerHTML = "";
            }
        }

        // Clean up specific modal types
        if (modalId === "gateway-test-modal") {
            cleanupGatewayTestModal();
        } else if (modalId === "tool-test-modal") {
            cleanupToolTestModal(); // ADD THIS LINE
        } else if (modalId === "prompt-test-modal") {
            cleanupPromptTestModal();
        }

        modal.classList.add("hidden");
        AppState.setModalInactive(modalId);

        console.log(`✓ Closed modal: ${modalId}`);
    } catch (error) {
        console.error(`Error closing modal ${modalId}:`, error);
    }
}

function resetModalState(modalId) {
    try {
        // Clear any dynamic content
        const modalContent = document.querySelector(
            `#${modalId} [data-dynamic-content]`,
        );
        if (modalContent) {
            modalContent.innerHTML = "";
        }

        // Reset any forms in the modal
        const forms = document.querySelectorAll(`#${modalId} form`);
        forms.forEach((form) => {
            try {
                form.reset();
                // Clear any error messages
                const errorElements = form.querySelectorAll(".error-message");
                errorElements.forEach((el) => el.remove());
            } catch (error) {
                console.error("Error resetting form:", error);
            }
        });

        console.log(`✓ Reset modal state: ${modalId}`);
    } catch (error) {
        console.error(`Error resetting modal state ${modalId}:`, error);
    }
}

// ===================================================================
// ENHANCED METRICS LOADING with Retry Logic and Request Deduplication
// ===================================================================

// More robust metrics request tracking
let metricsRequestController = null;
let metricsRequestPromise = null;
const MAX_METRICS_RETRIES = 3; // Increased from 2
const METRICS_RETRY_DELAY = 2000; // Increased from 1500ms

/**
 * Enhanced metrics loading with better race condition prevention
 */
async function loadAggregatedMetrics() {
    const metricsPanel = safeGetElement("metrics-panel", true);
    if (!metricsPanel || metricsPanel.closest(".tab-panel.hidden")) {
        console.log("Metrics panel not visible, skipping load");
        return;
    }

    // Cancel any existing request
    if (metricsRequestController) {
        console.log("Cancelling existing metrics request...");
        metricsRequestController.abort();
        metricsRequestController = null;
    }

    // If there's already a promise in progress, return it
    if (metricsRequestPromise) {
        console.log("Returning existing metrics promise...");
        return metricsRequestPromise;
    }

    console.log("Starting new metrics request...");
    showMetricsLoading();

    metricsRequestPromise = loadMetricsInternal().finally(() => {
        metricsRequestPromise = null;
        metricsRequestController = null;
        hideMetricsLoading();
    });

    return metricsRequestPromise;
}

async function loadMetricsInternal() {
    try {
        console.log("Loading aggregated metrics...");
        showMetricsLoading();

        const result = await fetchWithTimeoutAndRetry(
            `${window.ROOT_PATH}/admin/metrics`,
            {}, // options
            (window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000) * 1.5, // Use 1.5x configurable timeout for metrics
            MAX_METRICS_RETRIES,
        );

        if (!result.ok) {
            // If metrics endpoint doesn't exist, show a placeholder instead of failing
            if (result.status === 404) {
                showMetricsPlaceholder();
                return;
            }
            // FIX: Handle 500 errors specifically
            if (result.status >= 500) {
                throw new Error(
                    `Server error (${result.status}). The metrics calculation may have failed.`,
                );
            }
            throw new Error(`HTTP ${result.status}: ${result.statusText}`);
        }

        // FIX: Handle empty or invalid JSON responses
        let data;
        try {
            const text = await result.text();
            if (!text || !text.trim()) {
                console.warn("Empty metrics response, using default data");
                data = {}; // Use empty object as fallback
            } else {
                data = JSON.parse(text);
            }
        } catch (parseError) {
            console.error("Failed to parse metrics JSON:", parseError);
            data = {}; // Use empty object as fallback
        }

        displayMetrics(data);
        console.log("✓ Metrics loaded successfully");
    } catch (error) {
        console.error("Error loading aggregated metrics:", error);
        showMetricsError(error);
    } finally {
        hideMetricsLoading();
    }
}

/**
 * Enhanced fetch with automatic retry logic and better error handling
 */
async function fetchWithTimeoutAndRetry(
    url,
    options = {},
    timeout = window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000,
    maxRetries = 3,
) {
    let lastError;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
            console.log(`Metrics fetch attempt ${attempt}/${maxRetries}`);

            // Create new controller for each attempt
            metricsRequestController = new AbortController();

            const response = await fetchWithTimeout(
                url,
                {
                    ...options,
                    signal: metricsRequestController.signal,
                },
                timeout,
            );

            console.log(`✓ Metrics fetch attempt ${attempt} succeeded`);
            return response;
        } catch (error) {
            lastError = error;

            console.warn(
                `✗ Metrics fetch attempt ${attempt} failed:`,
                error.message,
            );

            // Don't retry on certain errors
            if (error.name === "AbortError" && attempt < maxRetries) {
                console.log("Request was aborted, skipping retry");
                throw error;
            }

            // Don't retry on the last attempt
            if (attempt === maxRetries) {
                console.error(
                    `All ${maxRetries} metrics fetch attempts failed`,
                );
                throw error;
            }

            // Wait before retrying, with modest backoff
            const delay = METRICS_RETRY_DELAY * attempt;
            console.log(`Retrying metrics fetch in ${delay}ms...`);
            await new Promise((resolve) => setTimeout(resolve, delay));
        }
    }

    throw lastError;
}

/**
 * Show loading state for metrics
 */
function showMetricsLoading() {
    const metricsPanel = safeGetElement("metrics-panel", true); // suppress warning
    if (metricsPanel) {
        const existingLoading = safeGetElement("metrics-loading", true);
        if (existingLoading) {
            return;
        }

        const loadingDiv = document.createElement("div");
        loadingDiv.id = "metrics-loading";
        loadingDiv.className = "flex justify-center items-center p-8";
        loadingDiv.innerHTML = `
            <div class="text-center">
                <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 mx-auto mb-4"></div>
                <p class="text-gray-600">Loading metrics...</p>
                <p class="text-sm text-gray-500 mt-2">This may take a moment</p>
            </div>
        `;
        metricsPanel.innerHTML = "";
        metricsPanel.appendChild(loadingDiv);
    }
}

/**
 * Hide loading state for metrics
 */
function hideMetricsLoading() {
    const loadingDiv = safeGetElement("metrics-loading", true);
    if (loadingDiv && loadingDiv.parentNode) {
        loadingDiv.parentNode.removeChild(loadingDiv);
    }
}

/**
 * Enhanced error display with retry option
 */
function showMetricsError(error) {
    const metricsPanel = safeGetElement("metrics-panel");
    if (metricsPanel) {
        const errorDiv = document.createElement("div");
        errorDiv.className = "text-center p-8";

        const errorMessage = handleFetchError(error, "load metrics");

        // Determine if this looks like a server/network issue
        const isNetworkError =
            error.message.includes("fetch") ||
            error.message.includes("network") ||
            error.message.includes("timeout") ||
            error.name === "AbortError";

        const helpText = isNetworkError
            ? "This usually happens when the server is slow to respond or there's a network issue."
            : "There may be an issue with the metrics calculation on the server.";

        errorDiv.innerHTML = `
            <div class="text-red-600 mb-4">
                <svg class="w-12 h-12 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
                <h3 class="text-lg font-medium mb-2">Failed to Load Metrics</h3>
                <p class="text-sm mb-2">${escapeHtml(errorMessage)}</p>
                <p class="text-xs text-gray-500 mb-4">${helpText}</p>
                <button
                    onclick="retryLoadMetrics()"
                    class="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 transition-colors">
                    Try Again
                </button>
            </div>
        `;

        metricsPanel.innerHTML = "";
        metricsPanel.appendChild(errorDiv);
    }
}

/**
 * Retry loading metrics (callable from retry button)
 */
function retryLoadMetrics() {
    console.log("Manual retry requested");
    // Reset all tracking variables
    metricsRequestController = null;
    metricsRequestPromise = null;
    loadAggregatedMetrics();
}

// Make retry function available globally immediately
window.retryLoadMetrics = retryLoadMetrics;

// ---------------------------------------------------------------
// Auto-refresh aggregated metrics every 10 seconds (when visible)
// ---------------------------------------------------------------
let metricsAutoRefreshTimer = null;
function startMetricsAutoRefresh() {
    if (metricsAutoRefreshTimer) return;
    metricsAutoRefreshTimer = setInterval(() => {
        const panel = safeGetElement("metrics-panel");
        if (!panel || panel.closest(".tab-panel.hidden")) return; // only refresh if visible
        loadAggregatedMetrics();
    }, 10000);
}
function stopMetricsAutoRefresh() {
    if (metricsAutoRefreshTimer) {
        clearInterval(metricsAutoRefreshTimer);
        metricsAutoRefreshTimer = null;
    }
}
startMetricsAutoRefresh();

function showMetricsPlaceholder() {
    const metricsPanel = safeGetElement("metrics-panel");
    if (metricsPanel) {
        const placeholderDiv = document.createElement("div");
        placeholderDiv.className = "text-gray-600 p-4 text-center";
        placeholderDiv.textContent =
            "Metrics endpoint not available. This feature may not be implemented yet.";
        metricsPanel.innerHTML = "";
        metricsPanel.appendChild(placeholderDiv);
    }
}

// ===================================================================
// ENHANCED METRICS DISPLAY with Complete System Overview
// ===================================================================

function displayMetrics(data) {
    const metricsPanel = safeGetElement("metrics-panel");
    if (!metricsPanel) {
        console.error("Metrics panel element not found");
        return;
    }

    try {
        // Normalize snake_case metrics keys to camelCase for consistent downstream processing
        const normalizeCategory = (obj) => {
            if (!obj || typeof obj !== "object") return obj;
            const out = { ...obj };
            const map = [
                ["total_executions", "totalExecutions"],
                ["successful_executions", "successfulExecutions"],
                ["failed_executions", "failedExecutions"],
                ["failure_rate", "failureRate"],
                ["avg_response_time", "avgResponseTime"],
                ["min_response_time", "minResponseTime"],
                ["max_response_time", "maxResponseTime"],
                ["last_execution_time", "lastExecutionTime"],
            ];
            map.forEach(([snake, camel]) => {
                if (out[camel] === undefined && out[snake] !== undefined) out[camel] = out[snake];
            });
            return out;
        };
        ["tools", "resources", "prompts", "servers", "gateways", "a2a_agents"].forEach((k) => {
            if (data[k]) data[k] = normalizeCategory(data[k]);
        });
        // FIX: Handle completely empty data
        if (!data || Object.keys(data).length === 0) {
            const emptyStateDiv = document.createElement("div");
            emptyStateDiv.className = "text-center p-8 text-gray-500";
            emptyStateDiv.innerHTML = `
                <svg class="mx-auto h-12 w-12 text-gray-400 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path>
                </svg>
                <h3 class="text-lg font-medium mb-2">No Metrics Available</h3>
                <p class="text-sm">Metrics data will appear here once tools, resources, or prompts are executed.</p>
                <button onclick="retryLoadMetrics()" class="mt-4 bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 transition-colors">
                    Refresh Metrics
                </button>
            `;
            metricsPanel.innerHTML = "";
            metricsPanel.appendChild(emptyStateDiv);
            return;
        }

        // Create main container with safe structure
        const mainContainer = document.createElement("div");
        mainContainer.className = "space-y-6";

        // System overview section (top priority display)
        if (data.system || data.overall) {
            const systemData = data.system || data.overall || {};
            const systemSummary = createSystemSummaryCard(systemData);
            mainContainer.appendChild(systemSummary);
        }

        // Key Performance Indicators section
        const kpiData = extractKPIData(data);
        if (Object.keys(kpiData).length > 0) {
            const kpiSection = createKPISection(kpiData);
            mainContainer.appendChild(kpiSection);
        }

        // Top Performers section (before individual metrics)
        if (data.topPerformers || data.top) {
            const topData = data.topPerformers || data.top;
            // const topSection = createTopPerformersSection(topData);
            const topSection = createEnhancedTopPerformersSection(topData);

            mainContainer.appendChild(topSection);
        }

        // Individual metrics grid for all components
        const metricsContainer = document.createElement("div");
        metricsContainer.className =
            "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6";

        // Tools metrics
        if (data.tools) {
            const toolsCard = createMetricsCard("Tools", data.tools);
            metricsContainer.appendChild(toolsCard);
        }

        // Resources metrics
        if (data.resources) {
            const resourcesCard = createMetricsCard(
                "Resources",
                data.resources,
            );
            metricsContainer.appendChild(resourcesCard);
        }

        // Prompts metrics
        if (data.prompts) {
            const promptsCard = createMetricsCard("Prompts", data.prompts);
            metricsContainer.appendChild(promptsCard);
        }

        // Gateways metrics
        if (data.gateways) {
            const gatewaysCard = createMetricsCard("Gateways", data.gateways);
            metricsContainer.appendChild(gatewaysCard);
        }

        // Servers metrics
        if (data.servers) {
            const serversCard = createMetricsCard("Servers", data.servers);
            metricsContainer.appendChild(serversCard);
        }

        // Performance metrics
        if (data.performance) {
            const performanceCard = createPerformanceCard(data.performance);
            metricsContainer.appendChild(performanceCard);
        }

        mainContainer.appendChild(metricsContainer);

        // Recent activity section (bottom)
        if (data.recentActivity || data.recent) {
            const activityData = data.recentActivity || data.recent;
            const activitySection = createRecentActivitySection(activityData);
            mainContainer.appendChild(activitySection);
        }

        // Safe content replacement
        metricsPanel.innerHTML = "";
        metricsPanel.appendChild(mainContainer);

        console.log("✓ Enhanced metrics display rendered successfully");
    } catch (error) {
        console.error("Error displaying metrics:", error);
        showMetricsError(error);
    }
}

/**
 * SECURITY: Create system summary card with safe HTML generation
 */
function createSystemSummaryCard(systemData) {
    try {
        const card = document.createElement("div");
        card.className =
            "bg-gradient-to-r from-blue-500 to-purple-600 rounded-lg shadow-lg p-6 text-white";

        // Card title
        const title = document.createElement("h2");
        title.className = "text-2xl font-bold mb-4";
        title.textContent = "System Overview";
        card.appendChild(title);

        // Statistics grid
        const statsGrid = document.createElement("div");
        statsGrid.className = "grid grid-cols-2 md:grid-cols-4 gap-4";

        // Define system statistics with validation
        const systemStats = [
            {
                key: "uptime",
                label: "Uptime",
                suffix: "",
            },
            {
                key: "totalRequests",
                label: "Total Requests",
                suffix: "",
            },
            {
                key: "activeConnections",
                label: "Active Connections",
                suffix: "",
            },
            {
                key: "memoryUsage",
                label: "Memory Usage",
                suffix: "%",
            },
            {
                key: "cpuUsage",
                label: "CPU Usage",
                suffix: "%",
            },
            {
                key: "diskUsage",
                label: "Disk Usage",
                suffix: "%",
            },
            {
                key: "networkIn",
                label: "Network In",
                suffix: " MB",
            },
            {
                key: "networkOut",
                label: "Network Out",
                suffix: " MB",
            },
        ];

        systemStats.forEach((stat) => {
            const value =
                systemData[stat.key] ??
                systemData[stat.key.replace(/([A-Z])/g, "_$1").toLowerCase()] ??
                "N/A";

            const statDiv = document.createElement("div");
            statDiv.className = "text-center";

            const valueSpan = document.createElement("div");
            valueSpan.className = "text-2xl font-bold";
            valueSpan.textContent =
                (value === "N/A" ? "N/A" : String(value)) + stat.suffix;

            const labelSpan = document.createElement("div");
            labelSpan.className = "text-blue-100 text-sm";
            labelSpan.textContent = stat.label;

            statDiv.appendChild(valueSpan);
            statDiv.appendChild(labelSpan);
            statsGrid.appendChild(statDiv);
        });

        card.appendChild(statsGrid);
        return card;
    } catch (error) {
        console.error("Error creating system summary card:", error);
        return document.createElement("div"); // Safe fallback
    }
}

/**
 * SECURITY: Create KPI section with safe data handling
 */
function createKPISection(kpiData) {
    try {
        const section = document.createElement("div");
        section.className = "grid grid-cols-1 md:grid-cols-4 gap-4";

        // Define KPI indicators with safe configuration
        const kpis = [
            {
                key: "totalExecutions",
                label: "Total Executions",
                icon: "🎯",
                color: "blue",
            },
            {
                key: "successRate",
                label: "Success Rate",
                icon: "✅",
                color: "green",
                suffix: "%",
            },
            {
                key: "avgResponseTime",
                label: "Avg Response Time",
                icon: "⚡",
                color: "yellow",
                suffix: "ms",
            },
            {
                key: "errorRate",
                label: "Error Rate",
                icon: "❌",
                color: "red",
                suffix: "%",
            },
        ];

        kpis.forEach((kpi) => {
            const value = kpiData[kpi.key] ?? "N/A";

            const kpiCard = document.createElement("div");
            kpiCard.className = `bg-white rounded-lg shadow p-4 border-l-4 border-${kpi.color}-500 dark:bg-gray-800`;

            const header = document.createElement("div");
            header.className = "flex items-center justify-between";

            const iconSpan = document.createElement("span");
            iconSpan.className = "text-2xl";
            iconSpan.textContent = kpi.icon;

            const valueDiv = document.createElement("div");
            valueDiv.className = "text-right";

            const valueSpan = document.createElement("div");
            valueSpan.className = `text-2xl font-bold text-${kpi.color}-600`;
            valueSpan.textContent =
                (value === "N/A" ? "N/A" : String(value)) + (kpi.suffix || "");

            const labelSpan = document.createElement("div");
            labelSpan.className = "text-sm text-gray-500 dark:text-gray-400";
            labelSpan.textContent = kpi.label;

            valueDiv.appendChild(valueSpan);
            valueDiv.appendChild(labelSpan);
            header.appendChild(iconSpan);
            header.appendChild(valueDiv);
            kpiCard.appendChild(header);
            section.appendChild(kpiCard);
        });

        return section;
    } catch (error) {
        console.error("Error creating KPI section:", error);
        return document.createElement("div"); // Safe fallback
    }
}

/**
 * SECURITY: Extract and calculate KPI data with validation
 */
function extractKPIData(data) {
    try {
        const kpiData = {};

        // Initialize calculation variables
        let totalExecutions = 0;
        let totalSuccessful = 0;
        let totalFailed = 0;
        const responseTimes = [];

        // Helper to safely resolve camelCase or snake_case keys.
        const metricVal = (obj, camel) => {
            if (!obj) return undefined;
            if (camel in obj) return obj[camel];
            // convert camelCase to snake_case
            const snake = camel
                .replace(/([A-Z])/g, "_$1")
                .replace(/__/g, "_")
                .toLowerCase();
            return obj[snake];
        };

        // Process each category safely (added a2a_agents; gateways kept for future parity)
        const categories = ["tools", "resources", "prompts", "servers", "gateways", "a2a_agents"];
        categories.forEach((category) => {
            const categoryData = data[category];
            if (!categoryData) return;

            totalExecutions += Number(metricVal(categoryData, "totalExecutions") || 0);
            totalSuccessful += Number(metricVal(categoryData, "successfulExecutions") || 0);
            totalFailed += Number(metricVal(categoryData, "failedExecutions") || 0);

            const avgRt = metricVal(categoryData, "avgResponseTime");
            if (avgRt !== undefined && avgRt !== null && avgRt !== "N/A") {
                const n = Number(avgRt);
                if (!Number.isNaN(n)) responseTimes.push(n);
            }
        });

        // Calculate safe aggregate metrics
        kpiData.totalExecutions = totalExecutions;
        kpiData.successRate =
            totalExecutions > 0
                ? Math.round((totalSuccessful / totalExecutions) * 100)
                : 0;
        kpiData.errorRate =
            totalExecutions > 0
                ? Math.round((totalFailed / totalExecutions) * 100)
                : 0;
        kpiData.avgResponseTime =
            responseTimes.length > 0
                ? Math.round(
                      responseTimes.reduce((a, b) => a + b, 0) /
                          responseTimes.length,
                  )
                : "N/A";

        return kpiData;
    } catch (error) {
        console.error("Error extracting KPI data:", error);
        return {}; // Safe fallback
    }
}

/**
 * SECURITY: Create top performers section with safe display
 */
// function createTopPerformersSection(topData) {
//     try {
//         const section = document.createElement("div");
//         section.className = "bg-white rounded-lg shadow p-6 dark:bg-gray-800";

//         const title = document.createElement("h3");
//         title.className = "text-lg font-medium mb-4 dark:text-gray-200";
//         title.textContent = "Top Performers";
//         section.appendChild(title);

//         const grid = document.createElement("div");
//         grid.className = "grid grid-cols-1 md:grid-cols-2 gap-4";

//         // Top Tools
//         if (topData.tools && Array.isArray(topData.tools)) {
//             const toolsCard = createTopItemCard("Tools", topData.tools);
//             grid.appendChild(toolsCard);
//         }

//         // Top Resources
//         if (topData.resources && Array.isArray(topData.resources)) {
//             const resourcesCard = createTopItemCard(
//                 "Resources",
//                 topData.resources,
//             );
//             grid.appendChild(resourcesCard);
//         }

//         // Top Prompts
//         if (topData.prompts && Array.isArray(topData.prompts)) {
//             const promptsCard = createTopItemCard("Prompts", topData.prompts);
//             grid.appendChild(promptsCard);
//         }

//         // Top Servers
//         if (topData.servers && Array.isArray(topData.servers)) {
//             const serversCard = createTopItemCard("Servers", topData.servers);
//             grid.appendChild(serversCard);
//         }

//         section.appendChild(grid);
//         return section;
//     } catch (error) {
//         console.error("Error creating top performers section:", error);
//         return document.createElement("div"); // Safe fallback
//     }
// }
function createEnhancedTopPerformersSection(topData) {
    try {
        const section = document.createElement("div");
        section.className = "bg-white rounded-lg shadow p-6 dark:bg-gray-800";

        const title = document.createElement("h3");
        title.className = "text-lg font-medium mb-4 dark:text-gray-200";
        title.textContent = "Top Performers";
        title.setAttribute("aria-label", "Top Performers Section");
        section.appendChild(title);

        // Loading skeleton
        const skeleton = document.createElement("div");
        skeleton.className = "animate-pulse space-y-4";
        skeleton.innerHTML = `
            <div class="h-4 bg-gray-200 rounded w-1/4 dark:bg-gray-700"></div>
            <div class="space-y-2">
                <div class="h-10 bg-gray-200 rounded dark:bg-gray-700"></div>
                <div class="h-32 bg-gray-200 rounded dark:bg-gray-700"></div>
            </div>`;
        section.appendChild(skeleton);

        // Tabs
        const tabsContainer = document.createElement("div");
        tabsContainer.className =
            "border-b border-gray-200 dark:border-gray-700";
        const tabList = document.createElement("nav");
        tabList.className = "-mb-px flex space-x-8 overflow-x-auto";
        tabList.setAttribute("aria-label", "Top Performers Tabs");

        const entityTypes = [
            "tools",
            "resources",
            "prompts",
            "gateways",
            "servers",
        ];
        entityTypes.forEach((type, index) => {
            if (topData[type] && Array.isArray(topData[type])) {
                const tab = createTab(type, index === 0);
                tabList.appendChild(tab);
            }
        });

        tabsContainer.appendChild(tabList);
        section.appendChild(tabsContainer);

        // Content panels
        const contentContainer = document.createElement("div");
        contentContainer.className = "mt-4";

        entityTypes.forEach((type, index) => {
            if (topData[type] && Array.isArray(topData[type])) {
                const panel = createTopPerformersTable(
                    type,
                    topData[type],
                    index === 0,
                );
                contentContainer.appendChild(panel);
            }
        });

        section.appendChild(contentContainer);

        // Remove skeleton once data is loaded
        setTimeout(() => skeleton.remove(), 500); // Simulate async data load

        // Export button
        const exportButton = document.createElement("button");
        exportButton.className =
            "mt-4 bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 dark:bg-indigo-500 dark:hover:bg-indigo-600";
        exportButton.textContent = "Export Metrics";
        exportButton.onclick = () => exportMetricsToCSV(topData);
        section.appendChild(exportButton);

        return section;
    } catch (error) {
        console.error("Error creating enhanced top performers section:", error);
        showErrorMessage("Failed to load top performers section");
        return document.createElement("div");
    }
}
function calculateSuccessRate(item) {
    // API returns successRate directly as a percentage
    if (item.successRate !== undefined && item.successRate !== null) {
        return Math.round(item.successRate);
    }
    // Fallback for legacy format (if needed)
    const total =
        item.execution_count || item.executions || item.executionCount || 0;
    const successful = item.successful_count || item.successfulExecutions || 0;
    return total > 0 ? Math.round((successful / total) * 100) : 0;
}

function formatNumber(num) {
    return new Intl.NumberFormat().format(num);
}

function formatLastUsed(timestamp) {
    if (!timestamp) {
        return "Never";
    }

    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) {
        return "Just now";
    }
    if (diffMins < 60) {
        return `${diffMins} min ago`;
    }
    if (diffMins < 1440) {
        return `${Math.floor(diffMins / 60)} hours ago`;
    }
    if (diffMins < 10080) {
        return `${Math.floor(diffMins / 1440)} days ago`;
    }

    return date.toLocaleDateString();
}
function createTopPerformersTable(entityType, data, isActive) {
    const panel = document.createElement("div");
    panel.id = `top-${entityType}-panel`;
    panel.className = `transition-opacity duration-300 ${isActive ? "opacity-100" : "hidden opacity-0"}`;
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", `top-${entityType}-tab`);

    if (data.length === 0) {
        const emptyState = document.createElement("p");
        emptyState.className =
            "text-gray-500 dark:text-gray-400 text-center py-4";
        emptyState.textContent = `No ${entityType} data available`;
        panel.appendChild(emptyState);
        return panel;
    }

    // Responsive table wrapper
    const tableWrapper = document.createElement("div");
    tableWrapper.className = "overflow-x-auto sm:overflow-x-visible";

    const table = document.createElement("table");
    table.className =
        "min-w-full divide-y divide-gray-200 dark:divide-gray-700";

    // Table header
    const thead = document.createElement("thead");
    thead.className =
        "bg-gray-50 dark:bg-gray-700 hidden sm:table-header-group";
    const headerRow = document.createElement("tr");
    const headers = [
        "Rank",
        "Name",
        "Executions",
        "Avg Response Time",
        "Success Rate",
        "Last Used",
    ];

    headers.forEach((headerText, index) => {
        const th = document.createElement("th");
        th.className =
            "px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider";
        th.setAttribute("scope", "col");
        th.textContent = headerText;
        if (index === 0) {
            th.setAttribute("aria-sort", "ascending");
        }
        headerRow.appendChild(th);
    });

    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Table body
    const tbody = document.createElement("tbody");
    tbody.className =
        "bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700";

    // Pagination (if > 5 items)
    const paginatedData = data.slice(0, 5); // Limit to top 5
    paginatedData.forEach((item, index) => {
        const row = document.createElement("tr");
        row.className =
            "hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors duration-200";

        // Rank
        const rankCell = document.createElement("td");
        rankCell.className =
            "px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-100 sm:px-6 sm:py-4";
        const rankBadge = document.createElement("span");
        rankBadge.className = `inline-flex items-center justify-center w-6 h-6 rounded-full ${
            index === 0
                ? "bg-yellow-400 text-yellow-900"
                : index === 1
                  ? "bg-gray-300 text-gray-900"
                  : index === 2
                    ? "bg-orange-400 text-orange-900"
                    : "bg-gray-100 text-gray-600"
        }`;
        rankBadge.textContent = index + 1;
        rankBadge.setAttribute("aria-label", `Rank ${index + 1}`);
        rankCell.appendChild(rankBadge);
        row.appendChild(rankCell);

        // Name (clickable for drill-down)
        const nameCell = document.createElement("td");
        nameCell.className =
            "px-6 py-4 whitespace-nowrap text-sm text-indigo-600 dark:text-indigo-400 cursor-pointer";
        nameCell.textContent = escapeHtml(item.name || "Unknown");
        // nameCell.onclick = () => showDetailedMetrics(entityType, item.id);
        nameCell.setAttribute("role", "button");
        nameCell.setAttribute(
            "aria-label",
            `View details for ${item.name || "Unknown"}`,
        );
        row.appendChild(nameCell);

        // Executions
        const execCell = document.createElement("td");
        execCell.className =
            "px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300 sm:px-6 sm:py-4";
        execCell.textContent = formatNumber(
            item.executionCount || item.execution_count || item.executions || 0,
        );
        row.appendChild(execCell);

        // Avg Response Time
        const avgTimeCell = document.createElement("td");
        avgTimeCell.className =
            "px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300 sm:px-6 sm:py-4";
        const avgTime = item.avg_response_time || item.avgResponseTime;
        avgTimeCell.textContent = avgTime ? `${Math.round(avgTime)}ms` : "N/A";
        row.appendChild(avgTimeCell);

        // Success Rate
        const successCell = document.createElement("td");
        successCell.className =
            "px-6 py-4 whitespace-nowrap text-sm sm:px-6 sm:py-4";
        const successRate = calculateSuccessRate(item);
        const successBadge = document.createElement("span");
        successBadge.className = `inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
            successRate >= 95
                ? "bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-100"
                : successRate >= 80
                  ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-800 dark:text-yellow-100"
                  : "bg-red-100 text-red-800 dark:bg-red-800 dark:text-red-100"
        }`;
        successBadge.textContent = `${successRate}%`;
        successBadge.setAttribute(
            "aria-label",
            `Success rate: ${successRate}%`,
        );
        successCell.appendChild(successBadge);
        row.appendChild(successCell);

        // Last Used
        const lastUsedCell = document.createElement("td");
        lastUsedCell.className =
            "px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300 sm:px-6 sm:py-4";
        lastUsedCell.textContent = formatLastUsed(
            item.last_execution || item.lastExecution,
        );
        row.appendChild(lastUsedCell);

        tbody.appendChild(row);
    });

    table.appendChild(tbody);
    tableWrapper.appendChild(table);
    panel.appendChild(tableWrapper);

    // Pagination controls (if needed)
    if (data.length > 5) {
        const pagination = createPaginationControls(data.length, 5, (page) => {
            updateTableRows(panel, entityType, data, page);
        });
        panel.appendChild(pagination);
    }

    return panel;
}

function createTab(type, isActive) {
    const tab = document.createElement("a");
    tab.href = "#";
    tab.id = `top-${type}-tab`;
    tab.className = `${
        isActive
            ? "border-indigo-500 text-indigo-600 dark:text-indigo-400"
            : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300"
    } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm capitalize transition-colors duration-200 sm:py-4 sm:px-1`;
    tab.textContent = type;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", `top-${type}-panel`);
    tab.setAttribute("aria-selected", isActive.toString());
    tab.onclick = (e) => {
        e.preventDefault();
        showTopPerformerTab(type);
    };
    return tab;
}

function showTopPerformerTab(activeType) {
    const entityTypes = [
        "tools",
        "resources",
        "prompts",
        "gateways",
        "servers",
    ];
    entityTypes.forEach((type) => {
        const panel = document.getElementById(`top-${type}-panel`);
        const tab = document.getElementById(`top-${type}-tab`);
        if (panel) {
            panel.classList.toggle("hidden", type !== activeType);
            panel.classList.toggle("opacity-100", type === activeType);
            panel.classList.toggle("opacity-0", type !== activeType);
            panel.setAttribute("aria-hidden", type !== activeType);
        }
        if (tab) {
            tab.classList.toggle("border-indigo-500", type === activeType);
            tab.classList.toggle("text-indigo-600", type === activeType);
            tab.classList.toggle("dark:text-indigo-400", type === activeType);
            tab.classList.toggle("border-transparent", type !== activeType);
            tab.classList.toggle("text-gray-500", type !== activeType);
            tab.setAttribute("aria-selected", type === activeType);
        }
    });
}

function createPaginationControls(totalItems, itemsPerPage, onPageChange) {
    const pagination = document.createElement("div");
    pagination.className = "mt-4 flex justify-end space-x-2";
    const totalPages = Math.ceil(totalItems / itemsPerPage);

    for (let page = 1; page <= totalPages; page++) {
        const button = document.createElement("button");
        button.className = `px-3 py-1 rounded ${page === 1 ? "bg-indigo-600 text-white" : "bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300"}`;
        button.textContent = page;
        button.onclick = () => {
            onPageChange(page);
            pagination.querySelectorAll("button").forEach((btn) => {
                btn.className = `px-3 py-1 rounded ${btn === button ? "bg-indigo-600 text-white" : "bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300"}`;
            });
        };
        pagination.appendChild(button);
    }

    return pagination;
}

function updateTableRows(panel, entityType, data, page) {
    const tbody = panel.querySelector("tbody");
    tbody.innerHTML = "";
    const start = (page - 1) * 5;
    const paginatedData = data.slice(start, start + 5);

    paginatedData.forEach((item, index) => {
        const row = document.createElement("tr");
        // ... (same row creation logic as in createTopPerformersTable)
        tbody.appendChild(row);
    });
}

function exportMetricsToCSV(topData) {
    const headers = [
        "Entity Type",
        "Rank",
        "Name",
        "Executions",
        "Avg Response Time",
        "Success Rate",
        "Last Used",
    ];
    const rows = [];

    ["tools", "resources", "prompts", "gateways", "servers"].forEach((type) => {
        if (topData[type] && Array.isArray(topData[type])) {
            topData[type].forEach((item, index) => {
                rows.push([
                    type,
                    index + 1,
                    `"${escapeHtml(item.name || "Unknown")}"`,
                    formatNumber(
                        item.executionCount ||
                            item.execution_count ||
                            item.executions ||
                            0,
                    ),
                    item.avg_response_time || item.avgResponseTime
                        ? `${Math.round(item.avg_response_time || item.avgResponseTime)}ms`
                        : "N/A",
                    `${calculateSuccessRate(item)}%`,
                    formatLastUsed(item.last_execution || item.lastExecution),
                ]);
            });
        }
    });

    const csv = [headers.join(","), ...rows.map((row) => row.join(","))].join(
        "\n",
    );
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `top_performers_${new Date().toISOString()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

/**
 * SECURITY: Create top item card with safe content handling
 */
// function createTopItemCard(title, items) {
//     try {
//         const card = document.createElement("div");
//         card.className = "bg-gray-50 rounded p-4 dark:bg-gray-700";

//         const cardTitle = document.createElement("h4");
//         cardTitle.className = "font-medium mb-2 dark:text-gray-200";
//         cardTitle.textContent = `Top ${title}`;
//         card.appendChild(cardTitle);

//         const list = document.createElement("ul");
//         list.className = "space-y-1";

//         items.slice(0, 5).forEach((item) => {
//             const listItem = document.createElement("li");
//             listItem.className =
//                 "text-sm text-gray-600 dark:text-gray-300 flex justify-between";

//             const nameSpan = document.createElement("span");
//             nameSpan.textContent = item.name || "Unknown";

//             const countSpan = document.createElement("span");
//             countSpan.className = "font-medium";
//             countSpan.textContent = String(item.executions || 0);

//             listItem.appendChild(nameSpan);
//             listItem.appendChild(countSpan);
//             list.appendChild(listItem);
//         });

//         card.appendChild(list);
//         return card;
//     } catch (error) {
//         console.error("Error creating top item card:", error);
//         return document.createElement("div"); // Safe fallback
//     }
// }

/**
 * SECURITY: Create performance metrics card with safe display
 */
function createPerformanceCard(performanceData) {
    try {
        const card = document.createElement("div");
        card.className = "bg-white rounded-lg shadow p-6 dark:bg-gray-800";

        const titleElement = document.createElement("h3");
        titleElement.className = "text-lg font-medium mb-4 dark:text-gray-200";
        titleElement.textContent = "Performance Metrics";
        card.appendChild(titleElement);

        const metricsList = document.createElement("div");
        metricsList.className = "space-y-2";

        // Define performance metrics with safe structure
        const performanceMetrics = [
            { key: "memoryUsage", label: "Memory Usage" },
            { key: "cpuUsage", label: "CPU Usage" },
            { key: "diskIo", label: "Disk I/O" },
            { key: "networkThroughput", label: "Network Throughput" },
            { key: "cacheHitRate", label: "Cache Hit Rate" },
            { key: "activeThreads", label: "Active Threads" },
        ];

        performanceMetrics.forEach((metric) => {
            const value =
                performanceData[metric.key] ??
                performanceData[
                    metric.key.replace(/([A-Z])/g, "_$1").toLowerCase()
                ] ??
                "N/A";

            const metricRow = document.createElement("div");
            metricRow.className = "flex justify-between";

            const label = document.createElement("span");
            label.className = "text-gray-600 dark:text-gray-400";
            label.textContent = metric.label + ":";

            const valueSpan = document.createElement("span");
            valueSpan.className = "font-medium dark:text-gray-200";
            valueSpan.textContent = value === "N/A" ? "N/A" : String(value);

            metricRow.appendChild(label);
            metricRow.appendChild(valueSpan);
            metricsList.appendChild(metricRow);
        });

        card.appendChild(metricsList);
        return card;
    } catch (error) {
        console.error("Error creating performance card:", error);
        return document.createElement("div"); // Safe fallback
    }
}

/**
 * SECURITY: Create recent activity section with safe content handling
 */
function createRecentActivitySection(activityData) {
    try {
        const section = document.createElement("div");
        section.className = "bg-white rounded-lg shadow p-6 dark:bg-gray-800";

        const title = document.createElement("h3");
        title.className = "text-lg font-medium mb-4 dark:text-gray-200";
        title.textContent = "Recent Activity";
        section.appendChild(title);

        if (Array.isArray(activityData) && activityData.length > 0) {
            const activityList = document.createElement("div");
            activityList.className = "space-y-3 max-h-64 overflow-y-auto";

            // Display up to 10 recent activities safely
            activityData.slice(0, 10).forEach((activity) => {
                const activityItem = document.createElement("div");
                activityItem.className =
                    "flex items-center justify-between p-2 bg-gray-50 rounded dark:bg-gray-700";

                const leftSide = document.createElement("div");

                const actionSpan = document.createElement("span");
                actionSpan.className = "font-medium dark:text-gray-200";
                actionSpan.textContent = escapeHtml(
                    activity.action || "Unknown Action",
                );

                const targetSpan = document.createElement("span");
                targetSpan.className =
                    "text-sm text-gray-500 dark:text-gray-400 ml-2";
                targetSpan.textContent = escapeHtml(activity.target || "");

                leftSide.appendChild(actionSpan);
                leftSide.appendChild(targetSpan);

                const rightSide = document.createElement("div");
                rightSide.className = "text-xs text-gray-400";
                rightSide.textContent = escapeHtml(activity.timestamp || "");

                activityItem.appendChild(leftSide);
                activityItem.appendChild(rightSide);
                activityList.appendChild(activityItem);
            });

            section.appendChild(activityList);
        } else {
            const noActivity = document.createElement("p");
            noActivity.className =
                "text-gray-500 dark:text-gray-400 text-center py-4";
            noActivity.textContent = "No recent activity to display";
            section.appendChild(noActivity);
        }

        return section;
    } catch (error) {
        console.error("Error creating recent activity section:", error);
        return document.createElement("div"); // Safe fallback
    }
}

function createMetricsCard(title, metrics) {
    const card = document.createElement("div");
    card.className = "bg-white rounded-lg shadow p-6 dark:bg-gray-800";

    const titleElement = document.createElement("h3");
    titleElement.className = "text-lg font-medium mb-4 dark:text-gray-200";
    titleElement.textContent = `${title} Metrics`;
    card.appendChild(titleElement);

    const metricsList = document.createElement("div");
    metricsList.className = "space-y-2";

    const metricsToShow = [
        { key: "totalExecutions", label: "Total Executions" },
        { key: "successfulExecutions", label: "Successful Executions" },
        { key: "failedExecutions", label: "Failed Executions" },
        { key: "failureRate", label: "Failure Rate" },
        { key: "avgResponseTime", label: "Average Response Time" },
        { key: "lastExecutionTime", label: "Last Execution Time" },
    ];

    metricsToShow.forEach((metric) => {
        const value =
            metrics[metric.key] ??
            metrics[metric.key.replace(/([A-Z])/g, "_$1").toLowerCase()] ??
            "N/A";

        const metricRow = document.createElement("div");
        metricRow.className = "flex justify-between";

        const label = document.createElement("span");
        label.className = "text-gray-600 dark:text-gray-400";
        label.textContent = metric.label + ":";

        const valueSpan = document.createElement("span");
        valueSpan.className = "font-medium dark:text-gray-200";
        valueSpan.textContent = value === "N/A" ? "N/A" : String(value);

        metricRow.appendChild(label);
        metricRow.appendChild(valueSpan);
        metricsList.appendChild(metricRow);
    });

    card.appendChild(metricsList);
    return card;
}

// ===================================================================
// SECURE CRUD OPERATIONS with Input Validation
// ===================================================================

/**
 * SECURE: Edit Tool function with input validation
 */
async function editTool(toolId) {
    try {
        console.log(`Editing tool ID: ${toolId}`);

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/tools/${toolId}`,
        );
        if (!response.ok) {
            // If the response is not OK, throw an error
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const tool = await response.json();
        const isInactiveCheckedBool = isInactiveChecked("tools");
        let hiddenField = safeGetElement("edit-show-inactive");
        if (!hiddenField) {
            hiddenField = document.createElement("input");
            hiddenField.type = "hidden";
            hiddenField.name = "is_inactive_checked";
            hiddenField.id = "edit-show-inactive";
            const editForm = safeGetElement("edit-tool-form");
            if (editForm) {
                editForm.appendChild(hiddenField);
            }
        }
        hiddenField.value = isInactiveCheckedBool;

        // Set form action and populate basic fields with validation
        const editForm = safeGetElement("edit-tool-form");
        if (editForm) {
            editForm.action = `${window.ROOT_PATH}/admin/tools/${toolId}/edit`;
        }

        // Validate and set fields
        const nameValidation = validateInputName(tool.name, "tool");
        const customNameValidation = validateInputName(tool.customName, "tool");

        const urlValidation = validateUrl(tool.url);

        const nameField = safeGetElement("edit-tool-name");
        const customNameField = safeGetElement("edit-tool-custom-name");
        const urlField = safeGetElement("edit-tool-url");
        const descField = safeGetElement("edit-tool-description");
        const typeField = safeGetElement("edit-tool-type");

        if (nameField && nameValidation.valid) {
            nameField.value = nameValidation.value;
        }
        if (customNameField && customNameValidation.valid) {
            customNameField.value = customNameValidation.value;
        }

        const displayNameField = safeGetElement("edit-tool-display-name");
        if (displayNameField) {
            displayNameField.value = tool.displayName || "";
        }
        if (urlField && urlValidation.valid) {
            urlField.value = urlValidation.value;
        }
        if (descField) {
            descField.value = tool.description || "";
        }
        if (typeField) {
            typeField.value = tool.integrationType || "MCP";
        }

        // Set tags field
        const tagsField = safeGetElement("edit-tool-tags");
        if (tagsField) {
            tagsField.value = tool.tags ? tool.tags.join(", ") : "";
        }

        const teamId = new URL(window.location.href).searchParams.get(
            "team_id",
        );

        if (teamId) {
            const hiddenInput = document.createElement("input");
            hiddenInput.type = "hidden";
            hiddenInput.name = "team_id";
            hiddenInput.value = teamId;
            editForm.appendChild(hiddenInput);
        }

        const visibility = tool.visibility; // Ensure visibility is either 'public', 'team', or 'private'
        const publicRadio = safeGetElement("edit-tool-visibility-public");
        const teamRadio = safeGetElement("edit-tool-visibility-team");
        const privateRadio = safeGetElement("edit-tool-visibility-private");

        if (visibility) {
            // Check visibility and set the corresponding radio button
            if (visibility === "public" && publicRadio) {
                publicRadio.checked = true;
            } else if (visibility === "team" && teamRadio) {
                teamRadio.checked = true;
            } else if (visibility === "private" && privateRadio) {
                privateRadio.checked = true;
            }
        }

        // Handle JSON fields safely with validation
        const headersValidation = validateJson(
            JSON.stringify(tool.headers || {}),
            "Headers",
        );
        const schemaValidation = validateJson(
            JSON.stringify(tool.inputSchema || {}),
            "Schema",
        );
        const annotationsValidation = validateJson(
            JSON.stringify(tool.annotations || {}),
            "Annotations",
        );

        const headersField = safeGetElement("edit-tool-headers");
        const schemaField = safeGetElement("edit-tool-schema");
        const annotationsField = safeGetElement("edit-tool-annotations");

        if (headersField && headersValidation.valid) {
            headersField.value = JSON.stringify(
                headersValidation.value,
                null,
                2,
            );
        }
        if (schemaField && schemaValidation.valid) {
            schemaField.value = JSON.stringify(schemaValidation.value, null, 2);
        }
        if (annotationsField && annotationsValidation.valid) {
            annotationsField.value = JSON.stringify(
                annotationsValidation.value,
                null,
                2,
            );
        }

        // Update CodeMirror editors if they exist
        if (window.editToolHeadersEditor && headersValidation.valid) {
            window.editToolHeadersEditor.setValue(
                JSON.stringify(headersValidation.value, null, 2),
            );
            window.editToolHeadersEditor.refresh();
        }
        if (window.editToolSchemaEditor && schemaValidation.valid) {
            window.editToolSchemaEditor.setValue(
                JSON.stringify(schemaValidation.value, null, 2),
            );
            window.editToolSchemaEditor.refresh();
        }

        // Prefill integration type from DB and set request types accordingly
        if (typeField) {
            typeField.value = tool.integrationType || "REST";
            // Disable integration type field for MCP tools (cannot be changed)
            if (tool.integrationType === "MCP") {
                typeField.disabled = true;
            } else {
                typeField.disabled = false;
            }
            updateEditToolRequestTypes(tool.requestType || null); // preselect from DB
            updateEditToolUrl(tool.url || null);
        }

        // Request Type field handling (disable for MCP)
        const requestTypeField = safeGetElement("edit-tool-request-type");
        if (requestTypeField) {
            if ((tool.integrationType || "REST") === "MCP") {
                requestTypeField.value = "";
                requestTypeField.disabled = true; // disabled -> not submitted
            } else {
                requestTypeField.disabled = false;
                requestTypeField.value = tool.requestType || ""; // keep DB verb or blank
            }
        }

        // Set auth type field
        const authTypeField = safeGetElement("edit-auth-type");
        if (authTypeField) {
            authTypeField.value = tool.auth?.authType || "";
        }
        const editAuthTokenField = safeGetElement("edit-auth-token");
        // Prefill integration type from DB and set request types accordingly
        if (typeField) {
            // Always set value from DB, never from previous UI state
            typeField.value = tool.integrationType;
            // Remove any previous hidden field for type
            const prevHiddenType = document.getElementById(
                "hidden-edit-tool-type",
            );
            if (prevHiddenType) {
                prevHiddenType.remove();
            }
            // Remove any previous hidden field for authType
            const prevHiddenAuthType = document.getElementById(
                "hidden-edit-auth-type",
            );
            if (prevHiddenAuthType) {
                prevHiddenAuthType.remove();
            }
            // Disable integration type field for MCP tools (cannot be changed)
            if (tool.integrationType === "MCP") {
                typeField.disabled = true;
                if (authTypeField) {
                    authTypeField.disabled = true;
                    // Add hidden field for authType
                    const hiddenAuthTypeField = document.createElement("input");
                    hiddenAuthTypeField.type = "hidden";
                    hiddenAuthTypeField.name = authTypeField.name;
                    hiddenAuthTypeField.value = authTypeField.value;
                    hiddenAuthTypeField.id = "hidden-edit-auth-type";
                    authTypeField.form.appendChild(hiddenAuthTypeField);
                }
                if (urlField) {
                    urlField.readOnly = true;
                }
                if (headersField) {
                    headersField.setAttribute("readonly", "readonly");
                }
                if (schemaField) {
                    schemaField.setAttribute("readonly", "readonly");
                }
                if (editAuthTokenField) {
                    editAuthTokenField.setAttribute("readonly", "readonly");
                }
                if (window.editToolHeadersEditor) {
                    window.editToolHeadersEditor.setOption("readOnly", true);
                }
                if (window.editToolSchemaEditor) {
                    window.editToolSchemaEditor.setOption("readOnly", true);
                }
            } else {
                typeField.disabled = false;
                if (authTypeField) {
                    authTypeField.disabled = false;
                }
                if (urlField) {
                    urlField.readOnly = false;
                }
                if (headersField) {
                    headersField.removeAttribute("readonly");
                }
                if (schemaField) {
                    schemaField.removeAttribute("readonly");
                }
                if (editAuthTokenField) {
                    editAuthTokenField.removeAttribute("readonly");
                }
                if (window.editToolHeadersEditor) {
                    window.editToolHeadersEditor.setOption("readOnly", false);
                }
                if (window.editToolSchemaEditor) {
                    window.editToolSchemaEditor.setOption("readOnly", false);
                }
            }
            // Update request types and URL field
            updateEditToolRequestTypes(tool.requestType || null);
            updateEditToolUrl(tool.url || null);
        }

        // Auth containers
        const authBasicSection = safeGetElement("edit-auth-basic-fields");
        const authBearerSection = safeGetElement("edit-auth-bearer-fields");
        const authHeadersSection = safeGetElement("edit-auth-headers-fields");

        // Individual fields
        const authUsernameField = authBasicSection?.querySelector(
            "input[name='auth_username']",
        );
        const authPasswordField = authBasicSection?.querySelector(
            "input[name='auth_password']",
        );

        const authTokenField = authBearerSection?.querySelector(
            "input[name='auth_token']",
        );

        const authHeaderKeyField = authHeadersSection?.querySelector(
            "input[name='auth_header_key']",
        );
        const authHeaderValueField = authHeadersSection?.querySelector(
            "input[name='auth_header_value']",
        );

        // Hide all auth sections first
        if (authBasicSection) {
            authBasicSection.style.display = "none";
        }
        if (authBearerSection) {
            authBearerSection.style.display = "none";
        }
        if (authHeadersSection) {
            authHeadersSection.style.display = "none";
        }

        // Clear old values
        if (authUsernameField) {
            authUsernameField.value = "";
        }
        if (authPasswordField) {
            authPasswordField.value = "";
        }
        if (authTokenField) {
            authTokenField.value = "";
        }
        if (authHeaderKeyField) {
            authHeaderKeyField.value = "";
        }
        if (authHeaderValueField) {
            authHeaderValueField.value = "";
        }

        // Display appropriate auth section and populate values
        switch (tool.auth?.authType) {
            case "basic":
                if (authBasicSection) {
                    authBasicSection.style.display = "block";
                    if (authUsernameField) {
                        authUsernameField.value = tool.auth.username || "";
                    }
                    if (authPasswordField) {
                        authPasswordField.value = "*****"; // masked
                    }
                }
                break;

            case "bearer":
                if (authBearerSection) {
                    authBearerSection.style.display = "block";
                    if (authTokenField) {
                        authTokenField.value = "*****"; // masked
                    }
                }
                break;

            case "authheaders":
                if (authHeadersSection) {
                    authHeadersSection.style.display = "block";
                    if (authHeaderKeyField) {
                        authHeaderKeyField.value =
                            tool.auth.authHeaderKey || "";
                    }
                    if (authHeaderValueField) {
                        authHeaderValueField.value = "*****"; // masked
                    }
                }
                break;

            case "":
            default:
                // No auth – keep everything hidden
                break;
        }

        openModal("tool-edit-modal");

        // Ensure editors are refreshed after modal display
        setTimeout(() => {
            if (window.editToolHeadersEditor) {
                window.editToolHeadersEditor.refresh();
            }
            if (window.editToolSchemaEditor) {
                window.editToolSchemaEditor.refresh();
            }
        }, 100);

        console.log("✓ Tool edit modal loaded successfully");
    } catch (error) {
        console.error("Error fetching tool details for editing:", error);
        const errorMessage = handleFetchError(error, "load tool for editing");
        showErrorMessage(errorMessage);
    }
}

/**
 * SECURE: View Resource function with safe display
 */
async function viewResource(resourceUri) {
    try {
        console.log(`Viewing resource: ${resourceUri}`);

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/resources/${encodeURIComponent(resourceUri)}`,
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        const resource = data.resource;
        const content = data.content;

        const resourceDetailsDiv = safeGetElement("resource-details");
        if (resourceDetailsDiv) {
            // Create safe display elements
            const container = document.createElement("div");
            container.className =
                "space-y-2 dark:bg-gray-900 dark:text-gray-100";

            // Add each piece of information safely
            const fields = [
                { label: "URI", value: resource.uri },
                { label: "Name", value: resource.name },
                { label: "Type", value: resource.mimeType || "N/A" },
                { label: "Description", value: resource.description || "N/A" },
            ];

            fields.forEach((field) => {
                const p = document.createElement("p");
                const strong = document.createElement("strong");
                strong.textContent = field.label + ": ";
                p.appendChild(strong);
                p.appendChild(document.createTextNode(field.value));
                container.appendChild(p);
            });

            // Tags section
            const tagsP = document.createElement("p");
            const tagsStrong = document.createElement("strong");
            tagsStrong.textContent = "Tags: ";
            tagsP.appendChild(tagsStrong);

            if (resource.tags && resource.tags.length > 0) {
                resource.tags.forEach((tag) => {
                    const tagSpan = document.createElement("span");
                    tagSpan.className =
                        "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full mr-1 mb-1 dark:bg-blue-900 dark:text-blue-200";
                    tagSpan.textContent = tag;
                    tagsP.appendChild(tagSpan);
                });
            } else {
                tagsP.appendChild(document.createTextNode("None"));
            }
            container.appendChild(tagsP);

            // Status with safe styling
            const statusP = document.createElement("p");
            const statusStrong = document.createElement("strong");
            statusStrong.textContent = "Status: ";
            statusP.appendChild(statusStrong);

            const statusSpan = document.createElement("span");
            statusSpan.className = `px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                resource.isActive
                    ? "bg-green-100 text-green-800"
                    : "bg-red-100 text-red-800"
            }`;
            statusSpan.textContent = resource.isActive ? "Active" : "Inactive";
            statusP.appendChild(statusSpan);
            container.appendChild(statusP);

            // Content display - safely handle different types
            const contentDiv = document.createElement("div");
            const contentStrong = document.createElement("strong");
            contentStrong.textContent = "Content:";
            contentDiv.appendChild(contentStrong);

            const contentPre = document.createElement("pre");
            contentPre.className =
                "mt-1 bg-gray-100 p-2 rounded overflow-auto max-h-80 dark:bg-gray-800 dark:text-gray-100";

            // Handle content display - extract actual content from object if needed
            let contentStr = extractContent(
                content,
                resource.description || "No content available",
            );

            if (!contentStr.trim()) {
                contentStr = resource.description || "No content available";
            }

            contentPre.textContent = contentStr;
            contentDiv.appendChild(contentPre);
            container.appendChild(contentDiv);

            // Metrics display
            if (resource.metrics) {
                const metricsDiv = document.createElement("div");
                const metricsStrong = document.createElement("strong");
                metricsStrong.textContent = "Metrics:";
                metricsDiv.appendChild(metricsStrong);

                const metricsList = document.createElement("ul");
                metricsList.className = "list-disc list-inside ml-4";

                const metricsData = [
                    {
                        label: "Total Executions",
                        value: resource.metrics.totalExecutions ?? 0,
                    },
                    {
                        label: "Successful Executions",
                        value: resource.metrics.successfulExecutions ?? 0,
                    },
                    {
                        label: "Failed Executions",
                        value: resource.metrics.failedExecutions ?? 0,
                    },
                    {
                        label: "Failure Rate",
                        value: resource.metrics.failureRate ?? 0,
                    },
                    {
                        label: "Min Response Time",
                        value: resource.metrics.minResponseTime ?? "N/A",
                    },
                    {
                        label: "Max Response Time",
                        value: resource.metrics.maxResponseTime ?? "N/A",
                    },
                    {
                        label: "Average Response Time",
                        value: resource.metrics.avgResponseTime ?? "N/A",
                    },
                    {
                        label: "Last Execution Time",
                        value: resource.metrics.lastExecutionTime ?? "N/A",
                    },
                ];

                metricsData.forEach((metric) => {
                    const li = document.createElement("li");
                    li.textContent = `${metric.label}: ${metric.value}`;
                    metricsList.appendChild(li);
                });

                metricsDiv.appendChild(metricsList);
                container.appendChild(metricsDiv);
            }

            // Add metadata section
            const metadataDiv = document.createElement("div");
            metadataDiv.className = "mt-6 border-t pt-4";

            const metadataTitle = document.createElement("strong");
            metadataTitle.textContent = "Metadata:";
            metadataDiv.appendChild(metadataTitle);

            const metadataGrid = document.createElement("div");
            metadataGrid.className = "grid grid-cols-2 gap-4 mt-2 text-sm";

            const metadataFields = [
                {
                    label: "Created By",
                    value:
                        resource.created_by ||
                        resource.createdBy ||
                        "Legacy Entity",
                },
                {
                    label: "Created At",
                    value:
                        resource.created_at || resource.createdAt
                            ? new Date(
                                  resource.created_at || resource.createdAt,
                              ).toLocaleString()
                            : "Pre-metadata",
                },
                {
                    label: "Created From",
                    value:
                        resource.created_from_ip ||
                        resource.createdFromIp ||
                        "Unknown",
                },
                {
                    label: "Created Via",
                    value:
                        resource.created_via ||
                        resource.createdVia ||
                        "Unknown",
                },
                {
                    label: "Last Modified By",
                    value: resource.modified_by || resource.modifiedBy || "N/A",
                },
                {
                    label: "Last Modified At",
                    value:
                        resource.updated_at || resource.updatedAt
                            ? new Date(
                                  resource.updated_at || resource.updatedAt,
                              ).toLocaleString()
                            : "N/A",
                },
                {
                    label: "Modified From",
                    value:
                        resource.modified_from_ip ||
                        resource.modifiedFromIp ||
                        "N/A",
                },
                {
                    label: "Modified Via",
                    value:
                        resource.modified_via || resource.modifiedVia || "N/A",
                },
                {
                    label: "Version",
                    value: resource.version || "1",
                },
                {
                    label: "Import Batch",
                    value:
                        resource.import_batch_id ||
                        resource.importBatchId ||
                        "N/A",
                },
            ];

            metadataFields.forEach((field) => {
                const fieldDiv = document.createElement("div");

                const labelSpan = document.createElement("span");
                labelSpan.className =
                    "font-medium text-gray-600 dark:text-gray-400";
                labelSpan.textContent = field.label + ":";

                const valueSpan = document.createElement("span");
                valueSpan.className = "ml-2";
                valueSpan.textContent = field.value;

                fieldDiv.appendChild(labelSpan);
                fieldDiv.appendChild(valueSpan);
                metadataGrid.appendChild(fieldDiv);
            });

            metadataDiv.appendChild(metadataGrid);
            container.appendChild(metadataDiv);

            // Replace content safely
            resourceDetailsDiv.innerHTML = "";
            resourceDetailsDiv.appendChild(container);
        }

        openModal("resource-modal");
        console.log("✓ Resource details loaded successfully");
    } catch (error) {
        console.error("Error fetching resource details:", error);
        const errorMessage = handleFetchError(error, "load resource details");
        showErrorMessage(errorMessage);
    }
}

/**
 * SECURE: Edit Resource function with validation
 */
async function editResource(resourceUri) {
    try {
        console.log(`Editing resource: ${resourceUri}`);

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/resources/${encodeURIComponent(resourceUri)}`,
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        const resource = data.resource;
        const content = data.content;
        const isInactiveCheckedBool = isInactiveChecked("resources");
        let hiddenField = safeGetElement("edit-resource-show-inactive");
        if (!hiddenField) {
            hiddenField = document.createElement("input");
            hiddenField.type = "hidden";
            hiddenField.name = "is_inactive_checked";
            hiddenField.id = "edit-resource-show-inactive";
            const editForm = safeGetElement("edit-resource-form");
            if (editForm) {
                editForm.appendChild(hiddenField);
            }
        }
        hiddenField.value = isInactiveCheckedBool;

        // Set form action and populate fields with validation
        const editForm = safeGetElement("edit-resource-form");
        if (editForm) {
            editForm.action = `${window.ROOT_PATH}/admin/resources/${encodeURIComponent(resourceUri)}/edit`;
        }

        // Validate inputs
        const nameValidation = validateInputName(resource.name, "resource");
        const uriValidation = validateInputName(resource.uri, "resource URI");

        const uriField = safeGetElement("edit-resource-uri");
        const nameField = safeGetElement("edit-resource-name");
        const descField = safeGetElement("edit-resource-description");
        const mimeField = safeGetElement("edit-resource-mime-type");
        const contentField = safeGetElement("edit-resource-content");

        if (uriField && uriValidation.valid) {
            uriField.value = uriValidation.value;
        }
        if (nameField && nameValidation.valid) {
            nameField.value = nameValidation.value;
        }
        if (descField) {
            descField.value = resource.description || "";
        }
        if (mimeField) {
            mimeField.value = resource.mimeType || "";
        }

        // Set tags field
        const tagsField = safeGetElement("edit-resource-tags");
        if (tagsField) {
            tagsField.value = resource.tags ? resource.tags.join(", ") : "";
        }

        if (contentField) {
            let contentStr = extractContent(
                content,
                resource.description || "No content available",
            );

            if (!contentStr.trim()) {
                contentStr = resource.description || "No content available";
            }

            contentField.value = contentStr;
        }

        // Update CodeMirror editor if it exists
        if (window.editResourceContentEditor) {
            let contentStr = extractContent(
                content,
                resource.description || "No content available",
            );

            if (!contentStr.trim()) {
                contentStr = resource.description || "No content available";
            }

            window.editResourceContentEditor.setValue(contentStr);
            window.editResourceContentEditor.refresh();
        }

        openModal("resource-edit-modal");

        // Refresh editor after modal display
        setTimeout(() => {
            if (window.editResourceContentEditor) {
                window.editResourceContentEditor.refresh();
            }
        }, 100);

        console.log("✓ Resource edit modal loaded successfully");
    } catch (error) {
        console.error("Error fetching resource for editing:", error);
        const errorMessage = handleFetchError(
            error,
            "load resource for editing",
        );
        showErrorMessage(errorMessage);
    }
}

/**
 * SECURE: View Prompt function with safe display
 */
async function viewPrompt(promptName) {
    try {
        console.log(`Viewing prompt: ${promptName}`);

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/prompts/${encodeURIComponent(promptName)}`,
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const prompt = await response.json();

        const promptDetailsDiv = safeGetElement("prompt-details");
        if (promptDetailsDiv) {
            // Create safe display container
            const container = document.createElement("div");
            container.className =
                "space-y-2 dark:bg-gray-900 dark:text-gray-100";

            // Basic info fields
            const fields = [
                { label: "Name", value: prompt.name },
                { label: "Description", value: prompt.description || "N/A" },
            ];

            fields.forEach((field) => {
                const p = document.createElement("p");
                const strong = document.createElement("strong");
                strong.textContent = field.label + ": ";
                p.appendChild(strong);
                p.appendChild(document.createTextNode(field.value));
                container.appendChild(p);
            });

            // Tags section
            const tagsP = document.createElement("p");
            const tagsStrong = document.createElement("strong");
            tagsStrong.textContent = "Tags: ";
            tagsP.appendChild(tagsStrong);

            if (prompt.tags && prompt.tags.length > 0) {
                prompt.tags.forEach((tag) => {
                    const tagSpan = document.createElement("span");
                    tagSpan.className =
                        "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full mr-1 mb-1 dark:bg-blue-900 dark:text-blue-200";
                    tagSpan.textContent = tag;
                    tagsP.appendChild(tagSpan);
                });
            } else {
                tagsP.appendChild(document.createTextNode("None"));
            }
            container.appendChild(tagsP);

            // Status
            const statusP = document.createElement("p");
            const statusStrong = document.createElement("strong");
            statusStrong.textContent = "Status: ";
            statusP.appendChild(statusStrong);

            const statusSpan = document.createElement("span");
            statusSpan.className = `px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                prompt.isActive
                    ? "bg-green-100 text-green-800"
                    : "bg-red-100 text-red-800"
            }`;
            statusSpan.textContent = prompt.isActive ? "Active" : "Inactive";
            statusP.appendChild(statusSpan);
            container.appendChild(statusP);

            // Template display
            const templateDiv = document.createElement("div");
            const templateStrong = document.createElement("strong");
            templateStrong.textContent = "Template:";
            templateDiv.appendChild(templateStrong);

            const templatePre = document.createElement("pre");
            templatePre.className =
                "mt-1 bg-gray-100 p-2 rounded overflow-auto max-h-80 dark:bg-gray-800 dark:text-gray-100";
            templatePre.textContent = prompt.template || "";
            templateDiv.appendChild(templatePre);
            container.appendChild(templateDiv);

            // Arguments display
            const argsDiv = document.createElement("div");
            const argsStrong = document.createElement("strong");
            argsStrong.textContent = "Arguments:";
            argsDiv.appendChild(argsStrong);

            const argsPre = document.createElement("pre");
            argsPre.className =
                "mt-1 bg-gray-100 p-2 rounded dark:bg-gray-800 dark:text-gray-100";
            argsPre.textContent = JSON.stringify(
                prompt.arguments || {},
                null,
                2,
            );
            argsDiv.appendChild(argsPre);
            container.appendChild(argsDiv);

            // Metrics
            if (prompt.metrics) {
                const metricsDiv = document.createElement("div");
                const metricsStrong = document.createElement("strong");
                metricsStrong.textContent = "Metrics:";
                metricsDiv.appendChild(metricsStrong);

                const metricsList = document.createElement("ul");
                metricsList.className = "list-disc list-inside ml-4";

                const metricsData = [
                    {
                        label: "Total Executions",
                        value: prompt.metrics.totalExecutions ?? 0,
                    },
                    {
                        label: "Successful Executions",
                        value: prompt.metrics.successfulExecutions ?? 0,
                    },
                    {
                        label: "Failed Executions",
                        value: prompt.metrics.failedExecutions ?? 0,
                    },
                    {
                        label: "Failure Rate",
                        value: prompt.metrics.failureRate ?? 0,
                    },
                    {
                        label: "Min Response Time",
                        value: prompt.metrics.minResponseTime ?? "N/A",
                    },
                    {
                        label: "Max Response Time",
                        value: prompt.metrics.maxResponseTime ?? "N/A",
                    },
                    {
                        label: "Average Response Time",
                        value: prompt.metrics.avgResponseTime ?? "N/A",
                    },
                    {
                        label: "Last Execution Time",
                        value: prompt.metrics.lastExecutionTime ?? "N/A",
                    },
                ];

                metricsData.forEach((metric) => {
                    const li = document.createElement("li");
                    li.textContent = `${metric.label}: ${metric.value}`;
                    metricsList.appendChild(li);
                });

                metricsDiv.appendChild(metricsList);
                container.appendChild(metricsDiv);
            }

            // Add metadata section
            const metadataDiv = document.createElement("div");
            metadataDiv.className = "mt-6 border-t pt-4";

            const metadataTitle = document.createElement("strong");
            metadataTitle.textContent = "Metadata:";
            metadataDiv.appendChild(metadataTitle);

            const metadataGrid = document.createElement("div");
            metadataGrid.className = "grid grid-cols-2 gap-4 mt-2 text-sm";

            const metadataFields = [
                {
                    label: "Created By",
                    value:
                        prompt.created_by ||
                        prompt.createdBy ||
                        "Legacy Entity",
                },
                {
                    label: "Created At",
                    value:
                        prompt.created_at || prompt.createdAt
                            ? new Date(
                                  prompt.created_at || prompt.createdAt,
                              ).toLocaleString()
                            : "Pre-metadata",
                },
                {
                    label: "Created From",
                    value:
                        prompt.created_from_ip ||
                        prompt.createdFromIp ||
                        "Unknown",
                },
                {
                    label: "Created Via",
                    value: prompt.created_via || prompt.createdVia || "Unknown",
                },
                {
                    label: "Last Modified By",
                    value: prompt.modified_by || prompt.modifiedBy || "N/A",
                },
                {
                    label: "Last Modified At",
                    value:
                        prompt.updated_at || prompt.updatedAt
                            ? new Date(
                                  prompt.updated_at || prompt.updatedAt,
                              ).toLocaleString()
                            : "N/A",
                },
                {
                    label: "Modified From",
                    value:
                        prompt.modified_from_ip ||
                        prompt.modifiedFromIp ||
                        "N/A",
                },
                {
                    label: "Modified Via",
                    value: prompt.modified_via || prompt.modifiedVia || "N/A",
                },
                { label: "Version", value: prompt.version || "1" },
                { label: "Import Batch", value: prompt.importBatchId || "N/A" },
            ];

            metadataFields.forEach((field) => {
                const fieldDiv = document.createElement("div");

                const labelSpan = document.createElement("span");
                labelSpan.className =
                    "font-medium text-gray-600 dark:text-gray-400";
                labelSpan.textContent = field.label + ":";

                const valueSpan = document.createElement("span");
                valueSpan.className = "ml-2";
                valueSpan.textContent = field.value;

                fieldDiv.appendChild(labelSpan);
                fieldDiv.appendChild(valueSpan);
                metadataGrid.appendChild(fieldDiv);
            });

            metadataDiv.appendChild(metadataGrid);
            container.appendChild(metadataDiv);

            // Replace content safely
            promptDetailsDiv.innerHTML = "";
            promptDetailsDiv.appendChild(container);
        }

        openModal("prompt-modal");
        console.log("✓ Prompt details loaded successfully");
    } catch (error) {
        console.error("Error fetching prompt details:", error);
        const errorMessage = handleFetchError(error, "load prompt details");
        showErrorMessage(errorMessage);
    }
}

/**
 * SECURE: Edit Prompt function with validation
 */
async function editPrompt(promptName) {
    try {
        console.log(`Editing prompt: ${promptName}`);

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/prompts/${encodeURIComponent(promptName)}`,
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const prompt = await response.json();

        const isInactiveCheckedBool = isInactiveChecked("prompts");
        let hiddenField = safeGetElement("edit-prompt-show-inactive");
        if (!hiddenField) {
            hiddenField = document.createElement("input");
            hiddenField.type = "hidden";
            hiddenField.name = "is_inactive_checked";
            hiddenField.id = "edit-prompt-show-inactive";
            const editForm = safeGetElement("edit-prompt-form");
            if (editForm) {
                editForm.appendChild(hiddenField);
            }
        }
        hiddenField.value = isInactiveCheckedBool;

        // Set form action and populate fields with validation
        const editForm = safeGetElement("edit-prompt-form");
        if (editForm) {
            editForm.action = `${window.ROOT_PATH}/admin/prompts/${encodeURIComponent(promptName)}/edit`;
        }

        // Validate prompt name
        const nameValidation = validateInputName(prompt.name, "prompt");

        const nameField = safeGetElement("edit-prompt-name");
        const descField = safeGetElement("edit-prompt-description");
        const templateField = safeGetElement("edit-prompt-template");
        const argsField = safeGetElement("edit-prompt-arguments");

        if (nameField && nameValidation.valid) {
            nameField.value = nameValidation.value;
        }
        if (descField) {
            descField.value = prompt.description || "";
        }

        // Set tags field
        const tagsField = safeGetElement("edit-prompt-tags");
        if (tagsField) {
            tagsField.value = prompt.tags ? prompt.tags.join(", ") : "";
        }

        if (templateField) {
            templateField.value = prompt.template || "";
        }

        // Validate arguments JSON
        const argsValidation = validateJson(
            JSON.stringify(prompt.arguments || {}),
            "Arguments",
        );
        if (argsField && argsValidation.valid) {
            argsField.value = JSON.stringify(argsValidation.value, null, 2);
        }

        // Update CodeMirror editors if they exist
        if (window.editPromptTemplateEditor) {
            window.editPromptTemplateEditor.setValue(prompt.template || "");
            window.editPromptTemplateEditor.refresh();
        }
        if (window.editPromptArgumentsEditor && argsValidation.valid) {
            window.editPromptArgumentsEditor.setValue(
                JSON.stringify(argsValidation.value, null, 2),
            );
            window.editPromptArgumentsEditor.refresh();
        }

        openModal("prompt-edit-modal");

        // Refresh editors after modal display
        setTimeout(() => {
            if (window.editPromptTemplateEditor) {
                window.editPromptTemplateEditor.refresh();
            }
            if (window.editPromptArgumentsEditor) {
                window.editPromptArgumentsEditor.refresh();
            }
        }, 100);

        console.log("✓ Prompt edit modal loaded successfully");
    } catch (error) {
        console.error("Error fetching prompt for editing:", error);
        const errorMessage = handleFetchError(error, "load prompt for editing");
        showErrorMessage(errorMessage);
    }
}

/**
 * SECURE: View Gateway function
 */
async function viewGateway(gatewayId) {
    try {
        console.log(`Viewing gateway ID: ${gatewayId}`);

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/gateways/${gatewayId}`,
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const gateway = await response.json();

        const gatewayDetailsDiv = safeGetElement("gateway-details");
        if (gatewayDetailsDiv) {
            const container = document.createElement("div");
            container.className =
                "space-y-2 dark:bg-gray-900 dark:text-gray-100";

            const fields = [
                { label: "Name", value: gateway.name },
                { label: "URL", value: gateway.url },
                { label: "Description", value: gateway.description || "N/A" },
            ];

            // Add tags field with special handling
            const tagsP = document.createElement("p");
            const tagsStrong = document.createElement("strong");
            tagsStrong.textContent = "Tags: ";
            tagsP.appendChild(tagsStrong);
            if (gateway.tags && gateway.tags.length > 0) {
                gateway.tags.forEach((tag, index) => {
                    const tagSpan = document.createElement("span");
                    tagSpan.className =
                        "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full mr-1";
                    tagSpan.textContent = tag;
                    tagsP.appendChild(tagSpan);
                });
            } else {
                tagsP.appendChild(document.createTextNode("No tags"));
            }
            container.appendChild(tagsP);

            fields.forEach((field) => {
                const p = document.createElement("p");
                const strong = document.createElement("strong");
                strong.textContent = field.label + ": ";
                p.appendChild(strong);
                p.appendChild(document.createTextNode(field.value));
                container.appendChild(p);
            });

            // Status
            const statusP = document.createElement("p");
            const statusStrong = document.createElement("strong");
            statusStrong.textContent = "Status: ";
            statusP.appendChild(statusStrong);

            const statusSpan = document.createElement("span");
            let statusText = "";
            let statusClass = "";
            let statusIcon = "";
            if (!gateway.enabled) {
                statusText = "Inactive";
                statusClass = "bg-red-100 text-red-800";
                statusIcon = `
                    <svg class="ml-1 h-4 w-4 text-red-600 self-center" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M6.293 6.293a1 1 0 011.414 0L10 8.586l2.293-2.293a1 1 0 111.414 1.414L11.414 10l2.293 2.293a1 1 0 11-1.414 1.414L10 11.414l-2.293 2.293a1 1 0 11-1.414-1.414L8.586 10 6.293 7.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
                      </svg>`;
            } else if (gateway.enabled && gateway.reachable) {
                statusText = "Active";
                statusClass = "bg-green-100 text-green-800";
                statusIcon = `
                    <svg class="ml-1 h-4 w-4 text-green-600 self-center" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-4.586l5.293-5.293-1.414-1.414L9 11.586 7.121 9.707 5.707 11.121 9 14.414z" clip-rule="evenodd"></path>
                      </svg>`;
            } else if (gateway.enabled && !gateway.reachable) {
                statusText = "Offline";
                statusClass = "bg-yellow-100 text-yellow-800";
                statusIcon = `
                    <svg class="ml-1 h-4 w-4 text-yellow-600 self-center" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-10h2v4h-2V8zm0 6h2v2h-2v-2z" clip-rule="evenodd"></path>
                      </svg>`;
            }

            statusSpan.className = `px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${statusClass}`;
            statusSpan.innerHTML = `${statusText} ${statusIcon}`;

            statusP.appendChild(statusSpan);
            container.appendChild(statusP);

            // Add metadata section
            const metadataDiv = document.createElement("div");
            metadataDiv.className = "mt-6 border-t pt-4";

            const metadataTitle = document.createElement("strong");
            metadataTitle.textContent = "Metadata:";
            metadataDiv.appendChild(metadataTitle);

            const metadataGrid = document.createElement("div");
            metadataGrid.className = "grid grid-cols-2 gap-4 mt-2 text-sm";

            const metadataFields = [
                {
                    label: "Created By",
                    value:
                        gateway.created_by ||
                        gateway.createdBy ||
                        "Legacy Entity",
                },
                {
                    label: "Created At",
                    value:
                        gateway.created_at || gateway.createdAt
                            ? new Date(
                                  gateway.created_at || gateway.createdAt,
                              ).toLocaleString()
                            : "Pre-metadata",
                },
                {
                    label: "Created From",
                    value:
                        gateway.created_from_ip ||
                        gateway.createdFromIp ||
                        "Unknown",
                },
                {
                    label: "Created Via",
                    value:
                        gateway.created_via || gateway.createdVia || "Unknown",
                },
                {
                    label: "Last Modified By",
                    value: gateway.modified_by || gateway.modifiedBy || "N/A",
                },
                {
                    label: "Last Modified At",
                    value:
                        gateway.updated_at || gateway.updatedAt
                            ? new Date(
                                  gateway.updated_at || gateway.updatedAt,
                              ).toLocaleString()
                            : "N/A",
                },
                {
                    label: "Modified From",
                    value:
                        gateway.modified_from_ip ||
                        gateway.modifiedFromIp ||
                        "N/A",
                },
                {
                    label: "Modified Via",
                    value: gateway.modified_via || gateway.modifiedVia || "N/A",
                },
                { label: "Version", value: gateway.version || "1" },
                {
                    label: "Import Batch",
                    value: gateway.importBatchId || "N/A",
                },
            ];

            metadataFields.forEach((field) => {
                const fieldDiv = document.createElement("div");

                const labelSpan = document.createElement("span");
                labelSpan.className =
                    "font-medium text-gray-600 dark:text-gray-400";
                labelSpan.textContent = field.label + ":";

                const valueSpan = document.createElement("span");
                valueSpan.className = "ml-2";
                valueSpan.textContent = field.value;

                fieldDiv.appendChild(labelSpan);
                fieldDiv.appendChild(valueSpan);
                metadataGrid.appendChild(fieldDiv);
            });

            metadataDiv.appendChild(metadataGrid);
            container.appendChild(metadataDiv);

            gatewayDetailsDiv.innerHTML = "";
            gatewayDetailsDiv.appendChild(container);
        }

        openModal("gateway-modal");
        console.log("✓ Gateway details loaded successfully");
    } catch (error) {
        console.error("Error fetching gateway details:", error);
        const errorMessage = handleFetchError(error, "load gateway details");
        showErrorMessage(errorMessage);
    }
}

/**
 * SECURE: Edit Gateway function
 */
async function editGateway(gatewayId) {
    try {
        console.log(`Editing gateway ID: ${gatewayId}`);

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/gateways/${gatewayId}`,
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const gateway = await response.json();

        const isInactiveCheckedBool = isInactiveChecked("gateways");
        let hiddenField = safeGetElement("edit-gateway-show-inactive");
        if (!hiddenField) {
            hiddenField = document.createElement("input");
            hiddenField.type = "hidden";
            hiddenField.name = "is_inactive_checked";
            hiddenField.id = "edit-gateway-show-inactive";
            const editForm = safeGetElement("edit-gateway-form");
            if (editForm) {
                editForm.appendChild(hiddenField);
            }
        }
        hiddenField.value = isInactiveCheckedBool;

        // Set form action and populate fields with validation
        const editForm = safeGetElement("edit-gateway-form");
        if (editForm) {
            editForm.action = `${window.ROOT_PATH}/admin/gateways/${gatewayId}/edit`;
        }

        const nameValidation = validateInputName(gateway.name, "gateway");
        const urlValidation = validateUrl(gateway.url);

        const nameField = safeGetElement("edit-gateway-name");
        const urlField = safeGetElement("edit-gateway-url");
        const descField = safeGetElement("edit-gateway-description");

        const transportField = safeGetElement("edit-gateway-transport");

        if (nameField && nameValidation.valid) {
            nameField.value = nameValidation.value;
        }
        if (urlField && urlValidation.valid) {
            urlField.value = urlValidation.value;
        }
        if (descField) {
            descField.value = gateway.description || "";
        }

        // Set tags field
        const tagsField = safeGetElement("edit-gateway-tags");
        if (tagsField) {
            tagsField.value = gateway.tags ? gateway.tags.join(", ") : "";
        }

        const teamId = new URL(window.location.href).searchParams.get(
            "team_id",
        );

        if (teamId) {
            const hiddenInput = document.createElement("input");
            hiddenInput.type = "hidden";
            hiddenInput.name = "team_id";
            hiddenInput.value = teamId;
            editForm.appendChild(hiddenInput);
        }

        const visibility = gateway.visibility; // Ensure visibility is either 'public', 'team', or 'private'
        const publicRadio = safeGetElement("edit-gateway-visibility-public");
        const teamRadio = safeGetElement("edit-gateway-visibility-team");
        const privateRadio = safeGetElement("edit-gateway-visibility-private");

        if (visibility) {
            // Check visibility and set the corresponding radio button
            if (visibility === "public" && publicRadio) {
                publicRadio.checked = true;
            } else if (visibility === "team" && teamRadio) {
                teamRadio.checked = true;
            } else if (visibility === "private" && privateRadio) {
                privateRadio.checked = true;
            }
        }

        if (transportField) {
            transportField.value = gateway.transport || "SSE"; // falls back to SSE(default)
        }

        const authTypeField = safeGetElement("auth-type-gw-edit");

        if (authTypeField) {
            authTypeField.value = gateway.authType || ""; // falls back to None
        }

        // Auth containers
        const authBasicSection = safeGetElement("auth-basic-fields-gw-edit");
        const authBearerSection = safeGetElement("auth-bearer-fields-gw-edit");
        const authHeadersSection = safeGetElement(
            "auth-headers-fields-gw-edit",
        );
        const authOAuthSection = safeGetElement("auth-oauth-fields-gw-edit");

        // Individual fields
        const authUsernameField = safeGetElement(
            "auth-basic-fields-gw-edit",
        )?.querySelector("input[name='auth_username']");
        const authPasswordField = safeGetElement(
            "auth-basic-fields-gw-edit",
        )?.querySelector("input[name='auth_password']");

        const authTokenField = safeGetElement(
            "auth-bearer-fields-gw-edit",
        )?.querySelector("input[name='auth_token']");

        const authHeaderKeyField = safeGetElement(
            "auth-headers-fields-gw-edit",
        )?.querySelector("input[name='auth_header_key']");
        const authHeaderValueField = safeGetElement(
            "auth-headers-fields-gw-edit",
        )?.querySelector("input[name='auth_header_value']");

        // OAuth fields
        const oauthGrantTypeField = safeGetElement("oauth-grant-type-gw-edit");
        const oauthClientIdField = safeGetElement("oauth-client-id-gw-edit");
        const oauthClientSecretField = safeGetElement(
            "oauth-client-secret-gw-edit",
        );
        const oauthTokenUrlField = safeGetElement("oauth-token-url-gw-edit");
        const oauthAuthUrlField = safeGetElement(
            "oauth-authorization-url-gw-edit",
        );
        const oauthRedirectUriField = safeGetElement(
            "oauth-redirect-uri-gw-edit",
        );
        const oauthScopesField = safeGetElement("oauth-scopes-gw-edit");
        const oauthAuthCodeFields = safeGetElement(
            "oauth-auth-code-fields-gw-edit",
        );

        // Hide all auth sections first
        if (authBasicSection) {
            authBasicSection.style.display = "none";
        }
        if (authBearerSection) {
            authBearerSection.style.display = "none";
        }
        if (authHeadersSection) {
            authHeadersSection.style.display = "none";
        }
        if (authOAuthSection) {
            authOAuthSection.style.display = "none";
        }

        switch (gateway.authType) {
            case "basic":
                if (authBasicSection) {
                    authBasicSection.style.display = "block";
                    if (authUsernameField) {
                        authUsernameField.value = gateway.authUsername || "";
                    }
                    if (authPasswordField) {
                        authPasswordField.value = "*****"; // mask password
                    }
                }
                break;
            case "bearer":
                if (authBearerSection) {
                    authBearerSection.style.display = "block";
                    if (authTokenField) {
                        authTokenField.value = gateway.authValue || ""; // show full token
                    }
                }
                break;
            case "authheaders":
                if (authHeadersSection) {
                    authHeadersSection.style.display = "block";
                    if (authHeaderKeyField) {
                        authHeaderKeyField.value = gateway.authHeaderKey || "";
                    }
                    if (authHeaderValueField) {
                        authHeaderValueField.value = "*****"; // mask header value
                    }
                }
                break;
            case "oauth":
                if (authOAuthSection) {
                    authOAuthSection.style.display = "block";
                }
                // Populate OAuth fields if available
                if (gateway.oauthConfig) {
                    const config = gateway.oauthConfig;
                    if (oauthGrantTypeField && config.grant_type) {
                        oauthGrantTypeField.value = config.grant_type;
                        // Show/hide authorization code fields based on grant type
                        if (oauthAuthCodeFields) {
                            oauthAuthCodeFields.style.display =
                                config.grant_type === "authorization_code"
                                    ? "block"
                                    : "none";
                        }
                    }
                    if (oauthClientIdField && config.client_id) {
                        oauthClientIdField.value = config.client_id;
                    }
                    if (oauthClientSecretField) {
                        oauthClientSecretField.value = ""; // Don't populate secret for security
                    }
                    if (oauthTokenUrlField && config.token_url) {
                        oauthTokenUrlField.value = config.token_url;
                    }
                    if (oauthAuthUrlField && config.authorization_url) {
                        oauthAuthUrlField.value = config.authorization_url;
                    }
                    if (oauthRedirectUriField && config.redirect_uri) {
                        oauthRedirectUriField.value = config.redirect_uri;
                    }
                    if (
                        oauthScopesField &&
                        config.scopes &&
                        Array.isArray(config.scopes)
                    ) {
                        oauthScopesField.value = config.scopes.join(" ");
                    }
                }
                break;
            case "":
            default:
                // No auth – keep everything hidden
                break;
        }

        // Handle passthrough headers
        const passthroughHeadersField = safeGetElement(
            "edit-gateway-passthrough-headers",
        );
        if (passthroughHeadersField) {
            if (
                gateway.passthroughHeaders &&
                Array.isArray(gateway.passthroughHeaders)
            ) {
                passthroughHeadersField.value =
                    gateway.passthroughHeaders.join(", ");
            } else {
                passthroughHeadersField.value = "";
            }
        }

        openModal("gateway-edit-modal");
        console.log("✓ Gateway edit modal loaded successfully");
    } catch (error) {
        console.error("Error fetching gateway for editing:", error);
        const errorMessage = handleFetchError(
            error,
            "load gateway for editing",
        );
        showErrorMessage(errorMessage);
    }
}

/**
 * SECURE: View Server function
 */
async function viewServer(serverId) {
    try {
        console.log(`Viewing server ID: ${serverId}`);

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/servers/${serverId}`,
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const server = await response.json();

        const serverDetailsDiv = safeGetElement("server-details");
        if (serverDetailsDiv) {
            const container = document.createElement("div");
            container.className =
                "space-y-4 dark:bg-gray-900 dark:text-gray-100";

            // Header section with server name and icon
            const headerDiv = document.createElement("div");
            headerDiv.className =
                "flex items-center space-x-3 pb-4 border-b border-gray-200 dark:border-gray-600";

            if (server.icon) {
                const iconImg = document.createElement("img");
                iconImg.src = server.icon;
                iconImg.alt = `${server.name} icon`;
                iconImg.className = "w-12 h-12 rounded-lg object-cover";
                iconImg.onerror = function () {
                    this.style.display = "none";
                };
                headerDiv.appendChild(iconImg);
            }

            const headerTextDiv = document.createElement("div");
            const serverTitle = document.createElement("h2");
            serverTitle.className =
                "text-xl font-bold text-gray-900 dark:text-gray-100";
            serverTitle.textContent = server.name;
            headerTextDiv.appendChild(serverTitle);

            if (server.description) {
                const serverDesc = document.createElement("p");
                serverDesc.className =
                    "text-sm text-gray-600 dark:text-gray-400 mt-1";
                serverDesc.textContent = server.description;
                headerTextDiv.appendChild(serverDesc);
            }

            headerDiv.appendChild(headerTextDiv);
            container.appendChild(headerDiv);

            // Basic information section
            const basicInfoDiv = document.createElement("div");
            basicInfoDiv.className = "space-y-2";

            const basicInfoTitle = document.createElement("strong");
            basicInfoTitle.textContent = "Basic Information:";
            basicInfoTitle.className =
                "block text-gray-900 dark:text-gray-100 mb-3";
            basicInfoDiv.appendChild(basicInfoTitle);

            const fields = [
                { label: "Server ID", value: server.id },
                { label: "URL", value: getCatalogUrl(server) || "N/A" },
                { label: "Type", value: "Virtual Server" },
            ];

            fields.forEach((field) => {
                const p = document.createElement("p");
                p.className = "text-sm";
                const strong = document.createElement("strong");
                strong.textContent = field.label + ": ";
                strong.className =
                    "font-medium text-gray-700 dark:text-gray-300";
                p.appendChild(strong);
                const valueSpan = document.createElement("span");
                valueSpan.textContent = field.value;
                valueSpan.className = "text-gray-600 dark:text-gray-400";
                p.appendChild(valueSpan);
                basicInfoDiv.appendChild(p);
            });

            container.appendChild(basicInfoDiv);

            // Tags and Status section
            const tagsStatusDiv = document.createElement("div");
            tagsStatusDiv.className =
                "flex items-center justify-between space-y-2";

            // Tags section
            const tagsP = document.createElement("p");
            tagsP.className = "text-sm";
            const tagsStrong = document.createElement("strong");
            tagsStrong.textContent = "Tags: ";
            tagsStrong.className =
                "font-medium text-gray-700 dark:text-gray-300";
            tagsP.appendChild(tagsStrong);

            if (server.tags && server.tags.length > 0) {
                server.tags.forEach((tag) => {
                    const tagSpan = document.createElement("span");
                    tagSpan.className =
                        "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full mr-1 mb-1 dark:bg-blue-900 dark:text-blue-200";
                    tagSpan.textContent = tag;
                    tagsP.appendChild(tagSpan);
                });
            } else {
                const noneSpan = document.createElement("span");
                noneSpan.textContent = "None";
                noneSpan.className = "text-gray-500 dark:text-gray-400";
                tagsP.appendChild(noneSpan);
            }

            // Status section
            const statusP = document.createElement("p");
            statusP.className = "text-sm";
            const statusStrong = document.createElement("strong");
            statusStrong.textContent = "Status: ";
            statusStrong.className =
                "font-medium text-gray-700 dark:text-gray-300";
            statusP.appendChild(statusStrong);

            const statusSpan = document.createElement("span");
            statusSpan.className = `px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                server.isActive
                    ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300"
                    : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300"
            }`;
            statusSpan.textContent = server.isActive ? "Active" : "Inactive";
            statusP.appendChild(statusSpan);

            tagsStatusDiv.appendChild(tagsP);
            tagsStatusDiv.appendChild(statusP);
            container.appendChild(tagsStatusDiv);

            // Associated Tools, Resources, and Prompts section
            const associatedDiv = document.createElement("div");
            associatedDiv.className = "mt-6 border-t pt-4";

            const associatedTitle = document.createElement("strong");
            associatedTitle.textContent = "Associated Items:";
            associatedDiv.appendChild(associatedTitle);

            // Tools section
            if (server.associatedTools && server.associatedTools.length > 0) {
                const toolsSection = document.createElement("div");
                toolsSection.className = "mt-3";

                const toolsLabel = document.createElement("p");
                const toolsStrong = document.createElement("strong");
                toolsStrong.textContent = "Tools: ";
                toolsLabel.appendChild(toolsStrong);

                const toolsList = document.createElement("div");
                toolsList.className = "mt-1 space-y-1";

                server.associatedTools.forEach((toolId) => {
                    const toolItem = document.createElement("div");
                    toolItem.className = "flex items-center space-x-2";

                    const toolBadge = document.createElement("span");
                    toolBadge.className =
                        "inline-block bg-green-100 text-green-800 text-xs px-2 py-1 rounded-full dark:bg-green-900 dark:text-green-200";
                    toolBadge.textContent =
                        window.toolMapping && window.toolMapping[toolId]
                            ? window.toolMapping[toolId]
                            : toolId;

                    const toolIdSpan = document.createElement("span");
                    toolIdSpan.className =
                        "text-xs text-gray-500 dark:text-gray-400";
                    toolIdSpan.textContent = `(${toolId})`;

                    toolItem.appendChild(toolBadge);
                    toolItem.appendChild(toolIdSpan);
                    toolsList.appendChild(toolItem);
                });

                toolsLabel.appendChild(toolsList);
                toolsSection.appendChild(toolsLabel);
                associatedDiv.appendChild(toolsSection);
            }

            // Resources section
            if (
                server.associatedResources &&
                server.associatedResources.length > 0
            ) {
                const resourcesSection = document.createElement("div");
                resourcesSection.className = "mt-3";

                const resourcesLabel = document.createElement("p");
                const resourcesStrong = document.createElement("strong");
                resourcesStrong.textContent = "Resources: ";
                resourcesLabel.appendChild(resourcesStrong);

                const resourcesList = document.createElement("div");
                resourcesList.className = "mt-1 space-y-1";

                server.associatedResources.forEach((resourceId) => {
                    const resourceItem = document.createElement("div");
                    resourceItem.className = "flex items-center space-x-2";

                    const resourceBadge = document.createElement("span");
                    resourceBadge.className =
                        "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full dark:bg-blue-900 dark:text-blue-200";
                    resourceBadge.textContent =
                        window.resourceMapping &&
                        window.resourceMapping[resourceId]
                            ? window.resourceMapping[resourceId]
                            : `Resource ${resourceId}`;

                    const resourceIdSpan = document.createElement("span");
                    resourceIdSpan.className =
                        "text-xs text-gray-500 dark:text-gray-400";
                    resourceIdSpan.textContent = `(${resourceId})`;

                    resourceItem.appendChild(resourceBadge);
                    resourceItem.appendChild(resourceIdSpan);
                    resourcesList.appendChild(resourceItem);
                });

                resourcesLabel.appendChild(resourcesList);
                resourcesSection.appendChild(resourcesLabel);
                associatedDiv.appendChild(resourcesSection);
            }

            // Prompts section
            if (
                server.associatedPrompts &&
                server.associatedPrompts.length > 0
            ) {
                const promptsSection = document.createElement("div");
                promptsSection.className = "mt-3";

                const promptsLabel = document.createElement("p");
                const promptsStrong = document.createElement("strong");
                promptsStrong.textContent = "Prompts: ";
                promptsLabel.appendChild(promptsStrong);

                const promptsList = document.createElement("div");
                promptsList.className = "mt-1 space-y-1";

                server.associatedPrompts.forEach((promptId) => {
                    const promptItem = document.createElement("div");
                    promptItem.className = "flex items-center space-x-2";

                    const promptBadge = document.createElement("span");
                    promptBadge.className =
                        "inline-block bg-purple-100 text-purple-800 text-xs px-2 py-1 rounded-full dark:bg-purple-900 dark:text-purple-200";
                    promptBadge.textContent =
                        window.promptMapping && window.promptMapping[promptId]
                            ? window.promptMapping[promptId]
                            : `Prompt ${promptId}`;

                    const promptIdSpan = document.createElement("span");
                    promptIdSpan.className =
                        "text-xs text-gray-500 dark:text-gray-400";
                    promptIdSpan.textContent = `(${promptId})`;

                    promptItem.appendChild(promptBadge);
                    promptItem.appendChild(promptIdSpan);
                    promptsList.appendChild(promptItem);
                });

                promptsLabel.appendChild(promptsList);
                promptsSection.appendChild(promptsLabel);
                associatedDiv.appendChild(promptsSection);
            }

            // A2A Agents section
            if (
                server.associatedA2aAgents &&
                server.associatedA2aAgents.length > 0
            ) {
                const agentsSection = document.createElement("div");
                agentsSection.className = "mt-3";

                const agentsLabel = document.createElement("p");
                const agentsStrong = document.createElement("strong");
                agentsStrong.textContent = "A2A Agents: ";
                agentsLabel.appendChild(agentsStrong);

                const agentsList = document.createElement("div");
                agentsList.className = "mt-1 space-y-1";

                server.associatedA2aAgents.forEach((agentId) => {
                    const agentItem = document.createElement("div");
                    agentItem.className = "flex items-center space-x-2";

                    const agentBadge = document.createElement("span");
                    agentBadge.className =
                        "inline-block bg-orange-100 text-orange-800 text-xs px-2 py-1 rounded-full dark:bg-orange-900 dark:text-orange-200";
                    agentBadge.textContent = `Agent ${agentId}`;

                    const agentIdSpan = document.createElement("span");
                    agentIdSpan.className =
                        "text-xs text-gray-500 dark:text-gray-400";
                    agentIdSpan.textContent = `(${agentId})`;

                    agentItem.appendChild(agentBadge);
                    agentItem.appendChild(agentIdSpan);
                    agentsList.appendChild(agentItem);
                });

                agentsLabel.appendChild(agentsList);
                agentsSection.appendChild(agentsLabel);
                associatedDiv.appendChild(agentsSection);
            }

            // Show message if no associated items
            if (
                (!server.associatedTools ||
                    server.associatedTools.length === 0) &&
                (!server.associatedResources ||
                    server.associatedResources.length === 0) &&
                (!server.associatedPrompts ||
                    server.associatedPrompts.length === 0) &&
                (!server.associatedA2aAgents ||
                    server.associatedA2aAgents.length === 0)
            ) {
                const noItemsP = document.createElement("p");
                noItemsP.className =
                    "mt-2 text-sm text-gray-500 dark:text-gray-400";
                noItemsP.textContent =
                    "No tools, resources, prompts, or A2A agents are currently associated with this server.";
                associatedDiv.appendChild(noItemsP);
            }

            container.appendChild(associatedDiv);

            // Add metadata section
            const metadataDiv = document.createElement("div");
            metadataDiv.className = "mt-6 border-t pt-4";

            const metadataTitle = document.createElement("strong");
            metadataTitle.textContent = "Metadata:";
            metadataDiv.appendChild(metadataTitle);

            const metadataGrid = document.createElement("div");
            metadataGrid.className = "grid grid-cols-2 gap-4 mt-2 text-sm";

            const metadataFields = [
                {
                    label: "Created By",
                    value: server.createdBy || "Legacy Entity",
                },
                {
                    label: "Created At",
                    value: server.createdAt
                        ? new Date(server.createdAt).toLocaleString()
                        : "Pre-metadata",
                },
                {
                    label: "Created From IP",
                    value:
                        server.created_from_ip ||
                        server.createdFromIp ||
                        "Unknown",
                },
                {
                    label: "Created Via",
                    value: server.created_via || server.createdVia || "Unknown",
                },
                {
                    label: "Last Modified By",
                    value: server.modified_by || server.modifiedBy || "N/A",
                },
                {
                    label: "Last Modified At",
                    value: server.updated_at
                        ? new Date(server.updated_at).toLocaleString()
                        : server.updatedAt
                          ? new Date(server.updatedAt).toLocaleString()
                          : "N/A",
                },
                {
                    label: "Modified From IP",
                    value:
                        server.modified_from_ip ||
                        server.modifiedFromIp ||
                        "N/A",
                },
                {
                    label: "Modified Via",
                    value: server.modified_via || server.modifiedVia || "N/A",
                },
                { label: "Version", value: server.version || "1" },
                {
                    label: "Import Batch",
                    value: server.importBatchId || "N/A",
                },
            ];

            metadataFields.forEach((field) => {
                const fieldDiv = document.createElement("div");

                const labelSpan = document.createElement("span");
                labelSpan.className =
                    "font-medium text-gray-600 dark:text-gray-400";
                labelSpan.textContent = field.label + ":";

                const valueSpan = document.createElement("span");
                valueSpan.className = "ml-2";
                valueSpan.textContent = field.value;

                fieldDiv.appendChild(labelSpan);
                fieldDiv.appendChild(valueSpan);
                metadataGrid.appendChild(fieldDiv);
            });

            metadataDiv.appendChild(metadataGrid);
            container.appendChild(metadataDiv);

            serverDetailsDiv.innerHTML = "";
            serverDetailsDiv.appendChild(container);
        }

        openModal("server-modal");
        console.log("✓ Server details loaded successfully");
    } catch (error) {
        console.error("Error fetching server details:", error);
        const errorMessage = handleFetchError(error, "load server details");
        showErrorMessage(errorMessage);
    }
}

/**
 * SECURE: Edit Server function
 */
async function editServer(serverId) {
    try {
        console.log(`Editing server ID: ${serverId}`);

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/servers/${serverId}`,
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const server = await response.json();

        const isInactiveCheckedBool = isInactiveChecked("servers");
        let hiddenField = safeGetElement("edit-server-show-inactive");
        const editForm = safeGetElement("edit-server-form");
        if (!hiddenField) {
            hiddenField = document.createElement("input");
            hiddenField.type = "hidden";
            hiddenField.name = "is_inactive_checked";
            hiddenField.id = "edit-server-show-inactive";

            if (editForm) {
                editForm.appendChild(hiddenField);
            }
        }
        hiddenField.value = isInactiveCheckedBool;

        const visibility = server.visibility; // Ensure visibility is either 'public', 'team', or 'private'
        const publicRadio = safeGetElement("edit-visibility-public");
        const teamRadio = safeGetElement("edit-visibility-team");
        const privateRadio = safeGetElement("edit-visibility-private");

        // Prepopulate visibility radio buttons based on the server data
        if (visibility) {
            // Check visibility and set the corresponding radio button
            if (visibility === "public" && publicRadio) {
                publicRadio.checked = true;
            } else if (visibility === "team" && teamRadio) {
                teamRadio.checked = true;
            } else if (visibility === "private" && privateRadio) {
                privateRadio.checked = true;
            }
        }

        const teamId = new URL(window.location.href).searchParams.get(
            "team_id",
        );

        if (teamId) {
            const hiddenInput = document.createElement("input");
            hiddenInput.type = "hidden";
            hiddenInput.name = "team_id";
            hiddenInput.value = teamId;
            editForm.appendChild(hiddenInput);
        }

        // Set form action and populate fields with validation
        if (editForm) {
            editForm.action = `${window.ROOT_PATH}/admin/servers/${serverId}/edit`;
        }

        const nameValidation = validateInputName(server.name, "server");
        const urlValidation = validateUrl(server.url);

        const nameField = safeGetElement("edit-server-name");
        const urlField = safeGetElement("edit-server-url");
        const descField = safeGetElement("edit-server-description");

        if (nameField && nameValidation.valid) {
            nameField.value = nameValidation.value;
        }
        if (urlField && urlValidation.valid) {
            urlField.value = urlValidation.value;
        }
        if (descField) {
            descField.value = server.description || "";
        }

        const idField = safeGetElement("edit-server-id");
        if (idField) {
            idField.value = server.id || "";
        }

        // Set tags field
        const tagsField = safeGetElement("edit-server-tags");
        if (tagsField) {
            tagsField.value = server.tags ? server.tags.join(", ") : "";
        }

        // Set icon field
        const iconField = safeGetElement("edit-server-icon");
        if (iconField) {
            iconField.value = server.icon || "";
        }

        // Store server data for modal population
        window.currentEditingServer = server;

        openModal("server-edit-modal");

        // Use multiple approaches to ensure checkboxes get set
        setEditServerAssociations(server);
        setTimeout(() => setEditServerAssociations(server), 100);
        setTimeout(() => setEditServerAssociations(server), 300);

        // Set associated items after modal is opened
        setTimeout(() => {
            console.log("Setting associated items for server:", server.id);
            console.log("Associated tools:", server.associatedTools);
            console.log("Associated resources:", server.associatedResources);
            console.log("Associated prompts:", server.associatedPrompts);

            // Set associated tools checkboxes
            const toolCheckboxes = document.querySelectorAll(
                'input[name="associatedTools"]',
            );
            console.log("Found", toolCheckboxes.length, "tool checkboxes");

            toolCheckboxes.forEach((checkbox) => {
                const isChecked =
                    server.associatedTools &&
                    server.associatedTools.includes(checkbox.value);
                console.log(
                    `Tool ${checkbox.value}: ${isChecked ? "CHECKED" : "unchecked"}`,
                );
                checkbox.checked = isChecked;
            });

            // Set associated resources checkboxes
            const resourceCheckboxes = document.querySelectorAll(
                'input[name="associatedResources"]',
            );
            console.log(
                "Found",
                resourceCheckboxes.length,
                "resource checkboxes",
            );

            resourceCheckboxes.forEach((checkbox) => {
                const checkboxValue = parseInt(checkbox.value);
                const isChecked =
                    server.associatedResources &&
                    server.associatedResources.includes(checkboxValue);
                console.log(
                    `Resource ${checkboxValue}: ${isChecked ? "CHECKED" : "unchecked"}`,
                );
                checkbox.checked = isChecked;
            });

            // Set associated prompts checkboxes
            const promptCheckboxes = document.querySelectorAll(
                'input[name="associatedPrompts"]',
            );
            console.log("Found", promptCheckboxes.length, "prompt checkboxes");

            promptCheckboxes.forEach((checkbox) => {
                const checkboxValue = parseInt(checkbox.value);
                const isChecked =
                    server.associatedPrompts &&
                    server.associatedPrompts.includes(checkboxValue);
                console.log(
                    `Prompt ${checkboxValue}: ${isChecked ? "CHECKED" : "unchecked"}`,
                );
                checkbox.checked = isChecked;
            });

            // Manually trigger the selector update functions to refresh pills
            setTimeout(() => {
                // Find and trigger existing tool selector update
                const toolContainer =
                    document.getElementById("edit-server-tools");
                if (toolContainer) {
                    const firstToolCheckbox = toolContainer.querySelector(
                        'input[type="checkbox"]',
                    );
                    if (firstToolCheckbox) {
                        const changeEvent = new Event("change", {
                            bubbles: true,
                        });
                        firstToolCheckbox.dispatchEvent(changeEvent);
                    }
                }

                // Trigger resource selector update
                const resourceContainer = document.getElementById(
                    "edit-server-resources",
                );
                if (resourceContainer) {
                    const firstResourceCheckbox =
                        resourceContainer.querySelector(
                            'input[type="checkbox"]',
                        );
                    if (firstResourceCheckbox) {
                        const changeEvent = new Event("change", {
                            bubbles: true,
                        });
                        firstResourceCheckbox.dispatchEvent(changeEvent);
                    }
                }

                // Trigger prompt selector update
                const promptContainer = document.getElementById(
                    "edit-server-prompts",
                );
                if (promptContainer) {
                    const firstPromptCheckbox = promptContainer.querySelector(
                        'input[type="checkbox"]',
                    );
                    if (firstPromptCheckbox) {
                        const changeEvent = new Event("change", {
                            bubbles: true,
                        });
                        firstPromptCheckbox.dispatchEvent(changeEvent);
                    }
                }
            }, 50);
        }, 200);

        console.log("✓ Server edit modal loaded successfully");
    } catch (error) {
        console.error("Error fetching server for editing:", error);
        const errorMessage = handleFetchError(error, "load server for editing");
        showErrorMessage(errorMessage);
    }
}

// Helper function to set edit server associations
function setEditServerAssociations(server) {
    // Set associated tools checkboxes
    const toolCheckboxes = document.querySelectorAll(
        'input[name="associatedTools"]',
    );

    if (toolCheckboxes.length === 0) {
        return;
    }

    toolCheckboxes.forEach((checkbox) => {
        let isChecked = false;
        if (server.associatedTools && window.toolMapping) {
            // Get the tool name for this checkbox UUID
            const toolName = window.toolMapping[checkbox.value];

            // Check if this tool name is in the associated tools array
            isChecked = toolName && server.associatedTools.includes(toolName);
        }

        checkbox.checked = isChecked;
    });

    // Set associated resources checkboxes
    const resourceCheckboxes = document.querySelectorAll(
        'input[name="associatedResources"]',
    );

    resourceCheckboxes.forEach((checkbox) => {
        const checkboxValue = parseInt(checkbox.value);
        const isChecked =
            server.associatedResources &&
            server.associatedResources.includes(checkboxValue);
        checkbox.checked = isChecked;
    });

    // Set associated prompts checkboxes
    const promptCheckboxes = document.querySelectorAll(
        'input[name="associatedPrompts"]',
    );

    promptCheckboxes.forEach((checkbox) => {
        const checkboxValue = parseInt(checkbox.value);
        const isChecked =
            server.associatedPrompts &&
            server.associatedPrompts.includes(checkboxValue);
        checkbox.checked = isChecked;
    });

    // Force update the pill displays by triggering change events
    setTimeout(() => {
        const allCheckboxes = [
            ...document.querySelectorAll(
                '#edit-server-tools input[type="checkbox"]',
            ),
            ...document.querySelectorAll(
                '#edit-server-resources input[type="checkbox"]',
            ),
            ...document.querySelectorAll(
                '#edit-server-prompts input[type="checkbox"]',
            ),
        ];

        allCheckboxes.forEach((checkbox) => {
            if (checkbox.checked) {
                checkbox.dispatchEvent(new Event("change", { bubbles: true }));
            }
        });
    }, 50);
}

// ===================================================================
// ENHANCED TAB HANDLING with Better Error Management
// ===================================================================

let tabSwitchTimeout = null;

function showTab(tabName) {
    try {
        console.log(`Switching to tab: ${tabName}`);

        // Clear any pending tab switch
        if (tabSwitchTimeout) {
            clearTimeout(tabSwitchTimeout);
        }

        // Navigation styling (immediate)
        document.querySelectorAll(".tab-panel").forEach((p) => {
            if (p) {
                p.classList.add("hidden");
            }
        });

        document.querySelectorAll(".tab-link").forEach((l) => {
            if (l) {
                l.classList.remove(
                    "border-indigo-500",
                    "text-indigo-600",
                    "dark:text-indigo-500",
                    "dark:border-indigo-400",
                );
                l.classList.add(
                    "border-transparent",
                    "text-gray-500",
                    "dark:text-gray-400",
                );
            }
        });

        // Reveal chosen panel
        const panel = safeGetElement(`${tabName}-panel`);
        if (panel) {
            panel.classList.remove("hidden");
        } else {
            console.error(`Panel ${tabName}-panel not found`);
            return;
        }

        const nav = document.querySelector(`[href="#${tabName}"]`);
        if (nav) {
            nav.classList.add(
                "border-indigo-500",
                "text-indigo-600",
                "dark:text-indigo-500",
                "dark:border-indigo-400",
            );
            nav.classList.remove(
                "border-transparent",
                "text-gray-500",
                "dark:text-gray-400",
            );
        }

        // Debounced content loading
        tabSwitchTimeout = setTimeout(() => {
            try {
                if (tabName === "metrics") {
                    // Only load if we're still on the metrics tab
                    if (!panel.classList.contains("hidden")) {
                        loadAggregatedMetrics();
                    }
                }

                if (tabName === "teams") {
                    // Load Teams list if not already loaded
                    const teamsList = safeGetElement("teams-list");
                    if (teamsList) {
                        // Check if it's still showing the loading message or is empty
                        const hasLoadingMessage =
                            teamsList.innerHTML.includes("Loading teams...");
                        const isEmpty = teamsList.innerHTML.trim() === "";
                        if (hasLoadingMessage || isEmpty) {
                            // Trigger HTMX load manually if HTMX is available
                            if (window.htmx && window.htmx.trigger) {
                                window.htmx.trigger(teamsList, "load");
                            }
                        }
                    }
                }

                if (tabName === "tokens") {
                    // Load Tokens list and set up form handling
                    const tokensList = safeGetElement("tokens-list");
                    if (tokensList) {
                        const hasLoadingMessage =
                            tokensList.innerHTML.includes("Loading tokens...");
                        const isEmpty = tokensList.innerHTML.trim() === "";
                        if (hasLoadingMessage || isEmpty) {
                            loadTokensList();
                        }
                    }

                    // Set up create token form if not already set up
                    const createForm = safeGetElement("create-token-form");
                    if (createForm && !createForm.hasAttribute("data-setup")) {
                        setupCreateTokenForm();
                        createForm.setAttribute("data-setup", "true");
                    }
                }

                if (tabName === "a2a-agents") {
                    // Load A2A agents list if not already loaded
                    const agentsList = safeGetElement("a2a-agents-list");
                    if (agentsList && agentsList.innerHTML.trim() === "") {
                        // Trigger HTMX load manually if HTMX is available
                        if (window.htmx && window.htmx.trigger) {
                            window.htmx.trigger(agentsList, "load");
                        }
                    }
                }

                if (tabName === "version-info") {
                    const versionPanel = safeGetElement("version-info-panel");
                    if (versionPanel && versionPanel.innerHTML.trim() === "") {
                        fetchWithTimeout(
                            `${window.ROOT_PATH}/version?partial=true`,
                            {},
                            window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000,
                        )
                            .then((resp) => {
                                if (!resp.ok) {
                                    throw new Error(
                                        `HTTP ${resp.status}: ${resp.statusText}`,
                                    );
                                }
                                return resp.text();
                            })
                            .then((html) => {
                                safeSetInnerHTML(versionPanel, html, true);
                                console.log("✓ Version info loaded");
                            })
                            .catch((err) => {
                                console.error(
                                    "Failed to load version info:",
                                    err,
                                );
                                const errorDiv = document.createElement("div");
                                errorDiv.className = "text-red-600 p-4";
                                errorDiv.textContent =
                                    "Failed to load version info. Please try again.";
                                versionPanel.innerHTML = "";
                                versionPanel.appendChild(errorDiv);
                            });
                    }
                }

                if (tabName === "export-import") {
                    // Initialize export/import functionality when tab is shown
                    if (!panel.classList.contains("hidden")) {
                        console.log(
                            "🔄 Initializing export/import tab content",
                        );
                        try {
                            // Ensure the export/import functionality is initialized
                            if (typeof initializeExportImport === "function") {
                                initializeExportImport();
                            }
                            // Load recent imports
                            if (typeof loadRecentImports === "function") {
                                loadRecentImports();
                            }
                        } catch (error) {
                            console.error(
                                "Error loading export/import content:",
                                error,
                            );
                        }
                    }
                }

                if (tabName === "permissions") {
                    // Initialize permissions panel when tab is shown
                    if (!panel.classList.contains("hidden")) {
                        console.log("🔄 Initializing permissions tab content");
                        try {
                            // Check if initializePermissionsPanel function exists
                            if (
                                typeof initializePermissionsPanel === "function"
                            ) {
                                initializePermissionsPanel();
                            } else {
                                console.warn(
                                    "initializePermissionsPanel function not found",
                                );
                            }
                        } catch (error) {
                            console.error(
                                "Error initializing permissions panel:",
                                error,
                            );
                        }
                    }
                }
            } catch (error) {
                console.error(
                    `Error in tab ${tabName} content loading:`,
                    error,
                );
            }
        }, 300); // 300ms debounce

        console.log(`✓ Successfully switched to tab: ${tabName}`);
    } catch (error) {
        console.error(`Error switching to tab ${tabName}:`, error);
        showErrorMessage(`Failed to switch to ${tabName} tab`);
    }
}

// ===================================================================
// AUTH HANDLING
// ===================================================================

function handleAuthTypeSelection(
    value,
    basicFields,
    bearerFields,
    headersFields,
    oauthFields,
) {
    if (!basicFields || !bearerFields || !headersFields) {
        console.warn("Auth field elements not found");
        return;
    }

    // Hide all fields first
    [basicFields, bearerFields, headersFields].forEach((field) => {
        if (field) {
            field.style.display = "none";
        }
    });

    // Hide OAuth fields if they exist
    if (oauthFields) {
        oauthFields.style.display = "none";
    }

    // Show relevant field based on selection
    switch (value) {
        case "basic":
            if (basicFields) {
                basicFields.style.display = "block";
            }
            break;
        case "bearer":
            if (bearerFields) {
                bearerFields.style.display = "block";
            }
            break;
        case "authheaders": {
            if (headersFields) {
                headersFields.style.display = "block";
                // Ensure at least one header row is present
                const containerId =
                    headersFields.querySelector('[id$="-container"]')?.id;
                if (containerId) {
                    const container = document.getElementById(containerId);
                    if (container && container.children.length === 0) {
                        addAuthHeader(containerId);
                    }
                }
            }
            break;
        }
        case "oauth":
            if (oauthFields) {
                oauthFields.style.display = "block";
            }
            break;
        default:
            // All fields already hidden
            break;
    }
}

// ===================================================================
// ENHANCED SCHEMA GENERATION with Safe State Access
// ===================================================================

function generateSchema() {
    const schema = {
        title: "CustomInputSchema",
        type: "object",
        properties: {},
        required: [],
    };

    const paramCount = AppState.getParameterCount();

    for (let i = 1; i <= paramCount; i++) {
        try {
            const nameField = document.querySelector(
                `[name="param_name_${i}"]`,
            );
            const typeField = document.querySelector(
                `[name="param_type_${i}"]`,
            );
            const descField = document.querySelector(
                `[name="param_description_${i}"]`,
            );
            const requiredField = document.querySelector(
                `[name="param_required_${i}"]`,
            );

            if (nameField && nameField.value.trim() !== "") {
                // Validate parameter name
                const nameValidation = validateInputName(
                    nameField.value.trim(),
                    "parameter",
                );
                if (!nameValidation.valid) {
                    console.warn(
                        `Invalid parameter name at index ${i}: ${nameValidation.error}`,
                    );
                    continue;
                }

                schema.properties[nameValidation.value] = {
                    type: typeField ? typeField.value : "string",
                    description: descField ? descField.value.trim() : "",
                };

                if (requiredField && requiredField.checked) {
                    schema.required.push(nameValidation.value);
                }
            }
        } catch (error) {
            console.error(`Error processing parameter ${i}:`, error);
        }
    }

    return JSON.stringify(schema, null, 2);
}

function updateSchemaPreview() {
    try {
        const modeRadio = document.querySelector(
            'input[name="schema_input_mode"]:checked',
        );
        if (modeRadio && modeRadio.value === "json") {
            if (
                window.schemaEditor &&
                typeof window.schemaEditor.setValue === "function"
            ) {
                window.schemaEditor.setValue(generateSchema());
            }
        }
    } catch (error) {
        console.error("Error updating schema preview:", error);
    }
}

// ===================================================================
// ENHANCED PARAMETER HANDLING with Validation
// ===================================================================

function handleAddParameter() {
    const parameterCount = AppState.incrementParameterCount();
    const parametersContainer = safeGetElement("parameters-container");

    if (!parametersContainer) {
        console.error("Parameters container not found");
        AppState.decrementParameterCount(); // Rollback
        return;
    }

    try {
        const paramDiv = document.createElement("div");
        paramDiv.classList.add(
            "border",
            "p-4",
            "mb-4",
            "rounded-md",
            "bg-gray-50",
            "shadow-sm",
        );

        // Create parameter form with validation
        const parameterForm = createParameterForm(parameterCount);
        paramDiv.appendChild(parameterForm);

        parametersContainer.appendChild(paramDiv);
        updateSchemaPreview();

        // Delete parameter functionality with safe state management
        const deleteButton = paramDiv.querySelector(".delete-param");
        if (deleteButton) {
            deleteButton.addEventListener("click", () => {
                try {
                    paramDiv.remove();
                    AppState.decrementParameterCount();
                    updateSchemaPreview();
                    console.log(
                        `✓ Removed parameter, count now: ${AppState.getParameterCount()}`,
                    );
                } catch (error) {
                    console.error("Error removing parameter:", error);
                }
            });
        }

        console.log(`✓ Added parameter ${parameterCount}`);
    } catch (error) {
        console.error("Error adding parameter:", error);
        AppState.decrementParameterCount(); // Rollback on error
    }
}

function createParameterForm(parameterCount) {
    const container = document.createElement("div");

    // Header with delete button
    const header = document.createElement("div");
    header.className = "flex justify-between items-center";

    const title = document.createElement("span");
    title.className = "font-semibold text-gray-800 dark:text-gray-200";
    title.textContent = `Parameter ${parameterCount}`;

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className =
        "delete-param text-red-600 hover:text-red-800 focus:outline-none text-xl";
    deleteBtn.title = "Delete Parameter";
    deleteBtn.textContent = "×";

    header.appendChild(title);
    header.appendChild(deleteBtn);
    container.appendChild(header);

    // Form fields grid
    const grid = document.createElement("div");
    grid.className = "grid grid-cols-1 md:grid-cols-2 gap-4 mt-4";

    // Parameter name field with validation
    const nameGroup = document.createElement("div");
    const nameLabel = document.createElement("label");
    nameLabel.className =
        "block text-sm font-medium text-gray-700 dark:text-gray-300";
    nameLabel.textContent = "Parameter Name";

    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.name = `param_name_${parameterCount}`;
    nameInput.required = true;
    nameInput.className =
        "mt-1 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200";

    // Add validation to name input
    nameInput.addEventListener("blur", function () {
        const validation = validateInputName(this.value, "parameter");
        if (!validation.valid) {
            this.setCustomValidity(validation.error);
            this.reportValidity();
        } else {
            this.setCustomValidity("");
            this.value = validation.value; // Use cleaned value
        }
    });

    nameGroup.appendChild(nameLabel);
    nameGroup.appendChild(nameInput);

    // Type field
    const typeGroup = document.createElement("div");
    const typeLabel = document.createElement("label");
    typeLabel.className =
        "block text-sm font-medium text-gray-700 dark:text-gray-300";
    typeLabel.textContent = "Type";

    const typeSelect = document.createElement("select");
    typeSelect.name = `param_type_${parameterCount}`;
    typeSelect.className =
        "mt-1 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200";

    const typeOptions = [
        { value: "string", text: "String" },
        { value: "number", text: "Number" },
        { value: "boolean", text: "Boolean" },
        { value: "object", text: "Object" },
        { value: "array", text: "Array" },
    ];

    typeOptions.forEach((option) => {
        const optionElement = document.createElement("option");
        optionElement.value = option.value;
        optionElement.textContent = option.text;
        typeSelect.appendChild(optionElement);
    });

    typeGroup.appendChild(typeLabel);
    typeGroup.appendChild(typeSelect);

    grid.appendChild(nameGroup);
    grid.appendChild(typeGroup);
    container.appendChild(grid);

    // Description field
    const descGroup = document.createElement("div");
    descGroup.className = "mt-4";

    const descLabel = document.createElement("label");
    descLabel.className =
        "block text-sm font-medium text-gray-700 dark:text-gray-300";
    descLabel.textContent = "Description";

    const descTextarea = document.createElement("textarea");
    descTextarea.name = `param_description_${parameterCount}`;
    descTextarea.className =
        "mt-1 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200";
    descTextarea.rows = 2;

    descGroup.appendChild(descLabel);
    descGroup.appendChild(descTextarea);
    container.appendChild(descGroup);

    // Required checkbox
    const requiredGroup = document.createElement("div");
    requiredGroup.className = "mt-4 flex items-center";

    const requiredInput = document.createElement("input");
    requiredInput.type = "checkbox";
    requiredInput.name = `param_required_${parameterCount}`;
    requiredInput.checked = true;
    requiredInput.className =
        "h-4 w-4 text-indigo-600 border border-gray-300 rounded";

    const requiredLabel = document.createElement("label");
    requiredLabel.className =
        "ml-2 text-sm font-medium text-gray-700 dark:text-gray-300";
    requiredLabel.textContent = "Required";

    requiredGroup.appendChild(requiredInput);
    requiredGroup.appendChild(requiredLabel);
    container.appendChild(requiredGroup);

    return container;
}

// ===================================================================
// INTEGRATION TYPE HANDLING
// ===================================================================

const integrationRequestMap = {
    REST: ["GET", "POST", "PUT", "PATCH", "DELETE"],
    MCP: [],
};

function updateRequestTypeOptions(preselectedValue = null) {
    const requestTypeSelect = safeGetElement("requestType");
    const integrationTypeSelect = safeGetElement("integrationType");

    if (!requestTypeSelect || !integrationTypeSelect) {
        return;
    }

    const selectedIntegration = integrationTypeSelect.value;
    const options = integrationRequestMap[selectedIntegration] || [];

    // Clear current options
    requestTypeSelect.innerHTML = "";

    // Add new options
    options.forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        requestTypeSelect.appendChild(option);
    });

    // Set the value if preselected
    if (preselectedValue && options.includes(preselectedValue)) {
        requestTypeSelect.value = preselectedValue;
    }
}

function updateEditToolRequestTypes(selectedMethod = null) {
    const editToolTypeSelect = safeGetElement("edit-tool-type");
    const editToolRequestTypeSelect = safeGetElement("edit-tool-request-type");
    if (!editToolTypeSelect || !editToolRequestTypeSelect) {
        return;
    }

    // Track previous value using a data attribute
    if (!editToolTypeSelect.dataset.prevValue) {
        editToolTypeSelect.dataset.prevValue = editToolTypeSelect.value;
    }

    // const prevType = editToolTypeSelect.dataset.prevValue;
    const selectedType = editToolTypeSelect.value;
    const allowedMethods = integrationRequestMap[selectedType] || [];

    // If this integration has no HTTP verbs (MCP), clear & disable the control
    if (allowedMethods.length === 0) {
        editToolRequestTypeSelect.innerHTML = "";
        editToolRequestTypeSelect.value = "";
        editToolRequestTypeSelect.disabled = true;
        return;
    }

    // Otherwise populate and enable
    editToolRequestTypeSelect.disabled = false;
    editToolRequestTypeSelect.innerHTML = "";
    allowedMethods.forEach((method) => {
        const option = document.createElement("option");
        option.value = method;
        option.textContent = method;
        editToolRequestTypeSelect.appendChild(option);
    });

    if (selectedMethod && allowedMethods.includes(selectedMethod)) {
        editToolRequestTypeSelect.value = selectedMethod;
    }
}

// ===================================================================
// TOOL SELECT FUNCTIONALITY
// ===================================================================

// Prevent manual REST→MCP changes in edit-tool-form
document.addEventListener("DOMContentLoaded", function () {
    const editToolTypeSelect = document.getElementById("edit-tool-type");
    if (editToolTypeSelect) {
        // Store the initial value for comparison
        editToolTypeSelect.dataset.prevValue = editToolTypeSelect.value;

        editToolTypeSelect.addEventListener("change", function (e) {
            const prevType = this.dataset.prevValue;
            const selectedType = this.value;
            if (prevType === "REST" && selectedType === "MCP") {
                alert("You cannot change integration type from REST to MCP.");
                this.value = prevType;
                // Optionally, reset any dependent fields here
            } else {
                this.dataset.prevValue = selectedType;
            }
        });
    }
});
//= ==================================================================
function initToolSelect(
    selectId,
    pillsId,
    warnId,
    max = 6,
    selectBtnId = null,
    clearBtnId = null,
) {
    const container = document.getElementById(selectId);
    const pillsBox = document.getElementById(pillsId);
    const warnBox = document.getElementById(warnId);
    const clearBtn = clearBtnId ? document.getElementById(clearBtnId) : null;
    const selectBtn = selectBtnId ? document.getElementById(selectBtnId) : null;

    if (!container || !pillsBox || !warnBox) {
        console.warn(
            `Tool select elements not found: ${selectId}, ${pillsId}, ${warnId}`,
        );
        return;
    }

    const checkboxes = container.querySelectorAll('input[type="checkbox"]');
    const pillClasses =
        "inline-block px-3 py-1 text-xs font-semibold text-indigo-700 bg-indigo-100 rounded-full shadow";

    function update() {
        try {
            const checked = Array.from(checkboxes).filter((cb) => cb.checked);
            const count = checked.length;

            // Rebuild pills safely
            pillsBox.innerHTML = "";
            checked.forEach((cb) => {
                const span = document.createElement("span");
                span.className = pillClasses;
                span.textContent =
                    cb.nextElementSibling?.textContent?.trim() || "Unnamed";
                pillsBox.appendChild(span);
            });

            // Warning when > max
            if (count > max) {
                warnBox.textContent = `Selected ${count} tools. Selecting more than ${max} tools can degrade agent performance with the server.`;
            } else {
                warnBox.textContent = "";
            }
        } catch (error) {
            console.error("Error updating tool select:", error);
        }
    }

    if (clearBtn) {
        clearBtn.addEventListener("click", () => {
            checkboxes.forEach((cb) => (cb.checked = false));
            update();
        });
    }

    if (selectBtn) {
        selectBtn.addEventListener("click", () => {
            checkboxes.forEach((cb) => (cb.checked = true));
            update();
        });
    }

    update(); // Initial render
    checkboxes.forEach((cb) => cb.addEventListener("change", update));
}

function initResourceSelect(
    selectId,
    pillsId,
    warnId,
    max = 10,
    selectBtnId = null,
    clearBtnId = null,
) {
    const container = document.getElementById(selectId);
    const pillsBox = document.getElementById(pillsId);
    const warnBox = document.getElementById(warnId);
    const clearBtn = clearBtnId ? document.getElementById(clearBtnId) : null;
    const selectBtn = selectBtnId ? document.getElementById(selectBtnId) : null;

    if (!container || !pillsBox || !warnBox) {
        console.warn(
            `Resource select elements not found: ${selectId}, ${pillsId}, ${warnId}`,
        );
        return;
    }

    const checkboxes = container.querySelectorAll('input[type="checkbox"]');
    const pillClasses =
        "inline-block px-3 py-1 text-xs font-semibold text-blue-700 bg-blue-100 rounded-full shadow dark:text-blue-300 dark:bg-blue-900";

    function update() {
        try {
            const checked = Array.from(checkboxes).filter((cb) => cb.checked);
            const count = checked.length;

            // Rebuild pills safely
            pillsBox.innerHTML = "";
            checked.forEach((cb) => {
                const span = document.createElement("span");
                span.className = pillClasses;
                span.textContent =
                    cb.nextElementSibling?.textContent?.trim() || "Unnamed";
                pillsBox.appendChild(span);
            });

            // Warning when > max
            if (count > max) {
                warnBox.textContent = `Selected ${count} resources. Selecting more than ${max} resources can degrade agent performance with the server.`;
            } else {
                warnBox.textContent = "";
            }
        } catch (error) {
            console.error("Error updating resource select:", error);
        }
    }

    if (clearBtn) {
        clearBtn.addEventListener("click", () => {
            checkboxes.forEach((cb) => (cb.checked = false));
            update();
        });
    }

    if (selectBtn) {
        selectBtn.addEventListener("click", () => {
            checkboxes.forEach((cb) => (cb.checked = true));
            update();
        });
    }

    update(); // Initial render
    checkboxes.forEach((cb) => cb.addEventListener("change", update));
}

function initPromptSelect(
    selectId,
    pillsId,
    warnId,
    max = 8,
    selectBtnId = null,
    clearBtnId = null,
) {
    const container = document.getElementById(selectId);
    const pillsBox = document.getElementById(pillsId);
    const warnBox = document.getElementById(warnId);
    const clearBtn = clearBtnId ? document.getElementById(clearBtnId) : null;
    const selectBtn = selectBtnId ? document.getElementById(selectBtnId) : null;

    if (!container || !pillsBox || !warnBox) {
        console.warn(
            `Prompt select elements not found: ${selectId}, ${pillsId}, ${warnId}`,
        );
        return;
    }

    const checkboxes = container.querySelectorAll('input[type="checkbox"]');
    const pillClasses =
        "inline-block px-3 py-1 text-xs font-semibold text-purple-700 bg-purple-100 rounded-full shadow dark:text-purple-300 dark:bg-purple-900";

    function update() {
        try {
            const checked = Array.from(checkboxes).filter((cb) => cb.checked);
            const count = checked.length;

            // Rebuild pills safely
            pillsBox.innerHTML = "";
            checked.forEach((cb) => {
                const span = document.createElement("span");
                span.className = pillClasses;
                span.textContent =
                    cb.nextElementSibling?.textContent?.trim() || "Unnamed";
                pillsBox.appendChild(span);
            });

            // Warning when > max
            if (count > max) {
                warnBox.textContent = `Selected ${count} prompts. Selecting more than ${max} prompts can degrade agent performance with the server.`;
            } else {
                warnBox.textContent = "";
            }
        } catch (error) {
            console.error("Error updating prompt select:", error);
        }
    }

    if (clearBtn) {
        clearBtn.addEventListener("click", () => {
            checkboxes.forEach((cb) => (cb.checked = false));
            update();
        });
    }

    if (selectBtn) {
        selectBtn.addEventListener("click", () => {
            checkboxes.forEach((cb) => (cb.checked = true));
            update();
        });
    }

    update(); // Initial render
    checkboxes.forEach((cb) => cb.addEventListener("change", update));
}

// ===================================================================
// INACTIVE ITEMS HANDLING
// ===================================================================

function toggleInactiveItems(type) {
    const checkbox = safeGetElement(`show-inactive-${type}`);
    if (!checkbox) {
        return;
    }

    const url = new URL(window.location);
    if (checkbox.checked) {
        url.searchParams.set("include_inactive", "true");
    } else {
        url.searchParams.delete("include_inactive");
    }
    window.location = url;
}

function handleToggleSubmit(event, type) {
    event.preventDefault();

    const isInactiveCheckedBool = isInactiveChecked(type);
    const form = event.target;
    const hiddenField = document.createElement("input");
    hiddenField.type = "hidden";
    hiddenField.name = "is_inactive_checked";
    hiddenField.value = isInactiveCheckedBool;

    form.appendChild(hiddenField);
    form.submit();
}

function handleSubmitWithConfirmation(event, type) {
    event.preventDefault();

    const confirmationMessage = `Are you sure you want to permanently delete this ${type}? (Deactivation is reversible, deletion is permanent)`;
    const confirmation = confirm(confirmationMessage);
    if (!confirmation) {
        return false;
    }

    return handleToggleSubmit(event, type);
}

// ===================================================================
// ENHANCED TOOL TESTING with Safe State Management
// ===================================================================

// Track active tool test requests globally
const toolTestState = {
    activeRequests: new Map(), // toolId -> AbortController
    lastRequestTime: new Map(), // toolId -> timestamp
    debounceDelay: 1000, // Increased from 500ms
    requestTimeout: window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000, // Use configurable timeout
};

let toolInputSchemaRegistry = null;

/**
 * ENHANCED: Tool testing with improved race condition handling
 */
async function testTool(toolId) {
    try {
        console.log(`Testing tool ID: ${toolId}`);

        // 1. ENHANCED DEBOUNCING: More aggressive to prevent rapid clicking
        const now = Date.now();
        const lastRequest = toolTestState.lastRequestTime.get(toolId) || 0;
        const timeSinceLastRequest = now - lastRequest;
        const enhancedDebounceDelay = 2000; // Increased from 1000ms

        if (timeSinceLastRequest < enhancedDebounceDelay) {
            console.log(
                `Tool ${toolId} test request debounced (${timeSinceLastRequest}ms ago)`,
            );
            const waitTime = Math.ceil(
                (enhancedDebounceDelay - timeSinceLastRequest) / 1000,
            );
            showErrorMessage(
                `Please wait ${waitTime} more second${waitTime > 1 ? "s" : ""} before testing again`,
            );
            return;
        }

        // 2. MODAL PROTECTION: Enhanced check
        if (AppState.isModalActive("tool-test-modal")) {
            console.warn("Tool test modal is already active");
            return; // Silent fail for better UX
        }

        // 3. BUTTON STATE: Immediate feedback with better state management
        const testButton = document.querySelector(
            `[onclick*="testTool('${toolId}')"]`,
        );
        if (testButton) {
            if (testButton.disabled) {
                console.log(
                    "Test button already disabled, request in progress",
                );
                return;
            }
            testButton.disabled = true;
            testButton.textContent = "Testing...";
            testButton.classList.add("opacity-50", "cursor-not-allowed");
        }

        // 4. REQUEST CANCELLATION: Enhanced cleanup
        const existingController = toolTestState.activeRequests.get(toolId);
        if (existingController) {
            console.log(`Cancelling existing request for tool ${toolId}`);
            existingController.abort();
            toolTestState.activeRequests.delete(toolId);
        }

        // 5. CREATE NEW REQUEST with longer timeout
        const controller = new AbortController();
        toolTestState.activeRequests.set(toolId, controller);
        toolTestState.lastRequestTime.set(toolId, now);

        // 6. MAKE REQUEST with increased timeout
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/tools/${toolId}`,
            {
                signal: controller.signal,
                headers: {
                    "Cache-Control": "no-cache",
                    Pragma: "no-cache",
                },
            },
            toolTestState.requestTimeout, // Use the increased timeout
        );

        if (!response.ok) {
            if (response.status === 404) {
                throw new Error(
                    `Tool with ID ${toolId} not found. It may have been deleted.`,
                );
            } else if (response.status === 429) {
                throw new Error(
                    "Too many requests. Please wait a moment before testing again.",
                );
            } else if (response.status >= 500) {
                throw new Error(
                    `Server error (${response.status}). The server may be overloaded. Please try again in a few seconds.`,
                );
            } else {
                throw new Error(
                    `HTTP ${response.status}: ${response.statusText}`,
                );
            }
        }

        const tool = await response.json();
        console.log(`Tool ${toolId} fetched successfully`, tool);
        toolInputSchemaRegistry = tool;

        // 7. CLEAN STATE before proceeding
        toolTestState.activeRequests.delete(toolId);

        // Store in safe state
        AppState.currentTestTool = tool;

        // Set modal title and description safely - NO DOUBLE ESCAPING
        const titleElement = safeGetElement("tool-test-modal-title");
        const descElement = safeGetElement("tool-test-modal-description");

        if (titleElement) {
            titleElement.textContent = "Test Tool: " + (tool.name || "Unknown");
        }
        if (descElement) {
            if (tool.description) {
                // Escape HTML and then replace newlines with <br/> tags
                descElement.innerHTML = escapeHtml(tool.description).replace(
                    /\n/g,
                    "<br/>",
                );
            } else {
                descElement.textContent = "No description available.";
            }
        }

        const container = safeGetElement("tool-test-form-fields");
        if (!container) {
            console.error("Tool test form fields container not found");
            return;
        }

        container.innerHTML = ""; // Clear previous fields

        // Parse the input schema safely
        let schema = tool.inputSchema;
        if (typeof schema === "string") {
            try {
                schema = JSON.parse(schema);
            } catch (e) {
                console.error("Invalid JSON schema", e);
                schema = {};
            }
        }

        // Dynamically create form fields based on schema.properties
        if (schema && schema.properties) {
            for (const key in schema.properties) {
                const prop = schema.properties[key];

                // Validate the property name
                const keyValidation = validateInputName(key, "schema property");
                if (!keyValidation.valid) {
                    console.warn(`Skipping invalid schema property: ${key}`);
                    continue;
                }

                const fieldDiv = document.createElement("div");
                fieldDiv.className = "mb-4";

                // Field label - use textContent to avoid double escaping
                const label = document.createElement("label");
                label.className =
                    "block text-sm font-medium text-gray-700 dark:text-gray-300";

                // Create span for label text
                const labelText = document.createElement("span");
                labelText.textContent = keyValidation.value;
                label.appendChild(labelText);

                // Add red star if field is required
                if (schema.required && schema.required.includes(key)) {
                    const requiredMark = document.createElement("span");
                    requiredMark.textContent = " *";
                    requiredMark.className = "text-red-500";
                    label.appendChild(requiredMark);
                }

                fieldDiv.appendChild(label);

                // Description help text - use textContent
                if (prop.description) {
                    const description = document.createElement("small");
                    description.textContent = prop.description;
                    description.className = "text-gray-500 block mb-1";
                    fieldDiv.appendChild(description);
                }

                if (prop.type === "array") {
                    const arrayContainer = document.createElement("div");
                    arrayContainer.className = "space-y-2";

                    function createArrayInput(value = "") {
                        const wrapper = document.createElement("div");
                        wrapper.className = "flex items-center space-x-2";

                        const input = document.createElement("input");
                        input.name = keyValidation.value;
                        input.required =
                            schema.required && schema.required.includes(key);
                        input.className =
                            "mt-1 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 text-gray-700 dark:text-gray-300 dark:border-gray-700 dark:focus:border-indigo-400 dark:focus:ring-indigo-400";

                        const itemTypes = Array.isArray(prop.items?.anyOf)
                            ? prop.items.anyOf.map((t) => t.type)
                            : [prop.items?.type];

                        if (
                            itemTypes.includes("number") ||
                            itemTypes.includes("integer")
                        ) {
                            input.type = "number";
                            input.step = itemTypes.includes("integer")
                                ? "1"
                                : "any";
                        } else if (itemTypes.includes("boolean")) {
                            input.type = "checkbox";
                            input.value = "true";
                            input.checked = value === true || value === "true";
                        } else {
                            input.type = "text";
                        }

                        if (
                            typeof value === "string" ||
                            typeof value === "number"
                        ) {
                            input.value = value;
                        }

                        const delBtn = document.createElement("button");
                        delBtn.type = "button";
                        delBtn.className =
                            "ml-2 text-red-600 hover:text-red-800 focus:outline-none";
                        delBtn.title = "Delete";
                        delBtn.textContent = "×";
                        delBtn.addEventListener("click", () => {
                            arrayContainer.removeChild(wrapper);
                        });

                        wrapper.appendChild(input);

                        if (itemTypes.includes("boolean")) {
                            const hidden = document.createElement("input");
                            hidden.type = "hidden";
                            hidden.name = keyValidation.value;
                            hidden.value = "false";
                            wrapper.appendChild(hidden);
                        }

                        wrapper.appendChild(delBtn);
                        return wrapper;
                    }

                    const addBtn = document.createElement("button");
                    addBtn.type = "button";
                    addBtn.className =
                        "mt-2 px-2 py-1 bg-indigo-500 text-white rounded hover:bg-indigo-600 focus:outline-none";
                    addBtn.textContent = "Add items";
                    addBtn.addEventListener("click", () => {
                        arrayContainer.appendChild(createArrayInput());
                    });

                    if (Array.isArray(prop.default)) {
                        if (prop.default.length > 0) {
                            prop.default.forEach((val) => {
                                arrayContainer.appendChild(
                                    createArrayInput(val),
                                );
                            });
                        } else {
                            // Create one empty input for empty default arrays
                            arrayContainer.appendChild(createArrayInput());
                        }
                    } else {
                        arrayContainer.appendChild(createArrayInput());
                    }

                    fieldDiv.appendChild(arrayContainer);
                    fieldDiv.appendChild(addBtn);
                } else {
                    // Input field with validation (with multiline support)
                    let fieldInput;
                    const isTextType = prop.type === "text";
                    if (isTextType) {
                        fieldInput = document.createElement("textarea");
                        fieldInput.rows = 4;
                    } else {
                        fieldInput = document.createElement("input");
                        if (prop.type === "number" || prop.type === "integer") {
                            fieldInput.type = "number";
                        } else if (prop.type === "boolean") {
                            fieldInput.type = "checkbox";
                            fieldInput.value = "true";
                        } else {
                            fieldInput = document.createElement("textarea");
                            fieldInput.rows = 1;
                        }
                    }

                    fieldInput.name = keyValidation.value;
                    fieldInput.required =
                        schema.required && schema.required.includes(key);
                    fieldInput.className =
                        prop.type === "boolean"
                            ? "mt-1 h-4 w-4 text-indigo-600 dark:text-indigo-200 border border-gray-300 rounded"
                            : "mt-1 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 text-gray-700 dark:text-gray-300 dark:border-gray-700 dark:focus:border-indigo-400 dark:focus:ring-indigo-400";

                    // Set default values here
                    if (prop.default !== undefined) {
                        if (fieldInput.type === "checkbox") {
                            fieldInput.checked = prop.default === true;
                        } else if (isTextType) {
                            fieldInput.value = prop.default;
                        } else {
                            fieldInput.value = prop.default;
                        }
                    }

                    fieldDiv.appendChild(fieldInput);
                    if (prop.default !== undefined) {
                        if (fieldInput.type === "checkbox") {
                            const hiddenInput = document.createElement("input");
                            hiddenInput.type = "hidden";
                            hiddenInput.value = "false";
                            hiddenInput.name = keyValidation.value;
                            fieldDiv.appendChild(hiddenInput);
                        }
                    }
                }

                container.appendChild(fieldDiv);
            }
        }

        openModal("tool-test-modal");
        console.log("✓ Tool test modal loaded successfully");
    } catch (error) {
        console.error("Error fetching tool details for testing:", error);

        // Clean up state on error
        toolTestState.activeRequests.delete(toolId);

        let errorMessage = error.message;

        // Enhanced error handling for rapid clicking scenarios
        if (error.name === "AbortError") {
            errorMessage = "Request was cancelled. Please try again.";
        } else if (
            error.message.includes("Failed to fetch") ||
            error.message.includes("NetworkError")
        ) {
            errorMessage =
                "Unable to connect to the server. Please wait a moment and try again.";
        } else if (
            error.message.includes("empty response") ||
            error.message.includes("ERR_EMPTY_RESPONSE")
        ) {
            errorMessage =
                "The server returned an empty response. Please wait a moment and try again.";
        } else if (error.message.includes("timeout")) {
            errorMessage =
                "Request timed out. Please try again in a few seconds.";
        }

        showErrorMessage(errorMessage);
    } finally {
        // 8. ALWAYS RESTORE BUTTON STATE
        const testButton = document.querySelector(
            `[onclick*="testTool('${toolId}')"]`,
        );
        if (testButton) {
            testButton.disabled = false;
            testButton.textContent = "Test";
            testButton.classList.remove("opacity-50", "cursor-not-allowed");
        }
    }
}

async function runToolTest() {
    const form = safeGetElement("tool-test-form");
    const loadingElement = safeGetElement("tool-test-loading");
    const resultContainer = safeGetElement("tool-test-result");
    const runButton = document.querySelector('button[onclick="runToolTest()"]');

    if (!form || !AppState.currentTestTool) {
        console.error("Tool test form or current tool not found");
        showErrorMessage("Tool test form not available");
        return;
    }

    // Prevent multiple concurrent test runs
    if (runButton && runButton.disabled) {
        console.log("Tool test already running");
        return;
    }

    try {
        // Disable run button
        if (runButton) {
            runButton.disabled = true;
            runButton.textContent = "Running...";
            runButton.classList.add("opacity-50");
        }

        // Show loading
        if (loadingElement) {
            loadingElement.style.display = "block";
        }
        if (resultContainer) {
            resultContainer.innerHTML = "";
        }

        const formData = new FormData(form);
        const params = {};

        const schema = toolInputSchemaRegistry.inputSchema;

        if (schema && schema.properties) {
            for (const key in schema.properties) {
                const prop = schema.properties[key];
                const keyValidation = validateInputName(key, "parameter");
                if (!keyValidation.valid) {
                    console.warn(`Skipping invalid parameter: ${key}`);
                    continue;
                }
                let value;
                if (prop.type === "array") {
                    const inputValues = formData.getAll(key);
                    try {
                        // Convert values based on the items schema type
                        if (prop.items) {
                            const itemType = Array.isArray(prop.items.anyOf)
                                ? prop.items.anyOf.map((t) => t.type)
                                : [prop.items.type];

                            if (
                                itemType.includes("number") ||
                                itemType.includes("integer")
                            ) {
                                value = inputValues.map((v) => {
                                    const num = Number(v);
                                    if (isNaN(num)) {
                                        throw new Error(`Invalid number: ${v}`);
                                    }
                                    return num;
                                });
                            } else if (itemType.includes("boolean")) {
                                value = inputValues.map(
                                    (v) => v === "true" || v === true,
                                );
                            } else if (itemType.includes("object")) {
                                value = inputValues.map((v) => {
                                    try {
                                        const parsed = JSON.parse(v);
                                        if (
                                            typeof parsed !== "object" ||
                                            Array.isArray(parsed)
                                        ) {
                                            throw new Error(
                                                "Value must be an object",
                                            );
                                        }
                                        return parsed;
                                    } catch {
                                        throw new Error(
                                            `Invalid object format for ${key}`,
                                        );
                                    }
                                });
                            } else {
                                value = inputValues;
                            }
                        }

                        // Handle empty values
                        if (
                            value.length === 0 ||
                            (value.length === 1 && value[0] === "")
                        ) {
                            if (
                                schema.required &&
                                schema.required.includes(key)
                            ) {
                                params[keyValidation.value] = [];
                            }
                            continue;
                        }
                        params[keyValidation.value] = value;
                    } catch (error) {
                        console.error(
                            `Error parsing array values for ${key}:`,
                            error,
                        );
                        showErrorMessage(
                            `Invalid input format for ${key}. Please check the values are in correct format.`,
                        );
                        throw error;
                    }
                } else {
                    value = formData.get(key);
                    if (value === null || value === undefined || value === "") {
                        if (schema.required && schema.required.includes(key)) {
                            params[keyValidation.value] = "";
                        }
                        continue;
                    }
                    if (prop.type === "number" || prop.type === "integer") {
                        params[keyValidation.value] = Number(value);
                    } else if (prop.type === "boolean") {
                        params[keyValidation.value] =
                            value === "true" || value === true;
                    } else if (prop.enum) {
                        if (prop.enum.includes(value)) {
                            params[keyValidation.value] = value;
                        }
                    } else {
                        params[keyValidation.value] = value;
                    }
                }
            }
        }

        const payload = {
            jsonrpc: "2.0",
            id: Date.now(),
            method: AppState.currentTestTool.name,
            params,
        };

        // Parse custom headers from the passthrough headers field
        const requestHeaders = {
            "Content-Type": "application/json",
        };

        // Authentication will be handled automatically by the JWT cookie
        // that was set when the admin UI loaded. The 'credentials: "include"'
        // in the fetch request ensures the cookie is sent with the request.

        const passthroughHeadersField = document.getElementById(
            "test-passthrough-headers",
        );
        if (passthroughHeadersField && passthroughHeadersField.value.trim()) {
            const headerLines = passthroughHeadersField.value
                .trim()
                .split("\n");
            for (const line of headerLines) {
                const trimmedLine = line.trim();
                if (trimmedLine) {
                    const colonIndex = trimmedLine.indexOf(":");
                    if (colonIndex > 0) {
                        const headerName = trimmedLine
                            .substring(0, colonIndex)
                            .trim();
                        const headerValue = trimmedLine
                            .substring(colonIndex + 1)
                            .trim();

                        // Validate header name and value
                        const validation = validatePassthroughHeader(
                            headerName,
                            headerValue,
                        );
                        if (!validation.valid) {
                            showErrorMessage(
                                `Invalid header: ${validation.error}`,
                            );
                            return;
                        }

                        if (headerName && headerValue) {
                            requestHeaders[headerName] = headerValue;
                        }
                    } else if (colonIndex === -1) {
                        showErrorMessage(
                            `Invalid header format: "${trimmedLine}". Expected format: "Header-Name: Value"`,
                        );
                        return;
                    }
                }
            }
        }

        // Use longer timeout for test execution
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/rpc`,
            {
                method: "POST",
                headers: requestHeaders,
                body: JSON.stringify(payload),
                credentials: "include",
            },
            window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000, // Use configurable timeout
        );

        const result = await response.json();
        const resultStr = JSON.stringify(result, null, 2);

        if (resultContainer && window.CodeMirror) {
            try {
                AppState.toolTestResultEditor = window.CodeMirror(
                    resultContainer,
                    {
                        value: resultStr,
                        mode: "application/json",
                        theme: "monokai",
                        readOnly: true,
                        lineNumbers: true,
                    },
                );
            } catch (editorError) {
                console.error("Error creating CodeMirror editor:", editorError);
                // Fallback to plain text
                const pre = document.createElement("pre");
                pre.className =
                    "bg-gray-900 text-green-400 p-4 rounded overflow-auto max-h-96";
                pre.textContent = resultStr;
                resultContainer.appendChild(pre);
            }
        } else if (resultContainer) {
            const pre = document.createElement("pre");
            pre.className =
                "bg-gray-100 p-4 rounded overflow-auto max-h-96 dark:bg-gray-800 dark:text-gray-100";
            pre.textContent = resultStr;
            resultContainer.appendChild(pre);
        }

        console.log("✓ Tool test completed successfully");
    } catch (error) {
        console.error("Tool test error:", error);
        if (resultContainer) {
            const errorMessage = handleFetchError(error, "run tool test");
            const errorDiv = document.createElement("div");
            errorDiv.className = "text-red-600 p-4";
            errorDiv.textContent = `Error: ${errorMessage}`;
            resultContainer.appendChild(errorDiv);
        }
    } finally {
        // Always restore UI state
        if (loadingElement) {
            loadingElement.style.display = "none";
        }
        if (runButton) {
            runButton.disabled = false;
            runButton.textContent = "Run Tool";
            runButton.classList.remove("opacity-50");
        }
    }
}

/**
 * NEW: Cleanup function for tool test state
 */
function cleanupToolTestState() {
    // Cancel all active requests
    for (const [toolId, controller] of toolTestState.activeRequests) {
        try {
            controller.abort();
            console.log(`Cancelled request for tool ${toolId}`);
        } catch (error) {
            console.warn(`Error cancelling request for tool ${toolId}:`, error);
        }
    }

    // Clear all state
    toolTestState.activeRequests.clear();
    toolTestState.lastRequestTime.clear();

    console.log("✓ Tool test state cleaned up");
}

/**
 * NEW: Tool test modal specific cleanup
 */
function cleanupToolTestModal() {
    try {
        // Clear current test tool
        AppState.currentTestTool = null;

        // Clear result editor
        if (AppState.toolTestResultEditor) {
            try {
                AppState.toolTestResultEditor.toTextArea();
                AppState.toolTestResultEditor = null;
            } catch (error) {
                console.warn(
                    "Error cleaning up tool test result editor:",
                    error,
                );
            }
        }

        // Reset form
        const form = safeGetElement("tool-test-form");
        if (form) {
            form.reset();
        }

        // Clear result container
        const resultContainer = safeGetElement("tool-test-result");
        if (resultContainer) {
            resultContainer.innerHTML = "";
        }

        // Hide loading
        const loadingElement = safeGetElement("tool-test-loading");
        if (loadingElement) {
            loadingElement.style.display = "none";
        }

        console.log("✓ Tool test modal cleaned up");
    } catch (error) {
        console.error("Error cleaning up tool test modal:", error);
    }
}

// ===================================================================
// PROMPT TEST FUNCTIONALITY
// ===================================================================

// State management for prompt testing
const promptTestState = {
    lastRequestTime: new Map(),
    activeRequests: new Set(),
    currentTestPrompt: null,
};

/**
 * Test a prompt by opening the prompt test modal
 */
async function testPrompt(promptName) {
    try {
        console.log(`Testing prompt: ${promptName}`);

        // Debouncing to prevent rapid clicking
        const now = Date.now();
        const lastRequest =
            promptTestState.lastRequestTime.get(promptName) || 0;
        const timeSinceLastRequest = now - lastRequest;
        const debounceDelay = 1000;

        if (timeSinceLastRequest < debounceDelay) {
            console.log(`Prompt ${promptName} test request debounced`);
            return;
        }

        // Check if modal is already active
        if (AppState.isModalActive("prompt-test-modal")) {
            console.warn("Prompt test modal is already active");
            return;
        }

        // Update button state
        const testButton = document.querySelector(
            `[onclick*="testPrompt('${promptName}')"]`,
        );
        if (testButton) {
            if (testButton.disabled) {
                console.log(
                    "Test button already disabled, request in progress",
                );
                return;
            }
            testButton.disabled = true;
            testButton.textContent = "Loading...";
            testButton.classList.add("opacity-50", "cursor-not-allowed");
        }

        // Record request time and mark as active
        promptTestState.lastRequestTime.set(promptName, now);
        promptTestState.activeRequests.add(promptName);

        // Fetch prompt details
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000);

        try {
            // Fetch prompt details from the prompts endpoint (view mode)
            const response = await fetch(
                `${window.ROOT_PATH}/admin/prompts/${encodeURIComponent(promptName)}`,
                {
                    method: "GET",
                    headers: {
                        Accept: "application/json",
                    },
                    credentials: "include",
                    signal: controller.signal,
                },
            );

            clearTimeout(timeoutId);

            if (!response.ok) {
                throw new Error(
                    `Failed to fetch prompt details: ${response.status} ${response.statusText}`,
                );
            }

            const prompt = await response.json();
            promptTestState.currentTestPrompt = prompt;

            // Set modal title and description
            const titleElement = safeGetElement("prompt-test-modal-title");
            const descElement = safeGetElement("prompt-test-modal-description");

            if (titleElement) {
                titleElement.textContent = `Test Prompt: ${prompt.name || promptName}`;
            }
            if (descElement) {
                if (prompt.description) {
                    // Escape HTML and then replace newlines with <br/> tags
                    descElement.innerHTML = escapeHtml(
                        prompt.description,
                    ).replace(/\n/g, "<br/>");
                } else {
                    descElement.textContent = "No description available.";
                }
            }

            // Build form fields based on prompt arguments
            buildPromptTestForm(prompt);

            // Open the modal
            openModal("prompt-test-modal");
        } catch (error) {
            clearTimeout(timeoutId);

            if (error.name === "AbortError") {
                console.warn("Request was cancelled (timeout or user action)");
                showErrorMessage("Request timed out. Please try again.");
            } else {
                console.error("Error fetching prompt details:", error);
                const errorMessage =
                    error.message || "Failed to load prompt details";
                showErrorMessage(`Error testing prompt: ${errorMessage}`);
            }
        }
    } catch (error) {
        console.error("Error in testPrompt:", error);
        showErrorMessage(`Error testing prompt: ${error.message}`);
    } finally {
        // Always restore button state
        const testButton = document.querySelector(
            `[onclick*="testPrompt('${promptName}')"]`,
        );
        if (testButton) {
            testButton.disabled = false;
            testButton.textContent = "Test";
            testButton.classList.remove("opacity-50", "cursor-not-allowed");
        }

        // Clean up state
        promptTestState.activeRequests.delete(promptName);
    }
}

/**
 * Build the form fields for prompt testing based on prompt arguments
 */
function buildPromptTestForm(prompt) {
    const fieldsContainer = safeGetElement("prompt-test-form-fields");
    if (!fieldsContainer) {
        console.error("Prompt test form fields container not found");
        return;
    }

    // Clear existing fields
    fieldsContainer.innerHTML = "";

    if (!prompt.arguments || prompt.arguments.length === 0) {
        fieldsContainer.innerHTML = `
            <div class="text-gray-500 dark:text-gray-400 text-sm italic">
                This prompt has no arguments - it will render as-is.
            </div>
        `;
        return;
    }

    // Create fields for each prompt argument
    prompt.arguments.forEach((arg, index) => {
        const fieldDiv = document.createElement("div");
        fieldDiv.className = "space-y-2";

        const label = document.createElement("label");
        label.className =
            "block text-sm font-medium text-gray-700 dark:text-gray-300";
        label.textContent = `${arg.name}${arg.required ? " *" : ""}`;

        const input = document.createElement("input");
        input.type = "text";
        input.id = `prompt-arg-${index}`;
        input.name = `arg-${arg.name}`;
        input.className =
            "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-300";

        if (arg.description) {
            input.placeholder = arg.description;
        }

        if (arg.required) {
            input.required = true;
        }

        fieldDiv.appendChild(label);
        if (arg.description) {
            const description = document.createElement("div");
            description.className = "text-xs text-gray-500 dark:text-gray-400";
            description.textContent = arg.description;
            fieldDiv.appendChild(description);
        }
        fieldDiv.appendChild(input);

        fieldsContainer.appendChild(fieldDiv);
    });
}

/**
 * Run the prompt test by calling the API with the provided arguments
 */
async function runPromptTest() {
    const form = safeGetElement("prompt-test-form");
    const loadingElement = safeGetElement("prompt-test-loading");
    const resultContainer = safeGetElement("prompt-test-result");
    const runButton = document.querySelector(
        'button[onclick="runPromptTest()"]',
    );

    if (!form || !promptTestState.currentTestPrompt) {
        console.error("Prompt test form or current prompt not found");
        showErrorMessage("Prompt test form not available");
        return;
    }

    // Prevent multiple concurrent test runs
    if (runButton && runButton.disabled) {
        console.log("Prompt test already running");
        return;
    }

    try {
        // Disable button and show loading
        if (runButton) {
            runButton.disabled = true;
            runButton.textContent = "Rendering...";
        }
        if (loadingElement) {
            loadingElement.classList.remove("hidden");
        }
        if (resultContainer) {
            resultContainer.innerHTML = `
                <div class="text-gray-500 dark:text-gray-400 text-sm italic">
                    Rendering prompt...
                </div>
            `;
        }

        // Collect form data (prompt arguments)
        const formData = new FormData(form);
        const args = {};

        // Parse the form data into arguments object
        for (const [key, value] of formData.entries()) {
            if (key.startsWith("arg-")) {
                const argName = key.substring(4); // Remove 'arg-' prefix
                args[argName] = value;
            }
        }

        // Call the prompt API endpoint
        const response = await fetch(
            `${window.ROOT_PATH}/prompts/${encodeURIComponent(promptTestState.currentTestPrompt.name)}`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                credentials: "include",
                body: JSON.stringify(args),
            },
        );

        if (!response.ok) {
            let errorMessage;
            try {
                const errorData = await response.json();
                errorMessage =
                    errorData.message ||
                    `HTTP ${response.status}: ${response.statusText}`;

                // Show more detailed error information
                if (errorData.details) {
                    errorMessage += `\nDetails: ${errorData.details}`;
                }
            } catch {
                errorMessage = `HTTP ${response.status}: ${response.statusText}`;
            }
            throw new Error(errorMessage);
        }

        const result = await response.json();

        // Display the result
        if (resultContainer) {
            let resultHtml = "";

            if (result.messages && Array.isArray(result.messages)) {
                result.messages.forEach((message, index) => {
                    resultHtml += `
                        <div class="mb-4 p-3 bg-white dark:bg-gray-700 rounded border">
                            <div class="text-sm font-medium text-gray-600 dark:text-gray-300 mb-2">
                                Message ${index + 1} (${message.role || "unknown"})
                            </div>
                            <div class="text-gray-900 dark:text-gray-100 whitespace-pre-wrap">${escapeHtml(message.content?.text || JSON.stringify(message.content) || "")}</div>
                        </div>
                    `;
                });
            } else {
                resultHtml = `
                    <div class="text-gray-900 dark:text-gray-100 whitespace-pre-wrap">${escapeHtml(JSON.stringify(result, null, 2))}</div>
                `;
            }

            resultContainer.innerHTML = resultHtml;
        }

        console.log("Prompt rendered successfully");
    } catch (error) {
        console.error("Error rendering prompt:", error);

        if (resultContainer) {
            resultContainer.innerHTML = `
                <div class="text-red-600 dark:text-red-400 text-sm">
                    <strong>Error:</strong> ${escapeHtml(error.message)}
                </div>
            `;
        }

        showErrorMessage(`Failed to render prompt: ${error.message}`);
    } finally {
        // Hide loading and restore button
        if (loadingElement) {
            loadingElement.classList.add("hidden");
        }
        if (runButton) {
            runButton.disabled = false;
            runButton.textContent = "Render Prompt";
        }
    }
}

/**
 * Clean up prompt test modal state
 */
function cleanupPromptTestModal() {
    try {
        // Clear current test prompt
        promptTestState.currentTestPrompt = null;

        // Reset form
        const form = safeGetElement("prompt-test-form");
        if (form) {
            form.reset();
        }

        // Clear form fields
        const fieldsContainer = safeGetElement("prompt-test-form-fields");
        if (fieldsContainer) {
            fieldsContainer.innerHTML = "";
        }

        // Clear result container
        const resultContainer = safeGetElement("prompt-test-result");
        if (resultContainer) {
            resultContainer.innerHTML = `
                <div class="text-gray-500 dark:text-gray-400 text-sm italic">
                    Click "Render Prompt" to see the rendered output
                </div>
            `;
        }

        // Hide loading
        const loadingElement = safeGetElement("prompt-test-loading");
        if (loadingElement) {
            loadingElement.classList.add("hidden");
        }

        console.log("✓ Prompt test modal cleaned up");
    } catch (error) {
        console.error("Error cleaning up prompt test modal:", error);
    }
}

// ===================================================================
// ENHANCED GATEWAY TEST FUNCTIONALITY
// ===================================================================

let gatewayTestHeadersEditor = null;
let gatewayTestBodyEditor = null;
let gatewayTestFormHandler = null;
let gatewayTestCloseHandler = null;

async function testGateway(gatewayURL) {
    try {
        console.log("Opening gateway test modal for:", gatewayURL);

        // Validate URL
        const urlValidation = validateUrl(gatewayURL);
        if (!urlValidation.valid) {
            showErrorMessage(`Invalid gateway URL: ${urlValidation.error}`);
            return;
        }

        // Clean up any existing event listeners first
        cleanupGatewayTestModal();

        // Open the modal
        openModal("gateway-test-modal");

        // Initialize CodeMirror editors if they don't exist
        if (!gatewayTestHeadersEditor) {
            const headersElement = safeGetElement("gateway-test-headers");
            if (headersElement && window.CodeMirror) {
                gatewayTestHeadersEditor = window.CodeMirror.fromTextArea(
                    headersElement,
                    {
                        mode: "application/json",
                        lineNumbers: true,
                        lineWrapping: true,
                    },
                );
                gatewayTestHeadersEditor.setSize(null, 100);
                console.log("✓ Initialized gateway test headers editor");
            }
        }

        if (!gatewayTestBodyEditor) {
            const bodyElement = safeGetElement("gateway-test-body");
            if (bodyElement && window.CodeMirror) {
                gatewayTestBodyEditor = window.CodeMirror.fromTextArea(
                    bodyElement,
                    {
                        mode: "application/json",
                        lineNumbers: true,
                        lineWrapping: true,
                    },
                );
                gatewayTestBodyEditor.setSize(null, 100);
                console.log("✓ Initialized gateway test body editor");
            }
        }

        // Set form action and URL
        const form = safeGetElement("gateway-test-form");
        const urlInput = safeGetElement("gateway-test-url");

        if (form) {
            form.action = `${window.ROOT_PATH}/admin/gateways/test`;
        }
        if (urlInput) {
            urlInput.value = urlValidation.value;
        }

        // Set up form submission handler
        if (form) {
            gatewayTestFormHandler = async (e) => {
                await handleGatewayTestSubmit(e);
            };
            form.addEventListener("submit", gatewayTestFormHandler);
        }

        // Set up close button handler
        const closeButton = safeGetElement("gateway-test-close");
        if (closeButton) {
            gatewayTestCloseHandler = () => {
                handleGatewayTestClose();
            };
            closeButton.addEventListener("click", gatewayTestCloseHandler);
        }
    } catch (error) {
        console.error("Error setting up gateway test modal:", error);
        showErrorMessage("Failed to open gateway test modal");
    }
}

async function handleGatewayTestSubmit(e) {
    e.preventDefault();

    const loading = safeGetElement("gateway-test-loading");
    const responseDiv = safeGetElement("gateway-test-response-json");
    const resultDiv = safeGetElement("gateway-test-result");
    const testButton = safeGetElement("gateway-test-submit");

    try {
        // Show loading
        if (loading) {
            loading.classList.remove("hidden");
        }
        if (resultDiv) {
            resultDiv.classList.add("hidden");
        }
        if (testButton) {
            testButton.disabled = true;
            testButton.textContent = "Testing...";
        }

        const form = e.target;
        const url = form.action;

        // Get form data with validation
        const formData = new FormData(form);
        const baseUrl = formData.get("url");
        const method = formData.get("method");
        const path = formData.get("path");

        // Validate URL
        const urlValidation = validateUrl(baseUrl);
        if (!urlValidation.valid) {
            throw new Error(`Invalid URL: ${urlValidation.error}`);
        }

        // Get CodeMirror content safely
        let headersRaw = "";
        let bodyRaw = "";

        if (gatewayTestHeadersEditor) {
            try {
                headersRaw = gatewayTestHeadersEditor.getValue() || "";
            } catch (error) {
                console.error("Error getting headers value:", error);
            }
        }

        if (gatewayTestBodyEditor) {
            try {
                bodyRaw = gatewayTestBodyEditor.getValue() || "";
            } catch (error) {
                console.error("Error getting body value:", error);
            }
        }

        // Validate and parse JSON safely
        const headersValidation = validateJson(headersRaw, "Headers");
        const bodyValidation = validateJson(bodyRaw, "Body");

        if (!headersValidation.valid) {
            throw new Error(headersValidation.error);
        }

        if (!bodyValidation.valid) {
            throw new Error(bodyValidation.error);
        }

        const payload = {
            base_url: urlValidation.value,
            method,
            path,
            headers: headersValidation.value,
            body: bodyValidation.value,
        };

        // Make the request with timeout
        const response = await fetchWithTimeout(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        const result = await response.json();

        const isSuccess =
            result.statusCode &&
            result.statusCode >= 200 &&
            result.statusCode < 300;

        const alertType = isSuccess ? "success" : "error";
        const icon = isSuccess ? "✅" : "❌";
        const title = isSuccess ? "Connection Successful" : "Connection Failed";
        const statusCode = result.statusCode || "Unknown";
        const latency =
            result.latencyMs != null ? `${result.latencyMs}ms` : "NA";
        const body = result.body
            ? `<details open>
                <summary class='cursor-pointer'><strong>Response Body</strong></summary>
                <pre class="text-sm px-4 max-h-96 dark:bg-gray-800 dark:text-gray-100 overflow-auto">${JSON.stringify(result.body, null, 2)}</pre>
            </details>`
            : "";

        responseDiv.innerHTML = `
        <div class="alert alert-${alertType}">
            <h4><strong>${icon} ${title}</strong></h4>
            <p><strong>Status Code:</strong> ${statusCode}</p>
            <p><strong>Response Time:</strong> ${latency}</p>
            ${body}
        </div>
        `;
    } catch (error) {
        console.error("Gateway test error:", error);
        if (responseDiv) {
            const errorDiv = document.createElement("div");
            errorDiv.className = "text-red-600 p-4";
            errorDiv.textContent = `❌ Error: ${error.message}`;
            responseDiv.innerHTML = "";
            responseDiv.appendChild(errorDiv);
        }
    } finally {
        if (loading) {
            loading.classList.add("hidden");
        }
        if (resultDiv) {
            resultDiv.classList.remove("hidden");
        }

        testButton.disabled = false;
        testButton.textContent = "Test";
    }
}

function handleGatewayTestClose() {
    try {
        // Reset form
        const form = safeGetElement("gateway-test-form");
        if (form) {
            form.reset();
        }

        // Clear editors
        if (gatewayTestHeadersEditor) {
            try {
                gatewayTestHeadersEditor.setValue("");
            } catch (error) {
                console.error("Error clearing headers editor:", error);
            }
        }

        if (gatewayTestBodyEditor) {
            try {
                gatewayTestBodyEditor.setValue("");
            } catch (error) {
                console.error("Error clearing body editor:", error);
            }
        }

        // Clear response
        const responseDiv = safeGetElement("gateway-test-response-json");
        const resultDiv = safeGetElement("gateway-test-result");

        if (responseDiv) {
            responseDiv.innerHTML = "";
        }
        if (resultDiv) {
            resultDiv.classList.add("hidden");
        }

        // Close modal
        closeModal("gateway-test-modal");
    } catch (error) {
        console.error("Error closing gateway test modal:", error);
    }
}

function cleanupGatewayTestModal() {
    try {
        const form = safeGetElement("gateway-test-form");
        const closeButton = safeGetElement("gateway-test-close");

        // Remove existing event listeners
        if (form && gatewayTestFormHandler) {
            form.removeEventListener("submit", gatewayTestFormHandler);
            gatewayTestFormHandler = null;
        }

        if (closeButton && gatewayTestCloseHandler) {
            closeButton.removeEventListener("click", gatewayTestCloseHandler);
            gatewayTestCloseHandler = null;
        }

        console.log("✓ Cleaned up gateway test modal listeners");
    } catch (error) {
        console.error("Error cleaning up gateway test modal:", error);
    }
}

// ===================================================================
// ENHANCED TOOL VIEWING with Secure Display
// ===================================================================

/**
 * SECURE: View Tool function with safe display
 */
async function viewTool(toolId) {
    try {
        console.log(`Fetching tool details for ID: ${toolId}`);

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/tools/${toolId}`,
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const tool = await response.json();

        // Build auth HTML safely with new styling
        let authHTML = "";
        if (tool.auth?.username && tool.auth?.password) {
            authHTML = `
        <span class="font-medium text-gray-700 dark:text-gray-300">Authentication Type:</span>
        <div class="mt-1 text-sm">
          <div class="text-gray-600 dark:text-gray-400">Basic Authentication</div>
          <div class="mt-1">Username: <span class="auth-username font-medium"></span></div>
          <div>Password: <span class="font-medium">********</span></div>
        </div>
      `;
        } else if (tool.auth?.token) {
            authHTML = `
        <span class="font-medium text-gray-700 dark:text-gray-300">Authentication Type:</span>
        <div class="mt-1 text-sm">
          <div class="text-gray-600 dark:text-gray-400">Bearer Token</div>
          <div class="mt-1">Token: <span class="font-medium">********</span></div>
        </div>
      `;
        } else if (tool.auth?.authHeaderKey && tool.auth?.authHeaderValue) {
            authHTML = `
        <span class="font-medium text-gray-700 dark:text-gray-300">Authentication Type:</span>
        <div class="mt-1 text-sm">
          <div class="text-gray-600 dark:text-gray-400">Custom Headers</div>
          <div class="mt-1">Header: <span class="auth-header-key font-medium"></span></div>
          <div>Value: <span class="font-medium">********</span></div>
        </div>
      `;
        } else {
            authHTML = `
        <span class="font-medium text-gray-700 dark:text-gray-300">Authentication Type:</span>
        <div class="mt-1 text-sm">None</div>
      `;
        }

        // Create annotation badges safely - NO ESCAPING since we're using textContent
        const renderAnnotations = (annotations) => {
            if (!annotations || Object.keys(annotations).length === 0) {
                return '<p><strong>Annotations:</strong> <span class="text-gray-600 dark:text-gray-300">None</span></p>';
            }

            const badges = [];

            // Show title if present
            if (annotations.title) {
                badges.push(
                    '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 mr-1 mb-1 annotation-title"></span>',
                );
            }

            // Show behavior hints with appropriate colors
            if (annotations.readOnlyHint === true) {
                badges.push(
                    '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 mr-1 mb-1">📖 Read-Only</span>',
                );
            }

            if (annotations.destructiveHint === true) {
                badges.push(
                    '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 mr-1 mb-1">⚠️ Destructive</span>',
                );
            }

            if (annotations.idempotentHint === true) {
                badges.push(
                    '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-800 mr-1 mb-1">🔄 Idempotent</span>',
                );
            }

            if (annotations.openWorldHint === true) {
                badges.push(
                    '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 mr-1 mb-1">🌐 External Access</span>',
                );
            }

            // Show any other custom annotations
            Object.keys(annotations).forEach((key) => {
                if (
                    ![
                        "title",
                        "readOnlyHint",
                        "destructiveHint",
                        "idempotentHint",
                        "openWorldHint",
                    ].includes(key)
                ) {
                    const value = annotations[key];
                    badges.push(
                        `<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:text-gray-200 mr-1 mb-1 custom-annotation" data-key="${key}" data-value="${value}"></span>`,
                    );
                }
            });

            return `
        <div>
          <strong>Annotations:</strong>
          <div class="mt-1 flex flex-wrap">
            ${badges.join("")}
          </div>
        </div>
      `;
        };

        const toolDetailsDiv = safeGetElement("tool-details");
        if (toolDetailsDiv) {
            // Create structure safely without double-escaping
            const safeHTML = `
        <div class="bg-transparent dark:bg-transparent dark:text-gray-300">
          <!-- Two Column Layout for Main Info -->
          <div class="grid grid-cols-2 gap-6 mb-6">
            <!-- Left Column -->
            <div class="space-y-3">
              <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">Display Name:</span>
                <div class="mt-1 tool-display-name font-medium"></div>
              </div>
              <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">Technical Name:</span>
                <div class="mt-1 tool-name text-sm"></div>
              </div>
              <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">URL:</span>
                <div class="mt-1 tool-url text-sm"></div>
              </div>
              <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">Type:</span>
                <div class="mt-1 tool-type text-sm"></div>
              </div>
            </div>
            <!-- Right Column -->
            <div class="space-y-3">
              <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">Description:</span>
                <div class="mt-1 tool-description text-sm"></div>
              </div>
              <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">Tags:</span>
                <div class="mt-1 tool-tags text-sm"></div>
              </div>
              <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">Request Type:</span>
                <div class="mt-1 tool-request-type text-sm"></div>
              </div>
              <div class="auth-info">
                ${authHTML}
              </div>
            </div>
          </div>

          <!-- Annotations Section -->
          <div class="mb-6">
            ${renderAnnotations(tool.annotations)}
          </div>

          <!-- Technical Details Section -->
          <div class="space-y-4">
            <div>
              <strong class="text-gray-700 dark:text-gray-300">Headers:</strong>
              <pre class="mt-1 bg-gray-100 p-3 rounded text-xs dark:bg-gray-800 dark:text-gray-200 tool-headers overflow-x-auto"></pre>
            </div>
            <div>
              <strong class="text-gray-700 dark:text-gray-300">Input Schema:</strong>
              <pre class="mt-1 bg-gray-100 p-3 rounded text-xs dark:bg-gray-800 dark:text-gray-200 tool-schema overflow-x-auto"></pre>
            </div>
          </div>

          <!-- Metrics Section -->
          <div class="mt-6 pt-4 border-t border-gray-200 dark:border-gray-600">
            <strong class="text-gray-700 dark:text-gray-300">Metrics:</strong>
            <div class="grid grid-cols-2 gap-4 mt-3 text-sm">
              <div class="space-y-2">
                <div class="flex justify-between">
                  <span class="text-gray-600 dark:text-gray-400">Total Executions:</span>
                  <span class="metric-total font-medium"></span>
                </div>
                <div class="flex justify-between">
                  <span class="text-gray-600 dark:text-gray-400">Successful Executions:</span>
                  <span class="metric-success font-medium text-green-600"></span>
                </div>
                <div class="flex justify-between">
                  <span class="text-gray-600 dark:text-gray-400">Failed Executions:</span>
                  <span class="metric-failed font-medium text-red-600"></span>
                </div>
                <div class="flex justify-between">
                  <span class="text-gray-600 dark:text-gray-400">Failure Rate:</span>
                  <span class="metric-failure-rate font-medium"></span>
                </div>
              </div>
              <div class="space-y-2">
                <div class="flex justify-between">
                  <span class="text-gray-600 dark:text-gray-400">Min Response Time:</span>
                  <span class="metric-min-time font-medium"></span>
                </div>
                <div class="flex justify-between">
                  <span class="text-gray-600 dark:text-gray-400">Max Response Time:</span>
                  <span class="metric-max-time font-medium"></span>
                </div>
                <div class="flex justify-between">
                  <span class="text-gray-600 dark:text-gray-400">Average Response Time:</span>
                  <span class="metric-avg-time font-medium"></span>
                </div>
                <div class="flex justify-between">
                  <span class="text-gray-600 dark:text-gray-400">Last Execution Time:</span>
                  <span class="metric-last-time font-medium"></span>
                </div>
              </div>
            </div>
          </div>
          <div class="mt-6 border-t pt-4">
            <strong>Metadata:</strong>
            <div class="grid grid-cols-2 gap-4 mt-2 text-sm">
              <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Created By:</span>
                <span class="ml-2 metadata-created-by"></span>
              </div>
              <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Created At:</span>
                <span class="ml-2 metadata-created-at"></span>
              </div>
              <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Created From:</span>
                <span class="ml-2 metadata-created-from"></span>
              </div>
              <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Created Via:</span>
                <span class="ml-2 metadata-created-via"></span>
              </div>
              <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Last Modified By:</span>
                <span class="ml-2 metadata-modified-by"></span>
              </div>
              <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Last Modified At:</span>
                <span class="ml-2 metadata-modified-at"></span>
              </div>
              <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Version:</span>
                <span class="ml-2 metadata-version"></span>
              </div>
              <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Import Batch:</span>
                <span class="ml-2 metadata-import-batch"></span>
              </div>
            </div>
          </div>
        </div>
      `;

            // Set structure first
            safeSetInnerHTML(toolDetailsDiv, safeHTML, true);

            // Now safely set text content - NO ESCAPING since textContent is safe
            const setTextSafely = (selector, value) => {
                const element = toolDetailsDiv.querySelector(selector);
                if (element) {
                    element.textContent = value || "N/A";
                }
            };

            setTextSafely(
                ".tool-display-name",
                tool.displayName || tool.customName || tool.name,
            );
            setTextSafely(".tool-name", tool.name);
            setTextSafely(".tool-url", tool.url);
            setTextSafely(".tool-type", tool.integrationType);
            setTextSafely(".tool-description", tool.description);

            // Set tags as HTML with badges
            const tagsElement = toolDetailsDiv.querySelector(".tool-tags");
            if (tagsElement) {
                if (tool.tags && tool.tags.length > 0) {
                    tagsElement.innerHTML = tool.tags
                        .map(
                            (tag) =>
                                `<span class="inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full mr-1 mb-1 dark:bg-blue-900 dark:text-blue-200">${escapeHtml(tag)}</span>`,
                        )
                        .join("");
                } else {
                    tagsElement.textContent = "None";
                }
            }

            setTextSafely(".tool-request-type", tool.requestType);
            setTextSafely(
                ".tool-headers",
                JSON.stringify(tool.headers || {}, null, 2),
            );
            setTextSafely(
                ".tool-schema",
                JSON.stringify(tool.inputSchema || {}, null, 2),
            );

            // Set auth fields safely
            if (tool.auth?.username) {
                setTextSafely(".auth-username", tool.auth.username);
            }
            if (tool.auth?.authHeaderKey) {
                setTextSafely(".auth-header-key", tool.auth.authHeaderKey);
            }

            // Set annotation title safely
            if (tool.annotations?.title) {
                setTextSafely(".annotation-title", tool.annotations.title);
            }

            // Set custom annotations safely
            const customAnnotations =
                toolDetailsDiv.querySelectorAll(".custom-annotation");
            customAnnotations.forEach((element) => {
                const key = element.dataset.key;
                const value = element.dataset.value;
                element.textContent = `${key}: ${value}`;
            });

            // Set metrics safely
            setTextSafely(".metric-total", tool.metrics?.totalExecutions ?? 0);
            setTextSafely(
                ".metric-success",
                tool.metrics?.successfulExecutions ?? 0,
            );
            setTextSafely(
                ".metric-failed",
                tool.metrics?.failedExecutions ?? 0,
            );
            setTextSafely(
                ".metric-failure-rate",
                tool.metrics?.failureRate ?? 0,
            );
            setTextSafely(
                ".metric-min-time",
                tool.metrics?.minResponseTime ?? "N/A",
            );
            setTextSafely(
                ".metric-max-time",
                tool.metrics?.maxResponseTime ?? "N/A",
            );
            setTextSafely(
                ".metric-avg-time",
                tool.metrics?.avgResponseTime ?? "N/A",
            );
            setTextSafely(
                ".metric-last-time",
                tool.metrics?.lastExecutionTime ?? "N/A",
            );

            // Set metadata fields safely with appropriate fallbacks for legacy entities
            setTextSafely(
                ".metadata-created-by",
                tool.created_by || tool.createdBy || "Legacy Entity",
            );
            setTextSafely(
                ".metadata-created-at",
                tool.created_at
                    ? new Date(tool.created_at).toLocaleString()
                    : tool.createdAt
                      ? new Date(tool.createdAt).toLocaleString()
                      : "Pre-metadata",
            );
            setTextSafely(
                ".metadata-created-from",
                tool.created_from_ip || tool.createdFromIp || "Unknown",
            );
            setTextSafely(
                ".metadata-created-via",
                tool.created_via || tool.createdVia || "Unknown",
            );
            setTextSafely(
                ".metadata-modified-by",
                tool.modified_by || tool.modifiedBy || "N/A",
            );
            setTextSafely(
                ".metadata-modified-at",
                tool.updated_at
                    ? new Date(tool.updated_at).toLocaleString()
                    : tool.updatedAt
                      ? new Date(tool.updatedAt).toLocaleString()
                      : "N/A",
            );
            setTextSafely(
                ".metadata-modified-from",
                tool.modified_from_ip || tool.modifiedFromIp || "N/A",
            );
            setTextSafely(
                ".metadata-modified-via",
                tool.modified_via || tool.modifiedVia || "N/A",
            );
            setTextSafely(".metadata-version", tool.version || "1");
            setTextSafely(
                ".metadata-import-batch",
                tool.import_batch_id || tool.importBatchId || "N/A",
            );
        }

        openModal("tool-modal");
        console.log("✓ Tool details loaded successfully");
    } catch (error) {
        console.error("Error fetching tool details:", error);
        const errorMessage = handleFetchError(error, "load tool details");
        showErrorMessage(errorMessage);
    }
}

// ===================================================================
// MISC UTILITY FUNCTIONS
// ===================================================================

function copyJsonToClipboard(sourceId) {
    const el = safeGetElement(sourceId);
    if (!el) {
        console.warn(
            `[copyJsonToClipboard] Source element "${sourceId}" not found.`,
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
        },
    );
}

// Make it available to inline onclick handlers
window.copyJsonToClipboard = copyJsonToClipboard;

// ===================================================================
// ENHANCED FORM HANDLERS with Input Validation
// ===================================================================

async function handleGatewayFormSubmit(e) {
    e.preventDefault();

    const form = e.target;
    const formData = new FormData(form);
    const status = safeGetElement("status-gateways");
    const loading = safeGetElement("add-gateway-loading");

    try {
        // Validate form inputs
        const name = formData.get("name");
        const url = formData.get("url");

        const nameValidation = validateInputName(name, "gateway");
        const urlValidation = validateUrl(url);

        if (!nameValidation.valid) {
            throw new Error(nameValidation.error);
        }

        if (!urlValidation.valid) {
            throw new Error(urlValidation.error);
        }

        if (loading) {
            loading.style.display = "block";
        }
        if (status) {
            status.textContent = "";
            status.classList.remove("error-status");
        }

        const isInactiveCheckedBool = isInactiveChecked("gateways");
        formData.append("is_inactive_checked", isInactiveCheckedBool);

        // Process passthrough headers - convert comma-separated string to array
        const passthroughHeadersString = formData.get("passthrough_headers");
        if (passthroughHeadersString && passthroughHeadersString.trim()) {
            // Split by comma and clean up each header name
            const passthroughHeaders = passthroughHeadersString
                .split(",")
                .map((header) => header.trim())
                .filter((header) => header.length > 0);

            // Validate each header name
            for (const headerName of passthroughHeaders) {
                if (!HEADER_NAME_REGEX.test(headerName)) {
                    showErrorMessage(
                        `Invalid passthrough header name: "${headerName}". Only letters, numbers, and hyphens are allowed.`,
                    );
                    return;
                }
            }

            // Remove the original string and add as JSON array
            formData.delete("passthrough_headers");
            formData.append(
                "passthrough_headers",
                JSON.stringify(passthroughHeaders),
            );
        }

        // Handle auth_headers JSON field
        const authHeadersJson = formData.get("auth_headers");
        if (authHeadersJson) {
            try {
                const authHeaders = JSON.parse(authHeadersJson);
                if (Array.isArray(authHeaders) && authHeaders.length > 0) {
                    // Remove the JSON string and add as parsed data for backend processing
                    formData.delete("auth_headers");
                    formData.append(
                        "auth_headers",
                        JSON.stringify(authHeaders),
                    );
                }
            } catch (e) {
                console.error("Invalid auth_headers JSON:", e);
            }
        }

        // Handle OAuth configuration
        const authType = formData.get("auth_type");
        if (authType === "oauth") {
            const oauthConfig = {
                grant_type: formData.get("oauth_grant_type"),
                client_id: formData.get("oauth_client_id"),
                client_secret: formData.get("oauth_client_secret"),
                token_url: formData.get("oauth_token_url"),
                scopes: formData.get("oauth_scopes")
                    ? formData
                          .get("oauth_scopes")
                          .split(" ")
                          .filter((s) => s.trim())
                    : [],
            };

            // Add authorization code specific fields
            if (oauthConfig.grant_type === "authorization_code") {
                oauthConfig.authorization_url = formData.get(
                    "oauth_authorization_url",
                );
                oauthConfig.redirect_uri = formData.get("oauth_redirect_uri");

                // Add token management options
                oauthConfig.token_management = {
                    store_tokens: formData.get("oauth_store_tokens") === "on",
                    auto_refresh: formData.get("oauth_auto_refresh") === "on",
                    refresh_threshold_seconds: 300,
                };
            }

            // Remove individual OAuth fields and add as oauth_config
            formData.delete("oauth_grant_type");
            formData.delete("oauth_client_id");
            formData.delete("oauth_client_secret");
            formData.delete("oauth_token_url");
            formData.delete("oauth_scopes");
            formData.delete("oauth_authorization_url");
            formData.delete("oauth_redirect_uri");
            formData.delete("oauth_store_tokens");
            formData.delete("oauth_auto_refresh");

            formData.append("oauth_config", JSON.stringify(oauthConfig));
        }

        formData.append("visibility", formData.get("visibility"));

        const teamId = new URL(window.location.href).searchParams.get(
            "team_id",
        );
        teamId && formData.append("team_id", teamId);

        const response = await fetch(`${window.ROOT_PATH}/admin/gateways`, {
            method: "POST",
            body: formData,
        });
        const result = await response.json();

        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to add gateway");
        } else {
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );
            const searchParams = new URLSearchParams();
            if (isInactiveCheckedBool) {
                searchParams.set("include_inactive", "true");
            }
            if (teamId) {
                searchParams.set("team_id", teamId);
            }

            const queryString = searchParams.toString();
            const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#gateways`;

            window.location.href = redirectUrl;
        }
    } catch (error) {
        console.error("Error:", error);
        if (status) {
            status.textContent = error.message || "An error occurred!";
            status.classList.add("error-status");
        }
        showErrorMessage(error.message);
    } finally {
        if (loading) {
            loading.style.display = "none";
        }
    }
}
async function handleResourceFormSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);
    const status = safeGetElement("status-resources");
    const loading = safeGetElement("add-resource-loading");
    try {
        // Validate inputs
        const name = formData.get("name");
        const uri = formData.get("uri");
        const nameValidation = validateInputName(name, "resource");
        const uriValidation = validateInputName(uri, "resource URI");

        if (!nameValidation.valid) {
            showErrorMessage(nameValidation.error);
            return;
        }

        if (!uriValidation.valid) {
            showErrorMessage(uriValidation.error);
            return;
        }

        if (loading) {
            loading.style.display = "block";
        }
        if (status) {
            status.textContent = "";
            status.classList.remove("error-status");
        }

        const isInactiveCheckedBool = isInactiveChecked("resources");
        formData.append("is_inactive_checked", isInactiveCheckedBool);

        const response = await fetch(`${window.ROOT_PATH}/admin/resources`, {
            method: "POST",
            body: formData,
        });
        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to add Resource");
        } else {
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );

            const searchParams = new URLSearchParams();
            if (isInactiveCheckedBool) {
                searchParams.set("include_inactive", "true");
            }
            if (teamId) {
                searchParams.set("team_id", teamId);
            }
            const queryString = searchParams.toString();
            const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#resources`;
            window.location.href = redirectUrl;
        }
    } catch (error) {
        console.error("Error:", error);
        if (status) {
            status.textContent = error.message || "An error occurred!";
            status.classList.add("error-status");
        }
        showErrorMessage(error.message);
    } finally {
        // location.reload();
        if (loading) {
            loading.style.display = "none";
        }
    }
}

async function handlePromptFormSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);
    const status = safeGetElement("status-prompts");
    const loading = safeGetElement("add-prompts-loading");
    try {
        // Validate inputs
        const name = formData.get("name");
        const nameValidation = validateInputName(name, "prompt");

        if (!nameValidation.valid) {
            showErrorMessage(nameValidation.error);
            return;
        }

        if (loading) {
            loading.style.display = "block";
        }
        if (status) {
            status.textContent = "";
            status.classList.remove("error-status");
        }

        const isInactiveCheckedBool = isInactiveChecked("prompts");
        formData.append("is_inactive_checked", isInactiveCheckedBool);

        const response = await fetch(`${window.ROOT_PATH}/admin/prompts`, {
            method: "POST",
            body: formData,
        });
        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to add prompt");
        }
        // Only redirect on success
        const teamId = new URL(window.location.href).searchParams.get(
            "team_id",
        );

        const searchParams = new URLSearchParams();
        if (isInactiveCheckedBool) {
            searchParams.set("include_inactive", "true");
        }
        if (teamId) {
            searchParams.set("team_id", teamId);
        }
        const queryString = searchParams.toString();
        const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#prompts`;
        window.location.href = redirectUrl;
    } catch (error) {
        console.error("Error:", error);
        if (status) {
            status.textContent = error.message || "An error occurred!";
            status.classList.add("error-status");
        }
        showErrorMessage(error.message);
    } finally {
        // location.reload();
        if (loading) {
            loading.style.display = "none";
        }
    }
}

async function handleEditPromptFormSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);

    try {
        // Validate inputs
        const name = formData.get("name");
        const nameValidation = validateInputName(name, "prompt");
        if (!nameValidation.valid) {
            showErrorMessage(nameValidation.error);
            return;
        }

        // Save CodeMirror editors' contents if present
        if (window.promptToolHeadersEditor) {
            window.promptToolHeadersEditor.save();
        }
        if (window.promptToolSchemaEditor) {
            window.promptToolSchemaEditor.save();
        }

        const isInactiveCheckedBool = isInactiveChecked("prompts");
        formData.append("is_inactive_checked", isInactiveCheckedBool);

        // Submit via fetch
        const response = await fetch(form.action, {
            method: "POST",
            body: formData,
        });

        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to edit Prompt");
        }
        // Only redirect on success
        const teamId = new URL(window.location.href).searchParams.get(
            "team_id",
        );

        const searchParams = new URLSearchParams();
        if (isInactiveCheckedBool) {
            searchParams.set("include_inactive", "true");
        }
        if (teamId) {
            searchParams.set("team_id", teamId);
        }
        const queryString = searchParams.toString();
        const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#prompts`;
        window.location.href = redirectUrl;
    } catch (error) {
        console.error("Error:", error);
        showErrorMessage(error.message);
    }
}

async function handleServerFormSubmit(e) {
    e.preventDefault();

    const form = e.target;
    const formData = new FormData(form);
    const status = safeGetElement("serverFormError");
    const loading = safeGetElement("add-server-loading"); // Add a loading spinner if needed

    try {
        const name = formData.get("name");

        // Basic validation
        const nameValidation = validateInputName(name, "server");
        if (!nameValidation.valid) {
            throw new Error(nameValidation.error);
        }

        if (loading) {
            loading.style.display = "block";
        }

        if (status) {
            status.textContent = "";
            status.classList.remove("error-status");
        }

        const isInactiveCheckedBool = isInactiveChecked("servers");
        formData.append("is_inactive_checked", isInactiveCheckedBool);

        formData.append("visibility", formData.get("visibility"));
        const teamId = new URL(window.location.href).searchParams.get(
            "team_id",
        );
        teamId && formData.append("team_id", teamId);

        const response = await fetch(`${window.ROOT_PATH}/admin/servers`, {
            method: "POST",
            body: formData,
        });
        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to add server.");
        } else {
            // Success redirect
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );

            const searchParams = new URLSearchParams();
            if (isInactiveCheckedBool) {
                searchParams.set("include_inactive", "true");
            }
            if (teamId) {
                searchParams.set("team_id", teamId);
            }

            const queryString = searchParams.toString();
            const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#catalog`;
            window.location.href = redirectUrl;
        }
    } catch (error) {
        console.error("Add Server Error:", error);
        if (status) {
            status.textContent = error.message || "An error occurred.";
            status.classList.add("error-status");
        }
        showErrorMessage(error.message); // Optional if you use global popup/snackbar
    } finally {
        if (loading) {
            loading.style.display = "none";
        }
    }
}

async function handleToolFormSubmit(event) {
    event.preventDefault();

    try {
        const form = event.target;
        const formData = new FormData(form);

        // Validate form inputs
        const name = formData.get("name");
        const url = formData.get("url");

        const nameValidation = validateInputName(name, "tool");
        const urlValidation = validateUrl(url);

        if (!nameValidation.valid) {
            throw new Error(nameValidation.error);
        }

        if (!urlValidation.valid) {
            throw new Error(urlValidation.error);
        }

        // If in UI mode, update schemaEditor with generated schema
        const mode = document.querySelector(
            'input[name="schema_input_mode"]:checked',
        );
        if (mode && mode.value === "ui") {
            if (window.schemaEditor) {
                const generatedSchema = generateSchema();
                const schemaValidation = validateJson(
                    generatedSchema,
                    "Generated Schema",
                );
                if (!schemaValidation.valid) {
                    throw new Error(schemaValidation.error);
                }
                window.schemaEditor.setValue(generatedSchema);
            }
        }

        // Save CodeMirror editors' contents
        if (window.headersEditor) {
            window.headersEditor.save();
        }
        if (window.schemaEditor) {
            window.schemaEditor.save();
        }

        const isInactiveCheckedBool = isInactiveChecked("tools");
        formData.append("is_inactive_checked", isInactiveCheckedBool);

        formData.append("visibility", formData.get("visibility"));
        const teamId = new URL(window.location.href).searchParams.get(
            "team_id",
        );
        teamId && formData.append("team_id", teamId);

        const response = await fetch(`${window.ROOT_PATH}/admin/tools`, {
            method: "POST",
            body: formData,
        });
        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to add tool");
        } else {
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );

            const searchParams = new URLSearchParams();
            if (isInactiveCheckedBool) {
                searchParams.set("include_inactive", "true");
            }
            if (teamId) {
                searchParams.set("team_id", teamId);
            }
            const queryString = searchParams.toString();
            const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#tools`;
            window.location.href = redirectUrl;
        }
    } catch (error) {
        console.error("Fetch error:", error);
        showErrorMessage(error.message);
    }
}
async function handleEditToolFormSubmit(event) {
    event.preventDefault();

    const form = event.target;

    try {
        const formData = new FormData(form);

        // Basic validation (customize as needed)
        const name = formData.get("name");
        const url = formData.get("url");
        const nameValidation = validateInputName(name, "tool");
        const urlValidation = validateUrl(url);

        if (!nameValidation.valid) {
            throw new Error(nameValidation.error);
        }
        if (!urlValidation.valid) {
            throw new Error(urlValidation.error);
        }

        // // Save CodeMirror editors' contents if present

        if (window.editToolHeadersEditor) {
            window.editToolHeadersEditor.save();
        }
        if (window.editToolSchemaEditor) {
            window.editToolSchemaEditor.save();
        }

        const isInactiveCheckedBool = isInactiveChecked("tools");
        formData.append("is_inactive_checked", isInactiveCheckedBool);

        // Submit via fetch
        const response = await fetch(form.action, {
            method: "POST",
            body: formData,
            headers: { "X-Requested-With": "XMLHttpRequest" },
        });

        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to edit tool");
        } else {
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );

            const searchParams = new URLSearchParams();
            if (isInactiveCheckedBool) {
                searchParams.set("include_inactive", "true");
            }
            if (teamId) {
                searchParams.set("team_id", teamId);
            }
            const queryString = searchParams.toString();
            const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#tools`;
            window.location.href = redirectUrl;
        }
    } catch (error) {
        console.error("Fetch error:", error);
        showErrorMessage(error.message);
    }
}
async function handleEditGatewayFormSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);
    try {
        // Validate form inputs
        const name = formData.get("name");
        const url = formData.get("url");

        const nameValidation = validateInputName(name, "gateway");
        const urlValidation = validateUrl(url);

        if (!nameValidation.valid) {
            throw new Error(nameValidation.error);
        }

        if (!urlValidation.valid) {
            throw new Error(urlValidation.error);
        }

        // Handle passthrough headers
        const passthroughHeadersString =
            formData.get("passthrough_headers") || "";
        const passthroughHeaders = passthroughHeadersString
            .split(",")
            .map((header) => header.trim())
            .filter((header) => header.length > 0);

        // Validate each header name
        for (const headerName of passthroughHeaders) {
            if (headerName && !HEADER_NAME_REGEX.test(headerName)) {
                showErrorMessage(
                    `Invalid passthrough header name: "${headerName}". Only letters, numbers, and hyphens are allowed.`,
                );
                return;
            }
        }

        formData.append(
            "passthrough_headers",
            JSON.stringify(passthroughHeaders),
        );

        // Handle OAuth configuration
        const authType = formData.get("auth_type");
        if (authType === "oauth") {
            const oauthConfig = {
                grant_type: formData.get("oauth_grant_type"),
                client_id: formData.get("oauth_client_id"),
                client_secret: formData.get("oauth_client_secret"),
                token_url: formData.get("oauth_token_url"),
                scopes: formData.get("oauth_scopes")
                    ? formData
                          .get("oauth_scopes")
                          .split(" ")
                          .filter((s) => s.trim())
                    : [],
            };

            // Add authorization code specific fields
            if (oauthConfig.grant_type === "authorization_code") {
                oauthConfig.authorization_url = formData.get(
                    "oauth_authorization_url",
                );
                oauthConfig.redirect_uri = formData.get("oauth_redirect_uri");
            }

            // Remove individual OAuth fields and add as oauth_config
            formData.delete("oauth_grant_type");
            formData.delete("oauth_client_id");
            formData.delete("oauth_client_secret");
            formData.delete("oauth_token_url");
            formData.delete("oauth_scopes");
            formData.delete("oauth_authorization_url");
            formData.delete("oauth_redirect_uri");

            formData.append("oauth_config", JSON.stringify(oauthConfig));
        }

        const isInactiveCheckedBool = isInactiveChecked("gateways");
        formData.append("is_inactive_checked", isInactiveCheckedBool);
        // Submit via fetch
        const response = await fetch(form.action, {
            method: "POST",
            body: formData,
        });
        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to edit gateway");
        }
        // Only redirect on success
        const teamId = new URL(window.location.href).searchParams.get(
            "team_id",
        );

        const searchParams = new URLSearchParams();
        if (isInactiveCheckedBool) {
            searchParams.set("include_inactive", "true");
        }
        if (teamId) {
            searchParams.set("team_id", teamId);
        }
        const queryString = searchParams.toString();
        const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#gateways`;
        window.location.href = redirectUrl;
    } catch (error) {
        console.error("Error:", error);
        showErrorMessage(error.message);
    }
}

async function handleEditServerFormSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);

    try {
        // Validate inputs
        const name = formData.get("name");
        const nameValidation = validateInputName(name, "server");
        if (!nameValidation.valid) {
            throw new Error(nameValidation.error);
        }

        // Save CodeMirror editors' contents if present
        if (window.promptToolHeadersEditor) {
            window.promptToolHeadersEditor.save();
        }
        if (window.promptToolSchemaEditor) {
            window.promptToolSchemaEditor.save();
        }

        const isInactiveCheckedBool = isInactiveChecked("servers");
        formData.append("is_inactive_checked", isInactiveCheckedBool);

        // Submit via fetch
        const response = await fetch(form.action, {
            method: "POST",
            body: formData,
        });
        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to edit server");
        }
        // Only redirect on success
        else {
            // Redirect to the appropriate page based on inactivity checkbox
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );

            const searchParams = new URLSearchParams();
            if (isInactiveCheckedBool) {
                searchParams.set("include_inactive", "true");
            }
            if (teamId) {
                searchParams.set("team_id", teamId);
            }
            const queryString = searchParams.toString();
            const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#catalog`;
            window.location.href = redirectUrl;
        }
    } catch (error) {
        console.error("Error:", error);
        showErrorMessage(error.message);
    }
}

async function handleEditResFormSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);

    try {
        // Validate inputs
        const name = formData.get("name");
        const uri = formData.get("uri");
        const nameValidation = validateInputName(name, "resource");
        const uriValidation = validateInputName(uri, "resource URI");

        if (!nameValidation.valid) {
            showErrorMessage(nameValidation.error);
            return;
        }

        if (!uriValidation.valid) {
            showErrorMessage(uriValidation.error);
            return;
        }

        // Save CodeMirror editors' contents if present
        if (window.promptToolHeadersEditor) {
            window.promptToolHeadersEditor.save();
        }
        if (window.promptToolSchemaEditor) {
            window.promptToolSchemaEditor.save();
        }

        const isInactiveCheckedBool = isInactiveChecked("resources");
        formData.append("is_inactive_checked", isInactiveCheckedBool);
        // Submit via fetch
        const response = await fetch(form.action, {
            method: "POST",
            body: formData,
        });

        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to edit resource");
        }
        // Only redirect on success
        else {
            // Redirect to the appropriate page based on inactivity checkbox
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );

            const searchParams = new URLSearchParams();
            if (isInactiveCheckedBool) {
                searchParams.set("include_inactive", "true");
            }
            if (teamId) {
                searchParams.set("team_id", teamId);
            }
            const queryString = searchParams.toString();
            const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#resources`;
            window.location.href = redirectUrl;
        }
    } catch (error) {
        console.error("Error:", error);
        showErrorMessage(error.message);
    }
}

// ===================================================================
// ENHANCED FORM VALIDATION for All Forms
// ===================================================================

function setupFormValidation() {
    // Add validation to all forms on the page
    const forms = document.querySelectorAll("form");

    forms.forEach((form) => {
        // Add validation to name fields
        const nameFields = form.querySelectorAll(
            'input[name*="name"], input[name*="Name"]',
        );
        nameFields.forEach((field) => {
            field.addEventListener("blur", function () {
                const validation = validateInputName(this.value, "name");
                if (!validation.valid) {
                    this.setCustomValidity(validation.error);
                    this.reportValidity();
                } else {
                    this.setCustomValidity("");
                    this.value = validation.value;
                }
            });
        });

        // Add validation to URL fields
        const urlFields = form.querySelectorAll(
            'input[name*="url"], input[name*="URL"]',
        );
        urlFields.forEach((field) => {
            field.addEventListener("blur", function () {
                if (this.value) {
                    const validation = validateUrl(this.value);
                    if (!validation.valid) {
                        this.setCustomValidity(validation.error);
                        this.reportValidity();
                    } else {
                        this.setCustomValidity("");
                        this.value = validation.value;
                    }
                }
            });
        });

        // Special validation for prompt name fields
        const promptNameFields = form.querySelectorAll(
            'input[name="prompt-name"], input[name="edit-prompt-name"]',
        );
        promptNameFields.forEach((field) => {
            field.addEventListener("blur", function () {
                const validation = validateInputName(this.value, "prompt");
                if (!validation.valid) {
                    this.setCustomValidity(validation.error);
                    this.reportValidity();
                } else {
                    this.setCustomValidity("");
                    this.value = validation.value;
                }
            });
        });
    });
}

// ===================================================================
// ENHANCED EDITOR REFRESH with Safety Checks
// ===================================================================

function refreshEditors() {
    setTimeout(() => {
        if (
            window.headersEditor &&
            typeof window.headersEditor.refresh === "function"
        ) {
            try {
                window.headersEditor.refresh();
                console.log("✓ Refreshed headersEditor");
            } catch (error) {
                console.error("Failed to refresh headersEditor:", error);
            }
        }

        if (
            window.schemaEditor &&
            typeof window.schemaEditor.refresh === "function"
        ) {
            try {
                window.schemaEditor.refresh();
                console.log("✓ Refreshed schemaEditor");
            } catch (error) {
                console.error("Failed to refresh schemaEditor:", error);
            }
        }
    }, 100);
}

// ===================================================================
// GLOBAL ERROR HANDLERS
// ===================================================================

window.addEventListener("error", (e) => {
    console.error("Global error:", e.error, e.filename, e.lineno);
    // Don't show user error for every script error, just log it
});

window.addEventListener("unhandledrejection", (e) => {
    console.error("Unhandled promise rejection:", e.reason);
    // Show user error for unhandled promises as they're often more serious
    showErrorMessage("An unexpected error occurred. Please refresh the page.");
});

// Enhanced cleanup function for page unload
window.addEventListener("beforeunload", () => {
    try {
        AppState.reset();
        cleanupToolTestState(); // ADD THIS LINE
        console.log("✓ Application state cleaned up before unload");
    } catch (error) {
        console.error("Error during cleanup:", error);
    }
});

// Performance monitoring
if (window.performance && window.performance.mark) {
    window.performance.mark("app-security-complete");
    console.log("✓ Performance markers available");
}

// ===================================================================
// Tool Tips for components with Alpine.js
// ===================================================================

/* global Alpine */
function setupTooltipsWithAlpine() {
    document.addEventListener("alpine:init", () => {
        console.log("Initializing Alpine tooltip directive...");

        Alpine.directive("tooltip", (el, { expression }, { evaluate }) => {
            let tooltipEl = null;
            let animationFrameId = null; // Track animation frame

            const moveTooltip = (e) => {
                if (!tooltipEl) {
                    return;
                }

                const paddingX = 12;
                const paddingY = 20;
                const tipRect = tooltipEl.getBoundingClientRect();

                let left = e.clientX + paddingX;
                let top = e.clientY + paddingY;

                if (left + tipRect.width > window.innerWidth - 8) {
                    left = e.clientX - tipRect.width - paddingX;
                }
                if (top + tipRect.height > window.innerHeight - 8) {
                    top = e.clientY - tipRect.height - paddingY;
                }

                tooltipEl.style.left = `${left}px`;
                tooltipEl.style.top = `${top}px`;
            };

            const showTooltip = (event) => {
                const text = evaluate(expression);
                if (!text) {
                    return;
                }

                hideTooltip(); // Clean up any existing tooltip

                tooltipEl = document.createElement("div");
                tooltipEl.textContent = text;
                tooltipEl.setAttribute("role", "tooltip");
                tooltipEl.className =
                    "fixed z-50 max-w-xs px-3 py-2 text-sm text-white bg-black/80 rounded-lg shadow-lg pointer-events-none opacity-0 transition-opacity duration-200";

                document.body.appendChild(tooltipEl);

                if (event?.clientX && event?.clientY) {
                    moveTooltip(event);
                    el.addEventListener("mousemove", moveTooltip);
                } else {
                    const rect = el.getBoundingClientRect();
                    const scrollY = window.scrollY || window.pageYOffset;
                    const scrollX = window.scrollX || window.pageXOffset;
                    tooltipEl.style.left = `${rect.left + scrollX}px`;
                    tooltipEl.style.top = `${rect.bottom + scrollY + 10}px`;
                }

                // FIX: Cancel any pending animation frame before setting a new one
                if (animationFrameId) {
                    cancelAnimationFrame(animationFrameId);
                }

                animationFrameId = requestAnimationFrame(() => {
                    // FIX: Check if tooltipEl still exists before accessing its style
                    if (tooltipEl) {
                        tooltipEl.style.opacity = "1";
                    }
                    animationFrameId = null;
                });

                window.addEventListener("scroll", hideTooltip, {
                    passive: true,
                });
                window.addEventListener("resize", hideTooltip, {
                    passive: true,
                });
            };

            const hideTooltip = () => {
                if (!tooltipEl) {
                    return;
                }

                // FIX: Cancel any pending animation frame
                if (animationFrameId) {
                    cancelAnimationFrame(animationFrameId);
                    animationFrameId = null;
                }

                tooltipEl.style.opacity = "0";
                el.removeEventListener("mousemove", moveTooltip);
                window.removeEventListener("scroll", hideTooltip);
                window.removeEventListener("resize", hideTooltip);
                el.removeEventListener("click", hideTooltip);

                const toRemove = tooltipEl;
                tooltipEl = null; // Set to null immediately

                setTimeout(() => {
                    if (toRemove && toRemove.parentNode) {
                        toRemove.parentNode.removeChild(toRemove);
                    }
                }, 200);
            };

            el.addEventListener("mouseenter", showTooltip);
            el.addEventListener("mouseleave", hideTooltip);
            el.addEventListener("focus", showTooltip);
            el.addEventListener("blur", hideTooltip);
            el.addEventListener("click", hideTooltip);
        });
    });
}

setupTooltipsWithAlpine();

// ===================================================================
// SINGLE CONSOLIDATED INITIALIZATION SYSTEM
// ===================================================================

document.addEventListener("DOMContentLoaded", () => {
    console.log("🔐 DOM loaded - initializing secure admin interface...");

    try {
        // initializeTooltips();

        // 1. Initialize CodeMirror editors first
        initializeCodeMirrorEditors();

        // 2. Initialize tool selects
        initializeToolSelects();

        // 3. Set up all event listeners
        initializeEventListeners();

        // 4. Handle initial tab/state
        initializeTabState();

        // 5. Set up form validation
        setupFormValidation();

        // 6. Setup bulk import modal
        try {
            setupBulkImportModal();
        } catch (error) {
            console.error("Error setting up bulk import modal:", error);
        }

        // 7. Initialize export/import functionality
        try {
            initializeExportImport();
        } catch (error) {
            console.error(
                "Error setting up export/import functionality:",
                error,
            );
        }

        // // ✅ 4.1 Set up tab button click handlers
        // document.querySelectorAll('.tab-button').forEach(button => {
        //     button.addEventListener('click', () => {
        //         const tabId = button.getAttribute('data-tab');

        //         document.querySelectorAll('.tab-panel').forEach(panel => {
        //             panel.classList.add('hidden');
        //         });

        //         document.getElementById(tabId).classList.remove('hidden');
        //     });
        // });

        // Mark as initialized
        AppState.isInitialized = true;

        console.log(
            "✅ Secure initialization complete - XSS protection active",
        );
    } catch (error) {
        console.error("❌ Initialization failed:", error);
        showErrorMessage(
            "Failed to initialize the application. Please refresh the page.",
        );
    }
});

// Separate initialization functions
function initializeCodeMirrorEditors() {
    console.log("Initializing CodeMirror editors...");

    const editorConfigs = [
        {
            id: "headers-editor",
            mode: "application/json",
            varName: "headersEditor",
        },
        {
            id: "schema-editor",
            mode: "application/json",
            varName: "schemaEditor",
        },
        {
            id: "resource-content-editor",
            mode: "text/plain",
            varName: "resourceContentEditor",
        },
        {
            id: "prompt-template-editor",
            mode: "text/plain",
            varName: "promptTemplateEditor",
        },
        {
            id: "prompt-args-editor",
            mode: "application/json",
            varName: "promptArgsEditor",
        },
        {
            id: "edit-tool-headers",
            mode: "application/json",
            varName: "editToolHeadersEditor",
        },
        {
            id: "edit-tool-schema",
            mode: "application/json",
            varName: "editToolSchemaEditor",
        },
        {
            id: "edit-resource-content",
            mode: "text/plain",
            varName: "editResourceContentEditor",
        },
        {
            id: "edit-prompt-template",
            mode: "text/plain",
            varName: "editPromptTemplateEditor",
        },
        {
            id: "edit-prompt-arguments",
            mode: "application/json",
            varName: "editPromptArgumentsEditor",
        },
    ];

    editorConfigs.forEach((config) => {
        const element = safeGetElement(config.id);
        if (element && window.CodeMirror) {
            try {
                window[config.varName] = window.CodeMirror.fromTextArea(
                    element,
                    {
                        mode: config.mode,
                        theme: "monokai",
                        lineNumbers: false,
                        autoCloseBrackets: true,
                        matchBrackets: true,
                        tabSize: 2,
                        lineWrapping: true,
                    },
                );
                console.log(`✓ Initialized ${config.varName}`);
            } catch (error) {
                console.error(`Failed to initialize ${config.varName}:`, error);
            }
        } else {
            console.warn(
                `Element ${config.id} not found or CodeMirror not available`,
            );
        }
    });
}

function initializeToolSelects() {
    console.log("Initializing tool selects...");

    initToolSelect(
        "associatedTools",
        "selectedToolsPills",
        "selectedToolsWarning",
        6,
        "selectAllToolsBtn",
        "clearAllToolsBtn",
    );
    initToolSelect(
        "edit-server-tools",
        "selectedEditToolsPills",
        "selectedEditToolsWarning",
        6,
        "selectAllEditToolsBtn",
        "clearAllEditToolsBtn",
    );

    // Initialize resource selector
    initResourceSelect(
        "edit-server-resources",
        "selectedEditResourcesPills",
        "selectedEditResourcesWarning",
        10,
        "selectAllEditResourcesBtn",
        "clearAllEditResourcesBtn",
    );

    // Initialize prompt selector
    initPromptSelect(
        "edit-server-prompts",
        "selectedEditPromptsPills",
        "selectedEditPromptsWarning",
        8,
        "selectAllEditPromptsBtn",
        "clearAllEditPromptsBtn",
    );
}

function initializeEventListeners() {
    console.log("Setting up event listeners...");

    setupTabNavigation();
    setupHTMXHooks();
    setupAuthenticationToggles();
    setupFormHandlers();
    setupSchemaModeHandlers();
    setupIntegrationTypeHandlers();
}

function setupTabNavigation() {
    const tabs = [
        "catalog",
        "tools",
        "resources",
        "prompts",
        "gateways",
        "a2a-agents",
        "roots",
        "metrics",
        "logs",
        "export-import",
        "version-info",
    ];

    tabs.forEach((tabName) => {
        // Suppress warnings for optional tabs that might not be enabled
        const optionalTabs = ["roots", "logs", "export-import", "version-info"];
        const suppressWarning = optionalTabs.includes(tabName);

        const tabElement = safeGetElement(`tab-${tabName}`, suppressWarning);
        if (tabElement) {
            tabElement.addEventListener("click", () => showTab(tabName));
        }
    });
}

function setupHTMXHooks() {
    document.body.addEventListener("htmx:beforeRequest", (event) => {
        if (event.detail.elt.id === "tab-version-info") {
            console.log("HTMX: Sending request for version info partial");
        }
    });

    document.body.addEventListener("htmx:afterSwap", (event) => {
        if (event.detail.target.id === "version-info-panel") {
            console.log("HTMX: Content swapped into version-info-panel");
        }
    });
}

function setupAuthenticationToggles() {
    const authHandlers = [
        {
            id: "auth-type",
            basicId: "auth-basic-fields",
            bearerId: "auth-bearer-fields",
            headersId: "auth-headers-fields",
        },
        {
            id: "auth-type-gw",
            basicId: "auth-basic-fields-gw",
            bearerId: "auth-bearer-fields-gw",
            headersId: "auth-headers-fields-gw",
        },
        {
            id: "auth-type-gw-edit",
            basicId: "auth-basic-fields-gw-edit",
            bearerId: "auth-bearer-fields-gw-edit",
            headersId: "auth-headers-fields-gw-edit",
            oauthId: "auth-oauth-fields-gw-edit",
        },
        {
            id: "edit-auth-type",
            basicId: "edit-auth-basic-fields",
            bearerId: "edit-auth-bearer-fields",
            headersId: "edit-auth-headers-fields",
        },
    ];

    authHandlers.forEach((handler) => {
        const element = safeGetElement(handler.id);
        if (element) {
            element.addEventListener("change", function () {
                const basicFields = safeGetElement(handler.basicId);
                const bearerFields = safeGetElement(handler.bearerId);
                const headersFields = safeGetElement(handler.headersId);
                handleAuthTypeSelection(
                    this.value,
                    basicFields,
                    bearerFields,
                    headersFields,
                );
            });
        }
    });
}

function setupFormHandlers() {
    const gatewayForm = safeGetElement("add-gateway-form");
    if (gatewayForm) {
        gatewayForm.addEventListener("submit", handleGatewayFormSubmit);

        // Add OAuth authentication type change handler
        const authTypeField = safeGetElement("auth-type-gw");
        if (authTypeField) {
            authTypeField.addEventListener("change", handleAuthTypeChange);
        }

        // Add OAuth grant type change handler
        const oauthGrantTypeField = safeGetElement("oauth-grant-type-gw");
        if (oauthGrantTypeField) {
            oauthGrantTypeField.addEventListener(
                "change",
                handleOAuthGrantTypeChange,
            );
        }
    }

    const resourceForm = safeGetElement("add-resource-form");
    if (resourceForm) {
        resourceForm.addEventListener("submit", handleResourceFormSubmit);
    }

    const promptForm = safeGetElement("add-prompt-form");
    if (promptForm) {
        promptForm.addEventListener("submit", handlePromptFormSubmit);
    }

    const editPromptForm = safeGetElement("edit-prompt-form");
    if (editPromptForm) {
        editPromptForm.addEventListener("submit", handleEditPromptFormSubmit);
        editPromptForm.addEventListener("click", () => {
            if (getComputedStyle(editPromptForm).display !== "none") {
                refreshEditors();
            }
        });
    }

    // Add OAuth grant type change handler for Edit Gateway modal
    const editOAuthGrantTypeField = safeGetElement("oauth-grant-type-gw-edit");
    if (editOAuthGrantTypeField) {
        editOAuthGrantTypeField.addEventListener(
            "change",
            handleEditOAuthGrantTypeChange,
        );
    }

    const toolForm = safeGetElement("add-tool-form");
    if (toolForm) {
        toolForm.addEventListener("submit", handleToolFormSubmit);
        toolForm.addEventListener("click", () => {
            if (getComputedStyle(toolForm).display !== "none") {
                refreshEditors();
            }
        });
    }

    const paramButton = safeGetElement("add-parameter-btn");
    if (paramButton) {
        paramButton.addEventListener("click", handleAddParameter);
    }

    const serverForm = safeGetElement("add-server-form");
    if (serverForm) {
        serverForm.addEventListener("submit", handleServerFormSubmit);
    }

    const editServerForm = safeGetElement("edit-server-form");
    if (editServerForm) {
        editServerForm.addEventListener("submit", handleEditServerFormSubmit);
        editServerForm.addEventListener("click", () => {
            if (getComputedStyle(editServerForm).display !== "none") {
                refreshEditors();
            }
        });
    }

    const editResourceForm = safeGetElement("edit-resource-form");
    if (editResourceForm) {
        editResourceForm.addEventListener("submit", handleEditResFormSubmit);
        editResourceForm.addEventListener("click", () => {
            if (getComputedStyle(editResourceForm).display !== "none") {
                refreshEditors();
            }
        });
    }

    const editToolForm = safeGetElement("edit-tool-form");
    if (editToolForm) {
        editToolForm.addEventListener("submit", handleEditToolFormSubmit);
        editToolForm.addEventListener("click", () => {
            if (getComputedStyle(editToolForm).display !== "none") {
                refreshEditors();
            }
        });
    }

    const editGatewayForm = safeGetElement("edit-gateway-form");
    if (editGatewayForm) {
        editGatewayForm.addEventListener("submit", handleEditGatewayFormSubmit);
        editGatewayForm.addEventListener("click", () => {
            if (getComputedStyle(editGatewayForm).display !== "none") {
                refreshEditors();
            }
        });
    }

    // Setup search functionality for selectors
    setupSelectorSearch();
}

/**
 * Setup search functionality for multi-select dropdowns
 */
function setupSelectorSearch() {
    // Tools search
    const searchTools = safeGetElement("searchTools", true);
    if (searchTools) {
        searchTools.addEventListener("input", function () {
            filterSelectorItems(
                this.value,
                "#associatedTools",
                ".tool-item",
                "noToolsMessage",
                "searchQuery",
            );
        });
    }

    // Resources search
    const searchResources = safeGetElement("searchResources", true);
    if (searchResources) {
        searchResources.addEventListener("input", function () {
            filterSelectorItems(
                this.value,
                "#associatedResources",
                ".resource-item",
                "noResourcesMessage",
                "searchResourcesQuery",
            );
        });
    }

    // Prompts search
    const searchPrompts = safeGetElement("searchPrompts", true);
    if (searchPrompts) {
        searchPrompts.addEventListener("input", function () {
            filterSelectorItems(
                this.value,
                "#associatedPrompts",
                ".prompt-item",
                "noPromptsMessage",
                "searchPromptsQuery",
            );
        });
    }
}

/**
 * Generic function to filter items in multi-select dropdowns with no results message
 */
function filterSelectorItems(
    searchText,
    containerSelector,
    itemSelector,
    noResultsId,
    searchQueryId,
) {
    const container = document.querySelector(containerSelector);
    if (!container) {
        return;
    }

    const items = container.querySelectorAll(itemSelector);
    const search = searchText.toLowerCase().trim();
    let hasVisibleItems = false;

    items.forEach((item) => {
        let textContent = "";

        // Get text from all text nodes within the item
        const textElements = item.querySelectorAll(
            "span, .text-xs, .font-medium",
        );
        textElements.forEach((el) => {
            textContent += " " + el.textContent;
        });

        // Also get direct text content
        textContent += " " + item.textContent;

        if (search === "" || textContent.toLowerCase().includes(search)) {
            item.style.display = "";
            hasVisibleItems = true;
        } else {
            item.style.display = "none";
        }
    });

    // Handle no results message
    const noResultsMessage = safeGetElement(noResultsId, true);
    const searchQuerySpan = safeGetElement(searchQueryId, true);

    if (search !== "" && !hasVisibleItems) {
        if (noResultsMessage) {
            noResultsMessage.style.display = "block";
        }
        if (searchQuerySpan) {
            searchQuerySpan.textContent = searchText;
        }
    } else {
        if (noResultsMessage) {
            noResultsMessage.style.display = "none";
        }
    }
}

/**
 * Filter server table rows based on search text
 */
function filterServerTable(searchText) {
    try {
        const tbody = document.querySelector(
            'tbody[data-testid="server-list"]',
        );
        if (!tbody) {
            console.warn("Server table not found");
            return;
        }

        const rows = tbody.querySelectorAll('tr[data-testid="server-item"]');
        const search = searchText.toLowerCase().trim();

        rows.forEach((row) => {
            let textContent = "";

            // Get text from all cells in the row
            const cells = row.querySelectorAll("td");
            cells.forEach((cell) => {
                textContent += " " + cell.textContent;
            });

            if (search === "" || textContent.toLowerCase().includes(search)) {
                row.style.display = "";
            } else {
                row.style.display = "none";
            }
        });
    } catch (error) {
        console.error("Error filtering server table:", error);
    }
}

// Make server search function available globally
window.filterServerTable = filterServerTable;

function handleAuthTypeChange() {
    const authType = this.value;
    const basicFields = safeGetElement("auth-basic-fields-gw");
    const bearerFields = safeGetElement("auth-bearer-fields-gw");
    const headersFields = safeGetElement("auth-headers-fields-gw");
    const oauthFields = safeGetElement("auth-oauth-fields-gw");

    // Hide all auth sections first
    if (basicFields) {
        basicFields.style.display = "none";
    }
    if (bearerFields) {
        bearerFields.style.display = "none";
    }
    if (headersFields) {
        headersFields.style.display = "none";
    }
    if (oauthFields) {
        oauthFields.style.display = "none";
    }

    // Show the appropriate section
    switch (authType) {
        case "basic":
            if (basicFields) {
                basicFields.style.display = "block";
            }
            break;
        case "bearer":
            if (bearerFields) {
                bearerFields.style.display = "block";
            }
            break;
        case "authheaders":
            if (headersFields) {
                headersFields.style.display = "block";
            }
            break;
        case "oauth":
            if (oauthFields) {
                oauthFields.style.display = "block";
            }
            break;
        default:
            // No auth - keep everything hidden
            break;
    }
}

function handleOAuthGrantTypeChange() {
    const grantType = this.value;
    const authCodeFields = safeGetElement("oauth-auth-code-fields-gw");

    if (authCodeFields) {
        if (grantType === "authorization_code") {
            authCodeFields.style.display = "block";

            // Make authorization code specific fields required
            const requiredFields =
                authCodeFields.querySelectorAll('input[type="url"]');
            requiredFields.forEach((field) => {
                field.required = true;
            });

            // Show additional validation for required fields
            console.log(
                "Authorization Code flow selected - additional fields are now required",
            );
        } else {
            authCodeFields.style.display = "none";

            // Remove required validation for hidden fields
            const requiredFields =
                authCodeFields.querySelectorAll('input[type="url"]');
            requiredFields.forEach((field) => {
                field.required = false;
            });
        }
    }
}

function handleEditOAuthGrantTypeChange() {
    const grantType = this.value;
    const authCodeFields = safeGetElement("oauth-auth-code-fields-gw-edit");

    if (authCodeFields) {
        if (grantType === "authorization_code") {
            authCodeFields.style.display = "block";

            // Make authorization code specific fields required
            const requiredFields =
                authCodeFields.querySelectorAll('input[type="url"]');
            requiredFields.forEach((field) => {
                field.required = true;
            });

            // Show additional validation for required fields
            console.log(
                "Authorization Code flow selected - additional fields are now required",
            );
        } else {
            authCodeFields.style.display = "none";

            // Remove required validation for hidden fields
            const requiredFields =
                authCodeFields.querySelectorAll('input[type="url"]');
            requiredFields.forEach((field) => {
                field.required = false;
            });
        }
    }
}

function setupSchemaModeHandlers() {
    const schemaModeRadios = document.getElementsByName("schema_input_mode");
    const uiBuilderDiv = safeGetElement("ui-builder");
    const jsonInputContainer = safeGetElement("json-input-container");

    if (schemaModeRadios.length === 0) {
        console.warn("Schema mode radios not found");
        return;
    }

    Array.from(schemaModeRadios).forEach((radio) => {
        radio.addEventListener("change", () => {
            try {
                if (radio.value === "ui" && radio.checked) {
                    if (uiBuilderDiv) {
                        uiBuilderDiv.style.display = "block";
                    }
                    if (jsonInputContainer) {
                        jsonInputContainer.style.display = "none";
                    }
                } else if (radio.value === "json" && radio.checked) {
                    if (uiBuilderDiv) {
                        uiBuilderDiv.style.display = "none";
                    }
                    if (jsonInputContainer) {
                        jsonInputContainer.style.display = "block";
                    }
                    updateSchemaPreview();
                }
            } catch (error) {
                console.error("Error handling schema mode change:", error);
            }
        });
    });

    console.log("✓ Schema mode handlers set up successfully");
}

function setupIntegrationTypeHandlers() {
    const integrationTypeSelect = safeGetElement("integrationType");
    if (integrationTypeSelect) {
        const defaultIntegration =
            integrationTypeSelect.dataset.default ||
            integrationTypeSelect.options[0].value;
        integrationTypeSelect.value = defaultIntegration;
        updateRequestTypeOptions();
        integrationTypeSelect.addEventListener("change", () =>
            updateRequestTypeOptions(),
        );
    }

    const editToolTypeSelect = safeGetElement("edit-tool-type");
    if (editToolTypeSelect) {
        editToolTypeSelect.addEventListener(
            "change",
            () => updateEditToolRequestTypes(),
            // updateEditToolUrl(),
        );
    }
}

function initializeTabState() {
    console.log("Initializing tab state...");

    const hash = window.location.hash;
    if (hash) {
        showTab(hash.slice(1));
    } else {
        showTab("catalog");
    }

    // Pre-load version info if that's the initial tab
    if (window.location.hash === "#version-info") {
        setTimeout(() => {
            const panel = safeGetElement("version-info-panel");
            if (panel && panel.innerHTML.trim() === "") {
                fetchWithTimeout(`${window.ROOT_PATH}/version?partial=true`)
                    .then((resp) => {
                        if (!resp.ok) {
                            throw new Error("Network response was not ok");
                        }
                        return resp.text();
                    })
                    .then((html) => {
                        safeSetInnerHTML(panel, html, true);
                    })
                    .catch((err) => {
                        console.error("Failed to preload version info:", err);
                        const errorDiv = document.createElement("div");
                        errorDiv.className = "text-red-600 p-4";
                        errorDiv.textContent = "Failed to load version info.";
                        panel.innerHTML = "";
                        panel.appendChild(errorDiv);
                    });
            }
        }, 100);
    }

    // Set checkbox states based on URL parameter
    const urlParams = new URLSearchParams(window.location.search);
    const includeInactive = urlParams.get("include_inactive") === "true";

    const checkboxes = [
        "show-inactive-tools",
        "show-inactive-resources",
        "show-inactive-prompts",
        "show-inactive-gateways",
        "show-inactive-servers",
    ];
    checkboxes.forEach((id) => {
        const checkbox = safeGetElement(id);
        if (checkbox) {
            checkbox.checked = includeInactive;
        }
    });
}

// ===================================================================
// GLOBAL EXPORTS - Make functions available to HTML onclick handlers
// ===================================================================

window.toggleInactiveItems = toggleInactiveItems;
window.handleToggleSubmit = handleToggleSubmit;
window.handleSubmitWithConfirmation = handleSubmitWithConfirmation;
window.viewTool = viewTool;
window.editTool = editTool;
window.testTool = testTool;
window.viewResource = viewResource;
window.editResource = editResource;
window.viewPrompt = viewPrompt;
window.editPrompt = editPrompt;
window.viewGateway = viewGateway;
window.editGateway = editGateway;
window.viewServer = viewServer;
window.editServer = editServer;
window.runToolTest = runToolTest;
window.testPrompt = testPrompt;
window.runPromptTest = runPromptTest;
window.closeModal = closeModal;
window.testGateway = testGateway;

// ===============================================
// CONFIG EXPORT FUNCTIONALITY
// ===============================================

/**
 * Global variables to store current config data
 */
let currentConfigData = null;
let currentConfigType = null;
let currentServerName = null;
let currentServerId = null;

/**
 * Show the config selection modal
 * @param {string} serverId - The server UUID
 * @param {string} serverName - The server name
 */
function showConfigSelectionModal(serverId, serverName) {
    currentServerId = serverId;
    currentServerName = serverName;

    const serverNameDisplay = safeGetElement("server-name-display");
    if (serverNameDisplay) {
        serverNameDisplay.textContent = serverName;
    }

    openModal("config-selection-modal");
}
/**
 * Build MCP_SERVER_CATALOG_URL for a given server
 * @param {Object} server
 * @returns {string}
 */
function getCatalogUrl(server) {
    const currentHost = window.location.hostname;
    const currentPort =
        window.location.port ||
        (window.location.protocol === "https:" ? "443" : "80");
    const protocol = window.location.protocol;

    const baseUrl = `${protocol}//${currentHost}${
        currentPort !== "80" && currentPort !== "443" ? ":" + currentPort : ""
    }`;

    return `${baseUrl}/servers/${server.id}`;
}

/**
 * Generate and show configuration for selected type
 * @param {string} configType - Configuration type: 'stdio', 'sse', or 'http'
 */
async function generateAndShowConfig(configType) {
    try {
        console.log(
            `Generating ${configType} config for server ${currentServerId}`,
        );

        // First, fetch the server details
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/servers/${currentServerId}`,
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const server = await response.json();

        // Generate the configuration
        const config = generateConfig(server, configType);

        // Store data for modal
        currentConfigData = config;
        currentConfigType = configType;

        // Close selection modal and show config display modal
        closeModal("config-selection-modal");
        showConfigDisplayModal(server, configType, config);

        console.log("✓ Config generated successfully");
    } catch (error) {
        console.error("Error generating config:", error);
        const errorMessage = handleFetchError(error, "generate configuration");
        showErrorMessage(errorMessage);
    }
}

/**
 * Export server configuration in specified format
 * @param {string} serverId - The server UUID
 * @param {string} configType - Configuration type: 'stdio', 'sse', or 'http'
 */
async function exportServerConfig(serverId, configType) {
    try {
        console.log(`Exporting ${configType} config for server ${serverId}`);

        // First, fetch the server details
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/servers/${serverId}`,
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const server = await response.json();

        // Generate the configuration
        const config = generateConfig(server, configType);

        // Store data for modal
        currentConfigData = config;
        currentConfigType = configType;
        currentServerName = server.name;

        // Show the modal with the config
        showConfigDisplayModal(server, configType, config);

        console.log("✓ Config generated successfully");
    } catch (error) {
        console.error("Error generating config:", error);
        const errorMessage = handleFetchError(error, "generate configuration");
        showErrorMessage(errorMessage);
    }
}

/**
 * Generate configuration object based on server and type
 * @param {Object} server - Server object from API
 * @param {string} configType - Configuration type
 * @returns {Object} - Generated configuration object
 */
function generateConfig(server, configType) {
    const currentHost = window.location.hostname;
    const currentPort =
        window.location.port ||
        (window.location.protocol === "https:" ? "443" : "80");
    const protocol = window.location.protocol;
    const baseUrl = `${protocol}//${currentHost}${currentPort !== "80" && currentPort !== "443" ? ":" + currentPort : ""}`;

    // Clean server name for use as config key (alphanumeric and hyphens only)
    const cleanServerName = server.name
        .toLowerCase()
        .replace(/[^a-z0-9-]/g, "-")
        .replace(/-+/g, "-")
        .replace(/^-|-$/g, "");

    switch (configType) {
        case "stdio":
            return {
                mcpServers: {
                    "mcpgateway-wrapper": {
                        command: "python",
                        args: ["-m", "mcpgateway.wrapper"],
                        env: {
                            MCP_AUTH_TOKEN: "your-token-here",
                            MCP_SERVER_CATALOG_URLS: `${baseUrl}/servers/${server.id}`,
                            MCP_TOOL_CALL_TIMEOUT: "120",
                        },
                    },
                },
            };

        case "sse":
            return {
                servers: {
                    [cleanServerName]: {
                        type: "sse",
                        url: `${baseUrl}/servers/${server.id}/sse`,
                        headers: {
                            Authorization: "Bearer your-token-here",
                        },
                    },
                },
            };

        case "http":
            return {
                servers: {
                    [cleanServerName]: {
                        type: "http",
                        url: `${baseUrl}/servers/${server.id}/mcp`,
                        headers: {
                            Authorization: "Bearer your-token-here",
                        },
                    },
                },
            };

        default:
            throw new Error(`Unknown config type: ${configType}`);
    }
}

/**
 * Show the config display modal with generated configuration
 * @param {Object} server - Server object
 * @param {string} configType - Configuration type
 * @param {Object} config - Generated configuration
 */
function showConfigDisplayModal(server, configType, config) {
    const descriptions = {
        stdio: "Configuration for Claude Desktop, CLI tools, and stdio-based MCP clients",
        sse: "Configuration for LangChain, LlamaIndex, and other SSE-based frameworks",
        http: "Configuration for REST clients and HTTP-based MCP integrations",
    };

    const usageInstructions = {
        stdio: "Save as .mcp.json in your user directory or use in Claude Desktop settings",
        sse: "Use with MCP client libraries that support Server-Sent Events transport",
        http: "Use with HTTP clients or REST API wrappers for MCP protocol",
    };

    // Update modal content
    const descriptionEl = safeGetElement("config-description");
    const usageEl = safeGetElement("config-usage");
    const contentEl = safeGetElement("config-content");

    if (descriptionEl) {
        descriptionEl.textContent = `${descriptions[configType]} for server "${server.name}"`;
    }

    if (usageEl) {
        usageEl.textContent = usageInstructions[configType];
    }

    if (contentEl) {
        contentEl.value = JSON.stringify(config, null, 2);
    }

    // Update title and open the modal
    const titleEl = safeGetElement("config-display-title");
    if (titleEl) {
        titleEl.textContent = `${configType.toUpperCase()} Configuration for ${server.name}`;
    }
    openModal("config-display-modal");
}

/**
 * Copy configuration to clipboard
 */
async function copyConfigToClipboard() {
    try {
        const contentEl = safeGetElement("config-content");
        if (!contentEl) {
            throw new Error("Config content not found");
        }

        await navigator.clipboard.writeText(contentEl.value);
        showSuccessMessage("Configuration copied to clipboard!");
    } catch (error) {
        console.error("Error copying to clipboard:", error);

        // Fallback: select the text for manual copying
        const contentEl = safeGetElement("config-content");
        if (contentEl) {
            contentEl.select();
            contentEl.setSelectionRange(0, 99999); // For mobile devices
            showErrorMessage("Please copy the selected text manually (Ctrl+C)");
        } else {
            showErrorMessage("Failed to copy configuration");
        }
    }
}

/**
 * Download configuration as JSON file
 */
function downloadConfig() {
    if (!currentConfigData || !currentConfigType || !currentServerName) {
        showErrorMessage("No configuration data available");
        return;
    }

    try {
        const content = JSON.stringify(currentConfigData, null, 2);
        const blob = new Blob([content], { type: "application/json" });
        const url = window.URL.createObjectURL(blob);

        const a = document.createElement("a");
        a.href = url;
        a.download = `${currentServerName}-${currentConfigType}-config.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);

        showSuccessMessage(`Configuration downloaded as ${a.download}`);
    } catch (error) {
        console.error("Error downloading config:", error);
        showErrorMessage("Failed to download configuration");
    }
}

/**
 * Go back to config selection modal
 */
function goBackToSelection() {
    closeModal("config-display-modal");
    openModal("config-selection-modal");
}

// Export functions to global scope immediately after definition
window.showConfigSelectionModal = showConfigSelectionModal;
window.generateAndShowConfig = generateAndShowConfig;
window.exportServerConfig = exportServerConfig;
window.copyConfigToClipboard = copyConfigToClipboard;
window.downloadConfig = downloadConfig;
window.goBackToSelection = goBackToSelection;

// ===============================================
// TAG FILTERING FUNCTIONALITY
// ===============================================

/**
 * Extract all unique tags from entities in a given entity type
 * @param {string} entityType - The entity type (tools, resources, prompts, servers, gateways)
 * @returns {Array<string>} - Array of unique tags
 */
function extractAvailableTags(entityType) {
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
function updateAvailableTags(entityType) {
    const availableTagsContainer = document.getElementById(
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
 * Add a tag to the filter input
 * @param {string} entityType - The entity type
 * @param {string} tag - The tag to add
 */
function addTagToFilter(entityType, tag) {
    const filterInput = document.getElementById(`${entityType}-tag-filter`);
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
 * Filter entities by tags
 * @param {string} entityType - The entity type (tools, resources, prompts, servers, gateways)
 * @param {string} tagsInput - Comma-separated string of tags to filter by
 */
function filterEntitiesByTags(entityType, tagsInput) {
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
            span.inline-flex.items-center.px-2.py-0\\.5.rounded.text-xs.font-medium.bg-blue-100.text-blue-800,
            span.inline-block.bg-blue-100.text-blue-800.text-xs.px-2.py-1.rounded-full
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
 * Update empty state message when filtering
 * @param {string} entityType - The entity type
 * @param {number} visibleCount - Number of visible entities
 * @param {boolean} isFiltering - Whether filtering is active
 */
function updateFilterEmptyState(entityType, visibleCount, isFiltering) {
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
                    <p class="text-gray-500 dark:text-gray-400">No ${entityType} found with the specified tags. Try adjusting your filter or <button onclick="clearTagFilter('${entityType}')" class="text-indigo-600 hover:text-indigo-500 underline">clear the filter</button>.</p>
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
function clearTagFilter(entityType) {
    const filterInput = document.getElementById(`${entityType}-tag-filter`);
    if (filterInput) {
        filterInput.value = "";
        filterEntitiesByTags(entityType, "");
    }
}

/**
 * Initialize tag filtering for all entity types on page load
 */
function initializeTagFiltering() {
    const entityTypes = [
        "catalog",
        "tools",
        "resources",
        "prompts",
        "servers",
        "gateways",
    ];

    entityTypes.forEach((entityType) => {
        // Update available tags on page load
        updateAvailableTags(entityType);

        // Set up event listeners for tab switching to refresh tags
        const tabButton = document.getElementById(`tab-${entityType}`);
        if (tabButton) {
            tabButton.addEventListener("click", () => {
                // Delay to ensure tab content is visible
                setTimeout(() => updateAvailableTags(entityType), 100);
            });
        }
    });
}

// Initialize tag filtering when page loads
document.addEventListener("DOMContentLoaded", function () {
    initializeTagFiltering();
});

// Expose tag filtering functions to global scope
window.filterEntitiesByTags = filterEntitiesByTags;
window.clearTagFilter = clearTagFilter;
window.updateAvailableTags = updateAvailableTags;

// ===================================================================
// MULTI-HEADER AUTHENTICATION MANAGEMENT
// ===================================================================

/**
 * Global counter for unique header IDs
 */
let headerCounter = 0;

/**
 * Add a new authentication header row to the specified container
 * @param {string} containerId - ID of the container to add the header row to
 */
function addAuthHeader(containerId) {
    const container = document.getElementById(containerId);
    if (!container) {
        console.error(`Container with ID ${containerId} not found`);
        return;
    }

    const headerId = `auth-header-${++headerCounter}`;

    const headerRow = document.createElement("div");
    headerRow.className = "flex items-center space-x-2";
    headerRow.id = headerId;

    headerRow.innerHTML = `
        <div class="flex-1">
            <input
                type="text"
                placeholder="Header Key (e.g., X-API-Key)"
                class="auth-header-key block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:placeholder-gray-300 dark:text-gray-300 text-sm"
                oninput="updateAuthHeadersJSON('${containerId}')"
            />
        </div>
        <div class="flex-1">
            <input
                type="password"
                placeholder="Header Value"
                class="auth-header-value block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:placeholder-gray-300 dark:text-gray-300 text-sm"
                oninput="updateAuthHeadersJSON('${containerId}')"
            />
        </div>
        <button
            type="button"
            onclick="removeAuthHeader('${headerId}', '${containerId}')"
            class="inline-flex items-center px-2 py-1 border border-transparent text-sm leading-4 font-medium rounded-md text-red-700 bg-red-100 hover:bg-red-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 dark:bg-red-900 dark:text-red-300 dark:hover:bg-red-800"
            title="Remove header"
        >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
            </svg>
        </button>
    `;

    container.appendChild(headerRow);
    updateAuthHeadersJSON(containerId);

    // Focus on the key input of the new header
    const keyInput = headerRow.querySelector(".auth-header-key");
    if (keyInput) {
        keyInput.focus();
    }
}

/**
 * Remove an authentication header row
 * @param {string} headerId - ID of the header row to remove
 * @param {string} containerId - ID of the container to update
 */
function removeAuthHeader(headerId, containerId) {
    const headerRow = document.getElementById(headerId);
    if (headerRow) {
        headerRow.remove();
        updateAuthHeadersJSON(containerId);
    }
}

/**
 * Update the JSON representation of authentication headers
 * @param {string} containerId - ID of the container with headers
 */
function updateAuthHeadersJSON(containerId) {
    const container = document.getElementById(containerId);
    if (!container) {
        return;
    }

    const headers = [];
    const headerRows = container.querySelectorAll('[id^="auth-header-"]');
    const duplicateKeys = new Set();
    const seenKeys = new Set();
    let hasValidationErrors = false;

    headerRows.forEach((row) => {
        const keyInput = row.querySelector(".auth-header-key");
        const valueInput = row.querySelector(".auth-header-value");

        if (keyInput && valueInput) {
            const key = keyInput.value.trim();
            const value = valueInput.value.trim();

            // Skip completely empty rows
            if (!key && !value) {
                return;
            }

            // Require key but allow empty values
            if (!key) {
                keyInput.setCustomValidity("Header key is required");
                keyInput.reportValidity();
                hasValidationErrors = true;
                return;
            }

            // Validate header key format (letters, numbers, hyphens, underscores)
            if (!/^[a-zA-Z0-9\-_]+$/.test(key)) {
                keyInput.setCustomValidity(
                    "Header keys should contain only letters, numbers, hyphens, and underscores",
                );
                keyInput.reportValidity();
                hasValidationErrors = true;
                return;
            } else {
                keyInput.setCustomValidity("");
            }

            // Track duplicate keys
            if (seenKeys.has(key.toLowerCase())) {
                duplicateKeys.add(key);
            }
            seenKeys.add(key.toLowerCase());

            headers.push({
                key,
                value, // Allow empty values
            });
        }
    });

    // Find the corresponding JSON input field
    let jsonInput = null;
    if (containerId === "auth-headers-container") {
        jsonInput = document.getElementById("auth-headers-json");
    } else if (containerId === "auth-headers-container-gw") {
        jsonInput = document.getElementById("auth-headers-json-gw");
    } else if (containerId === "edit-auth-headers-container") {
        jsonInput = document.getElementById("edit-auth-headers-json");
    } else if (containerId === "auth-headers-container-gw-edit") {
        jsonInput = document.getElementById("auth-headers-json-gw-edit");
    }

    // Warn about duplicate keys in console
    if (duplicateKeys.size > 0 && !hasValidationErrors) {
        console.warn(
            "Duplicate header keys detected (last value will be used):",
            Array.from(duplicateKeys),
        );
    }

    // Check for excessive headers
    if (headers.length > 100) {
        console.error("Maximum of 100 headers allowed per gateway");
        return;
    }

    if (jsonInput) {
        jsonInput.value = headers.length > 0 ? JSON.stringify(headers) : "";
    }
}

/**
 * Load existing authentication headers for editing
 * @param {string} containerId - ID of the container to populate
 * @param {Array} headers - Array of header objects with key and value properties
 */
function loadAuthHeaders(containerId, headers) {
    const container = document.getElementById(containerId);
    if (!container || !headers || !Array.isArray(headers)) {
        return;
    }

    // Clear existing headers
    container.innerHTML = "";

    // Add each header
    headers.forEach((header) => {
        if (header.key && header.value) {
            addAuthHeader(containerId);
            // Find the last added header row and populate it
            const headerRows = container.querySelectorAll(
                '[id^="auth-header-"]',
            );
            const lastRow = headerRows[headerRows.length - 1];
            if (lastRow) {
                const keyInput = lastRow.querySelector(".auth-header-key");
                const valueInput = lastRow.querySelector(".auth-header-value");
                if (keyInput && valueInput) {
                    keyInput.value = header.key;
                    valueInput.value = header.value;
                }
            }
        }
    });

    updateAuthHeadersJSON(containerId);
}

// Expose authentication header functions to global scope
window.addAuthHeader = addAuthHeader;
window.removeAuthHeader = removeAuthHeader;
window.updateAuthHeadersJSON = updateAuthHeadersJSON;
window.loadAuthHeaders = loadAuthHeaders;

/**
 * Fetch tools from MCP server after OAuth completion for Authorization Code flow
 * @param {string} gatewayId - ID of the gateway to fetch tools for
 * @param {string} gatewayName - Name of the gateway for display purposes
 */
async function fetchToolsForGateway(gatewayId, gatewayName) {
    const button = document.getElementById(`fetch-tools-${gatewayId}`);
    if (!button) {
        return;
    }

    // Disable button and show loading state
    button.disabled = true;
    button.textContent = "⏳ Fetching...";
    button.className =
        "inline-block bg-yellow-600 hover:bg-yellow-700 text-white px-3 py-1 rounded text-sm mr-2";

    try {
        const response = await fetch(
            `${window.ROOT_PATH}/oauth/fetch-tools/${gatewayId}`,
            {
                method: "POST",
            },
        );

        const result = await response.json();

        if (response.ok) {
            // Success
            button.textContent = "✅ Tools Fetched";
            button.className =
                "inline-block bg-green-600 hover:bg-green-700 text-white px-3 py-1 rounded text-sm mr-2";

            // Show success message
            showSuccessMessage(
                `Successfully fetched ${result.tools_created} tools from ${gatewayName}`,
            );

            // Refresh the page to show the new tools
            setTimeout(() => {
                window.location.reload();
            }, 2000);
        } else {
            throw new Error(result.detail || "Failed to fetch tools");
        }
    } catch (error) {
        console.error("Failed to fetch tools:", error);

        // Show error state
        button.textContent = "❌ Retry";
        button.className =
            "inline-block bg-red-600 hover:bg-red-700 text-white px-3 py-1 rounded text-sm mr-2";
        button.disabled = false;

        // Show error message
        showErrorMessage(
            `Failed to fetch tools from ${gatewayName}: ${error.message}`,
        );
    }
}

// Expose fetch tools function to global scope
window.fetchToolsForGateway = fetchToolsForGateway;

console.log("🛡️ ContextForge MCP Gateway admin.js initialized");

// ===================================================================
// BULK IMPORT TOOLS — MODAL WIRING
// ===================================================================

function setupBulkImportModal() {
    const openBtn = safeGetElement("open-bulk-import", true);
    const modalId = "bulk-import-modal";
    const modal = safeGetElement(modalId, true);

    if (!openBtn || !modal) {
        // Bulk import feature not available - skip silently
        return;
    }

    // avoid double-binding if admin.js gets evaluated more than once
    if (openBtn.dataset.wired === "1") {
        return;
    }
    openBtn.dataset.wired = "1";

    const closeBtn = safeGetElement("close-bulk-import", true);
    const backdrop = safeGetElement("bulk-import-backdrop", true);
    const resultEl = safeGetElement("import-result", true);

    const focusTarget =
        modal?.querySelector("#tools_json") ||
        modal?.querySelector("#tools_file") ||
        modal?.querySelector("[data-autofocus]");

    // helpers
    const open = (e) => {
        if (e) {
            e.preventDefault();
        }
        // clear previous results each time we open
        if (resultEl) {
            resultEl.innerHTML = "";
        }
        openModal(modalId);
        // prevent background scroll
        document.documentElement.classList.add("overflow-hidden");
        document.body.classList.add("overflow-hidden");
        if (focusTarget) {
            setTimeout(() => focusTarget.focus(), 0);
        }
        return false;
    };

    const close = () => {
        // also clear results on close to keep things tidy
        closeModal(modalId, "import-result");
        document.documentElement.classList.remove("overflow-hidden");
        document.body.classList.remove("overflow-hidden");
    };

    // wire events
    openBtn.addEventListener("click", open);

    if (closeBtn) {
        closeBtn.addEventListener("click", (e) => {
            e.preventDefault();
            close();
        });
    }

    // click on backdrop only (not the dialog content) closes the modal
    if (backdrop) {
        backdrop.addEventListener("click", (e) => {
            if (e.target === backdrop) {
                close();
            }
        });
    }

    // ESC to close
    modal.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            e.stopPropagation();
            close();
        }
    });

    // FORM SUBMISSION → handle bulk import
    const form = safeGetElement("bulk-import-form", true);
    if (form) {
        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const resultEl = safeGetElement("import-result", true);
            const indicator = safeGetElement("bulk-import-indicator", true);

            try {
                const formData = new FormData();

                // Get JSON from textarea or file
                const jsonTextarea = form?.querySelector('[name="tools_json"]');
                const fileInput = form?.querySelector('[name="tools_file"]');

                let hasData = false;

                // Check for file upload first (takes precedence)
                if (fileInput && fileInput.files.length > 0) {
                    formData.append("tools_file", fileInput.files[0]);
                    hasData = true;
                } else if (jsonTextarea && jsonTextarea.value.trim()) {
                    // Validate JSON before sending
                    try {
                        const toolsData = JSON.parse(jsonTextarea.value);
                        if (!Array.isArray(toolsData)) {
                            throw new Error("JSON must be an array of tools");
                        }
                        formData.append("tools", jsonTextarea.value);
                        hasData = true;
                    } catch (err) {
                        if (resultEl) {
                            resultEl.innerHTML = `
                                <div class="mt-2 p-3 bg-red-100 border border-red-400 text-red-700 rounded">
                                    <p class="font-semibold">Invalid JSON</p>
                                    <p class="text-sm mt-1">${escapeHtml(err.message)}</p>
                                </div>
                            `;
                        }
                        return;
                    }
                }

                if (!hasData) {
                    if (resultEl) {
                        resultEl.innerHTML = `
                            <div class="mt-2 p-3 bg-yellow-100 border border-yellow-400 text-yellow-700 rounded">
                                <p class="text-sm">Please provide JSON data or upload a file</p>
                            </div>
                        `;
                    }
                    return;
                }

                // Show loading state
                if (indicator) {
                    indicator.style.display = "flex";
                }

                // Submit to backend
                const response = await fetchWithTimeout(
                    `${window.ROOT_PATH}/admin/tools/import`,
                    {
                        method: "POST",
                        body: formData,
                    },
                );

                const result = await response.json();

                // Display results
                if (resultEl) {
                    if (result.success) {
                        resultEl.innerHTML = `
                            <div class="mt-2 p-3 bg-green-100 border border-green-400 text-green-700 rounded">
                                <p class="font-semibold">Import Successful</p>
                                <p class="text-sm mt-1">${escapeHtml(result.message)}</p>
                            </div>
                        `;

                        // Close modal and refresh page after delay
                        setTimeout(() => {
                            closeModal("bulk-import-modal");
                            window.location.reload();
                        }, 2000);
                    } else if (result.imported > 0) {
                        // Partial success
                        let detailsHtml = "";
                        if (result.details && result.details.failed) {
                            detailsHtml =
                                '<ul class="mt-2 text-sm list-disc list-inside">';
                            result.details.failed.forEach((item) => {
                                detailsHtml += `<li><strong>${escapeHtml(item.name)}:</strong> ${escapeHtml(item.error)}</li>`;
                            });
                            detailsHtml += "</ul>";
                        }

                        resultEl.innerHTML = `
                            <div class="mt-2 p-3 bg-yellow-100 border border-yellow-400 text-yellow-700 rounded">
                                <p class="font-semibold">Partial Import</p>
                                <p class="text-sm mt-1">${escapeHtml(result.message)}</p>
                                ${detailsHtml}
                            </div>
                        `;
                    } else {
                        // Complete failure
                        resultEl.innerHTML = `
                            <div class="mt-2 p-3 bg-red-100 border border-red-400 text-red-700 rounded">
                                <p class="font-semibold">Import Failed</p>
                                <p class="text-sm mt-1">${escapeHtml(result.message)}</p>
                            </div>
                        `;
                    }
                }
            } catch (error) {
                console.error("Bulk import error:", error);
                if (resultEl) {
                    resultEl.innerHTML = `
                        <div class="mt-2 p-3 bg-red-100 border border-red-400 text-red-700 rounded">
                            <p class="font-semibold">Import Error</p>
                            <p class="text-sm mt-1">${escapeHtml(error.message || "An unexpected error occurred")}</p>
                        </div>
                    `;
                }
            } finally {
                // Hide loading state
                if (indicator) {
                    indicator.style.display = "none";
                }
            }

            return false;
        });
    }
}

// ===================================================================
// EXPORT/IMPORT FUNCTIONALITY
// ===================================================================

/**
 * Initialize export/import functionality
 */
function initializeExportImport() {
    // Prevent double initialization
    if (window.exportImportInitialized) {
        console.log("🔄 Export/import already initialized, skipping");
        return;
    }

    console.log("🔄 Initializing export/import functionality");

    // Export button handlers
    const exportAllBtn = document.getElementById("export-all-btn");
    const exportSelectedBtn = document.getElementById("export-selected-btn");

    if (exportAllBtn) {
        exportAllBtn.addEventListener("click", handleExportAll);
    }

    if (exportSelectedBtn) {
        exportSelectedBtn.addEventListener("click", handleExportSelected);
    }

    // Import functionality
    const importDropZone = document.getElementById("import-drop-zone");
    const importFileInput = document.getElementById("import-file-input");
    const importValidateBtn = document.getElementById("import-validate-btn");
    const importExecuteBtn = document.getElementById("import-execute-btn");

    if (importDropZone && importFileInput) {
        // File input handler
        importDropZone.addEventListener("click", () => importFileInput.click());
        importFileInput.addEventListener("change", handleFileSelect);

        // Drag and drop handlers
        importDropZone.addEventListener("dragover", handleDragOver);
        importDropZone.addEventListener("drop", handleFileDrop);
        importDropZone.addEventListener("dragleave", handleDragLeave);
    }

    if (importValidateBtn) {
        importValidateBtn.addEventListener("click", () => handleImport(true));
    }

    if (importExecuteBtn) {
        importExecuteBtn.addEventListener("click", () => handleImport(false));
    }

    // Load recent imports when tab is shown
    loadRecentImports();

    // Mark as initialized
    window.exportImportInitialized = true;
}

/**
 * Handle export all configuration
 */
async function handleExportAll() {
    console.log("📤 Starting export all configuration");

    try {
        showExportProgress(true);

        const options = getExportOptions();
        const params = new URLSearchParams();

        if (options.types.length > 0) {
            params.append("types", options.types.join(","));
        }
        if (options.tags) {
            params.append("tags", options.tags);
        }
        if (options.includeInactive) {
            params.append("include_inactive", "true");
        }
        if (!options.includeDependencies) {
            params.append("include_dependencies", "false");
        }

        const response = await fetch(
            `${window.ROOT_PATH}/admin/export/configuration?${params}`,
            {
                method: "GET",
                headers: {
                    Authorization: `Bearer ${await getAuthToken()}`,
                },
            },
        );

        if (!response.ok) {
            throw new Error(`Export failed: ${response.statusText}`);
        }

        // Create download
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `mcpgateway-export-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.json`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        showNotification("✅ Export completed successfully!", "success");
    } catch (error) {
        console.error("Export error:", error);
        showNotification(`❌ Export failed: ${error.message}`, "error");
    } finally {
        showExportProgress(false);
    }
}

/**
 * Handle export selected configuration
 */
async function handleExportSelected() {
    console.log("📋 Starting selective export");

    try {
        showExportProgress(true);

        // This would need entity selection logic - for now, just do a filtered export
        await handleExportAll(); // Simplified implementation
    } catch (error) {
        console.error("Selective export error:", error);
        showNotification(
            `❌ Selective export failed: ${error.message}`,
            "error",
        );
    } finally {
        showExportProgress(false);
    }
}

/**
 * Get export options from form
 */
function getExportOptions() {
    const types = [];

    if (document.getElementById("export-tools")?.checked) {
        types.push("tools");
    }
    if (document.getElementById("export-gateways")?.checked) {
        types.push("gateways");
    }
    if (document.getElementById("export-servers")?.checked) {
        types.push("servers");
    }
    if (document.getElementById("export-prompts")?.checked) {
        types.push("prompts");
    }
    if (document.getElementById("export-resources")?.checked) {
        types.push("resources");
    }
    if (document.getElementById("export-roots")?.checked) {
        types.push("roots");
    }

    return {
        types,
        tags: document.getElementById("export-tags")?.value || "",
        includeInactive:
            document.getElementById("export-include-inactive")?.checked ||
            false,
        includeDependencies:
            document.getElementById("export-include-dependencies")?.checked ||
            true,
    };
}

/**
 * Show/hide export progress
 */
function showExportProgress(show) {
    const progressEl = document.getElementById("export-progress");
    if (progressEl) {
        progressEl.classList.toggle("hidden", !show);
        if (show) {
            let progress = 0;
            const progressBar = document.getElementById("export-progress-bar");
            const interval = setInterval(() => {
                progress += 10;
                if (progressBar) {
                    progressBar.style.width = `${Math.min(progress, 90)}%`;
                }
                if (progress >= 100) {
                    clearInterval(interval);
                }
            }, 200);
        }
    }
}

/**
 * Handle file selection for import
 */
function handleFileSelect(event) {
    const file = event.target.files[0];
    if (file) {
        processImportFile(file);
    }
}

/**
 * Handle drag over for file drop
 */
function handleDragOver(event) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    event.currentTarget.classList.add(
        "border-blue-500",
        "bg-blue-50",
        "dark:bg-blue-900",
    );
}

/**
 * Handle drag leave
 */
function handleDragLeave(event) {
    event.preventDefault();
    event.currentTarget.classList.remove(
        "border-blue-500",
        "bg-blue-50",
        "dark:bg-blue-900",
    );
}

/**
 * Handle file drop
 */
function handleFileDrop(event) {
    event.preventDefault();
    event.currentTarget.classList.remove(
        "border-blue-500",
        "bg-blue-50",
        "dark:bg-blue-900",
    );

    const files = event.dataTransfer.files;
    if (files.length > 0) {
        processImportFile(files[0]);
    }
}

/**
 * Process selected import file
 */
function processImportFile(file) {
    console.log("📁 Processing import file:", file.name);

    if (!file.type.includes("json")) {
        showNotification("❌ Please select a JSON file", "error");
        return;
    }

    const reader = new FileReader();
    reader.onload = function (e) {
        try {
            const importData = JSON.parse(e.target.result);

            // Validate basic structure
            if (!importData.version || !importData.entities) {
                throw new Error("Invalid import file format");
            }

            // Store import data and enable buttons
            window.currentImportData = importData;

            const previewBtn = document.getElementById("import-preview-btn");
            const validateBtn = document.getElementById("import-validate-btn");
            const executeBtn = document.getElementById("import-execute-btn");

            if (previewBtn) {
                previewBtn.disabled = false;
            }
            if (validateBtn) {
                validateBtn.disabled = false;
            }
            if (executeBtn) {
                executeBtn.disabled = false;
            }

            // Update drop zone to show file loaded
            updateDropZoneStatus(file.name, importData);

            showNotification(`✅ Import file loaded: ${file.name}`, "success");
        } catch (error) {
            console.error("File processing error:", error);
            showNotification(`❌ Invalid JSON file: ${error.message}`, "error");
        }
    };

    reader.readAsText(file);
}

/**
 * Update drop zone to show loaded file
 */
function updateDropZoneStatus(fileName, importData) {
    const dropZone = document.getElementById("import-drop-zone");
    if (dropZone) {
        const entityCounts = importData.metadata?.entity_counts || {};
        const totalEntities = Object.values(entityCounts).reduce(
            (sum, count) => sum + count,
            0,
        );

        dropZone.innerHTML = `
            <div class="space-y-2">
                <svg class="mx-auto h-8 w-8 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
                <div class="text-sm text-gray-900 dark:text-white font-medium">
                    📁 ${escapeHtml(fileName)}
                </div>
                <div class="text-xs text-gray-500 dark:text-gray-400">
                    ${totalEntities} entities • Version ${escapeHtml(importData.version || "unknown")}
                </div>
                <button class="text-xs text-blue-600 dark:text-blue-400 hover:underline" onclick="resetImportFile()">
                    Choose different file
                </button>
            </div>
        `;
    }
}

/**
 * Reset import file selection
 */
function resetImportFile() {
    window.currentImportData = null;

    const dropZone = document.getElementById("import-drop-zone");
    if (dropZone) {
        dropZone.innerHTML = `
            <div class="space-y-2">
                <svg class="mx-auto h-12 w-12 text-gray-400" stroke="currentColor" fill="none" viewBox="0 0 48 48">
                    <path d="M28 8H12a4 4 0 00-4 4v20m32-12v8m0 0v8a4 4 0 01-4 4H12a4 4 0 01-4-4v-4m32-4l-3-3m-3 3l3 3m-3-3V8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <div class="text-sm text-gray-600 dark:text-gray-300">
                    <span class="font-medium text-blue-600 dark:text-blue-400">Click to upload</span>
                    or drag and drop
                </div>
                <p class="text-xs text-gray-500 dark:text-gray-400">JSON export files only</p>
            </div>
        `;
    }

    const previewBtn = document.getElementById("import-preview-btn");
    const validateBtn = document.getElementById("import-validate-btn");
    const executeBtn = document.getElementById("import-execute-btn");

    if (previewBtn) {
        previewBtn.disabled = true;
    }
    if (validateBtn) {
        validateBtn.disabled = true;
    }
    if (executeBtn) {
        executeBtn.disabled = true;
    }

    // Hide status section
    const statusSection = document.getElementById("import-status-section");
    if (statusSection) {
        statusSection.classList.add("hidden");
    }
}

/**
 * Preview import file for selective import
 */
async function previewImport() {
    console.log("🔍 Generating import preview...");

    if (!window.currentImportData) {
        showNotification("❌ Please select an import file first", "error");
        return;
    }

    try {
        showImportProgress(true);

        const response = await fetch(
            (window.ROOT_PATH || "") + "/admin/import/preview",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${await getAuthToken()}`,
                },
                body: JSON.stringify({ data: window.currentImportData }),
            },
        );

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(
                errorData.detail || `Preview failed: ${response.statusText}`,
            );
        }

        const result = await response.json();
        displayImportPreview(result.preview);

        showNotification("✅ Import preview generated successfully", "success");
    } catch (error) {
        console.error("Import preview error:", error);
        showNotification(`❌ Preview failed: ${error.message}`, "error");
    } finally {
        showImportProgress(false);
    }
}

/**
 * Handle import (validate or execute)
 */
async function handleImport(dryRun = false) {
    console.log(`🔄 Starting import (dry_run=${dryRun})`);

    if (!window.currentImportData) {
        showNotification("❌ Please select an import file first", "error");
        return;
    }

    try {
        showImportProgress(true);

        const conflictStrategy =
            document.getElementById("import-conflict-strategy")?.value ||
            "update";
        const rekeySecret =
            document.getElementById("import-rekey-secret")?.value || null;

        const requestData = {
            import_data: window.currentImportData,
            conflict_strategy: conflictStrategy,
            dry_run: dryRun,
            rekey_secret: rekeySecret,
        };

        const response = await fetch(
            (window.ROOT_PATH || "") + "/admin/import/configuration",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${await getAuthToken()}`,
                },
                body: JSON.stringify(requestData),
            },
        );

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(
                errorData.detail || `Import failed: ${response.statusText}`,
            );
        }

        const result = await response.json();
        displayImportResults(result, dryRun);

        if (!dryRun) {
            // Refresh the current tab data if import was successful
            refreshCurrentTabData();
        }
    } catch (error) {
        console.error("Import error:", error);
        showNotification(`❌ Import failed: ${error.message}`, "error");
    } finally {
        showImportProgress(false);
    }
}

/**
 * Display import results
 */
function displayImportResults(result, isDryRun) {
    const statusSection = document.getElementById("import-status-section");
    if (statusSection) {
        statusSection.classList.remove("hidden");
    }

    const progress = result.progress || {};

    // Update progress bars and counts
    updateImportCounts(progress);

    // Show messages
    displayImportMessages(result.errors || [], result.warnings || [], isDryRun);

    const action = isDryRun ? "validation" : "import";
    const statusText = result.status || "completed";
    showNotification(`✅ ${action} ${statusText}!`, "success");
}

/**
 * Update import progress counts
 */
function updateImportCounts(progress) {
    const total = progress.total || 0;
    const processed = progress.processed || 0;
    const created = progress.created || 0;
    const updated = progress.updated || 0;
    const failed = progress.failed || 0;

    document.getElementById("import-total").textContent = total;
    document.getElementById("import-created").textContent = created;
    document.getElementById("import-updated").textContent = updated;
    document.getElementById("import-failed").textContent = failed;

    // Update progress bar
    const progressBar = document.getElementById("import-progress-bar");
    const progressText = document.getElementById("import-progress-text");

    if (progressBar && progressText && total > 0) {
        const percentage = Math.round((processed / total) * 100);
        progressBar.style.width = `${percentage}%`;
        progressText.textContent = `${percentage}%`;
    }
}

/**
 * Display import messages (errors and warnings)
 */
function displayImportMessages(errors, warnings, isDryRun) {
    const messagesContainer = document.getElementById("import-messages");
    if (!messagesContainer) {
        return;
    }

    messagesContainer.innerHTML = "";

    // Show errors
    if (errors.length > 0) {
        const errorDiv = document.createElement("div");
        errorDiv.className =
            "bg-red-100 dark:bg-red-900 border border-red-400 dark:border-red-600 text-red-700 dark:text-red-300 px-4 py-3 rounded";
        errorDiv.innerHTML = `
            <div class="font-bold">❌ Errors (${errors.length})</div>
            <ul class="mt-2 text-sm list-disc list-inside">
                ${errors
                    .slice(0, 5)
                    .map((error) => `<li>${escapeHtml(error)}</li>`)
                    .join("")}
                ${errors.length > 5 ? `<li class="text-gray-600 dark:text-gray-400">... and ${errors.length - 5} more errors</li>` : ""}
            </ul>
        `;
        messagesContainer.appendChild(errorDiv);
    }

    // Show warnings
    if (warnings.length > 0) {
        const warningDiv = document.createElement("div");
        warningDiv.className =
            "bg-yellow-100 dark:bg-yellow-900 border border-yellow-400 dark:border-yellow-600 text-yellow-700 dark:text-yellow-300 px-4 py-3 rounded";
        const warningTitle = isDryRun ? "🔍 Would Import" : "⚠️ Warnings";
        warningDiv.innerHTML = `
            <div class="font-bold">${warningTitle} (${warnings.length})</div>
            <ul class="mt-2 text-sm list-disc list-inside">
                ${warnings
                    .slice(0, 5)
                    .map((warning) => `<li>${escapeHtml(warning)}</li>`)
                    .join("")}
                ${warnings.length > 5 ? `<li class="text-gray-600 dark:text-gray-400">... and ${warnings.length - 5} more warnings</li>` : ""}
            </ul>
        `;
        messagesContainer.appendChild(warningDiv);
    }
}

/**
 * Show/hide import progress
 */
function showImportProgress(show) {
    // Disable/enable buttons during operation
    const previewBtn = document.getElementById("import-preview-btn");
    const validateBtn = document.getElementById("import-validate-btn");
    const executeBtn = document.getElementById("import-execute-btn");

    if (previewBtn) {
        previewBtn.disabled = show;
    }
    if (validateBtn) {
        validateBtn.disabled = show;
    }
    if (executeBtn) {
        executeBtn.disabled = show;
    }
}

/**
 * Load recent import operations
 */
async function loadRecentImports() {
    try {
        const response = await fetch(
            (window.ROOT_PATH || "") + "/admin/import/status",
            {
                headers: {
                    Authorization: `Bearer ${await getAuthToken()}`,
                },
            },
        );

        if (response.ok) {
            const imports = await response.json();
            console.log("Loaded recent imports:", imports.length);
        }
    } catch (error) {
        console.error("Failed to load recent imports:", error);
    }
}

/**
 * Refresh current tab data after successful import
 */
function refreshCurrentTabData() {
    // Find the currently active tab and refresh its data
    const activeTab = document.querySelector(".tab-link.border-indigo-500");
    if (activeTab) {
        const href = activeTab.getAttribute("href");
        if (href === "#catalog") {
            // Refresh servers
            if (typeof window.loadCatalog === "function") {
                window.loadCatalog();
            }
        } else if (href === "#tools") {
            // Refresh tools
            if (typeof window.loadTools === "function") {
                window.loadTools();
            }
        } else if (href === "#gateways") {
            // Refresh gateways
            if (typeof window.loadGateways === "function") {
                window.loadGateways();
            }
        }
        // Add other tab refresh logic as needed
    }
}

/**
 * Show notification (simple implementation)
 */
function showNotification(message, type = "info") {
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
}

/**
 * Utility function to get cookie value
 */
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
        return parts.pop().split(";").shift();
    }
    return "";
}

// Expose functions used in dynamically generated HTML
window.resetImportFile = resetImportFile;

// ===================================================================
// A2A AGENT TESTING FUNCTIONALITY
// ===================================================================

/**
 * Test an A2A agent by making a direct invocation call
 * @param {string} agentId - ID of the agent to test
 * @param {string} agentName - Name of the agent for display
 * @param {string} endpointUrl - Endpoint URL of the agent
 */
async function testA2AAgent(agentId, agentName, endpointUrl) {
    try {
        // Show loading state
        const testResult = document.getElementById(`test-result-${agentId}`);
        testResult.innerHTML =
            '<div class="text-blue-600">🔄 Testing agent...</div>';
        testResult.classList.remove("hidden");

        // Get auth token using the robust getAuthToken function
        const token = await getAuthToken();

        // Debug logging
        console.log("Available cookies:", document.cookie);
        console.log(
            "Found token:",
            token ? "Yes (length: " + token.length + ")" : "No",
        );

        // Prepare headers
        const headers = {
            "Content-Type": "application/json",
        };

        if (token) {
            headers.Authorization = `Bearer ${token}`;
        } else {
            // Fallback to basic auth if JWT not available
            console.warn("JWT token not found, attempting basic auth fallback");
            headers.Authorization = "Basic " + btoa("admin:changeme"); // Default admin credentials
        }

        // Test payload is now determined server-side based on agent configuration
        const testPayload = {};

        // Make test request to A2A agent via admin endpoint
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/a2a/${agentId}/test`,
            {
                method: "POST",
                headers,
                body: JSON.stringify(testPayload),
            },
            window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000, // Use configurable timeout
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();

        // Display result
        let resultHtml;
        if (!result.success || result.error) {
            resultHtml = `
                <div class="text-red-600">
                    <div>❌ Test Failed</div>
                    <div class="text-xs mt-1">Error: ${escapeHtml(result.error || "Unknown error")}</div>
                </div>`;
        } else {
            // Check if the agent result contains an error (agent-level error)
            const agentResult = result.result;
            if (agentResult && agentResult.error) {
                resultHtml = `
                    <div class="text-yellow-600">
                        <div>⚠️ Agent Error</div>
                        <div class="text-xs mt-1">Agent Response: ${escapeHtml(JSON.stringify(agentResult).substring(0, 150))}...</div>
                    </div>`;
            } else {
                resultHtml = `
                    <div class="text-green-600">
                        <div>✅ Test Successful</div>
                        <div class="text-xs mt-1">Response: ${escapeHtml(JSON.stringify(agentResult).substring(0, 150))}...</div>
                    </div>`;
            }
        }

        testResult.innerHTML = resultHtml;

        // Auto-hide after 10 seconds
        setTimeout(() => {
            testResult.classList.add("hidden");
        }, 10000);
    } catch (error) {
        console.error("A2A agent test failed:", error);

        const testResult = document.getElementById(`test-result-${agentId}`);
        testResult.innerHTML = `
            <div class="text-red-600">
                <div>❌ Test Failed</div>
                <div class="text-xs mt-1">Error: ${escapeHtml(error.message)}</div>
            </div>`;
        testResult.classList.remove("hidden");

        // Auto-hide after 10 seconds
        setTimeout(() => {
            testResult.classList.add("hidden");
        }, 10000);
    }
}

// Expose A2A test function to global scope
window.testA2AAgent = testA2AAgent;

/**
 * Token Management Functions
 */

/**
 * Load tokens list from API
 */
async function loadTokensList() {
    const tokensList = safeGetElement("tokens-list");
    if (!tokensList) {
        return;
    }

    try {
        tokensList.innerHTML =
            '<p class="text-gray-500 dark:text-gray-400">Loading tokens...</p>';

        const response = await fetchWithTimeout(`${window.ROOT_PATH}/tokens`, {
            headers: {
                Authorization: `Bearer ${await getAuthToken()}`,
                "Content-Type": "application/json",
            },
        });

        if (!response.ok) {
            throw new Error(`Failed to load tokens: ${response.status}`);
        }

        const data = await response.json();
        displayTokensList(data.tokens);
    } catch (error) {
        console.error("Error loading tokens:", error);
        tokensList.innerHTML = `<div class="text-red-500">Error loading tokens: ${escapeHtml(error.message)}</div>`;
    }
}

/**
 * Display tokens list in the UI
 */
function displayTokensList(tokens) {
    const tokensList = safeGetElement("tokens-list");
    if (!tokensList) {
        return;
    }

    if (!tokens || tokens.length === 0) {
        tokensList.innerHTML =
            '<p class="text-gray-500 dark:text-gray-400">No tokens found. Create your first token above.</p>';
        return;
    }

    let tokensHTML = "";
    tokens.forEach((token) => {
        const expiresText = token.expires_at
            ? new Date(token.expires_at).toLocaleDateString()
            : "Never";
        const lastUsedText = token.last_used
            ? new Date(token.last_used).toLocaleDateString()
            : "Never";
        const statusBadge = token.is_active
            ? '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-100">Active</span>'
            : '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-800 dark:text-red-100">Inactive</span>';

        tokensHTML += `
            <div class="border border-gray-200 dark:border-gray-600 rounded-lg p-4 mb-4">
                <div class="flex justify-between items-start">
                    <div class="flex-1">
                        <div class="flex items-center space-x-2">
                            <h4 class="text-lg font-medium text-gray-900 dark:text-white">${escapeHtml(token.name)}</h4>
                            ${statusBadge}
                        </div>
                        ${token.description ? `<p class="text-sm text-gray-600 dark:text-gray-400 mt-1">${escapeHtml(token.description)}</p>` : ""}
                        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-3 text-sm text-gray-500 dark:text-gray-400">
                            <div>
                                <span class="font-medium">Created:</span> ${new Date(token.createdAt).toLocaleDateString()}
                            </div>
                            <div>
                                <span class="font-medium">Expires:</span> ${expiresText}
                            </div>
                            <div>
                                <span class="font-medium">Last Used:</span> ${lastUsedText}
                            </div>
                        </div>
                        ${token.server_id ? `<div class="mt-2 text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Scoped to Server:</span> ${escapeHtml(token.server_id)}</div>` : ""}
                        ${token.resource_scopes && token.resource_scopes.length > 0 ? `<div class="mt-1 text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Permissions:</span> ${token.resource_scopes.map((p) => escapeHtml(p)).join(", ")}</div>` : ""}
                    </div>
                    <div class="flex space-x-2 ml-4">
                        <button
                            onclick="viewTokenUsage('${token.id}')"
                            class="px-3 py-1 text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 border border-blue-300 dark:border-blue-600 hover:border-blue-500 dark:hover:border-blue-400 rounded-md"
                        >
                            Usage Stats
                        </button>
                        <button
                            onclick="revokeToken('${token.id}', '${escapeHtml(token.name)}')"
                            class="px-3 py-1 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 border border-red-300 dark:border-red-600 hover:border-red-500 dark:hover:border-red-400 rounded-md"
                        >
                            Revoke
                        </button>
                    </div>
                </div>
            </div>
        `;
    });

    tokensList.innerHTML = tokensHTML;
}

/**
 * Set up create token form handling
 */
function setupCreateTokenForm() {
    const form = safeGetElement("create-token-form");
    if (!form) {
        return;
    }

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        await createToken(form);
    });
}

/**
 * Create a new API token
 */
async function createToken(form) {
    const formData = new FormData(form);
    const submitButton = form.querySelector('button[type="submit"]');
    const originalText = submitButton.textContent;

    try {
        submitButton.textContent = "Creating...";
        submitButton.disabled = true;

        // Build request payload
        const payload = {
            name: formData.get("name"),
            description: formData.get("description") || null,
            expires_in_days: formData.get("expires_in_days")
                ? parseInt(formData.get("expires_in_days"))
                : null,
            tags: [], // Always include empty tags array
        };

        // Add scoping if provided
        const scope = {};
        if (formData.get("server_id")) {
            scope.server_id = formData.get("server_id");
        }
        if (formData.get("ip_restrictions")) {
            // Parse IP restrictions as array (split by comma if multiple)
            const ipRestrictions = formData.get("ip_restrictions").trim();
            scope.ip_restrictions = ipRestrictions
                ? ipRestrictions.split(",").map((ip) => ip.trim())
                : [];
        } else {
            scope.ip_restrictions = [];
        }
        if (formData.get("permissions")) {
            scope.permissions = formData
                .get("permissions")
                .split(",")
                .map((p) => p.trim())
                .filter((p) => p.length > 0);
        } else {
            scope.permissions = [];
        }

        // Always include time_restrictions and usage_limits as empty objects
        scope.time_restrictions = {};
        scope.usage_limits = {};

        // Always add scope object (even if empty) to ensure proper structure
        payload.scope = scope;

        const response = await fetchWithTimeout(`${window.ROOT_PATH}/tokens`, {
            method: "POST",
            headers: {
                Authorization: `Bearer ${await getAuthToken()}`,
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(
                error.detail || `Failed to create token: ${response.status}`,
            );
        }

        const result = await response.json();

        // Show the new token to the user (this is the only time they'll see it)
        showTokenCreatedModal(result);

        // Reset form and reload tokens list
        form.reset();
        await loadTokensList();

        showNotification("Token created successfully", "success");
    } catch (error) {
        console.error("Error creating token:", error);
        showNotification(`Error creating token: ${error.message}`, "error");
    } finally {
        submitButton.textContent = originalText;
        submitButton.disabled = false;
    }
}

/**
 * Show modal with new token (one-time display)
 */
function showTokenCreatedModal(tokenData) {
    const modal = document.createElement("div");
    modal.className =
        "fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50";
    modal.innerHTML = `
        <div class="relative top-20 mx-auto p-5 border w-11/12 max-w-lg shadow-lg rounded-md bg-white dark:bg-gray-800">
            <div class="mt-3">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-lg font-medium text-gray-900 dark:text-white">Token Created Successfully</h3>
                    <button onclick="this.closest('.fixed').remove()" class="text-gray-400 hover:text-gray-600">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <div class="bg-yellow-50 dark:bg-yellow-900 border border-yellow-200 dark:border-yellow-700 rounded-md p-4 mb-4">
                    <div class="flex">
                        <div class="flex-shrink-0">
                            <svg class="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                                <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
                            </svg>
                        </div>
                        <div class="ml-3">
                            <h3 class="text-sm font-medium text-yellow-800 dark:text-yellow-200">
                                Important: Save your token now!
                            </h3>
                            <div class="mt-2 text-sm text-yellow-700 dark:text-yellow-300">
                                This is the only time you will be able to see this token. Make sure to save it in a secure location.
                            </div>
                        </div>
                    </div>
                </div>

                <div class="mb-4">
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                        Your API Token:
                    </label>
                    <div class="flex">
                        <input
                            type="text"
                            value="${tokenData.access_token}"
                            readonly
                            class="flex-1 p-2 border border-gray-300 dark:border-gray-600 rounded-l-md bg-gray-50 dark:bg-gray-700 text-sm font-mono"
                            id="new-token-value"
                        />
                        <button
                            onclick="copyToClipboard('new-token-value')"
                            class="px-3 py-2 bg-indigo-600 text-white text-sm rounded-r-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        >
                            Copy
                        </button>
                    </div>
                </div>

                <div class="text-sm text-gray-600 dark:text-gray-400 mb-4">
                    <strong>Token Name:</strong> ${escapeHtml(tokenData.token.name || "Unnamed Token")}<br/>
                    <strong>Expires:</strong> ${tokenData.token.expires_at ? new Date(tokenData.token.expires_at).toLocaleDateString() : "Never"}
                </div>

                <div class="flex justify-end">
                    <button
                        onclick="this.closest('.fixed').remove()"
                        class="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    >
                        I've Saved It
                    </button>
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // Focus the token input for easy selection
    const tokenInput = modal.querySelector("#new-token-value");
    tokenInput.focus();
    tokenInput.select();
}

/**
 * Copy text to clipboard
 */
function copyToClipboard(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.select();
        document.execCommand("copy");
        showNotification("Token copied to clipboard", "success");
    }
}

/**
 * Revoke a token
 */
async function revokeToken(tokenId, tokenName) {
    if (
        !confirm(
            `Are you sure you want to revoke the token "${tokenName}"? This action cannot be undone.`,
        )
    ) {
        return;
    }

    try {
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/tokens/${tokenId}`,
            {
                method: "DELETE",
                headers: {
                    Authorization: `Bearer ${await getAuthToken()}`,
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    reason: "Revoked by user via admin interface",
                }),
            },
        );

        if (!response.ok) {
            const error = await response.json();
            throw new Error(
                error.detail || `Failed to revoke token: ${response.status}`,
            );
        }

        showNotification("Token revoked successfully", "success");
        await loadTokensList();
    } catch (error) {
        console.error("Error revoking token:", error);
        showNotification(`Error revoking token: ${error.message}`, "error");
    }
}

/**
 * View token usage statistics
 */
async function viewTokenUsage(tokenId) {
    try {
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/tokens/${tokenId}/usage`,
            {
                headers: {
                    Authorization: `Bearer ${await getAuthToken()}`,
                    "Content-Type": "application/json",
                },
            },
        );

        if (!response.ok) {
            throw new Error(`Failed to load usage stats: ${response.status}`);
        }

        const stats = await response.json();
        showUsageStatsModal(stats);
    } catch (error) {
        console.error("Error loading usage stats:", error);
        showNotification(
            `Error loading usage stats: ${error.message}`,
            "error",
        );
    }
}

/**
 * Show usage statistics modal
 */
function showUsageStatsModal(stats) {
    const modal = document.createElement("div");
    modal.className =
        "fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50";
    modal.innerHTML = `
        <div class="relative top-20 mx-auto p-5 border w-11/12 max-w-2xl shadow-lg rounded-md bg-white dark:bg-gray-800">
            <div class="flex items-center justify-between mb-4">
                <h3 class="text-lg font-medium text-gray-900 dark:text-white">Token Usage Statistics (Last ${stats.period_days} Days)</h3>
                <button onclick="this.closest('.fixed').remove()" class="text-gray-400 hover:text-gray-600">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                <div class="bg-blue-50 dark:bg-blue-900 p-4 rounded-lg">
                    <div class="text-2xl font-bold text-blue-600 dark:text-blue-300">${stats.total_requests}</div>
                    <div class="text-sm text-blue-600 dark:text-blue-400">Total Requests</div>
                </div>
                <div class="bg-green-50 dark:bg-green-900 p-4 rounded-lg">
                    <div class="text-2xl font-bold text-green-600 dark:text-green-300">${stats.successful_requests}</div>
                    <div class="text-sm text-green-600 dark:text-green-400">Successful</div>
                </div>
                <div class="bg-red-50 dark:bg-red-900 p-4 rounded-lg">
                    <div class="text-2xl font-bold text-red-600 dark:text-red-300">${stats.blocked_requests}</div>
                    <div class="text-sm text-red-600 dark:text-red-400">Blocked</div>
                </div>
                <div class="bg-purple-50 dark:bg-purple-900 p-4 rounded-lg">
                    <div class="text-2xl font-bold text-purple-600 dark:text-purple-300">${Math.round(stats.success_rate * 100)}%</div>
                    <div class="text-sm text-purple-600 dark:text-purple-400">Success Rate</div>
                </div>
            </div>

            <div class="mb-4">
                <h4 class="text-md font-medium text-gray-900 dark:text-white mb-2">Average Response Time</h4>
                <div class="text-lg text-gray-700 dark:text-gray-300">${stats.average_response_time_ms}ms</div>
            </div>

            ${
                stats.top_endpoints && stats.top_endpoints.length > 0
                    ? `
                <div class="mb-4">
                    <h4 class="text-md font-medium text-gray-900 dark:text-white mb-2">Top Endpoints</h4>
                    <div class="space-y-2">
                        ${stats.top_endpoints
                            .map(
                                ([endpoint, count]) => `
                            <div class="flex justify-between items-center p-2 bg-gray-50 dark:bg-gray-700 rounded">
                                <span class="font-mono text-sm">${escapeHtml(endpoint)}</span>
                                <span class="text-sm font-medium">${count} requests</span>
                            </div>
                        `,
                            )
                            .join("")}
                    </div>
                </div>
            `
                    : ""
            }

            <div class="flex justify-end">
                <button
                    onclick="this.closest('.fixed').remove()"
                    class="px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-500"
                >
                    Close
                </button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);
}

/**
 * Get auth token from storage or user input
 */
async function getAuthToken() {
    // Use the same authentication method as the rest of the admin interface
    let token = getCookie("jwt_token");

    // Try alternative cookie names if primary not found
    if (!token) {
        token = getCookie("token");
    }

    // Fallback to localStorage for compatibility
    if (!token) {
        token = localStorage.getItem("auth_token");
    }

    return token || "";
}

// Expose token management functions to global scope
window.loadTokensList = loadTokensList;
window.setupCreateTokenForm = setupCreateTokenForm;
window.createToken = createToken;
window.revokeToken = revokeToken;
window.viewTokenUsage = viewTokenUsage;
window.copyToClipboard = copyToClipboard;

// ===================================================================
// USER MANAGEMENT FUNCTIONS
// ===================================================================

/**
 * Show user edit modal and load edit form
 */
function showUserEditModal(userEmail) {
    const modal = document.getElementById("user-edit-modal");
    if (modal) {
        modal.style.display = "block";
        modal.classList.remove("hidden");
    }
}

/**
 * Hide user edit modal
 */
function hideUserEditModal() {
    const modal = document.getElementById("user-edit-modal");
    if (modal) {
        modal.style.display = "none";
        modal.classList.add("hidden");
    }
}

/**
 * Close modal when clicking outside of it
 */
document.addEventListener("DOMContentLoaded", function () {
    const userModal = document.getElementById("user-edit-modal");
    if (userModal) {
        userModal.addEventListener("click", function (event) {
            if (event.target === userModal) {
                hideUserEditModal();
            }
        });
    }

    const teamModal = document.getElementById("team-edit-modal");
    if (teamModal) {
        teamModal.addEventListener("click", function (event) {
            if (event.target === teamModal) {
                hideTeamEditModal();
            }
        });
    }

    // Handle HTMX events to show/hide modal
    document.body.addEventListener("htmx:afterRequest", function (event) {
        if (
            event.detail.pathInfo.requestPath.includes("/admin/users/") &&
            event.detail.pathInfo.requestPath.includes("/edit")
        ) {
            showUserEditModal();
        }
    });
});

// Expose user modal functions to global scope
window.showUserEditModal = showUserEditModal;
window.hideUserEditModal = hideUserEditModal;

// Team edit modal functions
async function showTeamEditModal(teamId) {
    // Get the root path by extracting it from the current pathname
    let rootPath = window.location.pathname;
    const adminIndex = rootPath.lastIndexOf("/admin");
    if (adminIndex !== -1) {
        rootPath = rootPath.substring(0, adminIndex);
    } else {
        rootPath = "";
    }

    // Construct the full URL - ensure it starts with /
    const url = (rootPath || "") + "/admin/teams/" + teamId + "/edit";

    // Load the team edit form via HTMX
    fetch(url, {
        method: "GET",
        headers: {
            Authorization: "Bearer " + (await getAuthToken()),
        },
    })
        .then((response) => response.text())
        .then((html) => {
            document.getElementById("team-edit-modal-content").innerHTML = html;
            document
                .getElementById("team-edit-modal")
                .classList.remove("hidden");
        })
        .catch((error) => {
            console.error("Error loading team edit form:", error);
        });
}

function hideTeamEditModal() {
    document.getElementById("team-edit-modal").classList.add("hidden");
}

// Expose team modal functions to global scope
window.showTeamEditModal = showTeamEditModal;
window.hideTeamEditModal = hideTeamEditModal;

// Team member management functions
function showAddMemberForm(teamId) {
    const form = document.getElementById("add-member-form-" + teamId);
    if (form) {
        form.classList.remove("hidden");
    }
}

function hideAddMemberForm(teamId) {
    const form = document.getElementById("add-member-form-" + teamId);
    if (form) {
        form.classList.add("hidden");
        // Reset form
        const formElement = form.querySelector("form");
        if (formElement) {
            formElement.reset();
        }
    }
}

// Expose team member management functions to global scope
window.showAddMemberForm = showAddMemberForm;
window.hideAddMemberForm = hideAddMemberForm;

// Logs refresh function
function refreshLogs() {
    const logsSection = document.getElementById("logs");
    if (logsSection && typeof window.htmx !== "undefined") {
        // Trigger HTMX refresh on the logs section
        window.htmx.trigger(logsSection, "refresh");
    }
}

// Expose logs functions to global scope
window.refreshLogs = refreshLogs;

// User edit modal functions (already defined above)
// Functions are already exposed to global scope

// Team permissions functions are implemented in the admin.html template
// Remove placeholder functions to avoid overriding template functionality

function initializePermissionsPanel() {
    // Load team data if available
    if (window.USER_TEAMS && window.USER_TEAMS.length > 0) {
        const membersList = document.getElementById("team-members-list");
        const rolesList = document.getElementById("role-assignments-list");

        if (membersList) {
            membersList.innerHTML =
                '<div class="text-sm text-gray-500 dark:text-gray-400">Use the Teams Management tab to view and manage team members.</div>';
        }

        if (rolesList) {
            rolesList.innerHTML =
                '<div class="text-sm text-gray-500 dark:text-gray-400">Use the Teams Management tab to assign roles to team members.</div>';
        }
    }
}

// Permission functions are implemented in admin.html template - don't override them
window.initializePermissionsPanel = initializePermissionsPanel;

// ===================================================================
// TEAM DISCOVERY AND SELF-SERVICE FUNCTIONS
// ===================================================================

/**
 * Load and display public teams that the user can join
 */
async function loadPublicTeams() {
    const container = safeGetElement("public-teams-list");
    if (!container) {
        console.error("Public teams list container not found");
        return;
    }

    // Show loading state
    container.innerHTML =
        '<div class="animate-pulse text-gray-500 dark:text-gray-400">Loading public teams...</div>';

    try {
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH || ""}/teams/discover`,
            {
                headers: {
                    Authorization: `Bearer ${await getAuthToken()}`,
                    "Content-Type": "application/json",
                },
            },
        );
        if (!response.ok) {
            throw new Error(`Failed to load teams: ${response.status}`);
        }

        const teams = await response.json();
        displayPublicTeams(teams);
    } catch (error) {
        console.error("Error loading public teams:", error);
        container.innerHTML = `
            <div class="bg-red-50 dark:bg-red-900 border border-red-200 dark:border-red-700 rounded-md p-4">
                <div class="flex">
                    <div class="flex-shrink-0">
                        <svg class="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clip-rule="evenodd" />
                        </svg>
                    </div>
                    <div class="ml-3">
                        <h3 class="text-sm font-medium text-red-800 dark:text-red-200">
                            Failed to load public teams
                        </h3>
                        <div class="mt-2 text-sm text-red-700 dark:text-red-300">
                            ${escapeHtml(error.message)}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
}

/**
 * Display public teams in the UI
 * @param {Array} teams - Array of team objects
 */
function displayPublicTeams(teams) {
    const container = safeGetElement("public-teams-list");
    if (!container) {
        return;
    }

    if (!teams || teams.length === 0) {
        container.innerHTML = `
            <div class="text-center py-8">
                <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.83-1M17 20H7m10 0v-2c0-1.09-.29-2.11-.83-3M7 20v2m0-2v-2a3 3 0 011.87-2.77m0 0A3 3 0 017 12m0 0a3 3 0 013-3m-3 3h6.4M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <h3 class="mt-2 text-sm font-medium text-gray-900 dark:text-gray-100">No public teams found</h3>
                <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">There are no public teams available to join at the moment.</p>
            </div>
        `;
        return;
    }

    // Create teams grid
    const teamsHtml = teams
        .map(
            (team) => `
        <div class="bg-white dark:bg-gray-700 shadow rounded-lg p-6 hover:shadow-lg transition-shadow">
            <div class="flex items-center justify-between">
                <h3 class="text-lg font-medium text-gray-900 dark:text-white">
                    ${escapeHtml(team.name)}
                </h3>
                <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                    Public
                </span>
            </div>

            ${
                team.description
                    ? `
                <p class="mt-2 text-sm text-gray-600 dark:text-gray-300">
                    ${escapeHtml(team.description)}
                </p>
            `
                    : ""
            }

            <div class="mt-4 flex items-center justify-between">
                <div class="flex items-center text-sm text-gray-500 dark:text-gray-400">
                    <svg class="flex-shrink-0 mr-1.5 h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                        <path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z"/>
                    </svg>
                    ${team.member_count} members
                </div>
                <button
                    onclick="requestToJoinTeam('${escapeHtml(team.id)}')"
                    class="px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
                >
                    Request to Join
                </button>
            </div>
        </div>
    `,
        )
        .join("");

    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            ${teamsHtml}
        </div>
    `;
}

/**
 * Request to join a public team
 * @param {string} teamId - ID of the team to join
 */
async function requestToJoinTeam(teamId) {
    if (!teamId) {
        console.error("Team ID is required");
        return;
    }

    // Show confirmation dialog
    const message = prompt("Optional: Enter a message to the team owners:");

    try {
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH || ""}/teams/${teamId}/join`,
            {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${await getAuthToken()}`,
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    message: message || null,
                }),
            },
        );

        if (!response.ok) {
            const errorData = await response.json().catch(() => null);
            throw new Error(
                errorData?.detail ||
                    `Failed to request join: ${response.status}`,
            );
        }

        const result = await response.json();

        // Show success message
        showSuccessMessage(
            `Join request sent to ${result.team_name}! Team owners will review your request.`,
        );

        // Refresh the public teams list
        setTimeout(loadPublicTeams, 1000);
    } catch (error) {
        console.error("Error requesting to join team:", error);
        showErrorMessage(`Failed to send join request: ${error.message}`);
    }
}

/**
 * Leave a team
 * @param {string} teamId - ID of the team to leave
 * @param {string} teamName - Name of the team (for confirmation)
 */
async function leaveTeam(teamId, teamName) {
    if (!teamId) {
        console.error("Team ID is required");
        return;
    }

    // Show confirmation dialog
    const confirmed = confirm(
        `Are you sure you want to leave the team "${teamName}"? This action cannot be undone.`,
    );
    if (!confirmed) {
        return;
    }

    try {
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH || ""}/teams/${teamId}/leave`,
            {
                method: "DELETE",
                headers: {
                    Authorization: `Bearer ${await getAuthToken()}`,
                    "Content-Type": "application/json",
                },
            },
        );

        if (!response.ok) {
            const errorData = await response.json().catch(() => null);
            throw new Error(
                errorData?.detail || `Failed to leave team: ${response.status}`,
            );
        }

        await response.json();

        // Show success message
        showSuccessMessage(`Successfully left ${teamName}`);

        // Refresh teams list
        const teamsList = safeGetElement("teams-list");
        if (teamsList && window.htmx) {
            window.htmx.trigger(teamsList, "load");
        }

        // Refresh team selector if available
        if (typeof updateTeamContext === "function") {
            // Force reload teams data
            setTimeout(() => {
                window.location.reload();
            }, 1500);
        }
    } catch (error) {
        console.error("Error leaving team:", error);
        showErrorMessage(`Failed to leave team: ${error.message}`);
    }
}

/**
 * Approve a join request
 * @param {string} teamId - ID of the team
 * @param {string} requestId - ID of the join request
 */
async function approveJoinRequest(teamId, requestId) {
    if (!teamId || !requestId) {
        console.error("Team ID and request ID are required");
        return;
    }

    try {
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH || ""}/teams/${teamId}/join-requests/${requestId}/approve`,
            {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${await getAuthToken()}`,
                    "Content-Type": "application/json",
                },
            },
        );

        if (!response.ok) {
            const errorData = await response.json().catch(() => null);
            throw new Error(
                errorData?.detail ||
                    `Failed to approve join request: ${response.status}`,
            );
        }

        const result = await response.json();

        // Show success message
        showSuccessMessage(
            `Join request approved! ${result.user_email} is now a member.`,
        );

        // Refresh teams list
        const teamsList = safeGetElement("teams-list");
        if (teamsList && window.htmx) {
            window.htmx.trigger(teamsList, "load");
        }
    } catch (error) {
        console.error("Error approving join request:", error);
        showErrorMessage(`Failed to approve join request: ${error.message}`);
    }
}

/**
 * Reject a join request
 * @param {string} teamId - ID of the team
 * @param {string} requestId - ID of the join request
 */
async function rejectJoinRequest(teamId, requestId) {
    if (!teamId || !requestId) {
        console.error("Team ID and request ID are required");
        return;
    }

    const confirmed = confirm(
        "Are you sure you want to reject this join request?",
    );
    if (!confirmed) {
        return;
    }

    try {
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH || ""}/teams/${teamId}/join-requests/${requestId}`,
            {
                method: "DELETE",
                headers: {
                    Authorization: `Bearer ${await getAuthToken()}`,
                    "Content-Type": "application/json",
                },
            },
        );

        if (!response.ok) {
            const errorData = await response.json().catch(() => null);
            throw new Error(
                errorData?.detail ||
                    `Failed to reject join request: ${response.status}`,
            );
        }

        // Show success message
        showSuccessMessage("Join request rejected.");

        // Refresh teams list
        const teamsList = safeGetElement("teams-list");
        if (teamsList && window.htmx) {
            window.htmx.trigger(teamsList, "load");
        }
    } catch (error) {
        console.error("Error rejecting join request:", error);
        showErrorMessage(`Failed to reject join request: ${error.message}`);
    }
}

// Expose team functions to global scope
window.loadPublicTeams = loadPublicTeams;
window.requestToJoinTeam = requestToJoinTeam;
window.leaveTeam = leaveTeam;
window.approveJoinRequest = approveJoinRequest;
window.rejectJoinRequest = rejectJoinRequest;

/**
 * Validate password match in user edit form
 */
function validatePasswordMatch() {
    const passwordField = document.getElementById("password-field");
    const confirmPasswordField = document.getElementById(
        "confirm-password-field",
    );
    const messageElement = document.getElementById("password-match-message");
    const submitButton = document.querySelector(
        '#user-edit-modal-content button[type="submit"]',
    );

    if (!passwordField || !confirmPasswordField || !messageElement) {
        return;
    }

    const password = passwordField.value;
    const confirmPassword = confirmPasswordField.value;

    // Only show validation if both fields have content or if confirm field has content
    if (
        (password.length > 0 || confirmPassword.length > 0) &&
        password !== confirmPassword
    ) {
        messageElement.classList.remove("hidden");
        confirmPasswordField.classList.add("border-red-500");
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.classList.add("opacity-50", "cursor-not-allowed");
        }
    } else {
        messageElement.classList.add("hidden");
        confirmPasswordField.classList.remove("border-red-500");
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.classList.remove("opacity-50", "cursor-not-allowed");
        }
    }
}

// Expose password validation function to global scope
window.validatePasswordMatch = validatePasswordMatch;

// ===================================================================
// SELECTIVE IMPORT FUNCTIONS
// ===================================================================

/**
 * Display import preview with selective import options
 */
function displayImportPreview(preview) {
    console.log("📋 Displaying import preview:", preview);

    // Find or create preview container
    let previewContainer = document.getElementById("import-preview-container");
    if (!previewContainer) {
        previewContainer = document.createElement("div");
        previewContainer.id = "import-preview-container";
        previewContainer.className = "mt-6 border-t pt-6";

        // Insert after import options in the import section
        const importSection =
            document.querySelector("#import-drop-zone").parentElement
                .parentElement;
        importSection.appendChild(previewContainer);
    }

    previewContainer.innerHTML = `
        <h4 class="text-lg font-medium text-gray-900 dark:text-white mb-4">
            📋 Selective Import - Choose What to Import
        </h4>

        <!-- Summary -->
        <div class="bg-blue-50 dark:bg-blue-900 border border-blue-200 dark:border-blue-800 rounded-lg p-4 mb-6">
            <div class="flex items-center">
                <div class="ml-3">
                    <h3 class="text-sm font-medium text-blue-800 dark:text-blue-200">
                        Found ${preview.summary.total_items} items in import file
                    </h3>
                    <div class="mt-1 text-sm text-blue-600 dark:text-blue-300">
                        ${Object.entries(preview.summary.by_type)
                            .map(([type, count]) => `${type}: ${count}`)
                            .join(", ")}
                    </div>
                </div>
            </div>
        </div>

        <!-- Selection Controls -->
        <div class="flex justify-between items-center mb-4">
            <div class="space-x-4">
                <button onclick="selectAllItems()"
                        class="text-sm text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 underline">
                    Select All
                </button>
                <button onclick="selectNoneItems()"
                        class="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-300 underline">
                    Select None
                </button>
                <button onclick="selectOnlyCustom()"
                        class="text-sm text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-300 underline">
                    Custom Items Only
                </button>
            </div>

            <div class="text-sm text-gray-500 dark:text-gray-400">
                <span id="selection-count">0 items selected</span>
            </div>
        </div>

        <!-- Gateway Bundles -->
        ${
            Object.keys(preview.bundles || {}).length > 0
                ? `
            <div class="mb-6">
                <h5 class="text-md font-medium text-gray-900 dark:text-white mb-3">
                    🌐 Gateway Bundles (Gateway + Auto-discovered Items)
                </h5>
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    ${Object.entries(preview.bundles)
                        .map(
                            ([gatewayName, bundle]) => `
                        <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-4 hover:bg-gray-50 dark:hover:bg-gray-750">
                            <label class="flex items-start cursor-pointer">
                                <input type="checkbox"
                                       class="gateway-checkbox mt-1 mr-3"
                                       data-gateway="${gatewayName}"
                                       onchange="updateSelectionCount()">
                                <div class="flex-1">
                                    <div class="font-medium text-gray-900 dark:text-white">
                                        ${bundle.gateway.name}
                                    </div>
                                    <div class="text-sm text-gray-500 dark:text-gray-400 mb-2">
                                        ${bundle.gateway.description || "No description"}
                                    </div>
                                    <div class="text-xs text-blue-600 dark:text-blue-400">
                                        Bundle includes: ${bundle.total_items} items
                                        (${Object.entries(bundle.items)
                                            .filter(
                                                ([type, items]) =>
                                                    items.length > 0,
                                            )
                                            .map(
                                                ([type, items]) =>
                                                    `${items.length} ${type}`,
                                            )
                                            .join(", ")})
                                    </div>
                                </div>
                            </label>
                        </div>
                    `,
                        )
                        .join("")}
                </div>
            </div>
        `
                : ""
        }

        <!-- Custom Items by Type -->
        ${Object.entries(preview.items || {})
            .map(([entityType, items]) => {
                const customItems = items.filter((item) => item.is_custom);
                return customItems.length > 0
                    ? `
                <div class="mb-6">
                    <h5 class="text-md font-medium text-gray-900 dark:text-white mb-3 capitalize">
                        🛠️ Custom ${entityType}
                    </h5>
                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        ${customItems
                            .map(
                                (item) => `
                            <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-3 hover:bg-gray-50 dark:hover:bg-gray-750 ${item.conflicts_with ? "border-orange-300 dark:border-orange-700 bg-orange-50 dark:bg-orange-900" : ""}">
                                <label class="flex items-start cursor-pointer">
                                    <input type="checkbox"
                                           class="item-checkbox mt-1 mr-3"
                                           data-type="${entityType}"
                                           data-id="${item.id}"
                                           onchange="updateSelectionCount()">
                                    <div class="flex-1">
                                        <div class="text-sm font-medium text-gray-900 dark:text-white">
                                            ${item.name}
                                            ${
                                                item.conflicts_with
                                                    ? '<span class="text-orange-600 text-xs ml-1">⚠️ Conflict</span>'
                                                    : ""
                                            }
                                        </div>
                                        <div class="text-xs text-gray-500 dark:text-gray-400">
                                            ${item.description || `Custom ${entityType} item`}
                                        </div>
                                    </div>
                                </label>
                            </div>
                        `,
                            )
                            .join("")}
                    </div>
                </div>
            `
                    : "";
            })
            .join("")}

        <!-- Conflicts Warning -->
        ${
            Object.keys(preview.conflicts || {}).length > 0
                ? `
            <div class="mb-6">
                <div class="bg-orange-50 dark:bg-orange-900 border border-orange-200 dark:border-orange-800 rounded-lg p-4">
                    <div class="flex items-start">
                        <div class="flex-shrink-0">
                            <svg class="h-5 w-5 text-orange-400" fill="currentColor" viewBox="0 0 20 20">
                                <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
                            </svg>
                        </div>
                        <div class="ml-3">
                            <h3 class="text-sm font-medium text-orange-800 dark:text-orange-200">
                                Naming conflicts detected
                            </h3>
                            <div class="mt-1 text-sm text-orange-600 dark:text-orange-300">
                                Some items have the same names as existing items. Use conflict strategy to resolve.
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `
                : ""
        }

        <!-- Action Buttons -->
        <div class="flex justify-between pt-6 border-t border-gray-200 dark:border-gray-700">
            <button onclick="resetImportSelection()"
                    class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-700">
                🔄 Reset Selection
            </button>

            <div class="space-x-3">
                <button onclick="handleSelectiveImport(true)"
                        class="px-4 py-2 text-sm font-medium text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-900 border border-blue-200 dark:border-blue-800 rounded-md hover:bg-blue-100 dark:hover:bg-blue-800">
                    🧪 Preview Selected
                </button>
                <button onclick="handleSelectiveImport(false)"
                        class="px-4 py-2 text-sm font-medium text-white bg-green-600 border border-transparent rounded-md hover:bg-green-700">
                    ✅ Import Selected Items
                </button>
            </div>
        </div>
    `;

    // Store preview data and show preview section
    window.currentImportPreview = preview;
    updateSelectionCount();
}

/**
 * Handle selective import based on user selections
 */
async function handleSelectiveImport(dryRun = false) {
    console.log(`🎯 Starting selective import (dry_run=${dryRun})`);

    if (!window.currentImportData) {
        showNotification("❌ Please select an import file first", "error");
        return;
    }

    try {
        showImportProgress(true);

        // Collect user selections
        const selectedEntities = collectUserSelections();

        if (Object.keys(selectedEntities).length === 0) {
            showNotification(
                "❌ Please select at least one item to import",
                "warning",
            );
            showImportProgress(false);
            return;
        }

        const conflictStrategy =
            document.getElementById("import-conflict-strategy")?.value ||
            "update";
        const rekeySecret =
            document.getElementById("import-rekey-secret")?.value || null;

        const requestData = {
            import_data: window.currentImportData,
            conflict_strategy: conflictStrategy,
            dry_run: dryRun,
            rekey_secret: rekeySecret,
            selectedEntities,
        };

        console.log("🎯 Selected entities for import:", selectedEntities);

        const response = await fetch(
            (window.ROOT_PATH || "") + "/admin/import/configuration",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${await getAuthToken()}`,
                },
                body: JSON.stringify(requestData),
            },
        );

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(
                errorData.detail || `Import failed: ${response.statusText}`,
            );
        }

        const result = await response.json();
        displayImportResults(result, dryRun);

        if (!dryRun) {
            refreshCurrentTabData();
            showNotification(
                "✅ Selective import completed successfully",
                "success",
            );
        } else {
            showNotification("✅ Import preview completed", "success");
        }
    } catch (error) {
        console.error("Selective import error:", error);
        showNotification(`❌ Import failed: ${error.message}`, "error");
    } finally {
        showImportProgress(false);
    }
}

/**
 * Collect user selections for selective import
 */
function collectUserSelections() {
    const selections = {};

    // Collect gateway selections
    document
        .querySelectorAll(".gateway-checkbox:checked")
        .forEach((checkbox) => {
            const gatewayName = checkbox.dataset.gateway;
            if (!selections.gateways) {
                selections.gateways = [];
            }
            selections.gateways.push(gatewayName);
        });

    // Collect individual item selections
    document.querySelectorAll(".item-checkbox:checked").forEach((checkbox) => {
        const entityType = checkbox.dataset.type;
        const itemId = checkbox.dataset.id;
        if (!selections[entityType]) {
            selections[entityType] = [];
        }
        selections[entityType].push(itemId);
    });

    return selections;
}

/**
 * Update selection count display
 */
function updateSelectionCount() {
    const gatewayCount = document.querySelectorAll(
        ".gateway-checkbox:checked",
    ).length;
    const itemCount = document.querySelectorAll(
        ".item-checkbox:checked",
    ).length;
    const totalCount = gatewayCount + itemCount;

    const countElement = document.getElementById("selection-count");
    if (countElement) {
        countElement.textContent = `${totalCount} items selected (${gatewayCount} gateways, ${itemCount} individual items)`;
    }
}

/**
 * Select all items
 */
function selectAllItems() {
    document
        .querySelectorAll(".gateway-checkbox, .item-checkbox")
        .forEach((checkbox) => {
            checkbox.checked = true;
        });
    updateSelectionCount();
}

/**
 * Select no items
 */
function selectNoneItems() {
    document
        .querySelectorAll(".gateway-checkbox, .item-checkbox")
        .forEach((checkbox) => {
            checkbox.checked = false;
        });
    updateSelectionCount();
}

/**
 * Select only custom items (not gateway items)
 */
function selectOnlyCustom() {
    document.querySelectorAll(".gateway-checkbox").forEach((checkbox) => {
        checkbox.checked = false;
    });
    document.querySelectorAll(".item-checkbox").forEach((checkbox) => {
        checkbox.checked = true;
    });
    updateSelectionCount();
}

/**
 * Reset import selection
 */
function resetImportSelection() {
    const previewContainer = document.getElementById(
        "import-preview-container",
    );
    if (previewContainer) {
        previewContainer.remove();
    }
    window.currentImportPreview = null;
}

/* ---------------------------------------------------------------------------
  Robust reloadAllResourceSections
  - Replaces each section's full innerHTML with a server-rendered partial
  - Restores saved initial markup on failure
  - Re-runs initializers (Alpine, CodeMirror, select/pills, event handlers)
--------------------------------------------------------------------------- */

(function registerReloadAllResourceSections() {
    // list of sections we manage
    const SECTION_NAMES = [
        "tools",
        "resources",
        "prompts",
        "servers",
        "gateways",
        "catalog",
    ];

    // Save initial markup on first full load so we can restore exactly if needed
    document.addEventListener("DOMContentLoaded", () => {
        window.__initialSectionMarkup = window.__initialSectionMarkup || {};
        SECTION_NAMES.forEach((s) => {
            const el = document.getElementById(`${s}-section`);
            if (el && !(s in window.__initialSectionMarkup)) {
                // store the exact innerHTML produced by the server initially
                window.__initialSectionMarkup[s] = el.innerHTML;
            }
        });
    });

    // Helper: try to re-run common initializers after a section's DOM is replaced
    function reinitializeSection(sectionEl, sectionName) {
        try {
            if (!sectionEl) {
                return;
            }

            // 1) Re-init Alpine for the new subtree (if Alpine is present)
            try {
                if (window.Alpine) {
                    // For Alpine 3 use initTree if available
                    if (typeof window.Alpine.initTree === "function") {
                        window.Alpine.initTree(sectionEl);
                    } else if (
                        typeof window.Alpine.discoverAndRegisterComponents ===
                        "function"
                    ) {
                        // fallback: attempt a component discovery if available
                        window.Alpine.discoverAndRegisterComponents(sectionEl);
                    }
                }
            } catch (err) {
                console.warn(
                    "Alpine re-init failed for section",
                    sectionName,
                    err,
                );
            }

            // 2) Re-initialize tool/resource/pill helpers that expect DOM structure
            try {
                // these functions exist elsewhere in admin.js; call them if present
                if (typeof initResourceSelect === "function") {
                    // Many panels use specific ids — attempt to call generic initializers if they exist
                    initResourceSelect(
                        "associatedResources",
                        "resource-pills",
                        "resource-warn",
                        10,
                        null,
                        null,
                    );
                }
                if (typeof initToolSelect === "function") {
                    initToolSelect(
                        "associatedTools",
                        "tool-pills",
                        "tool-warn",
                        10,
                        null,
                        null,
                    );
                }
                // restore generic tool/resource selection areas if present
                if (typeof initResourceSelect === "function") {
                    // try specific common containers if present (safeGetElement suppresses warnings)
                    const containers = [
                        "edit-server-resources",
                        "edit-server-tools",
                    ];
                    containers.forEach((cid) => {
                        const c = document.getElementById(cid);
                        if (c && typeof initResourceSelect === "function") {
                            // caller may have different arg signature — best-effort call is OK
                            // we don't want to throw here if arguments mismatch
                            try {
                                /* no args: assume function will find DOM by ids */ initResourceSelect();
                            } catch (e) {
                                /* ignore */
                            }
                        }
                    });
                }
            } catch (err) {
                console.warn("Select/pill reinit error", err);
            }

            // 3) Re-run integration & schema handlers which attach behaviour to new inputs
            try {
                if (typeof setupIntegrationTypeHandlers === "function") {
                    setupIntegrationTypeHandlers();
                }
                if (typeof setupSchemaModeHandlers === "function") {
                    setupSchemaModeHandlers();
                }
            } catch (err) {
                console.warn("Integration/schema handler reinit failed", err);
            }

            // 4) Reinitialize CodeMirror editors within the replaced DOM (if CodeMirror used)
            try {
                if (window.CodeMirror) {
                    // For any <textarea class="codemirror"> re-create or refresh editors
                    const textareas = sectionEl.querySelectorAll("textarea");
                    textareas.forEach((ta) => {
                        // If the page previously attached a CodeMirror instance on same textarea,
                        // the existing instance may have been stored on the element. If refresh available, refresh it.
                        if (
                            ta.CodeMirror &&
                            typeof ta.CodeMirror.refresh === "function"
                        ) {
                            ta.CodeMirror.refresh();
                        } else {
                            // Create a new CodeMirror instance only when an explicit init function is present on page
                            if (
                                typeof window.createCodeMirrorForTextarea ===
                                "function"
                            ) {
                                try {
                                    window.createCodeMirrorForTextarea(ta);
                                } catch (e) {
                                    // ignore - not all textareas need CodeMirror
                                }
                            }
                        }
                    });
                }
            } catch (err) {
                console.warn("CodeMirror reinit failed", err);
            }

            // 5) Re-attach generic event wiring that is expected by the UI (checkboxes, buttons)
            try {
                // checkbox-driven pill updates
                const checkboxChangeEvent = new Event("change", {
                    bubbles: true,
                });
                sectionEl
                    .querySelectorAll('input[type="checkbox"]')
                    .forEach((cb) => {
                        // If there were checkbox-specific change functions on page, they will now re-run
                        cb.dispatchEvent(checkboxChangeEvent);
                    });

                // Reconnect any HTMX triggers that expect a load event
                if (window.htmx && typeof window.htmx.trigger === "function") {
                    // find elements with data-htmx or that previously had an HTMX load
                    const htmxTargets = sectionEl.querySelectorAll(
                        "[hx-get], [hx-post], [data-hx-load]",
                    );
                    htmxTargets.forEach((el) => {
                        try {
                            window.htmx.trigger(el, "load");
                        } catch (e) {
                            /* ignore */
                        }
                    });
                }
            } catch (err) {
                console.warn("Event wiring re-attach failed", err);
            }

            // 6) Accessibility / visual: force a small layout reflow, useful in some browsers
            try {
                // eslint-disable-next-line no-unused-expressions
                sectionEl.offsetHeight; // read to force reflow
            } catch (e) {
                /* ignore */
            }
        } catch (err) {
            console.error("Error reinitializing section", sectionName, err);
        }
    }

    function updateSectionHeaders(teamId) {
        const sections = [
            "tools",
            "resources",
            "prompts",
            "servers",
            "gateways",
        ];

        sections.forEach((section) => {
            const header = document.querySelector(
                "#" + section + "-section h2",
            );
            if (header) {
                // Remove existing team badge
                const existingBadge = header.querySelector(".team-badge");
                if (existingBadge) {
                    existingBadge.remove();
                }

                // Add team badge if team is selected
                if (teamId && teamId !== "") {
                    const teamName = getTeamNameById(teamId);
                    if (teamName) {
                        const badge = document.createElement("span");
                        badge.className =
                            "team-badge inline-flex items-center px-2 py-1 ml-2 text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 rounded-full";
                        badge.textContent = teamName;
                        header.appendChild(badge);
                    }
                }
            }
        });
    }

    function getTeamNameById(teamId) {
        // Get team name from Alpine.js data or fallback
        const teamSelector = document.querySelector('[x-data*="selectedTeam"]');
        if (
            teamSelector &&
            teamSelector._x_dataStack &&
            teamSelector._x_dataStack[0].teams
        ) {
            const team = teamSelector._x_dataStack[0].teams.find(
                (t) => t.id === teamId,
            );
            return team ? team.name : null;
        }
        return null;
    }

    // The exported function: reloadAllResourceSections
    async function reloadAllResourceSections(teamId) {
        const sections = [
            "tools",
            "resources",
            "prompts",
            "servers",
            "gateways",
        ];

        // ensure there is a ROOT_PATH set
        if (!window.ROOT_PATH) {
            console.warn(
                "ROOT_PATH not defined; aborting reloadAllResourceSections",
            );
            return;
        }

        // Iterate sections sequentially to avoid overloading the server and to ensure consistent order.
        for (const section of sections) {
            const sectionEl = document.getElementById(`${section}-section`);
            if (!sectionEl) {
                console.warn(`Section element not found: ${section}-section`);
                continue;
            }

            // Build server partial URL (server should return the *full HTML fragment* for the section)
            // Server endpoint pattern: /admin/sections/{section}?partial=true
            let url = `${window.ROOT_PATH}/admin/sections/${section}?partial=true`;
            if (teamId && teamId !== "") {
                url += `&team_id=${encodeURIComponent(teamId)}`;
            }

            try {
                const resp = await fetchWithTimeout(
                    url,
                    { credentials: "same-origin" },
                    window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000,
                );
                if (!resp.ok) {
                    throw new Error(`HTTP ${resp.status}`);
                }
                const html = await resp.text();

                // Replace entire section's innerHTML with server-provided HTML to keep DOM identical.
                // Use safeSetInnerHTML with isTrusted = true because this is server-rendered trusted content.
                safeSetInnerHTML(sectionEl, html, true);

                // After replacement, re-run local initializers so the new DOM behaves like initial load
                reinitializeSection(sectionEl, section);
            } catch (err) {
                console.error(
                    `Failed to load section ${section} from server:`,
                    err,
                );

                // Restore the original markup exactly as it was on initial load (fallback)
                if (
                    window.__initialSectionMarkup &&
                    window.__initialSectionMarkup[section]
                ) {
                    sectionEl.innerHTML =
                        window.__initialSectionMarkup[section];
                    // Re-run initializers on restored markup as well
                    reinitializeSection(sectionEl, section);
                    console.log(
                        `Restored initial markup for section ${section}`,
                    );
                } else {
                    // No fallback available: leave existing DOM intact and show error to console
                    console.warn(
                        `No saved initial markup for section ${section}; leaving DOM untouched`,
                    );
                }
            }
        }

        // Update headers (team badges) after reload
        try {
            if (typeof updateSectionHeaders === "function") {
                updateSectionHeaders(teamId);
            }
        } catch (err) {
            console.warn("updateSectionHeaders failed after reload", err);
        }

        console.log("✓ reloadAllResourceSections completed");
    }

    // Export to global to keep old callers working
    window.reloadAllResourceSections = reloadAllResourceSections;
})();

// Expose selective import functions to global scope
window.previewImport = previewImport;
window.handleSelectiveImport = handleSelectiveImport;
window.displayImportPreview = displayImportPreview;
window.collectUserSelections = collectUserSelections;
window.updateSelectionCount = updateSelectionCount;
window.selectAllItems = selectAllItems;
window.selectNoneItems = selectNoneItems;
window.selectOnlyCustom = selectOnlyCustom;
window.resetImportSelection = resetImportSelection;
