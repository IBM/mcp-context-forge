
import { closeModal, openModal } from "./modals";
import { escapeHtml } from "./security";
import { getAuthToken } from "./tokens";
import { fetchWithTimeout, safeGetElement, showErrorMessage } from "./utils";

// ===================================================================
// A2A AGENT TEST MODAL FUNCTIONALITY
// ===================================================================

let a2aTestFormHandler = null;
let a2aTestCloseHandler = null;

/**
 * Open A2A test modal with agent details
 * @param {string} agentId - ID of the agent to test
 * @param {string} agentName - Name of the agent for display
 * @param {string} endpointUrl - Endpoint URL of the agent
 */
export const testA2AAgent = async function (agentId, agentName, endpointUrl) {
  try {
    console.log("Opening A2A test modal for:", agentName);

    // Clean up any existing event listeners
    cleanupA2ATestModal();

    // Open the modal
    openModal("a2a-test-modal");

    // Set modal title and description
    const titleElement = safeGetElement("a2a-test-modal-title");
    const descElement = safeGetElement("a2a-test-modal-description");
    const agentIdInput = safeGetElement("a2a-test-agent-id");
    const queryInput = safeGetElement("a2a-test-query");
    const resultDiv = safeGetElement("a2a-test-result");

    if (titleElement) {
      titleElement.textContent = `Test A2A Agent: ${agentName}`;
    }
    if (descElement) {
      descElement.textContent = `Endpoint: ${endpointUrl}`;
    }
    if (agentIdInput) {
      agentIdInput.value = agentId;
    }
    if (queryInput) {
      // Reset to default value
      queryInput.value = "Hello from MCP Gateway Admin UI test!";
    }
    if (resultDiv) {
      resultDiv.classList.add("hidden");
    }

    // Set up form submission handler
    const form = safeGetElement("a2a-test-form");
    if (form) {
      a2aTestFormHandler = async (e) => {
        await handleA2ATestSubmit(e);
      };
      form.addEventListener("submit", a2aTestFormHandler);
    }

    // Set up close button handler
    const closeButton = safeGetElement("a2a-test-close");
    if (closeButton) {
      a2aTestCloseHandler = () => {
        handleA2ATestClose();
      };
      closeButton.addEventListener("click", a2aTestCloseHandler);
    }
  } catch (error) {
    console.error("Error setting up A2A test modal:", error);
    showErrorMessage("Failed to open A2A test modal");
  }
};

/**
 * Handle A2A test form submission
 * @param {Event} e - Form submit event
 */
export const handleA2ATestSubmit = async function (e) {
  e.preventDefault();

  const loading = safeGetElement("a2a-test-loading");
  const responseDiv = safeGetElement("a2a-test-response-json");
  const resultDiv = safeGetElement("a2a-test-result");
  const testButton = safeGetElement("a2a-test-submit");

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

    const agentId = safeGetElement("a2a-test-agent-id")?.value;
    const query =
      safeGetElement("a2a-test-query")?.value ||
      "Hello from MCP Gateway Admin UI test!";

    if (!agentId) {
      throw new Error("Agent ID is missing");
    }

    // Get auth token
    const token = await getAuthToken();
    const headers = { "Content-Type": "application/json" };
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    } else {
      // Fallback to basic auth if JWT not available
      console.warn("JWT token not found, attempting basic auth fallback");
      headers.Authorization = "Basic " + btoa("admin:changeme");
    }

    // Send test request with user query
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/a2a/${agentId}/test`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({ query }),
      },
      window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const result = await response.json();

    // Display result
    const isSuccess = result.success && !result.error;
    const icon = isSuccess ? "✅" : "❌";
    const title = isSuccess ? "Test Successful" : "Test Failed";

    let bodyHtml = "";
    if (result.result) {
      bodyHtml = `<details open>
                      <summary class='cursor-pointer font-medium'>Response</summary>
                      <pre class="text-sm px-4 max-h-96 dark:bg-gray-800 dark:text-gray-100 overflow-auto whitespace-pre-wrap">${escapeHtml(JSON.stringify(result.result, null, 2))}</pre>
                  </details>`;
    }

    responseDiv.innerHTML = `
                  <div class="p-3 rounded ${isSuccess ? "bg-green-50 dark:bg-green-900/20" : "bg-red-50 dark:bg-red-900/20"}">
                      <h4 class="font-bold ${isSuccess ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"}">${icon} ${title}</h4>
                      ${result.error ? `<p class="text-red-600 dark:text-red-400 mt-2">Error: ${escapeHtml(result.error)}</p>` : ""}
                      ${bodyHtml}
                  </div>
              `;
  } catch (error) {
    console.error("A2A test error:", error);
    if (responseDiv) {
      responseDiv.innerHTML = `<div class="text-red-600 dark:text-red-400 p-4 bg-red-50 dark:bg-red-900/20 rounded">❌ Error: ${escapeHtml(error.message)}</div>`;
    }
  } finally {
    if (loading) {
      loading.classList.add("hidden");
    }
    if (resultDiv) {
      resultDiv.classList.remove("hidden");
    }
    if (testButton) {
      testButton.disabled = false;
      testButton.textContent = "Test Agent";
    }
  }
};

/**
 * Handle A2A test modal close
 */
export const handleA2ATestClose = function () {
  try {
    // Reset form
    const form = safeGetElement("a2a-test-form");
    if (form) {
      form.reset();
    }

    // Clear response
    const responseDiv = safeGetElement("a2a-test-response-json");
    const resultDiv = safeGetElement("a2a-test-result");
    if (responseDiv) {
      responseDiv.innerHTML = "";
    }
    if (resultDiv) {
      resultDiv.classList.add("hidden");
    }

    // Close modal
    closeModal("a2a-test-modal");
  } catch (error) {
    console.error("Error closing A2A test modal:", error);
  }
};

/**
 * Clean up A2A test modal event listeners
 */
export const cleanupA2ATestModal = function () {
  try {
    const form = safeGetElement("a2a-test-form");
    const closeButton = safeGetElement("a2a-test-close");

    if (form && a2aTestFormHandler) {
      form.removeEventListener("submit", a2aTestFormHandler);
      a2aTestFormHandler = null;
    }

    if (closeButton && a2aTestCloseHandler) {
      closeButton.removeEventListener("click", a2aTestCloseHandler);
      a2aTestCloseHandler = null;
    }

    console.log("✓ Cleaned up A2A test modal listeners");
  } catch (error) {
    console.error("Error cleaning up A2A test modal:", error);
  }
};
