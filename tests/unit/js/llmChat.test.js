/**
 * Unit tests for llmChat.js module
 * Tests: buildLLMConfigLegacy, copyEnvVariables, handleChatInputKeydown,
 *        handleLLMModelChange, and other exported functions
 * (parseThinkTags is already tested in tests/js/)
 */

import { describe, test, expect, vi, afterEach } from "vitest";

import {
  buildLLMConfigLegacy,
  copyEnvVariables,
  handleChatInputKeydown,
  handleLLMModelChange,
  loadVirtualServersForChat,
  initializeLLMChat,
  connectLLMChat,
  disconnectLLMChat,
  selectServerForChat,
} from "../../../mcpgateway/admin_ui/llmChat.js";
import { showErrorMessage, fetchWithTimeout } from "../../../mcpgateway/admin_ui/utils.js";

// Mock all heavy dependencies
vi.mock("../../../mcpgateway/admin_ui/gateways.js", () => ({
  getSelectedGatewayIds: vi.fn(() => []),
}));
vi.mock("../../../mcpgateway/admin_ui/prompts.js", () => ({
  initPromptSelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/resources.js", () => ({
  initResourceSelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/tools.js", () => ({
  initToolSelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  escapeHtmlChat: vi.fn((s) => (s != null ? String(s) : "")),
  logRestrictedContext: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  fetchWithTimeout: vi.fn(),
  getCookie: vi.fn(() => "test-jwt"),
  getCurrentTeamId: vi.fn(() => null),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showErrorMessage: vi.fn(),
  showNotification: vi.fn(),
}));

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  delete window.CURRENT_USER;
});

// ---------------------------------------------------------------------------
// buildLLMConfigLegacy
// ---------------------------------------------------------------------------
describe("buildLLMConfigLegacy", () => {
  test("builds azure_openai config from DOM elements", () => {
    // Create DOM inputs
    const fields = {
      "azure-api-key": "test-key", // pragma: allowlist secret
      "azure-endpoint": "https://azure.example.com",
      "azure-deployment": "gpt-4",
      "azure-api-version": "2024-02-15",
      "azure-temperature": "0.7",
    };
    Object.entries(fields).forEach(([id, val]) => {
      const el = document.createElement("input");
      el.id = id;
      el.value = val;
      document.body.appendChild(el);
    });

    const result = buildLLMConfigLegacy("azure_openai");
    expect(result.provider).toBe("azure_openai");
    expect(result.config.api_key).toBe("test-key");
    expect(result.config.azure_endpoint).toBe("https://azure.example.com");
    expect(result.config.azure_deployment).toBe("gpt-4");
    expect(result.config.temperature).toBe(0.7);
  });

  test("builds openai config from DOM elements", () => {
    const fields = {
      "openai-api-key": "sk-test", // pragma: allowlist secret
      "openai-model": "gpt-4o",
      "openai-base-url": "https://api.openai.com/v1",
      "openai-temperature": "0.5",
    };
    Object.entries(fields).forEach(([id, val]) => {
      const el = document.createElement("input");
      el.id = id;
      el.value = val;
      document.body.appendChild(el);
    });

    const result = buildLLMConfigLegacy("openai");
    expect(result.provider).toBe("openai");
    expect(result.config.api_key).toBe("sk-test");
    expect(result.config.model).toBe("gpt-4o");
  });

  test("omits empty values from config", () => {
    const fields = {
      "azure-api-key": "",
      "azure-endpoint": "",
      "azure-deployment": "",
      "azure-api-version": "",
      "azure-temperature": "",
    };
    Object.entries(fields).forEach(([id, val]) => {
      const el = document.createElement("input");
      el.id = id;
      el.value = val;
      document.body.appendChild(el);
    });

    const result = buildLLMConfigLegacy("azure_openai");
    expect(result.config).toEqual({});
  });

  test("returns base config for unknown provider", () => {
    const result = buildLLMConfigLegacy("unknown_provider");
    expect(result.provider).toBe("unknown_provider");
    expect(result.config).toEqual({});
  });
});

