((Admin) => {
    // ===================================================================
    // UTILITY FUNCTIONS - Define these FIRST before anything else

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
    *
    * @example
    * const { init: initSearch, reset: resetSearch } = Admin.createMemoizedInit(
    *     initializeSearchInputs,
    *     300,
    *     'SearchInputs'
    * );
    *
    * // Use the memoized version
    * Admin.initSearch();
    *
    * // Reset when needed (e.g., tab switch)
    * Admin.resetSearch();
    * Admin.initSearch();
    */
    Admin.createMemoizedInit = function (fn, debounceMs = 300, name = "Init") {
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
                console.log(
                    `⏳ ${name} initialization already in progress, skipping...`,
                );
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
    };

    // ===================================================================
    // Safe element getter with logging
    Admin.safeGetElement = function (id, suppressWarning = false) {
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
    };

    // Check for inative items
    Admin.isInactiveChecked = function (type) {
        const checkbox = Admin.safeGetElement(`show-inactive-${type}`);
        return checkbox ? checkbox.checked : false;
    };

    // Enhanced fetch with timeout and better error handling
    Admin.fetchWithTimeout = async function (
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
    };

    // Enhanced error handler for fetch operations
    Admin.handleFetchError = function (error, operation = "operation") {
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
    };

    // Show user-friendly error messages
    Admin.showErrorMessage = function (message, elementId = null) {
        console.error("Error:", message);

        if (elementId) {
            const element = Admin.safeGetElement(elementId);
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
    };

    // Show success messages
    Admin.showSuccessMessage = function (message) {
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
    };

    // ----- URI Template Parsing -------------- //
    Admin.parseUriTemplate = function (template) {
        const regex = /{([^}]+)}/g;
        const fields = [];
        let match;

        while ((match = regex.exec(template)) !== null) {
            fields.push(match[1]); // capture inside {}
        }
        return fields;
    };
})(window.Admin)