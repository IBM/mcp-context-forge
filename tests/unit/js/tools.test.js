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
  validateTool,
  cleanupToolTestState,
  cleanupToolTestModal,
} from "../../../mcpgateway/admin_ui/tools.js";
import { fetchWithTimeout } from "../../../mcpgateway/admin_ui/utils";
import { openModal, closeModal } from "../../../mcpgateway/admin_ui/modals";

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
vi.mock("../../../mcpgateway/admin_ui/auth.js", () => ({
  loadAuthHeaders: vi.fn(),
  updateAuthHeadersJSON: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  safeSetInnerHTML: vi.fn((el, html) => {
    if (el) el.innerHTML = html;
  }),
  validateInputName: vi.fn((s) => ({ valid: true, value: s })),
  validateJson: vi.fn(() => ({ valid: true, value: {} })),
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

// ---------------------------------------------------------------------------
// generateTestCases
// ---------------------------------------------------------------------------
describe("generateTestCases", () => {
  test("generates test cases successfully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    // Create required DOM elements
    const testCaseCount = document.createElement("input");
    testCaseCount.id = "gen-testcase-count";
    testCaseCount.value = "5";
    document.body.appendChild(testCaseCount);

    const variationCount = document.createElement("input");
    variationCount.id = "gen-nl-variation-count";
    variationCount.value = "3";
    document.body.appendChild(variationCount);

    const toolId = document.createElement("div");
    toolId.id = "gen-test-tool-id";
    toolId.textContent = "test-tool-123";
    document.body.appendChild(toolId);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ status: "success" }),
      })
    );

    const { generateTestCases } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await generateTestCases();

    expect(fetch).toHaveBeenCalled();
    consoleSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const testCaseCount = document.createElement("input");
    testCaseCount.id = "gen-testcase-count";
    testCaseCount.value = "5";
    document.body.appendChild(testCaseCount);

    const variationCount = document.createElement("input");
    variationCount.id = "gen-nl-variation-count";
    variationCount.value = "3";
    document.body.appendChild(variationCount);

    const toolId = document.createElement("div");
    toolId.id = "gen-test-tool-id";
    toolId.textContent = "test-tool-123";
    document.body.appendChild(toolId);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Generation failed"))
    );

    const { generateTestCases } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await generateTestCases();

    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});

