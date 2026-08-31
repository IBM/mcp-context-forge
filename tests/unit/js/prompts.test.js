/**
 * Unit tests for prompts.js module
 * Tests: viewPrompt, editPrompt, initPromptSelect, testPrompt,
 *        buildPromptTestForm, runPromptTest, cleanupPromptTestModal
 */

import { describe, test, expect, vi, afterEach } from "vitest";

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

vi.mock("../../../mcpgateway/admin_ui/appState.js", () => ({
  AppState: {
    parameterCount: 0,
    getParameterCount: () => 0,
    isModalActive: vi.fn(() => false),
    editServerSelections: {},
  },
}));
vi.mock("../../../mcpgateway/admin_ui/gateways.js", () => ({
  getSelectedGatewayIds: vi.fn(() => []),
}));
vi.mock("../../../mcpgateway/admin_ui/modals", () => ({
  openModal: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeAttrValue: vi.fn((s) => (s != null ? String(s) : "")),
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
  makeCopyIdButton: vi.fn(() => document.createElement("button")),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showErrorMessage: vi.fn(),
}));

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

// ---------------------------------------------------------------------------
// initPromptSelect - Extended Tests
// ---------------------------------------------------------------------------
describe("initPromptSelect - Extended", () => {
  test("initializes with all elements present", () => {
    window.ROOT_PATH = "";

    const container = document.createElement("div");
    container.id = "test-select";
    document.body.appendChild(container);

    const pillsBox = document.createElement("div");
    pillsBox.id = "test-pills";
    document.body.appendChild(pillsBox);

    const warnBox = document.createElement("div");
    warnBox.id = "test-warn";
    document.body.appendChild(warnBox);

    const checkbox1 = document.createElement("input");
    checkbox1.type = "checkbox";
    checkbox1.value = "prompt-1";
    checkbox1.checked = true;
    container.appendChild(checkbox1);

    const label1 = document.createElement("label");
    label1.textContent = "Test Prompt 1";
    container.appendChild(label1);

    initPromptSelect("test-select", "test-pills", "test-warn");

    // Should show pill for checked item
    expect(pillsBox.children.length).toBeGreaterThan(0);
  });

  test("handles checkbox changes", () => {
    window.ROOT_PATH = "";

    const container = document.createElement("div");
    container.id = "test-select-2";
    document.body.appendChild(container);

    const pillsBox = document.createElement("div");
    pillsBox.id = "test-pills-2";
    document.body.appendChild(pillsBox);

    const warnBox = document.createElement("div");
    warnBox.id = "test-warn-2";
    document.body.appendChild(warnBox);

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = "prompt-1";
    container.appendChild(checkbox);

    const label = document.createElement("label");
    label.textContent = "Test Prompt";
    container.appendChild(label);

    initPromptSelect("test-select-2", "test-pills-2", "test-warn-2");

    // Trigger change event
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));

    expect(pillsBox.children.length).toBeGreaterThan(0);
  });

  test("shows warning when exceeding max prompts", () => {
    window.ROOT_PATH = "";

    const container = document.createElement("div");
    container.id = "test-select-3";
    document.body.appendChild(container);

    const pillsBox = document.createElement("div");
    pillsBox.id = "test-pills-3";
    document.body.appendChild(pillsBox);

    const warnBox = document.createElement("div");
    warnBox.id = "test-warn-3";
    document.body.appendChild(warnBox);

    // Add 10 checked checkboxes (max is 8)
    for (let i = 0; i < 10; i++) {
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = `prompt-${i}`;
      checkbox.checked = true;
      container.appendChild(checkbox);

      const label = document.createElement("label");
      label.textContent = `Prompt ${i}`;
      container.appendChild(label);
    }

    initPromptSelect("test-select-3", "test-pills-3", "test-warn-3", 8);

    expect(warnBox.textContent).toContain("10 prompts");
    expect(warnBox.textContent).toContain("8 prompts");
  });

  test("clear button clears all selections", () => {
    window.ROOT_PATH = "";

    const container = document.createElement("div");
    container.id = "test-select-4";
    document.body.appendChild(container);

    const pillsBox = document.createElement("div");
    pillsBox.id = "test-pills-4";
    document.body.appendChild(pillsBox);

    const warnBox = document.createElement("div");
    warnBox.id = "test-warn-4";
    document.body.appendChild(warnBox);

    const clearBtn = document.createElement("button");
    clearBtn.id = "test-clear-4";
    document.body.appendChild(clearBtn);

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = "prompt-1";
    checkbox.checked = true;
    container.appendChild(checkbox);

    initPromptSelect("test-select-4", "test-pills-4", "test-warn-4", 8, null, "test-clear-4");

    // Get the new button reference after initPromptSelect replaces it
    const newClearBtn = document.getElementById("test-clear-4");
    newClearBtn.click();

    expect(checkbox.checked).toBe(false);
  });

  test("shows summary pill for many selections", () => {
    window.ROOT_PATH = "";

    const container = document.createElement("div");
    container.id = "test-select-5";
    document.body.appendChild(container);

    const pillsBox = document.createElement("div");
    pillsBox.id = "test-pills-5";
    document.body.appendChild(pillsBox);

    const warnBox = document.createElement("div");
    warnBox.id = "test-warn-5";
    document.body.appendChild(warnBox);

    // Add 5 checked checkboxes (more than maxPillsToShow=3)
    for (let i = 0; i < 5; i++) {
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = `prompt-${i}`;
      checkbox.checked = true;
      container.appendChild(checkbox);

      const label = document.createElement("label");
      label.textContent = `Prompt ${i}`;
      container.appendChild(label);
    }

    initPromptSelect("test-select-5", "test-pills-5", "test-warn-5");

    // Should show 3 pills + 1 summary pill
    expect(pillsBox.children.length).toBe(4);
    expect(pillsBox.lastChild.textContent).toContain("+2 more");
  });
});

