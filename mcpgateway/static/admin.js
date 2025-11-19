const MASKED_AUTH_VALUE = "*****";

// Add three fields to passthrough section on Advanced button click
function handleAddPassthrough() {
    const passthroughContainer = safeGetElement("passthrough-container");
    if (!passthroughContainer) {
        console.error("Passthrough container not found");
        return;
    }

    // Toggle visibility
    if (
        passthroughContainer.style.display === "none" ||
        passthroughContainer.style.display === ""
    ) {
        passthroughContainer.style.display = "block";
        // Add fields only if not already present
        if (!document.getElementById("query-mapping-field")) {
            const queryDiv = document.createElement("div");
            queryDiv.className = "mb-4";
            queryDiv.innerHTML = `
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Query Mapping (JSON)</label>
                <textarea id="query-mapping-field" name="query_mapping" class="mt-1 px-1.5 block w-full h-40 rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 bg-black text-white" placeholder="{}"></textarea>
            `;
            passthroughContainer.appendChild(queryDiv);
        }
        if (!document.getElementById("header-mapping-field")) {
            const headerDiv = document.createElement("div");
            headerDiv.className = "mb-4";
            headerDiv.innerHTML = `
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Header Mapping (JSON)</label>
                <textarea id="header-mapping-field" name="header_mapping" class="mt-1 px-1.5 block w-full h-40 rounded-md border border-gray-300 dark:border-gray-600 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 bg-black text-white" placeholder="{}"></textarea>
            `;
            passthroughContainer.appendChild(headerDiv);
        }
        if (!document.getElementById("timeout-ms-field")) {
            const timeoutDiv = document.createElement("div");
            timeoutDiv.className = "mb-4";
            timeoutDiv.innerHTML = `
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">timeout_ms (number)</label>
                <input type="number" id="timeout-ms-field" name="timeout_ms" class="mt-1 px-1.5 block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:text-gray-300" placeholder="30000" min="0" />
            `;
            passthroughContainer.appendChild(timeoutDiv);
        }
        if (!document.getElementById("expose-passthrough-field")) {
            const exposeDiv = document.createElement("div");
            exposeDiv.className = "mb-4";
            exposeDiv.innerHTML = `
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Expose Passthrough</label>
                <select id="expose-passthrough-field" name="expose_passthrough" class="mt-1 px-1.5 block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:text-gray-300">
                    <option value="true" selected>True</option>
                    <option value="false">False</option>
                </select>
            `;
            passthroughContainer.appendChild(exposeDiv);
        }
        if (!document.getElementById("allowlist-field")) {
            const allowlistDiv = document.createElement("div");
            allowlistDiv.className = "mb-4";
            allowlistDiv.innerHTML = `
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Allowlist (comma-separated hosts/schemes)</label>
                <input type="text" id="allowlist-field" name="allowlist" class="mt-1 px-1.5 block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:text-gray-300" placeholder="[example.com, https://api.example.com]" />
            `;
            passthroughContainer.appendChild(allowlistDiv);
        }
        if (!document.getElementById("plugin-chain-pre-field")) {
            const pluginPreDiv = document.createElement("div");
            pluginPreDiv.className = "mb-4";
            pluginPreDiv.innerHTML = `
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Plugin Chain Pre</label>
                <input type="text" id="plugin-chain-pre-field" name="plugin_chain_pre" class="mt-1 px-1.5 block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:text-gray-300" placeholder="[]" />
            `;
            passthroughContainer.appendChild(pluginPreDiv);
        }
        if (!document.getElementById("plugin-chain-post-field")) {
            const pluginPostDiv = document.createElement("div");
            pluginPostDiv.className = "mb-4";
            pluginPostDiv.innerHTML = `
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Plugin Chain Post (optional, override defaults)</label>
                <input type="text" id="plugin-chain-post-field" name="plugin_chain_post" class="mt-1 px-1.5 block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:text-gray-300" placeholder="[]" />
            `;
            passthroughContainer.appendChild(pluginPostDiv);
        }
    } else {
        passthroughContainer.style.display = "none";
    }
}

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

    // Initialize CA certificate upload immediately
    initializeCACertUpload();

    // Also try to initialize after a short delay (in case the panel loads later)
    setTimeout(initializeCACertUpload, 500);

    // Re-initialize when switching to gateways tab
    const gatewaysTab = document.querySelector('[onclick*="gateways"]');
    if (gatewaysTab) {
        gatewaysTab.addEventListener("click", function () {
            setTimeout(initializeCACertUpload, 100);
        });
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

        console.log("Metrics data received:", data);
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
    // Only clear the aggregated metrics section, not the entire panel (to preserve System Metrics)
    const aggregatedSection = safeGetElement(
        "aggregated-metrics-section",
        true,
    );
    if (aggregatedSection) {
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
                <p class="text-gray-600">Loading aggregated metrics...</p>
                <p class="text-sm text-gray-500 mt-2">This may take a moment</p>
            </div>
        `;
        aggregatedSection.innerHTML = "";
        aggregatedSection.appendChild(loadingDiv);
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
    // Only show error in the aggregated metrics section, not the entire panel
    const aggregatedSection = safeGetElement("aggregated-metrics-content");
    if (aggregatedSection) {
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
                <h3 class="text-lg font-medium mb-2">Failed to Load Aggregated Metrics</h3>
                <p class="text-sm mb-2">${escapeHtml(errorMessage)}</p>
                <p class="text-xs text-gray-500 mb-4">${helpText}</p>
                <button
                    onclick="retryLoadMetrics()"
                    class="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 transition-colors">
                    Try Again
                </button>
            </div>
        `;

        aggregatedSection.innerHTML = "";
        aggregatedSection.appendChild(errorDiv);
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

function showMetricsPlaceholder() {
    const aggregatedSection = safeGetElement("aggregated-metrics-section");
    if (aggregatedSection) {
        const placeholderDiv = document.createElement("div");
        placeholderDiv.className = "text-gray-600 p-4 text-center";
        placeholderDiv.textContent =
            "Aggregated metrics endpoint not available. This feature may not be implemented yet.";
        aggregatedSection.innerHTML = "";
        aggregatedSection.appendChild(placeholderDiv);
    }
}

// ===================================================================
// ENHANCED METRICS DISPLAY with Complete System Overview
// ===================================================================

function displayMetrics(data, retryCount = 0) {
    console.log("displayMetrics called with:", data, "retry:", retryCount);

    // Ensure parent sections exist, create container if missing
    const metricsPanel = document.getElementById("metrics-panel");
    const aggregatedSection = document.getElementById(
        "aggregated-metrics-section",
    );
    let aggregatedContent = document.getElementById(
        "aggregated-metrics-content",
    );

    console.log("Panel check:", {
        metricsPanel: !!metricsPanel,
        metricsPanelHidden: metricsPanel?.classList.contains("hidden"),
        aggregatedSection: !!aggregatedSection,
        aggregatedContent: !!aggregatedContent,
    });

    if (!aggregatedSection) {
        if (retryCount < 10) {
            console.error(
                `Aggregated metrics section missing, retrying (${retryCount + 1}/10) in 100ms`,
            );
            setTimeout(() => displayMetrics(data, retryCount + 1), 100);
            return;
        }
        console.error(
            "Aggregated metrics section not found after retries; cannot render metrics",
        );
        return;
    }

    if (!aggregatedContent) {
        console.warn(
            "Aggregated metrics content container missing; creating fallback container",
        );
        aggregatedContent = document.createElement("div");
        aggregatedContent.id = "aggregated-metrics-content";
        aggregatedContent.className =
            "overflow-auto mb-6 bg-gray-100 dark:bg-gray-900";

        // Insert before chart if present, otherwise append to section
        const chartElement = aggregatedSection.querySelector("#metricsChart");
        if (chartElement && chartElement.parentElement === aggregatedSection) {
            aggregatedSection.insertBefore(aggregatedContent, chartElement);
        } else {
            aggregatedSection.appendChild(aggregatedContent);
        }
    }

    console.log("aggregated-metrics-content element ready:", aggregatedContent);

    try {
        // FIX: Handle completely empty data
        if (!data || Object.keys(data).length === 0) {
            console.warn("Empty or null data received");
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
            aggregatedContent.innerHTML = "";
            aggregatedContent.appendChild(emptyStateDiv);
            return;
        }

        // Create main container with safe structure
        const mainContainer = document.createElement("div");
        mainContainer.className = "space-y-6";

        // Key Performance Indicators section - render to dedicated container above Top Performers
        const kpiData = extractKPIData(data);
        if (Object.keys(kpiData).length > 0) {
            const kpiContainer = document.getElementById("kpi-metrics-section");
            if (kpiContainer) {
                const kpiSection = createKPISection(kpiData);
                kpiContainer.innerHTML = "";
                kpiContainer.appendChild(kpiSection);
            }
        }

        // Top Performers are now handled entirely by HTMX sections below aggregated-metrics-content
        // (see <details> sections with top-tools-content, top-resources-content, etc. in admin.html)
        // Legacy JavaScript widget is disabled to prevent duplicate rendering
        console.log(
            "✓ Top Performers handled by HTMX - skipping legacy JavaScript widget",
        );

        // Individual metrics grid - render inside Top Performers section
        const individualMetricsGrid = document.getElementById(
            "individual-metrics-grid",
        );
        if (individualMetricsGrid) {
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
                const gatewaysCard = createMetricsCard(
                    "Gateways",
                    data.gateways,
                );
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

            individualMetricsGrid.innerHTML = "";
            individualMetricsGrid.appendChild(metricsContainer);
        }

        // Recent activity section (bottom)
        if (data.recentActivity || data.recent) {
            const activityData = data.recentActivity || data.recent;
            const activitySection = createRecentActivitySection(activityData);
            mainContainer.appendChild(activitySection);
        }

        // Safe content replacement
        aggregatedContent.innerHTML = "";
        aggregatedContent.appendChild(mainContainer);

        console.log("✓ Enhanced metrics display rendered successfully");
    } catch (error) {
        console.error("Error displaying metrics:", error);
        showMetricsError(error);
    }
}

/**
 * Switch between Top Performers tabs
 */
// eslint-disable-next-line no-unused-vars
function switchTopPerformersTab(entityType) {
    // Hide all panels
    const panels = document.querySelectorAll(".top-performers-panel");
    panels.forEach((panel) => panel.classList.add("hidden"));

    // Remove active state from all tabs
    const tabs = document.querySelectorAll(".top-performers-tab");
    tabs.forEach((tab) => {
        tab.classList.remove(
            "border-indigo-500",
            "text-indigo-600",
            "dark:text-indigo-400",
        );
        tab.classList.add(
            "border-transparent",
            "text-gray-500",
            "hover:text-gray-700",
            "hover:border-gray-300",
            "dark:text-gray-400",
            "dark:hover:text-gray-300",
        );
    });

    // Show selected panel
    const selectedPanel = document.getElementById(
        `top-performers-panel-${entityType}`,
    );
    if (selectedPanel) {
        selectedPanel.classList.remove("hidden");
    }

    // Activate selected tab
    const selectedTab = document.getElementById(
        `top-performers-tab-${entityType}`,
    );
    if (selectedTab) {
        selectedTab.classList.remove(
            "border-transparent",
            "text-gray-500",
            "hover:text-gray-700",
            "hover:border-gray-300",
            "dark:text-gray-400",
            "dark:hover:text-gray-300",
        );
        selectedTab.classList.add(
            "border-indigo-500",
            "text-indigo-600",
            "dark:text-indigo-400",
        );
    }
}

/**
 * SECURITY: Create system summary card with safe HTML generation
 */
// eslint-disable-next-line no-unused-vars
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
            },
            {
                key: "avgResponseTime",
                label: "Avg Response Time",
                icon: "⚡",
                color: "yellow",
            },
            { key: "errorRate", label: "Error Rate", icon: "❌", color: "red" },
        ];

        kpis.forEach((kpi) => {
            let value = kpiData[kpi.key];
            if (value === null || value === undefined || value === "N/A") {
                value = "N/A";
            } else {
                if (kpi.key === "avgResponseTime") {
                    // ensure numeric then 3 decimals + unit
                    value = isNaN(Number(value))
                        ? "N/A"
                        : Number(value).toFixed(3) + " ms";
                } else if (
                    kpi.key === "successRate" ||
                    kpi.key === "errorRate"
                ) {
                    value = String(value) + "%";
                } else {
                    value = String(value);
                }
            }

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
            valueSpan.textContent = value;

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
    } catch (err) {
        console.error("Error creating KPI section:", err);
        return document.createElement("div");
    }
}

/**
 * SECURITY: Extract and calculate KPI data with validation
 */
function formatValue(value, key) {
    if (value === null || value === undefined || value === "N/A") {
        return "N/A";
    }

    if (key === "avgResponseTime") {
        return isNaN(Number(value)) ? "N/A" : Number(value).toFixed(3) + " ms";
    }

    if (key === "successRate" || key === "errorRate") {
        return `${value}%`;
    }

    if (typeof value === "number" && Number.isNaN(value)) {
        return "N/A";
    }

    return String(value).trim() === "" ? "N/A" : String(value);
}

function extractKPIData(data) {
    try {
        let totalExecutions = 0;
        let totalSuccessful = 0;
        let totalFailed = 0;
        let weightedResponseSum = 0;

        const categoryKeys = [
            ["tools", "Tools Metrics", "Tools", "tools_metrics"],
            [
                "resources",
                "Resources Metrics",
                "Resources",
                "resources_metrics",
            ],
            ["prompts", "Prompts Metrics", "Prompts", "prompts_metrics"],
            ["servers", "Servers Metrics", "Servers", "servers_metrics"],
            ["gateways", "Gateways Metrics", "Gateways", "gateways_metrics"],
            [
                "virtualServers",
                "Virtual Servers",
                "VirtualServers",
                "virtual_servers",
            ],
        ];

        categoryKeys.forEach((aliases) => {
            let categoryData = null;
            for (const key of aliases) {
                if (data && data[key]) {
                    categoryData = data[key];
                    break;
                }
            }
            if (!categoryData) {
                return;
            }

            // Build a lowercase-key map so "Successful Executions" and "successfulExecutions" both match
            const normalized = {};
            Object.entries(categoryData).forEach(([k, v]) => {
                normalized[k.toString().trim().toLowerCase()] = v;
            });

            const executions = Number(
                normalized["total executions"] ??
                    normalized.totalexecutions ??
                    normalized.execution_count ??
                    normalized["execution-count"] ??
                    normalized.executions ??
                    normalized.total_executions ??
                    0,
            );

            const successful = Number(
                normalized["successful executions"] ??
                    normalized.successfulexecutions ??
                    normalized.successful ??
                    normalized.successful_executions ??
                    0,
            );

            const failed = Number(
                normalized["failed executions"] ??
                    normalized.failedexecutions ??
                    normalized.failed ??
                    normalized.failed_executions ??
                    0,
            );

            const avgResponseRaw =
                normalized["average response time"] ??
                normalized.avgresponsetime ??
                normalized.avg_response_time ??
                normalized.avgresponsetime ??
                null;

            totalExecutions += Number.isNaN(executions) ? 0 : executions;
            totalSuccessful += Number.isNaN(successful) ? 0 : successful;
            totalFailed += Number.isNaN(failed) ? 0 : failed;

            if (
                avgResponseRaw !== null &&
                avgResponseRaw !== undefined &&
                avgResponseRaw !== "N/A" &&
                !Number.isNaN(Number(avgResponseRaw)) &&
                executions > 0
            ) {
                weightedResponseSum += executions * Number(avgResponseRaw);
            }
        });

        const avgResponseTime =
            totalExecutions > 0 && weightedResponseSum > 0
                ? weightedResponseSum / totalExecutions
                : null;

        const successRate =
            totalExecutions > 0
                ? Math.round((totalSuccessful / totalExecutions) * 100)
                : 0;

        const errorRate =
            totalExecutions > 0
                ? Math.round((totalFailed / totalExecutions) * 100)
                : 0;

        // Debug: show what we've read from the payload
        console.log("KPI Totals:", {
            totalExecutions,
            totalSuccessful,
            totalFailed,
            successRate,
            errorRate,
            avgResponseTime,
        });

        return { totalExecutions, successRate, errorRate, avgResponseTime };
    } catch (err) {
        console.error("Error extracting KPI data:", err);
        return {
            totalExecutions: 0,
            successRate: 0,
            errorRate: 0,
            avgResponseTime: null,
        };
    }
}

// eslint-disable-next-line no-unused-vars
function updateKPICards(kpiData) {
    try {
        if (!kpiData) {
            return;
        }

        const idMap = {
            "metrics-total-executions": formatValue(
                kpiData.totalExecutions,
                "totalExecutions",
            ),
            "metrics-success-rate": formatValue(
                kpiData.successRate,
                "successRate",
            ),
            "metrics-avg-response-time": formatValue(
                kpiData.avgResponseTime,
                "avgResponseTime",
            ),
            "metrics-error-rate": formatValue(kpiData.errorRate, "errorRate"),
        };

        Object.entries(idMap).forEach(([id, value]) => {
            const el = document.getElementById(id);
            if (!el) {
                return;
            }

            // If card has a `.value` span inside, update it, else update directly
            const valueEl =
                el.querySelector?.(".value") ||
                el.querySelector?.(".kpi-value");
            if (valueEl) {
                valueEl.textContent = value;
            } else {
                el.textContent = value;
            }
        });
    } catch (err) {
        console.error("updateKPICards error:", err);
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
// Removed unused function createEnhancedTopPerformersSection - handled by HTMX
/* function createEnhancedTopPerformersSection(topData) {
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
} */
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

    let date;
    if (typeof timestamp === "number" || /^\d+$/.test(timestamp)) {
        const num = Number(timestamp);
        date = new Date(num < 1e12 ? num * 1000 : num); // epoch seconds or ms
    } else {
        date = new Date(timestamp.endsWith("Z") ? timestamp : timestamp + "Z");
    }

    if (isNaN(date.getTime())) {
        return "Never";
    }

    const now = Date.now();
    const diff = now - date.getTime();

    if (diff < 60 * 1000) {
        return "Just now";
    }
    if (diff < 60 * 60 * 1000) {
        return `${Math.floor(diff / 60000)} min ago`;
    }

    return date.toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: true,
        timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });
}

/* Unused - part of commented createEnhancedTopPerformersSection
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

    // Pagination controls (using standard Alpine.js pattern)
    if (data.length > 5) {
        const pagination = createStandardPaginationControls(
            `top-${entityType}`,
            data.length,
            5,
            (page, perPage) => {
                updateTableRows(tbody, entityType, data, page, perPage);
            },
            },
        );
        panel.appendChild(pagination);
    }

    return panel;
}
*/

/* Unused - part of commented createEnhancedTopPerformersSection
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
*/

// eslint-disable-next-line no-unused-vars
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

/**
 * Creates standard Alpine.js-based pagination controls matching the pattern
 * used in Tools/Resources/Prompts sections for visual consistency
 */
// eslint-disable-next-line no-unused-vars
function createStandardPaginationControls(
    idPrefix,
    totalItems,
    initialPerPage,
    onPageChange,
) {
    const wrapper = document.createElement("div");

    // Store callback in a global namespace for Alpine.js to access
    const callbackId = `pagination_${idPrefix}_${Date.now()}`;
    window[callbackId] = onPageChange;

    wrapper.setAttribute(
        "x-data",
        `{
        currentPage: 1,
        perPage: ${initialPerPage},
        totalItems: ${totalItems},
        callbackId: '${callbackId}',
        get totalPages() { return Math.ceil(this.totalItems / this.perPage); },
        get hasNext() { return this.currentPage < this.totalPages; },
        get hasPrev() { return this.currentPage > 1; },
        get startItem() { return Math.min((this.currentPage - 1) * this.perPage + 1, this.totalItems); },
        get endItem() { return Math.min(this.currentPage * this.perPage, this.totalItems); },
        
        goToPage(page) {
            if (page >= 1 && page <= this.totalPages && page !== this.currentPage) {
                this.currentPage = page;
                window[this.callbackId](this.currentPage, this.perPage);
            }
        },
        prevPage() {
            if (this.hasPrev) { this.goToPage(this.currentPage - 1); }
        },
        nextPage() {
            if (this.hasNext) { this.goToPage(this.currentPage + 1); }
        },
        changePageSize(size) {
            this.perPage = parseInt(size);
            this.currentPage = 1;
            window[this.callbackId](this.currentPage, this.perPage);
        }
    }`,
    );
    wrapper.className =
        "flex flex-col sm:flex-row items-center justify-between gap-4 py-4 border-t border-gray-200 dark:border-gray-700";

    wrapper.innerHTML = `
        <!-- Page Size Selector -->
        <div class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
            <span>Show:</span>
            <select
                x-model="perPage"
                @change="changePageSize($event.target.value)"
                class="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-indigo-500 dark:focus:ring-indigo-400"
            >
                <option value="5">5</option>
                <option value="10">10</option>
                <option value="25">25</option>
                <option value="50">50</option>
                <option value="100">100</option>
            </select>
            <span>per page</span>
        </div>

        <!-- Page Info -->
        <div class="text-sm text-gray-700 dark:text-gray-300">
            <span x-text="\`Showing \${startItem} - \${endItem} of \${totalItems.toLocaleString()} items\`"></span>
        </div>

        <!-- Page Navigation -->
        <div class="flex items-center gap-2">
            <!-- First Page Button -->
            <button
                @click="goToPage(1)"
                :disabled="!hasPrev"
                :class="hasPrev ? 'text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20' : 'text-gray-400 dark:text-gray-600 cursor-not-allowed'"
                class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 transition-colors"
                title="First Page"
            >
                ⏮️
            </button>

            <!-- Previous Page Button -->
            <button
                @click="prevPage()"
                :disabled="!hasPrev"
                :class="hasPrev ? 'text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20' : 'text-gray-400 dark:text-gray-600 cursor-not-allowed'"
                class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 transition-colors"
                title="Previous Page"
            >
                ◀️ Prev
            </button>

            <!-- Page Number Display -->
            <div class="flex items-center gap-1">
                <!-- Show first page if not near start -->
                <template x-if="currentPage > 3">
                    <button
                        @click="goToPage(1)"
                        class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 text-gray-700 dark:text-gray-300"
                    >
                        1
                    </button>
                </template>

                <!-- Ellipsis if needed -->
                <template x-if="currentPage > 4">
                    <span class="px-2 text-gray-500 dark:text-gray-500">...</span>
                </template>

                <!-- Show 2 pages before current -->
                <template x-for="i in [currentPage - 2, currentPage - 1]" :key="i">
                    <button
                        x-show="i >= 1"
                        @click="goToPage(i)"
                        class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 text-gray-700 dark:text-gray-300"
                        x-text="i"
                    ></button>
                </template>

                <!-- Current Page (highlighted) -->
                <button
                    class="px-3 py-1 rounded-md border-2 border-indigo-600 dark:border-indigo-400 bg-indigo-50 dark:bg-indigo-900/20 font-semibold text-indigo-700 dark:text-indigo-300"
                    disabled
                    x-text="currentPage"
                ></button>

                <!-- Show 2 pages after current -->
                <template x-for="i in [currentPage + 1, currentPage + 2]" :key="i">
                    <button
                        x-show="i <= totalPages"
                        @click="goToPage(i)"
                        class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 text-gray-700 dark:text-gray-300"
                        x-text="i"
                    ></button>
                </template>

                <!-- Ellipsis if needed -->
                <template x-if="currentPage < totalPages - 3">
                    <span class="px-2 text-gray-500 dark:text-gray-500">...</span>
                </template>

                <!-- Show last page if not near end -->
                <template x-if="currentPage < totalPages - 2">
                    <button
                        @click="goToPage(totalPages)"
                        class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 text-gray-700 dark:text-gray-300"
                        x-text="totalPages"
                    ></button>
                </template>
            </div>

            <!-- Next Page Button -->
            <button
                @click="nextPage()"
                :disabled="!hasNext"
                :class="hasNext ? 'text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20' : 'text-gray-400 dark:text-gray-600 cursor-not-allowed'"
                class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 transition-colors"
                title="Next Page"
            >
                Next ▶️
            </button>

            <!-- Last Page Button -->
            <button
                @click="goToPage(totalPages)"
                :disabled="!hasNext"
                :class="hasNext ? 'text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20' : 'text-gray-400 dark:text-gray-600 cursor-not-allowed'"
                class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 transition-colors"
                title="Last Page"
            >
                ⏭️
            </button>
        </div>
    `;
    return wrapper;
}