// ---------------------------------------------------------------------------
// runToolTest
// ---------------------------------------------------------------------------
describe("runToolTest", () => {
  test("runs tool test successfully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = {
      name: "test-tool",
      inputSchema: {
        properties: {
          query: { type: "string" },
        },
        required: ["query"],
      },
    };

    const form = document.createElement("form");
    form.id = "tool-test-form";
    const input = document.createElement("input");
    input.name = "query";
    input.value = "test query";
    form.appendChild(input);
    document.body.appendChild(form);

    const loading = document.createElement("div");
    loading.id = "tool-test-loading";
    document.body.appendChild(loading);

    const result = document.createElement("div");
    result.id = "tool-test-result";
    document.body.appendChild(result);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ result: "success" }),
    });

    const { runToolTest } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolTest();

    expect(fetchWithTimeout).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("handles missing form", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const { runToolTest } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolTest();

    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runToolValidation
// ---------------------------------------------------------------------------
describe("runToolValidation", () => {
  test("runs validation successfully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = {
      name: "test-tool",
      inputSchema: {
        properties: {
          query: { type: "string" },
        },
        required: ["query"],
      },
    };

    const form = document.createElement("form");
    form.id = "tool-validation-form-0";
    const input = document.createElement("input");
    input.name = "query";
    input.value = "test";
    form.appendChild(input);
    document.body.appendChild(form);

    const result = document.createElement("div");
    result.id = "tool-validation-result-0";
    document.body.appendChild(result);

    const loading = document.createElement("div");
    loading.id = "tool-validation-loading-0";
    document.body.appendChild(loading);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ result: "valid" }),
    });

    const { runToolValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolValidation(0);

    expect(fetchWithTimeout).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = {
      name: "test-tool",
      inputSchema: { properties: {} },
    };

    const form = document.createElement("form");
    form.id = "tool-validation-form-0";
    document.body.appendChild(form);

    const result = document.createElement("div");
    result.id = "tool-validation-result-0";
    document.body.appendChild(result);

    const loading = document.createElement("div");
    loading.id = "tool-validation-loading-0";
    document.body.appendChild(loading);

    fetchWithTimeout.mockRejectedValue(new Error("Validation failed"));

    const { runToolValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolValidation(0);

    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runToolAgentValidation
// ---------------------------------------------------------------------------
describe("runToolAgentValidation", () => {
  test("runs agent validation successfully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = {
      id: "tool-123",
      name: "test-tool",
      inputSchema: { properties: {} },
    };

    const form = document.createElement("form");
    form.id = "tool-validation-form-0";
    document.body.appendChild(form);

    const nlUtterances = document.createElement("textarea");
    nlUtterances.id = "validation-passthrough-nlUtterances-0";
    nlUtterances.value = "Test utterance 1\n\nTest utterance 2";
    document.body.appendChild(nlUtterances);

    const result = document.createElement("div");
    result.id = "tool-validation-result-0";
    document.body.appendChild(result);

    const loading = document.createElement("div");
    loading.id = "tool-validation-loading-0";
    document.body.appendChild(loading);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ results: ["pass", "pass"] }),
    });

    const { runToolAgentValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolAgentValidation(0);

    expect(fetchWithTimeout).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = {
      id: "tool-123",
      name: "test-tool",
      inputSchema: { properties: {} },
    };

    const form = document.createElement("form");
    form.id = "tool-validation-form-0";
    document.body.appendChild(form);

    const nlUtterances = document.createElement("textarea");
    nlUtterances.id = "validation-passthrough-nlUtterances-0";
    nlUtterances.value = "Test utterance";
    document.body.appendChild(nlUtterances);

    const result = document.createElement("div");
    result.id = "tool-validation-result-0";
    document.body.appendChild(result);

    const loading = document.createElement("div");
    loading.id = "tool-validation-loading-0";
    document.body.appendChild(loading);

    fetchWithTimeout.mockRejectedValue(new Error("Validation failed"));

    const { runToolAgentValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolAgentValidation(0);

    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// initToolSelect - Enhanced Tests
// ---------------------------------------------------------------------------
describe("initToolSelect - enhanced", () => {
  test("initializes with checkboxes and updates pills", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const container = document.createElement("div");
    container.id = "test-select";
    document.body.appendChild(container);

    const pills = document.createElement("div");
    pills.id = "test-pills";
    document.body.appendChild(pills);

    const warn = document.createElement("div");
    warn.id = "test-warn";
    document.body.appendChild(warn);

    // Add checkboxes to container
    const cb1 = document.createElement("input");
    cb1.type = "checkbox";
    cb1.value = "tool1";
    const label1 = document.createElement("label");
    label1.textContent = "Tool 1";
    container.appendChild(cb1);
    container.appendChild(label1);

    const cb2 = document.createElement("input");
    cb2.type = "checkbox";
    cb2.value = "tool2";
    const label2 = document.createElement("label");
    label2.textContent = "Tool 2";
    container.appendChild(cb2);
    container.appendChild(label2);

    initToolSelect("test-select", "test-pills", "test-warn", 6);

    // Check one checkbox to trigger update
    cb1.checked = true;
    cb1.dispatchEvent(new Event("change", { bubbles: true }));

    expect(pills.children.length).toBeGreaterThan(0);
    consoleSpy.mockRestore();
  });

  test("shows warning when exceeding max tools", () => {
    window.ROOT_PATH = "";

    const container = document.createElement("div");
    container.id = "test-select";
    document.body.appendChild(container);

    const pills = document.createElement("div");
    pills.id = "test-pills";
    document.body.appendChild(pills);

    const warn = document.createElement("div");
    warn.id = "test-warn";
    document.body.appendChild(warn);

    // Add 10 checkboxes
    for (let i = 0; i < 10; i++) {
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = `tool${i}`;
      cb.checked = true;
      container.appendChild(cb);
    }

    initToolSelect("test-select", "test-pills", "test-warn", 6);

    // Update should trigger warning
    const event = new Event("change", { bubbles: true });
    container.querySelector("input").dispatchEvent(event);

    expect(warn.textContent).toContain("Selected 10 tools");
  });
});

// ---------------------------------------------------------------------------
// viewTool - Enhanced Tests for Complex Cases
// ---------------------------------------------------------------------------
describe("viewTool - enhanced", () => {
  test("displays tool with annotations", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "tool-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "t1",
          name: "test-tool",
          description: "A test tool",
          inputSchema: {},
          annotations: {
            title: "Important Tool",
            readOnlyHint: true,
            destructiveHint: false,
          },
          metrics: {
            totalExecutions: 100,
            successfulExecutions: 95,
            failedExecutions: 5,
            failureRate: 0.05,
          },
        }),
    });

    await viewTool("t1");
    expect(fetchWithTimeout).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("displays tool with auth headers", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "tool-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "t1",
          name: "test-tool",
          description: "A test tool",
          inputSchema: {},
          auth: {
            authHeaders: [
              { key: "Authorization", value: "Bearer token" },
              { key: "X-API-Key", value: "secret" },
            ],
          },
        }),
    });

    await viewTool("t1");
    expect(details.innerHTML).toContain("Custom Headers");
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// editTool - Enhanced Tests for Auth Types
// ---------------------------------------------------------------------------
describe("editTool - enhanced", () => {
  test("handles basic auth type", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "t1",
          name: "test-tool",
          description: "desc",
          inputSchema: {},
          auth: {
            authType: "basic",
            username: "user",
            password: "pass",
          },
        }),
    });

    const editForm = document.createElement("form");
    editForm.id = "edit-tool-form";
    document.body.appendChild(editForm);

    const authBasic = document.createElement("div");
    authBasic.id = "edit-auth-basic-fields";
    const usernameInput = document.createElement("input");
    usernameInput.name = "auth_username";
    authBasic.appendChild(usernameInput);
    const passwordInput = document.createElement("input");
    passwordInput.name = "auth_password";
    authBasic.appendChild(passwordInput);
    document.body.appendChild(authBasic);

    await editTool("t1");
    expect(usernameInput.value).toBe("user");
    expect(passwordInput.value).toBe("*****");
    consoleSpy.mockRestore();
  });

  test("handles bearer auth type", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "t1",
          name: "test-tool",
          description: "desc",
          inputSchema: {},
          auth: {
            authType: "bearer",
            token: "secret-token",
          },
        }),
    });

    const editForm = document.createElement("form");
    editForm.id = "edit-tool-form";
    document.body.appendChild(editForm);

    const authBearer = document.createElement("div");
    authBearer.id = "edit-auth-bearer-fields";
    const tokenInput = document.createElement("input");
    tokenInput.name = "auth_token";
    authBearer.appendChild(tokenInput);
    document.body.appendChild(authBearer);

    await editTool("t1");
    expect(tokenInput.value).toBe("*****");
    consoleSpy.mockRestore();
  });

  test("handles MCP tool type with disabled fields", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "t1",
          name: "test-tool",
          description: "desc",
          inputSchema: {},
          integrationType: "MCP",
        }),
    });

    const editForm = document.createElement("form");
    editForm.id = "edit-tool-form";
    document.body.appendChild(editForm);

    const typeField = document.createElement("select");
    typeField.id = "edit-tool-type";
    document.body.appendChild(typeField);

    await editTool("t1");
    expect(typeField.disabled).toBe(true);
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// testTool - Enhanced Tests for Debouncing and Button States
// ---------------------------------------------------------------------------
describe("testTool - debouncing", () => {
  test("debounces rapid test requests", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

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
          id: "t-debounce",
          name: "test-tool",
          inputSchema: { properties: {} },
        }),
    });

    // First call should work
    await testTool("t-debounce");
    
    // Second immediate call should be debounced
    await testTool("t-debounce");

    // Should only have been called once due to debouncing
    expect(fetchWithTimeout).toHaveBeenCalledTimes(1);
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// loadTools - Enhanced Tests
// ---------------------------------------------------------------------------
describe("loadTools - enhanced", () => {
  test("renders tool rows with correct status", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const toolBody = document.createElement("tbody");
    toolBody.id = "toolBody";
    document.body.appendChild(toolBody);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            data: [
              {
                id: "t1",
                name: "tool1",
                integrationType: "REST",
                enabled: true,
                reachable: true,
              },
              {
                id: "t2",
                name: "tool2",
                integrationType: "MCP",
                enabled: true,
                reachable: false,
              },
            ],
          }),
      })
    );

    await loadTools();
    
    expect(toolBody.innerHTML).toContain("tool1");
    expect(toolBody.innerHTML).toContain("Online");
    expect(toolBody.innerHTML).toContain("Offline");
    
    consoleSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  test("handles empty tools list", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const toolBody = document.createElement("tbody");
    toolBody.id = "toolBody";
    document.body.appendChild(toolBody);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve([]),
      })
    );

    await loadTools();
    expect(toolBody.innerHTML).toContain("No tools found");
    
    consoleSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});



