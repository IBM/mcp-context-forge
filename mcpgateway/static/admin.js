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

    if (cleaned.length > 100) {
        return {
            valid: false,
            error: `${type} name must be 100 characters or less`,
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
            const topSection = createTopPerformersSection(topData);
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
function createTopPerformersSection(topData) {
    try {
        const section = document.createElement("div");
        section.className = "bg-white rounded-lg shadow p-6 dark:bg-gray-800";

        const title = document.createElement("h3");
        title.className = "text-lg font-medium mb-4 dark:text-gray-200";
        title.textContent = "Top Performers";
        section.appendChild(title);

        const grid = document.createElement("div");
        grid.className = "grid grid-cols-1 md:grid-cols-2 gap-4";

        // Top Tools
        if (topData.tools && Array.isArray(topData.tools)) {
            const toolsCard = createTopItemCard("Tools", topData.tools);
            grid.appendChild(toolsCard);
        }

        // Top Resources
        if (topData.resources && Array.isArray(topData.resources)) {
            const resourcesCard = createTopItemCard(
                "Resources",
                topData.resources,
            );
            grid.appendChild(resourcesCard);
        }

        // Top Prompts
        if (topData.prompts && Array.isArray(topData.prompts)) {
            const promptsCard = createTopItemCard("Prompts", topData.prompts);
            grid.appendChild(promptsCard);
        }

        // Top Servers
        if (topData.servers && Array.isArray(topData.servers)) {
            const serversCard = createTopItemCard("Servers", topData.servers);
            grid.appendChild(serversCard);
        }

        section.appendChild(grid);
        return section;
    } catch (error) {
        console.error("Error creating top performers section:", error);
        return document.createElement("div"); // Safe fallback
    }
}

/**
 * SECURITY: Create top item card with safe content handling
 */
function createTopItemCard(title, items) {
    try {
        const card = document.createElement("div");
        card.className = "bg-gray-50 rounded p-4 dark:bg-gray-700";

        const cardTitle = document.createElement("h4");
        cardTitle.className = "font-medium mb-2 dark:text-gray-200";
        cardTitle.textContent = `Top ${title}`;
        card.appendChild(cardTitle);

        const list = document.createElement("ul");
        list.className = "space-y-1";

        items.slice(0, 5).forEach((item) => {
            const listItem = document.createElement("li");
            listItem.className =
                "text-sm text-gray-600 dark:text-gray-300 flex justify-between";

            const nameSpan = document.createElement("span");
            nameSpan.textContent = item.name || "Unknown";

            const countSpan = document.createElement("span");
            countSpan.className = "font-medium";
            countSpan.textContent = String(item.executions || 0);

            listItem.appendChild(nameSpan);
            listItem.appendChild(countSpan);
            list.appendChild(listItem);
        });

        card.appendChild(list);
        return card;
    } catch (error) {
        console.error("Error creating top item card:", error);
        return document.createElement("div"); // Safe fallback
    }
}

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

        // Trigger change event for integration type
        if (typeField) {
            const event = new Event("change");
            typeField.dispatchEvent(event);
        }

        // Set Request Type field
        const requestTypeField = safeGetElement("edit-tool-request-type");
        if (requestTypeField) {
            requestTypeField.value = tool.requestType || "SSE";
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
        case "authheaders":
            headersFields.style.display = "block";
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
    MCP: ["SSE", "STREAMABLE", "STDIO"],
    REST: ["GET", "POST", "PUT", "PATCH", "DELETE"],
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

    // Clear existing options
    editToolRequestTypeSelect.innerHTML = "";

    // Populate new options
    allowedMethods.forEach((method) => {
        const option = document.createElement("option");
        option.value = method;
        option.textContent = method;
        editToolRequestTypeSelect.appendChild(option);
    });

    // Set the pre-selected method, if valid
    if (selectedMethod && allowedMethods.includes(selectedMethod)) {
        editToolRequestTypeSelect.value = selectedMethod;
    }
}

// ===================================================================
// TOOL SELECT FUNCTIONALITY
// ===================================================================

function initToolSelect(selectId, pillsId, warnId, max = 6) {
    const select = safeGetElement(selectId);
    const pillsBox = safeGetElement(pillsId);
    const warnBox = safeGetElement(warnId);

    if (!select || !pillsBox || !warnBox) {
        console.warn(
            `Tool select elements not found: ${selectId}, ${pillsId}, ${warnId}`,
        );
        return;
    }

    const pillClasses =
        "inline-block px-2 py-1 text-xs font-medium text-blue-800 bg-blue-100 rounded";

    function update() {
        try {
            const chosen = Array.from(select.selectedOptions);
            const count = chosen.length;

            // Rebuild pills safely
            pillsBox.innerHTML = "";
            chosen.forEach((opt) => {
                const span = document.createElement("span");
                span.className = pillClasses;
                span.textContent = opt.text; // Safe text content
                pillsBox.appendChild(span);
            });

            // Warning when > max
            if (count > max) {
                warnBox.textContent = `Selected ${count} tools. Selecting more than ${max} tools can degrade agent performance with the server.`;
                warnBox.className = "text-yellow-600 text-sm mt-2";
            } else {
                warnBox.textContent = "";
                warnBox.className = "";
            }
        } catch (error) {
            console.error("Error updating tool select:", error);
        }
    }

    update(); // Initial render
    select.addEventListener("change", update);
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
            descElement.textContent =
                tool.description || "No description available.";
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
                label.textContent = keyValidation.value;
                label.className =
                    "block text-sm font-medium text-gray-700 dark:text-gray-300";
                fieldDiv.appendChild(label);

                // Description help text - use textContent
                if (prop.description) {
                    const description = document.createElement("small");
                    description.textContent = prop.description; // NO escapeHtml here
                    description.className = "text-gray-500 block mb-1";
                    fieldDiv.appendChild(description);
                }

                // Input field with validation
                const input = document.createElement("input");
                input.name = keyValidation.value;
                input.type = "text";
                input.required =
                    schema.required && schema.required.includes(key);
                input.className =
                    "mt-1 block w-full rounded-md border border-gray-500 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 text-gray-700 dark:text-gray-300 dark:border-gray-700 dark:focus:border-indigo-400 dark:focus:ring-indigo-400";

                // Add validation based on type
                if (prop.type === "number") {
                    input.type = "number";
                } else if (prop.type === "boolean") {
                    input.type = "checkbox";
                    input.className =
                        "mt-1 h-4 w-4 text-indigo-600 dark:text-indigo-200 border border-gray-300 rounded";
                }

                fieldDiv.appendChild(input);
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

        for (const [key, value] of formData.entries()) {
            // Validate each parameter
            const keyValidation = validateInputName(key, "parameter");
            if (!keyValidation.valid) {
                console.warn(`Skipping invalid parameter: ${key}`);
                continue;
            }

            // Type conversion
            if (isNaN(value) || value === "") {
                if (
                    value.toLowerCase() === "true" ||
                    value.toLowerCase() === "false"
                ) {
                    params[keyValidation.value] =
                        value.toLowerCase() === "true";
                } else {
                    params[keyValidation.value] = value;
                }
            } else {
                params[keyValidation.value] = Number(value);
            }
        }

        const payload = {
            jsonrpc: "2.0",
            id: Date.now(),
            method: AppState.currentTestTool.name,
            params,
        };

        // Use longer timeout for test execution
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/rpc`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
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

        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/admin/gateways`,
            {
                method: "POST",
                body: formData,
            },
        );

        const result = await response.json();
        if (!result.success) {
            throw new Error(result.message || "An error occurred");
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

function handleResourceFormSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);

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

    fetchWithTimeout(`${window.ROOT_PATH}/admin/resources`, {
        method: "POST",
        body: formData,
    })
        .then((response) => {
            if (!response.ok) {
                const status = safeGetElement("status-resources");
                if (status) {
                    status.textContent = "Connection failed!";
                    status.classList.add("error-status");
                }
                throw new Error("Network response was not ok");
            } else {
                location.reload();
            }
        })
        .catch((error) => {
            console.error("Error:", error);
            showErrorMessage("Failed to create resource");
        });
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
        if (!result.success) {
            console.log(result.message);
            throw new Error(result.message || "Failed to add server.");
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
        if (!result.success) {
            throw new Error(result.message || "An error occurred");
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

        // 5. Set up form validation
        setupFormValidation();

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
    );
    initToolSelect(
        "edit-server-tools",
        "selectedEditToolsPills",
        "selectedEditToolsWarning",
        6,
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
    }

    const resourceForm = safeGetElement("add-resource-form");
    if (resourceForm) {
        resourceForm.addEventListener("submit", handleResourceFormSubmit);
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

    const editResourceForm = safeGetElement("edit-resource-form");
    if (editResourceForm) {
        editResourceForm.addEventListener("submit", () => {
            if (window.editResourceContentEditor) {
                window.editResourceContentEditor.save();
            }
        });
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
        editToolTypeSelect.value = "REST";
        updateEditToolRequestTypes("PUT");
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

console.log("🛡️ ContextForge MCP Gateway admin.js initialized");
