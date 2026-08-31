import {
  escapeHtml,
  escapeHtmlChat,
  logRestrictedContext,
} from "./security.js";
import {
  fetchWithTimeout,
  getCookie,
  safeGetElement,
  showErrorMessage,
  showNotification,
} from "./utils.js";

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
  autoScroll: true,
};

/**
 * Initialize LLM Chat when tab is shown
 */
export const initializeLLMChat = function () {
  console.log("Initializing LLM Chat...");

  // Generate or retrieve user ID
  llmChatState.userId = generateUserId();

  // Restore previously selected server (if any) from sessionStorage
  try {
    const persistedServerId = sessionStorage.getItem(
      "llm_chat_selected_server_id"
    );
    const persistedServerName = sessionStorage.getItem(
      "llm_chat_selected_server_name"
    );
    if (persistedServerId) {
      llmChatState.selectedServerId = persistedServerId;
      if (persistedServerName) {
        llmChatState.selectedServerName = persistedServerName;
      }
    }
  } catch (e) {
    // sessionStorage may be unavailable in some environments
    console.warn("Could not restore persisted LLM server selection:", e);
  }

  // Load servers if not already loaded
  const serversList = safeGetElement("llm-chat-servers-list");
  if (serversList && serversList.children.length <= 1) {
    loadVirtualServersForChat();
  }

  // Load available LLM models from LLM Settings
  loadLLMModels();

  // Initialize chat input resize behavior
  initializeChatInputResize();

  // Initialize scroll handling
  initializeChatScroll();
};

/**
 * Initialize scroll listener for auto-scroll management
 */
const initializeChatScroll = function () {
  const container = safeGetElement("chat-messages-container");
  if (container) {
    container.addEventListener("scroll", () => {
      // Check if user is near bottom (within 50px)
      const isAtBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight <
        50;
      llmChatState.autoScroll = isAtBottom;
    });
  }
};

/**
 * Generate a unique user ID for the session
 */
const getAuthenticatedUserId = function () {
  const currentUser = window.CURRENT_USER;
  if (!currentUser) {
    return "";
  }
  if (typeof currentUser === "string") {
    return currentUser;
  }
  if (typeof currentUser === "object") {
    return (
      currentUser.id ||
      currentUser.user_id ||
      currentUser.sub ||
      currentUser.email ||
      ""
    );
  }
  return "";
};

const generateUserId = function () {
  const authenticatedUserId = getAuthenticatedUserId();
  if (authenticatedUserId) {
    try {
      sessionStorage.setItem("llm_chat_user_id", authenticatedUserId);
    } catch (e) {
      logRestrictedContext(e);
    }
    return authenticatedUserId;
  }
  // Check if user ID exists in session storage
  let userId;
  try {
    userId = sessionStorage.getItem("llm_chat_user_id");
  } catch (e) {
    console.debug("sessionStorage unavailable:", e.message);
  }
  if (!userId) {
    // Generate a unique ID
    userId = `user_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    try {
      sessionStorage.setItem("llm_chat_user_id", userId);
    } catch (e) {
      logRestrictedContext(e);
    }
  }
  return userId;
};

/**
 * Load virtual servers for chat
 */
export const loadVirtualServersForChat = async function () {
  const serversList = safeGetElement("llm-chat-servers-list");
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
        credentials: "same-origin", // pragma: allowlist secret
      }
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    let data = await response.json();
    // Handle new paginated response format
    if ("data" in data) {
      data = data.data;
    }
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
        const isActive =
          server.isActive !== undefined ? server.isActive : server.enabled;
        const visibility = server.visibility || "public";
        const requiresToken = visibility === "team" || visibility === "private";

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
                        data-action="select-server"
                        data-server-id="${server.id}"
                        data-server-name="${escapeHtml(server.name)}"
                        data-is-active="${isActive}"
                        data-requires-token="${requiresToken}"
                        data-visibility="${visibility}"
                        style="position: relative;">
                        ${
  requiresToken
    ? `
                      <div data-role="tooltip"
                        class="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 bg-gray-500 text-white text-[10px] rounded py-1 px-5 z-30 transition-opacity duration-200 ease-in pointer-events-none"
                        style="opacity: 0; visibility: hidden;">
                        ${tooltipMessage}
                        <div class="absolute left-1/2 -translate-x-1/2 -bottom-[5px] w-0 h-0 border-l-[5px] border-r-[5px] border-t-[5px] border-l-transparent border-r-transparent border-t-gray-500"></div>
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
      const tooltip = item.querySelector('[data-role="tooltip"]');
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

    // Attach click listeners (inline onclick stripped by innerHTML sanitizer)
    serversList
      .querySelectorAll('[data-action="select-server"]')
      .forEach((item) => {
        item.addEventListener("click", () => {
          selectServerForChat(
            item.dataset.serverId,
            item.dataset.serverName,
            item.dataset.isActive === "true",
            item.dataset.requiresToken === "true",
            item.dataset.visibility,
          );
        });
      });
  } catch (error) {
    console.error("Error loading servers for chat:", error);
    serversList.innerHTML =
      '<div class="text-center text-red-600 dark:text-red-400 text-sm py-4">Failed to load servers: ' +
      escapeHtml(error.message) +
      "</div>";
  }
};