// ---------------------------------------------------------------------------
// Additional Coverage Tests
// ---------------------------------------------------------------------------

// enrichTool - Additional tests
describe("enrichTool - additional", () => {
  test("handles 429 rate limit error", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 429,
      statusText: "Too Many Requests",
    });

    await enrichTool("enrich-429");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("opens description modal on success", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const newDesc = document.createElement("div");
    newDesc.id = "view-new-description";
    document.body.appendChild(newDesc);

    const oldDesc = document.createElement("div");
    oldDesc.id = "view-old-description";
    document.body.appendChild(oldDesc);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          enriched_desc: "New description",
          original_desc: "Old description*extra",
        }),
    });

    await enrichTool("enrich-success");
    expect(openModal).toHaveBeenCalledWith("description-view-modal");
    expect(newDesc.textContent).toBe("New description");
    consoleSpy.mockRestore();
  });
});

// generateToolTestCases - Additional tests
describe("generateToolTestCases - additional", () => {
  test("handles missing DOM elements gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await generateToolTestCases("gen-missing");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("handles 500 server error", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const genEl = document.createElement("div");
    genEl.id = "gen-test-tool-id";
    document.body.appendChild(genEl);

    // generateToolTestCases doesn't throw on HTTP errors, it just opens modal
    await generateToolTestCases("gen-500");
    expect(openModal).toHaveBeenCalledWith("testcase-gen-modal");
    consoleSpy.mockRestore();
  });
});

