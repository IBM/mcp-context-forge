import { showCopyableModal } from "./modals.js";
import { escapeHtml, parseErrorResponse } from "./security.js";
import { fetchWithAuth, getAuthToken } from "./tokens.js";
import { safeGetElement, showToast } from "./utils.js";

// ===================================================================
// LLM SETTINGS FUNCTIONS
// ===================================================================

/**
 * Switch between LLM Settings tabs (providers/models)
 */
export const switchLLMSettingsTab = function (tabName) {
  // Hide all content panels
  const panels = document.querySelectorAll(".llm-settings-content");
  panels.forEach((panel) => panel.classList.add("hidden"));

  // Remove active state from all tabs
  const tabs = document.querySelectorAll(".llm-settings-tab");
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
  const selectedPanel = safeGetElement(`llm-settings-content-${tabName}`);
  if (selectedPanel) {
    selectedPanel.classList.remove("hidden");
    // Trigger HTMX load if not yet loaded
    window.htmx.trigger(selectedPanel, "revealed");
  }

  // Activate selected tab
  const selectedTab = safeGetElement(`llm-settings-tab-${tabName}`);
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
};

// Cache for provider defaults
let llmProviderDefaults = null;

/**
 * Load provider defaults from the server
 */
const loadLLMProviderDefaults = async function () {
  if (llmProviderDefaults) {
    return llmProviderDefaults;
  }
  try {
    const response = await fetch(
      `${window.ROOT_PATH}/admin/llm/provider-defaults`,
      {
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
        },
      },
    );
    if (response.ok) {
      llmProviderDefaults = await response.json();
    }
  } catch (error) {
    console.error("Failed to load provider defaults:", error);
  }
  return llmProviderDefaults || {};
};

// Track previous provider type for smart auto-fill
let previousProviderType = null;

/**
 * Handle provider type change - auto-fill defaults
 */
export const onLLMProviderTypeChange = async function () {
  const providerType = safeGetElement("llm-provider-type").value;
  if (!providerType) {
    // Hide provider-specific config section
    const configSection = safeGetElement("llm-provider-specific-config");
    if (configSection) {
      configSection.classList.add("hidden");
    }
    return;
  }

  const defaults = await loadLLMProviderDefaults();
  const config = defaults[providerType];

  if (!config) {
    return;
  }

  // Only auto-fill if creating new provider (not editing)
  const providerId = safeGetElement("llm-provider-id").value;
  const isEditing = providerId !== "";

  const apiBaseField = safeGetElement("llm-provider-api-base");
  const defaultModelField = safeGetElement("llm-provider-default-model");

  if (!isEditing) {
    // Check if current values match previous provider's defaults
    const previousConfig = previousProviderType
      ? defaults[previousProviderType]
      : null;
    const apiBaseMatchesPrevious =
      previousConfig &&
      (apiBaseField.value === previousConfig.api_base ||
        apiBaseField.value === "");
    const modelMatchesPrevious =
      previousConfig &&
      (defaultModelField.value === previousConfig.default_model ||
        defaultModelField.value === "");

    // Auto-fill API base if empty or matches previous provider's default
    if ((apiBaseMatchesPrevious || !apiBaseField.value) && config.api_base) {
      apiBaseField.value = config.api_base;
    }

    // Auto-fill default model if empty or matches previous provider's default
    if (
      (modelMatchesPrevious || !defaultModelField.value) &&
      config.default_model
    ) {
      defaultModelField.value = config.default_model;
    }

    // Remember this provider type for next change
    previousProviderType = providerType;
  }

  // Update description/help text
  const descEl = safeGetElement("llm-provider-type-description");
  if (descEl && config.description) {
    descEl.textContent = config.description;
    descEl.classList.remove("hidden");
  }

  // Show/hide API key requirement indicator
  const apiKeyRequired = safeGetElement("llm-provider-api-key-required");
  if (apiKeyRequired) {
    if (config.requires_api_key) {
      apiKeyRequired.classList.remove("hidden");
    } else {
      apiKeyRequired.classList.add("hidden");
    }
  }

  // Load and render provider-specific configuration fields
  await renderProviderSpecificFields(providerType, isEditing);
};

/**
 * Render provider-specific configuration fields dynamically
 */