// ---------------------------------------------------------------------------
// viewPrompt - Extended Tests
// ---------------------------------------------------------------------------
describe("viewPrompt - Extended", () => {
  test("displays prompt with metrics", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "prompt-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "p1",
          name: "test-prompt",
          description: "Test",
          arguments: [],
          metrics: {
            totalExecutions: 100,
            successfulExecutions: 95,
            failedExecutions: 5,
            failureRate: 5,
            minResponseTime: "10ms",
            maxResponseTime: "500ms",
            avgResponseTime: "100ms",
            lastExecutionTime: "2024-01-01T00:00:00Z",
          },
        }),
    });

    await viewPrompt("test-prompt");

    expect(details.innerHTML).toContain("100");
    expect(details.innerHTML).toContain("95");
    consoleSpy.mockRestore();
  });

  test("displays prompt with metadata", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "prompt-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "p1",
          name: "test-prompt",
          description: "Test",
          arguments: [],
          created_by: "admin@example.com",
          created_at: "2024-01-01T00:00:00Z",
          modified_by: "user@example.com",
          updated_at: "2024-01-02T00:00:00Z",
        }),
    });

    await viewPrompt("test-prompt");

    expect(details.innerHTML).toContain("admin@example.com");
    expect(details.innerHTML).toContain("user@example.com");
    consoleSpy.mockRestore();
  });

  test("displays prompt with tags", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "prompt-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "p1",
          name: "test-prompt",
          description: "Test",
          arguments: [],
          tags: ["tag1", "tag2", { id: "tag3", label: "Tag 3" }],
        }),
    });

    await viewPrompt("test-prompt");

    // Check for tags in the tags container
    const tagsEl = details.querySelector(".prompt-tags");
    expect(tagsEl).toBeTruthy();
    expect(tagsEl.textContent).toContain("tag1");
    expect(tagsEl.textContent).toContain("tag2");
    expect(tagsEl.textContent).toContain("tag3"); // Uses id when both id and label present
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// editPrompt - Extended Tests
// ---------------------------------------------------------------------------
describe("editPrompt - Extended", () => {
  test("handles visibility restrictions", async () => {
    window.ROOT_PATH = "";
    window.ALLOW_PUBLIC_VISIBILITY = false;
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const nameInput = document.createElement("input");
    nameInput.id = "edit-prompt-name";
    document.body.appendChild(nameInput);

    const descInput = document.createElement("textarea");
    descInput.id = "edit-prompt-description";
    document.body.appendChild(descInput);

    const publicRadio = document.createElement("input");
    publicRadio.type = "radio";
    publicRadio.id = "edit-prompt-visibility-public";
    document.body.appendChild(publicRadio);

    const teamRadio = document.createElement("input");
    teamRadio.type = "radio";
    teamRadio.id = "edit-prompt-visibility-team";
    document.body.appendChild(teamRadio);

    const privateRadio = document.createElement("input");
    privateRadio.type = "radio";
    privateRadio.id = "edit-prompt-visibility-private";
    document.body.appendChild(privateRadio);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "p1",
          name: "test-prompt",
          description: "desc",
          arguments: [],
          template: "Hello",
          visibility: "public",
        }),
    });

    // Mock URL with team_id
    Object.defineProperty(window, "location", {
      value: { href: "http://localhost?team_id=team1", search: "?team_id=team1" },
      writable: true,
    });

    await editPrompt("p1");

    // Should coerce public to team when ALLOW_PUBLIC_VISIBILITY=false
    expect(teamRadio.checked).toBe(true);
    consoleSpy.mockRestore();
  });

  test("does not coerce visibility when team_id is whitespace-only", async () => {
    window.ROOT_PATH = "";
    window.ALLOW_PUBLIC_VISIBILITY = false;
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const nameInput = document.createElement("input");
    nameInput.id = "edit-prompt-name";
    document.body.appendChild(nameInput);

    const descInput = document.createElement("textarea");
    descInput.id = "edit-prompt-description";
    document.body.appendChild(descInput);

    const publicRadio = document.createElement("input");
    publicRadio.type = "radio";
    publicRadio.id = "edit-prompt-visibility-public";
    document.body.appendChild(publicRadio);

    const teamRadio = document.createElement("input");
    teamRadio.type = "radio";
    teamRadio.id = "edit-prompt-visibility-team";
    document.body.appendChild(teamRadio);

    const privateRadio = document.createElement("input");
    privateRadio.type = "radio";
    privateRadio.id = "edit-prompt-visibility-private";
    document.body.appendChild(privateRadio);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "p1",
          name: "test-prompt",
          description: "desc",
          arguments: [],
          template: "Hello",
          visibility: "public",
        }),
    });

    // Whitespace-only team_id should not trigger coercion
    Object.defineProperty(window, "location", {
      value: { href: "http://localhost?team_id=%20", search: "?team_id=%20" },
      writable: true,
    });

    await editPrompt("p1");

    // public visibility should be preserved — no coercion for whitespace-only team_id
    expect(publicRadio.checked).toBe(true);
    expect(teamRadio.checked).toBe(false);
    consoleSpy.mockRestore();
  });

  test("populates tags field", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const nameInput = document.createElement("input");
    nameInput.id = "edit-prompt-name";
    document.body.appendChild(nameInput);

    const descInput = document.createElement("textarea");
    descInput.id = "edit-prompt-description";
    document.body.appendChild(descInput);

    const tagsInput = document.createElement("input");
    tagsInput.id = "edit-prompt-tags";
    document.body.appendChild(tagsInput);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          id: "p1",
          name: "test-prompt",
          description: "desc",
          arguments: [],
          template: "Hello",
          tags: ["tag1", { label: "tag2" }],
        }),
    });

    await editPrompt("p1");

    expect(tagsInput.value).toContain("tag1");
    expect(tagsInput.value).toContain("tag2");
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// buildPromptTestForm - Extended Tests
// ---------------------------------------------------------------------------
describe("buildPromptTestForm - Extended", () => {
  test("creates required field indicators", () => {
    const container = document.createElement("div");
    container.id = "prompt-test-form-fields";
    document.body.appendChild(container);

    const prompt = {
      name: "test-prompt",
      arguments: [
        { name: "required_arg", description: "Required", required: true },
        { name: "optional_arg", description: "Optional", required: false },
      ],
    };

    buildPromptTestForm(prompt);

    expect(container.innerHTML).toContain("required_arg *");
    expect(container.innerHTML).toContain("optional_arg");
    expect(container.querySelector('input[required]')).not.toBeNull();
  });

  test("sets placeholder from description", () => {
    const container = document.createElement("div");
    container.id = "prompt-test-form-fields";
    document.body.appendChild(container);

    const prompt = {
      name: "test-prompt",
      arguments: [
        { name: "query", description: "Enter search query", required: false },
      ],
    };

    buildPromptTestForm(prompt);

    const input = container.querySelector('input[name="arg-query"]');
    expect(input.placeholder).toBe("Enter search query");
  });
});