/**
 * Select a server for chat
 */

export const selectServerForChat = async function (
  serverId,
  serverName,
  isActive,
  requiresToken,
  serverVisibility
) {
  if (!isActive) {
    showErrorMessage(
      "This server is inactive. Please select an active server."
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
      `Authentication Required\n\n${visibilityMessage}\n\nPlease enter the access token for "${serverName}":`
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

  // Persist selection so it survives tab reloads within the session
  try {
    sessionStorage.setItem("llm_chat_selected_server_id", serverId);
    sessionStorage.setItem("llm_chat_selected_server_name", serverName);
  } catch (e) {
    // sessionStorage may be unavailable (e.g. privacy mode); ignore silently
    console.warn("Could not persist selected LLM server:", e);
  }

  // Update toolbar dropdown button text
  const selectedServerName = safeGetElement("selected-server-name");
  if (selectedServerName) {
    selectedServerName.textContent = serverName;
  }

  // Update UI to show selected server in dropdown list
  const serverItems = document.querySelectorAll(".server-item");
  serverItems.forEach((item) => {
    if (item.dataset.serverId === serverId) {
      item.classList.add(
        "border-indigo-500",
        "bg-indigo-50",
        "dark:bg-indigo-900"
      );
      item.classList.remove("border-gray-200", "dark:border-gray-600");
    } else {
      item.classList.remove(
        "border-indigo-500",
        "bg-indigo-50",
        "dark:bg-indigo-900"
      );
      item.classList.add("border-gray-200", "dark:border-gray-600");
    }
  });

  // Close the dropdown
  const dropdownBtn = safeGetElement("llm-server-dropdown-btn");
  if (dropdownBtn) {
    // Trigger click outside to close dropdown
    const event = new Event("click");
    document.body.dispatchEvent(event);
  }

  // Enable connect button if provider is selected
  updateConnectButtonState();

  console.log(
    `Selected server: ${serverName} (${serverId}), Visibility: ${serverVisibility}, Token: ${requiresToken ? "Required" : "Not required"}`
  );
};

/**
 * Load available LLM models from the gateway's LLM Settings
 */
const loadLLMModels = async function () {
  const modelSelect = safeGetElement("llm-model-select");
  if (!modelSelect) {
    return;
  }

  try {
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/llmchat/gateway/models`
    );
    if (!response.ok) {
      throw new Error("Failed to load models");
    }
    const data = await response.json();

    // Clear existing options except the placeholder
    modelSelect.innerHTML =
      '<option value="">Select Model (configure in Settings → LLM Settings)</option>';

    // Add enabled models from enabled providers
    if (data.models && data.models.length > 0) {
      data.models.forEach((model) => {
        const option = document.createElement("option");
        option.value = model.model_id;
        option.textContent = `${model.model_id} (${model.provider_name || model.provider_type})`;
        modelSelect.appendChild(option);
      });
    }

    if (modelSelect.options.length === 1) {
      // Only placeholder exists - no models configured
      modelSelect.innerHTML =
        '<option value="">No models configured - go to Settings → LLM Settings</option>';
    }
  } catch (error) {
    console.error("Error loading LLM models:", error);
    modelSelect.innerHTML = '<option value="">Error loading models</option>';
  }

  updateConnectButtonState();
};

/**
 * Handle LLM model selection change
 */

export const handleLLMModelChange = function () {
  const modelSelect = safeGetElement("llm-model-select");
  const modelBadge = safeGetElement("llm-model-badge");
  const modelNameSpan = safeGetElement("llmchat-model-name");

  if (modelSelect && modelBadge && modelNameSpan) {
    const selectedOption = modelSelect.options[modelSelect.selectedIndex];
    const modelValue = modelSelect.value;

    if (modelValue) {
      // Show badge with selected model name
      const modelName = selectedOption.text;
      modelNameSpan.textContent = modelName;
      modelBadge.classList.remove("hidden");
    } else {
      // Hide badge when no model selected
      modelBadge.classList.add("hidden");
    }
  }

  updateConnectButtonState();
};

/**
 * Update connect button state
 */

const updateConnectButtonState = function () {
  const connectBtn = safeGetElement("llm-connect-btn");
  const modelSelect = safeGetElement("llm-model-select");
  const selectedModel = modelSelect ? modelSelect.value : "";
  const hasServer = llmChatState.selectedServerId !== null;

  if (connectBtn) {
    connectBtn.disabled = !hasServer || !selectedModel;
  }
};

/**
 * Connect to LLM chat
 */

export const connectLLMChat = async function () {
  if (!llmChatState.selectedServerId) {
    showErrorMessage("Please select a virtual server first");
    return;
  }

  const modelSelect = safeGetElement("llm-model-select");
  const selectedModel = modelSelect ? modelSelect.value : "";
  if (!selectedModel) {
    showErrorMessage("Please select an LLM model");
    return;
  }

  // Clear previous chat history before connecting
  clearChatMessages();
  llmChatState.messageHistory = [];

  // Show loading state
  const connectBtn = safeGetElement("llm-connect-btn");
  const originalText = connectBtn.textContent;
  connectBtn.textContent = "Connecting...";
  connectBtn.disabled = true;

  // Clear any previous error messages
  const statusDiv = safeGetElement("llm-config-status");
  if (statusDiv) {
    statusDiv.classList.add("hidden");
  }

  try {
    // Build LLM config - now uses model ID from LLM Settings
    const llmConfig = buildLLMConfig(selectedModel);

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
          credentials: "same-origin", // pragma: allowlist secret
        },
        30000
      );
    } catch (fetchError) {
      // Handle network/timeout errors
      if (
        fetchError.name === "AbortError" ||
        fetchError.message.includes("timeout")
      ) {
        throw new Error(
          "Connection timed out. Please check if the server is responsive and try again."
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
      throw new Error("Failed to parse server response. Please try again.");
    }

    console.log("Connection successful:", result);

    // Update state
    llmChatState.isConnected = true;
    llmChatState.connectedTools = result.tools || [];
    llmChatState.toolCount = result.tool_count || 0;

    // Update UI
    showConnectionSuccess();

    // Clear welcome message and show chat input
    const welcomeMsg = safeGetElement("chat-welcome-message");
    if (welcomeMsg) {
      welcomeMsg.remove();
    }

    const chatInput = safeGetElement("chat-input-container");
    if (chatInput) {
      chatInput.classList.remove("hidden");
      safeGetElement("chat-input").disabled = false;
      safeGetElement("chat-send-btn").disabled = false;
      safeGetElement("chat-input").focus();
    }

    // Hide connect button, show disconnect button
    const disconnectBtn = safeGetElement("llm-disconnect-btn");
    if (connectBtn) {
      connectBtn.classList.add("hidden");
    }
    if (disconnectBtn) {
      disconnectBtn.classList.remove("hidden");
    }

    // Auto-collapse configuration
    // Disable configuration toggle instead of hiding it
    const configToggle = safeGetElement("llm-config-toggle");
    if (configToggle) {
      configToggle.disabled = true;
      configToggle.classList.add("opacity-50", "cursor-not-allowed");
      configToggle.title = "Please disconnect to change configuration";

      // Ensure dropdown is closed if it was open (handled by Alpine, but good to be safe)
      // We DON'T set 'hidden' class manually as it breaks Alpine's state
      // But we can trigger a click if we knew it was open, or just let Alpine handle click.away
    }

    // Disable server dropdown as well
    const serverDropdownBtn = safeGetElement("llm-server-dropdown-btn");
    if (serverDropdownBtn) {
      serverDropdownBtn.disabled = true;
      serverDropdownBtn.classList.add("opacity-50", "cursor-not-allowed");
      serverDropdownBtn.title = "Please disconnect to change server";
    }

    // Show success message
    showNotification(
      `Connected to ${llmChatState.selectedServerName}`,
      "success"
    );
  } catch (error) {
    console.error("Connection error:", error);
    // Display the backend error message to the user
    showConnectionError(error.message);
  } finally {
    connectBtn.textContent = originalText;
    connectBtn.disabled = false;
  }
};

/**
 * Build LLM config object from form inputs
 * Models are configured via Admin UI -> Settings -> LLM Settings
 */
const buildLLMConfig = function (modelId) {
  const config = {
    model: modelId,
  };

  // Get optional temperature
  const temperatureEl = safeGetElement("llm-temperature");
  if (temperatureEl && temperatureEl.value.trim()) {
    config.temperature = parseFloat(temperatureEl.value.trim());
  }

  // Get optional max tokens
  const maxTokensEl = safeGetElement("llm-max-tokens");
  if (maxTokensEl && maxTokensEl.value.trim()) {
    config.max_tokens = parseInt(maxTokensEl.value.trim(), 10);
  }

  return config;
};

/**
 * Legacy function - kept for compatibility but no longer used
 * @deprecated Use buildLLMConfig(modelId) instead
 */

export const buildLLMConfigLegacy = function (provider) {
  const config = {
    provider,
    config: {},
  };

  if (provider === "azure_openai") {
    const apiKeyEl = safeGetElement("azure-api-key");
    const endpointEl = safeGetElement("azure-endpoint");
    const deploymentEl = safeGetElement("azure-deployment");
    const apiVersionEl = safeGetElement("azure-api-version");
    const temperatureEl = safeGetElement("azure-temperature");

    const apiKey = apiKeyEl?.value?.trim() || "";
    const endpoint = endpointEl?.value?.trim() || "";
    const deployment = deploymentEl?.value?.trim() || "";
    const apiVersion = apiVersionEl?.value?.trim() || "";
    const temperature = temperatureEl?.value?.trim() || "";

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
    const apiKeyEl = safeGetElement("openai-api-key");
    const modelEl = safeGetElement("openai-model");
    const baseUrlEl = safeGetElement("openai-base-url");
    const temperatureEl = safeGetElement("openai-temperature");

    const apiKey = apiKeyEl?.value?.trim() || "";
    const model = modelEl?.value?.trim() || "";
    const baseUrl = baseUrlEl.value.trim();
    const temperature = temperatureEl.value.trim();

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
    const apiKey = document.getElementById("anthropic-api-key").value.trim();
    const model = safeGetElement("anthropic-model").value.trim();
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
    const region = document.getElementById("aws-bedrock-region").value.trim();
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
    const apiKey = safeGetElement("watsonx-api-key").value.trim();
    const url = safeGetElement("watsonx-url").value.trim();
    const projectId = document
      .getElementById("watsonx-project-id")
      .value.trim();
    const modelId = document.getElementById("watsonx-model-id").value.trim();
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
    const model = safeGetElement("ollama-model").value.trim();
    const baseUrl = safeGetElement("ollama-base-url").value.trim();
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
};

/**
 * Copy environment variables to clipboard for the specified provider
 */

export const copyEnvVariables = async function (provider) {
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
};

/**
 * Show success notification when environment variables are copied
 */
const showCopySuccessNotification = function (provider) {
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
};

/**
 * Show connection success
 */
const showConnectionSuccess = function () {
  // Update connection status badge
  const statusBadge = safeGetElement("llm-connection-status");
  if (statusBadge) {
    statusBadge.classList.remove("hidden");
  }

  // Show active tools badge using data from connection response
  const toolsBadge = safeGetElement("llm-active-tools-badge");
  const toolCountSpan = safeGetElement("llm-tool-count");
  const toolListDiv = safeGetElement("llm-tool-list");

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
          "inline-flex items-center gap-1.5 px-3 py-2 rounded-full text-xs font-medium bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/40 dark:to-indigo-900/40 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-700 shadow-sm hover:shadow-md transition-all hover:scale-105";

        // Tool icon
        const icon = document.createElementNS(
          "http://www.w3.org/2000/svg",
          "svg"
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
  const connectBtn = safeGetElement("llm-connect-btn");
  const disconnectBtn = safeGetElement("llm-disconnect-btn");
  if (connectBtn) {
    connectBtn.classList.add("hidden");
  }
  if (disconnectBtn) {
    disconnectBtn.classList.remove("hidden");
  }

  // Show success message
  showNotification(
    `Connected to ${llmChatState.selectedServerName}`,
    "success"
  );
};

/**
 * Show connection error
 */
/**
 * Display connection error with proper formatting
 */
const showConnectionError = function (message) {
  const statusDiv = safeGetElement("llm-config-status");
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
};

/**
 * Disconnect from LLM chat
 */

export const disconnectLLMChat = async function () {
  if (!llmChatState.isConnected) {
    console.warn("No active connection to disconnect");
    return;
  }

  const disconnectBtn = safeGetElement("llm-disconnect-btn");
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
          credentials: "same-origin", // pragma: allowlist secret
        },
        10000
      ); // Shorter timeout for disconnect
    } catch (fetchError) {
      console.warn(
        "Disconnect request failed, cleaning up locally:",
        fetchError
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
          `Disconnect returned error: ${backendError}, cleaning up locally`
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
    const statusBadge = safeGetElement("llm-connection-status");
    if (statusBadge) {
      statusBadge.classList.add("hidden");
    }

    const toolsBadge = safeGetElement("llm-active-tools-badge");
    if (toolsBadge) {
      toolsBadge.classList.add("hidden");
    }

    const modelBadge = safeGetElement("llm-model-badge");
    if (modelBadge) {
      modelBadge.classList.add("hidden");
    }

    const connectBtn = safeGetElement("llm-connect-btn");
    if (connectBtn) {
      connectBtn.classList.remove("hidden");
    }
    if (disconnectBtn) {
      disconnectBtn.classList.add("hidden");
    }

    // Hide chat input
    const chatInput = safeGetElement("chat-input-container");
    if (chatInput) {
      chatInput.classList.add("hidden");
      safeGetElement("chat-input").disabled = true;
      safeGetElement("chat-send-btn").disabled = true;
    }

    // Re-enable configuration toggle
    const configToggle = safeGetElement("llm-config-toggle");
    if (configToggle) {
      configToggle.disabled = false;
      configToggle.classList.remove("opacity-50", "cursor-not-allowed");
      configToggle.removeAttribute("title");
    }

    // Re-enable server dropdown
    const serverDropdownBtn = safeGetElement("llm-server-dropdown-btn");
    if (serverDropdownBtn) {
      serverDropdownBtn.disabled = false;
      serverDropdownBtn.classList.remove("opacity-50", "cursor-not-allowed");
      serverDropdownBtn.removeAttribute("title");
    }

    // Clear messages
    clearChatMessages();

    // Show appropriate notification
    if (backendError) {
      showNotification(
        `Disconnected (server error: ${backendError})`,
        "warning"
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
      `Disconnection error: ${error.message}. Local session cleared.`
    );
  } finally {
    // Reset button state only if it's still visible (error case where we didn't disconnect)
    if (disconnectBtn && !disconnectBtn.classList.contains("hidden")) {
      disconnectBtn.textContent = originalText;
      disconnectBtn.disabled = false;
    }
  }
};

/**
 * Send chat message
 */
export const sendChatMessage = async function (event) {
  event.preventDefault();

  const input = safeGetElement("chat-input");
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
  safeGetElement("chat-send-btn").disabled = true;

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
        credentials: "same-origin", // pragma: allowlist secret
        signal: controller.signal,
      });

      clearTimeout(timeoutId);
    } catch (fetchError) {
      if (fetchError.name === "AbortError") {
        throw new Error("Request timed out. The response took too long.");
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
            console.warn("Failed to parse SSE data:", dataStr, parseError);
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
                    accumulatedText
                  );
                }
                break;
              }
              case "tool_start":
              case "tool_end":
              case "tool_error":
                addToolEventToCard(assistantMsgId, eventType, payload);
                break;

              case "final":
                if (payload.tool_used) {
                  setToolUsedSummary(assistantMsgId, true, payload.tools);
                }
                setTimeout(scrollChatToBottom, 50);
                break;

              case "error": {
                // Handle server-sent error events from backend
                const errorMsg =
                  payload.error || "An error occurred during processing";
                const isRecoverable = payload.recoverable !== false;

                // Display error in the assistant message
                updateChatMessage(assistantMsgId, `❌ Error: ${errorMsg}`);

                if (!isRecoverable) {
                  // For non-recoverable errors, suggest reconnection
                  appendChatMessage(
                    "system",
                    "⚠️ Connection lost. Please reconnect to continue."
                  );
                  llmChatState.isConnected = false;

                  // Update UI to show disconnected state
                  const connectBtn = safeGetElement("llm-connect-btn");
                  const disconnectBtn = safeGetElement("llm-disconnect-btn");
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
            console.error(`Error handling event ${eventType}:`, eventError);
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
    safeGetElement("chat-send-btn").disabled = false;
    input.focus();
  }
};

/**
 * Parse content with <think> tags and separate thinking from final answer
 * Returns: { thinkingSteps: [{content: string}], finalAnswer: string, rawContent: string }
 */
export const parseThinkTags = function (content) {
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
};

/**
 * Update chat message with think tags support
 * Renders thinking steps in collapsible UI and final answer separately
 */
const updateChatMessageWithThinkTags = function (messageId, content) {
  const messageDiv = safeGetElement(messageId);
  if (!messageDiv) {
    return;
  }

  const contentEl = messageDiv.querySelector(".message-content");
  if (!contentEl) {
    return;
  }

  // Store raw content for final processing
  contentEl.setAttribute("data-raw-content", content);

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
    answerDiv.className = "final-answer-content markdown-body";
    answerDiv.innerHTML = renderMarkdown(finalAnswer);
    contentEl.appendChild(answerDiv);
  }

  // Throttle scroll during streaming
  if (!scrollThrottle) {
    scrollChatToBottom();
    scrollThrottle = setTimeout(() => {
      scrollThrottle = null;
    }, 100);
  }
};

/**
 * Create the thinking UI component with collapsible steps
 */
const createThinkingUI = function (thinkingSteps) {
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
};

/**
 * Append chat message to UI
 */
// Append chat message to UI
// Append chat message to UI
// Append chat message to UI
// appendChatMessage = function (role, content, isStreaming = false) {
//     const container = safeGetElement('chat-messages-container');
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

const appendChatMessage = function (role, content, isStreaming = false) {
  const container = safeGetElement("chat-messages-container");
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
        <div class="bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-2xl px-4 py-3 shadow-sm text-sm flex flex-col gap-1 w-fit">
          <div class="message-content markdown-body"></div>
          ${isStreaming ? '<span class="streaming-indicator"></span>' : ""}
        </div>
      </div>
    `;
    const contentEl = messageDiv.querySelector(".message-content");
    if (contentEl) {
      contentEl.innerHTML = renderMarkdown(content);
    }
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
  // Use force scroll for new messages
  scrollChatToBottom(true);
  return messageId;
};

/**
 * Render and sanitize markdown content
 */
const renderMarkdown = function (text) {
  if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
    return text;
  }

  // Configure marked for nested markdown support
  const rawHtml = window.marked.parse(text, {
    breaks: true, // Support GFM line breaks
    gfm: true, // GitHub Flavored Markdown
    pedantic: false, // Allow nested markdown
    sanitize: false, // We'll sanitize with DOMPurify
    smartLists: true, // Better list handling
    smartypants: false, // No typographic replacements
  });

  return window.DOMPurify.sanitize(rawHtml);
};

/**
 * Update chat message content (for streaming)
 */
let scrollThrottle = null;
let renderThrottle = null;
const updateChatMessage = function (messageId, content) {
  const messageDiv = safeGetElement(messageId);
  if (messageDiv) {
    const contentEl = messageDiv.querySelector(".message-content");
    if (contentEl) {
      // Store raw content for final processing
      contentEl.setAttribute("data-raw-content", content);

      // Ensure markdown-body class is present
      if (!contentEl.classList.contains("markdown-body")) {
        contentEl.classList.add("markdown-body");
      }

      // During streaming, we use textContent for speed and to avoid broken HTML tags
      // but we can render markdown periodically for a better UI
      if (!renderThrottle) {
        contentEl.innerHTML = renderMarkdown(content);
        renderThrottle = setTimeout(() => {
          renderThrottle = null;
        }, 150);
      }

      // Throttle scroll during streaming
      if (!scrollThrottle) {
        scrollChatToBottom();
        scrollThrottle = setTimeout(() => {
          scrollThrottle = null;
        }, 100);
      }
    }
  }
};

/**
 * Mark message as complete (remove streaming indicator)
 */
const markMessageComplete = function (messageId) {
  const messageDiv = safeGetElement(messageId);
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
        contentEl.getAttribute("data-raw-content") || contentEl.textContent;
      if (fullContent.includes("<think>")) {
        const { thinkingSteps, finalAnswer } = parseThinkTags(fullContent);
        contentEl.innerHTML = "";

        if (thinkingSteps.length > 0) {
          const thinkingContainer = createThinkingUI(thinkingSteps);
          contentEl.appendChild(thinkingContainer);
        }

        if (finalAnswer) {
          const answerDiv = document.createElement("div");
          answerDiv.className = "final-answer-content markdown-body";
          answerDiv.innerHTML = renderMarkdown(finalAnswer);
          contentEl.appendChild(answerDiv);
        }
      } else {
        // If no think tags, just render markdown
        contentEl.classList.add("markdown-body");
        contentEl.innerHTML = renderMarkdown(fullContent);
      }
    }
  }
};