// eslint-disable-next-line no-unused-vars
function updateTableRows(tbody, entityType, data, page, perPage) {
    tbody.innerHTML = "";
    const start = (page - 1) * perPage;
    const paginatedData = data.slice(start, start + perPage);

    paginatedData.forEach((item, localIndex) => {
        const globalIndex = start + localIndex; // Calculate global rank
        const row = document.createElement("tr");
        row.className =
            "hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors duration-200";

        // Rank
        const rankCell = document.createElement("td");
        rankCell.className =
            "px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-100 sm:px-6 sm:py-4";
        const rankBadge = document.createElement("span");
        rankBadge.className = `inline-flex items-center justify-center w-6 h-6 rounded-full ${
            globalIndex === 0
                ? "bg-yellow-400 text-yellow-900"
                : globalIndex === 1
                  ? "bg-gray-300 text-gray-900"
                  : globalIndex === 2
                    ? "bg-orange-400 text-orange-900"
                    : "bg-gray-100 text-gray-600"
        }`;
        rankBadge.textContent = globalIndex + 1;
        rankBadge.setAttribute("aria-label", `Rank ${globalIndex + 1}`);
        rankCell.appendChild(rankBadge);
        row.appendChild(rankCell);

        // Name (clickable for drill-down)
        const nameCell = document.createElement("td");
        nameCell.className =
            "px-6 py-4 whitespace-nowrap text-sm text-indigo-600 dark:text-indigo-400 cursor-pointer";
        nameCell.textContent = escapeHtml(item.name || "Unknown");
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
}

/* Unused - part of commented createEnhancedTopPerformersSection
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
*/

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
        const outputSchemaValidation = validateJson(
            tool.outputSchema ? JSON.stringify(tool.outputSchema) : "",
            "Output Schema",
        );
        const annotationsValidation = validateJson(
            JSON.stringify(tool.annotations || {}),
            "Annotations",
        );

        const headersField = safeGetElement("edit-tool-headers");
        const schemaField = safeGetElement("edit-tool-schema");
        const outputSchemaField = safeGetElement("edit-tool-output-schema");
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
        if (outputSchemaField) {
            if (tool.outputSchema) {
                outputSchemaField.value = outputSchemaValidation.valid
                    ? JSON.stringify(outputSchemaValidation.value, null, 2)
                    : "";
            } else {
                outputSchemaField.value = "";
            }
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
        if (window.editToolOutputSchemaEditor) {
            if (tool.outputSchema && outputSchemaValidation.valid) {
                window.editToolOutputSchemaEditor.setValue(
                    JSON.stringify(outputSchemaValidation.value, null, 2),
                );
            } else {
                window.editToolOutputSchemaEditor.setValue("");
            }
            window.editToolOutputSchemaEditor.refresh();
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
                if (window.editToolOutputSchemaEditor) {
                    window.editToolOutputSchemaEditor.setOption(
                        "readOnly",
                        true,
                    );
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
                if (window.editToolOutputSchemaEditor) {
                    window.editToolOutputSchemaEditor.setOption(
                        "readOnly",
                        false,
                    );
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
        const authHeadersContainer = document.getElementById(
            "auth-headers-container-gw-edit",
        );
        const authHeadersJsonInput = document.getElementById(
            "auth-headers-json-gw-edit",
        );
        if (authHeadersContainer) {
            authHeadersContainer.innerHTML = "";
        }
        if (authHeadersJsonInput) {
            authHeadersJsonInput.value = "";
        }

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
            if (window.editToolOutputSchemaEditor) {
                window.editToolOutputSchemaEditor.refresh();
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
 * SECURE: View A2A Agents function with safe display
 */

async function viewAgent(agentId) {
    try {
        console.log(`Viewing agent ID: ${agentId}`);

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/a2a/${agentId}`,
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const agent = await response.json();

        const agentDetailsDiv = safeGetElement("agent-details");
        if (agentDetailsDiv) {
            const container = document.createElement("div");
            container.className =
                "space-y-2 dark:bg-gray-900 dark:text-gray-100";

            const fields = [
                { label: "Name", value: agent.name },
                { label: "Slug", value: agent.slug },
                { label: "Endpoint URL", value: agent.endpointUrl },
                { label: "Agent Type", value: agent.agentType },
                { label: "Protocol Version", value: agent.protocolVersion },
                { label: "Description", value: agent.description || "N/A" },
                { label: "Visibility", value: agent.visibility || "private" },
            ];

            // Tags
            const tagsP = document.createElement("p");
            const tagsStrong = document.createElement("strong");
            tagsStrong.textContent = "Tags: ";
            tagsP.appendChild(tagsStrong);
            if (agent.tags && agent.tags.length > 0) {
                agent.tags.forEach((tag) => {
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

            // Render basic fields
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

            if (!agent.enabled) {
                statusText = "Inactive";
                statusClass = "bg-red-100 text-red-800";
                statusIcon = `
                    <svg class="ml-1 h-4 w-4 text-red-600 self-center" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M6.293 6.293a1 1 0 011.414 0L10 8.586l2.293-2.293a1 1 0 111.414 1.414L11.414 10l2.293 2.293a1 1 0 11-1.414 1.414L10 11.414l-2.293 2.293a1 1 0 11-1.414-1.414L8.586 10 6.293 7.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
                      </svg>`;
            } else if (agent.enabled && agent.reachable) {
                statusText = "Active";
                statusClass = "bg-green-100 text-green-800";
                statusIcon = `
                    <svg class="ml-1 h-4 w-4 text-green-600 self-center" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-4.586l5.293-5.293-1.414-1.414L9 11.586 7.121 9.707 5.707 11.121 9 14.414z" clip-rule="evenodd"></path>
                      </svg>`;
            } else if (agent.enabled && !agent.reachable) {
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

            // Capabilities + Config (JSON formatted)
            const capConfigDiv = document.createElement("div");
            capConfigDiv.className =
                "mt-4 p-2 bg-gray-50 dark:bg-gray-800 rounded";
            const capTitle = document.createElement("strong");
            capTitle.textContent = "Capabilities & Config:";
            capConfigDiv.appendChild(capTitle);

            const pre = document.createElement("pre");
            pre.className = "text-xs mt-1 whitespace-pre-wrap break-words";
            pre.textContent = JSON.stringify(
                { capabilities: agent.capabilities, config: agent.config },
                null,
                2,
            );
            capConfigDiv.appendChild(pre);
            container.appendChild(capConfigDiv);

            // Metadata
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
                        agent.created_by || agent.createdBy || "Legacy Entity",
                },
                {
                    label: "Created At",
                    value:
                        agent.created_at || agent.createdAt
                            ? new Date(
                                  agent.created_at || agent.createdAt,
                              ).toLocaleString()
                            : "Pre-metadata",
                },
                {
                    label: "Created From IP",
                    value:
                        agent.created_from_ip ||
                        agent.createdFromIp ||
                        "Unknown",
                },
                {
                    label: "Created Via",
                    value: agent.created_via || agent.createdVia || "Unknown",
                },
                {
                    label: "Last Modified By",
                    value: agent.modified_by || agent.modifiedBy || "N/A",
                },
                {
                    label: "Last Modified At",
                    value:
                        agent.updated_at || agent.updatedAt
                            ? new Date(
                                  agent.updated_at || agent.updatedAt,
                              ).toLocaleString()
                            : "N/A",
                },
                {
                    label: "Modified From IP",
                    value:
                        agent.modified_from_ip || agent.modifiedFromIp || "N/A",
                },
                {
                    label: "Modified Via",
                    value: agent.modified_via || agent.modifiedVia || "N/A",
                },
                { label: "Version", value: agent.version || "1" },
                {
                    label: "Import Batch",
                    value: agent.importBatchId || "N/A",
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

            agentDetailsDiv.innerHTML = "";
            agentDetailsDiv.appendChild(container);
        }

        openModal("agent-modal");
        const modal = document.getElementById("agent-modal");
        if (modal && modal.classList.contains("hidden")) {
            console.warn("Modal was still hidden — forcing visible.");
            modal.classList.remove("hidden");
        }

        console.log("✓ Agent details loaded successfully");
    } catch (error) {
        console.error("Error fetching agent details:", error);
        const errorMessage = handleFetchError(error, "load agent details");
        showErrorMessage(errorMessage);
    }
}

/**
 * SECURE: Edit A2A Agent function
 */

async function editA2AAgent(agentId) {
    try {
        console.log(`Editing A2A Agent ID: ${agentId}`);

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/a2a/${agentId}`,
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const agent = await response.json();

        console.log("Agent Details: " + JSON.stringify(agent, null, 2));

        // for (const [key, value] of Object.entries(agent)) {
        //       console.log(`${key}:`, value);
        //     }

        const isInactiveCheckedBool = isInactiveChecked("a2a-agents");
        const editForm = safeGetElement("edit-a2a-agent-form");
        let hiddenField = safeGetElement("edit-a2a-agents-show-inactive");
        if (!hiddenField) {
            hiddenField = document.createElement("input");
            hiddenField.type = "hidden";
            hiddenField.name = "is_inactivate_checked";
            hiddenField.id = "edit-a2a-agents-show-inactive";

            if (editForm) {
                editForm.appendChild(hiddenField);
            }
        }
        hiddenField.value = isInactiveCheckedBool;

        // Set form action and populate fields with validation

        if (editForm) {
            editForm.action = `${window.ROOT_PATH}/admin/a2a/${agentId}/edit`;
            editForm.method = "POST"; // ensure method is POST
        }

        const nameValidation = validateInputName(agent.name, "a2a_agent");
        const urlValidation = validateUrl(agent.endpointUrl);

        const nameField = safeGetElement("a2a-agent-name-edit");
        const urlField = safeGetElement("a2a-agent-endpoint-url-edit");
        const descField = safeGetElement("a2a-agent-description-edit");
        const agentType = safeGetElement("a2a-agent-type-edit");

        agentType.value = agent.agentType;

        console.log("Agent Type: ", agent.agentType);

        if (nameField && nameValidation.valid) {
            nameField.value = nameValidation.value;
        }
        if (urlField && urlValidation.valid) {
            urlField.value = urlValidation.value;
        }
        if (descField) {
            descField.value = agent.description || "";
        }

        // Set tags field
        const tagsField = safeGetElement("a2a-agent-tags-edit");
        if (tagsField) {
            tagsField.value = agent.tags ? agent.tags.join(", ") : "";
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

        // ✅ Prefill visibility radios (consistent with server)
        const visibility = agent.visibility
            ? agent.visibility.toLowerCase()
            : null;

        const publicRadio = safeGetElement("a2a-visibility-public-edit");
        const teamRadio = safeGetElement("a2a-visibility-team-edit");
        const privateRadio = safeGetElement("a2a-visibility-private-edit");

        // Clear all first
        if (publicRadio) {
            publicRadio.checked = false;
        }
        if (teamRadio) {
            teamRadio.checked = false;
        }
        if (privateRadio) {
            privateRadio.checked = false;
        }

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

        const authTypeField = safeGetElement("auth-type-a2a-edit");

        if (authTypeField) {
            authTypeField.value = agent.authType || "";
        }

        toggleA2AAuthFields(agent.authType || "");

        // Auth containers
        const authBasicSection = safeGetElement("auth-basic-fields-a2a-edit");
        const authBearerSection = safeGetElement("auth-bearer-fields-a2a-edit");
        const authHeadersSection = safeGetElement(
            "auth-headers-fields-a2a-edit",
        );
        const authOAuthSection = safeGetElement("auth-oauth-fields-a2a-edit");

        // Individual fields
        const authUsernameField = safeGetElement(
            "auth-basic-fields-a2a-edit",
        )?.querySelector("input[name='auth_username']");
        const authPasswordField = safeGetElement(
            "auth-basic-fields-a2a-edit",
        )?.querySelector("input[name='auth_password']");

        const authTokenField = safeGetElement(
            "auth-bearer-fields-a2a-edit",
        )?.querySelector("input[name='auth_token']");

        const authHeaderKeyField = safeGetElement(
            "auth-headers-fields-a2a-edit",
        )?.querySelector("input[name='auth_header_key']");
        const authHeaderValueField = safeGetElement(
            "auth-headers-fields-a2a-edit",
        )?.querySelector("input[name='auth_header_value']");

        // OAuth fields
        const oauthGrantTypeField = safeGetElement("oauth-grant-type-a2a-edit");
        const oauthClientIdField = safeGetElement("oauth-client-id-a2a-edit");
        const oauthClientSecretField = safeGetElement(
            "oauth-client-secret-a2a-edit",
        );
        const oauthTokenUrlField = safeGetElement("oauth-token-url-a2a-edit");
        const oauthAuthUrlField = safeGetElement(
            "oauth-authorization-url-a2a-edit",
        );
        const oauthRedirectUriField = safeGetElement(
            "oauth-redirect-uri-a2a-edit",
        );
        const oauthScopesField = safeGetElement("oauth-scopes-a2a-edit");
        const oauthAuthCodeFields = safeGetElement(
            "oauth-auth-code-fields-a2a-edit",
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

        switch (agent.authType) {
            case "basic":
                if (authBasicSection) {
                    authBasicSection.style.display = "block";
                    if (authUsernameField) {
                        authUsernameField.value = agent.authUsername || "";
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
                        authTokenField.value = agent.authValue || ""; // show full token
                    }
                }
                break;
            case "authheaders":
                if (authHeadersSection) {
                    authHeadersSection.style.display = "block";
                    if (authHeaderKeyField) {
                        authHeaderKeyField.value = agent.authHeaderKey || "";
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
                if (agent.oauthConfig) {
                    const config = agent.oauthConfig;
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

        // **Capabilities & Config (ensure valid dicts)**
        safeSetValue(
            "a2a-agent-capabilities-edit",
            JSON.stringify(agent.capabilities || {}),
        );
        safeSetValue(
            "a2a-agent-config-edit",
            JSON.stringify(agent.config || {}),
        );

        // Set form action to the new POST endpoint

        // Handle passthrough headers
        const passthroughHeadersField = safeGetElement(
            "edit-a2a-agent-passthrough-headers",
        );
        if (passthroughHeadersField) {
            if (
                agent.passthroughHeaders &&
                Array.isArray(agent.passthroughHeaders)
            ) {
                passthroughHeadersField.value =
                    agent.passthroughHeaders.join(", ");
            } else {
                passthroughHeadersField.value = "";
            }
        }

        openModal("a2a-edit-modal");
        console.log("✓ A2A Agent edit modal loaded successfully");
    } catch (err) {
        console.error("Error loading A2A agent:", err);
        const errorMessage = handleFetchError(
            err,
            "load A2A Agent for editing",
        );
        showErrorMessage(errorMessage);
    }
}

function safeSetValue(id, val) {
    const el = document.getElementById(id);
    if (el) {
        el.value = val;
    }
}

function toggleA2AAuthFields(authType) {
    const sections = [
        "auth-basic-fields-a2a-edit",
        "auth-bearer-fields-a2a-edit",
        "auth-headers-fields-a2a-edit",
        "auth-oauth-fields-a2a-edit",
    ];
    sections.forEach((id) => {
        const el = document.getElementById(id);
        if (el) {
            el.style.display = "none";
        }
    });
    if (authType) {
        const el = document.getElementById(`auth-${authType}-fields-a2a-edit`);
        if (el) {
            el.style.display = "block";
        }
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
                {
                    label: "Visibility",
                    value: resource.visibility || "private",
                },
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
                    label: "Created From IP",
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
                    label: "Modified From IP",
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
        // Ensure hidden inactive flag is preserved
        const isInactiveCheckedBool = isInactiveChecked("resources");
        let hiddenField = safeGetElement("edit-resource-show-inactive");
        const editForm = safeGetElement("edit-resource-form");

        if (!hiddenField && editForm) {
            hiddenField = document.createElement("input");
            hiddenField.type = "hidden";
            hiddenField.name = "is_inactive_checked";
            hiddenField.id = "edit-resource-show-inactive";
            const editForm = safeGetElement("edit-resource-form");
            editForm.appendChild(hiddenField);
        }
        hiddenField.value = isInactiveCheckedBool;

        // ✅ Prefill visibility radios (consistent with server)
        const visibility = resource.visibility
            ? resource.visibility.toLowerCase()
            : null;

        const publicRadio = safeGetElement("edit-resource-visibility-public");
        const teamRadio = safeGetElement("edit-resource-visibility-team");
        const privateRadio = safeGetElement("edit-resource-visibility-private");

        // Clear all first
        if (publicRadio) {
            publicRadio.checked = false;
        }
        if (teamRadio) {
            teamRadio.checked = false;
        }
        if (privateRadio) {
            privateRadio.checked = false;
        }

        if (visibility) {
            if (visibility === "public" && publicRadio) {
                publicRadio.checked = true;
            } else if (visibility === "team" && teamRadio) {
                teamRadio.checked = true;
            } else if (visibility === "private" && privateRadio) {
                privateRadio.checked = true;
            }
        }

        // Set form action and populate fields with validation
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
                { label: "Visibility", value: prompt.visibility || "private" },
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
                    label: "Created From IP",
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
                    label: "Modified From IP",
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
async function editPrompt(promptId) {
    try {
        console.log(`Editing prompt: ${promptId}`);

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/prompts/${encodeURIComponent(promptId)}`,
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

        // ✅ Prefill visibility radios (consistent with server)
        const visibility = prompt.visibility
            ? prompt.visibility.toLowerCase()
            : null;

        const publicRadio = safeGetElement("edit-prompt-visibility-public");
        const teamRadio = safeGetElement("edit-prompt-visibility-team");
        const privateRadio = safeGetElement("edit-prompt-visibility-private");

        // Clear all first
        if (publicRadio) {
            publicRadio.checked = false;
        }
        if (teamRadio) {
            teamRadio.checked = false;
        }
        if (privateRadio) {
            privateRadio.checked = false;
        }

        if (visibility) {
            if (visibility === "public" && publicRadio) {
                publicRadio.checked = true;
            } else if (visibility === "team" && teamRadio) {
                teamRadio.checked = true;
            } else if (visibility === "private" && privateRadio) {
                privateRadio.checked = true;
            }
        }

        // Set form action and populate fields with validation
        const editForm = safeGetElement("edit-prompt-form");
        if (editForm) {
            editForm.action = `${window.ROOT_PATH}/admin/prompts/${encodeURIComponent(promptId)}/edit`;
            // Add or update hidden team_id input if present in URL
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );
            if (teamId) {
                let teamInput = safeGetElement("edit-prompt-team-id");
                if (!teamInput) {
                    teamInput = document.createElement("input");
                    teamInput.type = "hidden";
                    teamInput.name = "team_id";
                    teamInput.id = "edit-prompt-team-id";
                    editForm.appendChild(teamInput);
                }
                teamInput.value = teamId;
            }
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
                { label: "Visibility", value: gateway.visibility || "private" },
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
                    label: "Created From IP",
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
                    label: "Modified From IP",
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

        console.log("Gateway Details: " + JSON.stringify(gateway, null, 2));

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
                        if (gateway.authPasswordUnmasked) {
                            authPasswordField.dataset.isMasked = "true";
                            authPasswordField.dataset.realValue =
                                gateway.authPasswordUnmasked;
                        } else {
                            delete authPasswordField.dataset.isMasked;
                            delete authPasswordField.dataset.realValue;
                        }
                        authPasswordField.value = MASKED_AUTH_VALUE;
                    }
                }
                break;
            case "bearer":
                if (authBearerSection) {
                    authBearerSection.style.display = "block";
                    if (authTokenField) {
                        if (gateway.authTokenUnmasked) {
                            authTokenField.dataset.isMasked = "true";
                            authTokenField.dataset.realValue =
                                gateway.authTokenUnmasked;
                            authTokenField.value = MASKED_AUTH_VALUE;
                        } else {
                            delete authTokenField.dataset.isMasked;
                            delete authTokenField.dataset.realValue;
                            authTokenField.value = gateway.authToken || "";
                        }
                    }
                }
                break;
            case "authheaders":
                if (authHeadersSection) {
                    authHeadersSection.style.display = "block";
                    const unmaskedHeaders =
                        Array.isArray(gateway.authHeadersUnmasked) &&
                        gateway.authHeadersUnmasked.length > 0
                            ? gateway.authHeadersUnmasked
                            : gateway.authHeaders;
                    if (
                        Array.isArray(unmaskedHeaders) &&
                        unmaskedHeaders.length > 0
                    ) {
                        loadAuthHeaders(
                            "auth-headers-container-gw-edit",
                            unmaskedHeaders,
                            { maskValues: true },
                        );
                    } else {
                        updateAuthHeadersJSON("auth-headers-container-gw-edit");
                    }
                    if (authHeaderKeyField) {
                        authHeaderKeyField.value = gateway.authHeaderKey || "";
                    }
                    if (authHeaderValueField) {
                        if (
                            Array.isArray(unmaskedHeaders) &&
                            unmaskedHeaders.length === 1
                        ) {
                            authHeaderValueField.dataset.isMasked = "true";
                            authHeaderValueField.dataset.realValue =
                                unmaskedHeaders[0].value ?? "";
                        }
                        authHeaderValueField.value = MASKED_AUTH_VALUE;
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
                { label: "Visibility", value: server.visibility || "private" },
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

                const maxToShow = 3;
                const toolsToShow = server.associatedTools.slice(0, maxToShow);

                toolsToShow.forEach((toolId) => {
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

                // If more than maxToShow, add a summary badge
                if (server.associatedTools.length > maxToShow) {
                    const moreItem = document.createElement("div");
                    moreItem.className = "flex items-center space-x-2";

                    const moreBadge = document.createElement("span");
                    moreBadge.className =
                        "inline-block bg-green-100 text-green-800 text-xs px-2 py-1 rounded-full cursor-pointer dark:bg-green-900 dark:text-green-200";
                    moreBadge.title = "Total tools associated";
                    const remaining = server.associatedTools.length - maxToShow;
                    moreBadge.textContent = `+${remaining} more`;

                    moreItem.appendChild(moreBadge);
                    toolsList.appendChild(moreItem);
                }

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

                const maxToShow = 3;
                const resourcesToShow = server.associatedResources.slice(
                    0,
                    maxToShow,
                );

                resourcesToShow.forEach((resourceId) => {
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

                // If more than maxToShow, add a summary badge
                if (server.associatedResources.length > maxToShow) {
                    const moreItem = document.createElement("div");
                    moreItem.className = "flex items-center space-x-2";

                    const moreBadge = document.createElement("span");
                    moreBadge.className =
                        "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full cursor-pointer dark:bg-blue-900 dark:text-blue-200";
                    moreBadge.title = "Total resources associated";
                    const remaining =
                        server.associatedResources.length - maxToShow;
                    moreBadge.textContent = `+${remaining} more`;

                    moreItem.appendChild(moreBadge);
                    resourcesList.appendChild(moreItem);
                }

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

                const maxToShow = 3;
                const promptsToShow = server.associatedPrompts.slice(
                    0,
                    maxToShow,
                );

                promptsToShow.forEach((promptId) => {
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

                // If more than maxToShow, add a summary badge
                if (server.associatedPrompts.length > maxToShow) {
                    const moreItem = document.createElement("div");
                    moreItem.className = "flex items-center space-x-2";

                    const moreBadge = document.createElement("span");
                    moreBadge.className =
                        "inline-block bg-purple-100 text-purple-800 text-xs px-2 py-1 rounded-full cursor-pointer dark:bg-purple-900 dark:text-purple-200";
                    moreBadge.title = "Total prompts associated";
                    const remaining =
                        server.associatedPrompts.length - maxToShow;
                    moreBadge.textContent = `+${remaining} more`;

                    moreItem.appendChild(moreBadge);
                    promptsList.appendChild(moreItem);
                }

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

        // Set associated tools data attribute on the container for reference by initToolSelect
        const editToolsContainer = document.getElementById("edit-server-tools");
        if (editToolsContainer && server.associatedTools) {
            editToolsContainer.setAttribute(
                "data-server-tools",
                JSON.stringify(server.associatedTools),
            );
        }

        // Set associated resources data attribute on the container
        const editResourcesContainer = document.getElementById(
            "edit-server-resources",
        );
        if (editResourcesContainer && server.associatedResources) {
            editResourcesContainer.setAttribute(
                "data-server-resources",
                JSON.stringify(server.associatedResources),
            );
        }

        // Set associated prompts data attribute on the container
        const editPromptsContainer = document.getElementById(
            "edit-server-prompts",
        );
        if (editPromptsContainer && server.associatedPrompts) {
            editPromptsContainer.setAttribute(
                "data-server-prompts",
                JSON.stringify(server.associatedPrompts),
            );
        }

        openModal("server-edit-modal");

        // Initialize the select handlers for resources and prompts in the edit modal
        initResourceSelect(
            "edit-server-resources",
            "selectedEditResourcesPills",
            "selectedEditResourcesWarning",
            6,
            "selectAllEditResourcesBtn",
            "clearAllEditResourcesBtn",
        );

        initPromptSelect(
            "edit-server-prompts",
            "selectedEditPromptsPills",
            "selectedEditPromptsWarning",
            6,
            "selectAllEditPromptsBtn",
            "clearAllEditPromptsBtn",
        );

        // Use multiple approaches to ensure checkboxes get set
        setEditServerAssociations(server);
        setTimeout(() => setEditServerAssociations(server), 100);
        setTimeout(() => setEditServerAssociations(server), 300);

        // Set associated items after modal is opened
        setTimeout(() => {
            // Set associated tools checkboxes
            const toolCheckboxes = document.querySelectorAll(
                'input[name="associatedTools"]',
            );

            toolCheckboxes.forEach((checkbox) => {
                let isChecked = false;
                if (server.associatedTools && window.toolMapping) {
                    // Get the tool name for this checkbox UUID
                    const toolName = window.toolMapping[checkbox.value];

                    // Check if this tool name is in the associated tools array
                    isChecked =
                        toolName && server.associatedTools.includes(toolName);
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
// HTMX HANDLERS for dynamic content loading
// ===================================================================

// Set up HTMX handler for auto-checking newly loaded tools when Select All is active or Edit Server mode
if (window.htmx && !window._toolsHtmxHandlerAttached) {
    window._toolsHtmxHandlerAttached = true;

    window.htmx.on("htmx:afterSettle", function (evt) {
        // Only handle tool pagination requests
        if (
            evt.detail.pathInfo &&
            evt.detail.pathInfo.requestPath &&
            evt.detail.pathInfo.requestPath.includes("/admin/tools/partial")
        ) {
            // Use a slight delay to ensure DOM is fully updated
            setTimeout(() => {
                // Find which container actually triggered the request by checking the target
                let container = null;
                const target = evt.detail.target;

                // Check if the target itself is the edit server tools container (most common case for infinite scroll)
                if (target && target.id === "edit-server-tools") {
                    container = target;
                }
                // Or if target is the associated tools container (for add server)
                else if (target && target.id === "associatedTools") {
                    container = target;
                }
                // Otherwise try to find the container using closest
                else if (target) {
                    container =
                        target.closest("#associatedTools") ||
                        target.closest("#edit-server-tools");
                }

                // Fallback logic if container still not found
                if (!container) {
                    // Check which modal/dialog is currently open to determine the correct container
                    const editModal =
                        document.getElementById("server-edit-modal");
                    const isEditModalOpen =
                        editModal && !editModal.classList.contains("hidden");

                    if (isEditModalOpen) {
                        container =
                            document.getElementById("edit-server-tools");
                    } else {
                        container = document.getElementById("associatedTools");
                    }
                }

                // Final safety check - use direct lookup if still not found
                if (!container) {
                    const addServerContainer =
                        document.getElementById("associatedTools");
                    const editServerContainer =
                        document.getElementById("edit-server-tools");

                    // Check if edit server container has the server tools data attribute set
                    if (
                        editServerContainer &&
                        editServerContainer.getAttribute("data-server-tools")
                    ) {
                        container = editServerContainer;
                    } else if (
                        addServerContainer &&
                        addServerContainer.offsetParent !== null
                    ) {
                        container = addServerContainer;
                    } else if (
                        editServerContainer &&
                        editServerContainer.offsetParent !== null
                    ) {
                        container = editServerContainer;
                    } else {
                        // Last resort: just pick one that exists
                        container = addServerContainer || editServerContainer;
                    }
                }

                if (container) {
                    // Update tool mapping for newly loaded tools
                    const newCheckboxes = container.querySelectorAll(
                        "input[data-auto-check=true]",
                    );

                    if (!window.toolMapping) {
                        window.toolMapping = {};
                    }

                    newCheckboxes.forEach((cb) => {
                        const toolId = cb.value;
                        const toolName = cb.getAttribute("data-tool-name");
                        if (toolId && toolName) {
                            window.toolMapping[toolId] = toolName;
                        }
                    });

                    const selectAllInput = container.querySelector(
                        'input[name="selectAllTools"]',
                    );

                    // Check if Select All is active
                    if (selectAllInput && selectAllInput.value === "true") {
                        newCheckboxes.forEach((cb) => {
                            cb.checked = true;
                            cb.removeAttribute("data-auto-check");
                        });

                        if (newCheckboxes.length > 0) {
                            const event = new Event("change", {
                                bubbles: true,
                            });
                            container.dispatchEvent(event);
                        }
                    }
                    // Check if we're in Edit Server mode and need to pre-select tools
                    else if (container.id === "edit-server-tools") {
                        // Try to get server tools from data attribute (primary source)
                        let serverTools = null;
                        const dataAttr =
                            container.getAttribute("data-server-tools");

                        if (dataAttr) {
                            try {
                                serverTools = JSON.parse(dataAttr);
                            } catch (e) {
                                console.error(
                                    "Failed to parse data-server-tools:",
                                    e,
                                );
                            }
                        }

                        if (serverTools && serverTools.length > 0) {
                            newCheckboxes.forEach((cb) => {
                                const toolId = cb.value;
                                const toolName =
                                    cb.getAttribute("data-tool-name"); // Use the data attribute directly
                                if (toolId && toolName) {
                                    // Check if this tool name exists in server associated tools
                                    if (serverTools.includes(toolName)) {
                                        cb.checked = true;
                                    }
                                }
                                cb.removeAttribute("data-auto-check");
                            });

                            // Trigger an update to display the correct count based on server.associatedTools
                            // This will make sure the pill counters reflect the total associated tools count
                            const event = new Event("change", {
                                bubbles: true,
                            });
                            container.dispatchEvent(event);
                        }
                    }
                }
            }, 10); // Small delay to ensure DOM is updated
        }
    });
}

// Set up HTMX handler for auto-checking newly loaded resources when Select All is active
if (window.htmx && !window._resourcesHtmxHandlerAttached) {
    window._resourcesHtmxHandlerAttached = true;

    window.htmx.on("htmx:afterSettle", function (evt) {
        // Only handle resource pagination requests
        if (
            evt.detail.pathInfo &&
            evt.detail.pathInfo.requestPath &&
            evt.detail.pathInfo.requestPath.includes("/admin/resources/partial")
        ) {
            setTimeout(() => {
                // Find the container
                let container = null;
                const target = evt.detail.target;

                if (target && target.id === "edit-server-resources") {
                    container = target;
                } else if (target && target.id === "associatedResources") {
                    container = target;
                } else if (target) {
                    container =
                        target.closest("#associatedResources") ||
                        target.closest("#edit-server-resources");
                }

                if (!container) {
                    const editModal =
                        document.getElementById("server-edit-modal");
                    const isEditModalOpen =
                        editModal && !editModal.classList.contains("hidden");

                    if (isEditModalOpen) {
                        container = document.getElementById(
                            "edit-server-resources",
                        );
                    } else {
                        container = document.getElementById(
                            "associatedResources",
                        );
                    }
                }

                if (container) {
                    const newCheckboxes = container.querySelectorAll(
                        "input[data-auto-check=true]",
                    );

                    const selectAllInput = container.querySelector(
                        'input[name="selectAllResources"]',
                    );

                    // Check if Select All is active
                    if (selectAllInput && selectAllInput.value === "true") {
                        newCheckboxes.forEach((cb) => {
                            cb.checked = true;
                            cb.removeAttribute("data-auto-check");
                        });

                        if (newCheckboxes.length > 0) {
                            const event = new Event("change", {
                                bubbles: true,
                            });
                            container.dispatchEvent(event);
                        }
                    }

                    // Also check for edit mode: pre-select items based on server's associated resources
                    const dataAttr = container.getAttribute(
                        "data-server-resources",
                    );
                    if (dataAttr) {
                        try {
                            const associatedResourceIds = JSON.parse(dataAttr);
                            newCheckboxes.forEach((cb) => {
                                const checkboxValue = parseInt(cb.value);
                                if (
                                    associatedResourceIds.includes(
                                        checkboxValue,
                                    )
                                ) {
                                    cb.checked = true;
                                }
                                cb.removeAttribute("data-auto-check");
                            });

                            if (newCheckboxes.length > 0) {
                                const event = new Event("change", {
                                    bubbles: true,
                                });
                                container.dispatchEvent(event);
                            }
                        } catch (e) {
                            console.error(
                                "Error parsing data-server-resources:",
                                e,
                            );
                        }
                    }
                }
            }, 10);
        }
    });
}

// Set up HTMX handler for auto-checking newly loaded prompts when Select All is active
if (window.htmx && !window._promptsHtmxHandlerAttached) {
    window._promptsHtmxHandlerAttached = true;

    window.htmx.on("htmx:afterSettle", function (evt) {
        // Only handle prompt pagination requests
        if (
            evt.detail.pathInfo &&
            evt.detail.pathInfo.requestPath &&
            evt.detail.pathInfo.requestPath.includes("/admin/prompts/partial")
        ) {
            setTimeout(() => {
                // Find the container
                let container = null;
                const target = evt.detail.target;

                if (target && target.id === "edit-server-prompts") {
                    container = target;
                } else if (target && target.id === "associatedPrompts") {
                    container = target;
                } else if (target) {
                    container =
                        target.closest("#associatedPrompts") ||
                        target.closest("#edit-server-prompts");
                }

                if (!container) {
                    const editModal =
                        document.getElementById("server-edit-modal");
                    const isEditModalOpen =
                        editModal && !editModal.classList.contains("hidden");

                    if (isEditModalOpen) {
                        container = document.getElementById(
                            "edit-server-prompts",
                        );
                    } else {
                        container =
                            document.getElementById("associatedPrompts");
                    }
                }

                if (container) {
                    const newCheckboxes = container.querySelectorAll(
                        "input[data-auto-check=true]",
                    );

                    const selectAllInput = container.querySelector(
                        'input[name="selectAllPrompts"]',
                    );

                    // Check if Select All is active
                    if (selectAllInput && selectAllInput.value === "true") {
                        newCheckboxes.forEach((cb) => {
                            cb.checked = true;
                            cb.removeAttribute("data-auto-check");
                        });

                        if (newCheckboxes.length > 0) {
                            const event = new Event("change", {
                                bubbles: true,
                            });
                            container.dispatchEvent(event);
                        }
                    }

                    // Also check for edit mode: pre-select items based on server's associated prompts
                    const dataAttr = container.getAttribute(
                        "data-server-prompts",
                    );
                    if (dataAttr) {
                        try {
                            const associatedPromptIds = JSON.parse(dataAttr);
                            newCheckboxes.forEach((cb) => {
                                const checkboxValue = parseInt(cb.value);
                                if (
                                    associatedPromptIds.includes(checkboxValue)
                                ) {
                                    cb.checked = true;
                                }
                                cb.removeAttribute("data-auto-check");
                            });

                            if (newCheckboxes.length > 0) {
                                const event = new Event("change", {
                                    bubbles: true,
                                });
                                container.dispatchEvent(event);
                            }
                        } catch (e) {
                            console.error(
                                "Error parsing data-server-prompts:",
                                e,
                            );
                        }
                    }
                }
            }, 10);
        }
    });
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
                if (tabName === "llm-chat") {
                    initializeLLMChat();
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
                        const isEmpty = !tokensList.innerHTML.trim();
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

                    // Update team scoping warning when switching to tokens tab
                    updateTeamScopingWarning();
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

                if (tabName === "mcp-registry") {
                    // Load MCP Registry content
                    const registryContent = safeGetElement(
                        "mcp-registry-servers",
                    );
                    if (registryContent) {
                        // Always load on first visit or if showing loading message
                        const hasLoadingMessage =
                            registryContent.innerHTML.includes(
                                "Loading MCP Registry servers...",
                            );
                        const needsLoad =
                            hasLoadingMessage ||
                            !registryContent.getAttribute("data-loaded");

                        if (needsLoad) {
                            const rootPath = window.ROOT_PATH || "";

                            // Use HTMX if available
                            if (window.htmx && window.htmx.ajax) {
                                window.htmx
                                    .ajax(
                                        "GET",
                                        `${rootPath}/admin/mcp-registry/partial`,
                                        {
                                            target: "#mcp-registry-servers",
                                            swap: "innerHTML",
                                        },
                                    )
                                    .then(() => {
                                        registryContent.setAttribute(
                                            "data-loaded",
                                            "true",
                                        );
                                    });
                            } else {
                                // Fallback to fetch if HTMX is not available
                                fetch(`${rootPath}/admin/mcp-registry/partial`)
                                    .then((response) => response.text())
                                    .then((html) => {
                                        registryContent.innerHTML = html;
                                        registryContent.setAttribute(
                                            "data-loaded",
                                            "true",
                                        );
                                        // Process any HTMX attributes in the new content
                                        if (window.htmx) {
                                            window.htmx.process(
                                                registryContent,
                                            );
                                        }
                                    })
                                    .catch((error) => {
                                        console.error(
                                            "Failed to load MCP Registry:",
                                            error,
                                        );
                                        registryContent.innerHTML =
                                            '<div class="text-center text-red-600 py-8">Failed to load MCP Registry servers</div>';
                                    });
                            }
                        }
                    }
                }

                if (tabName === "gateways") {
                    // Reload gateways list to show any newly registered servers
                    const gatewaysSection = safeGetElement("gateways-section");
                    if (gatewaysSection) {
                        const gatewaysTbody =
                            gatewaysSection.querySelector("tbody");
                        if (gatewaysTbody) {
                            // Trigger HTMX reload if available
                            if (window.htmx && window.htmx.trigger) {
                                window.htmx.trigger(gatewaysTbody, "load");
                            } else {
                                // Fallback: reload the page section via fetch
                                const rootPath = window.ROOT_PATH || "";
                                fetch(`${rootPath}/admin`)
                                    .then((response) => response.text())
                                    .then((html) => {
                                        // Parse the HTML and extract just the gateways table
                                        const parser = new DOMParser();
                                        const doc = parser.parseFromString(
                                            html,
                                            "text/html",
                                        );
                                        const newTbody = doc.querySelector(
                                            "#gateways-section tbody",
                                        );
                                        if (newTbody) {
                                            gatewaysTbody.innerHTML =
                                                newTbody.innerHTML;
                                            // Process any HTMX attributes in the new content
                                            if (window.htmx) {
                                                window.htmx.process(
                                                    gatewaysTbody,
                                                );
                                            }
                                        }
                                    })
                                    .catch((error) => {
                                        console.error(
                                            "Failed to reload gateways:",
                                            error,
                                        );
                                    });
                            }
                        }
                    }
                }

                if (tabName === "plugins") {
                    const pluginsPanel = safeGetElement("plugins-panel");
                    if (pluginsPanel && pluginsPanel.innerHTML.trim() === "") {
                        const rootPath = window.ROOT_PATH || "";
                        fetchWithTimeout(
                            `${rootPath}/admin/plugins/partial`,
                            {
                                method: "GET",
                                credentials: "same-origin",
                                headers: {
                                    Accept: "text/html",
                                },
                            },
                            5000,
                        )
                            .then((response) => {
                                if (!response.ok) {
                                    throw new Error(
                                        `HTTP error! status: ${response.status}`,
                                    );
                                }
                                return response.text();
                            })
                            .then((html) => {
                                pluginsPanel.innerHTML = html;
                                // Initialize plugin functions after HTML is loaded
                                initializePluginFunctions();
                                // Populate filter dropdowns
                                if (window.populatePluginFilters) {
                                    window.populatePluginFilters();
                                }
                            })
                            .catch((error) => {
                                console.error(
                                    "Error loading plugins partial:",
                                    error,
                                );
                                pluginsPanel.innerHTML = `
                                    <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
                                        <strong class="font-bold">Error loading plugins:</strong>
                                        <span class="block sm:inline">${escapeHtml(error.message)}</span>
                                    </div>
                                `;
                            });
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

window.showTab = showTab;
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
        "mt-1 px-1.5 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200";

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
        "mt-1 px-1.5 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200";

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
        "mt-1 px-1.5 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200";
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

    const pillClasses =
        "inline-block bg-green-100 text-green-800 text-xs px-2 py-1 rounded-full dark:bg-green-900 dark:text-green-200";

    function update() {
        try {
            const checkboxes = container.querySelectorAll(
                'input[type="checkbox"]',
            );
            const checked = Array.from(checkboxes).filter((cb) => cb.checked);

            // Check if "Select All" mode is active
            const selectAllInput = container.querySelector(
                'input[name="selectAllTools"]',
            );
            const allIdsInput = container.querySelector(
                'input[name="allToolIds"]',
            );

            // Check if this is the edit server tools container
            const isEditServerMode = selectId === "edit-server-tools";
            let serverTools = null;

            if (isEditServerMode) {
                const dataAttr = container.getAttribute("data-server-tools");
                if (dataAttr) {
                    try {
                        serverTools = JSON.parse(dataAttr);
                    } catch (e) {
                        console.error("Error parsing data-server-tools:", e);
                    }
                }
            }

            let count = checked.length;

            // If Select All mode is active, use the count from allToolIds
            if (
                selectAllInput &&
                selectAllInput.value === "true" &&
                allIdsInput
            ) {
                try {
                    const allIds = JSON.parse(allIdsInput.value);
                    count = allIds.length;
                } catch (e) {
                    console.error("Error parsing allToolIds:", e);
                }
            }
            // If in edit server mode and we have server tools data, use that count
            else if (
                isEditServerMode &&
                serverTools &&
                Array.isArray(serverTools)
            ) {
                count = serverTools.length;
            }

            // Rebuild pills safely - show first 3, then summarize the rest
            pillsBox.innerHTML = "";
            const maxPillsToShow = 3;

            // In edit server mode, we want to show the server tools rather than just currently checked ones
            let pillsToDisplay = checked;
            if (
                isEditServerMode &&
                serverTools &&
                Array.isArray(serverTools) &&
                window.toolMapping
            ) {
                // Create a list of tools that exist both in serverTools and currently loaded tools
                const allLoadedTools = Array.from(checkboxes);
                pillsToDisplay = allLoadedTools.filter((checkbox) => {
                    const toolName = window.toolMapping[checkbox.value];
                    return toolName && serverTools.includes(toolName);
                });
            }

            pillsToDisplay.slice(0, maxPillsToShow).forEach((cb) => {
                const span = document.createElement("span");
                span.className = pillClasses;
                span.textContent =
                    cb.nextElementSibling?.textContent?.trim() || "Unnamed";
                pillsBox.appendChild(span);
            });

            // If more than maxPillsToShow, show a summary pill
            if (count > maxPillsToShow) {
                const span = document.createElement("span");
                span.className = pillClasses + " cursor-pointer";
                span.title = "Click to see all selected tools";
                const remaining = count - maxPillsToShow;
                span.textContent = `+${remaining} more`;
                pillsBox.appendChild(span);
            }

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

    // Remove old event listeners by cloning and replacing (preserving ID)
    if (clearBtn && !clearBtn.dataset.listenerAttached) {
        clearBtn.dataset.listenerAttached = "true";
        const newClearBtn = clearBtn.cloneNode(true);
        newClearBtn.dataset.listenerAttached = "true";
        clearBtn.parentNode.replaceChild(newClearBtn, clearBtn);

        newClearBtn.addEventListener("click", () => {
            const checkboxes = container.querySelectorAll(
                'input[type="checkbox"]',
            );
            checkboxes.forEach((cb) => (cb.checked = false));

            // Clear the "select all" flag
            const selectAllInput = container.querySelector(
                'input[name="selectAllTools"]',
            );
            if (selectAllInput) {
                selectAllInput.remove();
            }
            const allIdsInput = container.querySelector(
                'input[name="allToolIds"]',
            );
            if (allIdsInput) {
                allIdsInput.remove();
            }

            update();
        });
    }

    if (selectBtn && !selectBtn.dataset.listenerAttached) {
        selectBtn.dataset.listenerAttached = "true";
        const newSelectBtn = selectBtn.cloneNode(true);
        newSelectBtn.dataset.listenerAttached = "true";
        selectBtn.parentNode.replaceChild(newSelectBtn, selectBtn);

        newSelectBtn.addEventListener("click", async () => {
            // Disable button and show loading state
            const originalText = newSelectBtn.textContent;
            newSelectBtn.disabled = true;
            newSelectBtn.textContent = "Selecting all tools...";

            try {
                // Prefer full-set selection when pagination/infinite-scroll is present
                const loadedCheckboxes = container.querySelectorAll(
                    'input[type="checkbox"]',
                );
                const visibleCheckboxes = Array.from(loadedCheckboxes).filter(
                    (cb) => cb.offsetParent !== null,
                );

                // Detect pagination/infinite-scroll controls for tools
                const hasPaginationControls = !!document.getElementById(
                    "tools-pagination-controls",
                );
                const hasScrollTrigger = !!document.querySelector(
                    "[id^='tools-scroll-trigger']",
                );
                const isPaginated = hasPaginationControls || hasScrollTrigger;

                let allToolIds = [];

                if (!isPaginated && visibleCheckboxes.length > 0) {
                    // No pagination and some visible items => select visible set
                    allToolIds = visibleCheckboxes.map((cb) => cb.value);
                    visibleCheckboxes.forEach((cb) => (cb.checked = true));
                } else {
                    // Paginated (or no visible items) => fetch full set from server
                    const selectedGatewayIds = getSelectedGatewayIds
                        ? getSelectedGatewayIds()
                        : [];
                    const gatewayParam =
                        selectedGatewayIds && selectedGatewayIds.length
                            ? `?gateway_id=${encodeURIComponent(selectedGatewayIds.join(","))}`
                            : "";
                    const response = await fetch(
                        `${window.ROOT_PATH}/admin/tools/ids${gatewayParam}`,
                    );
                    if (!response.ok) {
                        throw new Error("Failed to fetch tool IDs");
                    }
                    const data = await response.json();
                    allToolIds = data.tool_ids || [];
                    // Check loaded checkboxes so UI shows selection where possible
                    loadedCheckboxes.forEach((cb) => (cb.checked = true));
                }

                // Add a hidden input to indicate "select all" mode
                let selectAllInput = container.querySelector(
                    'input[name="selectAllTools"]',
                );
                if (!selectAllInput) {
                    selectAllInput = document.createElement("input");
                    selectAllInput.type = "hidden";
                    selectAllInput.name = "selectAllTools";
                    container.appendChild(selectAllInput);
                }
                selectAllInput.value = "true";

                // Also store the IDs as a JSON array for the backend
                let allIdsInput = container.querySelector(
                    'input[name="allToolIds"]',
                );
                if (!allIdsInput) {
                    allIdsInput = document.createElement("input");
                    allIdsInput.type = "hidden";
                    allIdsInput.name = "allToolIds";
                    container.appendChild(allIdsInput);
                }
                allIdsInput.value = JSON.stringify(allToolIds);

                update();

                newSelectBtn.textContent = `✓ All ${allToolIds.length} tools selected`;
                setTimeout(() => {
                    newSelectBtn.textContent = originalText;
                }, 2000);
            } catch (error) {
                console.error("Error in Select All:", error);
                alert("Failed to select all tools. Please try again.");
                newSelectBtn.disabled = false;
                newSelectBtn.textContent = originalText;
            } finally {
                newSelectBtn.disabled = false;
            }
        });
    }

    update(); // Initial render

    // Attach change listeners to checkboxes (using delegation for dynamic content)
    if (!container.dataset.changeListenerAttached) {
        container.dataset.changeListenerAttached = "true";
        container.addEventListener("change", (e) => {
            if (e.target.type === "checkbox") {
                // Check if we're in "Select All" mode
                const selectAllInput = container.querySelector(
                    'input[name="selectAllTools"]',
                );
                const allIdsInput = container.querySelector(
                    'input[name="allToolIds"]',
                );

                if (
                    selectAllInput &&
                    selectAllInput.value === "true" &&
                    allIdsInput
                ) {
                    // User is manually checking/unchecking after Select All
                    // Update the allToolIds array to reflect the change
                    try {
                        let allIds = JSON.parse(allIdsInput.value);
                        const toolId = e.target.value;

                        if (e.target.checked) {
                            // Add the ID if it's not already there
                            if (!allIds.includes(toolId)) {
                                allIds.push(toolId);
                            }
                        } else {
                            // Remove the ID from the array
                            allIds = allIds.filter((id) => id !== toolId);
                        }

                        // Update the hidden field
                        allIdsInput.value = JSON.stringify(allIds);
                    } catch (error) {
                        console.error("Error updating allToolIds:", error);
                    }
                }
                // Check if we're in edit server mode
                else if (selectId === "edit-server-tools") {
                    // In edit server mode, update the server tools data based on checkbox state
                    const dataAttr =
                        container.getAttribute("data-server-tools");
                    let serverTools = [];

                    if (dataAttr) {
                        try {
                            serverTools = JSON.parse(dataAttr);
                        } catch (e) {
                            console.error(
                                "Error parsing data-server-tools:",
                                e,
                            );
                        }
                    }

                    // Get the tool name from toolMapping to update serverTools array
                    const toolId = e.target.value;
                    const toolName =
                        window.toolMapping && window.toolMapping[toolId];

                    if (toolName) {
                        if (e.target.checked) {
                            // Add tool name to server tools if not already there
                            if (!serverTools.includes(toolName)) {
                                serverTools.push(toolName);
                            }
                        } else {
                            // Remove tool name from server tools
                            serverTools = serverTools.filter(
                                (name) => name !== toolName,
                            );
                        }

                        // Update the data attribute
                        container.setAttribute(
                            "data-server-tools",
                            JSON.stringify(serverTools),
                        );
                    }
                }

                update();
            }
        });
    }
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

    const pillClasses =
        "inline-block px-3 py-1 text-xs font-semibold text-blue-700 bg-blue-100 rounded-full shadow dark:text-blue-300 dark:bg-blue-900";

    function update() {
        try {
            const checkboxes = container.querySelectorAll(
                'input[type="checkbox"]',
            );
            const checked = Array.from(checkboxes).filter((cb) => cb.checked);
            // const count = checked.length;

            // Select All handling
            const selectAllInput = container.querySelector(
                'input[name="selectAllResources"]',
            );
            const allIdsInput = container.querySelector(
                'input[name="allResourceIds"]',
            );

            let count = checked.length;
            if (
                selectAllInput &&
                selectAllInput.value === "true" &&
                allIdsInput
            ) {
                try {
                    const allIds = JSON.parse(allIdsInput.value);
                    count = allIds.length;
                } catch (e) {
                    console.error("Error parsing allResourceIds:", e);
                }
            }

            // Rebuild pills safely - show first 3, then summarize the rest
            pillsBox.innerHTML = "";
            const maxPillsToShow = 3;

            checked.slice(0, maxPillsToShow).forEach((cb) => {
                const span = document.createElement("span");
                span.className = pillClasses;
                span.textContent =
                    cb.nextElementSibling?.textContent?.trim() || "Unnamed";
                pillsBox.appendChild(span);
            });

            // If more than maxPillsToShow, show a summary pill
            if (count > maxPillsToShow) {
                const span = document.createElement("span");
                span.className = pillClasses + " cursor-pointer";
                span.title = "Click to see all selected resources";
                const remaining = count - maxPillsToShow;
                span.textContent = `+${remaining} more`;
                pillsBox.appendChild(span);
            }

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

    // Remove old event listeners by cloning and replacing (preserving ID)
    if (clearBtn && !clearBtn.dataset.listenerAttached) {
        clearBtn.dataset.listenerAttached = "true";
        const newClearBtn = clearBtn.cloneNode(true);
        newClearBtn.dataset.listenerAttached = "true";
        clearBtn.parentNode.replaceChild(newClearBtn, clearBtn);

        newClearBtn.addEventListener("click", () => {
            const checkboxes = container.querySelectorAll(
                'input[type="checkbox"]',
            );
            checkboxes.forEach((cb) => (cb.checked = false));

            // Remove any select-all hidden inputs
            const selectAllInput = container.querySelector(
                'input[name="selectAllResources"]',
            );
            if (selectAllInput) {
                selectAllInput.remove();
            }
            const allIdsInput = container.querySelector(
                'input[name="allResourceIds"]',
            );
            if (allIdsInput) {
                allIdsInput.remove();
            }

            update();
        });
    }

    if (selectBtn && !selectBtn.dataset.listenerAttached) {
        selectBtn.dataset.listenerAttached = "true";
        const newSelectBtn = selectBtn.cloneNode(true);
        newSelectBtn.dataset.listenerAttached = "true";
        selectBtn.parentNode.replaceChild(newSelectBtn, selectBtn);

        newSelectBtn.addEventListener("click", async () => {
            const originalText = newSelectBtn.textContent;
            newSelectBtn.disabled = true;
            newSelectBtn.textContent = "Selecting all resources...";

            try {
                // Prefer full-set selection when pagination/infinite-scroll is present
                const loadedCheckboxes = container.querySelectorAll(
                    'input[type="checkbox"]',
                );
                const visibleCheckboxes = Array.from(loadedCheckboxes).filter(
                    (cb) => cb.offsetParent !== null,
                );

                // Detect pagination/infinite-scroll controls for resources
                const hasPaginationControls = !!document.getElementById(
                    "resources-pagination-controls",
                );
                const hasScrollTrigger = !!document.querySelector(
                    "[id^='resources-scroll-trigger']",
                );
                const isPaginated = hasPaginationControls || hasScrollTrigger;

                let allIds = [];

                if (!isPaginated && visibleCheckboxes.length > 0) {
                    // No pagination and some visible items => select visible set
                    allIds = visibleCheckboxes.map((cb) => cb.value);
                    visibleCheckboxes.forEach((cb) => (cb.checked = true));
                } else {
                    // Paginated (or no visible items) => fetch full set from server
                    const selectedGatewayIds = getSelectedGatewayIds
                        ? getSelectedGatewayIds()
                        : [];
                    const gatewayParam =
                        selectedGatewayIds && selectedGatewayIds.length
                            ? `?gateway_id=${encodeURIComponent(selectedGatewayIds.join(","))}`
                            : "";
                    const resp = await fetch(
                        `${window.ROOT_PATH}/admin/resources/ids${gatewayParam}`,
                    );
                    if (!resp.ok) {
                        throw new Error("Failed to fetch resource IDs");
                    }
                    const data = await resp.json();
                    allIds = data.resource_ids || [];
                    // If nothing visible (paginated), check loaded checkboxes
                    loadedCheckboxes.forEach((cb) => (cb.checked = true));
                }

                // Add hidden select-all flag
                let selectAllInput = container.querySelector(
                    'input[name="selectAllResources"]',
                );
                if (!selectAllInput) {
                    selectAllInput = document.createElement("input");
                    selectAllInput.type = "hidden";
                    selectAllInput.name = "selectAllResources";
                    container.appendChild(selectAllInput);
                }
                selectAllInput.value = "true";

                // Store IDs as JSON for backend handling
                let allIdsInput = container.querySelector(
                    'input[name="allResourceIds"]',
                );
                if (!allIdsInput) {
                    allIdsInput = document.createElement("input");
                    allIdsInput.type = "hidden";
                    allIdsInput.name = "allResourceIds";
                    container.appendChild(allIdsInput);
                }
                allIdsInput.value = JSON.stringify(allIds);

                update();

                newSelectBtn.textContent = `✓ All ${allIds.length} resources selected`;
                setTimeout(() => {
                    newSelectBtn.textContent = originalText;
                }, 2000);
            } catch (error) {
                console.error("Error selecting all resources:", error);
                alert("Failed to select all resources. Please try again.");
            } finally {
                newSelectBtn.disabled = false;
            }
        });
    }

    update(); // Initial render

    // Attach change listeners using delegation for dynamic content
    if (!container.dataset.changeListenerAttached) {
        container.dataset.changeListenerAttached = "true";
        container.addEventListener("change", (e) => {
            if (e.target.type === "checkbox") {
                // If Select All mode is active, update the stored IDs array
                const selectAllInput = container.querySelector(
                    'input[name="selectAllResources"]',
                );
                const allIdsInput = container.querySelector(
                    'input[name="allResourceIds"]',
                );

                if (
                    selectAllInput &&
                    selectAllInput.value === "true" &&
                    allIdsInput
                ) {
                    try {
                        let allIds = JSON.parse(allIdsInput.value);
                        const id = e.target.value;
                        if (e.target.checked) {
                            if (!allIds.includes(id)) {
                                allIds.push(id);
                            }
                        } else {
                            allIds = allIds.filter((x) => x !== id);
                        }
                        allIdsInput.value = JSON.stringify(allIds);
                    } catch (err) {
                        console.error("Error updating allResourceIds:", err);
                    }
                }

                update();
            }
        });
    }
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

    const pillClasses =
        "inline-block px-3 py-1 text-xs font-semibold text-purple-700 bg-purple-100 rounded-full shadow dark:text-purple-300 dark:bg-purple-900";

    function update() {
        try {
            const checkboxes = container.querySelectorAll(
                'input[type="checkbox"]',
            );
            const checked = Array.from(checkboxes).filter((cb) => cb.checked);

            // Determine count: if Select All mode is active, use the stored allPromptIds
            const selectAllInput = container.querySelector(
                'input[name="selectAllPrompts"]',
            );
            const allIdsInput = container.querySelector(
                'input[name="allPromptIds"]',
            );

            let count = checked.length;
            if (
                selectAllInput &&
                selectAllInput.value === "true" &&
                allIdsInput
            ) {
                try {
                    const allIds = JSON.parse(allIdsInput.value);
                    count = allIds.length;
                } catch (e) {
                    console.error("Error parsing allPromptIds:", e);
                }
            }

            // Rebuild pills safely - show first 3, then summarize the rest
            pillsBox.innerHTML = "";
            const maxPillsToShow = 3;

            checked.slice(0, maxPillsToShow).forEach((cb) => {
                const span = document.createElement("span");
                span.className = pillClasses;
                span.textContent =
                    cb.nextElementSibling?.textContent?.trim() || "Unnamed";
                pillsBox.appendChild(span);
            });

            // If more than maxPillsToShow, show a summary pill
            if (count > maxPillsToShow) {
                const span = document.createElement("span");
                span.className = pillClasses + " cursor-pointer";
                span.title = "Click to see all selected prompts";
                const remaining = count - maxPillsToShow;
                span.textContent = `+${remaining} more`;
                pillsBox.appendChild(span);
            }

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

    // Remove old event listeners by cloning and replacing (preserving ID)
    if (clearBtn && !clearBtn.dataset.listenerAttached) {
        clearBtn.dataset.listenerAttached = "true";
        const newClearBtn = clearBtn.cloneNode(true);
        newClearBtn.dataset.listenerAttached = "true";
        clearBtn.parentNode.replaceChild(newClearBtn, clearBtn);

        newClearBtn.addEventListener("click", () => {
            const checkboxes = container.querySelectorAll(
                'input[type="checkbox"]',
            );
            checkboxes.forEach((cb) => (cb.checked = false));

            // Remove any select-all hidden inputs
            const selectAllInput = container.querySelector(
                'input[name="selectAllPrompts"]',
            );
            if (selectAllInput) {
                selectAllInput.remove();
            }
            const allIdsInput = container.querySelector(
                'input[name="allPromptIds"]',
            );
            if (allIdsInput) {
                allIdsInput.remove();
            }

            update();
        });
    }

    if (selectBtn && !selectBtn.dataset.listenerAttached) {
        selectBtn.dataset.listenerAttached = "true";
        const newSelectBtn = selectBtn.cloneNode(true);
        newSelectBtn.dataset.listenerAttached = "true";
        selectBtn.parentNode.replaceChild(newSelectBtn, selectBtn);
        newSelectBtn.addEventListener("click", async () => {
            const originalText = newSelectBtn.textContent;
            newSelectBtn.disabled = true;
            newSelectBtn.textContent = "Selecting all prompts...";

            try {
                // Prefer full-set selection when pagination/infinite-scroll is present
                const loadedCheckboxes = container.querySelectorAll(
                    'input[type="checkbox"]',
                );
                const visibleCheckboxes = Array.from(loadedCheckboxes).filter(
                    (cb) => cb.offsetParent !== null,
                );

                // Detect pagination/infinite-scroll controls for prompts
                const hasPaginationControls = !!document.getElementById(
                    "prompts-pagination-controls",
                );
                const hasScrollTrigger = !!document.querySelector(
                    "[id^='prompts-scroll-trigger']",
                );
                const isPaginated = hasPaginationControls || hasScrollTrigger;

                let allIds = [];

                if (!isPaginated && visibleCheckboxes.length > 0) {
                    // No pagination and some visible items => select visible set
                    allIds = visibleCheckboxes.map((cb) => cb.value);
                    visibleCheckboxes.forEach((cb) => (cb.checked = true));
                } else {
                    // Paginated (or no visible items) => fetch full set from server
                    const selectedGatewayIds = getSelectedGatewayIds
                        ? getSelectedGatewayIds()
                        : [];
                    const gatewayParam =
                        selectedGatewayIds && selectedGatewayIds.length
                            ? `?gateway_id=${encodeURIComponent(selectedGatewayIds.join(","))}`
                            : "";
                    const resp = await fetch(
                        `${window.ROOT_PATH}/admin/prompts/ids${gatewayParam}`,
                    );
                    if (!resp.ok) {
                        throw new Error("Failed to fetch prompt IDs");
                    }
                    const data = await resp.json();
                    allIds = data.prompt_ids || [];
                    // If nothing visible (paginated), check loaded checkboxes
                    loadedCheckboxes.forEach((cb) => (cb.checked = true));
                }

                // Add hidden select-all flag
                let selectAllInput = container.querySelector(
                    'input[name="selectAllPrompts"]',
                );
                if (!selectAllInput) {
                    selectAllInput = document.createElement("input");
                    selectAllInput.type = "hidden";
                    selectAllInput.name = "selectAllPrompts";
                    container.appendChild(selectAllInput);
                }
                selectAllInput.value = "true";

                // Store IDs as JSON for backend handling
                let allIdsInput = container.querySelector(
                    'input[name="allPromptIds"]',
                );
                if (!allIdsInput) {
                    allIdsInput = document.createElement("input");
                    allIdsInput.type = "hidden";
                    allIdsInput.name = "allPromptIds";
                    container.appendChild(allIdsInput);
                }
                allIdsInput.value = JSON.stringify(allIds);

                update();

                newSelectBtn.textContent = `✓ All ${allIds.length} prompts selected`;
                setTimeout(() => {
                    newSelectBtn.textContent = originalText;
                }, 2000);
            } catch (error) {
                console.error("Error selecting all prompts:", error);
                alert("Failed to select all prompts. Please try again.");
            } finally {
                newSelectBtn.disabled = false;
            }
        });
    }

    update(); // Initial render

    // Attach change listeners using delegation for dynamic content
    if (!container.dataset.changeListenerAttached) {
        container.dataset.changeListenerAttached = "true";
        container.addEventListener("change", (e) => {
            if (e.target.type === "checkbox") {
                // If Select All mode is active, update the stored IDs array
                const selectAllInput = container.querySelector(
                    'input[name="selectAllPrompts"]',
                );
                const allIdsInput = container.querySelector(
                    'input[name="allPromptIds"]',
                );

                if (
                    selectAllInput &&
                    selectAllInput.value === "true" &&
                    allIdsInput
                ) {
                    try {
                        let allIds = JSON.parse(allIdsInput.value);
                        const id = e.target.value;
                        if (e.target.checked) {
                            if (!allIds.includes(id)) {
                                allIds.push(id);
                            }
                        } else {
                            allIds = allIds.filter((x) => x !== id);
                        }
                        allIdsInput.value = JSON.stringify(allIds);
                    } catch (err) {
                        console.error("Error updating allPromptIds:", err);
                    }
                }

                update();
            }
        });
    }
}

// ===================================================================
// GATEWAY SELECT (Associated MCP Servers) - search/select/clear
// ===================================================================
function initGatewaySelect(
    selectId = "associatedGateways",
    pillsId = "selectedGatewayPills",
    warnId = "selectedGatewayWarning",
    max = 12,
    selectBtnId = "selectAllGatewayBtn",
    clearBtnId = "clearAllGatewayBtn",
    searchInputId = "searchGateways",
) {
    const container = document.getElementById(selectId);
    const pillsBox = document.getElementById(pillsId);
    const warnBox = document.getElementById(warnId);
    const clearBtn = clearBtnId ? document.getElementById(clearBtnId) : null;
    const selectBtn = selectBtnId ? document.getElementById(selectBtnId) : null;
    const searchInput = searchInputId
        ? document.getElementById(searchInputId)
        : null;

    if (!container || !pillsBox || !warnBox) {
        console.warn(
            `Gateway select elements not found: ${selectId}, ${pillsId}, ${warnId}`,
        );
        return;
    }

    const pillClasses =
        "inline-block bg-indigo-100 text-indigo-800 text-xs px-2 py-1 rounded-full dark:bg-indigo-900 dark:text-indigo-200";

    // Search functionality
    function applySearch() {
        if (!searchInput) {
            return;
        }

        try {
            const query = searchInput.value.toLowerCase().trim();
            const items = container.querySelectorAll(".tool-item");
            let visibleCount = 0;

            items.forEach((item) => {
                const text = item.textContent.toLowerCase();
                if (!query || text.includes(query)) {
                    item.style.display = "";
                    visibleCount++;
                } else {
                    item.style.display = "none";
                }
            });

            // Update "no results" message if it exists
            const noMsg = document.getElementById("noGatewayMessage");
            const searchQuerySpan =
                document.getElementById("searchQueryServers");

            if (noMsg) {
                if (query && visibleCount === 0) {
                    noMsg.style.display = "block";
                    if (searchQuerySpan) {
                        searchQuerySpan.textContent = query;
                    }
                } else {
                    noMsg.style.display = "none";
                }
            }
        } catch (error) {
            console.error("Error applying gateway search:", error);
        }
    }

    // Bind search input
    if (searchInput && !searchInput.dataset.searchBound) {
        searchInput.addEventListener("input", applySearch);
        searchInput.dataset.searchBound = "true";
    }

    function update() {
        try {
            const checkboxes = container.querySelectorAll(
                'input[type="checkbox"]',
            );
            const checked = Array.from(checkboxes).filter((cb) => cb.checked);

            // Check if "Select All" mode is active
            const selectAllInput = container.querySelector(
                'input[name="selectAllGateways"]',
            );
            const allIdsInput = container.querySelector(
                'input[name="allGatewayIds"]',
            );

            let count = checked.length;

            // If Select All mode is active, use the count from allGatewayIds
            if (
                selectAllInput &&
                selectAllInput.value === "true" &&
                allIdsInput
            ) {
                try {
                    const allIds = JSON.parse(allIdsInput.value);
                    count = allIds.length;
                } catch (e) {
                    console.error("Error parsing allGatewayIds:", e);
                }
            }

            // Rebuild pills safely - show first 3, then summarize the rest
            pillsBox.innerHTML = "";
            const maxPillsToShow = 3;

            checked.slice(0, maxPillsToShow).forEach((cb) => {
                const span = document.createElement("span");
                span.className = pillClasses;
                span.textContent =
                    cb.nextElementSibling?.textContent?.trim() || "Unnamed";
                pillsBox.appendChild(span);
            });

            // If more than maxPillsToShow, show a summary pill
            if (count > maxPillsToShow) {
                const span = document.createElement("span");
                span.className = pillClasses + " cursor-pointer";
                span.title = "Click to see all selected gateways";
                const remaining = count - maxPillsToShow;
                span.textContent = `+${remaining} more`;
                pillsBox.appendChild(span);
            }

            // Warning when > max
            if (count > max) {
                warnBox.textContent = `Selected ${count} MCP servers. Selecting more than ${max} servers may impact performance.`;
            } else {
                warnBox.textContent = "";
            }
        } catch (error) {
            console.error("Error updating gateway select:", error);
        }
    }

    // Remove old event listeners by cloning and replacing (preserving ID)
    if (clearBtn && !clearBtn.dataset.listenerAttached) {
        clearBtn.dataset.listenerAttached = "true";
        const newClearBtn = clearBtn.cloneNode(true);
        newClearBtn.dataset.listenerAttached = "true";
        clearBtn.parentNode.replaceChild(newClearBtn, clearBtn);

        newClearBtn.addEventListener("click", () => {
            const checkboxes = container.querySelectorAll(
                'input[type="checkbox"]',
            );
            checkboxes.forEach((cb) => (cb.checked = false));

            // Clear the "select all" flag
            const selectAllInput = container.querySelector(
                'input[name="selectAllGateways"]',
            );
            if (selectAllInput) {
                selectAllInput.remove();
            }
            const allIdsInput = container.querySelector(
                'input[name="allGatewayIds"]',
            );
            if (allIdsInput) {
                allIdsInput.remove();
            }

            update();

            // Reload associated items after clearing selection
            reloadAssociatedItems();
        });
    }

    if (selectBtn && !selectBtn.dataset.listenerAttached) {
        selectBtn.dataset.listenerAttached = "true";
        const newSelectBtn = selectBtn.cloneNode(true);
        newSelectBtn.dataset.listenerAttached = "true";
        selectBtn.parentNode.replaceChild(newSelectBtn, selectBtn);

        newSelectBtn.addEventListener("click", async () => {
            // Disable button and show loading state
            const originalText = newSelectBtn.textContent;
            newSelectBtn.disabled = true;
            newSelectBtn.textContent = "Selecting all gateways...";

            try {
                // Fetch all gateway IDs from the server
                const response = await fetch(
                    `${window.ROOT_PATH}/admin/gateways/ids`,
                );
                if (!response.ok) {
                    throw new Error("Failed to fetch gateway IDs");
                }

                const data = await response.json();
                const allGatewayIds = data.gateway_ids || [];

                // Apply search filter first to determine which items are visible
                applySearch();

                // Check only currently visible checkboxes
                const loadedCheckboxes = container.querySelectorAll(
                    'input[type="checkbox"]',
                );
                loadedCheckboxes.forEach((cb) => {
                    const parent = cb.closest(".tool-item") || cb.parentElement;
                    const isVisible =
                        parent && getComputedStyle(parent).display !== "none";
                    if (isVisible) {
                        cb.checked = true;
                    }
                });

                // Add a hidden input to indicate "select all" mode
                // Remove any existing one first
                let selectAllInput = container.querySelector(
                    'input[name="selectAllGateways"]',
                );
                if (!selectAllInput) {
                    selectAllInput = document.createElement("input");
                    selectAllInput.type = "hidden";
                    selectAllInput.name = "selectAllGateways";
                    container.appendChild(selectAllInput);
                }
                selectAllInput.value = "true";

                // Also store the IDs as a JSON array for the backend
                // Ensure the special 'null' sentinel is included when selecting all
                try {
                    const nullCheckbox = container.querySelector(
                        'input[data-gateway-null="true"]',
                    );
                    if (nullCheckbox) {
                        // Include the literal string "null" so server-side
                        // `any(gid.lower() == 'null' ...)` evaluates to true.
                        if (!allGatewayIds.includes("null")) {
                            allGatewayIds.push("null");
                        }
                    }
                } catch (err) {
                    console.error(
                        "Error ensuring null sentinel in gateway IDs:",
                        err,
                    );
                }

                let allIdsInput = container.querySelector(
                    'input[name="allGatewayIds"]',
                );
                if (!allIdsInput) {
                    allIdsInput = document.createElement("input");
                    allIdsInput.type = "hidden";
                    allIdsInput.name = "allGatewayIds";
                    container.appendChild(allIdsInput);
                }
                allIdsInput.value = JSON.stringify(allGatewayIds);

                update();

                newSelectBtn.textContent = `✓ All ${allGatewayIds.length} gateways selected`;
                setTimeout(() => {
                    newSelectBtn.textContent = originalText;
                }, 2000);

                // Reload associated items after selecting all
                reloadAssociatedItems();
            } catch (error) {
                console.error("Error in Select All:", error);
                alert("Failed to select all gateways. Please try again.");
                newSelectBtn.disabled = false;
                newSelectBtn.textContent = originalText;
            } finally {
                newSelectBtn.disabled = false;
            }
        });
    }

    update(); // Initial render

    // Attach change listeners to checkboxes (using delegation for dynamic content)
    if (!container.dataset.changeListenerAttached) {
        container.dataset.changeListenerAttached = "true";
        container.addEventListener("change", (e) => {
            if (e.target.type === "checkbox") {
                // Log gateway_id when checkbox is clicked
                const gatewayId = e.target.value;
                const gatewayName =
                    e.target.nextElementSibling?.textContent?.trim() ||
                    "Unknown";
                const isChecked = e.target.checked;

                console.log(
                    `[MCP Server Selection] Gateway ID: ${gatewayId}, Name: ${gatewayName}, Checked: ${isChecked}`,
                );

                // Check if we're in "Select All" mode
                const selectAllInput = container.querySelector(
                    'input[name="selectAllGateways"]',
                );
                const allIdsInput = container.querySelector(
                    'input[name="allGatewayIds"]',
                );

                if (
                    selectAllInput &&
                    selectAllInput.value === "true" &&
                    allIdsInput
                ) {
                    // User is manually checking/unchecking after Select All
                    // Update the allGatewayIds array to reflect the change
                    try {
                        let allIds = JSON.parse(allIdsInput.value);

                        if (e.target.checked) {
                            // Add the ID if it's not already there
                            if (!allIds.includes(gatewayId)) {
                                allIds.push(gatewayId);
                            }
                        } else {
                            // Remove the ID from the array
                            allIds = allIds.filter((id) => id !== gatewayId);
                        }

                        // Update the hidden field
                        allIdsInput.value = JSON.stringify(allIds);
                    } catch (error) {
                        console.error("Error updating allGatewayIds:", error);
                    }
                }

                // No exclusivity: allow the special 'null' gateway (RestTool/Prompts/Resources) to be
                // selected together with real gateways. Server-side filtering already
                // supports mixed lists like `gateway_id=abc,null`.

                update();

                // Trigger reload of associated tools, resources, and prompts with selected gateway filter
                reloadAssociatedItems();
            }
        });
    }

    // Initial render
    applySearch();
    update();
}

/**
 * Get all selected gateway IDs from the gateway selection container
 * @returns {string[]} Array of selected gateway IDs
 */
function getSelectedGatewayIds() {
    const container = document.getElementById("associatedGateways");
    console.log("[Gateway Selection DEBUG] Container found:", !!container);

    if (!container) {
        console.warn(
            "[Gateway Selection DEBUG] associatedGateways container not found",
        );
        return [];
    }

    // Check if "Select All" mode is active
    const selectAllInput = container.querySelector(
        "input[name='selectAllGateways']",
    );
    const allIdsInput = container.querySelector("input[name='allGatewayIds']");

    console.log(
        "[Gateway Selection DEBUG] Select All mode:",
        selectAllInput?.value === "true",
    );
    if (selectAllInput && selectAllInput.value === "true" && allIdsInput) {
        try {
            const allIds = JSON.parse(allIdsInput.value);
            console.log(
                `[Gateway Selection DEBUG] Returning all gateway IDs (${allIds.length} total)`,
            );
            return allIds;
        } catch (error) {
            console.error(
                "[Gateway Selection DEBUG] Error parsing allGatewayIds:",
                error,
            );
        }
    }

    // Otherwise, get all checked checkboxes. If the special 'null' gateway
    // checkbox is selected, include the sentinel 'null' alongside any real
    // gateway ids. This allows requests like `gateway_id=abc,null` which the
    // server interprets as (gateway_id = abc) OR (gateway_id IS NULL).
    const checkboxes = container.querySelectorAll(
        "input[type='checkbox']:checked",
    );

    const selectedIds = Array.from(checkboxes)
        .map((cb) => {
            // Convert the special null-gateway checkbox to the literal 'null'
            if (cb.dataset?.gatewayNull === "true") {
                return "null";
            }
            return cb.value;
        })
        // Filter out any empty values to avoid sending empty CSV entries
        .filter((id) => id !== "" && id !== null && id !== undefined);

    console.log(
        `[Gateway Selection DEBUG] Found ${selectedIds.length} checked gateway checkboxes`,
    );
    console.log("[Gateway Selection DEBUG] Selected gateway IDs:", selectedIds);

    return selectedIds;
}

/**
 * Reload associated tools, resources, and prompts filtered by selected gateway IDs
 */
function reloadAssociatedItems() {
    const selectedGatewayIds = getSelectedGatewayIds();
    // Join all selected IDs (including the special 'null' sentinel if present)
    // so the server receives a combined filter like `gateway_id=abc,null`.
    let gatewayIdParam = "";
    if (selectedGatewayIds.length > 0) {
        gatewayIdParam = selectedGatewayIds.join(",");
    }

    console.log(
        `[Filter Update] Reloading associated items for gateway IDs: ${gatewayIdParam || "none (showing all)"}`,
    );
    console.log(
        "[Filter Update DEBUG] Selected gateway IDs array:",
        selectedGatewayIds,
    );

    // Reload tools
    const toolsContainer = document.getElementById("associatedTools");
    if (toolsContainer) {
        const toolsUrl = gatewayIdParam
            ? `${window.ROOT_PATH}/admin/tools/partial?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
            : `${window.ROOT_PATH}/admin/tools/partial?page=1&per_page=50&render=selector`;

        console.log("[Filter Update DEBUG] Tools URL:", toolsUrl);

        // Use HTMX to reload the content
        if (window.htmx) {
            htmx.ajax("GET", toolsUrl, {
                target: "#associatedTools",
                swap: "innerHTML",
            })
                .then(() => {
                    console.log(
                        "[Filter Update DEBUG] Tools reloaded successfully",
                    );
                    // Re-initialize the tool select after content is loaded
                    initToolSelect(
                        "associatedTools",
                        "selectedToolsPills",
                        "selectedToolsWarning",
                        6,
                        "selectAllToolsBtn",
                        "clearAllToolsBtn",
                    );
                })
                .catch((err) => {
                    console.error(
                        "[Filter Update DEBUG] Tools reload failed:",
                        err,
                    );
                });
        } else {
            console.error(
                "[Filter Update DEBUG] HTMX not available for tools reload",
            );
        }
    } else {
        console.warn("[Filter Update DEBUG] Tools container not found");
    }

    // Reload resources - use fetch directly to avoid HTMX race conditions
    const resourcesContainer = document.getElementById("associatedResources");
    if (resourcesContainer) {
        const resourcesUrl = gatewayIdParam
            ? `${window.ROOT_PATH}/admin/resources/partial?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
            : `${window.ROOT_PATH}/admin/resources/partial?page=1&per_page=50&render=selector`;

        console.log("[Filter Update DEBUG] Resources URL:", resourcesUrl);

        // Use fetch() directly instead of htmx.ajax() to avoid race conditions
        fetch(resourcesUrl, {
            method: "GET",
            headers: {
                "HX-Request": "true",
                "HX-Current-URL": window.location.href,
            },
        })
            .then((response) => {
                if (!response.ok) {
                    throw new Error(
                        `HTTP ${response.status}: ${response.statusText}`,
                    );
                }
                return response.text();
            })
            .then((html) => {
                console.log(
                    "[Filter Update DEBUG] Resources fetch successful, HTML length:",
                    html.length,
                );
                resourcesContainer.innerHTML = html;
                // If HTMX is available, process the newly-inserted HTML so hx-*
                // triggers (like the infinite-scroll 'intersect' trigger) are
                // initialized. To avoid HTMX re-triggering the container's
                // own `hx-get`/`hx-trigger="load"` (which would issue a second
                // request without the gateway filter), temporarily remove those
                // attributes from the container while we call `htmx.process`.
                if (window.htmx && typeof window.htmx.process === "function") {
                    try {
                        // Backup and remove attributes that could auto-fire
                        const hadHxGet =
                            resourcesContainer.hasAttribute("hx-get");
                        const hadHxTrigger =
                            resourcesContainer.hasAttribute("hx-trigger");
                        const oldHxGet =
                            resourcesContainer.getAttribute("hx-get");
                        const oldHxTrigger =
                            resourcesContainer.getAttribute("hx-trigger");

                        if (hadHxGet) {
                            resourcesContainer.removeAttribute("hx-get");
                        }
                        if (hadHxTrigger) {
                            resourcesContainer.removeAttribute("hx-trigger");
                        }

                        // Process only the newly-inserted inner nodes to initialize
                        // any hx-* behavior (infinite scroll, after-swap hooks, etc.)
                        window.htmx.process(resourcesContainer);

                        // Restore original attributes so the container retains its
                        // declarative behavior for future operations, but don't
                        // re-process (we already processed child nodes).
                        if (hadHxGet && oldHxGet !== null) {
                            resourcesContainer.setAttribute("hx-get", oldHxGet);
                        }
                        if (hadHxTrigger && oldHxTrigger !== null) {
                            resourcesContainer.setAttribute(
                                "hx-trigger",
                                oldHxTrigger,
                            );
                        }

                        console.log(
                            "[Filter Update DEBUG] htmx.process called on resources container (attributes temporarily removed)",
                        );
                    } catch (e) {
                        console.warn(
                            "[Filter Update DEBUG] htmx.process failed:",
                            e,
                        );
                    }
                }

                // Re-initialize the resource select after content is loaded
                initResourceSelect(
                    "associatedResources",
                    "selectedResourcesPills",
                    "selectedResourcesWarning",
                    6,
                    "selectAllResourcesBtn",
                    "clearAllResourcesBtn",
                );
                console.log(
                    "[Filter Update DEBUG] Resources reloaded successfully via fetch",
                );
            })
            .catch((err) => {
                console.error(
                    "[Filter Update DEBUG] Resources reload failed:",
                    err,
                );
            });
    } else {
        console.warn("[Filter Update DEBUG] Resources container not found");
    }

    // Reload prompts
    const promptsContainer = document.getElementById("associatedPrompts");
    if (promptsContainer) {
        const promptsUrl = gatewayIdParam
            ? `${window.ROOT_PATH}/admin/prompts/partial?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
            : `${window.ROOT_PATH}/admin/prompts/partial?page=1&per_page=50&render=selector`;

        if (window.htmx) {
            htmx.ajax("GET", promptsUrl, {
                target: "#associatedPrompts",
                swap: "innerHTML",
            }).then(() => {
                // Re-initialize the prompt select after content is loaded
                initPromptSelect(
                    "associatedPrompts",
                    "selectedPromptsPills",
                    "selectedPromptsWarning",
                    6,
                    "selectAllPromptsBtn",
                    "clearAllPromptsBtn",
                );
            });
        }
    }
}

// Initialize gateway select on page load
document.addEventListener("DOMContentLoaded", function () {
    // Initialize for the create server form
    if (document.getElementById("associatedGateways")) {
        initGatewaySelect(
            "associatedGateways",
            "selectedGatewayPills",
            "selectedGatewayWarning",
            12,
            "selectAllGatewayBtn",
            "clearAllGatewayBtn",
            "searchGateways",
        );
    }
});

// ===================================================================
// INACTIVE ITEMS HANDLING
// ===================================================================

function toggleInactiveItems(type) {
    const checkbox = safeGetElement(`show-inactive-${type}`);
    if (!checkbox) {
        return;
    }

    // Update URL in address bar (no navigation) so state is reflected
    try {
        const urlObj = new URL(window.location);
        if (checkbox.checked) {
            urlObj.searchParams.set("include_inactive", "true");
        } else {
            urlObj.searchParams.delete("include_inactive");
        }
        // Use replaceState to avoid adding history entries for every toggle
        window.history.replaceState({}, document.title, urlObj.toString());
    } catch (e) {
        // ignore (shouldn't happen)
    }

    // Try to find the HTMX container that loads this entity's partial
    // Prefer an element with hx-get containing the admin partial endpoint
    const selector = `[hx-get*="/admin/${type}/partial"]`;
    let container = document.querySelector(selector);

    // Fallback to conventional id naming used in templates
    if (!container) {
        const fallbackId =
            type === "tools" ? "tools-table" : `${type}-list-container`;
        container = document.getElementById(fallbackId);
    }

    if (!container) {
        // If we couldn't find a container, fallback to full-page reload
        const fallbackUrl = new URL(window.location);
        if (checkbox.checked) {
            fallbackUrl.searchParams.set("include_inactive", "true");
        } else {
            fallbackUrl.searchParams.delete("include_inactive");
        }
        window.location = fallbackUrl;
        return;
    }

    // Build request URL based on the hx-get attribute or container id
    const base =
        container.getAttribute("hx-get") ||
        container.getAttribute("data-hx-get") ||
        "";
    let reqUrl;
    try {
        if (base) {
            // base may already include query params; construct URL and set include_inactive/page
            reqUrl = new URL(base, window.location.origin);
            // reset to page 1 when toggling
            reqUrl.searchParams.set("page", "1");
            if (checkbox.checked) {
                reqUrl.searchParams.set("include_inactive", "true");
            } else {
                reqUrl.searchParams.delete("include_inactive");
            }
        } else {
            // construct from known pattern
            const root = window.ROOT_PATH || "";
            reqUrl = new URL(
                `${root}/admin/${type}/partial?page=1&per_page=50`,
                window.location.origin,
            );
            if (checkbox.checked) {
                reqUrl.searchParams.set("include_inactive", "true");
            }
        }
    } catch (e) {
        // fallback to full reload
        const fallbackUrl2 = new URL(window.location);
        if (checkbox.checked) {
            fallbackUrl2.searchParams.set("include_inactive", "true");
        } else {
            fallbackUrl2.searchParams.delete("include_inactive");
        }
        window.location = fallbackUrl2;
        return;
    }

    // Determine indicator selector
    const indicator =
        container.getAttribute("hx-indicator") || `#${type}-loading`;

    // Use HTMX to reload only the container (outerHTML swap)
    if (window.htmx && typeof window.htmx.ajax === "function") {
        try {
            window.htmx.ajax("GET", reqUrl.toString(), {
                target: container,
                swap: "outerHTML",
                indicator,
            });
            return;
        } catch (e) {
            // fall through to full reload
        }
    }

    // Last resort: reload page with param
    const finalUrl = new URL(window.location);
    if (checkbox.checked) {
        finalUrl.searchParams.set("include_inactive", "true");
    } else {
        finalUrl.searchParams.delete("include_inactive");
    }
    window.location = finalUrl;
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
                            "mt-1 px-1.5 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 text-gray-700 dark:text-gray-300 dark:border-gray-700 dark:focus:border-indigo-400 dark:focus:ring-indigo-400";

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
                            : "mt-1 px-1.5 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 text-gray-700 dark:text-gray-300 dark:border-gray-700 dark:focus:border-indigo-400 dark:focus:ring-indigo-400";

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
async function testPrompt(promptId) {
    try {
        console.log(`Testing prompt ID: ${promptId}`);

        // Debouncing to prevent rapid clicking
        const now = Date.now();
        const lastRequest = promptTestState.lastRequestTime.get(promptId) || 0;
        const timeSinceLastRequest = now - lastRequest;
        const debounceDelay = 1000;

        if (timeSinceLastRequest < debounceDelay) {
            console.log(`Prompt ${promptId} test request debounced`);
            return;
        }

        // Check if modal is already active
        if (AppState.isModalActive("prompt-test-modal")) {
            console.warn("Prompt test modal is already active");
            return;
        }

        // Update button state
        const testButton = document.querySelector(
            `[onclick*="testPrompt('${promptId}')"]`,
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
        promptTestState.lastRequestTime.set(promptId, now);
        promptTestState.activeRequests.add(promptId);

        // Fetch prompt details
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000);

        try {
            // Fetch prompt details from the prompts endpoint (view mode)
            const response = await fetch(
                `${window.ROOT_PATH}/admin/prompts/${encodeURIComponent(promptId)}`,
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
                titleElement.textContent = `Test Prompt: ${prompt.name || promptId}`;
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
            `[onclick*="testPrompt('${promptId}')"]`,
        );
        if (testButton) {
            testButton.disabled = false;
            testButton.textContent = "Test";
            testButton.classList.remove("opacity-50", "cursor-not-allowed");
        }

        // Clean up state
        promptTestState.activeRequests.delete(promptId);
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
            "mt-1 px-1.5 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-300";

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
        const contentType = formData.get("content_type") || "application/json";

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

        // Process body based on content type
        let processedBody = bodyValidation.value;
        if (
            contentType === "application/x-www-form-urlencoded" &&
            bodyValidation.value &&
            typeof bodyValidation.value === "object"
        ) {
            // Convert JSON object to URL-encoded string
            const params = new URLSearchParams();
            Object.entries(bodyValidation.value).forEach(([key, value]) => {
                params.append(key, String(value));
            });
            processedBody = params.toString();
        }

        const payload = {
            base_url: urlValidation.value,
            method,
            path,
            headers: headersValidation.value,
            body: processedBody,
            content_type: contentType,
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
              <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">Visibility:</span>
                <div class="mt-1 tool-visibility text-sm"></div>
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
            <div>
              <strong class="text-gray-700 dark:text-gray-300">Output Schema:</strong>
              <pre class="mt-1 bg-gray-100 p-3 rounded text-xs dark:bg-gray-800 dark:text-gray-200 tool-output-schema overflow-x-auto"></pre>
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
          <!-- Metadata Section -->
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
                <span class="font-medium text-gray-600 dark:text-gray-400">Created From IP:</span>
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
                <span class="font-medium text-gray-600 dark:text-gray-400">Modified From IP:</span>
                <span class="ml-2 modified-from"></span>
              </div>
              <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Modified Via:</span>
                <span class="ml-2 metadata-modified-via"></span>
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
            setTextSafely(".tool-visibility", tool.visibility);

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
            setTextSafely(
                ".tool-output-schema",
                JSON.stringify(tool.outputSchema || {}, null, 2),
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
        // NOTE: OAuth config assembly is now handled by the backend (mcpgateway/admin.py)
        // The backend assembles individual form fields into oauth_config with proper field names
        // and supports DCR (Dynamic Client Registration) when client_id/client_secret are empty
        //
        // Leaving this commented for reference:
        // const authType = formData.get("auth_type");
        // if (authType === "oauth") {
        //     ... backend handles this now ...
        // }
        const authType = formData.get("auth_type");
        if (authType !== "oauth") {
            formData.set("oauth_grant_type", "");
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
        formData.append("visibility", formData.get("visibility"));
        const teamId = new URL(window.location.href).searchParams.get(
            "team_id",
        );
        teamId && formData.append("team_id", teamId);
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
        formData.append("visibility", formData.get("visibility"));
        const teamId = new URL(window.location.href).searchParams.get(
            "team_id",
        );
        teamId && formData.append("team_id", teamId);
        const response = await fetch(`${window.ROOT_PATH}/admin/prompts`, {
            method: "POST",
            body: formData,
        });
        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to add prompt");
        }

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
    // Add team_id from URL if present (like handleEditToolFormSubmit)
    const teamId = new URL(window.location.href).searchParams.get("team_id");
    if (teamId) {
        formData.set("team_id", teamId);
    }

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

// Handle Add A2A Form Submit
async function handleA2AFormSubmit(e) {
    e.preventDefault();

    const form = e.target;
    const formData = new FormData(form);
    const status = safeGetElement("a2aFormError");
    const loading = safeGetElement("add-a2a-loading");

    try {
        // Basic validation
        const name = formData.get("name");
        const nameValidation = validateInputName(name, "A2A Agent");
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

        const isInactiveCheckedBool = isInactiveChecked("a2a-agents");
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

        const authType = formData.get("auth_type");
        if (authType !== "oauth") {
            formData.set("oauth_grant_type", "");
        }

        // ✅ Ensure visibility is captured from checked radio button
        // formData.set("visibility", visibility);
        formData.append("visibility", formData.get("visibility"));
        const teamId = new URL(window.location.href).searchParams.get(
            "team_id",
        );
        teamId && formData.append("team_id", teamId);

        // Submit to backend
        // specifically log agentType only
        console.log("agentType:", formData.get("agentType"));

        const response = await fetch(`${window.ROOT_PATH}/admin/a2a`, {
            method: "POST",
            body: formData,
        });

        const result = await response.json();

        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to add A2A Agent.");
        } else {
            // Success redirect
            const searchParams = new URLSearchParams();
            if (isInactiveCheckedBool) {
                searchParams.set("include_inactive", "true");
            }
            if (teamId) {
                searchParams.set("team_id", teamId);
            }

            const queryString = searchParams.toString();
            const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#a2a-agents`;
            window.location.href = redirectUrl;
        }
    } catch (error) {
        console.error("Add A2A Agent Error:", error);
        if (status) {
            status.textContent = error.message || "An error occurred.";
            status.classList.add("error-status");
        }
        showErrorMessage(error.message); // global popup/snackbar if available
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
        if (window.outputSchemaEditor) {
            window.outputSchemaEditor.save();
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
        if (window.editToolOutputSchemaEditor) {
            window.editToolOutputSchemaEditor.save();
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

// Handle Gateway Edit Form
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
        // NOTE: OAuth config assembly is now handled by the backend (mcpgateway/admin.py)
        // The backend assembles individual form fields into oauth_config with proper field names
        // and supports DCR (Dynamic Client Registration) when client_id/client_secret are empty
        //
        // Leaving this commented for reference:
        // const authType = formData.get("auth_type");
        // if (authType === "oauth") {
        //     ... backend handles this now ...
        // }
        const authType = formData.get("auth_type");
        if (authType !== "oauth") {
            formData.set("oauth_grant_type", "");
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

// Handle A2A Agent Edit Form
async function handleEditA2AAgentFormSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);

    console.log("Edit A2A Agent Form Details: ");
    console.log(
        JSON.stringify(Object.fromEntries(formData.entries()), null, 2),
    );

    try {
        // Validate form inputs
        const name = formData.get("name");
        const url = formData.get("endpoint_url");
        console.log("Original A2A URL: ", url);
        const nameValidation = validateInputName(name, "a2a_agent");
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
        // NOTE: OAuth config assembly is now handled by the backend (mcpgateway/admin.py)
        // The backend assembles individual form fields into oauth_config with proper field names
        // and supports DCR (Dynamic Client Registration) when client_id/client_secret are empty
        //
        // Leaving this commented for reference:
        // const authType = formData.get("auth_type");
        // if (authType === "oauth") {
        //     ... backend handles this now ...
        // }

        const authType = formData.get("auth_type");
        if (authType !== "oauth") {
            formData.set("oauth_grant_type", "");
        }

        const isInactiveCheckedBool = isInactiveChecked("a2a-agents");
        formData.append("is_inactive_checked", isInactiveCheckedBool);
        // Submit via fetch
        const response = await fetch(form.action, {
            method: "POST",
            body: formData,
        });
        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to edit a2a agent");
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
        const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#a2a-agents`;
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

/* global Alpine, htmx */
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
            id: "output-schema-editor",
            mode: "application/json",
            varName: "outputSchemaEditor",
        },
        {
            id: "edit-tool-output-schema",
            mode: "application/json",
            varName: "editToolOutputSchemaEditor",
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

    // Add Server form
    initToolSelect(
        "associatedTools",
        "selectedToolsPills",
        "selectedToolsWarning",
        6,
        "selectAllToolsBtn",
        "clearAllToolsBtn",
    );

    initResourceSelect(
        "associatedResources",
        "selectedResourcesPills",
        "selectedResourcesWarning",
        10,
        "selectAllResourcesBtn",
        "clearAllResourcesBtn",
    );

    initPromptSelect(
        "associatedPrompts",
        "selectedPromptsPills",
        "selectedPromptsWarning",
        8,
        "selectAllPromptsBtn",
        "clearAllPromptsBtn",
    );

    // Edit Server form
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
    console.log("🎯 Setting up event listeners...");

    setupTabNavigation();
    setupHTMXHooks();
    console.log("✅ HTMX hooks registered");
    setupAuthenticationToggles();
    setupFormHandlers();
    setupSchemaModeHandlers();
    setupIntegrationTypeHandlers();
    console.log("✅ All event listeners initialized");
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
        "plugins",
        "logs",
        "export-import",
        "version-info",
    ];

    tabs.forEach((tabName) => {
        // Suppress warnings for optional tabs that might not be enabled
        const optionalTabs = [
            "roots",
            "logs",
            "export-import",
            "version-info",
            "plugins",
        ];
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

        // Gateway Add Form auth fields

        {
            id: "auth-type-gw",
            basicId: "auth-basic-fields-gw",
            bearerId: "auth-bearer-fields-gw",
            headersId: "auth-headers-fields-gw",
        },

        // A2A Add Form auth fields

        {
            id: "auth-type-a2a",
            basicId: "auth-basic-fields-a2a",
            bearerId: "auth-bearer-fields-a2a",
            headersId: "auth-headers-fields-a2a",
        },

        // Gateway Edit Form auth fields

        {
            id: "auth-type-gw-edit",
            basicId: "auth-basic-fields-gw-edit",
            bearerId: "auth-bearer-fields-gw-edit",
            headersId: "auth-headers-fields-gw-edit",
            oauthId: "auth-oauth-fields-gw-edit",
        },

        // A2A Edit Form auth fields

        {
            id: "auth-type-a2a-edit",
            basicId: "auth-basic-fields-a2a-edit",
            bearerId: "auth-bearer-fields-a2a-edit",
            headersId: "auth-headers-fields-a2a-edit",
            oauthId: "auth-oauth-fields-a2a-edit",
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

        // Add OAuth grant type change handler for Gateway
        const oauthGrantTypeField = safeGetElement("oauth-grant-type-gw");
        if (oauthGrantTypeField) {
            oauthGrantTypeField.addEventListener(
                "change",
                handleOAuthGrantTypeChange,
            );
        }
    }

    // Add A2A Form
    const a2aForm = safeGetElement("add-a2a-form");

    if (a2aForm) {
        a2aForm.addEventListener("submit", handleA2AFormSubmit);

        // Add OAuth authentication type change handler
        const authTypeField = safeGetElement("auth-type-a2a");
        if (authTypeField) {
            authTypeField.addEventListener("change", handleAuthTypeChange);
        }

        const oauthGrantTypeField = safeGetElement("oauth-grant-type-a2a");
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
    // Checkpoint commented
    /*
    const editOAuthGrantTypeField = safeGetElement("oauth-grant-type-gw-edit");
    if (editOAuthGrantTypeField) {
        editOAuthGrantTypeField.addEventListener(
            "change",
            handleEditOAuthGrantTypeChange,
        );
    }

    */

    // Checkpoint Started
    ["oauth-grant-type-gw-edit", "oauth-grant-type-a2a-edit"].forEach((id) => {
        const field = safeGetElement(id);
        if (field) {
            field.addEventListener("change", handleEditOAuthGrantTypeChange);
        }
    });
    // Checkpoint Ended

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

    const passthroughButton = safeGetElement("add-passthrough-btn");
    if (passthroughButton) {
        passthroughButton.addEventListener("click", handleAddPassthrough);
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

    const editA2AAgentForm = safeGetElement("edit-a2a-agent-form");
    if (editA2AAgentForm) {
        editA2AAgentForm.addEventListener(
            "submit",
            handleEditA2AAgentFormSubmit,
        );
        editA2AAgentForm.addEventListener("click", () => {
            if (getComputedStyle(editA2AAgentForm).display !== "none") {
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
    // Tools search - server-side search
    const searchTools = safeGetElement("searchTools", true);
    if (searchTools) {
        let searchTimeout;
        searchTools.addEventListener("input", function () {
            const searchTerm = this.value;

            // Clear previous timeout
            if (searchTimeout) {
                clearTimeout(searchTimeout);
            }

            // Debounce search to avoid too many API calls
            searchTimeout = setTimeout(() => {
                serverSideToolSearch(searchTerm);
            }, 300);
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

    // Prompts search (server-side)
    const searchPrompts = safeGetElement("searchPrompts", true);
    if (searchPrompts) {
        let promptSearchTimeout;
        searchPrompts.addEventListener("input", function () {
            const searchTerm = this.value;
            if (promptSearchTimeout) {
                clearTimeout(promptSearchTimeout);
            }
            promptSearchTimeout = setTimeout(() => {
                serverSidePromptSearch(searchTerm);
            }, 300);
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

    // Detect form type based on the element ID
    // e.g., "auth-type-a2a" or "auth-type-gw"
    const isA2A = this.id.includes("a2a");
    const prefix = isA2A ? "a2a" : "gw";

    // Select the correct field groups dynamically
    const basicFields = safeGetElement(`auth-basic-fields-${prefix}`);
    const bearerFields = safeGetElement(`auth-bearer-fields-${prefix}`);
    const headersFields = safeGetElement(`auth-headers-fields-${prefix}`);
    const oauthFields = safeGetElement(`auth-oauth-fields-${prefix}`);

    // Hide all auth sections first
    [basicFields, bearerFields, headersFields, oauthFields].forEach(
        (section) => {
            if (section) {
                section.style.display = "none";
            }
        },
    );

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
            // "none" or unknown type — keep everything hidden
            break;
    }
}

function handleOAuthGrantTypeChange() {
    const grantType = this.value;

    // Detect form type (a2a or gw) from the triggering element ID
    const isA2A = this.id.includes("a2a");
    const prefix = isA2A ? "a2a" : "gw";

    // Select the correct fields dynamically based on prefix
    const authCodeFields = safeGetElement(`oauth-auth-code-fields-${prefix}`);
    const usernameField = safeGetElement(`oauth-username-field-${prefix}`);
    const passwordField = safeGetElement(`oauth-password-field-${prefix}`);

    // Handle Authorization Code flow
    if (authCodeFields) {
        if (grantType === "authorization_code") {
            authCodeFields.style.display = "block";

            // Make URL fields required
            const requiredFields =
                authCodeFields.querySelectorAll('input[type="url"]');
            requiredFields.forEach((field) => (field.required = true));

            console.log(
                `(${prefix.toUpperCase()}) Authorization Code flow selected - fields are now required`,
            );
        } else {
            authCodeFields.style.display = "none";

            // Remove required validation
            const requiredFields =
                authCodeFields.querySelectorAll('input[type="url"]');
            requiredFields.forEach((field) => (field.required = false));
        }
    }

    // Handle Password Grant flow
    if (usernameField && passwordField) {
        const usernameInput = safeGetElement(`oauth-username-${prefix}`);
        const passwordInput = safeGetElement(`oauth-password-${prefix}`);

        if (grantType === "password") {
            usernameField.style.display = "block";
            passwordField.style.display = "block";

            if (usernameInput) {
                usernameInput.required = true;
            }
            if (passwordInput) {
                passwordInput.required = true;
            }

            console.log(
                `(${prefix.toUpperCase()}) Password grant flow selected - username and password are now required`,
            );
        } else {
            usernameField.style.display = "none";
            passwordField.style.display = "none";

            if (usernameInput) {
                usernameInput.required = false;
            }
            if (passwordInput) {
                passwordInput.required = false;
            }
        }
    }
}

function handleEditOAuthGrantTypeChange() {
    const grantType = this.value;

    // Detect prefix dynamically (supports both gw-edit and a2a-edit)
    const id = this.id || "";
    const prefix = id.includes("a2a") ? "a2a-edit" : "gw-edit";

    const authCodeFields = safeGetElement(`oauth-auth-code-fields-${prefix}`);
    const usernameField = safeGetElement(`oauth-username-field-${prefix}`);
    const passwordField = safeGetElement(`oauth-password-field-${prefix}`);

    // === Handle Authorization Code grant ===
    if (authCodeFields) {
        const urlInputs = authCodeFields.querySelectorAll('input[type="url"]');
        if (grantType === "authorization_code") {
            authCodeFields.style.display = "block";
            urlInputs.forEach((field) => (field.required = true));
            console.log(
                `Authorization Code flow selected (${prefix}) - additional fields are now required`,
            );
        } else {
            authCodeFields.style.display = "none";
            urlInputs.forEach((field) => (field.required = false));
        }
    }

    // === Handle Password grant ===
    if (usernameField && passwordField) {
        const usernameInput = safeGetElement(`oauth-username-${prefix}`);
        const passwordInput = safeGetElement(`oauth-password-${prefix}`);

        if (grantType === "password") {
            usernameField.style.display = "block";
            passwordField.style.display = "block";

            if (usernameInput) {
                usernameInput.required = true;
            }
            if (passwordInput) {
                passwordInput.required = true;
            }

            console.log(
                `Password grant flow selected (${prefix}) - username and password are now required`,
            );
        } else {
            usernameField.style.display = "none";
            passwordField.style.display = "none";

            if (usernameInput) {
                usernameInput.required = false;
            }
            if (passwordInput) {
                passwordInput.required = false;
            }
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
window.viewAgent = viewAgent;
window.editA2AAgent = editA2AAgent;
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
                            MCP_AUTH: "Bearer <your-token-here>",
                            MCP_SERVER_URL: `${baseUrl}/servers/${server.id}`,
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
        "a2a-agents",
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

    if (typeof initializeTeamScopingMonitor === "function") {
        initializeTeamScopingMonitor();
    }
});

// Expose tag filtering functions to global scope
window.filterEntitiesByTags = filterEntitiesByTags;
window.clearTagFilter = clearTagFilter;
window.updateAvailableTags = updateAvailableTags;

// ===================================================================
// MULTI-HEADER AUTHENTICATION MANAGEMENT
// ===================================================================

/**
 * Toggle masking for sensitive text inputs (passwords, tokens, headers)
 * @param {HTMLElement|string} inputOrId - Target input element or its ID
 * @param {HTMLElement} button - Button triggering the toggle
 */
function toggleInputMask(inputOrId, button) {
    const input =
        typeof inputOrId === "string"
            ? document.getElementById(inputOrId)
            : inputOrId;

    if (!input || !button) {
        return;
    }

    const revealing = input.type === "password";
    if (revealing) {
        input.type = "text";
        if (input.dataset.isMasked === "true") {
            input.value = input.dataset.realValue ?? "";
        }
    } else {
        input.type = "password";
        if (input.dataset.isMasked === "true") {
            input.value = MASKED_AUTH_VALUE;
        }
    }

    const label = input.getAttribute("data-sensitive-label") || "value";
    button.textContent = revealing ? "Hide" : "Show";
    button.setAttribute("aria-pressed", revealing ? "true" : "false");
    button.setAttribute(
        "aria-label",
        `${revealing ? "Hide" : "Show"} ${label}`.trim(),
    );

    const container = input.closest('[id^="auth-headers-container"]');
    if (container) {
        updateAuthHeadersJSON(container.id);
    }
}

window.toggleInputMask = toggleInputMask;

/**
 * Global counter for unique header IDs
 */
let headerCounter = 0;

/**
 * Add a new authentication header row to the specified container
 * @param {string} containerId - ID of the container to add the header row to
 */
function addAuthHeader(containerId, options = {}) {
    const container = document.getElementById(containerId);
    if (!container) {
        console.error(`Container with ID ${containerId} not found`);
        return;
    }

    const headerId = `auth-header-${++headerCounter}`;
    const valueInputId = `${headerId}-value`;

    const headerRow = document.createElement("div");
    headerRow.className = "flex items-center space-x-2";
    headerRow.id = headerId;
    if (options.existing) {
        headerRow.dataset.existing = "true";
    }

    headerRow.innerHTML = `
        <div class="flex-1">
            <input
                type="text"
                placeholder="Header Key (e.g., X-API-Key)"
                class="auth-header-key block w-full px-1.5 rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:placeholder-gray-300 dark:text-gray-300 text-sm"
                oninput="updateAuthHeadersJSON('${containerId}')"
            />
        </div>
        <div class="flex-1">
            <div class="relative">
                <input
                    type="password"
                    id="${valueInputId}"
                    placeholder="Header Value"
                    data-sensitive-label="header value"
                    class="auth-header-value block w-full px-1.5 rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:placeholder-gray-300 dark:text-gray-300 text-sm pr-16"
                    oninput="updateAuthHeadersJSON('${containerId}')"
                />
                <button
                    type="button"
                    class="absolute inset-y-0 right-0 flex items-center px-2 text-xs font-medium text-indigo-600 hover:text-indigo-800 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 dark:text-indigo-300"
                    onclick="toggleInputMask('${valueInputId}', this)"
                    aria-pressed="false"
                    aria-label="Show header value"
                >
                    Show
                </button>
            </div>
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

    const keyInput = headerRow.querySelector(".auth-header-key");
    const valueInput = headerRow.querySelector(".auth-header-value");
    if (keyInput) {
        keyInput.value = options.key ?? "";
    }
    if (valueInput) {
        if (options.isMasked) {
            valueInput.value = MASKED_AUTH_VALUE;
            valueInput.dataset.isMasked = "true";
            valueInput.dataset.realValue = options.value ?? "";
        } else {
            valueInput.value = options.value ?? "";
            if (valueInput.dataset) {
                delete valueInput.dataset.isMasked;
                delete valueInput.dataset.realValue;
            }
        }
    }

    updateAuthHeadersJSON(containerId);

    const shouldFocus = options.focus !== false;
    // Focus on the key input of the new header
    if (shouldFocus && keyInput) {
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
            const rawValue = valueInput.value;

            // Skip completely empty rows
            if (!key && (!rawValue || !rawValue.trim())) {
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

            if (valueInput.dataset.isMasked === "true") {
                const storedValue = valueInput.dataset.realValue ?? "";
                if (
                    rawValue !== MASKED_AUTH_VALUE &&
                    rawValue !== storedValue
                ) {
                    delete valueInput.dataset.isMasked;
                    delete valueInput.dataset.realValue;
                }
            }

            const finalValue =
                valueInput.dataset.isMasked === "true"
                    ? MASKED_AUTH_VALUE
                    : rawValue.trim();

            headers.push({
                key,
                value: finalValue, // Allow empty values
            });
        }
    });

    // Find the corresponding JSON input field
    let jsonInput = null;
    if (containerId === "auth-headers-container") {
        jsonInput = document.getElementById("auth-headers-json");
    } else if (containerId === "auth-headers-container-gw") {
        jsonInput = document.getElementById("auth-headers-json-gw");
    } else if (containerId === "auth-headers-container-a2a") {
        jsonInput = document.getElementById("auth-headers-json-a2a");
    } else if (containerId === "edit-auth-headers-container") {
        jsonInput = document.getElementById("edit-auth-headers-json");
    } else if (containerId === "auth-headers-container-gw-edit") {
        jsonInput = document.getElementById("auth-headers-json-gw-edit");
    } else if (containerId === "auth-headers-container-a2a-edit") {
        jsonInput = document.getElementById("auth-headers-json-a2a-edit");
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
function loadAuthHeaders(containerId, headers, options = {}) {
    const container = document.getElementById(containerId);
    if (!container) {
        return;
    }

    const jsonInput = (() => {
        if (containerId === "auth-headers-container") {
            return document.getElementById("auth-headers-json");
        }
        if (containerId === "auth-headers-container-gw") {
            return document.getElementById("auth-headers-json-gw");
        }
        if (containerId === "auth-headers-container-a2a") {
            return document.getElementById("auth-headers-json-a2a");
        }
        if (containerId === "edit-auth-headers-container") {
            return document.getElementById("edit-auth-headers-json");
        }
        if (containerId === "auth-headers-container-gw-edit") {
            return document.getElementById("auth-headers-json-gw-edit");
        }
        if (containerId === "auth-headers-container-a2a-edit") {
            return document.getElementById("auth-headers-json-a2a-edit");
        }
        return null;
    })();

    container.innerHTML = "";

    if (!headers || !Array.isArray(headers) || headers.length === 0) {
        if (jsonInput) {
            jsonInput.value = "";
        }
        return;
    }

    const shouldMaskValues = options.maskValues === true;

    headers.forEach((header) => {
        if (!header || !header.key) {
            return;
        }
        const value = typeof header.value === "string" ? header.value : "";
        addAuthHeader(containerId, {
            key: header.key,
            value,
            existing: true,
            isMasked: shouldMaskValues,
            focus: false,
        });
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
            { method: "POST" },
        );

        const result = await response.json();

        if (response.ok) {
            // Success
            button.textContent = "✅ Tools Fetched";
            button.className =
                "inline-block bg-green-600 hover:bg-green-700 text-white px-3 py-1 rounded text-sm mr-2";

            // Show success message - API returns {success: true, message: "..."}
            const message =
                result.message ||
                `Successfully fetched tools from ${gatewayName}`;
            showSuccessMessage(message);

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
            throw new Error(`Failed to load tokens: (${response.status})`);
        }

        const data = await response.json();
        displayTokensList(data.tokens);
    } catch (error) {
        console.error("Error loading tokens:", error);
        tokensList.innerHTML =
            '<div class="text-red-500">Error loading tokens: ' +
            escapeHtml(error.message) +
            "</div>";
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
        const createdText = token.created_at
            ? new Date(token.created_at).toLocaleDateString()
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
                                <span class="font-medium">Created:</span> ${createdText}
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
 * Get the currently selected team ID from the team selector
 */
function getCurrentTeamId() {
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
    const teamId = urlParams.get("teamid");

    if (!teamId || teamId === "" || teamId === "all") {
        return null;
    }

    return teamId;
}

/**
 * Get the currently selected team name from Alpine.js team selector
 * @returns {string|null} Team name or null if not found
 */
function getCurrentTeamName() {
    const currentTeamId = getCurrentTeamId();

    if (!currentTeamId) {
        return null;
    }

    // Method 1: Try from window.USERTEAMSDATA (most reliable)
    if (window.USERTEAMSDATA && Array.isArray(window.USERTEAMSDATA)) {
        const teamObj = window.USERTEAMSDATA.find(
            (t) => t.id === currentTeamId,
        );
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
                (t) => t.id === currentTeamId,
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
}

/**
 * Update the team scoping warning/info visibility based on team selection
 */
function updateTeamScopingWarning() {
    const warningDiv = document.getElementById("team-scoping-warning");
    const infoDiv = document.getElementById("team-scoping-info");
    const teamNameSpan = document.getElementById("selected-team-name");

    if (!warningDiv || !infoDiv) {
        return;
    }

    const currentTeamId = getCurrentTeamId();

    if (!currentTeamId) {
        // Show warning when "All Teams" is selected
        warningDiv.classList.remove("hidden");
        infoDiv.classList.add("hidden");
    } else {
        // Hide warning and show info when a specific team is selected
        warningDiv.classList.add("hidden");
        infoDiv.classList.remove("hidden");

        // Get team name to display
        const teamName = getCurrentTeamName() || currentTeamId;
        if (teamNameSpan) {
            teamNameSpan.textContent = teamName;
        }
    }
}

/**
 * Monitor team selection changes using Alpine.js watcher
 */
function initializeTeamScopingMonitor() {
    // Use Alpine.js $watch to monitor team selection changes
    document.addEventListener("alpine:init", () => {
        const teamSelector = document.querySelector('[x-data*="selectedTeam"]');
        if (teamSelector && window.Alpine) {
            // The Alpine component will notify us of changes
            const checkInterval = setInterval(() => {
                updateTeamScopingWarning();
            }, 500); // Check every 500ms

            // Store interval ID for cleanup if needed
            window._teamMonitorInterval = checkInterval;
        }
    });

    // Also update when tokens tab is shown
    document.addEventListener("DOMContentLoaded", () => {
        const tokensTab = document.querySelector('a[href="#tokens"]');
        if (tokensTab) {
            tokensTab.addEventListener("click", () => {
                setTimeout(updateTeamScopingWarning, 100);
            });
        }
    });
}

/**
 * Set up create token form handling
 */
function setupCreateTokenForm() {
    const form = safeGetElement("create-token-form");
    if (!form) {
        return;
    }

    // Update team scoping warning/info display
    updateTeamScopingWarning();

    form.addEventListener("submit", async (e) => {
        e.preventDefault();

        // User can create public-only tokens in that context
        await createToken(form);
    });
}

/**
 * Create a new API token
 */
// Create a new API token
async function createToken(form) {
    const formData = new FormData(form);
    const submitButton = form.querySelector('button[type="submit"]');
    const originalText = submitButton.textContent;

    try {
        submitButton.textContent = "Creating...";
        submitButton.disabled = true;

        // Get current team ID (null means "All Teams" = public-only token)
        const currentTeamId = getCurrentTeamId();

        // Build request payload
        const payload = {
            name: formData.get("name"),
            description: formData.get("description") || null,
            expires_in_days: formData.get("expires_in_days")
                ? parseInt(formData.get("expires_in_days"))
                : null,
            tags: [],
            team_id: currentTeamId || null, // null = public-only token
        };

        // Add scoping if provided
        const scope = {};

        if (formData.get("server_id")) {
            scope.server_id = formData.get("server_id");
        }

        if (formData.get("ip_restrictions")) {
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

        scope.time_restrictions = {};
        scope.usage_limits = {};
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
                error.detail || `Failed to create token (${response.status})`,
            );
        }

        const result = await response.json();
        showTokenCreatedModal(result);
        form.reset();
        await loadTokensList();

        // Show appropriate success message
        const tokenType = currentTeamId ? "team-scoped" : "public-only";
        showNotification(`${tokenType} token created successfully!`, "success");
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
    console.log("MY TOKEN GENERATED:", token);

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

// Plugin management functions
function initializePluginFunctions() {
    // Populate hook, tag, and author filters on page load
    window.populatePluginFilters = function () {
        const cards = document.querySelectorAll(".plugin-card");
        const hookSet = new Set();
        const tagSet = new Set();
        const authorSet = new Set();

        cards.forEach((card) => {
            const hooks = card.dataset.hooks
                ? card.dataset.hooks.split(",")
                : [];
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

        const hookFilter = document.getElementById("plugin-hook-filter");
        const tagFilter = document.getElementById("plugin-tag-filter");
        const authorFilter = document.getElementById("plugin-author-filter");

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
                option.textContent =
                    author.charAt(0).toUpperCase() + author.slice(1);
                authorFilter.appendChild(option);
            });
        }
    };

    // Filter plugins based on search and filters
    window.filterPlugins = function () {
        const searchInput = document.getElementById("plugin-search");
        const modeFilter = document.getElementById("plugin-mode-filter");
        const statusFilter = document.getElementById("plugin-status-filter");
        const hookFilter = document.getElementById("plugin-hook-filter");
        const tagFilter = document.getElementById("plugin-tag-filter");
        const authorFilter = document.getElementById("plugin-author-filter");

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
            const name = card.dataset.name
                ? card.dataset.name.toLowerCase()
                : "";
            const description = card.dataset.description
                ? card.dataset.description.toLowerCase()
                : "";
            const author = card.dataset.author
                ? card.dataset.author.toLowerCase()
                : "";
            const mode = card.dataset.mode;
            const status = card.dataset.status;
            const hooks = card.dataset.hooks
                ? card.dataset.hooks.split(",")
                : [];
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
    window.filterByHook = function (hook) {
        const hookFilter = document.getElementById("plugin-hook-filter");
        if (hookFilter) {
            hookFilter.value = hook;
            window.filterPlugins();
            hookFilter.scrollIntoView({ behavior: "smooth", block: "nearest" });

            // Update visual highlighting
            updateBadgeHighlighting("hook", hook);
        }
    };

    // Filter by tag when clicking on tag
    window.filterByTag = function (tag) {
        const tagFilter = document.getElementById("plugin-tag-filter");
        if (tagFilter) {
            tagFilter.value = tag;
            window.filterPlugins();
            tagFilter.scrollIntoView({ behavior: "smooth", block: "nearest" });

            // Update visual highlighting
            updateBadgeHighlighting("tag", tag);
        }
    };

    // Filter by author when clicking on author
    window.filterByAuthor = function (author) {
        const authorFilter = document.getElementById("plugin-author-filter");
        if (authorFilter) {
            // Convert to lowercase to match data-author attribute
            authorFilter.value = author.toLowerCase();
            window.filterPlugins();
            authorFilter.scrollIntoView({
                behavior: "smooth",
                block: "nearest",
            });

            // Update visual highlighting
            updateBadgeHighlighting("author", author);
        }
    };

    // Helper function to update badge highlighting
    function updateBadgeHighlighting(type, value) {
        // Define selectors for each type
        const selectors = {
            hook: "[onclick^='filterByHook']",
            tag: "[onclick^='filterByTag']",
            author: "[onclick^='filterByAuthor']",
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
                    "hover:bg-gray-200",
                );
                badge.classList.remove(
                    "dark:bg-gray-700",
                    "dark:text-gray-200",
                    "dark:hover:bg-gray-600",
                );
                badge.classList.add(
                    "bg-indigo-100",
                    "text-indigo-800",
                    "border",
                    "border-indigo-300",
                );
                badge.classList.add(
                    "dark:bg-indigo-900",
                    "dark:text-indigo-200",
                    "dark:border-indigo-700",
                );
            } else if (!isAllBadge) {
                // Reset to default styling for non-All badges
                badge.classList.remove(
                    "bg-indigo-100",
                    "text-indigo-800",
                    "border",
                    "border-indigo-300",
                );
                badge.classList.remove(
                    "dark:bg-indigo-900",
                    "dark:text-indigo-200",
                    "dark:border-indigo-700",
                );
                badge.classList.add(
                    "bg-gray-100",
                    "text-gray-800",
                    "hover:bg-gray-200",
                );
                badge.classList.add(
                    "dark:bg-gray-700",
                    "dark:text-gray-200",
                    "dark:hover:bg-gray-600",
                );
            }
        });
    }

    // Show plugin details modal
    window.showPluginDetails = async function (pluginName) {
        const modal = document.getElementById("plugin-details-modal");
        const modalName = document.getElementById("modal-plugin-name");
        const modalContent = document.getElementById("modal-plugin-content");

        if (!modal || !modalName || !modalContent) {
            console.error("Plugin details modal elements not found");
            return;
        }

        // Show loading state
        modalName.textContent = pluginName;
        modalContent.innerHTML =
            '<div class="text-center py-4">Loading...</div>';
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
                },
            );

            if (!response.ok) {
                throw new Error(
                    `Failed to load plugin details: ${response.statusText}`,
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
                                        `<span class="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">${hook}</span>`,
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
                                        `<span class="px-2 py-1 text-xs bg-gray-100 text-gray-700 rounded">${tag}</span>`,
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
    window.closePluginDetails = function () {
        const modal = document.getElementById("plugin-details-modal");
        if (modal) {
            modal.classList.add("hidden");
        }
    };
}

// Initialize plugin functions if plugins panel exists
if (document.getElementById("plugins-panel")) {
    initializePluginFunctions();
    // Populate filter dropdowns on initial load
    if (window.populatePluginFilters) {
        window.populatePluginFilters();
    }
}

// Expose plugin functions to global scope
window.initializePluginFunctions = initializePluginFunctions;

// ===================================================================
// MCP REGISTRY MODAL FUNCTIONS
// ===================================================================

// Define modal functions in global scope for MCP Registry
window.showApiKeyModal = function (serverId, serverName, serverUrl) {
    const modal = document.getElementById("api-key-modal");
    if (modal) {
        document.getElementById("modal-server-id").value = serverId;
        document.getElementById("modal-server-name").textContent = serverName;
        document.getElementById("modal-custom-name").placeholder = serverName;
        modal.classList.remove("hidden");
    }
};

window.closeApiKeyModal = function () {
    const modal = document.getElementById("api-key-modal");
    if (modal) {
        modal.classList.add("hidden");
    }
    const form = document.getElementById("api-key-form");
    if (form) {
        form.reset();
    }
};

window.submitApiKeyForm = function (event) {
    event.preventDefault();
    const serverId = document.getElementById("modal-server-id").value;
    const customName = document.getElementById("modal-custom-name").value;
    const apiKey = document.getElementById("modal-api-key").value;

    // Prepare request data
    const requestData = {};
    if (customName) {
        requestData.name = customName;
    }
    if (apiKey) {
        requestData.api_key = apiKey;
    }

    const rootPath = window.ROOT_PATH || "";

    // Send registration request
    fetch(`${rootPath}/admin/mcp-registry/${serverId}/register`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            Authorization: "Bearer " + (getCookie("jwt_token") || ""),
        },
        body: JSON.stringify(requestData),
    })
        .then((response) => response.json())
        .then((data) => {
            if (data.success) {
                window.closeApiKeyModal();
                // Reload the catalog
                if (window.htmx && window.htmx.ajax) {
                    window.htmx.ajax(
                        "GET",
                        `${rootPath}/admin/mcp-registry/partial`,
                        {
                            target: "#mcp-registry-content",
                            swap: "innerHTML",
                        },
                    );
                }
            } else {
                alert("Registration failed: " + (data.error || data.message));
            }
        })
        .catch((error) => {
            alert("Error registering server: " + error);
        });
};

// gRPC Services Functions

/**
 * Toggle visibility of TLS certificate/key fields based on TLS checkbox
 */
window.toggleGrpcTlsFields = function () {
    const tlsEnabled =
        document.getElementById("grpc-tls-enabled")?.checked || false;
    const certField = document.getElementById("grpc-tls-cert-field");
    const keyField = document.getElementById("grpc-tls-key-field");

    if (tlsEnabled) {
        certField?.classList.remove("hidden");
        keyField?.classList.remove("hidden");
    } else {
        certField?.classList.add("hidden");
        keyField?.classList.add("hidden");
    }
};

/**
 * View gRPC service methods in a modal or alert
 * @param {string} serviceId - The gRPC service ID
 */
window.viewGrpcMethods = function (serviceId) {
    const rootPath = window.ROOT_PATH || "";

    fetch(`${rootPath}/grpc/${serviceId}/methods`, {
        method: "GET",
        headers: {
            "Content-Type": "application/json",
            Authorization: "Bearer " + (getCookie("jwt_token") || ""),
        },
    })
        .then((response) => response.json())
        .then((data) => {
            if (data.methods && data.methods.length > 0) {
                let methodsList = "gRPC Methods:\n\n";
                data.methods.forEach((method) => {
                    methodsList += `${method.full_name}\n`;
                    methodsList += `  Input: ${method.input_type || "N/A"}\n`;
                    methodsList += `  Output: ${method.output_type || "N/A"}\n`;
                    if (method.client_streaming || method.server_streaming) {
                        methodsList += `  Streaming: ${method.client_streaming ? "Client" : ""} ${method.server_streaming ? "Server" : ""}\n`;
                    }
                    methodsList += "\n";
                });
                alert(methodsList);
            } else {
                alert(
                    "No methods discovered for this service. Try re-reflecting the service.",
                );
            }
        })
        .catch((error) => {
            alert("Error fetching methods: " + error);
        });
};

// Helper function to get cookie if not already defined
if (typeof window.getCookie === "undefined") {
    window.getCookie = function (name) {
        const value = "; " + document.cookie;
        const parts = value.split("; " + name + "=");
        if (parts.length === 2) {
            return parts.pop().split(";").shift();
        }
        return "";
    };
}

// ==================== LLM CHAT FUNCTIONALITY ====================

// State management for LLM chat
const llmChatState = {
    selectedServerId: null,
    selectedServerName: null,
    isConnected: false,
    userId: null,
    messageHistory: [],
    connectedTools: [],
    toolCount: 0,
    serverToken: "",
};

/**
 * Initialize LLM Chat when tab is shown
 */
function initializeLLMChat() {
    console.log("Initializing LLM Chat...");

    // Generate or retrieve user ID
    llmChatState.userId = generateUserId();

    // Load servers if not already loaded
    const serversList = document.getElementById("llm-chat-servers-list");
    if (serversList && serversList.children.length <= 1) {
        loadVirtualServersForChat();
    }

    // Initialize chat input resize behavior
    initializeChatInputResize();
}

/**
 * Generate a unique user ID for the session
 */
function generateUserId() {
    // Check if user ID exists in session storage
    let userId = sessionStorage.getItem("llm_chat_user_id");
    if (!userId) {
        // Generate a unique ID
        userId = `user_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        sessionStorage.setItem("llm_chat_user_id", userId);
    }
    return userId;
}

/**
 * Load virtual servers for chat
 */
async function loadVirtualServersForChat() {
    const serversList = document.getElementById("llm-chat-servers-list");
    if (!serversList) {
        return;
    }

    serversList.innerHTML =
        '<div class="flex items-center justify-center py-8"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div></div>';

    try {
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/servers`,
            {
                method: "GET",
                credentials: "same-origin",
            },
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        const servers = Array.isArray(data) ? data : data.servers || [];

        if (servers.length === 0) {
            serversList.innerHTML =
                '<div class="text-center text-gray-500 dark:text-gray-400 text-sm py-4">No virtual servers available</div>';
            return;
        }

        // Render server list with "Requires Token" pill and tooltip
        serversList.innerHTML = servers
            .map((server) => {
                const toolCount = (server.associatedTools || []).length;
                const isActive = server.isActive;
                const visibility = server.visibility || "public";
                const requiresToken =
                    visibility === "team" || visibility === "private";

                // Generate appropriate tooltip message
                const tooltipMessage = requiresToken
                    ? server.visibility === "team"
                        ? "This is a team-level server. An access token will be required to connect."
                        : "This is a private server. An access token will be required to connect."
                    : "";

                return `
                <div class="server-item relative p-3 border rounded-lg cursor-pointer transition-colors
                    ${llmChatState.selectedServerId === server.id ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-900" : "border-gray-200 dark:border-gray-600 hover:border-indigo-300 dark:hover:border-indigo-600"}
                    ${!isActive ? "opacity-50" : ""}"
                    onclick="selectServerForChat('${server.id}', '${escapeHtml(server.name)}', ${isActive}, ${requiresToken}, '${visibility}')"
                    style="position: relative;">

                    ${
                        requiresToken
                            ? `
                        <div class="tooltip"
                        style="position: absolute; left: 50%; transform: translateX(-50%); bottom: 120%; margin-bottom: 8px;
                                background-color: #6B7280; color: white; font-size: 10px; border-radius: 4px;
                                padding: 4px 20px; /* More horizontal width */
                                opacity: 0; visibility: hidden; transition: opacity 0.2s ease-in;
                                z-index: 1000;"> <!-- Added higher z-index to ensure it's above other elements -->
                        ${tooltipMessage}
                        <div style="position: absolute; left: 50%; bottom: -5px; transform: translateX(-50%);
                                    width: 0; height: 0; border-left: 5px solid transparent;
                                    border-right: 5px solid transparent; border-top: 5px solid #6B7280;"></div>
                        </div>`
                            : ""
                    }

                    <div class="flex justify-between items-start">
                        <div class="flex-1 min-w-0">
                            <h4 class="text-sm font-medium text-gray-900 dark:text-white truncate">${escapeHtml(server.name)}</h4>
                            <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">${toolCount} tool${toolCount !== 1 ? "s" : ""}</p>
                        </div>
                        <div class="flex flex-col items-end gap-1">
                            ${!isActive ? '<span class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800">Inactive</span>' : ""}
                            ${requiresToken ? '<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-yellow-100 text-yellow-800">Requires Token</span>' : ""}
                        </div>
                    </div>
                    ${server.description ? `<p class="text-xs text-gray-600 dark:text-gray-400 mt-2 line-clamp-2">${escapeHtml(server.description)}</p>` : ""}
                </div>
            `;
            })
            .join("");

        // Add hover event to show tooltip immediately on hover
        const serverItems = document.querySelectorAll(".server-item");
        serverItems.forEach((item) => {
            const tooltip = item.querySelector(".tooltip");
            item.addEventListener("mouseenter", () => {
                if (tooltip) {
                    tooltip.style.opacity = "1"; // Make tooltip visible
                    tooltip.style.visibility = "visible"; // Show tooltip immediately
                }
            });
            item.addEventListener("mouseleave", () => {
                if (tooltip) {
                    tooltip.style.opacity = "0"; // Hide tooltip
                    tooltip.style.visibility = "hidden"; // Keep tooltip hidden when not hovering
                }
            });
        });
    } catch (error) {
        console.error("Error loading servers for chat:", error);
        serversList.innerHTML =
            '<div class="text-center text-red-600 dark:text-red-400 text-sm py-4">Failed to load servers: ' +
            escapeHtml(error.message) +
            "</div>";
    }
}

/**
 * Select a server for chat
 */
// eslint-disable-next-line no-unused-vars
async function selectServerForChat(
    serverId,
    serverName,
    isActive,
    requiresToken,
    serverVisibility,
) {
    if (!isActive) {
        showErrorMessage(
            "This server is inactive. Please select an active server.",
        );
        return;
    }

    // If server requires token (team or private), prompt for it
    if (requiresToken) {
        // Create context-aware message based on visibility level
        const visibilityMessage =
            serverVisibility === "team"
                ? "This is a team-level server that requires authentication for access."
                : "This is a private server that requires authentication for access.";

        const token = prompt(
            `Authentication Required\n\n${visibilityMessage}\n\nPlease enter the access token for "${serverName}":`,
        );

        if (token === null) {
            // User cancelled
            return;
        }

        // Store the token temporarily for this server
        llmChatState.serverToken = token || "";
    } else {
        // Public server - no token needed
        llmChatState.serverToken = "";
    }

    // Update state
    llmChatState.selectedServerId = serverId;
    llmChatState.selectedServerName = serverName;

    // Update UI to show selected server
    const serverItems = document.querySelectorAll(".server-item");
    serverItems.forEach((item) => {
        if (item.onclick.toString().includes(serverId)) {
            item.classList.add(
                "border-indigo-500",
                "bg-indigo-50",
                "dark:bg-indigo-900",
            );
            item.classList.remove("border-gray-200", "dark:border-gray-600");
        } else {
            item.classList.remove(
                "border-indigo-500",
                "bg-indigo-50",
                "dark:bg-indigo-900",
            );
            item.classList.add("border-gray-200", "dark:border-gray-600");
        }
    });

    // Show and expand LLM configuration
    const configForm = document.getElementById("llm-config-form");
    if (configForm && configForm.classList.contains("hidden")) {
        toggleLLMConfig();
    }

    // Enable connect button if provider is selected
    updateConnectButtonState();

    console.log(
        `Selected server: ${serverName} (${serverId}), Visibility: ${serverVisibility}, Token: ${requiresToken ? "Required" : "Not required"}`,
    );
}

/**
 * Toggle LLM configuration visibility
 */
function toggleLLMConfig() {
    const configForm = document.getElementById("llm-config-form");
    const chevron = document.getElementById("llm-config-chevron");

    if (configForm && chevron) {
        configForm.classList.toggle("hidden");
        chevron.classList.toggle("rotate-180");
    }
}

/**
 * Handle LLM provider selection change
 */
// eslint-disable-next-line no-unused-vars
function handleLLMProviderChange() {
    const provider = document.getElementById("llm-provider").value;
    const azureFields = document.getElementById("azure-openai-fields");
    const openaiFields = document.getElementById("openai-fields");
    const anthropicFields = document.getElementById("anthropic-fields");
    const awsBedrockFields = document.getElementById("aws-bedrock-fields");
    const watsonxFields = document.getElementById("watsonx-fields");
    const ollamaFields = document.getElementById("ollama-fields");

    // Hide all fields first
    azureFields.classList.add("hidden");
    openaiFields.classList.add("hidden");
    anthropicFields.classList.add("hidden");
    awsBedrockFields.classList.add("hidden");
    watsonxFields.classList.add("hidden");
    ollamaFields.classList.add("hidden");

    // Show relevant fields
    if (provider === "azure_openai") {
        azureFields.classList.remove("hidden");
    } else if (provider === "openai") {
        openaiFields.classList.remove("hidden");
    } else if (provider === "anthropic") {
        anthropicFields.classList.remove("hidden");
    } else if (provider === "aws_bedrock") {
        awsBedrockFields.classList.remove("hidden");
    } else if (provider === "watsonx") {
        watsonxFields.classList.remove("hidden");
    } else if (provider === "ollama") {
        ollamaFields.classList.remove("hidden");
    }

    // Update connect button state
    updateConnectButtonState();
}

/**
 * Update connect button state
 */
function updateConnectButtonState() {
    const connectBtn = document.getElementById("llm-connect-btn");
    const provider = document.getElementById("llm-provider").value;
    const hasServer = llmChatState.selectedServerId !== null;

    if (connectBtn) {
        connectBtn.disabled = !hasServer || !provider;
    }
}

/**
 * Connect to LLM chat
 */
// eslint-disable-next-line no-unused-vars
async function connectLLMChat() {
    if (!llmChatState.selectedServerId) {
        showErrorMessage("Please select a virtual server first");
        return;
    }

    const provider = document.getElementById("llm-provider").value;
    if (!provider) {
        showErrorMessage("Please select an LLM provider");
        return;
    }

    // Clear previous chat history before connecting
    clearChatMessages();
    llmChatState.messageHistory = [];

    // Show loading state
    const connectBtn = document.getElementById("llm-connect-btn");
    const originalText = connectBtn.textContent;
    connectBtn.textContent = "Connecting...";
    connectBtn.disabled = true;

    // Clear any previous error messages
    const statusDiv = document.getElementById("llm-config-status");
    if (statusDiv) {
        statusDiv.classList.add("hidden");
    }

    try {
        // Build LLM config
        const llmConfig = buildLLMConfig(provider);

        // Build server URL
        const serverUrl = `${location.protocol}//${location.hostname}${![80, 443].includes(location.port) ? `:${location.port}` : ""}/servers/${llmChatState.selectedServerId}/mcp`;
        console.log("Selected server URL:", serverUrl);

        // Use the stored server token (empty string for public servers)
        const jwtToken = llmChatState.serverToken || "";

        const payload = {
            user_id: llmChatState.userId,
            server: {
                url: serverUrl,
                transport: "streamable_http",
                auth_token: jwtToken,
            },
            llm: llmConfig,
            streaming: true,
        };

        console.log("Connecting with payload:", {
            ...payload,
            server: { ...payload.server, auth_token: "REDACTED" },
        });

        // Make connection request with timeout handling
        let response;
        try {
            response = await fetchWithTimeout(
                `${window.ROOT_PATH}/llmchat/connect`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        Authorization: `Bearer ${jwtToken}`,
                    },
                    body: JSON.stringify(payload),
                    credentials: "same-origin",
                },
                30000,
            );
        } catch (fetchError) {
            // Handle network/timeout errors
            if (
                fetchError.name === "AbortError" ||
                fetchError.message.includes("timeout")
            ) {
                throw new Error(
                    "Connection timed out. Please check if the server is responsive and try again.",
                );
            }
            throw new Error(`Network error: ${fetchError.message}`);
        }

        // Handle HTTP errors - extract backend error message
        if (!response.ok) {
            let errorMessage = `Connection failed (HTTP ${response.status})`;

            try {
                const errorData = await response.json();
                if (errorData.detail) {
                    // Use the backend error message directly
                    errorMessage = errorData.detail;
                }
            } catch (parseError) {
                console.warn("Could not parse error response:", parseError);
                // Keep generic error message
            }

            throw new Error(errorMessage);
        }

        // Parse successful response
        let result;
        try {
            result = await response.json();
        } catch (parseError) {
            throw new Error(
                "Failed to parse server response. Please try again.",
            );
        }

        console.log("Connection successful:", result);

        // Update state
        llmChatState.isConnected = true;
        llmChatState.connectedTools = result.tools || [];
        llmChatState.toolCount = result.tool_count || 0;

        // Update UI
        showConnectionSuccess();

        // Clear welcome message and show chat input
        const welcomeMsg = document.getElementById("chat-welcome-message");
        if (welcomeMsg) {
            welcomeMsg.remove();
        }

        const chatInput = document.getElementById("chat-input-container");
        if (chatInput) {
            chatInput.classList.remove("hidden");
            document.getElementById("chat-input").disabled = false;
            document.getElementById("chat-send-btn").disabled = false;
            document.getElementById("chat-input").focus();
        }

        // Hide connect button, show disconnect button
        const disconnectBtn = document.getElementById("llm-disconnect-btn");
        if (connectBtn) {
            connectBtn.classList.add("hidden");
        }
        if (disconnectBtn) {
            disconnectBtn.classList.remove("hidden");
        }

        // Auto-collapse configuration
        const configForm = document.getElementById("llm-config-form");
        const chevron = document.getElementById("llm-config-chevron");
        if (configForm && !configForm.classList.contains("hidden")) {
            configForm.classList.add("hidden");
            chevron.classList.remove("rotate-180");
        }

        // Show success message
        showNotification(
            `Connected to ${llmChatState.selectedServerName}`,
            "success",
        );
    } catch (error) {
        console.error("Connection error:", error);
        // Display the backend error message to the user
        showConnectionError(error.message);
    } finally {
        connectBtn.textContent = originalText;
        connectBtn.disabled = false;
    }
}

/**
 * Build LLM config object from form inputs
 */
function buildLLMConfig(provider) {
    const config = {
        provider,
        config: {},
    };

    if (provider === "azure_openai") {
        const apiKey = document.getElementById("azure-api-key").value.trim();
        const endpoint = document.getElementById("azure-endpoint").value.trim();
        const deployment = document
            .getElementById("azure-deployment")
            .value.trim();
        const apiVersion = document
            .getElementById("azure-api-version")
            .value.trim();
        const temperature = document
            .getElementById("azure-temperature")
            .value.trim();

        // Only include non-empty values
        if (apiKey) {
            config.config.api_key = apiKey;
        }
        if (endpoint) {
            config.config.azure_endpoint = endpoint;
        }
        if (deployment) {
            config.config.azure_deployment = deployment;
        }
        if (apiVersion) {
            config.config.api_version = apiVersion;
        }
        if (temperature) {
            config.config.temperature = parseFloat(temperature);
        }
    } else if (provider === "openai") {
        const apiKey = document.getElementById("openai-api-key").value.trim();
        const model = document.getElementById("openai-model").value.trim();
        const baseUrl = document.getElementById("openai-base-url").value.trim();
        const temperature = document
            .getElementById("openai-temperature")
            .value.trim();

        // Only include non-empty values
        if (apiKey) {
            config.config.api_key = apiKey;
        }
        if (model) {
            config.config.model = model;
        }
        if (baseUrl) {
            config.config.base_url = baseUrl;
        }
        if (temperature) {
            config.config.temperature = parseFloat(temperature);
        }
    } else if (provider === "anthropic") {
        const apiKey = document
            .getElementById("anthropic-api-key")
            .value.trim();
        const model = document.getElementById("anthropic-model").value.trim();
        const temperature = document
            .getElementById("anthropic-temperature")
            .value.trim();
        const maxTokens = document
            .getElementById("anthropic-max-tokens")
            .value.trim();

        // Only include non-empty values
        if (apiKey) {
            config.config.api_key = apiKey;
        }
        if (model) {
            config.config.model = model;
        }
        if (temperature) {
            config.config.temperature = parseFloat(temperature);
        }
        if (maxTokens) {
            config.config.max_tokens = parseInt(maxTokens, 10);
        }
    } else if (provider === "aws_bedrock") {
        const modelId = document
            .getElementById("aws-bedrock-model-id")
            .value.trim();
        const region = document
            .getElementById("aws-bedrock-region")
            .value.trim();
        const accessKeyId = document
            .getElementById("aws-access-key-id")
            .value.trim();
        const secretAccessKey = document
            .getElementById("aws-secret-access-key")
            .value.trim();
        const temperature = document
            .getElementById("aws-bedrock-temperature")
            .value.trim();
        const maxTokens = document
            .getElementById("aws-bedrock-max-tokens")
            .value.trim();

        // Only include non-empty values
        if (modelId) {
            config.config.model_id = modelId;
        }
        if (region) {
            config.config.region_name = region;
        }
        if (accessKeyId) {
            config.config.aws_access_key_id = accessKeyId;
        }
        if (secretAccessKey) {
            config.config.aws_secret_access_key = secretAccessKey;
        }
        if (temperature) {
            config.config.temperature = parseFloat(temperature);
        }
        if (maxTokens) {
            config.config.max_tokens = parseInt(maxTokens, 10);
        }
    } else if (provider === "watsonx") {
        const apiKey = document.getElementById("watsonx-api-key").value.trim();
        const url = document.getElementById("watsonx-url").value.trim();
        const projectId = document
            .getElementById("watsonx-project-id")
            .value.trim();
        const modelId = document
            .getElementById("watsonx-model-id")
            .value.trim();
        const temperature = document
            .getElementById("watsonx-temperature")
            .value.trim();
        const maxNewTokens = document
            .getElementById("watsonx-max-new-tokens")
            .value.trim();
        const decodingMethod = document
            .getElementById("watsonx-decoding-method")
            .value.trim();

        // Only include non-empty values
        if (apiKey) {
            config.config.apikey = apiKey;
        }
        if (url) {
            config.config.url = url;
        }
        if (projectId) {
            config.config.projectid = projectId;
        }
        if (modelId) {
            config.config.modelid = modelId;
        }
        if (temperature) {
            config.config.temperature = parseFloat(temperature);
        }
        if (maxNewTokens) {
            config.config.maxnewtokens = parseInt(maxNewTokens, 10);
        }
        if (decodingMethod) {
            config.config.decodingmethod = decodingMethod;
        }
    } else if (provider === "ollama") {
        const model = document.getElementById("ollama-model").value.trim();
        const baseUrl = document.getElementById("ollama-base-url").value.trim();
        const temperature = document
            .getElementById("ollama-temperature")
            .value.trim();

        // Only include non-empty values
        if (model) {
            config.config.model = model;
        }
        if (baseUrl) {
            config.config.base_url = baseUrl;
        }
        if (temperature) {
            config.config.temperature = parseFloat(temperature);
        }
    }

    return config;
}

/**
 * Copy environment variables to clipboard for the specified provider
 */
// eslint-disable-next-line no-unused-vars
async function copyEnvVariables(provider) {
    const envVariables = {
        azure: `AZURE_OPENAI_API_KEY=<api_key>
AZURE_OPENAI_ENDPOINT=https://test-url.openai.azure.com
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_DEPLOYMENT=gpt4o
AZURE_OPENAI_MODEL=gpt4o`,

        openai: `OPENAI_API_KEY=<api_key>
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1`,

        anthropic: `ANTHROPIC_API_KEY=<api_key>
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
ANTHROPIC_MAX_TOKENS=4096`,

        aws_bedrock: `AWS_BEDROCK_MODEL_ID=anthropic.claude-v2
AWS_BEDROCK_REGION=us-east-1
AWS_ACCESS_KEY_ID=<optional>
AWS_SECRET_ACCESS_KEY=<optional>`,

        watsonx: `WATSONX_APIKEY=apikey
WATSONX_URL=https://us-south.ml.cloud.ibm.com
WATSONX_PROJECT_ID=project-id
WATSONX_MODEL_ID=ibm/granite-13b-chat-v2
WATSONX_TEMPERATURE=0.7`,

        ollama: `OLLAMA_MODEL=llama3
OLLAMA_BASE_URL=http://localhost:11434`,
    };

    const variables = envVariables[provider];

    if (!variables) {
        console.error("Unknown provider:", provider);
        showErrorMessage("Unknown provider");
        return;
    }

    try {
        // Try modern clipboard API first
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(variables);
            showCopySuccessNotification(provider);
        } else {
            // Fallback for older browsers
            const textArea = document.createElement("textarea");
            textArea.value = variables;
            textArea.style.position = "fixed";
            textArea.style.left = "-999999px";
            textArea.style.top = "-999999px";
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();

            try {
                const successful = document.execCommand("copy");
                if (successful) {
                    showCopySuccessNotification(provider);
                } else {
                    throw new Error("Copy command failed");
                }
            } catch (err) {
                console.error("Fallback copy failed:", err);
                showErrorMessage("Failed to copy to clipboard");
            } finally {
                document.body.removeChild(textArea);
            }
        }
    } catch (err) {
        console.error("Failed to copy environment variables:", err);
        showErrorMessage("Failed to copy to clipboard. Please copy manually.");
    }
}

/**
 * Show success notification when environment variables are copied
 */
function showCopySuccessNotification(provider) {
    const providerNames = {
        azure: "Azure OpenAI",
        ollama: "Ollama",
        openai: "OpenAI",
    };

    const displayName = providerNames[provider] || provider;

    // Create notification element
    const notification = document.createElement("div");
    notification.className = "fixed top-4 right-4 z-50 animate-fade-in";
    notification.innerHTML = `
        <div class="bg-green-500 text-white px-4 py-3 rounded-lg shadow-lg flex items-center space-x-2">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
            </svg>
            <span class="font-medium">${displayName} variables copied!</span>
        </div>
    `;

    document.body.appendChild(notification);

    // Remove notification after 3 seconds
    setTimeout(() => {
        notification.style.opacity = "0";
        notification.style.transition = "opacity 0.3s ease-out";
        setTimeout(() => {
            if (notification.parentNode) {
                document.body.removeChild(notification);
            }
        }, 300);
    }, 3000);
}

/**
 * Show connection success
 */
function showConnectionSuccess() {
    // Update connection status badge
    const statusBadge = document.getElementById("llm-connection-status");
    if (statusBadge) {
        statusBadge.classList.remove("hidden");
    }

    // Show active tools badge using data from connection response
    const toolsBadge = document.getElementById("llm-active-tools-badge");
    const toolCountSpan = document.getElementById("llm-tool-count");
    const toolListDiv = document.getElementById("llm-tool-list");

    if (toolsBadge && toolCountSpan && toolListDiv) {
        const tools = llmChatState.connectedTools || [];
        const count = tools.length;

        toolCountSpan.textContent = `${count} tool${count !== 1 ? "s" : ""}`;

        // Clear and populate tool list with individual pills
        toolListDiv.innerHTML = "";

        if (count > 0) {
            tools.forEach((toolName, index) => {
                const pill = document.createElement("span");
                pill.className =
                    "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/40 dark:to-indigo-900/40 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-700 shadow-sm hover:shadow-md transition-all hover:scale-105";

                // Tool icon
                const icon = document.createElementNS(
                    "http://www.w3.org/2000/svg",
                    "svg",
                );
                icon.setAttribute("class", "w-3.5 h-3.5");
                icon.setAttribute("fill", "none");
                icon.setAttribute("stroke", "currentColor");
                icon.setAttribute("viewBox", "0 0 24 24");
                icon.innerHTML =
                    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"></path>';

                const text = document.createElement("span");
                text.textContent = toolName;

                pill.appendChild(icon);
                pill.appendChild(text);
                toolListDiv.appendChild(pill);
            });
        } else {
            const emptyMsg = document.createElement("div");
            emptyMsg.className = "text-center py-4";
            emptyMsg.innerHTML = `
      <svg class="w-8 h-8 mx-auto text-gray-400 dark:text-gray-600 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"></path>
      </svg>
      <p class="text-xs text-gray-500 dark:text-gray-400">No tools available for this server</p>
    `;
            toolListDiv.appendChild(emptyMsg);
        }

        toolsBadge.classList.remove("hidden");
    }

    // Hide connect button, show disconnect button
    const connectBtn = document.getElementById("llm-connect-btn");
    const disconnectBtn = document.getElementById("llm-disconnect-btn");
    if (connectBtn) {
        connectBtn.classList.add("hidden");
    }
    if (disconnectBtn) {
        disconnectBtn.classList.remove("hidden");
    }

    // Auto-collapse configuration
    const configForm = document.getElementById("llm-config-form");
    const chevron = document.getElementById("llm-config-chevron");
    if (configForm && !configForm.classList.contains("hidden")) {
        configForm.classList.add("hidden");
        chevron.classList.remove("rotate-180");
    }

    // Show success message
    showNotification(
        `Connected to ${llmChatState.selectedServerName}`,
        "success",
    );
}

/**
 * Show connection error
 */
/**
 * Display connection error with proper formatting
 */
function showConnectionError(message) {
    const statusDiv = document.getElementById("llm-config-status");
    if (statusDiv) {
        statusDiv.className =
            "text-sm text-red-600 dark:text-red-400 p-3 bg-red-50 dark:bg-red-900/20 rounded border border-red-200 dark:border-red-700";
        statusDiv.innerHTML = `
            <div class="flex items-start gap-2">
                <svg class="w-5 h-5 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
                </svg>
                <div class="flex-1">
                    <strong class="font-semibold">Connection Failed</strong>
                    <p class="mt-1">${escapeHtml(message)}</p>
                </div>
            </div>
        `;
        statusDiv.classList.remove("hidden");
    }
}

/**
 * Disconnect from LLM chat
 */
// eslint-disable-next-line no-unused-vars
async function disconnectLLMChat() {
    if (!llmChatState.isConnected) {
        console.warn("No active connection to disconnect");
        return;
    }

    const disconnectBtn = document.getElementById("llm-disconnect-btn");
    const originalText = disconnectBtn.textContent;
    disconnectBtn.textContent = "Disconnecting...";
    disconnectBtn.disabled = true;

    try {
        const jwtToken = getCookie("jwt_token");

        // Attempt graceful disconnection
        let response;
        let backendError = null;

        try {
            response = await fetchWithTimeout(
                `${window.ROOT_PATH}/llmchat/disconnect`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        Authorization: `Bearer ${jwtToken}`,
                    },
                    body: JSON.stringify({
                        user_id: llmChatState.userId,
                    }),
                    credentials: "same-origin",
                },
                10000,
            ); // Shorter timeout for disconnect
        } catch (fetchError) {
            console.warn(
                "Disconnect request failed, cleaning up locally:",
                fetchError,
            );
            backendError = fetchError.message;
            // Continue with local cleanup even if server request fails
        }

        // Parse response if available
        let disconnectStatus = "unknown";
        if (response) {
            if (response.ok) {
                try {
                    const result = await response.json();
                    disconnectStatus = result.status || "disconnected";

                    if (result.warning) {
                        console.warn("Disconnect warning:", result.warning);
                    }
                } catch (parseError) {
                    console.warn("Could not parse disconnect response");
                }
            } else {
                // Extract backend error message
                try {
                    const errorData = await response.json();
                    if (errorData.detail) {
                        backendError = errorData.detail;
                    }
                } catch (parseError) {
                    backendError = `HTTP ${response.status}`;
                }
                console.warn(
                    `Disconnect returned error: ${backendError}, cleaning up locally`,
                );
            }
        }

        // Always update local state regardless of server response
        llmChatState.isConnected = false;
        llmChatState.messageHistory = [];
        llmChatState.connectedTools = [];
        llmChatState.toolCount = 0;
        llmChatState.serverToken = "";

        // Update UI
        const statusBadge = document.getElementById("llm-connection-status");
        if (statusBadge) {
            statusBadge.classList.add("hidden");
        }

        const toolsBadge = document.getElementById("llm-active-tools-badge");
        if (toolsBadge) {
            toolsBadge.classList.add("hidden");
        }

        const connectBtn = document.getElementById("llm-connect-btn");
        if (connectBtn) {
            connectBtn.classList.remove("hidden");
        }
        if (disconnectBtn) {
            disconnectBtn.classList.add("hidden");
        }

        // Hide chat input
        const chatInput = document.getElementById("chat-input-container");
        if (chatInput) {
            chatInput.classList.add("hidden");
            document.getElementById("chat-input").disabled = true;
            document.getElementById("chat-send-btn").disabled = true;
        }

        // Clear messages
        clearChatMessages();

        // Show appropriate notification
        if (backendError) {
            showNotification(
                `Disconnected (server error: ${backendError})`,
                "warning",
            );
        } else if (disconnectStatus === "no_active_session") {
            showNotification("Already disconnected", "info");
        } else if (disconnectStatus === "disconnected_with_errors") {
            showNotification("Disconnected (with cleanup warnings)", "warning");
        } else {
            showNotification("Disconnected successfully", "info");
        }
    } catch (error) {
        console.error("Unexpected disconnection error:", error);

        // Force cleanup even on error
        llmChatState.isConnected = false;
        llmChatState.messageHistory = [];
        llmChatState.connectedTools = [];
        llmChatState.toolCount = 0;

        // Display backend error if available
        showErrorMessage(
            `Disconnection error: ${error.message}. Local session cleared.`,
        );
    } finally {
        disconnectBtn.textContent = originalText;
        disconnectBtn.disabled = false;
    }
}

/**
 * Send chat message
 */
async function sendChatMessage(event) {
    event.preventDefault();

    const input = document.getElementById("chat-input");
    const message = input.value.trim();

    if (!message) {
        return;
    }

    if (!llmChatState.isConnected) {
        showErrorMessage("Please connect to a server first");
        return;
    }

    // Add user message to chat
    appendChatMessage("user", message);

    // Clear input
    input.value = "";
    input.style.height = "auto";

    // Disable input while processing
    input.disabled = true;
    document.getElementById("chat-send-btn").disabled = true;

    let assistantMsgId = null;
    let reader = null;

    try {
        const jwtToken = getCookie("jwt_token");

        // Create assistant message placeholder for streaming
        assistantMsgId = appendChatMessage("assistant", "", true);

        // Make request with timeout handling
        let response;
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 120000); // 2 minute timeout

            response = await fetch(`${window.ROOT_PATH}/llmchat/chat`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${jwtToken}`,
                },
                body: JSON.stringify({
                    user_id: llmChatState.userId,
                    message,
                    streaming: true,
                }),
                credentials: "same-origin",
                signal: controller.signal,
            });

            clearTimeout(timeoutId);
        } catch (fetchError) {
            if (fetchError.name === "AbortError") {
                throw new Error(
                    "Request timed out. The response took too long.",
                );
            }
            throw new Error(`Network error: ${fetchError.message}`);
        }

        // Handle HTTP errors - extract backend error message
        if (!response.ok) {
            let errorMessage = `Chat request failed (HTTP ${response.status})`;

            try {
                const errorData = await response.json();
                if (errorData.detail) {
                    // Use backend error message directly
                    errorMessage = errorData.detail;
                }
            } catch (parseError) {
                console.warn("Could not parse error response");
            }

            throw new Error(errorMessage);
        }

        // Validate response has body stream
        if (!response.body) {
            throw new Error("No response stream received from server");
        }

        // Handle streaming SSE response
        reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let accumulatedText = "";
        let hasReceivedData = false;

        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) {
                    break;
                }

                hasReceivedData = true;
                buffer += decoder.decode(value, { stream: true });

                // Process complete SSE events (separated by blank line)
                let boundary;
                while ((boundary = buffer.indexOf("\n\n")) !== -1) {
                    const rawEvent = buffer.slice(0, boundary).trim();
                    buffer = buffer.slice(boundary + 2);

                    if (!rawEvent) {
                        continue;
                    }

                    let eventType = "message";
                    const dataLines = [];

                    for (const line of rawEvent.split("\n")) {
                        if (line.startsWith("event:")) {
                            eventType = line.slice(6).trim();
                        } else if (line.startsWith("data:")) {
                            dataLines.push(line.slice(5).trim());
                        }
                    }

                    let payload = {};
                    const dataStr = dataLines.join("");

                    try {
                        payload = dataStr ? JSON.parse(dataStr) : {};
                    } catch (parseError) {
                        console.warn(
                            "Failed to parse SSE data:",
                            dataStr,
                            parseError,
                        );
                        continue;
                    }

                    // Handle different event types
                    try {
                        switch (eventType) {
                            case "token": {
                                const text = payload.content;
                                if (text) {
                                    accumulatedText += text;
                                    // Process and render with think tags
                                    updateChatMessageWithThinkTags(
                                        assistantMsgId,
                                        accumulatedText,
                                    );
                                }
                                break;
                            }
                            case "tool_start":
                            case "tool_end":
                            case "tool_error":
                                addToolEventToCard(
                                    assistantMsgId,
                                    eventType,
                                    payload,
                                );
                                break;

                            case "final":
                                if (payload.tool_used) {
                                    setToolUsedSummary(
                                        assistantMsgId,
                                        true,
                                        payload.tools,
                                    );
                                }
                                setTimeout(scrollChatToBottom, 50);
                                break;

                            case "error": {
                                // Handle server-sent error events from backend
                                const errorMsg =
                                    payload.error ||
                                    "An error occurred during processing";
                                const isRecoverable =
                                    payload.recoverable !== false;

                                // Display error in the assistant message
                                updateChatMessage(
                                    assistantMsgId,
                                    `❌ Error: ${errorMsg}`,
                                );

                                if (!isRecoverable) {
                                    // For non-recoverable errors, suggest reconnection
                                    appendChatMessage(
                                        "system",
                                        "⚠️ Connection lost. Please reconnect to continue.",
                                    );
                                    llmChatState.isConnected = false;

                                    // Update UI to show disconnected state
                                    const connectBtn =
                                        document.getElementById(
                                            "llm-connect-btn",
                                        );
                                    const disconnectBtn =
                                        document.getElementById(
                                            "llm-disconnect-btn",
                                        );
                                    if (connectBtn) {
                                        connectBtn.classList.remove("hidden");
                                    }
                                    if (disconnectBtn) {
                                        disconnectBtn.classList.add("hidden");
                                    }
                                }
                                break;
                            }
                            default:
                                console.warn("Unknown event type:", eventType);
                                break;
                        }
                    } catch (eventError) {
                        console.error(
                            `Error handling event ${eventType}:`,
                            eventError,
                        );
                        // Continue processing other events
                    }
                }

                setTimeout(scrollChatToBottom, 100);
            }
        } catch (streamError) {
            console.error("Stream reading error:", streamError);
            throw new Error(`Stream error: ${streamError.message}`);
        }

        // Validate we received some data
        if (!hasReceivedData) {
            throw new Error("No data received from server");
        }

        // Mark streaming as complete
        markMessageComplete(assistantMsgId);
    } catch (error) {
        console.error("Chat error:", error);

        // Display backend error message to user
        const errorMsg = error.message || "An unexpected error occurred";
        appendChatMessage("system", `❌ ${errorMsg}`);

        // If we have a partial assistant message, mark it as complete
        if (assistantMsgId) {
            markMessageComplete(assistantMsgId);
        }
    } finally {
        // Clean up reader if it exists
        if (reader) {
            try {
                await reader.cancel();
            } catch (cancelError) {
                console.warn("Error canceling reader:", cancelError);
            }
        }

        // Re-enable input
        input.disabled = false;
        document.getElementById("chat-send-btn").disabled = false;
        input.focus();
    }
}

/**
 * Parse content with <think> tags and separate thinking from final answer
 * Returns: { thinkingSteps: [{content: string}], finalAnswer: string, rawContent: string }
 */
function parseThinkTags(content) {
    const thinkingSteps = [];
    let finalAnswer = "";
    const rawContent = content;

    // Extract all <think>...</think> blocks
    const thinkRegex = /<think>([\s\S]*?)<\/think>/g;
    let match;
    // let lastIndex = 0;

    while ((match = thinkRegex.exec(content)) !== null) {
        const thinkContent = match[1].trim();
        if (thinkContent) {
            thinkingSteps.push({ content: thinkContent });
        }
        // lastIndex = match.index + match[0].length;
    }

    // Remove all <think> tags to get final answer
    finalAnswer = content.replace(/<think>[\s\S]*?<\/think>/g, "").trim();

    return { thinkingSteps, finalAnswer, rawContent };
}

/**
 * Update chat message with think tags support
 * Renders thinking steps in collapsible UI and final answer separately
 */
function updateChatMessageWithThinkTags(messageId, content) {
    const messageDiv = document.getElementById(messageId);
    if (!messageDiv) {
        return;
    }

    const contentEl = messageDiv.querySelector(".message-content");
    if (!contentEl) {
        return;
    }

    // Parse content for think tags
    const { thinkingSteps, finalAnswer } = parseThinkTags(content);

    // Clear existing content
    contentEl.innerHTML = "";

    // Render thinking steps if present
    if (thinkingSteps.length > 0) {
        const thinkingContainer = createThinkingUI(thinkingSteps);
        contentEl.appendChild(thinkingContainer);
    }

    // Render final answer
    if (finalAnswer) {
        const answerDiv = document.createElement("div");
        answerDiv.className = "final-answer-content";
        answerDiv.textContent = finalAnswer;
        contentEl.appendChild(answerDiv);
    }

    // Throttle scroll during streaming
    if (!scrollThrottle) {
        scrollChatToBottom();
        scrollThrottle = setTimeout(() => {
            scrollThrottle = null;
        }, 100);
    }
}

/**
 * Create the thinking UI component with collapsible steps
 */
function createThinkingUI(thinkingSteps) {
    const container = document.createElement("div");
    container.className = "thinking-container";

    // Create header with icon and label
    const header = document.createElement("div");
    header.className = "thinking-header";
    header.innerHTML = `
        <div class="thinking-header-content">
            <svg class="thinking-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
            </svg>
            <span class="thinking-label">Thinking</span>
            <span class="thinking-count">${thinkingSteps.length} step${thinkingSteps.length !== 1 ? "s" : ""}</span>
        </div>
        <button class="thinking-toggle" aria-label="Toggle thinking steps">
            <svg class="thinking-chevron" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
            </svg>
        </button>
    `;

    // Create collapsible content
    const content = document.createElement("div");
    content.className = "thinking-content collapsed";

    // Add each thinking step
    thinkingSteps.forEach((step, index) => {
        const stepDiv = document.createElement("div");
        stepDiv.className = "thinking-step";
        stepDiv.innerHTML = `
            <div class="thinking-step-number">
                <span>${index + 1}</span>
            </div>
            <div class="thinking-step-text">${escapeHtml(step.content)}</div>
        `;
        content.appendChild(stepDiv);
    });

    // Toggle functionality
    const toggleBtn = header.querySelector(".thinking-toggle");
    const chevron = header.querySelector(".thinking-chevron");

    toggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const isCollapsed = content.classList.contains("collapsed");

        if (isCollapsed) {
            content.classList.remove("collapsed");
            chevron.style.transform = "rotate(180deg)";
        } else {
            content.classList.add("collapsed");
            chevron.style.transform = "rotate(0deg)";
        }

        // Scroll after animation
        setTimeout(scrollChatToBottom, 200);
    });

    container.appendChild(header);
    container.appendChild(content);

    return container;
}

/**
 * Helper to escape HTML for safe rendering
 */
function escapeHtmlChat(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Append chat message to UI
 */
// Append chat message to UI
// Append chat message to UI
// Append chat message to UI
// function appendChatMessage(role, content, isStreaming = false) {
//     const container = document.getElementById('chat-messages-container');
//     const messageId = `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

//     const messageDiv = document.createElement('div');
//     messageDiv.id = messageId;
//     messageDiv.className = `chat-message ${role}-message`;

//     if (role === 'user') {
//         messageDiv.innerHTML = `
//             <div class="flex justify-end" style="margin: 0;">
//                 <div class="max-w-80 rounded-lg bg-indigo-600 text-white" style="padding: 6px 12px;">
//                     <div class="text-sm whitespace-pre-wrap" style="margin: 0; padding: 0; line-height: 1.3;">${escapeHtml(content)}</div>
//                 </div>
//             </div>
//         `;
//     } else if (role === 'assistant') {
//         messageDiv.innerHTML = `
//             <div class="flex justify-start" style="margin: 0;">
//                 <div class="max-w-80 rounded-lg bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-gray-100" style="padding: 6px 12px;">
//                     <div class="text-sm whitespace-pre-wrap message-content" style="margin: 0; padding: 0; line-height: 1.3; display: inline-block;">${escapeHtml(content)}</div>
//                     ${isStreaming ? '<span class="streaming-indicator inline-block ml-2"></span>' : ''}
//                 </div>
//             </div>
//         `;
//     } else if (role === 'system') {
//         messageDiv.innerHTML = `
//             <div class="flex justify-center">
//                 <div class="rounded-lg bg-yellow-50 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200 text-xs" style="padding: 4px 10px; margin: 0;">
//                     ${escapeHtml(content)}
//                 </div>
//             </div>
//         `;
//     }

//     container.appendChild(messageDiv);
//     scrollChatToBottom();
//     return messageId;
// }

function appendChatMessage(role, content, isStreaming = false) {
    const container = document.getElementById("chat-messages-container");
    const messageId = `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    const messageDiv = document.createElement("div");
    messageDiv.id = messageId;
    messageDiv.className = `chat-message ${role}-message`;
    messageDiv.style.marginBottom = "6px"; // compact spacing between messages

    if (role === "user") {
        messageDiv.innerHTML = `
            <div class="flex justify-end px-2">
                <div class="bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-2xl px-4 py-2 max-w-xs shadow-sm text-sm whitespace-pre-wrap flex items-end gap-1">
                    <div class="message-content">${escapeHtmlChat(content)}</div>
                </div>
            </div>
        `;
    } else if (role === "assistant") {
        messageDiv.innerHTML = `
            <div class="flex justify-start px-2">
                <div class="bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-2xl px-4 py-2 max-w-xs shadow-sm text-sm whitespace-pre-wrap flex items-end gap-1">
                    <div class="message-content">${escapeHtmlChat(content)}</div>
                    ${isStreaming ? '<span class="streaming-indicator w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>' : ""}
                </div>
            </div>
        `;
    } else if (role === "system") {
        messageDiv.innerHTML = `
            <div class="flex justify-center px-2">
                <div class="bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-100 text-xs px-3 py-1 rounded-md shadow-sm">
                    ${escapeHtmlChat(content)}
                </div>
            </div>
        `;
    }

    container.appendChild(messageDiv);
    scrollChatToBottom();
    return messageId;
}

/**
 * Update chat message content (for streaming)
 */
let scrollThrottle = null;
function updateChatMessage(messageId, content) {
    const messageDiv = document.getElementById(messageId);
    if (messageDiv) {
        const contentEl = messageDiv.querySelector(".message-content");
        if (contentEl) {
            // Store raw content for final processing
            contentEl.setAttribute("data-raw-content", content);
            contentEl.textContent = content;

            // Throttle scroll during streaming
            if (!scrollThrottle) {
                scrollChatToBottom();
                scrollThrottle = setTimeout(() => {
                    scrollThrottle = null;
                }, 100);
            }
        }
    }
}

/**
 * Mark message as complete (remove streaming indicator)
 */
function markMessageComplete(messageId) {
    const messageDiv = document.getElementById(messageId);
    if (messageDiv) {
        const indicator = messageDiv.querySelector(".streaming-indicator");
        if (indicator) {
            indicator.remove();
        }

        // Ensure final render with think tags
        const contentEl = messageDiv.querySelector(".message-content");
        if (contentEl && contentEl.textContent) {
            // Re-parse one final time to ensure complete rendering
            const fullContent =
                contentEl.getAttribute("data-raw-content") ||
                contentEl.textContent;
            if (fullContent.includes("<think>")) {
                const { thinkingSteps, finalAnswer } =
                    parseThinkTags(fullContent);
                contentEl.innerHTML = "";

                if (thinkingSteps.length > 0) {
                    const thinkingContainer = createThinkingUI(thinkingSteps);
                    contentEl.appendChild(thinkingContainer);
                }

                if (finalAnswer) {
                    const answerDiv = document.createElement("div");
                    answerDiv.className = "final-answer-content";
                    answerDiv.textContent = finalAnswer;
                    contentEl.appendChild(answerDiv);
                }
            }
        }
    }
}

/**
 * Get or create a tool-events card positioned above the assistant message.
 * The card is a sibling of the message div, not nested inside.
 */
function getOrCreateToolCard(messageId) {
    const messageDiv = document.getElementById(messageId);
    if (!messageDiv) {
        return null;
    }

    // Check if card already exists as a sibling
    let card = messageDiv.previousElementSibling;
    if (card && card.classList.contains("tool-events-card")) {
        return card;
    }

    // Create a new card
    card = document.createElement("div");
    card.className =
        "tool-events-card mb-2 p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700";

    const header = document.createElement("div");
    header.className = "flex items-center justify-between mb-2";

    const title = document.createElement("div");
    title.className =
        "font-semibold text-sm text-blue-800 dark:text-blue-200 flex items-center gap-2";
    title.innerHTML = `
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path>
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
    </svg>
    <span>Tool Invocations</span>
  `;

    const toggleBtn = document.createElement("button");
    toggleBtn.className =
        "text-xs text-blue-600 dark:text-blue-300 hover:underline";
    toggleBtn.textContent = "Hide";
    toggleBtn.onclick = () => {
        const body = card.querySelector(".tool-events-body");
        if (body.classList.contains("hidden")) {
            body.classList.remove("hidden");
            toggleBtn.textContent = "Hide";
        } else {
            body.classList.add("hidden");
            toggleBtn.textContent = "Show";
        }
    };

    header.appendChild(title);
    header.appendChild(toggleBtn);
    card.appendChild(header);

    const body = document.createElement("div");
    body.className = "tool-events-body space-y-2";
    card.appendChild(body);

    // Insert card before the message div
    messageDiv.parentElement.insertBefore(card, messageDiv);

    return card;
}

/**
 * Add a tool event row to the tool card.
 */
function addToolEventToCard(messageId, eventType, payload) {
    const card = getOrCreateToolCard(messageId);
    if (!card) {
        return;
    }

    const body = card.querySelector(".tool-events-body");

    const row = document.createElement("div");
    row.className =
        "text-xs p-2 rounded bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700";

    let icon = "";
    let text = "";
    let colorClass = "";

    if (eventType === "tool_start") {
        icon =
            '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>';
        colorClass = "text-green-700 dark:text-green-400";
        text = `<strong>Started:</strong> ${escapeHtmlChat(payload.tool || payload.id || "unknown")}`;
        if (payload.input) {
            text += `<br><span class="text-gray-600 dark:text-gray-400">Input: ${escapeHtmlChat(JSON.stringify(payload.input))}</span>`;
        }
    } else if (eventType === "tool_end") {
        icon =
            '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>';
        colorClass = "text-blue-700 dark:text-blue-400";
        text = `<strong>Completed:</strong> ${escapeHtmlChat(payload.tool || payload.id || "unknown")}`;
        if (payload.output) {
            const out =
                typeof payload.output === "string"
                    ? payload.output
                    : JSON.stringify(payload.output);
            text += `<br><span class="text-gray-600 dark:text-gray-400">Output: ${escapeHtmlChat(out)}</span>`;
        }
    } else if (eventType === "tool_error") {
        icon =
            '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>';
        colorClass = "text-red-700 dark:text-red-400";
        text = `<strong>Error:</strong> ${escapeHtmlChat(payload.error || payload.tool || payload.id || "unknown")}`;
    }

    row.innerHTML = `<div class="flex items-start gap-2 ${colorClass}">${icon}<div>${text}</div></div>`;
    body.appendChild(row);
}

/**
 * Update or create a "tools used" summary badge on the tool card when final event arrives.
 */
function setToolUsedSummary(messageId, used, toolsList) {
    const card = getOrCreateToolCard(messageId);
    if (!card) {
        return;
    }

    let badge = card.querySelector(".tool-summary-badge");
    if (!badge) {
        badge = document.createElement("div");
        badge.className =
            "tool-summary-badge mt-2 pt-2 border-t border-blue-200 dark:border-blue-700 text-xs font-medium";
        card.appendChild(badge);
    }

    if (used && toolsList && toolsList.length > 0) {
        badge.className =
            "tool-summary-badge mt-2 pt-2 border-t border-blue-200 dark:border-blue-700 text-xs font-medium text-green-700 dark:text-green-400";
        badge.textContent = `✓ Tools used: ${toolsList.join(", ")}`;
    } else {
        badge.className =
            "tool-summary-badge mt-2 pt-2 border-t border-blue-200 dark:border-blue-700 text-xs font-medium text-gray-600 dark:text-gray-400";
        badge.textContent = "No tools invoked";
    }
}

/**
 * Clear all chat messages
 */
function clearChatMessages() {
    const container = document.getElementById("chat-messages-container");
    if (container) {
        container.innerHTML = `
      <div id="chat-welcome-message" class="flex items-center justify-center h-full">
        <div class="text-center text-gray-500 dark:text-gray-400">
          <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
          </svg>
          <p class="mt-4 text-lg font-medium">Select a server and connect to start chatting</p>
          <p class="mt-2 text-sm">Choose a virtual server from the left and configure your LLM settings</p>
        </div>
      </div>
    `;
    }
}

/**
 * Scroll chat to bottom
 */
function scrollChatToBottom() {
    const container = document.getElementById("chat-messages-container");
    if (container) {
        requestAnimationFrame(() => {
            // Use instant scroll during streaming for better UX
            container.scrollTop = container.scrollHeight;
        });
    }
}

/**
 * Handle Enter key in chat input (send on Enter, new line on Shift+Enter)
 */
// eslint-disable-next-line no-unused-vars
function handleChatInputKeydown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendChatMessage(event);
    }
}

function initializeChatInputResize() {
    const chatInput = document.getElementById("chat-input");
    if (chatInput) {
        chatInput.addEventListener("input", function () {
            this.style.height = "auto";
            this.style.height = Math.min(this.scrollHeight, 120) + "px";
        });

        // Reset height when message is sent
        const form = document.getElementById("chat-input-form");
        if (form) {
            form.addEventListener("submit", () => {
                setTimeout(() => {
                    chatInput.style.height = "auto";
                }, 0);
            });
        }
    }
}
/**
 * Perform server-side search for tools and update the tool list
 */
async function serverSideToolSearch(searchTerm) {
    const container = document.getElementById("associatedTools");
    const noResultsMessage = safeGetElement("noToolsMessage", true);
    const searchQuerySpan = safeGetElement("searchQueryTools", true);

    if (!container) {
        console.error("associatedTools container not found");
        return;
    }

    // Show loading state
    container.innerHTML = `
        <div class="text-center py-4">
            <svg class="animate-spin h-5 w-5 text-indigo-600 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <p class="mt-2 text-sm text-gray-500">Searching tools...</p>
        </div>
    `;

    if (searchTerm.trim() === "") {
        // If search term is empty, reload the default tool list
        try {
            const response = await fetch(
                `${window.ROOT_PATH}/admin/tools/partial?page=1&per_page=50&render=selector`,
            );
            if (response.ok) {
                const html = await response.text();
                container.innerHTML = html;

                // Hide no results message
                if (noResultsMessage) {
                    noResultsMessage.style.display = "none";
                }

                // Update tool mapping if needed
                updateToolMapping(container);
            } else {
                container.innerHTML =
                    '<div class="text-center py-4 text-red-600">Failed to load tools</div>';
            }
        } catch (error) {
            console.error("Error loading tools:", error);
            container.innerHTML =
                '<div class="text-center py-4 text-red-600">Error loading tools</div>';
        }
        return;
    }

    try {
        // Call the new search API
        const response = await fetch(
            `${window.ROOT_PATH}/admin/tools/search?q=${encodeURIComponent(searchTerm)}&limit=100`,
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (data.tools && data.tools.length > 0) {
            // Create HTML for search results
            let searchResultsHtml = "";
            data.tools.forEach((tool) => {
                // Create a label element similar to the ones in tools_selector_items.html
                // Use the same name priority as the template: displayName or customName or original_name
                const displayName =
                    tool.display_name ||
                    tool.custom_name ||
                    tool.name ||
                    tool.id;

                searchResultsHtml += `
                    <label
                        class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 cursor-pointer hover:bg-indigo-50 dark:hover:bg-indigo-900 rounded-md p-1 tool-item"
                        data-tool-id="${escapeHtml(tool.id)}"
                    >
                        <input
                            type="checkbox"
                            name="associatedTools"
                            value="${escapeHtml(tool.id)}"
                            data-tool-name="${escapeHtml(displayName)}"
                            class="tool-checkbox form-checkbox h-5 w-5 text-indigo-600 dark:bg-gray-800 dark:border-gray-600"
                        />
                        <span class="select-none">${escapeHtml(displayName)}</span>
                    </label>
                `;
            });

            container.innerHTML = searchResultsHtml;

            // Update tool mapping with search results
            updateToolMapping(container);

            // Hide no results message
            if (noResultsMessage) {
                noResultsMessage.style.display = "none";
            }
        } else {
            // Show no results message
            container.innerHTML = "";
            if (noResultsMessage) {
                if (searchQuerySpan) {
                    searchQuerySpan.textContent = searchTerm;
                }
                noResultsMessage.style.display = "block";
            }
        }
    } catch (error) {
        console.error("Error searching tools:", error);
        container.innerHTML =
            '<div class="text-center py-4 text-red-600">Error searching tools</div>';

        // Hide no results message in case of error
        if (noResultsMessage) {
            noResultsMessage.style.display = "none";
        }
    }
}

/**
 * Update the tool mapping with tools in the given container
 */
function updateToolMapping(container) {
    if (!window.toolMapping) {
        window.toolMapping = {};
    }

    const checkboxes = container.querySelectorAll(
        'input[name="associatedTools"]',
    );
    checkboxes.forEach((checkbox) => {
        const toolId = checkbox.value;
        const toolName = checkbox.getAttribute("data-tool-name");
        if (toolId && toolName) {
            window.toolMapping[toolId] = toolName;
        }
    });
}

/**
 * Perform server-side search for prompts and update the prompt list
 */
async function serverSidePromptSearch(searchTerm) {
    const container = document.getElementById("associatedPrompts");
    const noResultsMessage = safeGetElement("noPromptsMessage", true);
    const searchQuerySpan = safeGetElement("searchPromptsQuery", true);

    if (!container) {
        console.error("associatedPrompts container not found");
        return;
    }

    // Show loading state
    container.innerHTML = `
        <div class="text-center py-4">
            <svg class="animate-spin h-5 w-5 text-purple-600 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <p class="mt-2 text-sm text-gray-500">Searching prompts...</p>
        </div>
    `;

    if (searchTerm.trim() === "") {
        // If search term is empty, reload the default prompt selector
        try {
            const response = await fetch(
                `${window.ROOT_PATH}/admin/prompts/partial?page=1&per_page=50&render=selector`,
            );
            if (response.ok) {
                const html = await response.text();
                container.innerHTML = html;

                // Hide no results message
                if (noResultsMessage) {
                    noResultsMessage.style.display = "none";
                }

                // Initialize prompt mapping if needed
                initPromptSelect(
                    "associatedPrompts",
                    "selectedPromptsPills",
                    "selectedPromptsWarning",
                    6,
                    "selectAllPromptsBtn",
                    "clearAllPromptsBtn",
                );
            } else {
                container.innerHTML =
                    '<div class="text-center py-4 text-red-600">Failed to load prompts</div>';
            }
        } catch (error) {
            console.error("Error loading prompts:", error);
            container.innerHTML =
                '<div class="text-center py-4 text-red-600">Error loading prompts</div>';
        }
        return;
    }

    try {
        const response = await fetch(
            `${window.ROOT_PATH}/admin/prompts/search?q=${encodeURIComponent(searchTerm)}&limit=100`,
        );
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (data.prompts && data.prompts.length > 0) {
            let searchResultsHtml = "";
            data.prompts.forEach((prompt) => {
                const displayName = prompt.name || prompt.id;
                searchResultsHtml += `
                    <label
                        class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 cursor-pointer hover:bg-purple-50 dark:hover:bg-purple-900 rounded-md p-1 prompt-item"
                        data-prompt-id="${escapeHtml(prompt.id)}"
                    >
                        <input
                            type="checkbox"
                            name="associatedPrompts"
                            value="${escapeHtml(prompt.id)}"
                            data-prompt-name="${escapeHtml(displayName)}"
                            class="prompt-checkbox form-checkbox h-5 w-5 text-purple-600 dark:bg-gray-800 dark:border-gray-600"
                        />
                        <span class="select-none">${escapeHtml(displayName)}</span>
                    </label>
                `;
            });

            container.innerHTML = searchResultsHtml;

            // Initialize prompt select mapping
            initPromptSelect(
                "associatedPrompts",
                "selectedPromptsPills",
                "selectedPromptsWarning",
                6,
                "selectAllPromptsBtn",
                "clearAllPromptsBtn",
            );

            if (noResultsMessage) {
                noResultsMessage.style.display = "none";
            }
        } else {
            container.innerHTML = "";
            if (noResultsMessage) {
                if (searchQuerySpan) {
                    searchQuerySpan.textContent = searchTerm;
                }
                noResultsMessage.style.display = "block";
            }
        }
    } catch (error) {
        console.error("Error searching prompts:", error);
        container.innerHTML =
            '<div class="text-center py-4 text-red-600">Error searching prompts</div>';
        if (noResultsMessage) {
            noResultsMessage.style.display = "none";
        }
    }
}

// Add CSS for streaming indicator animation
const style = document.createElement("style");
style.textContent = `
  .streaming-indicator {
    animation: blink 1s infinite;
  }

  @keyframes blink {
    0%, 50% { opacity: 1; }
    51%, 100% { opacity: 0; }
  }

  #chat-input {
    max-height: 120px;
    overflow-y: auto;
  }
`;
document.head.appendChild(style);

// ============================================================================
// CA Certificate Validation Functions
// ============================================================================

/**
 * Validate CA certificate file on upload (supports multiple files)
 * @param {Event} event - The file input change event
 */
async function validateCACertFiles(event) {
    const files = Array.from(event.target.files);
    const feedbackEl = document.getElementById("ca-certificate-feedback");

    if (!files.length) {
        feedbackEl.textContent = "No files selected.";
        return;
    }

    // Check file size (max 10MB for cert files)
    const maxSize = 10 * 1024 * 1024; // 10MB
    const oversizedFiles = files.filter((f) => f.size > maxSize);
    if (oversizedFiles.length > 0) {
        if (feedbackEl) {
            feedbackEl.innerHTML = `
                <div class="flex items-center text-red-600">
                    <svg class="w-6 h-6 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                    <span>Certificate file(s) too large. Maximum size is 10MB per file.</span>
                </div>
            `;
            feedbackEl.className = "mt-2 text-sm";
        }
        event.target.value = "";
        return;
    }

    // Check file extensions
    const validExtensions = [".pem", ".crt", ".cer", ".cert"];
    const invalidFiles = files.filter((file) => {
        const fileName = file.name.toLowerCase();
        return !validExtensions.some((ext) => fileName.endsWith(ext));
    });

    if (invalidFiles.length > 0) {
        if (feedbackEl) {
            feedbackEl.innerHTML = `
                <div class="flex items-center text-red-600">
                    <svg class="w-6 h-6 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                    <span>Invalid file type. Please upload valid certificate files (.pem, .crt, .cer, .cert)</span>
                </div>
            `;
            feedbackEl.className = "mt-2 text-sm";
        }
        event.target.value = "";
        return;
    }

    // Read and validate all files
    const certResults = [];
    for (const file of files) {
        try {
            const content = await readFileAsync(file);
            const isValid = isValidCertificate(content);
            const certInfo = isValid ? parseCertificateInfo(content) : null;

            certResults.push({
                file,
                content,
                isValid,
                certInfo,
            });
        } catch (error) {
            certResults.push({
                file,
                content: null,
                isValid: false,
                certInfo: null,
                error: error.message,
            });
        }
    }

    // Display per-file validation results
    displayCertValidationResults(certResults, feedbackEl);

    // If all valid, order and concatenate
    const allValid = certResults.every((r) => r.isValid);
    if (allValid) {
        const orderedCerts = orderCertificateChain(certResults);
        const concatenated = orderedCerts
            .map((r) => r.content.trim())
            .join("\n");

        // Store concatenated result in a hidden field
        let hiddenInput = document.getElementById(
            "ca_certificate_concatenated",
        );
        if (!hiddenInput) {
            hiddenInput = document.createElement("input");
            hiddenInput.type = "hidden";
            hiddenInput.id = "ca_certificate_concatenated";
            hiddenInput.name = "ca_certificate";
            event.target.form.appendChild(hiddenInput);
        }
        hiddenInput.value = concatenated;

        // Update drop zone
        updateDropZoneWithFiles(files);
    } else {
        event.target.value = "";
    }
}

/**
 * Helper function to read file as text asynchronously
 * @param {File} file - The file to read
 * @returns {Promise<string>} - Promise resolving to file content
 */
function readFileAsync(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => resolve(e.target.result);
        reader.onerror = () => reject(new Error("Error reading file"));
        reader.readAsText(file);
    });
}

/**
 * Parse certificate information to determine if it's self-signed (root CA)
 * @param {string} content - PEM certificate content
 * @returns {Object} - Certificate info with isRoot flag
 */
function parseCertificateInfo(content) {
    // Basic heuristic: check if Subject and Issuer appear the same
    // In a real implementation, you'd parse the ASN.1 structure properly
    const subjectMatch = content.match(/Subject:([^\n]+)/i);
    const issuerMatch = content.match(/Issuer:([^\n]+)/i);

    // If we can't parse, assume it's an intermediate
    if (!subjectMatch || !issuerMatch) {
        return { isRoot: false };
    }

    const subject = subjectMatch[1].trim();
    const issuer = issuerMatch[1].trim();

    return {
        isRoot: subject === issuer,
        subject,
        issuer,
    };
}

/**
 * Order certificates in chain: root CA first, then intermediates, then leaf
 * @param {Array} certResults - Array of certificate result objects
 * @returns {Array} - Ordered array of certificate results
 */
function orderCertificateChain(certResults) {
    const roots = certResults.filter((r) => r.certInfo && r.certInfo.isRoot);
    const nonRoots = certResults.filter(
        (r) => r.certInfo && !r.certInfo.isRoot,
    );

    // Simple ordering: roots first, then rest
    // In production, you'd build a proper chain by matching issuer/subject
    return [...roots, ...nonRoots];
}

/**
 * Display validation results for each certificate file
 * @param {Array} certResults - Array of validation result objects
 * @param {HTMLElement} feedbackEl - Element to display feedback
 */
function displayCertValidationResults(certResults, feedbackEl) {
    const allValid = certResults.every((r) => r.isValid);

    let html = '<div class="space-y-2">';

    // Overall status
    if (allValid) {
        html += `
            <div class="flex items-center text-green-600 font-semibold text-lg">
                <svg class="w-8 h-8 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                <span>All certificates validated successfully!</span>
            </div>
        `;
    } else {
        html += `
            <div class="flex items-center text-red-600 font-semibold text-lg">
                <svg class="w-8 h-8 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                <span>Some certificates failed validation</span>
            </div>
        `;
    }

    // Per-file results
    html += '<div class="mt-3 space-y-1">';
    for (const result of certResults) {
        const icon = result.isValid
            ? '<svg class="w-5 h-5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>'
            : '<svg class="w-5 h-5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>';

        const statusClass = result.isValid ? "text-gray-700" : "text-red-700";
        const typeLabel =
            result.certInfo && result.certInfo.isRoot ? " (Root CA)" : "";

        html += `
            <div class="flex items-center ${statusClass}">
                ${icon}
                <span class="ml-2">${escapeHtml(result.file.name)}${typeLabel} - ${formatFileSize(result.file.size)}</span>
            </div>
        `;
    }
    html += "</div></div>";

    feedbackEl.innerHTML = html;
    feedbackEl.className = "mt-2 text-sm";
}

/**
 * Validate certificate content (PEM format)
 * @param {string} content - The certificate file content
 * @returns {boolean} - True if valid certificate
 */
function isValidCertificate(content) {
    // Trim whitespace
    content = content.trim();

    // Check for PEM certificate markers
    const beginCertPattern = /-----BEGIN CERTIFICATE-----/;
    const endCertPattern = /-----END CERTIFICATE-----/;

    if (!beginCertPattern.test(content) || !endCertPattern.test(content)) {
        return false;
    }

    // Check for proper structure
    const certPattern =
        /-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g;
    const matches = content.match(certPattern);

    if (!matches || matches.length === 0) {
        return false;
    }

    // Validate base64 content between markers
    for (const cert of matches) {
        const base64Content = cert
            .replace(/-----BEGIN CERTIFICATE-----/, "")
            .replace(/-----END CERTIFICATE-----/, "")
            .replace(/\s/g, "");

        // Check if content is valid base64
        if (!isValidBase64(base64Content)) {
            return false;
        }

        // Basic length check (certificates are typically > 100 chars of base64)
        if (base64Content.length < 100) {
            return false;
        }
    }

    return true;
}

/**
 * Check if string is valid base64
 * @param {string} str - The string to validate
 * @returns {boolean} - True if valid base64
 */
function isValidBase64(str) {
    if (str.length === 0) {
        return false;
    }

    // Base64 regex pattern
    const base64Pattern = /^[A-Za-z0-9+/]*={0,2}$/;
    return base64Pattern.test(str);
}

/**
 * Update drop zone UI with selected file info
 * @param {File} file - The selected file
 */
function updateDropZoneWithFiles(files) {
    const dropZone = document.getElementById("ca-certificate-upload-drop-zone");
    if (!dropZone) {
        return;
    }

    const fileListHTML = Array.from(files)
        .map(
            (file) =>
                `<div>${escapeHtml(file.name)} • ${formatFileSize(file.size)}</div>`,
        )
        .join("");

    dropZone.innerHTML = `
        <div class="space-y-2">
            <svg class="mx-auto h-12 w-12 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
            <div class="text-sm text-gray-700 dark:text-gray-300">
                <span class="font-medium">Selected Certificates:</span>
            </div>
            <div class="text-xs text-gray-500 dark:text-gray-400">${fileListHTML}</div>
        </div>
    `;
}

/**
 * Format file size for display
 * @param {number} bytes - File size in bytes
 * @returns {string} - Formatted file size
 */
function formatFileSize(bytes) {
    if (bytes === 0) {
        return "0 Bytes";
    }
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + " " + sizes[i];
}

/**
 * Initialize drag and drop for CA cert upload
 * Called on DOMContentLoaded
 */
function initializeCACertUpload() {
    const dropZone = document.getElementById("ca-certificate-upload-drop-zone");
    const fileInput = document.getElementById("upload-ca-certificate");

    if (dropZone && fileInput) {
        // Click to upload
        dropZone.addEventListener("click", function (e) {
            fileInput.click();
        });

        // Drag and drop handlers
        dropZone.addEventListener("dragover", function (e) {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.add(
                "border-indigo-500",
                "bg-indigo-50",
                "dark:bg-indigo-900/20",
            );
        });

        dropZone.addEventListener("dragleave", function (e) {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove(
                "border-indigo-500",
                "bg-indigo-50",
                "dark:bg-indigo-900/20",
            );
        });

        dropZone.addEventListener("drop", function (e) {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove(
                "border-indigo-500",
                "bg-indigo-50",
                "dark:bg-indigo-900/20",
            );

            const files = e.dataTransfer.files;
            if (files.length > 0) {
                fileInput.files = files;
                // Trigger the validation
                const event = new Event("change", { bubbles: true });
                fileInput.dispatchEvent(event);
            }
        });
    }
}

// Expose CA certificate upload/validation functions for usage in admin.html
// This ensures ESLint recognizes them as used via global handlers.
window.validateCACertFiles = validateCACertFiles;
window.initializeCACertUpload = initializeCACertUpload;

// Function to update body label based on content type selection
function updateBodyLabel() {
    const bodyLabel = document.getElementById("gateway-test-body-label");
    const contentType = document.getElementById(
        "gateway-test-content-type",
    )?.value;

    if (bodyLabel) {
        bodyLabel.innerHTML =
            contentType === "application/x-www-form-urlencoded"
                ? 'Body (JSON)<br><small class="text-gray-500">Auto-converts to form data</small>'
                : "Body (JSON)";
    }
}

// Make it available globally for HTML onclick handlers
window.updateBodyLabel = updateBodyLabel;