const renderProviderSpecificFields = async function (
  providerType,
  isEditing = false,
) {
  try {
    // Fetch provider configurations
    const response = await fetch(
      `${window.ROOT_PATH}/admin/llm/provider-configs`,
      {
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
        },
      },
    );

    if (!response.ok) {
      console.error("Failed to fetch provider configs");
      return;
    }

    const providerConfigs = await response.json();
    const providerConfig = providerConfigs[providerType];

    if (
      !providerConfig ||
      !providerConfig.config_fields ||
      providerConfig.config_fields.length === 0
    ) {
      // No provider-specific fields, hide the section
      const configSection = safeGetElement("llm-provider-specific-config");
      if (configSection) {
        configSection.classList.add("hidden");
      }
      return;
    }

    // Show the provider-specific config section
    const configSection = safeGetElement("llm-provider-specific-config");
    const fieldsContainer = safeGetElement("llm-provider-config-fields");

    if (!configSection || !fieldsContainer) {
      return;
    }

    configSection.classList.remove("hidden");
    fieldsContainer.innerHTML = ""; // Clear existing fields

    // Render each field
    for (const fieldDef of providerConfig.config_fields) {
      const fieldDiv = document.createElement("div");

      const label = document.createElement("label");
      label.setAttribute("for", `llm-config-${fieldDef.name}`);
      label.className =
        "block text-sm font-medium text-gray-700 dark:text-gray-300";
      label.textContent = fieldDef.label;
      if (fieldDef.required) {
        const requiredSpan = document.createElement("span");
        requiredSpan.className = "text-red-500 ml-1";
        requiredSpan.textContent = "*";
        label.appendChild(requiredSpan);
      }
      fieldDiv.appendChild(label);

      let inputElement;

      if (fieldDef.field_type === "select") {
        inputElement = document.createElement("select");
        inputElement.className =
          "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-700 dark:border-gray-600 dark:text-white sm:text-sm";

        // Add empty option
        const emptyOption = document.createElement("option");
        emptyOption.value = "";
        emptyOption.textContent = "Select...";
        inputElement.appendChild(emptyOption);

        // Add options
        if (fieldDef.options) {
          for (const opt of fieldDef.options) {
            const option = document.createElement("option");
            option.value = opt.value;
            option.textContent = opt.label;
            inputElement.appendChild(option);
          }
        }
      } else if (fieldDef.field_type === "textarea") {
        inputElement = document.createElement("textarea");
        inputElement.className =
          "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-700 dark:border-gray-600 dark:text-white sm:text-sm";
        inputElement.rows = 3;
      } else {
        inputElement = document.createElement("input");
        inputElement.type = fieldDef.field_type;
        inputElement.className =
          "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-700 dark:border-gray-600 dark:text-white sm:text-sm";

        if (fieldDef.field_type === "number") {
          if (fieldDef.min_value !== null && fieldDef.min_value !== undefined) {
            inputElement.min = fieldDef.min_value;
          }
          if (fieldDef.max_value !== null && fieldDef.max_value !== undefined) {
            inputElement.max = fieldDef.max_value;
          }
        }
      }

      inputElement.id = `llm-config-${fieldDef.name}`;
      inputElement.name = `config_${fieldDef.name}`;

      if (fieldDef.required) {
        inputElement.required = true;
      }

      if (fieldDef.placeholder) {
        inputElement.placeholder = fieldDef.placeholder;
      }

      if (fieldDef.default_value && !isEditing) {
        inputElement.value = fieldDef.default_value;
      }

      fieldDiv.appendChild(inputElement);

      // Add help text if available
      if (fieldDef.help_text) {
        const helpText = document.createElement("p");
        helpText.className = "mt-1 text-xs text-gray-500 dark:text-gray-400";
        helpText.textContent = fieldDef.help_text;
        fieldDiv.appendChild(helpText);
      }

      fieldsContainer.appendChild(fieldDiv);
    }
  } catch (error) {
    console.error("Error rendering provider-specific fields:", error);
  }
};

/**
 * Show Add Provider Modal
 */
export const showAddProviderModal = async function () {
  safeGetElement("llm-provider-id").value = "";
  safeGetElement("llm-provider-form").reset();
  safeGetElement("llm-provider-modal-title").textContent = "Add LLM Provider";

  // Reset helper elements
  const descEl = safeGetElement("llm-provider-type-description");
  if (descEl) {
    descEl.classList.add("hidden");
  }

  // Reset provider type tracker for smart auto-fill
  previousProviderType = null;

  // Load defaults for quick access
  await loadLLMProviderDefaults();

  safeGetElement("llm-provider-modal").classList.remove("hidden");
};

/**
 * Close Provider Modal
 */
export const closeLLMProviderModal = function () {
  safeGetElement("llm-provider-modal").classList.add("hidden");
};

/**
 * Fetch models from a provider's API
 */
export const fetchLLMProviderModels = async function (providerId) {
  try {
    const response = await fetch(
      `${window.ROOT_PATH}/admin/llm/providers/${providerId}/fetch-models`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
        },
      },
    );

    const result = await response.json();

    if (result.success) {
      const modelList = result.models
        .map((m) => `- ${m.id} (${m.owned_by || "unknown"})`)
        .join("\n");
      showCopyableModal(
        `Found ${result.count} Models`,
        modelList || "No models found",
        "success",
      );
    } else {
      showCopyableModal("Failed to Fetch Models", result.error, "error");
    }

    return result;
  } catch (error) {
    console.error("Error fetching models:", error);
    showCopyableModal(
      "Failed to Fetch Models",
      `Error: ${error.message}`,
      "error",
    );
    return { success: false, error: error.message, models: [] };
  }
};

/**
 * Sync models from provider API to database
 */
