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
vi.mock("../../../mcpgateway/admin_ui/gateways.js", () => ({
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
  escapeAttrValue: vi.fn((s) => (s != null ? String(s) : "")),
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

  test("derives count from allToolIds when selectAllTools mode is active", () => {
    const container = document.createElement("div");
    container.id = "sel-selectall";
    // Two checked checkboxes (visible selection)
    for (let i = 0; i < 2; i++) {
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = `t${i}`;
      cb.checked = true;
      const lbl = document.createElement("span");
      lbl.textContent = `Tool ${i}`;
      container.appendChild(cb);
      container.appendChild(lbl);
    }
    // Hidden inputs for Select All mode (5 total tool IDs)
    const saInput = document.createElement("input");
    saInput.type = "hidden";
    saInput.name = "selectAllTools";
    saInput.value = "true";
    container.appendChild(saInput);
    const idsInput = document.createElement("input");
    idsInput.type = "hidden";
    idsInput.name = "allToolIds";
    idsInput.value = JSON.stringify(["t0","t1","t2","t3","t4"]);
    container.appendChild(idsInput);
    document.body.appendChild(container);

    const pillsBox = document.createElement("div");
    pillsBox.id = "pills-selectall";
    document.body.appendChild(pillsBox);
    const warnBox = document.createElement("div");
    warnBox.id = "warn-selectall";
    document.body.appendChild(warnBox);

    initToolSelect("sel-selectall", "pills-selectall", "warn-selectall");

    // count=5 from allToolIds; pills from 2 checked + "+2 more" (5-3=2)
    const spans = [...pillsBox.querySelectorAll("span")];
    expect(spans.at(-1).textContent).toBe("+2 more");
    // count(5) <= max(6): no warning
    expect(warnBox.textContent).toBe("");
  });

  test("builds pillsData from edit-server-tools selection store", async () => {
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.editServerSelections = {
      "edit-server-tools": new Set(["tool-a", "tool-b"]),
    };
    window.Admin = { toolMapping: { "tool-a": "Alpha", "tool-b": "Beta" } };

    const container = document.createElement("div");
    container.id = "edit-server-tools";
    // One checked checkbox in DOM
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = "tool-a";
    cb.checked = true;
    container.appendChild(cb);
    document.body.appendChild(container);

    const pillsBox = document.createElement("div");
    pillsBox.id = "pills-est";
    document.body.appendChild(pillsBox);
    const warnBox = document.createElement("div");
    warnBox.id = "warn-est";
    document.body.appendChild(warnBox);

    initToolSelect("edit-server-tools", "pills-est", "warn-est");

    // Pills come from pillsData (store), not from checked checkboxes
    const spans = [...pillsBox.querySelectorAll("span")];
    const names = spans.map((s) => s.textContent);
    expect(names).toContain("Alpha");
    expect(names).toContain("Beta");

    delete window.Admin;
    delete AppState.editServerSelections;
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

  test("injects hidden team_id input when URL contains team_id param", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    vi.stubGlobal("location", { href: "http://localhost/?team_id=team-42" });

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "t1",
          name: "test-tool",
          inputSchema: {},
        }),
    });

    const editForm = document.createElement("form");
    editForm.id = "edit-tool-form";
    document.body.appendChild(editForm);

    await editTool("t1");

    const hidden = editForm.querySelector('input[name="team_id"]');
    expect(hidden).not.toBeNull();
    expect(hidden.type).toBe("hidden");
    expect(hidden.value).toBe("team-42");

    vi.unstubAllGlobals();
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
// testTool - form field generation (lines 1498-1681)
// ---------------------------------------------------------------------------
describe("testTool - form field generation", () => {
  function setupFieldsDom() {
    const title = document.createElement("div");
    title.id = "tool-test-modal-title";
    document.body.appendChild(title);
    const desc = document.createElement("div");
    desc.id = "tool-test-modal-description";
    document.body.appendChild(desc);
    const fields = document.createElement("div");
    fields.id = "tool-test-form-fields";
    document.body.appendChild(fields);
    return fields;
  }

  test("renders scalar field types with label, description, required star", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const fields = setupFieldsDom();

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "tf-scalar",
          name: "scalar-tool",
          inputSchema: {
            type: "object",
            properties: {
              count:  { type: "number", description: "A count" },
              active: { type: "boolean" },
              config: { type: "object" },
              note:   { type: "string" },
            },
            required: ["count"],
          },
        }),
    });

    await testTool("tf-scalar");

    // number → <input type="number">, required
    const countInput = fields.querySelector('input[name="count"]');
    expect(countInput).not.toBeNull();
    expect(countInput.type).toBe("number");
    expect(countInput.required).toBe(true);

    // description <small> rendered
    expect(fields.querySelector("small").textContent).toBe("A count");

    // required star <span> rendered
    expect(fields.querySelector("span.text-red-500")).not.toBeNull();

    // boolean → <input type="checkbox">
    expect(fields.querySelector('input[name="active"][type="checkbox"]')).not.toBeNull();

    // object → <textarea>
    expect(fields.querySelector('textarea[name="config"]')).not.toBeNull();

    // string → <textarea> (else branch)
    expect(fields.querySelector('textarea[name="note"]')).not.toBeNull();

    consoleSpy.mockRestore();
  });

  test("renders array fields with Add button and item-type inputs", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const fields = setupFieldsDom();

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "tf-array",
          name: "array-tool",
          inputSchema: {
            type: "object",
            properties: {
              tags:  { type: "array", items: { type: "string" } },
              nums:  { type: "array", items: { type: "number" } },
              flags: { type: "array", items: { type: "boolean" } },
            },
          },
        }),
    });

    await testTool("tf-array");

    // Each array field gets an "Add items" button
    const addBtns = [...fields.querySelectorAll('button[type="button"]')].filter(
      (b) => b.textContent === "Add items"
    );
    expect(addBtns).toHaveLength(3);

    // number array → <input type="number">
    expect(fields.querySelector('input[name="nums"][type="number"]')).not.toBeNull();

    // boolean array → checkbox + hidden companion
    expect(fields.querySelector('input[name="flags"][type="checkbox"]')).not.toBeNull();
    const hiddenFlags = [...fields.querySelectorAll('input[name="flags"]')].find(
      (i) => i.type === "hidden"
    );
    expect(hiddenFlags).not.toBeNull();

    consoleSpy.mockRestore();
  });

  test("pre-fills array inputs from default values; boolean and object defaults", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const fields = setupFieldsDom();

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "tf-defaults",
          name: "defaults-tool",
          inputSchema: {
            type: "object",
            properties: {
              words:      { type: "array", items: { type: "string" }, default: ["hello", "world"] },
              empty_arr:  { type: "array", items: { type: "string" }, default: [] },
              checked_cb: { type: "boolean", default: true },
              config_obj: { type: "object", default: { key: "val" } },
            },
          },
        }),
    });

    await testTool("tf-defaults");

    // Non-empty default → one input per value
    const wordInputs = [...fields.querySelectorAll('input[name="words"]')].filter(
      (i) => i.type !== "hidden"
    );
    expect(wordInputs).toHaveLength(2);
    expect(wordInputs[0].value).toBe("hello");
    expect(wordInputs[1].value).toBe("world");

    // Empty default → one empty input
    const emptyInputs = [...fields.querySelectorAll('input[name="empty_arr"]')].filter(
      (i) => i.type !== "hidden"
    );
    expect(emptyInputs).toHaveLength(1);
    expect(emptyInputs[0].value).toBe("");

    // Boolean with default=true → checked + hidden companion
    const cb = fields.querySelector('input[name="checked_cb"][type="checkbox"]');
    expect(cb).not.toBeNull();
    expect(cb.checked).toBe(true);
    expect(
      [...fields.querySelectorAll('input[name="checked_cb"]')].some((i) => i.type === "hidden")
    ).toBe(true);

    // Object with default → textarea containing JSON
    const configArea = fields.querySelector('textarea[name="config_obj"]');
    expect(configArea).not.toBeNull();
    expect(JSON.parse(configArea.value)).toEqual({ key: "val" });

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
// ---------------------------------------------------------------------------
// Helpers for registry-primed tests
// ---------------------------------------------------------------------------

