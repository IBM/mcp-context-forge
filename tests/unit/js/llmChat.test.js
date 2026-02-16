/**
 * Unit tests for llmChat.js module
 * Tests: buildLLMConfigLegacy, copyEnvVariables, handleChatInputKeydown,
 *        handleLLMModelChange, and other exported functions
 * (parseThinkTags is already tested in tests/js/)
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import {
  buildLLMConfigLegacy,
  copyEnvVariables,
  handleChatInputKeydown,
  handleLLMModelChange,
  loadVirtualServersForChat,
  sendChatMessage,
  initializeLLMChat,
  connectLLMChat,
  disconnectLLMChat,
  serverSideToolSearch,
  serverSidePromptSearch,
  serverSideResourceSearch,
} from "../../../mcpgateway/admin_ui/llmChat.js";
import { showErrorMessage, fetchWithTimeout } from "../../../mcpgateway/admin_ui/utils.js";

// Mock all heavy dependencies
vi.mock("../../../mcpgateway/admin_ui/gateway.js", () => ({
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
      "azure-api-key": "test-key",
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
      "openai-api-key": "sk-test",
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
// serverSideToolSearch
// ---------------------------------------------------------------------------
describe("serverSideToolSearch", () => {
  test("does nothing when container is missing", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await serverSideToolSearch("test");
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("not found")
    );
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// serverSidePromptSearch
// ---------------------------------------------------------------------------
describe("serverSidePromptSearch", () => {
  test("does nothing when container is missing", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await serverSidePromptSearch("test");
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("not found")
    );
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// serverSideResourceSearch
// ---------------------------------------------------------------------------
describe("serverSideResourceSearch", () => {
  test("does nothing when container is missing", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await serverSideResourceSearch("test");
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("not found")
    );
    consoleSpy.mockRestore();
  });
});