export const syncLLMProviderModels = async function (providerId) {
  try {
    showToast("Syncing models...", "info");

    const response = await fetch(
      `${window.ROOT_PATH}/admin/llm/providers/${providerId}/sync-models`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
        },
      },
    );

    const result = await response.json();

    if (result.success) {
      showCopyableModal(
        "Models Synced Successfully",
        `${result.message}\n\nTotal available: ${result.total || 0}`,
        "success",
      );
      // Refresh the models list
      refreshLLMModels();
    } else {
      showCopyableModal("Failed to Sync Models", result.error, "error");
    }

    return result;
  } catch (error) {
    console.error("Error syncing models:", error);
    showCopyableModal(
      "Failed to Sync Models",
      `Error: ${error.message}`,
      "error",
    );
    return { success: false, error: error.message };
  }
};

/**
 * Edit LLM Provider
 */
export const editLLMProvider = async function (providerId) {
  try {
    const response = await fetch(
      `${window.ROOT_PATH}/llm/providers/${providerId}`,
      {
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
        },
      },
    );
    if (!response.ok) {
      throw new Error("Failed to fetch provider details");
    }
    const provider = await response.json();

    safeGetElement("llm-provider-id").value = provider.id;
    safeGetElement("llm-provider-name").value = provider.name;
    safeGetElement("llm-provider-type").value = provider.provider_type;
    safeGetElement("llm-provider-description").value =
      provider.description || "";
    safeGetElement("llm-provider-api-key").value = "";
    safeGetElement("llm-provider-api-base").value = provider.api_base || "";
    safeGetElement("llm-provider-default-model").value =
      provider.default_model || "";
    safeGetElement("llm-provider-temperature").value =
      provider.default_temperature || 0.7;
    safeGetElement("llm-provider-max-tokens").value =
      provider.default_max_tokens || "";
    safeGetElement("llm-provider-enabled").checked = provider.enabled;

    // Render provider-specific fields and populate with existing config
    await renderProviderSpecificFields(provider.provider_type, true);

    // Populate provider-specific config values
    if (provider.config) {
      for (const [key, value] of Object.entries(provider.config)) {
        const input = safeGetElement(`llm-config-${key}`);
        if (input) {
          if (input.type === "checkbox") {
            input.checked = value;
          } else {
            input.value = value || "";
          }
        }
      }
    }

    safeGetElement("llm-provider-modal-title").textContent =
      "Edit LLM Provider";
    document.getElementById("llm-provider-modal").classList.remove("hidden");
  } catch (error) {
    console.error("Error fetching provider:", error);
    showToast("Failed to load provider details", "error");
  }
};

/**
 * Save LLM Provider (create or update)
 */