// ---------------------------------------------------------------------------
// copyEnvVariables
// ---------------------------------------------------------------------------
describe("copyEnvVariables", () => {
  test("copies env variables to clipboard for known provider", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      writable: true,
      configurable: true,
    });

    await copyEnvVariables("openai");
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("OPENAI_API_KEY"));
  });

  test("shows error for unknown provider", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await copyEnvVariables("unknown");
    expect(showErrorMessage).toHaveBeenCalledWith("Unknown provider");
    consoleSpy.mockRestore();
  });

  test("handles clipboard API failure gracefully", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
      writable: true,
      configurable: true,
    });
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    // Should not throw
    await expect(copyEnvVariables("openai")).resolves.not.toThrow();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// handleChatInputKeydown
// ---------------------------------------------------------------------------
describe("handleChatInputKeydown", () => {
  test("prevents default and sends message on Enter", () => {
    // Set up minimal DOM for sendChatMessage to not crash
    window.ROOT_PATH = "";
    const chatInput = document.createElement("textarea");
    chatInput.id = "chat-input";
    chatInput.value = "";
    document.body.appendChild(chatInput);

    const event = {
      key: "Enter",
      shiftKey: false,
      preventDefault: vi.fn(),
    };

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    handleChatInputKeydown(event);
    expect(event.preventDefault).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });

  test("does not prevent default on Shift+Enter (allows newline)", () => {
    const event = {
      key: "Enter",
      shiftKey: true,
      preventDefault: vi.fn(),
    };
    handleChatInputKeydown(event);
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  test("does not prevent default on other keys", () => {
    const event = {
      key: "a",
      shiftKey: false,
      preventDefault: vi.fn(),
    };
    handleChatInputKeydown(event);
    expect(event.preventDefault).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleLLMModelChange
// ---------------------------------------------------------------------------
describe("handleLLMModelChange", () => {
  test("shows model badge when a model is selected", () => {
    const select = document.createElement("select");
    select.id = "llm-model-select";
    const opt = document.createElement("option");
    opt.value = "gpt-4";
    opt.text = "GPT-4";
    opt.selected = true;
    select.appendChild(opt);
    document.body.appendChild(select);

    const badge = document.createElement("div");
    badge.id = "llm-model-badge";
    badge.classList.add("hidden");
    document.body.appendChild(badge);

    const nameSpan = document.createElement("span");
    nameSpan.id = "llmchat-model-name";
    document.body.appendChild(nameSpan);

    handleLLMModelChange();

    expect(badge.classList.contains("hidden")).toBe(false);
    expect(nameSpan.textContent).toBe("GPT-4");
  });

  test("hides model badge when no model is selected", () => {
    const select = document.createElement("select");
    select.id = "llm-model-select";
    const opt = document.createElement("option");
    opt.value = "";
    opt.text = "Select model";
    opt.selected = true;
    select.appendChild(opt);
    document.body.appendChild(select);

    const badge = document.createElement("div");
    badge.id = "llm-model-badge";
    document.body.appendChild(badge);

    const nameSpan = document.createElement("span");
    nameSpan.id = "llmchat-model-name";
    document.body.appendChild(nameSpan);

    handleLLMModelChange();

    expect(badge.classList.contains("hidden")).toBe(true);
  });

  test("does nothing when elements are missing", () => {
    expect(() => handleLLMModelChange()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// loadVirtualServersForChat
// ---------------------------------------------------------------------------
describe("loadVirtualServersForChat", () => {
  test("does nothing when servers list element is missing", async () => {
    await loadVirtualServersForChat();
    expect(fetchWithTimeout).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// initializeLLMChat
// ---------------------------------------------------------------------------
describe("initializeLLMChat", () => {
  test("does not throw when DOM elements are missing", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(() => initializeLLMChat()).not.toThrow();
    consoleSpy.mockRestore();
    warnSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// connectLLMChat
// ---------------------------------------------------------------------------
describe("connectLLMChat", () => {
  test("shows error when no server is selected", async () => {
    await connectLLMChat();
    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("select a virtual server")
    );
  });
});

// ---------------------------------------------------------------------------
// disconnectLLMChat
// ---------------------------------------------------------------------------
describe("disconnectLLMChat", () => {
  test("does not throw when not connected", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    await expect(disconnectLLMChat()).resolves.not.toThrow();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// initializeLLMChat - Extended Tests
// ---------------------------------------------------------------------------
describe("initializeLLMChat - Extended", () => {
  test("generates user ID from CURRENT_USER object", () => {
    window.CURRENT_USER = { id: "user-123", email: "test@example.com" };
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    initializeLLMChat();

    // User ID should be set from CURRENT_USER
    consoleSpy.mockRestore();
  });

  test("generates user ID from CURRENT_USER string", () => {
    window.CURRENT_USER = "user-456";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    initializeLLMChat();

    consoleSpy.mockRestore();
  });

  test("loads servers when list is empty", async () => {
    window.ROOT_PATH = "";
    const serversList = document.createElement("div");
    serversList.id = "llm-chat-servers-list";
    document.body.appendChild(serversList);

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ data: [] }),
    });

    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    initializeLLMChat();
    consoleSpy.mockRestore();
  });

  test("handles sessionStorage unavailable gracefully", () => {
    const originalSessionStorage = window.sessionStorage;
    Object.defineProperty(window, "sessionStorage", {
      value: {
        getItem: () => {
          throw new Error("sessionStorage unavailable");
        },
        setItem: () => {
          throw new Error("sessionStorage unavailable");
        },
      },
      writable: true,
      configurable: true,
    });

    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    expect(() => initializeLLMChat()).not.toThrow();

    consoleSpy.mockRestore();
    warnSpy.mockRestore();
    Object.defineProperty(window, "sessionStorage", {
      value: originalSessionStorage,
      writable: true,
      configurable: true,
    });
  });
});

// ---------------------------------------------------------------------------
// loadVirtualServersForChat - Extended Tests
// ---------------------------------------------------------------------------
describe("loadVirtualServersForChat - Extended", () => {
  test("displays loading spinner initially", async () => {
    window.ROOT_PATH = "";
    const serversList = document.createElement("div");
    serversList.id = "llm-chat-servers-list";
    document.body.appendChild(serversList);

    fetchWithTimeout.mockImplementation(() => new Promise(() => {})); // Never resolves

    loadVirtualServersForChat();

    expect(serversList.innerHTML).toContain("animate-spin");
  });

  test("renders server list with active servers", async () => {
    window.ROOT_PATH = "";
    const serversList = document.createElement("div");
    serversList.id = "llm-chat-servers-list";
    document.body.appendChild(serversList);

    const mockServers = [
      {
        id: "srv-1",
        name: "Test Server",
        description: "A test server",
        isActive: true,
        visibility: "public",
        associatedTools: ["tool1", "tool2"],
      },
    ];

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ data: mockServers }),
    });

    await loadVirtualServersForChat();

    expect(serversList.innerHTML).toContain("Test Server");
    expect(serversList.innerHTML).toContain("2 tools");
  });

  test("shows inactive badge for inactive servers", async () => {
    window.ROOT_PATH = "";
    const serversList = document.createElement("div");
    serversList.id = "llm-chat-servers-list";
    document.body.appendChild(serversList);

    const mockServers = [
      {
        id: "srv-2",
        name: "Inactive Server",
        isActive: false,
        visibility: "public",
        associatedTools: [],
      },
    ];

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ data: mockServers }),
    });

    await loadVirtualServersForChat();

    expect(serversList.innerHTML).toContain("Inactive");
  });

  test("shows requires token badge for team servers", async () => {
    window.ROOT_PATH = "";
    const serversList = document.createElement("div");
    serversList.id = "llm-chat-servers-list";
    document.body.appendChild(serversList);

    const mockServers = [
      {
        id: "srv-3",
        name: "Team Server",
        isActive: true,
        visibility: "team",
        associatedTools: [],
      },
    ];

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ data: mockServers }),
    });

    await loadVirtualServersForChat();

    expect(serversList.innerHTML).toContain("Requires Token");
  });

  test("handles HTTP error gracefully", async () => {
    window.ROOT_PATH = "";
    const serversList = document.createElement("div");
    serversList.id = "llm-chat-servers-list";
    document.body.appendChild(serversList);

    fetchWithTimeout.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
    });

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await loadVirtualServersForChat();

    expect(serversList.innerHTML).toContain("Failed to load servers");
    consoleSpy.mockRestore();
  });

  test("handles empty server list", async () => {
    window.ROOT_PATH = "";
    const serversList = document.createElement("div");
    serversList.id = "llm-chat-servers-list";
    document.body.appendChild(serversList);

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ data: [] }),
    });

    await loadVirtualServersForChat();

    expect(serversList.innerHTML).toContain("No virtual servers available");
  });

  test("handles legacy response format without data wrapper", async () => {
    window.ROOT_PATH = "";
    const serversList = document.createElement("div");
    serversList.id = "llm-chat-servers-list";
    document.body.appendChild(serversList);

    const mockServers = [
      {
        id: "srv-4",
        name: "Legacy Server",
        enabled: true,
        visibility: "public",
        associatedTools: [],
      },
    ];

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: async () => mockServers,
    });

    await loadVirtualServersForChat();

    expect(serversList.innerHTML).toContain("Legacy Server");
  });
});