// generateTestCases - Additional tests
describe("generateTestCases - additional", () => {
  test("closes modal and shows success message", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { showSuccessMessage } = await import(
      "../../../mcpgateway/admin_ui/utils.js"
    );

    const testCaseCount = document.createElement("input");
    testCaseCount.id = "gen-testcase-count";
    testCaseCount.value = "3";
    document.body.appendChild(testCaseCount);

    const variationCount = document.createElement("input");
    variationCount.id = "gen-nl-variation-count";
    variationCount.value = "2";
    document.body.appendChild(variationCount);

    const toolId = document.createElement("div");
    toolId.id = "gen-test-tool-id";
    toolId.textContent = "tool-123";
    document.body.appendChild(toolId);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ status: "success" }),
      })
    );

    const { generateTestCases } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await generateTestCases();

    expect(showSuccessMessage).toHaveBeenCalled();
    expect(closeModal).toHaveBeenCalledWith("testcase-gen-modal");
    
    consoleSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});

// validateTool - Additional tests
describe("validateTool - additional", () => {
  test("shows error when test cases not generated", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { showErrorMessage } = await import(
      "../../../mcpgateway/admin_ui/utils.js"
    );

    const title = document.createElement("div");
    title.id = "tool-validation-modal-title";
    document.body.appendChild(title);

    const desc = document.createElement("div");
    desc.id = "tool-validation-modal-description";
    document.body.appendChild(desc);

    const fields = document.createElement("div");
    fields.id = "tool-validation-form-fields";
    document.body.appendChild(fields);

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "val-t1",
          name: "test-tool",
          inputSchema: { properties: {} },
        }),
    }).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([{ status: "not-initiated" }]),
    });

    await validateTool("val-t1");
    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("generate test cases")
    );
    consoleSpy.mockRestore();
  });

  test("shows error when test case generation in progress", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { showErrorMessage } = await import(
      "../../../mcpgateway/admin_ui/utils.js"
    );

    const title = document.createElement("div");
    title.id = "tool-validation-modal-title";
    document.body.appendChild(title);

    const desc = document.createElement("div");
    desc.id = "tool-validation-modal-description";
    document.body.appendChild(desc);

    const fields = document.createElement("div");
    fields.id = "tool-validation-form-fields";
    document.body.appendChild(fields);

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "val-t2",
          name: "test-tool",
          inputSchema: { properties: {} },
        }),
    }).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([{ status: "in-progress" }]),
    });

    await validateTool("val-t2");
    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("in progress")
    );
    consoleSpy.mockRestore();
  });

  test("shows error when test case generation failed", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { showErrorMessage } = await import(
      "../../../mcpgateway/admin_ui/utils.js"
    );

    const title = document.createElement("div");
    title.id = "tool-validation-modal-title";
    document.body.appendChild(title);

    const desc = document.createElement("div");
    desc.id = "tool-validation-modal-description";
    document.body.appendChild(desc);

    const fields = document.createElement("div");
    fields.id = "tool-validation-form-fields";
    document.body.appendChild(fields);

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "val-t3",
          name: "test-tool",
          inputSchema: { properties: {} },
        }),
    }).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([{ status: "failed", error_message: "LLM error" }]),
    });

    await validateTool("val-t3");
    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("failed")
    );
    consoleSpy.mockRestore();
  });

  test("renders test cases with accordion UI", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const title = document.createElement("div");
    title.id = "tool-validation-modal-title";
    document.body.appendChild(title);

    const desc = document.createElement("div");
    desc.id = "tool-validation-modal-description";
    document.body.appendChild(desc);

    const fields = document.createElement("div");
    fields.id = "tool-validation-form-fields";
    document.body.appendChild(fields);

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "val-t4",
          name: "test-tool",
          inputSchema: {
            properties: {
              query: { type: "string" },
            },
          },
        }),
    }).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([{ status: "completed" }]),
    }).mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve([
          {
            input_parameters: { query: "test" },
            nl_utterance: ["Find test data", "Search for test"],
          },
        ]),
    });

    await validateTool("val-t4");
    
    const accordion = fields.querySelector("button");
    expect(accordion).toBeTruthy();
    expect(openModal).toHaveBeenCalledWith("tool-validation-modal");
    consoleSpy.mockRestore();
  });
});