export const saveLLMProvider = async function (event) {
  event.preventDefault();

  const providerId = safeGetElement("llm-provider-id").value;
  const isUpdate = providerId !== "";

  const formData = {
    name: safeGetElement("llm-provider-name").value,
    provider_type: safeGetElement("llm-provider-type").value,
    description: safeGetElement("llm-provider-description").value || null,
    api_base: safeGetElement("llm-provider-api-base").value || null,
    default_model: safeGetElement("llm-provider-default-model").value || null,
    default_temperature: parseFloat(
      safeGetElement("llm-provider-temperature").value,
    ),
    enabled: safeGetElement("llm-provider-enabled").checked,
    config: {},
  };

  const apiKey = safeGetElement("llm-provider-api-key").value;
  if (apiKey) {
    formData.api_key = apiKey;
  }

  const maxTokens = safeGetElement("llm-provider-max-tokens").value;
  if (maxTokens) {
    formData.default_max_tokens = parseInt(maxTokens, 10);
  }

  // Collect provider-specific configuration fields
  const configFieldsContainer = safeGetElement("llm-provider-config-fields");
  if (configFieldsContainer) {
    const configInputs = configFieldsContainer.querySelectorAll(
      "input, select, textarea",
    );
    for (const input of configInputs) {
      if (input.name && input.name.startsWith("config_")) {
        const fieldName = input.name.replace("config_", "");
        let value = input.value;

        // Convert to appropriate type
        if (input.type === "number") {
          value = value ? parseFloat(value) : null;
        } else if (input.type === "checkbox") {
          value = input.checked;
        } else if (value === "") {
          value = null;
        }

        if (value !== null && value !== "") {
          formData.config[fieldName] = value;
        }
      }
    }
  }

  try {
    const url = isUpdate
      ? `${window.ROOT_PATH}/llm/providers/${providerId}`
      : `${window.ROOT_PATH}/llm/providers`;
    const method = isUpdate ? "PATCH" : "POST";

    const response = await fetch(url, {
      method,
      headers: {
        Authorization: `Bearer ${await getAuthToken()}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(formData),
    });

    if (!response.ok) {
      const errorMsg = await parseErrorResponse(
        response,
        "Failed to save provider",
      );
      throw new Error(errorMsg);
    }

    closeLLMProviderModal();
    showToast(
      isUpdate
        ? "Provider updated successfully"
        : "Provider created successfully",
      "success",
    );
    refreshLLMProviders();
  } catch (error) {
    console.error("Error saving provider:", error);
    showToast(error.message || "Failed to save provider", "error");
  }
};

/**
 * Delete LLM Provider
 */
export const deleteLLMProvider = async function (providerId, providerName) {
  if (
    !confirm(
      `Are you sure you want to delete the provider "${providerName}"? This will also delete all associated models.`,
    )
  ) {
    return;
  }

  try {
    const response = await fetch(
      `${window.ROOT_PATH}/llm/providers/${providerId}`,
      {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
        },
      },
    );

    if (!response.ok) {
      const errorMsg = await parseErrorResponse(
        response,
        "Failed to delete provider",
      );
      throw new Error(errorMsg);
    }

    showToast("Provider deleted successfully", "success");
    refreshLLMProviders();
  } catch (error) {
    console.error("Error deleting provider:", error);
    showToast(error.message || "Failed to delete provider", "error");
  }
};

/**
 * Toggle LLM Provider enabled state
 */
export const toggleLLMProvider = async function (providerId) {
  try {
    const response = await fetch(
      `${window.ROOT_PATH}/llm/providers/${providerId}/state`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
        },
      },
    );

    if (!response.ok) {
      throw new Error("Failed to toggle provider");
    }

    refreshLLMProviders();
  } catch (error) {
    console.error("Error toggling provider:", error);
    showToast("Failed to toggle provider", "error");
  }
};

/**
 * Check LLM Provider health
 */
export const checkLLMProviderHealth = async function (providerId) {
  try {
    const response = await fetch(
      `${window.ROOT_PATH}/admin/llm/providers/${providerId}/health`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
        },
      },
    );

    const result = await response.json();

    // Show result message with details using copyable modal
    if (result.status === "healthy") {
      const message = `Status: ${result.status}\nLatency: ${result.latency_ms}ms`;
      showCopyableModal("Health Check Passed", message, "success");
    } else {
      // Show error details for unhealthy status
      let message = `Status: ${result.status}`;
      if (result.latency_ms) {
        message += `\nLatency: ${result.latency_ms}ms`;
      }
      if (result.error) {
        message += `\n\nError:\n${result.error}`;
      }
      showCopyableModal("Health Check Failed", message, "error");
    }

    // Refresh providers to update status
    refreshLLMProviders();
  } catch (error) {
    console.error("Error checking provider health:", error);
    showCopyableModal(
      "Health Check Request Failed",
      `Error: ${error.message}`,
      "error",
    );
  }
};

/**
 * Refresh LLM Providers list
 */
const refreshLLMProviders = function () {
  const container = safeGetElement("llm-providers-container");
  if (container) {
    window.htmx.ajax("GET", `${window.ROOT_PATH}/admin/llm/providers/html`, {
      target: "#llm-providers-container",
      swap: "innerHTML",
    });
  }
};

/**
 * Show Add Model Modal
 */
export const showAddModelModal = async function () {
  safeGetElement("llm-model-id").value = "";
  safeGetElement("llm-model-form").reset();
  safeGetElement("llm-model-modal-title").textContent = "Add LLM Model";

  // Populate providers dropdown
  await populateProviderDropdown();

  safeGetElement("llm-model-modal").classList.remove("hidden");
};

/**
 * Populate provider dropdown in model modal
 */
export const populateProviderDropdown = async function () {
  try {
    const response = await fetch(`${window.ROOT_PATH}/llm/providers`, {
      headers: {
        Authorization: `Bearer ${await getAuthToken()}`,
      },
    });
    if (!response.ok) {
      throw new Error("Failed to fetch providers");
    }
    const data = await response.json();

    const select = safeGetElement("llm-model-provider");
    select.innerHTML = '<option value="">Select provider</option>';

    data.providers.forEach((provider) => {
      const option = document.createElement("option");
      option.value = provider.id;
      option.textContent = `${provider.name} (${provider.provider_type})`;
      select.appendChild(option);
    });
  } catch (error) {
    console.error("Error fetching providers:", error);
  }
};

/**
 * Close Model Modal
 */
export const closeLLMModelModal = function () {
  safeGetElement("llm-model-modal").classList.add("hidden");
};

/**
 * Handle provider change in model modal - auto-fetch models
 */
export const onModelProviderChange = async function () {
  const providerId = safeGetElement("llm-model-provider").value;
  const modelInput = safeGetElement("llm-model-model-id");
  const datalist = safeGetElement("llm-model-suggestions");
  const statusEl = safeGetElement("llm-model-fetch-status");

  // Clear existing suggestions
  datalist.innerHTML = "";

  if (!providerId) {
    modelInput.placeholder = "Select provider first...";
    statusEl.classList.add("hidden");
    return;
  }

  modelInput.placeholder = "Type or select a model...";

  // Auto-fetch models when provider is selected
  await fetchModelsForModelModal();
};

/**
 * Fetch available models for the model modal
 */
export const fetchModelsForModelModal = async function () {
  const providerId = safeGetElement("llm-model-provider").value;
  const datalist = safeGetElement("llm-model-suggestions");
  const statusEl = safeGetElement("llm-model-fetch-status");

  if (!providerId) {
    showToast("Please select a provider first", "warning");
    return;
  }

  statusEl.textContent = "Fetching models...";
  statusEl.classList.remove("hidden");

  try {
    const response = await fetch(
      `${window.ROOT_PATH}/admin/llm/providers/${providerId}/fetch-models`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
        },
      },
    );

    const result = await response.json();

    if (result.success && result.models && result.models.length > 0) {
      // Populate datalist with model suggestions
      datalist.innerHTML = "";
      result.models.forEach((model) => {
        const option = document.createElement("option");
        option.value = model.id;
        option.textContent = model.name || model.id;
        datalist.appendChild(option);
      });

      statusEl.textContent = `Found ${result.models.length} models. Type to filter or enter custom.`;
      statusEl.classList.remove("hidden");
    } else {
      statusEl.textContent =
        result.error || "No models found. Enter model ID manually.";
      statusEl.classList.remove("hidden");
    }
  } catch (error) {
    console.error("Error fetching models:", error);
    statusEl.textContent = "Failed to fetch models. Enter model ID manually.";
    statusEl.classList.remove("hidden");
  }
};

/**
 * Edit LLM Model
 */
export const editLLMModel = async function (modelId) {
  try {
    const response = await fetch(`${window.ROOT_PATH}/llm/models/${modelId}`, {
      headers: {
        Authorization: `Bearer ${await getAuthToken()}`,
      },
    });
    if (!response.ok) {
      throw new Error("Failed to fetch model details");
    }
    const model = await response.json();

    await populateProviderDropdown();

    safeGetElement("llm-model-id").value = model.id;
    safeGetElement("llm-model-provider").value = model.provider_id;
    safeGetElement("llm-model-model-id").value = model.model_id;
    safeGetElement("llm-model-name").value = model.model_name;
    safeGetElement("llm-model-alias").value = model.model_alias || "";
    safeGetElement("llm-model-description").value = model.description || "";
    safeGetElement("llm-model-context-window").value =
      model.context_window || "";
    safeGetElement("llm-model-max-output").value =
      model.max_output_tokens || "";
    safeGetElement("llm-model-supports-chat").checked = model.supports_chat;
    safeGetElement("llm-model-supports-streaming").checked =
      model.supports_streaming;
    safeGetElement("llm-model-supports-functions").checked =
      model.supports_function_calling;
    safeGetElement("llm-model-supports-vision").checked = model.supports_vision;
    safeGetElement("llm-model-enabled").checked = model.enabled;
    safeGetElement("llm-model-deprecated").checked = model.deprecated;

    safeGetElement("llm-model-modal-title").textContent = "Edit LLM Model";
    safeGetElement("llm-model-modal").classList.remove("hidden");
  } catch (error) {
    console.error("Error fetching model:", error);
    showToast("Failed to load model details", "error");
  }
};

/**
 * Save LLM Model (create or update)
 */
export const saveLLMModel = async function (event) {
  event.preventDefault();

  const modelId = safeGetElement("llm-model-id").value;
  const isUpdate = modelId !== "";

  const formData = {
    provider_id: safeGetElement("llm-model-provider").value,
    model_id: safeGetElement("llm-model-model-id").value,
    model_name: safeGetElement("llm-model-name").value,
    model_alias: safeGetElement("llm-model-alias").value || null,
    description: safeGetElement("llm-model-description").value || null,
    supports_chat: safeGetElement("llm-model-supports-chat").checked,
    supports_streaming: safeGetElement("llm-model-supports-streaming").checked,
    supports_function_calling: safeGetElement("llm-model-supports-functions")
      .checked,
    supports_vision: safeGetElement("llm-model-supports-vision").checked,
    enabled: safeGetElement("llm-model-enabled").checked,
    deprecated: safeGetElement("llm-model-deprecated").checked,
  };

  const contextWindow = safeGetElement("llm-model-context-window").value;
  if (contextWindow) {
    formData.context_window = parseInt(contextWindow, 10);
  }

  const maxOutput = safeGetElement("llm-model-max-output").value;
  if (maxOutput) {
    formData.max_output_tokens = parseInt(maxOutput, 10);
  }

  try {
    const url = isUpdate
      ? `${window.ROOT_PATH}/llm/models/${modelId}`
      : `${window.ROOT_PATH}/llm/models`;
    const method = isUpdate ? "PATCH" : "POST";

    const response = await fetch(url, {
      method,
      headers: {
        Authorization: `Bearer ${await getAuthToken()}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(formData),
    });

    if (!response.ok) {
      const errorMsg = await parseErrorResponse(
        response,
        "Failed to save model",
      );
      throw new Error(errorMsg);
    }

    closeLLMModelModal();
    showToast(
      isUpdate ? "Model updated successfully" : "Model created successfully",
      "success",
    );
    refreshLLMModels();
  } catch (error) {
    console.error("Error saving model:", error);
    showToast(error.message || "Failed to save model", "error");
  }
};

/**
 * Delete LLM Model
 */
export const deleteLLMModel = async function (modelId, modelName) {
  if (!confirm(`Are you sure you want to delete the model "${modelName}"?`)) {
    return;
  }

  try {
    const response = await fetch(`${window.ROOT_PATH}/llm/models/${modelId}`, {
      method: "DELETE",
      headers: {
        Authorization: `Bearer ${await getAuthToken()}`,
      },
    });

    if (!response.ok) {
      const errorMsg = await parseErrorResponse(
        response,
        "Failed to delete model",
      );
      throw new Error(errorMsg);
    }

    showToast("Model deleted successfully", "success");
    refreshLLMModels();
  } catch (error) {
    console.error("Error deleting model:", error);
    showToast(error.message || "Failed to delete model", "error");
  }
};

/**
 * Toggle LLM Model enabled state
 */
export const toggleLLMModel = async function (modelId) {
  try {
    const response = await fetch(
      `${window.ROOT_PATH}/llm/models/${modelId}/state`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
        },
      },
    );

    if (!response.ok) {
      throw new Error("Failed to toggle model");
    }

    refreshLLMModels();
  } catch (error) {
    console.error("Error toggling model:", error);
    showToast("Failed to toggle model", "error");
  }
};

