// ===================================================================
// ENHANCED MODAL FUNCTIONS with Security and State Management
// ===================================================================

import { AppState } from "./appState.js";
import { escapeHtml } from "./security.js";
import { getCookie, safeGetElement } from "./utils.js";

// Callback registry for cleanup functions defined in other modules
const cleanupCallbacks = {
  gatewayTest: null,
  toolTest: null,
  promptTest: null,
  resourceTest: null,
  a2aTest: null,
};

export function registerModalCleanup(modalType, callback) {
  if (modalType in cleanupCallbacks) {
    cleanupCallbacks[modalType] = callback;
  }
}

export function openModal(modalId) {
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

export function closeModal(modalId, clearId = null) {
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

    // Clean up specific modal types via registered callbacks
    if (modalId === "gateway-test-modal" && cleanupCallbacks.gatewayTest) {
      cleanupCallbacks.gatewayTest();
    } else if (modalId === "tool-test-modal" && cleanupCallbacks.toolTest) {
      cleanupCallbacks.toolTest();
    } else if (modalId === "prompt-test-modal" && cleanupCallbacks.promptTest) {
      cleanupCallbacks.promptTest();
    } else if (
      modalId === "resource-test-modal" &&
      cleanupCallbacks.resourceTest
    ) {
      cleanupCallbacks.resourceTest();
    } else if (modalId === "a2a-test-modal" && cleanupCallbacks.a2aTest) {
      cleanupCallbacks.a2aTest();
    }

    modal.classList.add("hidden");
    AppState.setModalInactive(modalId);

    console.log(`✓ Closed modal: ${modalId}`);
  } catch (error) {
    console.error(`Error closing modal ${modalId}:`, error);
  }
}

export function resetModalState(modalId) {
  try {
    // Clear any dynamic content
    const modalContent = document.querySelector(
      `#${modalId} [data-dynamic-content]`
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
        // Clear inline validation error styling
        const inlineErrors = form.querySelectorAll("p[data-error-message-for]");
        inlineErrors.forEach((el) => el.classList.add("invisible"));
        // Clear red border styling from inputs
        const invalidInputs = form.querySelectorAll(
          ".border-red-500, .focus\\:ring-red-500, .dark\\:border-red-500, .dark\\:ring-red-500"
        );
        invalidInputs.forEach((el) => {
          el.classList.remove(
            "border-red-500",
            "focus:ring-red-500",
            "dark:border-red-500",
            "dark:ring-red-500"
          );
          el.setCustomValidity("");
        });
      } catch (error) {
        console.error("Error resetting form:", error);
      }
    });

    console.log(`✓ Reset modal state: ${modalId}`);
  } catch (error) {
    console.error(`Error resetting modal state ${modalId}:`, error);
  }
}

/**
 * Show a modal dialog with copyable content.
 *
 * @param {string} title - The modal title.
 * @param {string} message - The message to display (can be multi-line).
 * @param {string} type - The type of modal: 'success', 'error', or 'info'.
 */
