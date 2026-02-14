/**
 * Unit tests for fileTransfer.js module
 * Tests: handleExportAll, handleExportSelected, showExportProgress, handleFileSelect,
 *        handleDragOver, handleDragLeave, handleFileDrop, processImportJSONFile,
 *        resetImportFile, previewImport, handleImport, displayImportResults,
 *        showImportProgress, loadRecentImports, refreshCurrentTabData
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

// Mock dependencies BEFORE importing module under test
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
}));

vi.mock("../../../mcpgateway/admin_ui/selectiveImport.js", () => ({
  displayImportPreview: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  getAuthToken: vi.fn(() => Promise.resolve("test-token")),
}));

vi.mock("../../../mcpgateway/admin_ui/tools.js", () => ({
  loadTools: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  showNotification: vi.fn(),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));

// Import module under test AFTER mocks are set up
import {
  handleExportAll,
  handleExportSelected,
  showExportProgress,
  handleFileSelect,
  handleDragOver,
  handleDragLeave,
  handleFileDrop,
  processImportJSONFile,
  resetImportFile,
  previewImport,
  handleImport,
  displayImportResults,
  showImportProgress,
  loadRecentImports,
  refreshCurrentTabData,
} from "../../../mcpgateway/admin_ui/fileTransfer.js";

import { showNotification } from "../../../mcpgateway/admin_ui/utils.js";
import { getAuthToken } from "../../../mcpgateway/admin_ui/tokens.js";
import { displayImportPreview } from "../../../mcpgateway/admin_ui/selectiveImport.js";
import { loadTools } from "../../../mcpgateway/admin_ui/tools.js";

// ---------------------------------------------------------------------------
// handleExportAll
// ---------------------------------------------------------------------------
describe("handleExportAll", () => {
  let fetchSpy;
  let createObjectURLSpy;
  let revokeObjectURLSpy;

  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
    window.ROOT_PATH = "";
    window.URL.createObjectURL = vi.fn(() => "blob:test-url");
    window.URL.revokeObjectURL = vi.fn();
    createObjectURLSpy = vi.spyOn(window.URL, "createObjectURL");
    revokeObjectURLSpy = vi.spyOn(window.URL, "revokeObjectURL");
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
  });

  test("performs export with selected options", async () => {
    // Setup DOM elements for export options
    const toolsCheckbox = document.createElement("input");
    toolsCheckbox.id = "export-tools";
    toolsCheckbox.type = "checkbox";
    toolsCheckbox.checked = true;
    document.body.appendChild(toolsCheckbox);

    const gatewaysCheckbox = document.createElement("input");
    gatewaysCheckbox.id = "export-gateways";
    gatewaysCheckbox.type = "checkbox";
    gatewaysCheckbox.checked = true;
    document.body.appendChild(gatewaysCheckbox);

    const tagsInput = document.createElement("input");
    tagsInput.id = "export-tags";
    tagsInput.value = "production";
    document.body.appendChild(tagsInput);

    const includeInactive = document.createElement("input");
    includeInactive.id = "export-include-inactive";
    includeInactive.type = "checkbox";
    includeInactive.checked = true;
    document.body.appendChild(includeInactive);

    const progressEl = document.createElement("div");
    progressEl.id = "export-progress";
    progressEl.classList.add("hidden");
    document.body.appendChild(progressEl);

    const progressBar = document.createElement("div");
    progressBar.id = "export-progress-bar";
    progressBar.style.width = "0%";
    document.body.appendChild(progressBar);

    const blob = new Blob(['{"test":"data"}'], { type: "application/json" });
    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(blob),
    });

    // Mock document.body.appendChild and removeChild to avoid navigation errors
    const originalAppendChild = document.body.appendChild;
    const originalRemoveChild = document.body.removeChild;
    const mockAppendChild = vi.fn((node) => {
      if (node.tagName === 'A' && node.download) {
        // Don't actually append download link to avoid click navigation
        return node;
      }
      return originalAppendChild.call(document.body, node);
    });
    const mockRemoveChild = vi.fn((node) => {
      // Don't throw if node is not a child
      if (document.body.contains(node)) {
        return originalRemoveChild.call(document.body, node);
      }
      return node;
    });
    document.body.appendChild = mockAppendChild;
    document.body.removeChild = mockRemoveChild;

    await handleExportAll();

    expect(fetchSpy).toHaveBeenCalled();
    const [url, options] = fetchSpy.mock.calls[0];
    expect(url).toContain("/admin/export/configuration");
    expect(url).toContain("types=tools");
    expect(url).toContain("gateways");
    expect(url).toContain("tags=production");
    expect(url).toContain("include_inactive=true");
    expect(options.headers.Authorization).toBe("Bearer test-token");
    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Export completed successfully"),
      "success"
    );

    // Restore
    document.body.appendChild = originalAppendChild;
    document.body.removeChild = originalRemoveChild;
    fetchSpy.mockRestore();
  });

  test("handles export error gracefully", async () => {
    const progressEl = document.createElement("div");
    progressEl.id = "export-progress";
    progressEl.classList.add("hidden");
    document.body.appendChild(progressEl);

    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      statusText: "Server Error",
    });

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await handleExportAll();

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Export failed"),
      "error"
    );

    fetchSpy.mockRestore();
    consoleSpy.mockRestore();
  });

  test("creates download link with correct filename format", async () => {
    const progressEl = document.createElement("div");
    progressEl.id = "export-progress";
    document.body.appendChild(progressEl);

    const blob = new Blob(['{"test":"data"}'], { type: "application/json" });
    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(blob),
    });

    await handleExportAll();

    expect(createObjectURLSpy).toHaveBeenCalledWith(blob);
    expect(revokeObjectURLSpy).toHaveBeenCalledWith("blob:test-url");

    fetchSpy.mockRestore();
  });

  test("shows and hides export progress", async () => {
    const progressEl = document.createElement("div");
    progressEl.id = "export-progress";
    progressEl.classList.add("hidden");
    document.body.appendChild(progressEl);

    const blob = new Blob(['{"test":"data"}'], { type: "application/json" });
    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(blob),
    });

    await handleExportAll();

    // Progress should be hidden after completion
    expect(progressEl.classList.contains("hidden")).toBe(true);

    fetchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// handleExportSelected
// ---------------------------------------------------------------------------
describe("handleExportSelected", () => {
  let fetchSpy;

  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
    window.ROOT_PATH = "";
    window.URL.createObjectURL = vi.fn(() => "blob:test-url");
    window.URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
  });

  test("calls handleExportAll as simplified implementation", async () => {
    const progressEl = document.createElement("div");
    progressEl.id = "export-progress";
    progressEl.classList.add("hidden");
    document.body.appendChild(progressEl);

    const progressBar = document.createElement("div");
    progressBar.id = "export-progress-bar";
    progressBar.style.width = "0%";
    document.body.appendChild(progressBar);

    const blob = new Blob(['{"test":"data"}'], { type: "application/json" });
    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(blob),
    });

    // Mock document.body.appendChild and removeChild to avoid navigation errors
    const originalAppendChild = document.body.appendChild;
    const originalRemoveChild = document.body.removeChild;
    const mockAppendChild = vi.fn((node) => {
      if (node.tagName === 'A' && node.download) {
        // Don't actually append download link to avoid click navigation
        return node;
      }
      return originalAppendChild.call(document.body, node);
    });
    const mockRemoveChild = vi.fn((node) => {
      // Don't throw if node is not a child
      if (document.body.contains(node)) {
        return originalRemoveChild.call(document.body, node);
      }
      return node;
    });
    document.body.appendChild = mockAppendChild;
    document.body.removeChild = mockRemoveChild;

    await handleExportSelected();

    expect(fetchSpy).toHaveBeenCalled();
    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Export completed successfully"),
      "success"
    );

    // Restore
    document.body.appendChild = originalAppendChild;
    document.body.removeChild = originalRemoveChild;
    fetchSpy.mockRestore();
  });

  test("handles export error", async () => {
    const progressEl = document.createElement("div");
    progressEl.id = "export-progress";
    document.body.appendChild(progressEl);

    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      statusText: "Error",
    });

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await handleExportSelected();

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("failed"),
      "error"
    );

    fetchSpy.mockRestore();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// showExportProgress
// ---------------------------------------------------------------------------
describe("showExportProgress", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
    vi.useFakeTimers();
  });

  afterEach(() => {
    document.body.innerHTML = "";
    vi.useRealTimers();
  });

  test("shows progress element when show is true", () => {
    const progressEl = document.createElement("div");
    progressEl.id = "export-progress";
    progressEl.classList.add("hidden");
    document.body.appendChild(progressEl);

    const progressBar = document.createElement("div");
    progressBar.id = "export-progress-bar";
    progressBar.style.width = "0%";
    document.body.appendChild(progressBar);

    showExportProgress(true);

    expect(progressEl.classList.contains("hidden")).toBe(false);
  });

  test("hides progress element when show is false", () => {
    const progressEl = document.createElement("div");
    progressEl.id = "export-progress";
    document.body.appendChild(progressEl);

    showExportProgress(false);

    expect(progressEl.classList.contains("hidden")).toBe(true);
  });

  test("animates progress bar when showing", () => {
    const progressEl = document.createElement("div");
    progressEl.id = "export-progress";
    progressEl.classList.add("hidden");
    document.body.appendChild(progressEl);

    const progressBar = document.createElement("div");
    progressBar.id = "export-progress-bar";
    progressBar.style.width = "0%";
    document.body.appendChild(progressBar);

    showExportProgress(true);

    // Advance timers to trigger interval
    vi.advanceTimersByTime(200);
    expect(progressBar.style.width).toBe("10%");

    vi.advanceTimersByTime(200);
    expect(progressBar.style.width).toBe("20%");
  });

  test("does nothing when progress element is missing", () => {
    expect(() => showExportProgress(true)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// handleFileSelect
// ---------------------------------------------------------------------------
describe("handleFileSelect", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
    window.Admin = { currentImportData: null };
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.Admin;
  });

  test("processes file when file is selected", () => {
    const file = new File(['{"version":"1.0","entities":{}}'], "test.json", {
      type: "application/json",
    });

    const event = {
      target: {
        files: [file],
      },
    };

    // Mock FileReader constructor
    const mockFileReader = {
      readAsText: vi.fn(function () {
        this.onload({
          target: { result: '{"version":"1.0","entities":{}}' },
        });
      }),
      onload: null,
    };

    globalThis.FileReader = vi.fn(function() {
      return mockFileReader;
    });

    handleFileSelect(event);

    expect(mockFileReader.readAsText).toHaveBeenCalledWith(file);
  });

  test("does nothing when no file is selected", () => {
    const event = {
      target: {
        files: [],
      },
    };

    expect(() => handleFileSelect(event)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// handleDragOver
// ---------------------------------------------------------------------------
describe("handleDragOver", () => {
  test("prevents default and adds CSS classes", () => {
    const element = document.createElement("div");
    const event = {
      preventDefault: vi.fn(),
      dataTransfer: { dropEffect: "" },
      currentTarget: element,
    };

    handleDragOver(event);

    expect(event.preventDefault).toHaveBeenCalled();
    expect(event.dataTransfer.dropEffect).toBe("copy");
    expect(element.classList.contains("border-blue-500")).toBe(true);
    expect(element.classList.contains("bg-blue-50")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// handleDragLeave
// ---------------------------------------------------------------------------
describe("handleDragLeave", () => {
  test("prevents default and removes CSS classes", () => {
    const element = document.createElement("div");
    element.classList.add("border-blue-500", "bg-blue-50", "dark:bg-blue-900");

    const event = {
      preventDefault: vi.fn(),
      currentTarget: element,
    };

    handleDragLeave(event);

    expect(event.preventDefault).toHaveBeenCalled();
    expect(element.classList.contains("border-blue-500")).toBe(false);
    expect(element.classList.contains("bg-blue-50")).toBe(false);
    expect(element.classList.contains("dark:bg-blue-900")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// handleFileDrop
// ---------------------------------------------------------------------------
describe("handleFileDrop", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
    window.Admin = { currentImportData: null };
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.Admin;
  });

  test("processes dropped file and removes CSS classes", () => {
    const file = new File(['{"version":"1.0","entities":{}}'], "test.json", {
      type: "application/json",
    });

    const element = document.createElement("div");
    element.classList.add("border-blue-500", "bg-blue-50", "dark:bg-blue-900");

    const event = {
      preventDefault: vi.fn(),
      currentTarget: element,
      dataTransfer: {
        files: [file],
      },
    };

    // Mock FileReader constructor
    const mockFileReader = {
      readAsText: vi.fn(function () {
        this.onload({
          target: { result: '{"version":"1.0","entities":{}}' },
        });
      }),
      onload: null,
    };

    globalThis.FileReader = vi.fn(function() {
      return mockFileReader;
    });

    handleFileDrop(event);

    expect(event.preventDefault).toHaveBeenCalled();
    expect(element.classList.contains("border-blue-500")).toBe(false);
    expect(mockFileReader.readAsText).toHaveBeenCalledWith(file);
  });

  test("does nothing when no files are dropped", () => {
    const element = document.createElement("div");
    const event = {
      preventDefault: vi.fn(),
      currentTarget: element,
      dataTransfer: {
        files: [],
      },
    };

    expect(() => handleFileDrop(event)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// processImportJSONFile
// ---------------------------------------------------------------------------
describe("processImportJSONFile", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
    window.Admin = { currentImportData: null };
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.Admin;
  });

  test("rejects non-JSON files", () => {
    const file = new File(["test"], "test.txt", { type: "text/plain" });

    processImportJSONFile(file);

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Please select a JSON file"),
      "error"
    );
  });

  test("processes valid JSON file and enables buttons", () => {
    const previewBtn = document.createElement("button");
    previewBtn.id = "import-preview-btn";
    previewBtn.disabled = true;
    document.body.appendChild(previewBtn);

    const validateBtn = document.createElement("button");
    validateBtn.id = "import-validate-btn";
    validateBtn.disabled = true;
    document.body.appendChild(validateBtn);

    const executeBtn = document.createElement("button");
    executeBtn.id = "import-execute-btn";
    executeBtn.disabled = true;
    document.body.appendChild(executeBtn);

    const dropZone = document.createElement("div");
    dropZone.id = "import-drop-zone";
    document.body.appendChild(dropZone);

    const file = new File(
      ['{"version":"1.0","entities":{},"metadata":{"entity_counts":{"tools":5}}}'],
      "test.json",
      { type: "application/json" }
    );

    const mockFileReader = {
      readAsText: vi.fn(function () {
        this.onload({
          target: {
            result:
              '{"version":"1.0","entities":{},"metadata":{"entity_counts":{"tools":5}}}',
          },
        });
      }),
      onload: null,
    };

    globalThis.FileReader = vi.fn(function() {
      return mockFileReader;
    });

    processImportJSONFile(file);

    expect(window.Admin.currentImportData).toEqual({
      version: "1.0",
      entities: {},
      metadata: { entity_counts: { tools: 5 } },
    });
    expect(previewBtn.disabled).toBe(false);
    expect(validateBtn.disabled).toBe(false);
    expect(executeBtn.disabled).toBe(false);
    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Import file loaded"),
      "success"
    );
  });

  test("shows error for invalid JSON format", () => {
    const file = new File(['{"invalid":true}'], "test.json", {
      type: "application/json",
    });

    const mockFileReader = {
      readAsText: vi.fn(function () {
        this.onload({
          target: { result: '{"invalid":true}' },
        });
      }),
      onload: null,
    };

    globalThis.FileReader = vi.fn(function() {
      return mockFileReader;
    });

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    processImportJSONFile(file);

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Invalid JSON file"),
      "error"
    );

    consoleSpy.mockRestore();
  });

  test("shows error for invalid JSON syntax", () => {
    const file = new File(['{invalid json}'], "test.json", {
      type: "application/json",
    });

    const mockFileReader = {
      readAsText: vi.fn(function () {
        this.onload({
          target: { result: '{invalid json}' },
        });
      }),
      onload: null,
    };

    globalThis.FileReader = vi.fn(function() {
      return mockFileReader;
    });

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    processImportJSONFile(file);

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Invalid JSON file"),
      "error"
    );

    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// resetImportFile
// ---------------------------------------------------------------------------
describe("resetImportFile", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
    window.Admin = { currentImportData: { version: "1.0" } };
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.Admin;
  });

  test("clears import data and resets UI", () => {
    const dropZone = document.createElement("div");
    dropZone.id = "import-drop-zone";
    document.body.appendChild(dropZone);

    const previewBtn = document.createElement("button");
    previewBtn.id = "import-preview-btn";
    previewBtn.disabled = false;
    document.body.appendChild(previewBtn);

    const validateBtn = document.createElement("button");
    validateBtn.id = "import-validate-btn";
    validateBtn.disabled = false;
    document.body.appendChild(validateBtn);

    const executeBtn = document.createElement("button");
    executeBtn.id = "import-execute-btn";
    executeBtn.disabled = false;
    document.body.appendChild(executeBtn);

    const statusSection = document.createElement("div");
    statusSection.id = "import-status-section";
    document.body.appendChild(statusSection);

    resetImportFile();

    expect(window.Admin.currentImportData).toBeNull();
    expect(dropZone.innerHTML).toContain("Click to upload");
    expect(previewBtn.disabled).toBe(true);
    expect(validateBtn.disabled).toBe(true);
    expect(executeBtn.disabled).toBe(true);
    expect(statusSection.classList.contains("hidden")).toBe(true);
  });

  test("does nothing when elements are missing", () => {
    expect(() => resetImportFile()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// previewImport
// ---------------------------------------------------------------------------
describe("previewImport", () => {
  let fetchSpy;

  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
    window.ROOT_PATH = "";
    window.currentImportData = null;
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.currentImportData;
  });

  test("shows error when no import data is loaded", async () => {
    await previewImport();

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Please select an import file first"),
      "error"
    );
  });

  test("fetches and displays preview successfully", async () => {
    window.currentImportData = { version: "1.0", entities: {} };

    const previewBtn = document.createElement("button");
    previewBtn.id = "import-preview-btn";
    document.body.appendChild(previewBtn);

    const validateBtn = document.createElement("button");
    validateBtn.id = "import-validate-btn";
    document.body.appendChild(validateBtn);

    const executeBtn = document.createElement("button");
    executeBtn.id = "import-execute-btn";
    document.body.appendChild(executeBtn);

    const previewData = { items: [], summary: {} };

    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ preview: previewData }),
    });

    await previewImport();

    expect(fetchSpy).toHaveBeenCalledWith(
      "/admin/import/preview",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          Authorization: "Bearer test-token",
        }),
      })
    );
    expect(displayImportPreview).toHaveBeenCalledWith(previewData);
    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Import preview generated successfully"),
      "success"
    );

    fetchSpy.mockRestore();
  });

  test("handles preview error", async () => {
    window.currentImportData = { version: "1.0", entities: {} };

    const previewBtn = document.createElement("button");
    previewBtn.id = "import-preview-btn";
    document.body.appendChild(previewBtn);

    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      statusText: "Bad Request",
      json: () => Promise.resolve({ detail: "Invalid data" }),
    });

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await previewImport();

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Preview failed"),
      "error"
    );

    fetchSpy.mockRestore();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// handleImport
// ---------------------------------------------------------------------------
describe("handleImport", () => {
  let fetchSpy;

  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
    window.ROOT_PATH = "";
    window.currentImportData = null;
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.ROOT_PATH;
    delete window.currentImportData;
  });

  test("shows error when no import data is loaded", async () => {
    await handleImport(false);

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Please select an import file first"),
      "error"
    );
  });

  test("performs dry run validation successfully", async () => {
    window.currentImportData = { version: "1.0", entities: {} };

    const conflictStrategy = document.createElement("select");
    conflictStrategy.id = "import-conflict-strategy";
    conflictStrategy.value = "update";
    document.body.appendChild(conflictStrategy);

    const previewBtn = document.createElement("button");
    previewBtn.id = "import-preview-btn";
    document.body.appendChild(previewBtn);

    const validateBtn = document.createElement("button");
    validateBtn.id = "import-validate-btn";
    document.body.appendChild(validateBtn);

    const executeBtn = document.createElement("button");
    executeBtn.id = "import-execute-btn";
    document.body.appendChild(executeBtn);

    const statusSection = document.createElement("div");
    statusSection.id = "import-status-section";
    statusSection.classList.add("hidden");
    document.body.appendChild(statusSection);

    const totalEl = document.createElement("span");
    totalEl.id = "import-total";
    document.body.appendChild(totalEl);

    const createdEl = document.createElement("span");
    createdEl.id = "import-created";
    document.body.appendChild(createdEl);

    const updatedEl = document.createElement("span");
    updatedEl.id = "import-updated";
    document.body.appendChild(updatedEl);

    const failedEl = document.createElement("span");
    failedEl.id = "import-failed";
    document.body.appendChild(failedEl);

    const progressBar = document.createElement("div");
    progressBar.id = "import-progress-bar";
    progressBar.style.width = "0%";
    document.body.appendChild(progressBar);

    const progressText = document.createElement("div");
    progressText.id = "import-progress-text";
    document.body.appendChild(progressText);

    const messagesContainer = document.createElement("div");
    messagesContainer.id = "import-messages";
    document.body.appendChild(messagesContainer);

    const result = {
      status: "completed",
      progress: { total: 10, processed: 10, created: 5, updated: 3, failed: 2 },
      errors: [],
      warnings: [],
    };

    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(result),
    });

    await handleImport(true);

    expect(fetchSpy).toHaveBeenCalledWith(
      "/admin/import/configuration",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"dry_run":true'),
      })
    );
    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("validation completed"),
      "success"
    );

    fetchSpy.mockRestore();
  });

  test("performs actual import and refreshes data", async () => {
    window.currentImportData = { version: "1.0", entities: {} };

    const conflictStrategy = document.createElement("select");
    conflictStrategy.id = "import-conflict-strategy";
    conflictStrategy.value = "skip";
    document.body.appendChild(conflictStrategy);

    const rekeySecret = document.createElement("input");
    rekeySecret.id = "import-rekey-secret";
    rekeySecret.value = "new-secret";
    document.body.appendChild(rekeySecret);

    const previewBtn = document.createElement("button");
    previewBtn.id = "import-preview-btn";
    document.body.appendChild(previewBtn);

    const validateBtn = document.createElement("button");
    validateBtn.id = "import-validate-btn";
    document.body.appendChild(validateBtn);

    const executeBtn = document.createElement("button");
    executeBtn.id = "import-execute-btn";
    document.body.appendChild(executeBtn);

    const statusSection = document.createElement("div");
    statusSection.id = "import-status-section";
    statusSection.classList.add("hidden");
    document.body.appendChild(statusSection);

    const totalEl = document.createElement("span");
    totalEl.id = "import-total";
    document.body.appendChild(totalEl);

    const createdEl = document.createElement("span");
    createdEl.id = "import-created";
    document.body.appendChild(createdEl);

    const updatedEl = document.createElement("span");
    updatedEl.id = "import-updated";
    document.body.appendChild(updatedEl);

    const failedEl = document.createElement("span");
    failedEl.id = "import-failed";
    document.body.appendChild(failedEl);

    const progressBar = document.createElement("div");
    progressBar.id = "import-progress-bar";
    progressBar.style.width = "0%";
    document.body.appendChild(progressBar);

    const progressText = document.createElement("div");
    progressText.id = "import-progress-text";
    document.body.appendChild(progressText);

    const messagesContainer = document.createElement("div");
    messagesContainer.id = "import-messages";
    document.body.appendChild(messagesContainer);

    const result = {
      status: "completed",
      progress: { total: 5, processed: 5, created: 3, updated: 2, failed: 0 },
      errors: [],
      warnings: [],
    };

    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(result),
    });

    await handleImport(false);

    expect(fetchSpy).toHaveBeenCalledWith(
      "/admin/import/configuration",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"dry_run":false'),
      })
    );
    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("import completed"),
      "success"
    );

    fetchSpy.mockRestore();
  });

  test("handles import error", async () => {
    window.currentImportData = { version: "1.0", entities: {} };

    const previewBtn = document.createElement("button");
    previewBtn.id = "import-preview-btn";
    document.body.appendChild(previewBtn);

    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      statusText: "Internal Server Error",
      json: () => Promise.resolve({ detail: "Database error" }),
    });

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await handleImport(false);

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Import failed"),
      "error"
    );

    fetchSpy.mockRestore();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// displayImportResults
// ---------------------------------------------------------------------------
describe("displayImportResults", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("displays results with progress counts", () => {
    const statusSection = document.createElement("div");
    statusSection.id = "import-status-section";
    statusSection.classList.add("hidden");
    document.body.appendChild(statusSection);

    const totalEl = document.createElement("span");
    totalEl.id = "import-total";
    document.body.appendChild(totalEl);

    const createdEl = document.createElement("span");
    createdEl.id = "import-created";
    document.body.appendChild(createdEl);

    const updatedEl = document.createElement("span");
    updatedEl.id = "import-updated";
    document.body.appendChild(updatedEl);

    const failedEl = document.createElement("span");
    failedEl.id = "import-failed";
    document.body.appendChild(failedEl);

    const progressBar = document.createElement("div");
    progressBar.id = "import-progress-bar";
    progressBar.style.width = "0%";
    document.body.appendChild(progressBar);

    const progressText = document.createElement("div");
    progressText.id = "import-progress-text";
    document.body.appendChild(progressText);

    const messagesContainer = document.createElement("div");
    messagesContainer.id = "import-messages";
    document.body.appendChild(messagesContainer);

    const result = {
      status: "completed",
      progress: { total: 10, processed: 10, created: 6, updated: 3, failed: 1 },
      errors: ["Error 1"],
      warnings: ["Warning 1", "Warning 2"],
    };

    displayImportResults(result, false);

    expect(statusSection.classList.contains("hidden")).toBe(false);
    expect(totalEl.textContent).toBe("10");
    expect(createdEl.textContent).toBe("6");
    expect(updatedEl.textContent).toBe("3");
    expect(failedEl.textContent).toBe("1");
    expect(progressBar.style.width).toBe("100%");
    expect(progressText.textContent).toBe("100%");
    expect(messagesContainer.innerHTML).toContain("Errors");
    expect(messagesContainer.innerHTML).toContain("Warnings");
  });

  test("displays dry run results with 'Would Import' label", () => {
    const statusSection = document.createElement("div");
    statusSection.id = "import-status-section";
    statusSection.classList.add("hidden");
    document.body.appendChild(statusSection);

    const totalEl = document.createElement("span");
    totalEl.id = "import-total";
    document.body.appendChild(totalEl);

    const createdEl = document.createElement("span");
    createdEl.id = "import-created";
    document.body.appendChild(createdEl);

    const updatedEl = document.createElement("span");
    updatedEl.id = "import-updated";
    document.body.appendChild(updatedEl);

    const failedEl = document.createElement("span");
    failedEl.id = "import-failed";
    document.body.appendChild(failedEl);

    const messagesContainer = document.createElement("div");
    messagesContainer.id = "import-messages";
    document.body.appendChild(messagesContainer);

    const result = {
      status: "completed",
      progress: { total: 5, processed: 5, created: 0, updated: 0, failed: 0 },
      errors: [],
      warnings: ["Would create 3 tools", "Would update 2 servers"],
    };

    displayImportResults(result, true);

    expect(messagesContainer.innerHTML).toContain("Would Import");
  });

  test("displays errors with truncation when more than 5", () => {
    const statusSection = document.createElement("div");
    statusSection.id = "import-status-section";
    statusSection.classList.add("hidden");
    document.body.appendChild(statusSection);

    const totalEl = document.createElement("span");
    totalEl.id = "import-total";
    document.body.appendChild(totalEl);

    const createdEl = document.createElement("span");
    createdEl.id = "import-created";
    document.body.appendChild(createdEl);

    const updatedEl = document.createElement("span");
    updatedEl.id = "import-updated";
    document.body.appendChild(updatedEl);

    const failedEl = document.createElement("span");
    failedEl.id = "import-failed";
    document.body.appendChild(failedEl);

    const messagesContainer = document.createElement("div");
    messagesContainer.id = "import-messages";
    document.body.appendChild(messagesContainer);

    const errors = Array.from({ length: 10 }, (_, i) => `Error ${i + 1}`);

    const result = {
      status: "completed",
      progress: { total: 10, processed: 10, created: 0, updated: 0, failed: 10 },
      errors: errors,
      warnings: [],
    };

    displayImportResults(result, false);

    expect(messagesContainer.innerHTML).toContain("Error 1");
    expect(messagesContainer.innerHTML).toContain("Error 5");
    expect(messagesContainer.innerHTML).toContain("and 5 more errors");
  });

  test("handles empty progress object", () => {
    const statusSection = document.createElement("div");
    statusSection.id = "import-status-section";
    statusSection.classList.add("hidden");
    document.body.appendChild(statusSection);

    // Add all required elements even if they won't be used
    const totalEl = document.createElement("span");
    totalEl.id = "import-total";
    document.body.appendChild(totalEl);

    const createdEl = document.createElement("span");
    createdEl.id = "import-created";
    document.body.appendChild(createdEl);

    const updatedEl = document.createElement("span");
    updatedEl.id = "import-updated";
    document.body.appendChild(updatedEl);

    const failedEl = document.createElement("span");
    failedEl.id = "import-failed";
    document.body.appendChild(failedEl);

    const messagesContainer = document.createElement("div");
    messagesContainer.id = "import-messages";
    document.body.appendChild(messagesContainer);

    const result = {
      status: "completed",
      progress: {}, // Empty progress object
      errors: [],
      warnings: [],
    };

    displayImportResults(result, false);

    expect(statusSection.classList.contains("hidden")).toBe(false);
    // Should default to 0 when values are missing
    expect(totalEl.textContent).toBe("0");
    expect(createdEl.textContent).toBe("0");
  });
});

// ---------------------------------------------------------------------------
// showImportProgress
// ---------------------------------------------------------------------------
describe("showImportProgress", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("disables buttons when showing progress", () => {
    const previewBtn = document.createElement("button");
    previewBtn.id = "import-preview-btn";
    previewBtn.disabled = false;
    document.body.appendChild(previewBtn);

    const validateBtn = document.createElement("button");
    validateBtn.id = "import-validate-btn";
    validateBtn.disabled = false;
    document.body.appendChild(validateBtn);

    const executeBtn = document.createElement("button");
    executeBtn.id = "import-execute-btn";
    executeBtn.disabled = false;
    document.body.appendChild(executeBtn);

    showImportProgress(true);

    expect(previewBtn.disabled).toBe(true);
    expect(validateBtn.disabled).toBe(true);
    expect(executeBtn.disabled).toBe(true);
  });

  test("enables buttons when hiding progress", () => {
    const previewBtn = document.createElement("button");
    previewBtn.id = "import-preview-btn";
    previewBtn.disabled = true;
    document.body.appendChild(previewBtn);

    const validateBtn = document.createElement("button");
    validateBtn.id = "import-validate-btn";
    validateBtn.disabled = true;
    document.body.appendChild(validateBtn);

    const executeBtn = document.createElement("button");
    executeBtn.id = "import-execute-btn";
    executeBtn.disabled = true;
    document.body.appendChild(executeBtn);

    showImportProgress(false);

    expect(previewBtn.disabled).toBe(false);
    expect(validateBtn.disabled).toBe(false);
    expect(executeBtn.disabled).toBe(false);
  });

  test("does nothing when buttons are missing", () => {
    expect(() => showImportProgress(true)).not.toThrow();
    expect(() => showImportProgress(false)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// loadRecentImports
// ---------------------------------------------------------------------------
describe("loadRecentImports", () => {
  let fetchSpy;

  beforeEach(() => {
    vi.clearAllMocks();
    window.ROOT_PATH = "";
  });

  afterEach(() => {
    delete window.ROOT_PATH;
  });

  test("fetches recent imports successfully", async () => {
    const imports = [
      { id: 1, timestamp: "2024-01-01T00:00:00Z" },
      { id: 2, timestamp: "2024-01-02T00:00:00Z" },
    ];

    fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(imports),
    });

    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await loadRecentImports();

    expect(fetchSpy).toHaveBeenCalledWith(
      "/admin/import/status",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer test-token",
        }),
      })
    );
    expect(consoleSpy).toHaveBeenCalledWith("Loaded recent imports:", 2);

    fetchSpy.mockRestore();
    consoleSpy.mockRestore();
  });

  test("handles fetch error gracefully", async () => {
    fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new Error("Network error")
    );

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await loadRecentImports();

    expect(consoleSpy).toHaveBeenCalledWith(
      "Failed to load recent imports:",
      expect.any(Error)
    );

    fetchSpy.mockRestore();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// refreshCurrentTabData
// ---------------------------------------------------------------------------
describe("refreshCurrentTabData", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
    window.loadCatalog = vi.fn();
    window.Admin = { loadGateways: vi.fn() };
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.loadCatalog;
    delete window.Admin;
  });

  test("refreshes catalog when catalog tab is active", () => {
    const catalogTab = document.createElement("a");
    catalogTab.className = "tab-link border-indigo-500";
    catalogTab.setAttribute("href", "#catalog");
    document.body.appendChild(catalogTab);

    refreshCurrentTabData();

    expect(window.loadCatalog).toHaveBeenCalled();
  });

  test("refreshes tools when tools tab is active", () => {
    const toolsTab = document.createElement("a");
    toolsTab.className = "tab-link border-indigo-500";
    toolsTab.setAttribute("href", "#tools");
    document.body.appendChild(toolsTab);

    refreshCurrentTabData();

    expect(loadTools).toHaveBeenCalled();
  });

  test("refreshes gateways when gateways tab is active", () => {
    const gatewaysTab = document.createElement("a");
    gatewaysTab.className = "tab-link border-indigo-500";
    gatewaysTab.setAttribute("href", "#gateways");
    document.body.appendChild(gatewaysTab);

    refreshCurrentTabData();

    expect(window.Admin.loadGateways).toHaveBeenCalled();
  });

  test("does nothing when no active tab is found", () => {
    expect(() => refreshCurrentTabData()).not.toThrow();
  });

  test("does nothing when tab refresh function is missing", () => {
    delete window.loadCatalog;
    delete window.Admin;

    const catalogTab = document.createElement("a");
    catalogTab.className = "tab-link border-indigo-500";
    catalogTab.setAttribute("href", "#catalog");
    document.body.appendChild(catalogTab);

    expect(() => refreshCurrentTabData()).not.toThrow();
  });
});