/**
 * Refresh LLM Models list
 */
const refreshLLMModels = function () {
  const container = safeGetElement("llm-models-container");
  if (container) {
    window.htmx.ajax("GET", `${window.ROOT_PATH}/admin/llm/models/html`, {
      target: "#llm-models-container",
      swap: "innerHTML",
    });
  }
};

/**
 * Filter models by provider
 */
export const filterModelsByProvider = function (providerId) {
  const url = providerId
    ? `${window.ROOT_PATH}/admin/llm/models/html?provider_id=${providerId}`
    : `${window.ROOT_PATH}/admin/llm/models/html`;

  window.htmx.ajax("GET", url, {
    target: "#llm-models-container",
    swap: "innerHTML",
  });
};

/**
 * Alpine.js component for LLM API Info & Test
 */
export const llmApiInfoApp = function () {
  return {
    testType: "models",
    testModel: "",
    testMessage: "Hello! Please respond with a short greeting.",
    testing: false,
    testResult: null,
    testSuccess: false,
    testMetrics: null,
    assistantMessage: null,
    modelList: null,

    formatDuration(ms) {
      if (ms < 1000) {
        return `${ms}ms`;
      }
      return `${(ms / 1000).toFixed(2)}s`;
    },

    formatBytes(bytes) {
      if (bytes === 0) {
        return "0 B";
      }
      if (bytes < 1024) {
        return `${bytes} B`;
      } else if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(2)} KB`;
      } else {
        return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
      }
    },

    async runTest() {
      // Use admin test endpoint directly
      this.testing = true;
      this.testResult = null;
      this.testSuccess = false;
      this.testMetrics = null;
      this.assistantMessage = null;
      this.modelList = null;

      try {
        const requestBody = {
          test_type: this.testType,
        };

        if (this.testType === "chat") {
          if (!this.testModel) {
            this.testResult = JSON.stringify(
              { error: "Please select a model" },
              null,
              2,
            );
            this.testSuccess = false;
            this.testMetrics = {
              httpStatus: 400,
              httpStatusText: "Bad Request",
            };
            return;
          }
          requestBody.model_id = this.testModel;
          requestBody.message = this.testMessage;
          requestBody.max_tokens = 100;
        }

        const requestBodyStr = JSON.stringify(requestBody);
        const startTime = performance.now();

        const response = await fetch(`${window.ROOT_PATH}/admin/llm/test`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${await getAuthToken()}`,
            "Content-Type": "application/json",
          },
          body: requestBodyStr,
        });

        const endTime = performance.now();
        const data = await response.json();

        this.testSuccess = data.success === true;
        this.testResult = JSON.stringify(data, null, 2);

        // Build metrics
        this.testMetrics = {
          duration: data.metrics?.duration || Math.round(endTime - startTime),
          httpStatus: response.status,
          httpStatusText: response.statusText,
          requestSize: requestBodyStr.length,
          responseSize: JSON.stringify(data).length,
        };

        if (this.testType === "chat" && data.metrics) {
          this.testMetrics.promptTokens = data.metrics.promptTokens || 0;
          this.testMetrics.completionTokens =
            data.metrics.completionTokens || 0;
          this.testMetrics.totalTokens = data.metrics.totalTokens || 0;
          this.testMetrics.responseModel = data.metrics.responseModel;
          this.assistantMessage = data.assistant_message;
        }

        if (this.testType === "models" && data.metrics) {
          this.testMetrics.modelCount = data.metrics.modelCount;
          this.modelList = data.data?.data || [];
        }
      } catch (error) {
        this.testResult = JSON.stringify({ error: error.message }, null, 2);
        this.testSuccess = false;
        this.testMetrics = {
          httpStatus: 0,
          httpStatusText: "Network Error",
        };
      } finally {
        this.testing = false;
      }
    },
  };
};

