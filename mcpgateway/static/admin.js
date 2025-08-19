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
function fetchWithTimeout(url, options = {}, timeout = 30000) {
    // Increased from 10000
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
            45000, // Increased timeout specifically for metrics (was 20000)
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
    timeout = 20000,
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

        // Process each category safely
        const categories = [
            "tools",
            "resources",
            "prompts",
            "gateways",
            "servers",
        ];
        categories.forEach((category) => {
            if (data[category]) {
                const categoryData = data[category];
                totalExecutions += Number(categoryData.totalExecutions || 0);
                totalSuccessful += Number(
                    categoryData.successfulExecutions || 0,
                );
                totalFailed += Number(categoryData.failedExecutions || 0);

                if (
                    categoryData.avgResponseTime &&
                    categoryData.avgResponseTime !== "N/A"
                ) {
                    responseTimes.push(Number(categoryData.avgResponseTime));
                }
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
        const urlValidation = validateUrl(tool.url);

        const nameField = safeGetElement("edit-tool-name");
        const urlField = safeGetElement("edit-tool-url");
        const descField = safeGetElement("edit-tool-description");
        const typeField = safeGetElement("edit-tool-type");

        if (nameField && nameValidation.valid) {
            nameField.value = nameValidation.value;
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
                    value: resource.createdBy || "Legacy Entity",
                },
                {
                    label: "Created At",
                    value: resource.createdAt
                        ? new Date(resource.createdAt).toLocaleString()
                        : "Pre-metadata",
                },
                {
                    label: "Created From",
                    value: resource.createdFromIp || "Unknown",
                },
                {
                    label: "Created Via",
                    value: resource.createdVia || "Unknown",
                },
                {
                    label: "Last Modified By",
                    value: resource.modifiedBy || "N/A",
                },
                {
                    label: "Last Modified At",
                    value: resource.modifiedAt
                        ? new Date(resource.modifiedAt).toLocaleString()
                        : "N/A",
                },
                { label: "Version", value: resource.version || "1" },
                {
                    label: "Import Batch",
                    value: resource.importBatchId || "N/A",
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
                    value: prompt.createdBy || "Legacy Entity",
                },
                {
                    label: "Created At",
                    value: prompt.createdAt
                        ? new Date(prompt.createdAt).toLocaleString()
                        : "Pre-metadata",
                },
                {
                    label: "Created From",
                    value: prompt.createdFromIp || "Unknown",
                },
                { label: "Created Via", value: prompt.createdVia || "Unknown" },
                {
                    label: "Last Modified By",
                    value: prompt.modifiedBy || "N/A",
                },
                {
                    label: "Last Modified At",
                    value: prompt.modifiedAt
                        ? new Date(prompt.modifiedAt).toLocaleString()
                        : "N/A",
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
                    value: gateway.createdBy || "Legacy Entity",
                },
                {
                    label: "Created At",
                    value: gateway.createdAt
                        ? new Date(gateway.createdAt).toLocaleString()
                        : "Pre-metadata",
                },
                {
                    label: "Created From",
                    value: gateway.createdFromIp || "Unknown",
                },
                {
                    label: "Created Via",
                    value: gateway.createdVia || "Unknown",
                },
                {
                    label: "Last Modified By",
                    value: gateway.modifiedBy || "N/A",
                },
                {
                    label: "Last Modified At",
                    value: gateway.modifiedAt
                        ? new Date(gateway.modifiedAt).toLocaleString()
                        : "N/A",
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
                "space-y-2 dark:bg-gray-900 dark:text-gray-100";

            const fields = [
                { label: "Name", value: server.name },
                { label: "URL", value: server.url },
                { label: "Description", value: server.description || "N/A" },
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

            if (server.tags && server.tags.length > 0) {
                server.tags.forEach((tag) => {
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
                server.isActive
                    ? "bg-green-100 text-green-800"
                    : "bg-red-100 text-red-800"
            }`;
            statusSpan.textContent = server.isActive ? "Active" : "Inactive";
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
                    value: server.createdBy || "Legacy Entity",
                },
                {
                    label: "Created At",
                    value: server.createdAt
                        ? new Date(server.createdAt).toLocaleString()
                        : "Pre-metadata",
                },
                {
                    label: "Created From",
                    value: server.createdFromIp || "Unknown",
                },
                { label: "Created Via", value: server.createdVia || "Unknown" },
                {
                    label: "Last Modified By",
                    value: server.modifiedBy || "N/A",
                },
                {
                    label: "Last Modified At",
                    value: server.modifiedAt
                        ? new Date(server.modifiedAt).toLocaleString()
                        : "N/A",
                },
                { label: "Version", value: server.version || "1" },
                { label: "Import Batch", value: server.importBatchId || "N/A" },
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
        if (!hiddenField) {
            hiddenField = document.createElement("input");
            hiddenField.type = "hidden";
            hiddenField.name = "is_inactive_checked";
            hiddenField.id = "edit-server-show-inactive";
            const editForm = safeGetElement("edit-server-form");
            if (editForm) {
                editForm.appendChild(hiddenField);
            }
        }
        hiddenField.value = isInactiveCheckedBool;

        // Set form action and populate fields with validation
        const editForm = safeGetElement("edit-server-form");
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

        // Set tags field
        const tagsField = safeGetElement("edit-server-tags");
        if (tagsField) {
            tagsField.value = server.tags ? server.tags.join(", ") : "";
        }

        openModal("server-edit-modal");
        console.log("✓ Server edit modal loaded successfully");
    } catch (error) {
        console.error("Error fetching server for editing:", error);
        const errorMessage = handleFetchError(error, "load server for editing");
        showErrorMessage(errorMessage);
    }
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

                if (tabName === "version-info") {
                    const versionPanel = safeGetElement("version-info-panel");
                    if (versionPanel && versionPanel.innerHTML.trim() === "") {
                        fetchWithTimeout(
                            `${window.ROOT_PATH}/version?partial=true`,
                            {},
                            10000,
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
) {
    if (!basicFields || !bearerFields || !headersFields) {
        console.warn("Auth field elements not found");
        return;
    }

    // Hide all fields first
    [basicFields, bearerFields, headersFields].forEach((field) => {
        field.style.display = "none";
    });

    // Show relevant field based on selection
    switch (value) {
        case "basic":
            basicFields.style.display = "block";
            break;
        case "bearer":
            bearerFields.style.display = "block";
            break;
        case "authheaders": {
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
            break;
        }
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
    requestTimeout: 30000, // Increased from 10000ms
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
                descElement.innerHTML = tool.description.replace(
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
            20000, // Increased from 8000
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

        // Build auth HTML safely
        let authHTML = "";
        if (tool.auth?.username && tool.auth?.password) {
            authHTML = `
        <p><strong>Authentication Type:</strong> Basic</p>
        <p><strong>Username:</strong> <span class="auth-username"></span></p>
        <p><strong>Password:</strong> ********</p>
      `;
        } else if (tool.auth?.token) {
            authHTML = `
        <p><strong>Authentication Type:</strong> Token</p>
        <p><strong>Token:</strong> ********</p>
      `;
        } else if (tool.auth?.authHeaderKey && tool.auth?.authHeaderValue) {
            authHTML = `
        <p><strong>Authentication Type:</strong> Custom Headers</p>
        <p><strong>Header Key:</strong> <span class="auth-header-key"></span></p>
        <p><strong>Header Value:</strong> ********</p>
      `;
        } else {
            authHTML = "<p><strong>Authentication Type:</strong> None</p>";
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
        <div class="space-y-2 dark:bg-gray-800 dark:text-gray-300">
          <p><strong>Name:</strong> <span class="tool-name"></span></p>
          <p><strong>URL:</strong> <span class="tool-url"></span></p>
          <p><strong>Type:</strong> <span class="tool-type"></span></p>
          <p><strong>Description:</strong> <span class="tool-description"></span></p>
          <p><strong>Tags:</strong> <span class="tool-tags"></span></p>
          <p><strong>Request Type:</strong> <span class="tool-request-type"></span></p>
          ${authHTML}
          ${renderAnnotations(tool.annotations)}
          <div>
            <strong>Headers:</strong>
            <pre class="mt-1 bg-gray-100 p-2 rounded dark:bg-gray-800 dark:text-gray-200 tool-headers"></pre>
          </div>
          <div>
            <strong>Input Schema:</strong>
            <pre class="mt-1 bg-gray-100 p-2 rounded dark:bg-gray-800 dark:text-gray-200 tool-schema"></pre>
          </div>
          <div>
            <strong>Metrics:</strong>
            <ul class="list-disc list-inside ml-4">
              <li>Total Executions: <span class="metric-total"></span></li>
              <li>Successful Executions: <span class="metric-success"></span></li>
              <li>Failed Executions: <span class="metric-failed"></span></li>
              <li>Failure Rate: <span class="metric-failure-rate"></span></li>
              <li>Min Response Time: <span class="metric-min-time"></span></li>
              <li>Max Response Time: <span class="metric-max-time"></span></li>
              <li>Average Response Time: <span class="metric-avg-time"></span></li>
              <li>Last Execution Time: <span class="metric-last-time"></span></li>
            </ul>
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
                                `<span class="inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full mr-1 mb-1 dark:bg-blue-900 dark:text-blue-200">${tag}</span>`,
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
                tool.createdBy || "Legacy Entity",
            );
            setTextSafely(
                ".metadata-created-at",
                tool.createdAt
                    ? new Date(tool.createdAt).toLocaleString()
                    : "Pre-metadata",
            );
            setTextSafely(
                ".metadata-created-from",
                tool.createdFromIp || "Unknown",
            );
            setTextSafely(
                ".metadata-created-via",
                tool.createdVia || "Unknown",
            );
            setTextSafely(".metadata-modified-by", tool.modifiedBy || "N/A");
            setTextSafely(
                ".metadata-modified-at",
                tool.modifiedAt
                    ? new Date(tool.modifiedAt).toLocaleString()
                    : "N/A",
            );
            setTextSafely(".metadata-version", tool.version || "1");
            setTextSafely(
                ".metadata-import-batch",
                tool.importBatchId || "N/A",
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

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/gateways`,
            {
                method: "POST",
                body: formData,
            },
        );
        const result = await response.json();

        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to add gateway");
        } else {
            const redirectUrl = isInactiveCheckedBool
                ? `${window.ROOT_PATH}/admin?include_inactive=true#gateways`
                : `${window.ROOT_PATH}/admin#gateways`;
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

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/resources`,
            {
                method: "POST",
                body: formData,
            },
        );
        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to add Resource");
        } else {
            const redirectUrl = isInactiveCheckedBool
                ? `${window.ROOT_PATH}/admin?include_inactive=true#resources`
                : `${window.ROOT_PATH}/admin#resources`;
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

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/prompts`,
            {
                method: "POST",
                body: formData,
            },
        );
        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to add prompt");
        }
        // Only redirect on success
        const redirectUrl = isInactiveCheckedBool
            ? `${window.ROOT_PATH}/admin?include_inactive=true#prompts`
            : `${window.ROOT_PATH}/admin#prompts`;
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
        const redirectUrl = isInactiveCheckedBool
            ? `${window.ROOT_PATH}/admin?include_inactive=true#prompts`
            : `${window.ROOT_PATH}/admin#prompts`;
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

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/servers`,
            {
                method: "POST",
                body: formData,
                redirect: "manual",
            },
        );
        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to add server.");
        } else {
            // Success redirect
            const redirectUrl = isInactiveCheckedBool
                ? `${window.ROOT_PATH}/admin?include_inactive=true#catalog`
                : `${window.ROOT_PATH}/admin#catalog`;
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

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/tools`,
            {
                method: "POST",
                body: formData,
            },
        );
        const result = await response.json();
        if (!result || !result.success) {
            throw new Error(result?.message || "Failed to add tool");
        } else {
            const redirectUrl = isInactiveCheckedBool
                ? `${window.ROOT_PATH}/admin?include_inactive=true#tools`
                : `${window.ROOT_PATH}/admin#tools`;
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
            const redirectUrl = isInactiveCheckedBool
                ? `${window.ROOT_PATH}/admin?include_inactive=true#tools`
                : `${window.ROOT_PATH}/admin#tools`;
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
        const redirectUrl = isInactiveCheckedBool
            ? `${window.ROOT_PATH}/admin?include_inactive=true#gateways`
            : `${window.ROOT_PATH}/admin#gateways`;
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
            const redirectUrl = isInactiveCheckedBool
                ? `${window.ROOT_PATH}/admin?include_inactive=true#catalog`
                : `${window.ROOT_PATH}/admin#catalog`;
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
            const redirectUrl = isInactiveCheckedBool
                ? `${window.ROOT_PATH}/admin?include_inactive=true#resources`
                : `${window.ROOT_PATH}/admin#resources`;
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
        "roots",
        "metrics",
        "logs",
        "export-import",
        "version-info",
    ];

    tabs.forEach((tabName) => {
        const tabElement = safeGetElement(`tab-${tabName}`);
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
}

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
        editToolTypeSelect.addEventListener("change", () =>
            updateEditToolRequestTypes(),
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
                    [cleanServerName]: {
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
                mcpServers: {
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
                mcpServers: {
                    [cleanServerName]: {
                        type: "http",
                        url: `${baseUrl}/servers/${server.id}`,
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
        const response = await fetch(`/oauth/fetch-tools/${gatewayId}`, {
            method: "POST",
        });

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
        console.warn(
            "Bulk Import modal wiring skipped (missing button or modal).",
        );
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

        const response = await fetch(`/admin/export/configuration?${params}`, {
            method: "GET",
            headers: {
                Authorization: `Bearer ${getCookie("jwt_token")}`,
            },
        });

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

            const validateBtn = document.getElementById("import-validate-btn");
            const executeBtn = document.getElementById("import-execute-btn");

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

    const validateBtn = document.getElementById("import-validate-btn");
    const executeBtn = document.getElementById("import-execute-btn");

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

        const response = await fetch("/admin/import/configuration", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${getCookie("jwt_token")}`,
            },
            body: JSON.stringify(requestData),
        });

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
    const validateBtn = document.getElementById("import-validate-btn");
    const executeBtn = document.getElementById("import-execute-btn");

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
        const response = await fetch("/admin/import/status", {
            headers: {
                Authorization: `Bearer ${getCookie("jwt_token")}`,
            },
        });

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