/**
 * Get or create a tool-events card positioned above the assistant message.
 * The card is a sibling of the message div, not nested inside.
 */
const getOrCreateToolCard = function (messageId) {
  const messageDiv = safeGetElement(messageId);
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
};

/**
 * Add a tool event row to the tool card.
 */
const addToolEventToCard = function (messageId, eventType, payload) {
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
};

/**
 * Update or create a "tools used" summary badge on the tool card when final event arrives.
 */
const setToolUsedSummary = function (messageId, used, toolsList) {
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
};

/**
 * Clear all chat messages
 */
const clearChatMessages = function () {
  const container = safeGetElement("chat-messages-container");
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
};

/**
 * Scroll chat to bottom
 */
const scrollChatToBottom = function (force = false) {
  const container = safeGetElement("chat-messages-container");
  if (container) {
    if (force || llmChatState.autoScroll) {
      requestAnimationFrame(() => {
        // Use instant scroll during streaming for better UX
        container.scrollTop = container.scrollHeight;
      });
    }
  }
};

/**
 * Handle Enter key in chat input (send on Enter, new line on Shift+Enter)
 */

export const handleChatInputKeydown = function (event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendChatMessage(event);
  }
};

const initializeChatInputResize = function () {
  const chatInput = safeGetElement("chat-input");
  if (chatInput) {
    chatInput.addEventListener("input", function () {
      this.style.height = "auto";
      this.style.height = Math.min(this.scrollHeight, 120) + "px";
    });

    // Reset height when message is sent
    const form = safeGetElement("chat-input-form");
    if (form) {
      form.addEventListener("submit", () => {
        setTimeout(() => {
          chatInput.style.height = "auto";
        }, 0);
      });
    }
  }
};