export const overviewDashboard = function () {
  return {
    init() {
      this.updateSvgColors();
      const observer = new MutationObserver(() => this.updateSvgColors());
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["class"],
      });
    },
    updateSvgColors() {
      const isDark = document.documentElement.classList.contains("dark");
      const svg = safeGetElement("overview-architecture");
      if (!svg) {
        return;
      }

      const marker = svg.querySelector("#arrowhead polygon");
      if (marker) {
        marker.setAttribute(
          "class",
          isDark ? "fill-gray-500" : "fill-gray-400",
        );
      }
    },
  };
};

// Debounce helper for search
const searchDebounceTimers = {};
export const debouncedServerSideUserSearch = function (
  teamId,
  searchTerm,
  delay = 300,
) {
  if (searchDebounceTimers[teamId]) {
    clearTimeout(searchDebounceTimers[teamId]);
  }
  searchDebounceTimers[teamId] = setTimeout(() => {
    serverSideUserSearch(teamId, searchTerm);
  }, delay);
};

// Team user search function - searches all users and splits into members/non-members
export const serverSideUserSearch = async function (teamId, searchTerm) {
  const membersContainer = safeGetElement(`team-members-container-${teamId}`);
  const nonMembersContainer = safeGetElement(
    `team-non-members-container-${teamId}`,
  );

  if (!membersContainer || !nonMembersContainer) {
    console.error("Team containers not found");
    return;
  }

  // Read per_page from data attributes (set server-side), fallback to 20
  const membersPerPage =
    membersContainer.dataset.perPage ||
    membersContainer.getAttribute("data-per-page") ||
    20;
  const nonMembersPerPage =
    nonMembersContainer.dataset.perPage ||
    nonMembersContainer.getAttribute("data-per-page") ||
    20;

  // If search is empty, reload both sections with full data
  if (!searchTerm || searchTerm.trim() === "") {
    try {
      // Reload members - use fetchWithAuth for bearer token support
      const membersResponse = await fetchWithAuth(
        `${window.ROOT_PATH}/admin/teams/${teamId}/members/partial?page=1&per_page=${membersPerPage}`,
      );
      if (membersResponse.ok) {
        membersContainer.innerHTML = await membersResponse.text();
        // Re-initialize HTMX on new content for infinite scroll triggers
        if (typeof htmx !== "undefined") {
          window.htmx.process(membersContainer);
        }
      }

      // Reload non-members
      const nonMembersResponse = await fetchWithAuth(
        `${window.ROOT_PATH}/admin/teams/${teamId}/non-members/partial?page=1&per_page=${nonMembersPerPage}`,
      );
      if (nonMembersResponse.ok) {
        nonMembersContainer.innerHTML = await nonMembersResponse.text();
        // Re-initialize HTMX on new content for infinite scroll triggers
        if (typeof htmx !== "undefined") {
          window.htmx.process(nonMembersContainer);
        }
      }
    } catch (error) {
      console.error("Error reloading user lists:", error);
    }
    return;
  }

  try {
    // First, collect member data AND checkbox states from DOM (before search replaces content)
    const memberDataFromDom = {};
    const checkboxStates = {}; // Track checkbox states for all visible users
    const existingMemberItems = document.querySelectorAll(
      `#team-members-container-${teamId} .user-item`,
    );
    existingMemberItems.forEach((item) => {
      const email = item.dataset.userEmail;
      if (email) {
        const roleSelect = item.querySelector(".role-select");
        const checkbox = item.querySelector(".user-checkbox");
        memberDataFromDom[email] = {
          role: roleSelect ? roleSelect.value : "member",
        };
        if (checkbox) {
          checkboxStates[email] = checkbox.checked;
        }
      }
    });

    // Also collect checkbox states from non-members section
    const existingNonMemberItems = document.querySelectorAll(
      `#team-non-members-container-${teamId} .user-item`,
    );
    existingNonMemberItems.forEach((item) => {
      const email = item.dataset.userEmail;
      if (email) {
        const checkbox = item.querySelector(".user-checkbox");
        const roleSelect = item.querySelector(".role-select");
        if (checkbox) {
          checkboxStates[email] = checkbox.checked;
          // Also preserve role selection for users being added
          if (checkbox.checked && roleSelect) {
            memberDataFromDom[email] = {
              role: roleSelect.value,
              pendingAdd: true, // Flag that this is a pending addition
            };
          }
        }
      }
    });

    // If no members found in DOM yet, fetch from server to get membership data with roles
    if (Object.keys(memberDataFromDom).length === 0) {
      try {
        const membersResp = await fetchWithAuth(
          `${window.ROOT_PATH}/admin/teams/${teamId}/members/partial?page=1&per_page=100`,
        );
        if (membersResp.ok) {
          const tempDiv = document.createElement("div");
          tempDiv.innerHTML = await membersResp.text();
          tempDiv.querySelectorAll(".user-item").forEach((item) => {
            const email = item.dataset.userEmail;
            if (email) {
              const roleSelect = item.querySelector(".role-select");
              memberDataFromDom[email] = {
                role: roleSelect ? roleSelect.value : "member",
              };
            }
          });
        }
      } catch (e) {
        console.error("Error fetching member data:", e);
      }
    }

    // Search all users - use fetchWithAuth for bearer token support
    const searchUrl = `${window.ROOT_PATH}/admin/users/search?q=${encodeURIComponent(searchTerm)}&limit=100`;
    const response = await fetchWithAuth(searchUrl);

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();

    if (data.users && data.users.length > 0) {
      // Split users into members and non-members based on collected data
      const members = [];
      const nonMembers = [];

      data.users.forEach((user) => {
        if (memberDataFromDom[user.email]) {
          members.push({
            ...user,
            role: memberDataFromDom[user.email].role,
          });
        } else {
          nonMembers.push(user);
        }
      });

      // Render members with preserved roles, checkbox states, and loadedMembers hidden input
      let membersHtml = "";
      members.forEach((user) => {
        const fullName = escapeHtml(user.full_name || user.email);
        const email = escapeHtml(user.email);
        const role = user.role || "member";
        const isOwner = role === "owner";
        // Preserve checkbox state if available, otherwise default to checked for existing members
        const isChecked =
          checkboxStates[user.email] !== undefined
            ? checkboxStates[user.email]
            : true;
        membersHtml += `
      <div class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 p-3 hover:bg-indigo-50 dark:hover:bg-indigo-900 rounded-md user-item border border-indigo-200 dark:border-indigo-800 bg-indigo-50/50 dark:bg-indigo-900/20" data-user-email="${email}">
          <div class="flex-shrink-0">
              <div class="w-8 h-8 bg-gray-300 dark:bg-gray-600 rounded-full flex items-center justify-center">
                  <span class="text-sm font-medium text-gray-700 dark:text-gray-300">${user.email[0].toUpperCase()}</span>
              </div>
          </div>
          <input type="hidden" name="loadedMembers" value="${email}" />
          <input type="checkbox" name="associatedUsers" value="${email}" data-user-name="${fullName}" class="user-checkbox form-checkbox h-5 w-5 text-indigo-600 dark:bg-gray-800 dark:border-gray-600 flex-shrink-0" ${isChecked ? "checked" : ""} data-auto-check="true" />
          <div class="flex-grow min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                  <span class="select-none font-medium text-gray-900 dark:text-white truncate">${fullName}</span>
                  ${isOwner ? '<span class="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-800 rounded-full dark:bg-purple-900 dark:text-purple-200">Owner</span>' : ""}
              </div>
              <div class="text-sm text-gray-500 dark:text-gray-400 truncate">${email}</div>
          </div>
          <select name="role_${encodeURIComponent(user.email)}" class="role-select text-sm px-2 py-1 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-white flex-shrink-0">
              <option value="member" ${!isOwner ? "selected" : ""}>Member</option>
              <option value="owner" ${isOwner ? "selected" : ""}>Owner</option>
          </select>
      </div>
  `;
      });

      // Render non-members with preserved checkbox states and roles
      let nonMembersHtml = "";
      nonMembers.forEach((user) => {
        const fullName = escapeHtml(user.full_name || user.email);
        const email = escapeHtml(user.email);
        // Preserve checkbox state if available, otherwise default to unchecked for non-members
        const isChecked =
          checkboxStates[user.email] !== undefined
            ? checkboxStates[user.email]
            : false;
        // Preserve role selection for users being added
        const pendingData = memberDataFromDom[user.email];
        const role =
          pendingData && pendingData.pendingAdd ? pendingData.role : "member";
        const isOwner = role === "owner";
        nonMembersHtml += `
      <div class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 p-3 hover:bg-indigo-50 dark:hover:bg-indigo-900 rounded-md user-item border border-transparent" data-user-email="${email}" data-is-member="false">
          <div class="flex-shrink-0">
              <div class="w-8 h-8 bg-gray-300 dark:bg-gray-600 rounded-full flex items-center justify-center">
                  <span class="text-sm font-medium text-gray-700 dark:text-gray-300">${user.email[0].toUpperCase()}</span>
              </div>
          </div>
          <input type="checkbox" name="associatedUsers" value="${email}" data-user-name="${fullName}" class="user-checkbox form-checkbox h-5 w-5 text-indigo-600 dark:bg-gray-800 dark:border-gray-600 flex-shrink-0" ${isChecked ? "checked" : ""} />
          <div class="flex-grow min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                  <span class="select-none font-medium text-gray-900 dark:text-white truncate">${fullName}</span>
              </div>
              <div class="text-sm text-gray-500 dark:text-gray-400 truncate">${email}</div>
          </div>
          <select name="role_${encodeURIComponent(user.email)}" class="role-select text-sm px-2 py-1 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-white flex-shrink-0">
              <option value="member" ${!isOwner ? "selected" : ""}>Member</option>
              <option value="owner" ${isOwner ? "selected" : ""}>Owner</option>
          </select>
      </div>
  `;
      });

      membersContainer.innerHTML =
        membersHtml ||
        '<div class="text-center py-4 text-gray-500 dark:text-gray-400">No matching members</div>';
      nonMembersContainer.innerHTML =
        nonMembersHtml ||
        '<div class="text-center py-4 text-gray-500 dark:text-gray-400">No matching users</div>';
    } else {
      // No results
      membersContainer.innerHTML =
        '<div class="text-center py-4 text-gray-500 dark:text-gray-400">No matching members</div>';
      nonMembersContainer.innerHTML =
        '<div class="text-center py-4 text-gray-500 dark:text-gray-400">No matching users</div>';
    }
  } catch (error) {
    console.error("Error searching users:", error);
    membersContainer.innerHTML =
      '<div class="text-center py-4 text-red-600">Error searching users</div>';
    nonMembersContainer.innerHTML =
      '<div class="text-center py-4 text-red-600">Error searching users</div>';
  }
};