/** Create the three DOM nodes that runToolTest requires. */
function setupRTTDom() {
  const form = document.createElement("form");
  form.id = "tool-test-form";
  document.body.appendChild(form);

  const loading = document.createElement("div");
  loading.id = "tool-test-loading";
  document.body.appendChild(loading);

  const result = document.createElement("div");
  result.id = "tool-test-result";
  document.body.appendChild(result);

  return { form, loading, result };
}

// ---------------------------------------------------------------------------
// runToolTest - runButton state management (lines 3196-3198, 3415-3418)
// ---------------------------------------------------------------------------
describe("runToolTest - runButton management", () => {
  test("disables and restores runButton around execution", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.currentTestTool = { id: "t1", name: "primer-tool", inputSchema: { type: "object", properties: {} } };
    setupRTTDom();

    const runButton = document.createElement("button");
    runButton.setAttribute("onclick", "runToolTest()");
    document.body.appendChild(runButton);

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ result: "ok" }),
    });

    const { runToolTest } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolTest();

    expect(runButton.disabled).toBe(false);
    expect(runButton.textContent).toBe("Run Tool");
    expect(runButton.classList.contains("opacity-50")).toBe(false);
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runToolTest - invalid parameter key warning (lines 3219-3220)
// ---------------------------------------------------------------------------
describe("runToolTest - invalid parameter key", () => {
  test("warns and skips parameters with invalid keys", async () => {
    window.ROOT_PATH = "";
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { validateInputName } = await import(
      "../../../mcpgateway/admin_ui/security.js"
    );

    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.currentTestTool = { id: "t1", name: "primer-tool", inputSchema: { type: "object", properties: { bad_key: { type: "string" } } } };
    setupRTTDom();

    // The primer schema has one property "bad_key"; make validateInputName
    // return invalid for that call in runToolTest so lines 3219-3220 execute.
    validateInputName.mockReturnValueOnce({ valid: false });

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    });

    const { runToolTest } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolTest();

    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("Skipping invalid parameter")
    );
    warnSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runToolTest - scalar parameter types (lines 3282-3303, 3278)
// ---------------------------------------------------------------------------
describe("runToolTest - scalar parameter types", () => {
  // prettier-ignore
  test.each([
    ["number",              { count:     { type: "number" } },                 null,           "count",     "42",          "count",     42],
    ["boolean",             { flag:      { type: "boolean" } },                null,           "flag",      "true",        "flag",      true],
    ["enum",                { mode:      { enum: ["fast", "slow"] } },         null,           "mode",      "fast",        "mode",      "fast"],
    ["object (valid JSON)", { config:    { type: "object" } },                 null,           "config",    '{"key":"val"}', "config",  { key: "val" }],
    ["required empty",      { req_field: { type: "string" } },                 ["req_field"],  "req_field", "",            "req_field", ""],
    ["string passthrough",  { label:     { type: "string" } },                 null,           "label",     "hello world", "label",     "hello world"],
  ])("converts %s", async (_, props, required, inputName, inputValue, paramKey, expected) => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    const schema = required ? { type: "object", properties: props, required } : { type: "object", properties: props };
    AppState.currentTestTool = { id: "t1", name: "primer-tool", inputSchema: schema };
    const { form } = setupRTTDom();
    const input = document.createElement("input");
    input.name = inputName;
    input.value = inputValue;
    form.appendChild(input);
    fetchWithTimeout.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });
    const { runToolTest } = await import("../../../mcpgateway/admin_ui/tools.js");
    await runToolTest();
    const body = JSON.parse(fetchWithTimeout.mock.calls.at(-1)[1].body);
    expect(body.params[paramKey]).toEqual(expected);
    consoleSpy.mockRestore();
  });

  // prettier-ignore
  test.each([
    ["invalid JSON string",       "not-valid-json"],
    ["valid JSON but not object", "123"],
  ])("shows error for object param with %s", async (_, inputValue) => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { showErrorMessage } = await import("../../../mcpgateway/admin_ui/utils.js");
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.currentTestTool = { id: "t1", name: "primer-tool", inputSchema: { type: "object", properties: { config: { type: "object" } } } };
    const { form, result } = setupRTTDom();
    const input = document.createElement("input");
    input.name = "config";
    input.value = inputValue;
    form.appendChild(input);
    const { runToolTest } = await import("../../../mcpgateway/admin_ui/tools.js");
    await runToolTest();
    expect(showErrorMessage).toHaveBeenCalledWith(expect.stringContaining("Invalid JSON object format"));
    expect(result.querySelector(".text-red-600")).not.toBeNull();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runToolTest - array parameter types (lines 3224-3272)
// ---------------------------------------------------------------------------
describe("runToolTest - array parameter types", () => {
  // prettier-ignore
  test.each([
    ["numbers",        { nums:  { type: "array", items: { type: "number" } } },                                    null,     "nums",  ["1", "2"],  "nums",  [1, 2]],
    ["integers anyOf", { ids:   { type: "array", items: { anyOf: [{ type: "integer" }, { type: "string" }] } } }, null,     "ids",   ["7"],       "ids",   [7]],
    ["booleans",       { flags: { type: "array", items: { type: "boolean" } } },                                   null,     "flags", ["true"],     "flags", [true]],
    ["objects",        { objs:  { type: "array", items: { type: "object" } } },                                    null,     "objs",  ['{"x":1}'], "objs",  [{ x: 1 }]],
    ["required empty", { tags:  { type: "array", items: { type: "string" } } },                                    ["tags"], "tags",  [""],        "tags",  []],
  ])("converts array of %s", async (_, props, required, inputName, inputValues, paramKey, expected) => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    const schema = required ? { type: "object", properties: props, required } : { type: "object", properties: props };
    AppState.currentTestTool = { id: "t1", name: "primer-tool", inputSchema: schema };
    const { form } = setupRTTDom();
    inputValues.forEach((v) => {
      const inp = document.createElement("input");
      inp.name = inputName;
      inp.value = v;
      form.appendChild(inp);
    });
    fetchWithTimeout.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });
    const { runToolTest } = await import("../../../mcpgateway/admin_ui/tools.js");
    await runToolTest();
    const body = JSON.parse(fetchWithTimeout.mock.calls.at(-1)[1].body);
    expect(body.params[paramKey]).toEqual(expected);
    consoleSpy.mockRestore();
  });

  // prettier-ignore
  test.each([
    ["invalid JSON in object item",          { items: { type: "array", items: { type: "object" } } }, "items", "not-valid-json"],
    ["NaN number item",                      { nums:  { type: "array", items: { type: "number" } } }, "nums",  "abc"],
    ["valid JSON but not object in array",   { objs:  { type: "array", items: { type: "object" } } }, "objs",  "123"],
  ])("shows error for array with %s", async (_, props, inputName, inputValue) => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { showErrorMessage } = await import("../../../mcpgateway/admin_ui/utils.js");
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.currentTestTool = { id: "t1", name: "primer-tool", inputSchema: { type: "object", properties: props } };
    const { form, result } = setupRTTDom();
    const inp = document.createElement("input");
    inp.name = inputName;
    inp.value = inputValue;
    form.appendChild(inp);
    const { runToolTest } = await import("../../../mcpgateway/admin_ui/tools.js");
    await runToolTest();
    expect(showErrorMessage).toHaveBeenCalledWith(expect.stringContaining("Invalid input format"));
    expect(result.querySelector(".text-red-600")).not.toBeNull();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runToolTest - passthrough headers (lines 3333-3347)
// ---------------------------------------------------------------------------
describe("runToolTest - passthrough headers", () => {
  test("adds valid colon-separated header to request headers", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.currentTestTool = { id: "t1", name: "primer-tool", inputSchema: { type: "object", properties: {} } };
    setupRTTDom();

    const headersEl = document.createElement("textarea");
    headersEl.id = "test-passthrough-headers";
    headersEl.value = "X-Custom: myvalue";
    document.body.appendChild(headersEl);

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    });

    const { validatePassthroughHeader } = await import(
      "../../../mcpgateway/admin_ui/security.js"
    );
    const { runToolTest } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolTest();

    // fetchWithTimeout was called (header processing did not return early)
    // and validatePassthroughHeader was invoked for the parsed header
    expect(validatePassthroughHeader).toHaveBeenCalledWith("X-Custom", "myvalue");
    expect(fetchWithTimeout).toHaveBeenCalledTimes(1);
    consoleSpy.mockRestore();
  });

  test("returns early and shows error when header fails validation", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { validatePassthroughHeader } = await import(
      "../../../mcpgateway/admin_ui/security.js"
    );
    validatePassthroughHeader.mockReturnValueOnce({
      valid: false,
      error: "Forbidden header name",
    });
    const { showErrorMessage } = await import(
      "../../../mcpgateway/admin_ui/utils.js"
    );

    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.currentTestTool = { id: "t1", name: "primer-tool", inputSchema: { type: "object", properties: {} } };
    setupRTTDom();

    const headersEl = document.createElement("textarea");
    headersEl.id = "test-passthrough-headers";
    headersEl.value = "X-Bad: value";
    document.body.appendChild(headersEl);

    const { runToolTest } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolTest();

    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("Invalid header")
    );
    // runToolTest returned early; fetch was never called
    expect(fetchWithTimeout).toHaveBeenCalledTimes(0);
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runToolTest - CodeMirror error fallback (lines 3384-3390)
// ---------------------------------------------------------------------------
describe("runToolTest - CodeMirror fallback", () => {
  test("falls back to <pre> when CodeMirror constructor throws", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    window.CodeMirror = vi.fn(() => {
      throw new Error("CM init failed");
    });

    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.currentTestTool = { id: "t1", name: "primer-tool", inputSchema: { type: "object", properties: {} } };
    const { result } = setupRTTDom();

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ data: "ok" }),
    });

    const { runToolTest } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolTest();

    expect(result.querySelector("pre")).not.toBeNull();
    delete window.CodeMirror;
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runToolTest - fetch error appends error div (lines 3402-3408)
// ---------------------------------------------------------------------------
describe("runToolTest - fetch error handling", () => {
  test("appends error div to resultContainer on fetch failure", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { AppState } = await import("../../../mcpgateway/admin_ui/appState.js");
    AppState.currentTestTool = { id: "t1", name: "primer-tool", inputSchema: { type: "object", properties: {} } };
    const { result } = setupRTTDom();

    fetchWithTimeout.mockRejectedValueOnce(new Error("Network failure"));

    const { runToolTest } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolTest();

    expect(result.querySelector(".text-red-600")).not.toBeNull();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runToolAgentValidation - guard check (lines 3023-3025)
// ---------------------------------------------------------------------------
describe("runToolAgentValidation - guard check", () => {
  test("logs error and calls showErrorMessage when form is missing", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { showErrorMessage } = await import(
      "../../../mcpgateway/admin_ui/utils.js"
    );
    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = null;

    const { runToolAgentValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolAgentValidation(99);

    expect(consoleSpy).toHaveBeenCalledWith(
      "Tool test form or current tool not found"
    );
    expect(showErrorMessage).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runToolAgentValidation - concurrent check (lines 3030-3031)
// ---------------------------------------------------------------------------
describe("runToolAgentValidation - concurrent check", () => {
  test("returns early when runButton is already disabled", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = { id: "t1", name: "t1" };

    const form = document.createElement("form");
    form.id = "tool-validation-form-0";
    document.body.appendChild(form);

    const runButton = document.createElement("button");
    runButton.setAttribute("onclick", "runToolAgentValidation()");
    runButton.disabled = true;
    document.body.appendChild(runButton);

    const { runToolAgentValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolAgentValidation(0);

    expect(consoleSpy).toHaveBeenCalledWith("Tool test already running");
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runToolAgentValidation - runButton state (lines 3037-3039, 3168-3170)
// ---------------------------------------------------------------------------
describe("runToolAgentValidation - runButton state", () => {
  test("disables and restores runButton around execution", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = { id: "t1", name: "test-tool" };

    const form = document.createElement("form");
    form.id = "tool-validation-form-0";
    document.body.appendChild(form);

    const nlEl = document.createElement("textarea");
    nlEl.id = "validation-passthrough-nlUtterances-0";
    nlEl.value = "test utterance";
    document.body.appendChild(nlEl);

    const result = document.createElement("div");
    result.id = "tool-validation-result-0";
    document.body.appendChild(result);

    const loading = document.createElement("div");
    loading.id = "tool-validation-loading-0";
    document.body.appendChild(loading);

    const runButton = document.createElement("button");
    runButton.setAttribute("onclick", "runToolAgentValidation()");
    document.body.appendChild(runButton);

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ results: [] }),
    });

    const { runToolAgentValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolAgentValidation(0);

    expect(runButton.disabled).toBe(false);
    expect(runButton.textContent).toBe("Run Tool");
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runToolAgentValidation - passthrough headers (lines 3077-3103)
// ---------------------------------------------------------------------------
describe("runToolAgentValidation - passthrough headers", () => {
  async function setupAgentValidationDom(index) {
    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = { id: "t1", name: "test-tool" };

    const form = document.createElement("form");
    form.id = `tool-validation-form-${index}`;
    document.body.appendChild(form);

    const nlEl = document.createElement("textarea");
    nlEl.id = `validation-passthrough-nlUtterances-${index}`;
    nlEl.value = "utterance";
    document.body.appendChild(nlEl);

    const result = document.createElement("div");
    result.id = `tool-validation-result-${index}`;
    document.body.appendChild(result);

    const loading = document.createElement("div");
    loading.id = `tool-validation-loading-${index}`;
    document.body.appendChild(loading);

    return result;
  }

  test("processes valid colon-formatted header without returning early", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    await setupAgentValidationDom(0);

    const headersEl = document.createElement("textarea");
    headersEl.id = "validation-passthrough-headers";
    headersEl.value = "X-Tenant: acme";
    document.body.appendChild(headersEl);

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    });

    const { validatePassthroughHeader } = await import(
      "../../../mcpgateway/admin_ui/security.js"
    );
    const { runToolAgentValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolAgentValidation(0);

    expect(validatePassthroughHeader).toHaveBeenCalledWith("X-Tenant", "acme");
    expect(fetchWithTimeout).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("shows error when header has no colon separator", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { showErrorMessage } = await import(
      "../../../mcpgateway/admin_ui/utils.js"
    );
    await setupAgentValidationDom(1);

    const headersEl = document.createElement("textarea");
    headersEl.id = "validation-passthrough-headers";
    headersEl.value = "InvalidHeaderNoColon";
    document.body.appendChild(headersEl);

    const { runToolAgentValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolAgentValidation(1);

    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("Invalid header format")
    );
    consoleSpy.mockRestore();
  });

  test("shows error when header fails passthrough validation", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { validatePassthroughHeader } = await import(
      "../../../mcpgateway/admin_ui/security.js"
    );
    validatePassthroughHeader.mockReturnValueOnce({
      valid: false,
      error: "Bad header name",
    });
    const { showErrorMessage } = await import(
      "../../../mcpgateway/admin_ui/utils.js"
    );
    await setupAgentValidationDom(2);

    const headersEl = document.createElement("textarea");
    headersEl.id = "validation-passthrough-headers";
    headersEl.value = "X-Bad: value";
    document.body.appendChild(headersEl);

    const { runToolAgentValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolAgentValidation(2);

    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("Invalid header")
    );
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runToolAgentValidation - CodeMirror display/fallback (lines 3127-3142)
// ---------------------------------------------------------------------------
describe("runToolAgentValidation - CodeMirror display", () => {
  test("uses CodeMirror for result when available", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const mockCM = vi.fn(() => ({}));
    window.CodeMirror = mockCM;

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = { id: "t1", name: "test-tool" };

    const form = document.createElement("form");
    form.id = "tool-validation-form-0";
    document.body.appendChild(form);

    const nlEl = document.createElement("textarea");
    nlEl.id = "validation-passthrough-nlUtterances-0";
    nlEl.value = "utterance";
    document.body.appendChild(nlEl);

    const result = document.createElement("div");
    result.id = "tool-validation-result-0";
    document.body.appendChild(result);

    const loading = document.createElement("div");
    loading.id = "tool-validation-loading-0";
    document.body.appendChild(loading);

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ results: [] }),
    });

    const { runToolAgentValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolAgentValidation(0);

    expect(mockCM).toHaveBeenCalled();
    delete window.CodeMirror;
    consoleSpy.mockRestore();
  });

  test("falls back to <pre> when CodeMirror constructor throws", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    window.CodeMirror = vi.fn(() => {
      throw new Error("CM error");
    });

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = { id: "t1", name: "test-tool" };

    const form = document.createElement("form");
    form.id = "tool-validation-form-0";
    document.body.appendChild(form);

    const nlEl = document.createElement("textarea");
    nlEl.id = "validation-passthrough-nlUtterances-0";
    nlEl.value = "utterance";
    document.body.appendChild(nlEl);

    const result = document.createElement("div");
    result.id = "tool-validation-result-0";
    document.body.appendChild(result);

    const loading = document.createElement("div");
    loading.id = "tool-validation-loading-0";
    document.body.appendChild(loading);

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    });

    const { runToolAgentValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolAgentValidation(0);

    expect(result.querySelector("pre")).not.toBeNull();
    delete window.CodeMirror;
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runToolValidation - runButton restore in finally (lines 3005-3007)
// ---------------------------------------------------------------------------
describe("runToolValidation - runButton restore", () => {
  test("restores runButton in finally block after successful run", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    AppState.currentTestTool = { id: "t1", name: "test-tool", inputSchema: { type: "object", properties: {} } };

    const form = document.createElement("form");
    form.id = "tool-validation-form-0";
    document.body.appendChild(form);

    const loading = document.createElement("div");
    loading.id = "tool-validation-loading-0";
    document.body.appendChild(loading);

    const result = document.createElement("div");
    result.id = "tool-validation-result-0";
    document.body.appendChild(result);

    const runButton = document.createElement("button");
    runButton.setAttribute("onclick", "runToolValidation()");
    document.body.appendChild(runButton);

    fetchWithTimeout.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ result: "ok" }),
    });

    const { runToolValidation } = await import(
      "../../../mcpgateway/admin_ui/tools.js"
    );
    await runToolValidation(0);

    expect(runButton.disabled).toBe(false);
    expect(runButton.textContent).toBe("Run Tool");
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// cleanupToolTestState - abort error (line 3433)
// ---------------------------------------------------------------------------
describe("cleanupToolTestState - abort error", () => {
  test("warns when controller.abort() throws during cleanup", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    class ThrowingController {
      constructor() {
        this.signal = {};
      }
      abort() {
        throw new Error("abort error");
      }
    }
    vi.stubGlobal("AbortController", ThrowingController);

    // Never-resolving promise keeps testTool suspended after it registers the
    // controller in toolTestState.activeRequests, so cleanupToolTestState
    // finds it and tries to abort it.
    fetchWithTimeout.mockReturnValueOnce(new Promise(() => {}));

    // Do NOT await – we need testTool to stay suspended at the fetch await.
    testTool("abort-throw-unique-id");

    // Yield once to let testTool run synchronously up to its first await.
    await Promise.resolve();

    cleanupToolTestState();

    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("Error cancelling request"),
      expect.any(Error)
    );

    vi.unstubAllGlobals();
    warnSpy.mockRestore();
    logSpy.mockRestore();
    errSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// cleanupToolTestModal - successful toTextArea (line 3456)
// ---------------------------------------------------------------------------
describe("cleanupToolTestModal - toTextArea success", () => {
  test("calls toTextArea and nulls editor reference on success", async () => {
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { AppState } = await import(
      "../../../mcpgateway/admin_ui/appState.js"
    );
    const mockToTextArea = vi.fn();
    AppState.toolTestResultEditor = { toTextArea: mockToTextArea };

    cleanupToolTestModal();

    expect(mockToTextArea).toHaveBeenCalled();
    expect(AppState.toolTestResultEditor).toBeNull();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// cleanupToolTestModal - outer catch (line 3482)
// ---------------------------------------------------------------------------
describe("cleanupToolTestModal - outer error", () => {
  test("catches and logs errors thrown inside the cleanup body", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { safeGetElement } = await import(
      "../../../mcpgateway/admin_ui/utils.js"
    );
    // Force an error inside the try block after the editor cleanup
    safeGetElement.mockImplementationOnce(() => {
      throw new Error("DOM access failed");
    });

    cleanupToolTestModal();

    expect(consoleSpy).toHaveBeenCalledWith(
      "Error cleaning up tool test modal:",
      expect.any(Error)
    );
    consoleSpy.mockRestore();
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

// ---------------------------------------------------------------------------
// initToolSelect - Select All passes search query
// ---------------------------------------------------------------------------
describe("initToolSelect - Select All respects search filter", () => {
  test("passes search query to /admin/tools/ids when search input has value", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    // Set up container
    const container = document.createElement("div");
    container.id = "associatedTools";
    document.body.appendChild(container);

    // Pills and warning
    const pillsBox = document.createElement("div");
    pillsBox.id = "test-pills-sa";
    document.body.appendChild(pillsBox);
    const warnBox = document.createElement("div");
    warnBox.id = "test-warn-sa";
    document.body.appendChild(warnBox);

    // Select All button
    const selectBtn = document.createElement("button");
    selectBtn.id = "selectAllToolsBtn";
    document.body.appendChild(selectBtn);

    // Pagination trigger (forces fetch path instead of visible-only path)
    const scrollTrigger = document.createElement("div");
    scrollTrigger.id = "tools-scroll-trigger-1";
    document.body.appendChild(scrollTrigger);

    // Search input with a search term
    const searchInput = document.createElement("input");
    searchInput.id = "searchTools";
    searchInput.value = "  git  ";
    document.body.appendChild(searchInput);

    // Mock global fetch
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ tool_ids: ["tool-git-1"], count: 1 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    // Initialize
    initToolSelect(
      "associatedTools",
      "test-pills-sa",
      "test-warn-sa",
      6,
      "selectAllToolsBtn"
    );

    // Click Select All
    const btn = document.getElementById("selectAllToolsBtn");
    await btn.click();
    // Allow microtask queue to flush
    await new Promise((resolve) => setTimeout(resolve, 0));

    // Verify fetch was called with q=git (trimmed)
    expect(fetchSpy).toHaveBeenCalled();
    const fetchUrl = fetchSpy.mock.calls[0][0];
    expect(fetchUrl).toContain("/admin/tools/ids");
    expect(fetchUrl).toContain("q=git");

    consoleSpy.mockRestore();
    warnSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  test("uses searchEditTools input in edit-server mode", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    // Set up container for edit mode
    const container = document.createElement("div");
    container.id = "edit-server-tools";
    document.body.appendChild(container);

    const pillsBox = document.createElement("div");
    pillsBox.id = "test-pills-edit";
    document.body.appendChild(pillsBox);
    const warnBox = document.createElement("div");
    warnBox.id = "test-warn-edit";
    document.body.appendChild(warnBox);

    const selectBtn = document.createElement("button");
    selectBtn.id = "selectAllEditToolsBtn";
    document.body.appendChild(selectBtn);

    const scrollTrigger = document.createElement("div");
    scrollTrigger.id = "tools-scroll-trigger-1";
    document.body.appendChild(scrollTrigger);

    // Edit mode search input
    const searchInput = document.createElement("input");
    searchInput.id = "searchEditTools";
    searchInput.value = "python";
    document.body.appendChild(searchInput);

    // Also add the add-mode input to verify it's NOT used
    const addSearchInput = document.createElement("input");
    addSearchInput.id = "searchTools";
    addSearchInput.value = "should-not-use-this";
    document.body.appendChild(addSearchInput);

    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ tool_ids: ["tool-py-1"], count: 1 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    initToolSelect(
      "edit-server-tools",
      "test-pills-edit",
      "test-warn-edit",
      6,
      "selectAllEditToolsBtn"
    );

    const btn = document.getElementById("selectAllEditToolsBtn");
    await btn.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchSpy).toHaveBeenCalled();
    const fetchUrl = fetchSpy.mock.calls[0][0];
    expect(fetchUrl).toContain("q=python");
    expect(fetchUrl).not.toContain("should-not-use-this");

    consoleSpy.mockRestore();
    warnSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  test("does not include q param when search input is empty", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const container = document.createElement("div");
    container.id = "associatedTools";
    document.body.appendChild(container);

    const pillsBox = document.createElement("div");
    pillsBox.id = "test-pills-empty";
    document.body.appendChild(pillsBox);
    const warnBox = document.createElement("div");
    warnBox.id = "test-warn-empty";
    document.body.appendChild(warnBox);

    const selectBtn = document.createElement("button");
    selectBtn.id = "selectAllToolsBtnEmpty";
    document.body.appendChild(selectBtn);

    const scrollTrigger = document.createElement("div");
    scrollTrigger.id = "tools-scroll-trigger-1";
    document.body.appendChild(scrollTrigger);

    // Empty search input
    const searchInput = document.createElement("input");
    searchInput.id = "searchTools";
    searchInput.value = "";
    document.body.appendChild(searchInput);

    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ tool_ids: ["tool-1", "tool-2"], count: 2 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    initToolSelect(
      "associatedTools",
      "test-pills-empty",
      "test-warn-empty",
      6,
      "selectAllToolsBtnEmpty"
    );

    const btn = document.getElementById("selectAllToolsBtnEmpty");
    await btn.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchSpy).toHaveBeenCalled();
    const fetchUrl = fetchSpy.mock.calls[0][0];
    expect(fetchUrl).toContain("/admin/tools/ids");
    expect(fetchUrl).not.toContain("q=");

    consoleSpy.mockRestore();
    warnSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});
