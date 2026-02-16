/**
 * Unit tests for tools.js module
 * Tests: viewTool, editTool, initToolSelect, testTool, loadTools,
 *        enrichTool, generateToolTestCases, generateTestCases,
 *        validateTool, runToolTest, cleanupToolTestState, cleanupToolTestModal
 */

import { describe, test, expect, vi, afterEach } from "vitest";

import {
  viewTool,
  editTool,
  initToolSelect,
  testTool,
  loadTools,
  enrichTool,
  generateToolTestCases,
  generateTestCases,
  validateTool,
  runToolTest,
  cleanupToolTestState,
  cleanupToolTestModal,
} from "../../../mcpgateway/admin_ui/tools.js";
import { fetchWithTimeout } from "../../../mcpgateway/admin_ui/utils";
import { openModal } from "../../../mcpgateway/admin_ui/modals";

vi.mock("../../../mcpgateway/admin_ui/appState.js", () => ({
  AppState: {
    parameterCount: 0,
    getParameterCount: () => 0,
    isModalActive: vi.fn(() => false),
    currentTestTool: null,
    toolTestResultEditor: null,
  },
}));
vi.mock("../../../mcpgateway/admin_ui/formFieldHandlers.js", () => ({
  updateEditToolRequestTypes: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/gateway.js", () => ({
  getSelectedGatewayIds: vi.fn(() => []),
}));
vi.mock("../../../mcpgateway/admin_ui/modals", () => ({
  closeModal: vi.fn(),
  openModal: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  safeSetInnerHTML: vi.fn((el, html) => {
    if (el) el.innerHTML = html;
  }),
  validateInputName: vi.fn((s) => ({ valid: true, value: s })),
  validateJson: vi.fn(() => ({ valid: true })),
  validatePassthroughHeader: vi.fn(() => ({ valid: true })),
  validateUrl: vi.fn(() => ({ valid: true })),
}));
vi.mock("../../../mcpgateway/admin_ui/utils", () => ({
  decodeHtml: vi.fn((s) => s || ""),
  fetchWithTimeout: vi.fn(),
  getCurrentTeamId: vi.fn(() => null),
  handleFetchError: vi.fn((e) => e.message),
  isInactiveChecked: vi.fn(() => false),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showErrorMessage: vi.fn(),
  showSuccessMessage: vi.fn(),
  updateEditToolUrl: vi.fn(),
}));

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// viewTool
// ---------------------------------------------------------------------------
describe("viewTool", () => {
  test("fetches and displays tool details", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "tool-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          tool: {
            id: "t1",
            name: "test-tool",
            description: "A test tool",
            inputSchema: {},
          },
        }),
    });

    await viewTool("t1");
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("t1")
    );
    consoleSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Network error"));

    await viewTool("t1");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// editTool
// ---------------------------------------------------------------------------
describe("editTool", () => {
  test("fetches tool data for editing", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          tool: {
            id: "t1",
            name: "test-tool",
            description: "desc",
            inputSchema: {},
          },
        }),
    });

    const nameInput = document.createElement("input");
    nameInput.id = "edit-tool-name";
    document.body.appendChild(nameInput);

    const idInput = document.createElement("input");
    idInput.id = "edit-tool-id";
    document.body.appendChild(idInput);

    await editTool("t1");
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("t1")
    );
    consoleSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Failed"));

    await editTool("t1");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// initToolSelect
