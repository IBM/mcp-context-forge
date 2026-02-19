/**
 * Unit tests for llmModels.js module
 * Tests: switchLLMSettingsTab, onLLMProviderTypeChange, showAddProviderModal,
 *        closeLLMProviderModal, fetchLLMProviderModels, syncLLMProviderModels,
 *        editLLMProvider, saveLLMProvider, deleteLLMProvider, toggleLLMProvider,
 *        checkLLMProviderHealth, showAddModelModal, populateProviderDropdown,
 *        closeLLMModelModal, onModelProviderChange, fetchModelsForModelModal,
 *        editLLMModel, saveLLMModel, deleteLLMModel, toggleLLMModel,
 *        filterModelsByProvider, llmApiInfoApp, overviewDashboard,
 *        debouncedServerSideUserSearch, serverSideUserSearch
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import {
  switchLLMSettingsTab,
  onLLMProviderTypeChange,
  showAddProviderModal,
  closeLLMProviderModal,
  fetchLLMProviderModels,
  syncLLMProviderModels,
  editLLMProvider,
  saveLLMProvider,
  deleteLLMProvider,
  toggleLLMProvider,
  checkLLMProviderHealth,
  showAddModelModal,
  populateProviderDropdown,
  closeLLMModelModal,
  onModelProviderChange,
  fetchModelsForModelModal,
  editLLMModel,
  saveLLMModel,
  deleteLLMModel,
  toggleLLMModel,
  filterModelsByProvider,
  llmApiInfoApp,
  overviewDashboard,
  debouncedServerSideUserSearch,
  serverSideUserSearch,
} from "../../../mcpgateway/admin_ui/llmModels.js";

import { showCopyableModal } from "../../../mcpgateway/admin_ui/modals.js";
import { fetchWithAuth } from "../../../mcpgateway/admin_ui/tokens.js";
import { showToast } from "../../../mcpgateway/admin_ui/utils.js";

// Mock dependencies before imports
vi.mock("../../../mcpgateway/admin_ui/modals.js", () => ({
  showCopyableModal: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  parseErrorResponse: vi.fn((response, defaultMsg) =>
    Promise.resolve(defaultMsg)
  ),
}));

vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  fetchWithAuth: vi.fn(),
  getAuthToken: vi.fn(() => Promise.resolve("test-token")),
}));

vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showToast: vi.fn(),
}));

beforeEach(() => {
  window.ROOT_PATH = "";
  window.htmx = {
    trigger: vi.fn(),
    ajax: vi.fn(),
    process: vi.fn(),
  };
  vi.clearAllMocks();
});

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  delete window.htmx;
});

// ---------------------------------------------------------------------------
// switchLLMSettingsTab
// ---------------------------------------------------------------------------
describe("switchLLMSettingsTab", () => {
  test("switches to providers tab", () => {
    const providersPanel = document.createElement("div");
    providersPanel.id = "llm-settings-content-providers";
    providersPanel.classList.add("llm-settings-content", "hidden");
    document.body.appendChild(providersPanel);

    const modelsPanel = document.createElement("div");
    modelsPanel.id = "llm-settings-content-models";
    modelsPanel.classList.add("llm-settings-content");
    document.body.appendChild(modelsPanel);

    const providersTab = document.createElement("div");
    providersTab.id = "llm-settings-tab-providers";
    providersTab.classList.add("llm-settings-tab", "border-transparent");
    document.body.appendChild(providersTab);

    switchLLMSettingsTab("providers");

    expect(providersPanel.classList.contains("hidden")).toBe(false);
    expect(modelsPanel.classList.contains("hidden")).toBe(true);
    expect(providersTab.classList.contains("border-indigo-500")).toBe(true);
    expect(window.htmx.trigger).toHaveBeenCalledWith(providersPanel, "revealed");
  });

  test("switches to models tab", () => {
    const providersPanel = document.createElement("div");
    providersPanel.id = "llm-settings-content-providers";
    providersPanel.classList.add("llm-settings-content");
    document.body.appendChild(providersPanel);

    const modelsPanel = document.createElement("div");
    modelsPanel.id = "llm-settings-content-models";
    modelsPanel.classList.add("llm-settings-content", "hidden");
    document.body.appendChild(modelsPanel);

    const modelsTab = document.createElement("div");
    modelsTab.id = "llm-settings-tab-models";
    modelsTab.classList.add("llm-settings-tab", "border-transparent");
    document.body.appendChild(modelsTab);

    switchLLMSettingsTab("models");

    expect(modelsPanel.classList.contains("hidden")).toBe(false);
    expect(providersPanel.classList.contains("hidden")).toBe(true);
    expect(modelsTab.classList.contains("border-indigo-500")).toBe(true);
  });

  test("handles missing panel gracefully", () => {
    const providersTab = document.createElement("div");
    providersTab.id = "llm-settings-tab-providers";
    document.body.appendChild(providersTab);

    expect(() => switchLLMSettingsTab("providers")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// onLLMProviderTypeChange
// ---------------------------------------------------------------------------
describe("onLLMProviderTypeChange", () => {
  test("hides config section when provider type is empty", async () => {
    const providerType = document.createElement("select");
    providerType.id = "llm-provider-type";
    providerType.value = "";
    document.body.appendChild(providerType);

    const configSection = document.createElement("div");
    configSection.id = "llm-provider-specific-config";
    document.body.appendChild(configSection);

    await onLLMProviderTypeChange();

    expect(configSection.classList.contains("hidden")).toBe(true);
  });

  test("auto-fills defaults for new provider", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    // Mock first fetch for provider defaults
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          openai: {
            api_base: "https://api.openai.com/v1",
            default_model: "gpt-4",
            description: "OpenAI API",
            requires_api_key: true,
          },
        }),
    });

    // Mock second fetch for provider configs
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    });

    const providerType = document.createElement("select");
    providerType.id = "llm-provider-type";
    const option = document.createElement("option");
    option.value = "openai";
    option.selected = true;
    providerType.appendChild(option);
    document.body.appendChild(providerType);

    const providerId = document.createElement("input");
    providerId.id = "llm-provider-id";
    providerId.value = "";
    document.body.appendChild(providerId);

    const apiBase = document.createElement("input");
    apiBase.id = "llm-provider-api-base";
    apiBase.value = "";
    document.body.appendChild(apiBase);

    const defaultModel = document.createElement("input");
    defaultModel.id = "llm-provider-default-model";
    defaultModel.value = "";
    document.body.appendChild(defaultModel);

    const description = document.createElement("p");
    description.id = "llm-provider-type-description";
    description.classList.add("hidden");
    document.body.appendChild(description);

    const apiKeyRequired = document.createElement("div");
    apiKeyRequired.id = "llm-provider-api-key-required";
    apiKeyRequired.classList.add("hidden");
    document.body.appendChild(apiKeyRequired);

    const configSection = document.createElement("div");
    configSection.id = "llm-provider-specific-config";
    document.body.appendChild(configSection);

    const fieldsContainer = document.createElement("div");
    fieldsContainer.id = "llm-provider-config-fields";
    document.body.appendChild(fieldsContainer);

    await onLLMProviderTypeChange();

    expect(apiBase.value).toBe("https://api.openai.com/v1");
    expect(defaultModel.value).toBe("gpt-4");
    expect(description.textContent).toBe("OpenAI API");
    expect(description.classList.contains("hidden")).toBe(false);
    expect(apiKeyRequired.classList.contains("hidden")).toBe(false);

    fetchSpy.mockRestore();
    consoleSpy.mockRestore();
  });

  test("does not auto-fill when editing existing provider", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          openai: {
            api_base: "https://api.openai.com/v1",
            default_model: "gpt-4",
          },
        }),
    });

    const providerType = document.createElement("select");
    providerType.id = "llm-provider-type";
    providerType.value = "openai";
    document.body.appendChild(providerType);

    const providerId = document.createElement("input");
    providerId.id = "llm-provider-id";
    providerId.value = "existing-id";
    document.body.appendChild(providerId);

    const apiBase = document.createElement("input");
    apiBase.id = "llm-provider-api-base";
    apiBase.value = "https://custom.api.com";
    document.body.appendChild(apiBase);

    const defaultModel = document.createElement("input");
    defaultModel.id = "llm-provider-default-model";
    defaultModel.value = "custom-model";
    document.body.appendChild(defaultModel);

    const configSection = document.createElement("div");
    configSection.id = "llm-provider-specific-config";
    document.body.appendChild(configSection);

    const fieldsContainer = document.createElement("div");
    fieldsContainer.id = "llm-provider-config-fields";
    document.body.appendChild(fieldsContainer);

    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    });

    await onLLMProviderTypeChange();

    expect(apiBase.value).toBe("https://custom.api.com");
    expect(defaultModel.value).toBe("custom-model");

    fetchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// showAddProviderModal / closeLLMProviderModal
// ---------------------------------------------------------------------------
describe("showAddProviderModal / closeLLMProviderModal", () => {
  test("opens modal and resets form", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });

    const modal = document.createElement("div");
    modal.id = "llm-provider-modal";
    modal.classList.add("hidden");
    document.body.appendChild(modal);

    const form = document.createElement("form");
    form.id = "llm-provider-form";
    document.body.appendChild(form);

    const providerId = document.createElement("input");
    providerId.id = "llm-provider-id";
    providerId.value = "old-id";
    document.body.appendChild(providerId);

    const modalTitle = document.createElement("h2");
    modalTitle.id = "llm-provider-modal-title";
    document.body.appendChild(modalTitle);

    const description = document.createElement("p");
    description.id = "llm-provider-type-description";
    document.body.appendChild(description);

    await showAddProviderModal();

    expect(providerId.value).toBe("");
    expect(modalTitle.textContent).toBe("Add LLM Provider");
    expect(modal.classList.contains("hidden")).toBe(false);

    fetchSpy.mockRestore();
  });

  test("closes modal", () => {
    const modal = document.createElement("div");
    modal.id = "llm-provider-modal";
    document.body.appendChild(modal);

    closeLLMProviderModal();

    expect(modal.classList.contains("hidden")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// fetchLLMProviderModels
// ---------------------------------------------------------------------------
describe("fetchLLMProviderModels", () => {
  test("fetches models successfully", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          success: true,
          count: 2,
          models: [
            { id: "gpt-4", owned_by: "openai" },
            { id: "gpt-3.5-turbo", owned_by: "openai" },
          ],
        }),
    });

    const result = await fetchLLMProviderModels("provider-1");

    expect(result.success).toBe(true);
    expect(result.count).toBe(2);
    expect(showCopyableModal).toHaveBeenCalledWith(
      "Found 2 Models",
      expect.stringContaining("gpt-4"),
      "success"
    );

    fetchSpy.mockRestore();
  });

  test("handles fetch error", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ success: false, error: "API error" }),
    });

    const result = await fetchLLMProviderModels("provider-1");

    expect(result.success).toBe(false);
    expect(showCopyableModal).toHaveBeenCalledWith(
      "Failed to Fetch Models",
      "API error",
      "error"
    );

    fetchSpy.mockRestore();
  });

  test("handles network error", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockRejectedValue(new Error("Network error"));

    const result = await fetchLLMProviderModels("provider-1");

    expect(result.success).toBe(false);
    expect(result.error).toBe("Network error");
    expect(showCopyableModal).toHaveBeenCalledWith(
      "Failed to Fetch Models",
      expect.stringContaining("Network error"),
      "error"
    );

    fetchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// syncLLMProviderModels
// ---------------------------------------------------------------------------
describe("syncLLMProviderModels", () => {
  test("syncs models successfully", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          success: true,
          message: "Synced 5 models",
          total: 10,
        }),
    });

    const container = document.createElement("div");
    container.id = "llm-models-container";
    document.body.appendChild(container);

    const result = await syncLLMProviderModels("provider-1");

    expect(result.success).toBe(true);
    expect(showToast).toHaveBeenCalledWith("Syncing models...", "info");
    expect(showCopyableModal).toHaveBeenCalledWith(
      "Models Synced Successfully",
      expect.stringContaining("Synced 5 models"),
      "success"
    );
    expect(window.htmx.ajax).toHaveBeenCalled();

    fetchSpy.mockRestore();
  });

  test("handles sync error", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ success: false, error: "Sync failed" }),
    });

    const result = await syncLLMProviderModels("provider-1");

    expect(result.success).toBe(false);
    expect(showCopyableModal).toHaveBeenCalledWith(
      "Failed to Sync Models",
      "Sync failed",
      "error"
    );

    fetchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// editLLMProvider
// ---------------------------------------------------------------------------
describe("editLLMProvider", () => {
  test("loads provider data and opens modal", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // First call to fetch provider data
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "provider-1",
          name: "OpenAI",
          provider_type: "openai",
          description: "OpenAI provider",
          api_base: "https://api.openai.com/v1",
          default_model: "gpt-4",
          default_temperature: 0.7,
          default_max_tokens: 1000,
          enabled: true,
          config: { organization: "org-123" },
        }),
    });

    // Second call for renderProviderSpecificFields
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    });

    const modal = document.createElement("div");
    modal.id = "llm-provider-modal";
    modal.classList.add("hidden");
    document.body.appendChild(modal);

    const providerId = document.createElement("input");
    providerId.id = "llm-provider-id";
    document.body.appendChild(providerId);

    const name = document.createElement("input");
    name.id = "llm-provider-name";
    document.body.appendChild(name);

    const providerType = document.createElement("select");
    providerType.id = "llm-provider-type";
    const typeOption = document.createElement("option");
    typeOption.value = "openai";
    typeOption.selected = true;
    providerType.appendChild(typeOption);
    document.body.appendChild(providerType);

    const description = document.createElement("input");
    description.id = "llm-provider-description";
    document.body.appendChild(description);

    const apiKey = document.createElement("input");
    apiKey.id = "llm-provider-api-key";
    document.body.appendChild(apiKey);

    const apiBase = document.createElement("input");
    apiBase.id = "llm-provider-api-base";
    document.body.appendChild(apiBase);

    const defaultModel = document.createElement("input");
    defaultModel.id = "llm-provider-default-model";
    document.body.appendChild(defaultModel);

    const temperature = document.createElement("input");
    temperature.id = "llm-provider-temperature";
    document.body.appendChild(temperature);

    const maxTokens = document.createElement("input");
    maxTokens.id = "llm-provider-max-tokens";
    document.body.appendChild(maxTokens);

    const enabled = document.createElement("input");
    enabled.id = "llm-provider-enabled";
    enabled.type = "checkbox";
    document.body.appendChild(enabled);

    const modalTitle = document.createElement("h2");
    modalTitle.id = "llm-provider-modal-title";
    document.body.appendChild(modalTitle);

    const configField = document.createElement("input");
    configField.id = "llm-config-organization";
    document.body.appendChild(configField);

    const configSection = document.createElement("div");
    configSection.id = "llm-provider-specific-config";
    document.body.appendChild(configSection);

    const fieldsContainer = document.createElement("div");
    fieldsContainer.id = "llm-provider-config-fields";
    document.body.appendChild(fieldsContainer);

    await editLLMProvider("provider-1");

    expect(providerId.value).toBe("provider-1");
    expect(name.value).toBe("OpenAI");
    expect(providerType.value).toBe("openai");
    expect(description.value).toBe("OpenAI provider");
    expect(apiBase.value).toBe("https://api.openai.com/v1");
    expect(defaultModel.value).toBe("gpt-4");
    expect(temperature.value).toBe("0.7");
    expect(maxTokens.value).toBe("1000");
    expect(enabled.checked).toBe(true);
    expect(modalTitle.textContent).toBe("Edit LLM Provider");
    expect(modal.classList.contains("hidden")).toBe(false);

    fetchSpy.mockRestore();
    consoleSpy.mockRestore();
  });

  test("handles fetch error", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
    });

    await editLLMProvider("provider-1");

    expect(showToast).toHaveBeenCalledWith("Failed to load provider details", "error");

    fetchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// saveLLMProvider
// ---------------------------------------------------------------------------
describe("saveLLMProvider", () => {
  test("creates new provider", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ id: "new-provider" }),
    });

    const providerId = document.createElement("input");
    providerId.id = "llm-provider-id";
    providerId.value = "";
    document.body.appendChild(providerId);

    const name = document.createElement("input");
    name.id = "llm-provider-name";
    name.value = "New Provider";
    document.body.appendChild(name);

    const providerType = document.createElement("select");
    providerType.id = "llm-provider-type";
    providerType.value = "openai";
    document.body.appendChild(providerType);

    const description = document.createElement("input");
    description.id = "llm-provider-description";
    description.value = "Test provider";
    document.body.appendChild(description);

    const apiKey = document.createElement("input");
    apiKey.id = "llm-provider-api-key";
    apiKey.value = "sk-test";
    document.body.appendChild(apiKey);

    const apiBase = document.createElement("input");
    apiBase.id = "llm-provider-api-base";
    apiBase.value = "https://api.test.com";
    document.body.appendChild(apiBase);

    const defaultModel = document.createElement("input");
    defaultModel.id = "llm-provider-default-model";
    defaultModel.value = "test-model";
    document.body.appendChild(defaultModel);

    const temperature = document.createElement("input");
    temperature.id = "llm-provider-temperature";
    temperature.value = "0.5";
    document.body.appendChild(temperature);

    const maxTokens = document.createElement("input");
    maxTokens.id = "llm-provider-max-tokens";
    maxTokens.value = "2000";
    document.body.appendChild(maxTokens);

    const enabled = document.createElement("input");
    enabled.id = "llm-provider-enabled";
    enabled.type = "checkbox";
    enabled.checked = true;
    document.body.appendChild(enabled);

    const configFields = document.createElement("div");
    configFields.id = "llm-provider-config-fields";
    document.body.appendChild(configFields);

    const modal = document.createElement("div");
    modal.id = "llm-provider-modal";
    document.body.appendChild(modal);

    const container = document.createElement("div");
    container.id = "llm-providers-container";
    document.body.appendChild(container);

    const event = { preventDefault: vi.fn() };
    await saveLLMProvider(event);

    expect(event.preventDefault).toHaveBeenCalled();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/llm/providers",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
      })
    );
    expect(showToast).toHaveBeenCalledWith(
      "Provider created successfully",
      "success"
    );

    fetchSpy.mockRestore();
  });

  test("updates existing provider", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });

    const providerId = document.createElement("input");
    providerId.id = "llm-provider-id";
    providerId.value = "provider-1";
    document.body.appendChild(providerId);

    const name = document.createElement("input");
    name.id = "llm-provider-name";
    name.value = "Updated Provider";
    document.body.appendChild(name);

    const providerType = document.createElement("select");
    providerType.id = "llm-provider-type";
    providerType.value = "openai";
    document.body.appendChild(providerType);

    const description = document.createElement("input");
    description.id = "llm-provider-description";
    description.value = "";
    document.body.appendChild(description);

    const apiKey = document.createElement("input");
    apiKey.id = "llm-provider-api-key";
    apiKey.value = "";
    document.body.appendChild(apiKey);

    const apiBase = document.createElement("input");
    apiBase.id = "llm-provider-api-base";
    apiBase.value = "";
    document.body.appendChild(apiBase);

    const defaultModel = document.createElement("input");
    defaultModel.id = "llm-provider-default-model";
    defaultModel.value = "";
    document.body.appendChild(defaultModel);

    const temperature = document.createElement("input");
    temperature.id = "llm-provider-temperature";
    temperature.value = "0.7";
    document.body.appendChild(temperature);

    const maxTokens = document.createElement("input");
    maxTokens.id = "llm-provider-max-tokens";
    maxTokens.value = "";
    document.body.appendChild(maxTokens);

    const enabled = document.createElement("input");
    enabled.id = "llm-provider-enabled";
    enabled.type = "checkbox";
    enabled.checked = false;
    document.body.appendChild(enabled);

    const configFields = document.createElement("div");
    configFields.id = "llm-provider-config-fields";
    document.body.appendChild(configFields);

    const modal = document.createElement("div");
    modal.id = "llm-provider-modal";
    document.body.appendChild(modal);

    const container = document.createElement("div");
    container.id = "llm-providers-container";
    document.body.appendChild(container);

    const event = { preventDefault: vi.fn() };
    await saveLLMProvider(event);

    expect(fetchSpy).toHaveBeenCalledWith(
      "/llm/providers/provider-1",
      expect.objectContaining({
        method: "PATCH",
      })
    );
    expect(showToast).toHaveBeenCalledWith(
      "Provider updated successfully",
      "success"
    );

    fetchSpy.mockRestore();
  });

  test("handles save error", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 400,
    });

    const providerId = document.createElement("input");
    providerId.id = "llm-provider-id";
    providerId.value = "";
    document.body.appendChild(providerId);

    const name = document.createElement("input");
    name.id = "llm-provider-name";
    name.value = "Test";
    document.body.appendChild(name);

    const providerType = document.createElement("select");
    providerType.id = "llm-provider-type";
    providerType.value = "openai";
    document.body.appendChild(providerType);

    const description = document.createElement("input");
    description.id = "llm-provider-description";
    document.body.appendChild(description);

    const apiKey = document.createElement("input");
    apiKey.id = "llm-provider-api-key";
    document.body.appendChild(apiKey);

    const apiBase = document.createElement("input");
    apiBase.id = "llm-provider-api-base";
    document.body.appendChild(apiBase);

    const defaultModel = document.createElement("input");
    defaultModel.id = "llm-provider-default-model";
    document.body.appendChild(defaultModel);

    const temperature = document.createElement("input");
    temperature.id = "llm-provider-temperature";
    temperature.value = "0.7";
    document.body.appendChild(temperature);

    const maxTokens = document.createElement("input");
    maxTokens.id = "llm-provider-max-tokens";
    document.body.appendChild(maxTokens);

    const enabled = document.createElement("input");
    enabled.id = "llm-provider-enabled";
    enabled.type = "checkbox";
    document.body.appendChild(enabled);

    const configFields = document.createElement("div");
    configFields.id = "llm-provider-config-fields";
    document.body.appendChild(configFields);

    const event = { preventDefault: vi.fn() };
    await saveLLMProvider(event);

    expect(showToast).toHaveBeenCalledWith("Failed to save provider", "error");

    fetchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// deleteLLMProvider
// ---------------------------------------------------------------------------
describe("deleteLLMProvider", () => {
  test("deletes provider after confirmation", async () => {
    const confirmSpy = vi.spyOn(globalThis, "confirm").mockReturnValue(true);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
    });

    const container = document.createElement("div");
    container.id = "llm-providers-container";
    document.body.appendChild(container);

    await deleteLLMProvider("provider-1", "Test Provider");

    expect(confirmSpy).toHaveBeenCalledWith(
      expect.stringContaining("Test Provider")
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/llm/providers/provider-1",
      expect.objectContaining({ method: "DELETE" })
    );
    expect(showToast).toHaveBeenCalledWith(
      "Provider deleted successfully",
      "success"
    );

    confirmSpy.mockRestore();
    fetchSpy.mockRestore();
  });

  test("does not delete if user cancels", async () => {
    const confirmSpy = vi.spyOn(globalThis, "confirm").mockReturnValue(false);
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    await deleteLLMProvider("provider-1", "Test Provider");

    expect(confirmSpy).toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();

    confirmSpy.mockRestore();
  });

  test("handles delete error", async () => {
    const confirmSpy = vi.spyOn(globalThis, "confirm").mockReturnValue(true);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
    });

    await deleteLLMProvider("provider-1", "Test Provider");

    expect(showToast).toHaveBeenCalledWith("Failed to delete provider", "error");

    confirmSpy.mockRestore();
    fetchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// toggleLLMProvider
// ---------------------------------------------------------------------------
describe("toggleLLMProvider", () => {
  test("toggles provider state", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
    });

    const container = document.createElement("div");
    container.id = "llm-providers-container";
    document.body.appendChild(container);

    await toggleLLMProvider("provider-1");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/llm/providers/provider-1/state",
      expect.objectContaining({ method: "POST" })
    );
    expect(window.htmx.ajax).toHaveBeenCalled();

    fetchSpy.mockRestore();
  });

  test("handles toggle error", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
    });

    await toggleLLMProvider("provider-1");

    expect(showToast).toHaveBeenCalledWith("Failed to toggle provider", "error");

    fetchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// checkLLMProviderHealth
// ---------------------------------------------------------------------------
describe("checkLLMProviderHealth", () => {
  test("shows healthy status", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          status: "healthy",
          latency_ms: 123,
        }),
    });

    const container = document.createElement("div");
    container.id = "llm-providers-container";
    document.body.appendChild(container);

    await checkLLMProviderHealth("provider-1");

    expect(showCopyableModal).toHaveBeenCalledWith(
      "Health Check Passed",
      expect.stringContaining("123ms"),
      "success"
    );

    fetchSpy.mockRestore();
  });

  test("shows unhealthy status with error", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          status: "unhealthy",
          error: "Connection timeout",
        }),
    });

    const container = document.createElement("div");
    container.id = "llm-providers-container";
    document.body.appendChild(container);

    await checkLLMProviderHealth("provider-1");

    expect(showCopyableModal).toHaveBeenCalledWith(
      "Health Check Failed",
      expect.stringContaining("Connection timeout"),
      "error"
    );

    fetchSpy.mockRestore();
  });

  test("handles network error", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockRejectedValue(new Error("Network error"));

    await checkLLMProviderHealth("provider-1");

    expect(showCopyableModal).toHaveBeenCalledWith(
      "Health Check Request Failed",
      expect.stringContaining("Network error"),
      "error"
    );

    fetchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// showAddModelModal / closeLLMModelModal
// ---------------------------------------------------------------------------
describe("showAddModelModal / closeLLMModelModal", () => {
  test("opens modal and populates providers", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          providers: [
            { id: "p1", name: "OpenAI", provider_type: "openai" },
            { id: "p2", name: "Anthropic", provider_type: "anthropic" },
          ],
        }),
    });

    const modal = document.createElement("div");
    modal.id = "llm-model-modal";
    modal.classList.add("hidden");
    document.body.appendChild(modal);

    const form = document.createElement("form");
    form.id = "llm-model-form";
    document.body.appendChild(form);

    const modelId = document.createElement("input");
    modelId.id = "llm-model-id";
    document.body.appendChild(modelId);

    const modalTitle = document.createElement("h2");
    modalTitle.id = "llm-model-modal-title";
    document.body.appendChild(modalTitle);

    const providerSelect = document.createElement("select");
    providerSelect.id = "llm-model-provider";
    document.body.appendChild(providerSelect);

    await showAddModelModal();

    expect(modalTitle.textContent).toBe("Add LLM Model");
    expect(modal.classList.contains("hidden")).toBe(false);
    expect(providerSelect.options.length).toBe(3); // 1 empty + 2 providers

    fetchSpy.mockRestore();
  });

  test("closes modal", () => {
    const modal = document.createElement("div");
    modal.id = "llm-model-modal";
    document.body.appendChild(modal);

    closeLLMModelModal();

    expect(modal.classList.contains("hidden")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// populateProviderDropdown
// ---------------------------------------------------------------------------
describe("populateProviderDropdown", () => {
  test("populates dropdown with providers", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          providers: [
            { id: "p1", name: "OpenAI", provider_type: "openai" },
            { id: "p2", name: "Anthropic", provider_type: "anthropic" },
          ],
        }),
    });

    const select = document.createElement("select");
    select.id = "llm-model-provider";
    document.body.appendChild(select);

    await populateProviderDropdown();

    expect(select.options.length).toBe(3);
    expect(select.options[1].value).toBe("p1");
    expect(select.options[1].textContent).toBe("OpenAI (openai)");

    fetchSpy.mockRestore();
  });

  test("handles fetch error", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
    });

    const select = document.createElement("select");
    select.id = "llm-model-provider";
    document.body.appendChild(select);

    await populateProviderDropdown();

    expect(select.options.length).toBe(0);

    fetchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// onModelProviderChange
// ---------------------------------------------------------------------------
describe("onModelProviderChange", () => {
  test("clears suggestions when no provider selected", async () => {
    const providerSelect = document.createElement("select");
    providerSelect.id = "llm-model-provider";
    providerSelect.value = "";
    document.body.appendChild(providerSelect);

    const modelInput = document.createElement("input");
    modelInput.id = "llm-model-model-id";
    document.body.appendChild(modelInput);

    const datalist = document.createElement("datalist");
    datalist.id = "llm-model-suggestions";
    document.body.appendChild(datalist);

    const statusEl = document.createElement("div");
    statusEl.id = "llm-model-fetch-status";
    document.body.appendChild(statusEl);

    await onModelProviderChange();

    expect(modelInput.placeholder).toBe("Select provider first...");
    expect(statusEl.classList.contains("hidden")).toBe(true);
    expect(datalist.innerHTML).toBe("");
  });

  test("fetches models when provider is selected", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          success: true,
          models: [{ id: "gpt-4", name: "GPT-4" }],
        }),
    });

    const providerSelect = document.createElement("select");
    providerSelect.id = "llm-model-provider";
    const option = document.createElement("option");
    option.value = "p1";
    option.selected = true;
    providerSelect.appendChild(option);
    document.body.appendChild(providerSelect);

    const modelInput = document.createElement("input");
    modelInput.id = "llm-model-model-id";
    document.body.appendChild(modelInput);

    const datalist = document.createElement("datalist");
    datalist.id = "llm-model-suggestions";
    document.body.appendChild(datalist);

    const statusEl = document.createElement("div");
    statusEl.id = "llm-model-fetch-status";
    statusEl.classList.add("hidden");
    document.body.appendChild(statusEl);

    await onModelProviderChange();

    expect(modelInput.placeholder).toBe("Type or select a model...");
    expect(datalist.options.length).toBe(1);

    fetchSpy.mockRestore();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// fetchModelsForModelModal
// ---------------------------------------------------------------------------
describe("fetchModelsForModelModal", () => {
  test("fetches and populates model suggestions", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          success: true,
          models: [
            { id: "gpt-4", name: "GPT-4" },
            { id: "gpt-3.5-turbo", name: "GPT-3.5 Turbo" },
          ],
        }),
    });

    const providerSelect = document.createElement("select");
    providerSelect.id = "llm-model-provider";
    const option = document.createElement("option");
    option.value = "p1";
    option.selected = true;
    providerSelect.appendChild(option);
    document.body.appendChild(providerSelect);

    const datalist = document.createElement("datalist");
    datalist.id = "llm-model-suggestions";
    document.body.appendChild(datalist);

    const statusEl = document.createElement("div");
    statusEl.id = "llm-model-fetch-status";
    statusEl.classList.add("hidden");
    document.body.appendChild(statusEl);

    await fetchModelsForModelModal();

    expect(statusEl.classList.contains("hidden")).toBe(false);
    expect(statusEl.textContent).toContain("Found 2 models");
    expect(datalist.options.length).toBe(2);

    fetchSpy.mockRestore();
    consoleSpy.mockRestore();
  });

  test("shows warning when no provider selected", async () => {
    const providerSelect = document.createElement("select");
    providerSelect.id = "llm-model-provider";
    providerSelect.value = "";
    document.body.appendChild(providerSelect);

    const datalist = document.createElement("datalist");
    datalist.id = "llm-model-suggestions";
    document.body.appendChild(datalist);

    const statusEl = document.createElement("div");
    statusEl.id = "llm-model-fetch-status";
    document.body.appendChild(statusEl);

    await fetchModelsForModelModal();

    expect(showToast).toHaveBeenCalledWith("Please select a provider first", "warning");
  });

  test("handles fetch error gracefully", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockRejectedValueOnce(new Error("Network error"));

    const providerSelect = document.createElement("select");
    providerSelect.id = "llm-model-provider";
    const option = document.createElement("option");
    option.value = "p1";
    option.selected = true;
    providerSelect.appendChild(option);
    document.body.appendChild(providerSelect);

    const datalist = document.createElement("datalist");
    datalist.id = "llm-model-suggestions";
    document.body.appendChild(datalist);

    const statusEl = document.createElement("div");
    statusEl.id = "llm-model-fetch-status";
    statusEl.classList.add("hidden");
    document.body.appendChild(statusEl);

    await fetchModelsForModelModal();

    expect(statusEl.textContent).toContain("Failed to fetch models");

    fetchSpy.mockRestore();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// editLLMModel
// ---------------------------------------------------------------------------
describe("editLLMModel", () => {
  test("loads model data and opens modal", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // First call for model data
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "model-1",
          provider_id: "p1",
          model_id: "gpt-4",
          model_name: "GPT-4",
          model_alias: "gpt4",
          description: "Test model",
          context_window: 8192,
          max_output_tokens: 4096,
          supports_chat: true,
          supports_streaming: true,
          supports_function_calling: true,
          supports_vision: false,
          enabled: true,
          deprecated: false,
        }),
    });

    // Second call for populateProviderDropdown
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          providers: [{ id: "p1", name: "OpenAI", provider_type: "openai" }],
        }),
    });

    const modal = document.createElement("div");
    modal.id = "llm-model-modal";
    modal.classList.add("hidden");
    document.body.appendChild(modal);

    const modelId = document.createElement("input");
    modelId.id = "llm-model-id";
    document.body.appendChild(modelId);

    const providerId = document.createElement("select");
    providerId.id = "llm-model-provider";
    document.body.appendChild(providerId);

    const modelIdInput = document.createElement("input");
    modelIdInput.id = "llm-model-model-id";
    document.body.appendChild(modelIdInput);

    const name = document.createElement("input");
    name.id = "llm-model-name";
    document.body.appendChild(name);

    const alias = document.createElement("input");
    alias.id = "llm-model-alias";
    document.body.appendChild(alias);

    const description = document.createElement("input");
    description.id = "llm-model-description";
    document.body.appendChild(description);

    const contextWindow = document.createElement("input");
    contextWindow.id = "llm-model-context-window";
    document.body.appendChild(contextWindow);

    const maxOutput = document.createElement("input");
    maxOutput.id = "llm-model-max-output";
    document.body.appendChild(maxOutput);

    const supportsChat = document.createElement("input");
    supportsChat.id = "llm-model-supports-chat";
    supportsChat.type = "checkbox";
    document.body.appendChild(supportsChat);

    const supportsStreaming = document.createElement("input");
    supportsStreaming.id = "llm-model-supports-streaming";
    supportsStreaming.type = "checkbox";
    document.body.appendChild(supportsStreaming);

    const supportsFunctions = document.createElement("input");
    supportsFunctions.id = "llm-model-supports-functions";
    supportsFunctions.type = "checkbox";
    document.body.appendChild(supportsFunctions);

    const supportsVision = document.createElement("input");
    supportsVision.id = "llm-model-supports-vision";
    supportsVision.type = "checkbox";
    document.body.appendChild(supportsVision);

    const enabled = document.createElement("input");
    enabled.id = "llm-model-enabled";
    enabled.type = "checkbox";
    document.body.appendChild(enabled);

    const deprecated = document.createElement("input");
    deprecated.id = "llm-model-deprecated";
    deprecated.type = "checkbox";
    document.body.appendChild(deprecated);

    const modalTitle = document.createElement("h2");
    modalTitle.id = "llm-model-modal-title";
    document.body.appendChild(modalTitle);

    await editLLMModel("model-1");

    expect(modelId.value).toBe("model-1");
    expect(name.value).toBe("GPT-4");
    expect(alias.value).toBe("gpt4");
    expect(description.value).toBe("Test model");
    expect(contextWindow.value).toBe("8192");
    expect(maxOutput.value).toBe("4096");
    expect(supportsChat.checked).toBe(true);
    expect(supportsStreaming.checked).toBe(true);
    expect(supportsFunctions.checked).toBe(true);
    expect(supportsVision.checked).toBe(false);
    expect(enabled.checked).toBe(true);
    expect(deprecated.checked).toBe(false);
    expect(modalTitle.textContent).toBe("Edit LLM Model");

    fetchSpy.mockRestore();
    consoleSpy.mockRestore();
  });

  test("handles fetch error", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
    });

    await editLLMModel("model-1");

    expect(showToast).toHaveBeenCalledWith("Failed to load model details", "error");

    fetchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// saveLLMModel
// ---------------------------------------------------------------------------
describe("saveLLMModel", () => {
  test("creates new model", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ id: "new-model" }),
    });

    const modelId = document.createElement("input");
    modelId.id = "llm-model-id";
    modelId.value = "";
    document.body.appendChild(modelId);

    const providerId = document.createElement("select");
    providerId.id = "llm-model-provider";
    providerId.value = "p1";
    document.body.appendChild(providerId);

    const modelIdInput = document.createElement("input");
    modelIdInput.id = "llm-model-model-id";
    modelIdInput.value = "gpt-4";
    document.body.appendChild(modelIdInput);

    const name = document.createElement("input");
    name.id = "llm-model-name";
    name.value = "GPT-4";
    document.body.appendChild(name);

    const alias = document.createElement("input");
    alias.id = "llm-model-alias";
    alias.value = "";
    document.body.appendChild(alias);

    const description = document.createElement("input");
    description.id = "llm-model-description";
    description.value = "";
    document.body.appendChild(description);

    const contextWindow = document.createElement("input");
    contextWindow.id = "llm-model-context-window";
    contextWindow.value = "8192";
    document.body.appendChild(contextWindow);

    const maxOutput = document.createElement("input");
    maxOutput.id = "llm-model-max-output";
    maxOutput.value = "";
    document.body.appendChild(maxOutput);

    const supportsChat = document.createElement("input");
    supportsChat.id = "llm-model-supports-chat";
    supportsChat.type = "checkbox";
    supportsChat.checked = true;
    document.body.appendChild(supportsChat);

    const supportsStreaming = document.createElement("input");
    supportsStreaming.id = "llm-model-supports-streaming";
    supportsStreaming.type = "checkbox";
    supportsStreaming.checked = false;
    document.body.appendChild(supportsStreaming);

    const supportsFunctions = document.createElement("input");
    supportsFunctions.id = "llm-model-supports-functions";
    supportsFunctions.type = "checkbox";
    supportsFunctions.checked = false;
    document.body.appendChild(supportsFunctions);

    const supportsVision = document.createElement("input");
    supportsVision.id = "llm-model-supports-vision";
    supportsVision.type = "checkbox";
    supportsVision.checked = false;
    document.body.appendChild(supportsVision);

    const enabled = document.createElement("input");
    enabled.id = "llm-model-enabled";
    enabled.type = "checkbox";
    enabled.checked = true;
    document.body.appendChild(enabled);

    const deprecated = document.createElement("input");
    deprecated.id = "llm-model-deprecated";
    deprecated.type = "checkbox";
    deprecated.checked = false;
    document.body.appendChild(deprecated);

    const modal = document.createElement("div");
    modal.id = "llm-model-modal";
    document.body.appendChild(modal);

    const container = document.createElement("div");
    container.id = "llm-models-container";
    document.body.appendChild(container);

    const event = { preventDefault: vi.fn() };
    await saveLLMModel(event);

    expect(event.preventDefault).toHaveBeenCalled();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/llm/models",
      expect.objectContaining({
        method: "POST",
      })
    );
    expect(showToast).toHaveBeenCalledWith("Model created successfully", "success");

    fetchSpy.mockRestore();
  });

  test("handles save error", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
    });

    const modelId = document.createElement("input");
    modelId.id = "llm-model-id";
    modelId.value = "";
    document.body.appendChild(modelId);

    const providerId = document.createElement("select");
    providerId.id = "llm-model-provider";
    document.body.appendChild(providerId);

    const modelIdInput = document.createElement("input");
    modelIdInput.id = "llm-model-model-id";
    document.body.appendChild(modelIdInput);

    const name = document.createElement("input");
    name.id = "llm-model-name";
    document.body.appendChild(name);

    const alias = document.createElement("input");
    alias.id = "llm-model-alias";
    document.body.appendChild(alias);

    const description = document.createElement("input");
    description.id = "llm-model-description";
    document.body.appendChild(description);

    const contextWindow = document.createElement("input");
    contextWindow.id = "llm-model-context-window";
    document.body.appendChild(contextWindow);

    const maxOutput = document.createElement("input");
    maxOutput.id = "llm-model-max-output";
    document.body.appendChild(maxOutput);

    const supportsChat = document.createElement("input");
    supportsChat.id = "llm-model-supports-chat";
    supportsChat.type = "checkbox";
    document.body.appendChild(supportsChat);

    const supportsStreaming = document.createElement("input");
    supportsStreaming.id = "llm-model-supports-streaming";
    supportsStreaming.type = "checkbox";
    document.body.appendChild(supportsStreaming);

    const supportsFunctions = document.createElement("input");
    supportsFunctions.id = "llm-model-supports-functions";
    supportsFunctions.type = "checkbox";
    document.body.appendChild(supportsFunctions);

    const supportsVision = document.createElement("input");
    supportsVision.id = "llm-model-supports-vision";
    supportsVision.type = "checkbox";
    document.body.appendChild(supportsVision);

    const enabled = document.createElement("input");
    enabled.id = "llm-model-enabled";
    enabled.type = "checkbox";
    document.body.appendChild(enabled);

    const deprecated = document.createElement("input");
    deprecated.id = "llm-model-deprecated";
    deprecated.type = "checkbox";
    document.body.appendChild(deprecated);

    const event = { preventDefault: vi.fn() };
    await saveLLMModel(event);

    expect(showToast).toHaveBeenCalledWith("Failed to save model", "error");

    fetchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// deleteLLMModel
// ---------------------------------------------------------------------------
describe("deleteLLMModel", () => {
  test("deletes model after confirmation", async () => {
    const confirmSpy = vi.spyOn(globalThis, "confirm").mockReturnValue(true);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
    });

    const container = document.createElement("div");
    container.id = "llm-models-container";
    document.body.appendChild(container);

    await deleteLLMModel("model-1", "GPT-4");

    expect(confirmSpy).toHaveBeenCalledWith(
      expect.stringContaining("GPT-4")
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/llm/models/model-1",
      expect.objectContaining({ method: "DELETE" })
    );
    expect(showToast).toHaveBeenCalledWith("Model deleted successfully", "success");

    confirmSpy.mockRestore();
    fetchSpy.mockRestore();
  });

  test("does not delete if user cancels", async () => {
    const confirmSpy = vi.spyOn(globalThis, "confirm").mockReturnValue(false);
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    await deleteLLMModel("model-1", "GPT-4");

    expect(confirmSpy).toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();

    confirmSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// toggleLLMModel
// ---------------------------------------------------------------------------
describe("toggleLLMModel", () => {
  test("toggles model state", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
    });

    const container = document.createElement("div");
    container.id = "llm-models-container";
    document.body.appendChild(container);

    await toggleLLMModel("model-1");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/llm/models/model-1/state",
      expect.objectContaining({ method: "POST" })
    );

    fetchSpy.mockRestore();
  });

  test("handles toggle error", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
    });

    await toggleLLMModel("model-1");

    expect(showToast).toHaveBeenCalledWith("Failed to toggle model", "error");

    fetchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// filterModelsByProvider
// ---------------------------------------------------------------------------
describe("filterModelsByProvider", () => {
  test("filters models by provider ID", () => {
    filterModelsByProvider("provider-1");

    expect(window.htmx.ajax).toHaveBeenCalledWith(
      "GET",
      "/admin/llm/models/html?provider_id=provider-1",
      expect.objectContaining({
        target: "#llm-models-container",
        swap: "innerHTML",
      })
    );
  });

  test("shows all models when no provider ID provided", () => {
    filterModelsByProvider("");

    expect(window.htmx.ajax).toHaveBeenCalledWith(
      "GET",
      "/admin/llm/models/html",
      expect.objectContaining({
        target: "#llm-models-container",
      })
    );
  });
});

// ---------------------------------------------------------------------------
// llmApiInfoApp
// ---------------------------------------------------------------------------
describe("llmApiInfoApp", () => {
  test("initializes with default values", () => {
    const app = llmApiInfoApp();

    expect(app.testType).toBe("models");
    expect(app.testModel).toBe("");
    expect(app.testing).toBe(false);
    expect(app.testResult).toBeNull();
  });

  test("formatDuration returns milliseconds for values under 1000", () => {
    const app = llmApiInfoApp();
    expect(app.formatDuration(500)).toBe("500ms");
  });

  test("formatDuration returns seconds for values over 1000", () => {
    const app = llmApiInfoApp();
    expect(app.formatDuration(1500)).toBe("1.50s");
  });

  test("formatBytes handles various sizes", () => {
    const app = llmApiInfoApp();
    expect(app.formatBytes(0)).toBe("0 B");
    expect(app.formatBytes(500)).toBe("500 B");
    expect(app.formatBytes(1024)).toBe("1.00 KB");
    expect(app.formatBytes(1024 * 1024)).toBe("1.00 MB");
  });

  test("runTest handles models test", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      json: () =>
        Promise.resolve({
          success: true,
          metrics: { modelCount: 5 },
          data: { data: [{ id: "gpt-4" }] },
        }),
    });

    const app = llmApiInfoApp();
    await app.runTest();

    expect(app.testSuccess).toBe(true);
    expect(app.testMetrics.modelCount).toBe(5);
    expect(app.testing).toBe(false);

    fetchSpy.mockRestore();
  });

  test("runTest validates model selection for chat test", async () => {
    const app = llmApiInfoApp();
    app.testType = "chat";
    app.testModel = "";

    await app.runTest();

    expect(app.testSuccess).toBe(false);
    expect(app.testMetrics.httpStatus).toBe(400);
  });

  test("runTest handles errors gracefully", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockRejectedValue(new Error("Network error"));

    const app = llmApiInfoApp();
    await app.runTest();

    expect(app.testSuccess).toBe(false);
    expect(app.testMetrics.httpStatus).toBe(0);
    expect(app.testing).toBe(false);

    fetchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// overviewDashboard
// ---------------------------------------------------------------------------
describe("overviewDashboard", () => {
  test("initializes and updates SVG colors", () => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.id = "overview-architecture";

    const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
    marker.id = "arrowhead";
    const polygon = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
    marker.appendChild(polygon);
    svg.appendChild(marker);

    document.body.appendChild(svg);

    const dashboard = overviewDashboard();
    dashboard.init();

    expect(polygon.getAttribute("class")).toBeTruthy();
  });

  test("handles missing SVG element", () => {
    const dashboard = overviewDashboard();
    expect(() => dashboard.updateSvgColors()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// debouncedServerSideUserSearch / serverSideUserSearch
// ---------------------------------------------------------------------------
describe("debouncedServerSideUserSearch", () => {
  test("debounces search calls", async () => {
    vi.useFakeTimers();

    const membersContainer = document.createElement("div");
    membersContainer.id = "team-members-container-team1";
    document.body.appendChild(membersContainer);

    const nonMembersContainer = document.createElement("div");
    nonMembersContainer.id = "team-non-members-container-team1";
    document.body.appendChild(nonMembersContainer);

    debouncedServerSideUserSearch("team1", "test", 300);
    debouncedServerSideUserSearch("team1", "test2", 300);

    // Only the last call should be executed after debounce
    vi.advanceTimersByTime(300);

    vi.useRealTimers();
  });
});

describe("serverSideUserSearch", () => {
  test("reloads both sections when search is empty", async () => {
    fetchWithAuth.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("<div>Members</div>"),
    });
    fetchWithAuth.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("<div>Non-members</div>"),
    });

    const membersContainer = document.createElement("div");
    membersContainer.id = "team-members-container-team1";
    membersContainer.dataset.perPage = "20";
    document.body.appendChild(membersContainer);

    const nonMembersContainer = document.createElement("div");
    nonMembersContainer.id = "team-non-members-container-team1";
    nonMembersContainer.dataset.perPage = "20";
    document.body.appendChild(nonMembersContainer);

    await serverSideUserSearch("team1", "");

    expect(fetchWithAuth).toHaveBeenCalledTimes(2);
    expect(membersContainer.innerHTML).toContain("Members");
    expect(nonMembersContainer.innerHTML).toContain("Non-members");
  });

  test("searches users and splits into members/non-members", async () => {
    // Mock member data fetch
    fetchWithAuth.mockResolvedValueOnce({
      ok: true,
      text: () =>
        Promise.resolve(
          '<div class="user-item" data-user-email="member@test.com"><select class="role-select"><option value="member" selected>Member</option></select></div>'
        ),
    });

    // Mock user search
    fetchWithAuth.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          users: [
            { email: "member@test.com", full_name: "Member User" },
            { email: "nonmember@test.com", full_name: "Non-Member User" },
          ],
        }),
    });

    const membersContainer = document.createElement("div");
    membersContainer.id = "team-members-container-team1";
    membersContainer.dataset.perPage = "20";
    document.body.appendChild(membersContainer);

    const nonMembersContainer = document.createElement("div");
    nonMembersContainer.id = "team-non-members-container-team1";
    nonMembersContainer.dataset.perPage = "20";
    document.body.appendChild(nonMembersContainer);

    await serverSideUserSearch("team1", "test");

    expect(membersContainer.innerHTML).toContain("member@test.com");
    expect(nonMembersContainer.innerHTML).toContain("nonmember@test.com");
  });

  test("handles search error", async () => {
    fetchWithAuth.mockRejectedValue(new Error("Search failed"));

    const membersContainer = document.createElement("div");
    membersContainer.id = "team-members-container-team1";
    document.body.appendChild(membersContainer);

    const nonMembersContainer = document.createElement("div");
    nonMembersContainer.id = "team-non-members-container-team1";
    document.body.appendChild(nonMembersContainer);

    await serverSideUserSearch("team1", "test");

    expect(membersContainer.innerHTML).toContain("Error searching users");
  });

  test("handles missing containers", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await serverSideUserSearch("team1", "test");

    expect(consoleSpy).toHaveBeenCalledWith("Team containers not found");

    consoleSpy.mockRestore();
  });
});