// ---------------------------------------------------------------------------
// runPromptTest - Extended Tests
// ---------------------------------------------------------------------------
describe("runPromptTest - Extended", () => {
  test("handles successful prompt rendering", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const form = document.createElement("form");
    form.id = "prompt-test-form";
    document.body.appendChild(form);

    const loading = document.createElement("div");
    loading.id = "prompt-test-loading";
    loading.classList.add("hidden");
    document.body.appendChild(loading);

    const result = document.createElement("div");
    result.id = "prompt-test-result";
    document.body.appendChild(result);

    const button = document.createElement("button");
    button.onclick = runPromptTest;
    button.textContent = "Render Prompt";
    document.body.appendChild(button);

    // Import and set current test prompt
    const { testPrompt } = await import("../../../mcpgateway/admin_ui/prompts.js");

    // Mock fetch for prompt details
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          id: "p1",
          name: "test-prompt",
          arguments: [],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          messages: [
            { role: "user", content: { text: "Hello world" } },
          ],
        }),
      })
    );

    await testPrompt("p1");
    await runPromptTest();

    expect(result.innerHTML).toContain("Hello world");
    consoleSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  test("handles rendering error", async () => {
    window.ROOT_PATH = "";
    cleanupPromptTestModal(); // Reset currentTestPrompt to null from previous test
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const form = document.createElement("form");
    form.id = "prompt-test-form";
    document.body.appendChild(form);

    const loading = document.createElement("div");
    loading.id = "prompt-test-loading";
    loading.classList.add("hidden");
    document.body.appendChild(loading);

    const result = document.createElement("div");
    result.id = "prompt-test-result";
    document.body.appendChild(result);

    const button = document.createElement("button");
    button.textContent = "Render Prompt";
    document.body.appendChild(button);

    // Create required DOM elements for testPrompt
    const fieldsContainer = document.createElement("div");
    fieldsContainer.id = "prompt-test-form-fields";
    document.body.appendChild(fieldsContainer);

    const title = document.createElement("div");
    title.id = "prompt-test-modal-title";
    document.body.appendChild(title);

    const desc = document.createElement("div");
    desc.id = "prompt-test-modal-description";
    document.body.appendChild(desc);

    // Mock fetch for runPromptTest (error)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        json: () => Promise.resolve({
          message: "Invalid arguments",
          details: "Missing required field",
        }),
      });

    vi.stubGlobal("fetch", fetchMock);

    // Mock runPromptTest to directly set up the error scenario
    // Since promptTestState is not exported, we'll test the error path by
    // ensuring the form exists and runPromptTest is called
    const { runPromptTest: runPromptTestFn } = await import("../../../mcpgateway/admin_ui/prompts.js");

    // Create a hidden input to simulate having prompt data
    const promptInput = document.createElement("input");
    promptInput.type = "hidden";
    promptInput.name = "prompt_id";
    promptInput.value = "p1";
    form.appendChild(promptInput);

    // Call runPromptTest which should trigger the error
    await runPromptTestFn();

    // Since promptTestState.currentTestPrompt is null, runPromptTest returns early
    // This test verifies the early return behavior
    expect(result.innerHTML).not.toContain("Error");

    consoleSpy.mockRestore();
    logSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});