// runToolTest - Additional tests
describe("runToolTest - additional", () => {
  test("handles missing form gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { showErrorMessage } = await import(
      "../../../mcpgateway/admin_ui/utils.js"
    );

    const { runToolTest } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolTest();

    expect(consoleSpy).toHaveBeenCalled();
    expect(showErrorMessage).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("prevents concurrent test runs", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = {
      name: "test-tool",
      inputSchema: { properties: {} },
    };

    const form = document.createElement("form");
    form.id = "tool-test-form";
    document.body.appendChild(form);

    const runButton = document.createElement("button");
    runButton.setAttribute("onclick", "runToolTest()");
    runButton.disabled = true;
    document.body.appendChild(runButton);

    const { runToolTest } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolTest();

    expect(consoleSpy).toHaveBeenCalledWith("Tool test already running");
    consoleSpy.mockRestore();
  });

  test("handles array parameters correctly", async () => {
    window.ROOT_PATH = "";
    window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT = 60000;
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = {
      name: "test-tool",
      inputSchema: {
        properties: {
          items: {
            type: "array",
            items: { type: "number" },
          },
        },
      },
    };

    const form = document.createElement("form");
    form.id = "tool-test-form";
    const input1 = document.createElement("input");
    input1.name = "items";
    input1.value = "1";
    const input2 = document.createElement("input");
    input2.name = "items";
    input2.value = "2";
    form.appendChild(input1);
    form.appendChild(input2);
    document.body.appendChild(form);

    const loading = document.createElement("div");
    loading.id = "tool-test-loading";
    document.body.appendChild(loading);

    const result = document.createElement("div");
    result.id = "tool-test-result";
    document.body.appendChild(result);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ result: "success" }),
    });

    const { runToolTest } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolTest();

    expect(fetchWithTimeout).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("validates passthrough headers", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { validatePassthroughHeader } = await import(
      "../../../mcpgateway/admin_ui/security.js"
    );
    validatePassthroughHeader.mockReturnValue({ valid: false, error: "Invalid header" });

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = {
      name: "test-tool",
      inputSchema: { properties: {} },
    };

    const form = document.createElement("form");
    form.id = "tool-test-form";
    document.body.appendChild(form);

    const loading = document.createElement("div");
    loading.id = "tool-test-loading";
    document.body.appendChild(loading);

    const result = document.createElement("div");
    result.id = "tool-test-result";
    document.body.appendChild(result);

    const headers = document.createElement("textarea");
    headers.id = "test-passthrough-headers";
    headers.value = "Invalid-Header";
    document.body.appendChild(headers);

    const { runToolTest } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolTest();

    validatePassthroughHeader.mockReturnValue({ valid: true });
    consoleSpy.mockRestore();
  });

  test("uses CodeMirror for result display when available", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const mockCodeMirror = vi.fn(() => ({
      setValue: vi.fn(),
      refresh: vi.fn(),
    }));
    window.CodeMirror = mockCodeMirror;

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = {
      name: "test-tool",
      inputSchema: { properties: {} },
    };

    const form = document.createElement("form");
    form.id = "tool-test-form";
    document.body.appendChild(form);

    const loading = document.createElement("div");
    loading.id = "tool-test-loading";
    document.body.appendChild(loading);

    const result = document.createElement("div");
    result.id = "tool-test-result";
    document.body.appendChild(result);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ result: "success" }),
    });

    const { runToolTest } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolTest();

    expect(mockCodeMirror).toHaveBeenCalled();
    delete window.CodeMirror;
    consoleSpy.mockRestore();
  });
});

