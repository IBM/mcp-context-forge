/**
 * Unit tests for prompts.js module
 * Tests: viewPrompt, editPrompt, initPromptSelect, testPrompt,
 *        buildPromptTestForm, runPromptTest, cleanupPromptTestModal
 */

import { describe, test, expect, vi, afterEach } from "vitest";

vi.mock("../../../mcpgateway/admin_ui/appState.js", () => ({
  AppState: {
    parameterCount: 0,
    getParameterCount: () => 0,
    isModalActive: vi.fn(() => false),
  },
}));
vi.mock("../../../mcpgateway/admin_ui/gateway.js", () => ({
  getSelectedGatewayIds: vi.fn(() => []),
}));
vi.mock("../../../mcpgateway/admin_ui/modals", () => ({
  openModal: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  validateInputName: vi.fn((s) => ({ valid: true, value: s })),
  validateJson: vi.fn((s) => ({ valid: true })),
}));
vi.mock("../../../mcpgateway/admin_ui/utils", () => ({
  decodeHtml: vi.fn((s) => s || ""),
  fetchWithTimeout: vi.fn(),
  getCurrentTeamId: vi.fn(() => null),
  handleFetchError: vi.fn((e) => e.message),
  isInactiveChecked: vi.fn(() => false),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showErrorMessage: vi.fn(),
}));

import {
  viewPrompt,
  editPrompt,
  initPromptSelect,
  testPrompt,
  buildPromptTestForm,
  runPromptTest,
  cleanupPromptTestModal,
} from "../../../mcpgateway/admin_ui/prompts.js";
import { fetchWithTimeout } from "../../../mcpgateway/admin_ui/utils";
import { openModal } from "../../../mcpgateway/admin_ui/modals";

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// viewPrompt
// ---------------------------------------------------------------------------
describe("viewPrompt", () => {
  test("fetches prompt and displays details", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "prompt-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "test-prompt",
          description: "A test prompt",
          arguments: [],
        }),
    });

    await viewPrompt("test-prompt");
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("test-prompt")
    );
    expect(openModal).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("handles fetch error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Network error"));

    await viewPrompt("test-prompt");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });

  test("handles non-ok response", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
    });

    await viewPrompt("missing-prompt");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// editPrompt
// ---------------------------------------------------------------------------
describe("editPrompt", () => {
  test("fetches prompt data for editing", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "p1",
          name: "test-prompt",
          description: "desc",
          arguments: [],
          template: "Hello {name}",
        }),
    });

    // Create edit form elements
    const nameInput = document.createElement("input");
    nameInput.id = "edit-prompt-name";
    document.body.appendChild(nameInput);

    const descInput = document.createElement("textarea");
    descInput.id = "edit-prompt-description";
    document.body.appendChild(descInput);

    const idInput = document.createElement("input");
    idInput.id = "edit-prompt-id";
    document.body.appendChild(idInput);

    await editPrompt("p1");
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("p1")
    );
    consoleSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Failed"));

    await editPrompt("p1");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// initPromptSelect
// ---------------------------------------------------------------------------
describe("initPromptSelect", () => {
  test("returns early when required elements are missing", async () => {
    window.ROOT_PATH = "";
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    // Only container exists, no pillsBox or warnBox => early return
    const container = document.createElement("div");
    container.id = "test-select";
    document.body.appendChild(container);

    await initPromptSelect("test-select", "test-pills", "test-warn");
    // Should not call fetch because it returns early
    expect(fetchWithTimeout).not.toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  test("does nothing when container element is missing", async () => {
    window.ROOT_PATH = "";
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    await initPromptSelect("missing-select", "missing-pills", "missing-warn");
    warnSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// testPrompt
// ---------------------------------------------------------------------------
describe("testPrompt", () => {
  test("fetches prompt and opens test modal", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    // Create required DOM elements
    const fieldsContainer = document.createElement("div");
    fieldsContainer.id = "prompt-test-form-fields";
    document.body.appendChild(fieldsContainer);

    const title = document.createElement("div");
    title.id = "prompt-test-modal-title";
    document.body.appendChild(title);

    const desc = document.createElement("div");
    desc.id = "prompt-test-modal-description";
    document.body.appendChild(desc);

    // testPrompt uses plain fetch(), not fetchWithTimeout
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "test-prompt",
          description: "Test",
          arguments: [
            { name: "arg1", description: "An argument", required: true },
          ],
        }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await testPrompt("test-prompt");
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("test-prompt"),
      expect.any(Object)
    );
    consoleSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Fetch failed"))
    );

    // Use unique ID to avoid debounce from previous test
    await testPrompt("test-prompt-err");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});

// ---------------------------------------------------------------------------
// buildPromptTestForm
// ---------------------------------------------------------------------------
describe("buildPromptTestForm", () => {
  test("creates form for prompt with arguments", () => {
    const container = document.createElement("div");
    container.id = "prompt-test-form-fields";
    document.body.appendChild(container);

    const prompt = {
      name: "test-prompt",
      description: "A test prompt",
      arguments: [
        { name: "query", description: "Search query", required: true },
        { name: "limit", description: "Result limit", required: false },
      ],
    };

    buildPromptTestForm(prompt);
    expect(container.innerHTML).toContain("query");
  });

  test("handles prompt with no arguments", () => {
    const container = document.createElement("div");
    container.id = "prompt-test-form-fields";
    document.body.appendChild(container);

    buildPromptTestForm({ name: "simple", arguments: [] });
    expect(container.innerHTML).toContain("no arguments");
  });

  test("does nothing when container is missing", () => {
    const errorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    buildPromptTestForm({ name: "test", arguments: [] });
    errorSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runPromptTest
// ---------------------------------------------------------------------------
describe("runPromptTest", () => {
  test("handles missing prompt state", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    window.ROOT_PATH = "";

    await runPromptTest();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// cleanupPromptTestModal
// ---------------------------------------------------------------------------
describe("cleanupPromptTestModal", () => {
  test("clears test form fields and result", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const form = document.createElement("form");
    form.id = "prompt-test-form";
    document.body.appendChild(form);

    const fields = document.createElement("div");
    fields.id = "prompt-test-form-fields";
    fields.innerHTML = "<div>test content</div>";
    document.body.appendChild(fields);

    const result = document.createElement("div");
    result.id = "prompt-test-result";
    result.innerHTML = "<div>results</div>";
    document.body.appendChild(result);

    cleanupPromptTestModal();
    expect(fields.innerHTML).toBe("");
    // Result gets a placeholder, not empty
    expect(result.innerHTML).toContain("Render Prompt");
    consoleSpy.mockRestore();
  });

  test("does nothing when elements are missing", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(() => cleanupPromptTestModal()).not.toThrow();
    consoleSpy.mockRestore();
  });
});