// ---------------------------------------------------------------------------
describe("initToolSelect", () => {
  test("returns early when required elements are missing", async () => {
    window.ROOT_PATH = "";
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const container = document.createElement("div");
    container.id = "test-select";
    document.body.appendChild(container);

    // Needs 3 args: selectId, pillsId, warnId - returns early when not all found
    await initToolSelect("test-select", "test-pills", "test-warn");
    expect(fetchWithTimeout).not.toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  test("does nothing when container element is missing", async () => {
    window.ROOT_PATH = "";
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    await initToolSelect("missing-select", "missing-pills", "missing-warn");
    warnSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// testTool
// ---------------------------------------------------------------------------
describe("testTool", () => {
  test("fetches tool and opens test modal", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    // Create DOM elements testTool needs
    const title = document.createElement("div");
    title.id = "tool-test-modal-title";
    document.body.appendChild(title);

    const desc = document.createElement("div");
    desc.id = "tool-test-modal-description";
    document.body.appendChild(desc);

    const fields = document.createElement("div");
    fields.id = "tool-test-form-fields";
    document.body.appendChild(fields);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          tool: {
            id: "t1",
            name: "test-tool",
            inputSchema: {
              properties: { query: { type: "string" } },
              required: ["query"],
            },
          },
        }),
    });

    await testTool("t1");
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("t1"),
      expect.any(Object),
      expect.any(Number)
    );
    consoleSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Fetch failed"));

    // Use unique ID to avoid debounce from previous test
    await testTool("t-err-1");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
    warnSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// loadTools
// ---------------------------------------------------------------------------
describe("loadTools", () => {
  test("fetches tools list using fetch", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const toolBody = document.createElement("tbody");
    toolBody.id = "toolBody";
    document.body.appendChild(toolBody);

    // loadTools uses plain fetch(), not fetchWithTimeout
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ data: [] }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await loadTools();
    expect(mockFetch).toHaveBeenCalled();
    consoleSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const toolBody = document.createElement("tbody");
    toolBody.id = "toolBody";
    document.body.appendChild(toolBody);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Network error"))
    );

    await loadTools();
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});

// ---------------------------------------------------------------------------
// enrichTool
// ---------------------------------------------------------------------------
describe("enrichTool", () => {
  test("sends enrich request for tool", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          enriched_desc: "Better description",
          original_desc: "Old desc*extra",
        }),
    });

    await enrichTool("enrich-t1");
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("enrich"),
      expect.any(Object),
      expect.any(Number)
    );
    consoleSpy.mockRestore();
    errorSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Failed"));

    await enrichTool("enrich-err-t1");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// generateToolTestCases
// ---------------------------------------------------------------------------
describe("generateToolTestCases", () => {
  test("opens test case generation modal", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    // generateToolTestCases opens a modal and accesses gen-test-tool-id element
    const genEl = document.createElement("div");
    genEl.id = "gen-test-tool-id";
    document.body.appendChild(genEl);

    await generateToolTestCases("gen-t1");
    expect(openModal).toHaveBeenCalledWith("testcase-gen-modal");
    consoleSpy.mockRestore();
    errorSpy.mockRestore();
  });

  test("handles error when DOM elements are missing", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    // Without gen-test-tool-id, it will throw and catch
    await generateToolTestCases("gen-err-t1");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// validateTool
// ---------------------------------------------------------------------------
describe("validateTool", () => {
  test("sends validate request for tool", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ valid: true }),
    });

    await validateTool("val-t1");
    expect(fetchWithTimeout).toHaveBeenCalled();
    consoleSpy.mockRestore();
    errorSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Failed"));

    await validateTool("val-err-t1");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// cleanupToolTestState
// ---------------------------------------------------------------------------
describe("cleanupToolTestState", () => {
  test("does not throw", () => {
    expect(() => cleanupToolTestState()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// cleanupToolTestModal
// ---------------------------------------------------------------------------
describe("cleanupToolTestModal", () => {
  test("clears test form and result", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const form = document.createElement("form");
    form.id = "tool-test-form";
    document.body.appendChild(form);

    const result = document.createElement("div");
    result.id = "tool-test-result";
    result.innerHTML = "<div>results</div>";
    document.body.appendChild(result);

    const loading = document.createElement("div");
    loading.id = "tool-test-loading";
    document.body.appendChild(loading);

    cleanupToolTestModal();
    expect(result.innerHTML).toBe("");
    expect(loading.style.display).toBe("none");
    consoleSpy.mockRestore();
  });

  test("does nothing when elements are missing", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(() => cleanupToolTestModal()).not.toThrow();
    consoleSpy.mockRestore();
  });
});
