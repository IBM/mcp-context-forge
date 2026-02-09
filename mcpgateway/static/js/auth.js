import { MASKED_AUTH_VALUE } from './constants.js';
import { safeGetElement, showSuccessMessage, showErrorMessage } from './utils.js';

// ===================================================================
// MULTI-HEADER AUTHENTICATION MANAGEMENT
// ===================================================================
/**
 * Toggle masking for sensitive text inputs (passwords, tokens, headers)
 * @param {HTMLElement|string} inputOrId - Target input element or its ID
 * @param {HTMLElement} button - Button triggering the toggle
 */
export function toggleInputMask(inputOrId, button) {
    const input =
        typeof inputOrId === "string"
            ? safeGetElement(inputOrId)
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

/**
 * Add a new authentication header row to the specified container
 * @param {string} containerId - ID of the container to add the header row to
 */
export function addAuthHeader(containerId, options = {}) {
    const container = safeGetElement(containerId);
    if (!container) {
        console.error(`Container with ID ${containerId} not found`);
        return;
    }

    /**
     * Global counter for unique header IDs
     */
    let headerCounter = 0;
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
                oninput="Admin.updateAuthHeadersJSON('${containerId}')"
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
                    oninput="Admin.updateAuthHeadersJSON('${containerId}')"
                />
                <button
                    type="button"
                    class="absolute inset-y-0 right-0 flex items-center px-2 text-xs font-medium text-indigo-600 hover:text-indigo-800 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 dark:text-indigo-300"
                    onclick="Admin.toggleInputMask('${valueInputId}', this)"
                    aria-pressed="false"
                    aria-label="Show header value"
                >
                    Show
                </button>
            </div>
        </div>
        <button
            type="button"
            onclick="Admin.removeAuthHeader('${headerId}', '${containerId}')"
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
export function removeAuthHeader(headerId, containerId) {
    const headerRow = safeGetElement(headerId);
    if (headerRow) {
        headerRow.remove();
        updateAuthHeadersJSON(containerId);
    }
}

/**
 * Update the JSON representation of authentication headers
 * @param {string} containerId - ID of the container with headers
 */
export function updateAuthHeadersJSON(containerId) {
    const container = safeGetElement(containerId);
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
        jsonInput = safeGetElement("auth-headers-json");
    } else if (containerId === "auth-headers-container-gw") {
        jsonInput = safeGetElement("auth-headers-json-gw");
    } else if (containerId === "auth-headers-container-a2a") {
        jsonInput = safeGetElement("auth-headers-json-a2a");
    } else if (containerId === "edit-auth-headers-container") {
        jsonInput = safeGetElement("edit-auth-headers-json");
    } else if (containerId === "auth-headers-container-gw-edit") {
        jsonInput = safeGetElement("auth-headers-json-gw-edit");
    } else if (containerId === "auth-headers-container-a2a-edit") {
        jsonInput = safeGetElement("auth-headers-json-a2a-edit");
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
export function loadAuthHeaders(containerId, headers, options = {}) {
    const container = safeGetElement(containerId);
    if (!container) {
        return;
    }

    const jsonInput = (() => {
        if (containerId === "auth-headers-container") {
            return safeGetElement("auth-headers-json");
        }
        if (containerId === "auth-headers-container-gw") {
            return safeGetElement("auth-headers-json-gw");
        }
        if (containerId === "auth-headers-container-a2a") {
            return safeGetElement("auth-headers-json-a2a");
        }
        if (containerId === "edit-auth-headers-container") {
            return safeGetElement("edit-auth-headers-json");
        }
        if (containerId === "auth-headers-container-gw-edit") {
            return safeGetElement("auth-headers-json-gw-edit");
        }
        if (containerId === "auth-headers-container-a2a-edit") {
            return safeGetElement("auth-headers-json-a2a-edit");
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

/**
 * Fetch tools from MCP server after OAuth completion for Authorization Code flow
 * @param {string} gatewayId - ID of the gateway to fetch tools for
 * @param {string} gatewayName - Name of the gateway for display purposes
 */
export async function fetchToolsForGateway(gatewayId, gatewayName) {
    const button = safeGetElement(`fetch-tools-${gatewayId}`);
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

// ===================================================================
// AUTH HANDLING
// ===================================================================

export function handleAuthTypeSelection(
    value,
    basicFields,
    bearerFields,
    headersFields,
    oauthFields,
    queryParamFields,
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

    // Hide query param fields if they exist
    if (queryParamFields) {
        queryParamFields.style.display = "none";
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
                    const container = safeGetElement(containerId);
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
        case "query_param":
            if (queryParamFields) {
                queryParamFields.style.display = "block";
            }
            break;
        default:
            // All fields already hidden
            break;
    }
}
  
export const handleAuthTypeChange = function () {
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
  const queryParamFields = safeGetElement(
    `auth-query_param-fields-${prefix}`,
  );
  
  // Hide all auth sections first
  [
    basicFields,
    bearerFields,
    headersFields,
    oauthFields,
    queryParamFields,
  ].forEach((section) => {
    if (section) {
      section.style.display = "none";
    }
  });
  
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
    case "query_param":
    if (queryParamFields) {
      queryParamFields.style.display = "block";
    }
    break;
    default:
    // "none" or unknown type — keep everything hidden
    break;
  }
}

export const handleOAuthGrantTypeChange = function () {
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

export const handleEditOAuthGrantTypeChange = function () {
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