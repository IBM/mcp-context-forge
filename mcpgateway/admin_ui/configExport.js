// ===============================================
// CONFIG EXPORT FUNCTIONALITY
// ===============================================

import { closeModal, openModal } from "./modals.js";
import {
  fetchWithTimeout,
  handleFetchError,
  safeGetElement,
  showErrorMessage,
  showSuccessMessage,
} from "./utils.js";

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
export const showConfigSelectionModal = function (serverId, serverName) {
  currentServerId = serverId;
  currentServerName = serverName;

  const serverNameDisplay = safeGetElement("server-name-display");
  if (serverNameDisplay) {
    serverNameDisplay.textContent = serverName;
  }

  openModal("config-selection-modal");
};
/**
 * Build MCP_SERVER_CATALOG_URL for a given server
 * @param {Object} server
 * @returns {string}
 */
export const getCatalogUrl = function (server) {
  const currentHost = window.location.hostname;
  const currentPort =
    window.location.port ||
    (window.location.protocol === "https:" ? "443" : "80");
  const protocol = window.location.protocol;

  const baseUrl = `${protocol}//${currentHost}${
    currentPort !== "80" && currentPort !== "443" ? ":" + currentPort : ""
  }`;

  return `${baseUrl}/servers/${server.id}`;
};

/**
 * Generate and show configuration for selected type
 * @param {string} configType - Configuration type: 'stdio', 'sse', or 'http'
 */
export const generateAndShowConfig = async function (configType) {
  try {
    console.log(
      `Generating ${configType} config for server ${currentServerId}`
    );

    // First, fetch the server details
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/servers/${currentServerId}`
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
};

/**
 * Export server configuration in specified format
 * @param {string} serverId - The server UUID
 * @param {string} configType - Configuration type: 'stdio', 'sse', or 'http'
 */
export const exportServerConfig = async function (serverId, configType) {
  try {
    console.log(`Exporting ${configType} config for server ${serverId}`);

    // First, fetch the server details
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/servers/${serverId}`
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
};

/**
 * Generate configuration object based on server and type
 * @param {Object} server - Server object from API
 * @param {string} configType - Configuration type
 * @returns {Object} - Generated configuration object
 */
export const generateConfig = function (server, configType) {
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
            type: "streamable-http",
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
};

/**
 * Show the config display modal with generated configuration
 * @param {Object} server - Server object
 * @param {string} configType - Configuration type
 * @param {Object} config - Generated configuration
 */
export const showConfigDisplayModal = function (server, configType, config) {
  const descriptions = {
    stdio:
      "Configuration for Claude Desktop, CLI tools, and stdio-based MCP clients",
    sse: "Configuration for LangChain, LlamaIndex, and other SSE-based frameworks",
    http: "Configuration for REST clients and HTTP-based MCP integrations",
  };

  const usageInstructions = {
    stdio:
      "Save as .mcp.json in your user directory or use in Claude Desktop settings",
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
};

/**
 * Copy configuration to clipboard
 */
export const copyConfigToClipboard = async function () {
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
};

/**
 * Download configuration as JSON file
 */
export const downloadConfig = function () {
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
};

/**
 * Go back to config selection modal
 */
export const goBackToSelection = function () {
  closeModal("config-display-modal");
  openModal("config-selection-modal");
};