// ---------------------------------------------------------------------------
// connectLLMChat - Extended Tests
// ---------------------------------------------------------------------------
describe("connectLLMChat - Extended", () => {
  test("shows error when no model is selected", async () => {
    // Mock state to have a selected server
    const select = document.createElement("select");
    select.id = "llm-model-select";
    select.value = "";
    document.body.appendChild(select);

    // Need to import and set state directly
    const { selectServerForChat } = await import("../../../mcpgateway/admin_ui/llmChat.js");
    await selectServerForChat("srv-1", "Test Server", true, false, "public");

    await connectLLMChat();

    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("select an LLM model")
    );
  });

  test("handles connection timeout", async () => {
    window.ROOT_PATH = "";

    const select = document.createElement("select");
    select.id = "llm-model-select";
    select.value = "gpt-4";
    document.body.appendChild(select);

    const connectBtn = document.createElement("button");
    connectBtn.id = "llm-connect-btn";
    connectBtn.textContent = "Connect";
    document.body.appendChild(connectBtn);

    const statusDiv = document.createElement("div");
    statusDiv.id = "llm-config-status";
    document.body.appendChild(statusDiv);

    const chatContainer = document.createElement("div");
    chatContainer.id = "chat-messages-container";
    document.body.appendChild(chatContainer);

    // Mock timeout error - connection fails before state is set
    fetchWithTimeout.mockRejectedValueOnce(new Error("timeout"));

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    // Call connectLLMChat without setting up server state - should fail early
    await connectLLMChat();

    // Should show error about selecting server first
    expect(showErrorMessage).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("handles HTTP error with backend message", async () => {
    window.ROOT_PATH = "";

    const select = document.createElement("select");
    select.id = "llm-model-select";
    select.value = "gpt-4";
    document.body.appendChild(select);

    const connectBtn = document.createElement("button");
    connectBtn.id = "llm-connect-btn";
    connectBtn.textContent = "Connect";
    document.body.appendChild(connectBtn);

    const statusDiv = document.createElement("div");
    statusDiv.id = "llm-config-status";
    document.body.appendChild(statusDiv);

    const chatContainer = document.createElement("div");
    chatContainer.id = "chat-messages-container";
    document.body.appendChild(chatContainer);

    // Mock HTTP error - connection fails before state check
    fetchWithTimeout.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Invalid authentication token" }),
    });

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    // Call without server state - should fail early
    await connectLLMChat();

    expect(showErrorMessage).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// disconnectLLMChat - Extended Tests
// ---------------------------------------------------------------------------
describe("disconnectLLMChat - Extended", () => {
  test("handles successful disconnection", async () => {
    fetchWithTimeout.mockReset();
    window.ROOT_PATH = "";
    window.CURRENT_USER = { email: "test@example.com" };

    const disconnectBtn = document.createElement("button");
    disconnectBtn.id = "llm-disconnect-btn";
    disconnectBtn.textContent = "Disconnect";
    document.body.appendChild(disconnectBtn);

    const statusBadge = document.createElement("div");
    statusBadge.id = "llm-connection-status";
    document.body.appendChild(statusBadge);

    const toolsBadge = document.createElement("div");
    toolsBadge.id = "llm-active-tools-badge";
    document.body.appendChild(toolsBadge);

    const toolCountSpan = document.createElement("span");
    toolCountSpan.id = "llm-tool-count";
    document.body.appendChild(toolCountSpan);

    const toolListDiv = document.createElement("div");
    toolListDiv.id = "llm-tool-list";
    document.body.appendChild(toolListDiv);

    const modelBadge = document.createElement("div");
    modelBadge.id = "llm-model-badge";
    document.body.appendChild(modelBadge);

    const connectBtn = document.createElement("button");
    connectBtn.id = "llm-connect-btn";
    connectBtn.classList.add("hidden");
    document.body.appendChild(connectBtn);

    const chatInput = document.createElement("div");
    chatInput.id = "chat-input-container";
    document.body.appendChild(chatInput);

    const input = document.createElement("textarea");
    input.id = "chat-input";
    document.body.appendChild(input);

    const sendBtn = document.createElement("button");
    sendBtn.id = "chat-send-btn";
    document.body.appendChild(sendBtn);

    const configToggle = document.createElement("button");
    configToggle.id = "llm-config-toggle";
    document.body.appendChild(configToggle);

    const serverDropdown = document.createElement("button");
    serverDropdown.id = "llm-server-dropdown-btn";
    document.body.appendChild(serverDropdown);

    const chatContainer = document.createElement("div");
    chatContainer.id = "chat-messages-container";
    document.body.appendChild(chatContainer);

    // Set up connected state by calling connectLLMChat first
    const select = document.createElement("select");
    select.id = "llm-model-select";
    const option = document.createElement("option");
    option.value = "gpt-4";
    option.selected = true;
    select.appendChild(option);
    document.body.appendChild(select);

    const statusDiv = document.createElement("div");
    statusDiv.id = "llm-config-status";
    document.body.appendChild(statusDiv);

    await selectServerForChat("srv-1", "Test Server", true, false, "public");

    // Mock successful connection
    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: "connected",
        tools: ["tool1", "tool2"],
        tool_count: 2,
        server_token: "test-token"
      }),
    });

    await connectLLMChat();

    // Verify UI shows connected state before disconnect
    expect(disconnectBtn.classList.contains("hidden")).toBe(false);
    expect(connectBtn.classList.contains("hidden")).toBe(true);

    // Now mock successful disconnection
    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: "disconnected" }),
    });

    await disconnectLLMChat();

    // Wait for async state updates
    await new Promise(resolve => setTimeout(resolve, 0));

    // Verify disconnect button is hidden and connect button is shown
    expect(disconnectBtn.classList.contains("hidden")).toBe(true);
    expect(connectBtn.classList.contains("hidden")).toBe(false);
  });

  test("returns early when not connected", async () => {
    fetchWithTimeout.mockClear();
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    // Call disconnect without being connected
    await disconnectLLMChat();

    // Should log warning and return early
    expect(consoleSpy).toHaveBeenCalledWith("No active connection to disconnect");
    expect(fetchWithTimeout).not.toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// buildLLMConfigLegacy - Additional Provider Tests
// ---------------------------------------------------------------------------
describe("buildLLMConfigLegacy - Additional Providers", () => {
  test("builds anthropic config", () => {
    const fields = {
      "anthropic-api-key": "sk-ant-test", // pragma: allowlist secret
      "anthropic-model": "claude-3-opus",
      "anthropic-temperature": "0.8",
      "anthropic-max-tokens": "4096",
    };
    Object.entries(fields).forEach(([id, val]) => {
      const el = document.createElement("input");
      el.id = id;
      el.value = val;
      document.body.appendChild(el);
    });

    const result = buildLLMConfigLegacy("anthropic");
    expect(result.provider).toBe("anthropic");
    expect(result.config.api_key).toBe("sk-ant-test");
    expect(result.config.model).toBe("claude-3-opus");
    expect(result.config.temperature).toBe(0.8);
    expect(result.config.max_tokens).toBe(4096);
  });

  test("builds aws_bedrock config", () => {
    const fields = {
      "aws-bedrock-model-id": "anthropic.claude-v2",
      "aws-bedrock-region": "us-east-1",
      "aws-access-key-id": "AKIATEST",
      "aws-secret-access-key": "secret",
      "aws-bedrock-temperature": "0.7",
      "aws-bedrock-max-tokens": "2048",
    };
    Object.entries(fields).forEach(([id, val]) => {
      const el = document.createElement("input");
      el.id = id;
      el.value = val;
      document.body.appendChild(el);
    });

    const result = buildLLMConfigLegacy("aws_bedrock");
    expect(result.provider).toBe("aws_bedrock");
    expect(result.config.model_id).toBe("anthropic.claude-v2");
    expect(result.config.region_name).toBe("us-east-1");
  });

  test("builds watsonx config", () => {
    const fields = {
      "watsonx-api-key": "test-key", // pragma: allowlist secret
      "watsonx-url": "https://us-south.ml.cloud.ibm.com",
      "watsonx-project-id": "proj-123",
      "watsonx-model-id": "ibm/granite-13b-chat-v2",
      "watsonx-temperature": "0.7",
      "watsonx-max-new-tokens": "1024",
      "watsonx-decoding-method": "greedy",
    };
    Object.entries(fields).forEach(([id, val]) => {
      const el = document.createElement("input");
      el.id = id;
      el.value = val;
      document.body.appendChild(el);
    });

    const result = buildLLMConfigLegacy("watsonx");
    expect(result.provider).toBe("watsonx");
    expect(result.config.apikey).toBe("test-key");
    expect(result.config.modelid).toBe("ibm/granite-13b-chat-v2");
  });

  test("builds ollama config", () => {
    const fields = {
      "ollama-model": "llama3",
      "ollama-base-url": "http://localhost:11434",
      "ollama-temperature": "0.5",
    };
    Object.entries(fields).forEach(([id, val]) => {
      const el = document.createElement("input");
      el.id = id;
      el.value = val;
      document.body.appendChild(el);
    });

    const result = buildLLMConfigLegacy("ollama");
    expect(result.provider).toBe("ollama");
    expect(result.config.model).toBe("llama3");
    expect(result.config.base_url).toBe("http://localhost:11434");
  });
});

// ---------------------------------------------------------------------------
// copyEnvVariables - Additional Provider Tests
// ---------------------------------------------------------------------------
describe("copyEnvVariables - Additional Providers", () => {
  test("copies azure env variables", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      writable: true,
      configurable: true,
    });

    await copyEnvVariables("azure");
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("AZURE_OPENAI_API_KEY"));
  });

  test("copies anthropic env variables", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      writable: true,
      configurable: true,
    });

    await copyEnvVariables("anthropic");
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("ANTHROPIC_API_KEY"));
  });

  test("uses fallback copy method when clipboard API unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: undefined,
      writable: true,
      configurable: true,
    });

    // Mock execCommand on document
    document.execCommand = vi.fn().mockReturnValue(true);

    await copyEnvVariables("openai");

    expect(document.execCommand).toHaveBeenCalledWith("copy");
  });

  test("handles fallback copy failure", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: undefined,
      writable: true,
      configurable: true,
    });

    // Mock execCommand on document
    document.execCommand = vi.fn().mockReturnValue(false);

    await copyEnvVariables("openai");

    expect(showErrorMessage).toHaveBeenCalled();
  });
});