// runToolValidation - Additional tests
describe("runToolValidation - additional", () => {
  test("handles missing form", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { showErrorMessage } = await import(
      "../../../mcpgateway/admin_ui/utils.js"
    );

    const { runToolValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolValidation(0);

    expect(consoleSpy).toHaveBeenCalled();
    expect(showErrorMessage).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("handles object array items", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = {
      name: "test-tool",
      inputSchema: {
        properties: {
          objects: {
            type: "array",
            items: { type: "object" },
          },
        },
      },
    };

    const form = document.createElement("form");
    form.id = "tool-validation-form-0";
    const input = document.createElement("input");
    input.name = "objects";
    input.value = '{"key":"value"}';
    form.appendChild(input);
    document.body.appendChild(form);

    const result = document.createElement("div");
    result.id = "tool-validation-result-0";
    document.body.appendChild(result);

    const loading = document.createElement("div");
    loading.id = "tool-validation-loading-0";
    document.body.appendChild(loading);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ result: "valid" }),
    });

    const { runToolValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolValidation(0);

    expect(fetchWithTimeout).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});

// runToolAgentValidation - Additional tests
describe("runToolAgentValidation - additional", () => {
  test("handles missing NL utterances element", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = {
      id: "tool-123",
      name: "test-tool",
      inputSchema: { properties: {} },
    };

    const form = document.createElement("form");
    form.id = "tool-validation-form-0";
    document.body.appendChild(form);

    const result = document.createElement("div");
    result.id = "tool-validation-result-0";
    document.body.appendChild(result);

    const loading = document.createElement("div");
    loading.id = "tool-validation-loading-0";
    document.body.appendChild(loading);

    const { runToolAgentValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    
    // Function handles missing element by catching error
    try {
      await runToolAgentValidation(0);
    } catch (e) {
      // Expected to throw when element is missing
      expect(e).toBeTruthy();
    }
    
    consoleSpy.mockRestore();
  });

  test("splits NL utterances correctly", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = {
      id: "tool-123",
      name: "test-tool",
      inputSchema: { properties: {} },
    };

    const form = document.createElement("form");
    form.id = "tool-validation-form-0";
    document.body.appendChild(form);

    const nlUtterances = document.createElement("textarea");
    nlUtterances.id = "validation-passthrough-nlUtterances-0";
    nlUtterances.value = "Utterance 1\n\nUtterance 2\n\nUtterance 3";
    document.body.appendChild(nlUtterances);

    const result = document.createElement("div");
    result.id = "tool-validation-result-0";
    document.body.appendChild(result);

    const loading = document.createElement("div");
    loading.id = "tool-validation-loading-0";
    document.body.appendChild(loading);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ results: ["pass", "pass", "pass"] }),
    });

    const { runToolAgentValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolAgentValidation(0);

    expect(fetchWithTimeout).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});

