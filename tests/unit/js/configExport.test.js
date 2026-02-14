/**
 * Unit tests for configExport.js module
 * Tests: generateAndShowConfig, exportServerConfig, showConfigDisplayModal,
 *        copyConfigToClipboard, downloadConfig, goBackToSelection
 *
 * Note: showConfigSelectionModal, getCatalogUrl, and generateConfig are already
 * tested in tests/js/ integration tests
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

// Mock dependencies BEFORE importing the module under test
vi.mock("../../../mcpgateway/admin_ui/modals.js", () => ({
  openModal: vi.fn(),
  closeModal: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  fetchWithTimeout: vi.fn(),
  handleFetchError: vi.fn((error, context) => `Error ${context}: ${error.message}`),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showErrorMessage: vi.fn(),
  showSuccessMessage: vi.fn(),
}));

import {
  generateAndShowConfig,
  exportServerConfig,
  showConfigDisplayModal,
  copyConfigToClipboard,
  downloadConfig,
  goBackToSelection,
  generateConfig,
} from "../../../mcpgateway/admin_ui/configExport.js";
import { openModal, closeModal } from "../../../mcpgateway/admin_ui/modals.js";
import {
  fetchWithTimeout,
  handleFetchError,
  showErrorMessage,
  showSuccessMessage,
} from "../../../mcpgateway/admin_ui/utils.js";

beforeEach(() => {
  // Mock navigator.clipboard for all tests
  Object.defineProperty(navigator, "clipboard", {
    value: {
      writeText: vi.fn(),
    },
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.clearAllMocks();
  delete window.ROOT_PATH;
});

// ---------------------------------------------------------------------------
// generateAndShowConfig
// ---------------------------------------------------------------------------
describe("generateAndShowConfig", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  test("fetches server details and generates stdio config", async () => {
    const mockServer = {
      id: "server-123",
      name: "Test Server",
    };

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: async () => mockServer,
    });

    // We need to call showConfigSelectionModal first to set currentServerId
    const { showConfigSelectionModal } = await import("../../../mcpgateway/admin_ui/configExport.js");
    showConfigSelectionModal("server-123", "Test Server");

    await generateAndShowConfig("stdio");

    expect(fetchWithTimeout).toHaveBeenCalledWith("/admin/servers/server-123");
    expect(closeModal).toHaveBeenCalledWith("config-selection-modal");
    expect(openModal).toHaveBeenCalledWith("config-display-modal");
  });

  test("fetches server details and generates sse config", async () => {
    const mockServer = {
      id: "server-456",
      name: "SSE Server",
    };

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: async () => mockServer,
    });

    const { showConfigSelectionModal } = await import("../../../mcpgateway/admin_ui/configExport.js");
    showConfigSelectionModal("server-456", "SSE Server");

    await generateAndShowConfig("sse");

    expect(fetchWithTimeout).toHaveBeenCalledWith("/admin/servers/server-456");
    expect(closeModal).toHaveBeenCalledWith("config-selection-modal");
    expect(openModal).toHaveBeenCalledWith("config-display-modal");
  });

  test("fetches server details and generates http config", async () => {
    const mockServer = {
      id: "server-789",
      name: "HTTP Server",
    };

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: async () => mockServer,
    });

    const { showConfigSelectionModal } = await import("../../../mcpgateway/admin_ui/configExport.js");
    showConfigSelectionModal("server-789", "HTTP Server");

    await generateAndShowConfig("http");

    expect(fetchWithTimeout).toHaveBeenCalledWith("/admin/servers/server-789");
    expect(closeModal).toHaveBeenCalledWith("config-selection-modal");
    expect(openModal).toHaveBeenCalledWith("config-display-modal");
  });

  test("handles fetch error gracefully", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
    });

    const { showConfigSelectionModal } = await import("../../../mcpgateway/admin_ui/configExport.js");
    showConfigSelectionModal("server-404", "Missing Server");

    await generateAndShowConfig("stdio");

    expect(handleFetchError).toHaveBeenCalled();
    expect(showErrorMessage).toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  test("handles network error gracefully", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    fetchWithTimeout.mockRejectedValue(new Error("Network failure"));

    const { showConfigSelectionModal } = await import("../../../mcpgateway/admin_ui/configExport.js");
    showConfigSelectionModal("server-net", "Network Server");

    await generateAndShowConfig("sse");

    expect(handleFetchError).toHaveBeenCalledWith(
      expect.any(Error),
      "generate configuration"
    );
    expect(showErrorMessage).toHaveBeenCalled();
    errorSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// exportServerConfig
// ---------------------------------------------------------------------------
describe("exportServerConfig", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  test("fetches server and displays config modal", async () => {
    const mockServer = {
      id: "export-123",
      name: "Export Server",
    };

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: async () => mockServer,
    });

    await exportServerConfig("export-123", "stdio");

    expect(fetchWithTimeout).toHaveBeenCalledWith("/admin/servers/export-123");
    expect(openModal).toHaveBeenCalledWith("config-display-modal");
  });

  test("generates correct config type when exporting", async () => {
    const mockServer = {
      id: "export-456",
      name: "SSE Export",
    };

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: async () => mockServer,
    });

    // Create description element to verify correct config type
    const descEl = document.createElement("div");
    descEl.id = "config-description";
    document.body.appendChild(descEl);

    const usageEl = document.createElement("div");
    usageEl.id = "config-usage";
    document.body.appendChild(usageEl);

    const contentEl = document.createElement("textarea");
    contentEl.id = "config-content";
    document.body.appendChild(contentEl);

    const titleEl = document.createElement("h2");
    titleEl.id = "config-display-title";
    document.body.appendChild(titleEl);

    await exportServerConfig("export-456", "sse");

    expect(descEl.textContent).toContain("SSE");
    expect(descEl.textContent).toContain("SSE Export");
  });

  test("handles HTTP error response", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
    });

    await exportServerConfig("error-server", "http");

    expect(handleFetchError).toHaveBeenCalled();
    expect(showErrorMessage).toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  test("handles exception during export", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    fetchWithTimeout.mockRejectedValue(new Error("Timeout"));

    await exportServerConfig("timeout-server", "stdio");

    expect(handleFetchError).toHaveBeenCalledWith(
      expect.any(Error),
      "generate configuration"
    );
    expect(showErrorMessage).toHaveBeenCalled();
    errorSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// showConfigDisplayModal
// ---------------------------------------------------------------------------
describe("showConfigDisplayModal", () => {
  beforeEach(() => {
    // Create all required DOM elements
    const descEl = document.createElement("div");
    descEl.id = "config-description";
    document.body.appendChild(descEl);

    const usageEl = document.createElement("div");
    usageEl.id = "config-usage";
    document.body.appendChild(usageEl);

    const contentEl = document.createElement("textarea");
    contentEl.id = "config-content";
    document.body.appendChild(contentEl);

    const titleEl = document.createElement("h2");
    titleEl.id = "config-display-title";
    document.body.appendChild(titleEl);
  });

  test("displays stdio configuration with correct description", () => {
    const server = { id: "s1", name: "Stdio Server" };
    const config = { mcpServers: { "mcpgateway-wrapper": {} } };

    showConfigDisplayModal(server, "stdio", config);

    const descEl = document.getElementById("config-description");
    expect(descEl.textContent).toContain("Claude Desktop");
    expect(descEl.textContent).toContain("Stdio Server");

    const usageEl = document.getElementById("config-usage");
    expect(usageEl.textContent).toContain(".mcp.json");

    const titleEl = document.getElementById("config-display-title");
    expect(titleEl.textContent).toContain("STDIO");
    expect(titleEl.textContent).toContain("Stdio Server");

    expect(openModal).toHaveBeenCalledWith("config-display-modal");
  });

  test("displays sse configuration with correct description", () => {
    const server = { id: "s2", name: "SSE Server" };
    const config = { servers: { "sse-server": { type: "sse" } } };

    showConfigDisplayModal(server, "sse", config);

    const descEl = document.getElementById("config-description");
    expect(descEl.textContent).toContain("LangChain");
    expect(descEl.textContent).toContain("SSE Server");

    const usageEl = document.getElementById("config-usage");
    expect(usageEl.textContent).toContain("Server-Sent Events");

    const titleEl = document.getElementById("config-display-title");
    expect(titleEl.textContent).toContain("SSE");
  });

  test("displays http configuration with correct description", () => {
    const server = { id: "s3", name: "HTTP Server" };
    const config = { servers: { "http-server": { type: "streamable-http" } } };

    showConfigDisplayModal(server, "http", config);

    const descEl = document.getElementById("config-description");
    expect(descEl.textContent).toContain("REST clients");
    expect(descEl.textContent).toContain("HTTP Server");

    const usageEl = document.getElementById("config-usage");
    expect(usageEl.textContent).toContain("HTTP clients");

    const titleEl = document.getElementById("config-display-title");
    expect(titleEl.textContent).toContain("HTTP");
  });

  test("formats config as JSON with proper indentation", () => {
    const server = { id: "s4", name: "Test" };
    const config = { test: { nested: "value" } };

    showConfigDisplayModal(server, "stdio", config);

    const contentEl = document.getElementById("config-content");
    const parsed = JSON.parse(contentEl.value);
    expect(parsed).toEqual(config);
    expect(contentEl.value).toContain("  "); // Has indentation
  });

  test("handles missing DOM elements gracefully", () => {
    document.body.innerHTML = ""; // Clear all elements
    const server = { id: "s5", name: "Missing" };
    const config = { test: "data" };

    expect(() => {
      showConfigDisplayModal(server, "stdio", config);
    }).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// copyConfigToClipboard
// ---------------------------------------------------------------------------
describe("copyConfigToClipboard", () => {
  test("copies config content to clipboard successfully", async () => {
    const contentEl = document.createElement("textarea");
    contentEl.id = "config-content";
    contentEl.value = '{"test": "config"}';
    document.body.appendChild(contentEl);

    const clipboardSpy = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();

    await copyConfigToClipboard();

    expect(clipboardSpy).toHaveBeenCalledWith('{"test": "config"}');
    expect(showSuccessMessage).toHaveBeenCalledWith("Configuration copied to clipboard!");

    clipboardSpy.mockRestore();
  });

  test("handles missing config content element", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await copyConfigToClipboard();

    expect(showErrorMessage).toHaveBeenCalledWith(expect.stringContaining("copy"));
    errorSpy.mockRestore();
  });

  test("falls back to manual selection on clipboard API failure", async () => {
    const contentEl = document.createElement("textarea");
    contentEl.id = "config-content";
    contentEl.value = "test config";
    contentEl.select = vi.fn();
    contentEl.setSelectionRange = vi.fn();
    document.body.appendChild(contentEl);

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const clipboardSpy = vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(
      new Error("Clipboard access denied")
    );

    await copyConfigToClipboard();

    expect(contentEl.select).toHaveBeenCalled();
    expect(contentEl.setSelectionRange).toHaveBeenCalledWith(0, 99999);
    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("copy the selected text manually")
    );

    clipboardSpy.mockRestore();
    errorSpy.mockRestore();
  });

  test("handles fallback when element is missing during clipboard failure", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const clipboardSpy = vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(
      new Error("Denied")
    );

    // First create element for initial check, then remove for fallback
    const contentEl = document.createElement("textarea");
    contentEl.id = "config-content";
    contentEl.value = "test";
    document.body.appendChild(contentEl);

    // Mock safeGetElement to return null on second call (in catch block)
    let callCount = 0;
    const { safeGetElement } = await import("../../../mcpgateway/admin_ui/utils.js");
    safeGetElement.mockImplementation((id) => {
      callCount++;
      if (callCount === 1) return contentEl;
      return null;
    });

    await copyConfigToClipboard();

    expect(showErrorMessage).toHaveBeenCalledWith("Failed to copy configuration");

    clipboardSpy.mockRestore();
    errorSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// downloadConfig
// ---------------------------------------------------------------------------
describe("downloadConfig", () => {
  let createObjectURLSpy;
  let revokeObjectURLSpy;

  beforeEach(() => {
    createObjectURLSpy = vi.spyOn(window.URL, "createObjectURL").mockReturnValue("blob:mock-url");
    revokeObjectURLSpy = vi.spyOn(window.URL, "revokeObjectURL").mockImplementation(() => {});
  });

  afterEach(() => {
    createObjectURLSpy.mockRestore();
    revokeObjectURLSpy.mockRestore();
  });

  test("creates blob with correct JSON content", async () => {
    const mockServer = { id: "blob-test", name: "Blob Server" };
    const config = { servers: { test: "config" } };

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: async () => mockServer,
    });

    await exportServerConfig("blob-test", "sse");

    downloadConfig();

    expect(createObjectURLSpy).toHaveBeenCalled();
    const blobArg = createObjectURLSpy.mock.calls[0][0];
    expect(blobArg.type).toBe("application/json");
  });

  test("cleans up object URL after download", async () => {
    const mockServer = { id: "cleanup-test", name: "Cleanup Server" };
    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: async () => mockServer,
    });

    await exportServerConfig("cleanup-test", "http");

    downloadConfig();

    expect(revokeObjectURLSpy).toHaveBeenCalledWith("blob:mock-url");
  });

  test("handles download error gracefully", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const mockServer = { id: "error-dl", name: "Error Server" };

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: async () => mockServer,
    });

    await exportServerConfig("error-dl", "stdio");

    // Force an error during blob creation
    createObjectURLSpy.mockImplementation(() => {
      throw new Error("Blob creation failed");
    });

    downloadConfig();

    expect(showErrorMessage).toHaveBeenCalledWith("Failed to download configuration");
    errorSpy.mockRestore();
  });

  test("generates correct filename for stdio config", async () => {
    const mockServer = { id: "stdio-dl", name: "My Stdio Server" };
    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: async () => mockServer,
    });

    await exportServerConfig("stdio-dl", "stdio");

    let downloadedFilename = null;
    const appendChildSpy = vi.spyOn(document.body, "appendChild").mockImplementation((el) => {
      if (el.tagName === "A") {
        downloadedFilename = el.download;
      }
      return el;
    });

    downloadConfig();

    expect(downloadedFilename).toContain("stdio-config.json");
    appendChildSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// goBackToSelection
// ---------------------------------------------------------------------------
describe("goBackToSelection", () => {
  test("closes display modal and opens selection modal", () => {
    goBackToSelection();

    expect(closeModal).toHaveBeenCalledWith("config-display-modal");
    expect(openModal).toHaveBeenCalledWith("config-selection-modal");
  });

  test("can be called multiple times without error", () => {
    goBackToSelection();
    goBackToSelection();
    goBackToSelection();

    expect(closeModal).toHaveBeenCalledTimes(3);
    expect(openModal).toHaveBeenCalledTimes(3);
  });
});
