((Admin) => {
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

    Admin.escapeHtml = function (unsafe) {
        if (unsafe === null || unsafe === undefined) {
            return "";
        }
        return Admin.String(unsafe)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;")
            .replace(/`/g, "&#x60;")
            .replace(/\//g, "&#x2F;"); // Extra protection against script injection
    };

    /**
    * Extract a human-readable error message from an API error response.
    * Handles both string errors and Pydantic validation error arrays.
    * @param {Object} error - The parsed JSON error response
    * @param {string} fallback - Fallback message if no detail found
    * @returns {string} Human-readable error message
    */
    Admin.extractApiError = function (error, fallback = "An error occurred") {
        if (!error || !error.detail) {
            return fallback;
        }
        if (typeof error.detail === "string") {
            return error.detail;
        }
        if (Array.isArray(error.detail)) {
            // Pydantic validation errors - extract messages
            return error.detail
                .map((err) => err.msg || JSON.stringify(err))
                .join("; ");
        }
        return fallback;
    };

    /**
    * Safely parse an error response, handling both JSON and plain text bodies.
    * @param {Response} response - The fetch Response object
    * @param {string} fallback - Fallback message if parsing fails
    * @returns {Promise<string>} Human-readable error message
    */
    Admin.parseErrorResponse = async function (response, fallback = "An error occurred") {
        try {
            const contentType = response.headers.get("content-type") || "";
            if (contentType.includes("application/json")) {
                const error = await response.json();
                return Admin.extractApiError(error, fallback);
            }
            // Non-JSON response - try to get text
            const text = await response.text();
            return text || fallback;
        } catch {
            return fallback;
        }
    };

    /**
    * Validate a passthrough header name and value
    * @param {string} name - Header name to validate
    * @param {string} value - Header value to validate
    * @returns {Object} Validation result with 'valid' boolean and 'error' message
    */
    Admin.validatePassthroughHeader = function (name, value) {
        // Validate header name
        if (!Admin.HEADER_NAME_REGEX.test(name)) {
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
        if (value.length > Admin.MAX_HEADER_VALUE_LENGTH) {
            return {
                valid: false,
                error: `Header value too long (${value.length} chars, max ${Admin.MAX_HEADER_VALUE_LENGTH})`,
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
    };

    /**
    * SECURITY: Validate input names to prevent XSS and ensure clean data
    */
    Admin.validateInputName = function (name, type = "input") {
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

        if (cleaned.length > window.MAX_NAME_LENGTH) {
            return {
                valid: false,
                error: `${type} must be ${window.MAX_NAME_LENGTH} characters or less`,
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
    };

    /**
    * Extracts content from various formats with fallback
    */

    /**
    Admin.extractContent = function (content, fallback = "") {
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
        return Admin.String(content || fallback);
    };
    */

    /**
    * SECURITY: Validate URL inputs
    */
    Admin.validateUrl = function (url, label = "") {
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
    };

    /**
    * SECURITY: Validate JSON input
    */
    Admin.validateJson = function (jsonString, fieldName = "JSON") {
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
    };

    /**
    * SECURITY: Safely set innerHTML ONLY for trusted backend content
    * For user-generated content, use textContent instead
    */
    Admin.safeSetInnerHTML = function (element, htmlContent, isTrusted = false) {
        if (!isTrusted) {
            console.error("Attempted to set innerHTML with untrusted content");
            element.textContent = htmlContent; // Fallback to safe text
            return;
        }
        element.innerHTML = htmlContent;
    };
})(window.Admin)