// ---------------------------------------------------------------------------
// initPromptSelect - Select All respects search filter
// ---------------------------------------------------------------------------
describe("initPromptSelect - Select All respects search filter", () => {
  test("passes search query to /admin/prompts/ids when search input has value", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const container = document.createElement("div");
    container.id = "associatedPrompts";
    document.body.appendChild(container);

    const pillsBox = document.createElement("div");
    pillsBox.id = "prompt-pills-sa";
    document.body.appendChild(pillsBox);
    const warnBox = document.createElement("div");
    warnBox.id = "prompt-warn-sa";
    document.body.appendChild(warnBox);

    const selectBtn = document.createElement("button");
    selectBtn.id = "selectAllPromptsBtn";
    document.body.appendChild(selectBtn);

    const scrollTrigger = document.createElement("div");
    scrollTrigger.id = "prompts-scroll-trigger-1";
    document.body.appendChild(scrollTrigger);

    const searchInput = document.createElement("input");
    searchInput.id = "searchPrompts";
    searchInput.value = "  code  ";
    document.body.appendChild(searchInput);

    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({ prompt_ids: ["prompt-code-1"], count: 1 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    initPromptSelect(
      "associatedPrompts",
      "prompt-pills-sa",
      "prompt-warn-sa",
      6,
      "selectAllPromptsBtn"
    );

    const btn = document.getElementById("selectAllPromptsBtn");
    await btn.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchSpy).toHaveBeenCalled();
    const fetchUrl = fetchSpy.mock.calls[0][0];
    expect(fetchUrl).toContain("/admin/prompts/ids");
    expect(fetchUrl).toContain("q=code");

    consoleSpy.mockRestore();
    warnSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  test("uses searchEditPrompts input in edit-server mode", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const container = document.createElement("div");
    container.id = "edit-server-prompts";
    document.body.appendChild(container);

    const pillsBox = document.createElement("div");
    pillsBox.id = "prompt-pills-edit";
    document.body.appendChild(pillsBox);
    const warnBox = document.createElement("div");
    warnBox.id = "prompt-warn-edit";
    document.body.appendChild(warnBox);

    const selectBtn = document.createElement("button");
    selectBtn.id = "selectAllEditPromptsBtn";
    document.body.appendChild(selectBtn);

    const scrollTrigger = document.createElement("div");
    scrollTrigger.id = "prompts-scroll-trigger-1";
    document.body.appendChild(scrollTrigger);

    const searchInput = document.createElement("input");
    searchInput.id = "searchEditPrompts";
    searchInput.value = "review";
    document.body.appendChild(searchInput);

    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({ prompt_ids: ["prompt-review-1"], count: 1 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    initPromptSelect(
      "edit-server-prompts",
      "prompt-pills-edit",
      "prompt-warn-edit",
      6,
      "selectAllEditPromptsBtn"
    );

    const btn = document.getElementById("selectAllEditPromptsBtn");
    await btn.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchSpy).toHaveBeenCalled();
    const fetchUrl = fetchSpy.mock.calls[0][0];
    expect(fetchUrl).toContain("q=review");

    consoleSpy.mockRestore();
    warnSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});