export const showCopyableModal = function (title, message, type = "info") {
  // Remove any existing modal
  const existingModal = safeGetElement("copyable-modal-overlay");
  if (existingModal) {
    existingModal.remove();
  }

  // Color schemes based on type
  const colors = {
    success: {
      bg: "bg-green-50 dark:bg-green-900/20",
      border: "border-green-500",
      title: "text-green-800 dark:text-green-200",
      icon: `<svg class="h-6 w-6 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                </svg>`,
    },
    error: {
      bg: "bg-red-50 dark:bg-red-900/20",
      border: "border-red-500",
      title: "text-red-800 dark:text-red-200",
      icon: `<svg class="h-6 w-6 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>`,
    },
    info: {
      bg: "bg-blue-50 dark:bg-blue-900/20",
      border: "border-blue-500",
      title: "text-blue-800 dark:text-blue-200",
      icon: `<svg class="h-6 w-6 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>`,
    },
  };

  const colorScheme = colors[type] || colors.info;

  // Create modal overlay
  const overlay = document.createElement("div");
  overlay.id = "copyable-modal-overlay";
  overlay.className =
    "fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50";
  overlay.onclick = (e) => {
    if (e.target === overlay) {
      overlay.remove();
    }
  };

  // Create modal content
  const modal = document.createElement("div");
  modal.className = `${colorScheme.bg} border-l-4 ${colorScheme.border} rounded-lg shadow-xl max-w-lg w-full mx-4 overflow-hidden`;

  modal.innerHTML = `
    <div class="p-4">
      <div class="flex items-start">
        <div class="flex-shrink-0">
          ${colorScheme.icon}
        </div>
        <div class="ml-3 flex-1">
          <h3 class="text-lg font-medium ${colorScheme.title}">${escapeHtml(title)}</h3>
          <div class="mt-2">
            <pre id="copyable-modal-content" class="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-mono bg-white dark:bg-gray-800 p-3 rounded border border-gray-200 dark:border-gray-600 max-h-64 overflow-auto select-all cursor-text">${escapeHtml(message)}</pre>
          </div>
          <div class="mt-4 flex justify-end space-x-3">
            <button id="copyable-modal-copy" class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
              <svg class="h-4 w-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
              </svg>
              Copy
            </button>
            <button id="copyable-modal-close" class="inline-flex items-center px-3 py-1.5 border border-transparent text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  `;

  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  // Add event listeners
  safeGetElement("copyable-modal-close").onclick = () => overlay.remove();

  safeGetElement("copyable-modal-copy").onclick = async () => {
    const content = safeGetElement("copyable-modal-content");
    try {
      await navigator.clipboard.writeText(content.textContent);
      const copyBtn = safeGetElement("copyable-modal-copy");
      const originalText = copyBtn.innerHTML;
      copyBtn.innerHTML = `<svg class="h-4 w-4 mr-1.5 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                </svg> Copied!`;
      setTimeout(() => {
        copyBtn.innerHTML = originalText;
      }, 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
      // Fallback: select the text
      const range = document.createRange();
      range.selectNodeContents(content);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    }
  };

  // Close on Escape key
  const handleEscape = (e) => {
    if (e.key === "Escape") {
      overlay.remove();
      document.removeEventListener("keydown", handleEscape);
    }
  };
  document.addEventListener("keydown", handleEscape);
};

// ===================================================================
// MCP REGISTRY MODAL FUNCTIONS
// ===================================================================

// Define modal functions in global scope for MCP Registry
export const showApiKeyModal = function (serverId, serverName, serverUrl) {
  const modal = safeGetElement("api-key-modal");
  if (modal) {
    safeGetElement("modal-server-id").value = serverId;
    safeGetElement("modal-server-name").textContent = serverName;
    safeGetElement("modal-custom-name").placeholder = serverName;
    modal.classList.remove("hidden");
  }
};

export const closeApiKeyModal = function () {
  const modal = safeGetElement("api-key-modal");
  if (modal) {
    modal.classList.add("hidden");
  }
  const form = safeGetElement("api-key-form");
  if (form) {
    form.reset();
  }
};

export const submitApiKeyForm = function (event) {
  event.preventDefault();
  const serverId = safeGetElement("modal-server-id").value;
  const customName = safeGetElement("modal-custom-name").value;
  const apiKey = safeGetElement("modal-api-key").value;

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
        closeApiKeyModal();
        // Reload the catalog
        if (window.htmx && window.htmx.ajax) {
          window.htmx.ajax("GET", `${rootPath}/admin/mcp-registry/partial`, {
            target: "#mcp-registry-content",
            swap: "innerHTML",
          });
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
export const toggleGrpcTlsFields = function () {
  const tlsEnabled = safeGetElement("grpc-tls-enabled")?.checked || false;
  const certField = safeGetElement("grpc-tls-cert-field");
  const keyField = safeGetElement("grpc-tls-key-field");

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
export const viewGrpcMethods = function (serviceId) {
  const rootPath = window.ROOT_PATH || "";

  fetch(`${rootPath}/admin/grpc/${serviceId}/methods`, {
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
          "No methods discovered for this service. Try re-reflecting the service."
        );
      }
    })
    .catch((error) => {
      alert("Error fetching methods: " + error);
    });
};