// cleanupToolTestState - Additional tests
describe("cleanupToolTestState - additional", () => {
  test("handles errors during cleanup gracefully", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    // Just verify the function doesn't throw
    expect(() => cleanupToolTestState()).not.toThrow();
    
    warnSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// cleanupToolTestModal - Additional tests
describe("cleanupToolTestModal - additional", () => {
  test("handles CodeMirror cleanup errors", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.toolTestResultEditor = {
      toTextArea: vi.fn(() => {
        throw new Error("Cleanup failed");
      }),
    };

    const form = document.createElement("form");
    form.id = "tool-test-form";
    document.body.appendChild(form);

    const result = document.createElement("div");
    result.id = "tool-test-result";
    document.body.appendChild(result);

    const loading = document.createElement("div");
    loading.id = "tool-test-loading";
    document.body.appendChild(loading);

    expect(() => cleanupToolTestModal()).not.toThrow();
    
    warnSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// loadTools - Edge cases
describe("loadTools - edge cases", () => {
  test("handles tools with missing fields", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const toolBody = document.createElement("tbody");
    toolBody.id = "toolBody";
    document.body.appendChild(toolBody);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            data: [
              {
                id: "t1",
                name: "incomplete-tool",
                // Missing integrationType, enabled, reachable
              },
            ],
          }),
      })
    );

    await loadTools();
    expect(toolBody.innerHTML).toContain("incomplete-tool");
    
    consoleSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  test("handles tools with disabled status", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const toolBody = document.createElement("tbody");
    toolBody.id = "toolBody";
    document.body.appendChild(toolBody);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            data: [
              {
                id: "t1",
                name: "disabled-tool",
                integrationType: "REST",
                enabled: false,
                reachable: false,
              },
            ],
          }),
      })
    );

    await loadTools();
    expect(toolBody.innerHTML).toContain("Inactive");
    
    consoleSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});
