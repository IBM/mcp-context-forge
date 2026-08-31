/**
 * Unit tests for resources.js module
 * Tests: testResource, openResourceTestModal, runResourceTest,
 *        viewResource, editResource, initResourceSelect, cleanupResourceTestModal
 */

import { describe, test, expect, vi, afterEach, beforeEach } from "vitest";

import {
  testResource,
  openResourceTestModal,
  runResourceTest,
  viewResource,
  editResource,
  initResourceSelect,
  cleanupResourceTestModal,
} from "../../../mcpgateway/admin_ui/resources.js";
import { fetchWithTimeout } from "../../../mcpgateway/admin_ui/utils";
import { openModal } from "../../../mcpgateway/admin_ui/modals.js";

vi.mock("../../../mcpgateway/admin_ui/gateways.js", () => ({
  getSelectedGatewayIds: vi.fn(() => []),
}));
vi.mock("../../../mcpgateway/admin_ui/modals.js", () => ({
  openModal: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  validateInputName: vi.fn((s) => ({ valid: true, value: s })),
}));
vi.mock("../../../mcpgateway/admin_ui/servers.js", () => ({
  getEditSelections: vi.fn(() => new Set()),
  updatePromptMapping: vi.fn(),
  updateResourceMapping: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/teams.js", () => ({
  applyVisibilityRestrictions: vi.fn(),
  isTeamScopedView: vi.fn(() => false),
}));
vi.mock("../../../mcpgateway/admin_ui/utils", () => ({
  decodeHtml: vi.fn((s) => s || ""),
  fetchWithTimeout: vi.fn(),
  getCurrentTeamId: vi.fn(() => null),
  handleFetchError: vi.fn((e) => e.message),
  isInactiveChecked: vi.fn(() => false),
  makeCopyIdButton: vi.fn(() => document.createElement("button")),
  parseUriTemplate: vi.fn(() => []),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showErrorMessage: vi.fn(),
}));

beforeEach(() => {
  // Ensure window.Admin exists (cleanupResourceTestModal needs it)
  window.Admin = window.Admin || {};
});

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  delete window.Admin;
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// viewResource
// ---------------------------------------------------------------------------
describe("viewResource", () => {
  test("fetches and displays resource details", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "resource-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          resource: {
            id: "r1",
            name: "test-resource",
            uri: "test://uri",
            description: "A test resource",
          },
        }),
    });

    await viewResource("r1");
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("r1")
    );
    consoleSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Network error"));

    await viewResource("r1");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// editResource
// ---------------------------------------------------------------------------
describe("editResource", () => {
  test("fetches resource data for editing", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          resource: {
            id: "r1",
            name: "test-resource",
            uri: "test://uri",
            description: "desc",
            mimeType: "text/plain",
          },
        }),
    });

    const nameInput = document.createElement("input");
    nameInput.id = "edit-resource-name";
    document.body.appendChild(nameInput);

    const uriInput = document.createElement("input");
    uriInput.id = "edit-resource-uri";
    document.body.appendChild(uriInput);

    const idInput = document.createElement("input");
    idInput.id = "edit-resource-id";
    document.body.appendChild(idInput);

    await editResource("r1");
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("r1")
    );
    consoleSpy.mockRestore();
    errorSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Failed"));

    await editResource("r1");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// testResource
// ---------------------------------------------------------------------------
describe("testResource", () => {
  test("fetches resource and opens test modal", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    // Create DOM elements needed by openResourceTestModal
    const title = document.createElement("div");
    title.id = "resource-test-modal-title";
    document.body.appendChild(title);

    const fields = document.createElement("div");
    fields.id = "resource-test-form-fields";
    document.body.appendChild(fields);

    const result = document.createElement("div");
    result.id = "resource-test-result";
    document.body.appendChild(result);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          resource: {
            id: "r1",
            name: "test-resource",
            uri: "test://uri/{param}",
          },
        }),
    });

    await testResource("r1");
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("r1")
    );
    consoleSpy.mockRestore();
    errorSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Fetch failed"));

    await testResource("r1");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// openResourceTestModal
// ---------------------------------------------------------------------------
describe("openResourceTestModal", () => {
  test("opens modal with resource data", () => {
    // Create required DOM elements
    const title = document.createElement("div");
    title.id = "resource-test-modal-title";
    document.body.appendChild(title);

    const fields = document.createElement("div");
    fields.id = "resource-test-form-fields";
    document.body.appendChild(fields);

    const result = document.createElement("div");
    result.id = "resource-test-result";
    document.body.appendChild(result);

    openResourceTestModal({
      id: "r1",
      name: "test-resource",
      uri: "test://uri",
    });

    expect(openModal).toHaveBeenCalled();
    expect(title.textContent).toContain("test-resource");
  });

  test("handles missing DOM elements gracefully", () => {
    const errorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    // Without DOM elements, it will throw trying to set textContent on null
    expect(() =>
      openResourceTestModal({ id: "r1", name: "test", uri: "test://uri" })
    ).toThrow();
    errorSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// runResourceTest
// ---------------------------------------------------------------------------
describe("runResourceTest", () => {
  test("handles missing resource state", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    // No CurrentResourceUnderTest set
    await runResourceTest();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// initResourceSelect
// ---------------------------------------------------------------------------
describe("initResourceSelect", () => {
  test("returns early when required elements are missing", async () => {
    window.ROOT_PATH = "";
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const container = document.createElement("div");
    container.id = "test-select";
    document.body.appendChild(container);

    // Need 3 args: selectId, pillsId, warnId
    await initResourceSelect("test-select", "test-pills", "test-warn");
    expect(fetchWithTimeout).not.toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  test("does nothing when container element is missing", async () => {
    window.ROOT_PATH = "";
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    await initResourceSelect("missing-select", "missing-pills", "missing-warn");
    warnSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// cleanupResourceTestModal
// ---------------------------------------------------------------------------
describe("cleanupResourceTestModal", () => {
  test("clears test form fields and result", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const fields = document.createElement("div");
    fields.id = "resource-test-form-fields";
    fields.innerHTML = "<div>test content</div>";
    document.body.appendChild(fields);

    const result = document.createElement("div");
    result.id = "resource-test-result";
    result.innerHTML = "<div>results</div>";
    document.body.appendChild(result);

    cleanupResourceTestModal();
    expect(fields.innerHTML).toBe("");
    // Result gets a placeholder
    expect(result.innerHTML).toContain("Fill the fields");
    expect(window.Admin.CurrentResourceUnderTest).toBeNull();
    consoleSpy.mockRestore();
  });

  test("does nothing when elements are missing", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(() => cleanupResourceTestModal()).not.toThrow();
    consoleSpy.mockRestore();
  });

  test("hides loading element when present", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const loading = document.createElement("div");
    loading.id = "resource-test-loading";
    document.body.appendChild(loading);

    cleanupResourceTestModal();

    expect(loading.classList.contains("hidden")).toBe(true);
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// openResourceTestModal - extended coverage
// ---------------------------------------------------------------------------
describe("openResourceTestModal - with uriTemplate", () => {
  test("builds input fields for each template parameter", async () => {
    const { parseUriTemplate } = await import("../../../mcpgateway/admin_ui/utils");
    parseUriTemplate.mockReturnValue(["userId", "itemId"]);

    const title = document.createElement("div");
    title.id = "resource-test-modal-title";
    document.body.appendChild(title);

    const fields = document.createElement("div");
    fields.id = "resource-test-form-fields";
    document.body.appendChild(fields);

    const result = document.createElement("div");
    result.id = "resource-test-result";
    document.body.appendChild(result);

    openResourceTestModal({
      id: "r1",
      name: "parameterized-resource",
      uriTemplate: "resource://{userId}/items/{itemId}",
    });

    expect(fields.querySelectorAll("input").length).toBe(2);
    expect(document.getElementById("resource-field-userId")).not.toBeNull();
    expect(document.getElementById("resource-field-itemId")).not.toBeNull();
    expect(openModal).toHaveBeenCalledWith("resource-test-modal");
  });

  test("shows 'no URI template' message when uriTemplate is absent", async () => {
    const { parseUriTemplate } = await import("../../../mcpgateway/admin_ui/utils");
    parseUriTemplate.mockReturnValue([]);

    const title = document.createElement("div");
    title.id = "resource-test-modal-title";
    document.body.appendChild(title);

    const fields = document.createElement("div");
    fields.id = "resource-test-form-fields";
    document.body.appendChild(fields);

    const result = document.createElement("div");
    result.id = "resource-test-result";
    document.body.appendChild(result);

    openResourceTestModal({ id: "r1", name: "simple", uri: "resource://simple" });

    expect(fields.innerHTML).toContain("no URI template");
    expect(openModal).toHaveBeenCalledWith("resource-test-modal");
  });

  test("stores resource on window.Admin.CurrentResourceUnderTest", () => {
    const title = document.createElement("div");
    title.id = "resource-test-modal-title";
    document.body.appendChild(title);
    const fields = document.createElement("div");
    fields.id = "resource-test-form-fields";
    document.body.appendChild(fields);
    const result = document.createElement("div");
    result.id = "resource-test-result";
    document.body.appendChild(result);

    const resource = { id: "r42", name: "my-res", uri: "res://r42" };
    openResourceTestModal(resource);

    expect(window.Admin.CurrentResourceUnderTest).toBe(resource);
  });
});

// ---------------------------------------------------------------------------
// runResourceTest - extended coverage
// ---------------------------------------------------------------------------
describe("runResourceTest - with resource", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    window.Admin = {};
  });

  test("uses resource.uri when no uriTemplate", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    window.Admin.CurrentResourceUnderTest = {
      id: "r1",
      name: "direct",
      uri: "resource://direct",
    };

    const resultBox = document.createElement("div");
    resultBox.id = "resource-test-result";
    document.body.appendChild(resultBox);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ content: { text: "hello world" } }),
    });

    await runResourceTest();

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("resource%3A%2F%2Fdirect")
    );
    consoleSpy.mockRestore();
  });

  test("fills in uriTemplate parameters", async () => {
    const { parseUriTemplate } = await import("../../../mcpgateway/admin_ui/utils");
    parseUriTemplate.mockReturnValue(["id"]);

    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    window.Admin.CurrentResourceUnderTest = {
      id: "r2",
      name: "templated",
      uriTemplate: "resource://{id}",
    };

    const idInput = document.createElement("input");
    idInput.id = "resource-field-id";
    idInput.value = "42";
    document.body.appendChild(idInput);

    const resultBox = document.createElement("div");
    resultBox.id = "resource-test-result";
    document.body.appendChild(resultBox);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ content: { text: "result" } }),
    });

    await runResourceTest();

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("resource%3A%2F%2F42")
    );
    consoleSpy.mockRestore();
  });

  test("handles large content by auto-collapsing", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    window.Admin.CurrentResourceUnderTest = { id: "r3", uri: "res://r3" };

    const resultBox = document.createElement("div");
    resultBox.id = "resource-test-result";
    document.body.appendChild(resultBox);

    // Create content with > 30 lines
    const largeContent = Array(35).fill("line").join("\n");

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ content: { text: largeContent } }),
    });

    await runResourceTest();

    const pre = resultBox.querySelector("pre");
    expect(pre).not.toBeNull();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// viewResource - extended coverage
// ---------------------------------------------------------------------------
describe("viewResource - extended", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
  });

  test("handles HTTP error response", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { showErrorMessage } = await import("../../../mcpgateway/admin_ui/utils");

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: () => Promise.resolve({ detail: "Resource not found" }),
    });

    await viewResource("r-missing");

    expect(showErrorMessage).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });

  test("renders resource with tags", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "resource-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          resource: {
            id: "r2",
            name: "tagged-resource",
            uri: "res://r2",
            tags: ["alpha", "beta"],
            enabled: true,
          },
        }),
    });

    await viewResource("r2");

    expect(details.innerHTML).not.toBe("");
    consoleSpy.mockRestore();
  });

  test("renders resource with metrics", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "resource-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          resource: {
            id: "r3",
            name: "metrics-resource",
            uri: "res://r3",
            enabled: false,
            metrics: {
              totalExecutions: 10,
              successfulExecutions: 8,
              failedExecutions: 2,
              failureRate: 0.2,
              minResponseTime: 5,
              maxResponseTime: 100,
              avgResponseTime: 50,
              lastExecutionTime: "2025-01-01",
            },
          },
        }),
    });

    await viewResource("r3");

    expect(details.innerHTML).toContain("Total Executions");
    consoleSpy.mockRestore();
  });

  test("opens resource-modal after loading", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "resource-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          resource: { id: "r4", name: "res", uri: "res://r4" },
        }),
    });

    await viewResource("r4");

    expect(openModal).toHaveBeenCalledWith("resource-modal");
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// editResource - extended coverage
// ---------------------------------------------------------------------------
describe("editResource - extended", () => {
  beforeEach(() => {
    window.ROOT_PATH = "";
    delete window.location;
    window.location = { href: "http://localhost/admin" };
  });

  function buildEditForm() {
    const form = document.createElement("form");
    form.id = "edit-resource-form";
    document.body.appendChild(form);

    ["edit-resource-name", "edit-resource-uri", "edit-resource-description",
      "edit-resource-mime-type", "edit-resource-tags"].forEach((id) => {
      const input = document.createElement("input");
      input.id = id;
      document.body.appendChild(input);
    });

    ["public", "team", "private"].forEach((v) => {
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.id = `edit-resource-visibility-${v}`;
      document.body.appendChild(radio);
    });
    return form;
  }

  test("prefills form fields and opens edit modal", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    buildEditForm();

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          resource: {
            id: "r1",
            name: "my-res",
            uri: "res://r1",
            description: "desc",
            mimeType: "text/plain",
            visibility: "team",
            tags: ["a", "b"],
          },
        }),
    });

    await editResource("r1");

    expect(openModal).toHaveBeenCalledWith("resource-edit-modal");
    expect(document.getElementById("edit-resource-name").value).toBe("my-res");
    expect(document.getElementById("edit-resource-uri").value).toBe("res://r1");
    expect(document.getElementById("edit-resource-visibility-team").checked).toBe(true);
    consoleSpy.mockRestore();
  });

  test("sets public visibility radio correctly", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    buildEditForm();

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          resource: { id: "r1", name: "pub-res", uri: "res://r1", visibility: "public" },
        }),
    });

    await editResource("r1");

    expect(document.getElementById("edit-resource-visibility-public").checked).toBe(true);
    consoleSpy.mockRestore();
  });

  test("sets private visibility radio correctly", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    buildEditForm();

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          resource: { id: "r1", name: "priv-res", uri: "res://r1", visibility: "private" },
        }),
    });

    await editResource("r1");

    expect(document.getElementById("edit-resource-visibility-private").checked).toBe(true);
    consoleSpy.mockRestore();
  });

  test("handles HTTP error response", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const { showErrorMessage } = await import("../../../mcpgateway/admin_ui/utils");

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: () => Promise.resolve({ detail: "Server error" }),
    });

    await editResource("r1");

    expect(showErrorMessage).toHaveBeenCalled();
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// initResourceSelect - extended coverage
// ---------------------------------------------------------------------------
describe("initResourceSelect - with elements", () => {
  function buildSelectDOM(selectId = "associatedResources", pillsId = "res-pills", warnId = "res-warn") {
    const container = document.createElement("div");
    container.id = selectId;
    document.body.appendChild(container);

    const pills = document.createElement("div");
    pills.id = pillsId;
    document.body.appendChild(pills);

    const warn = document.createElement("div");
    warn.id = warnId;
    document.body.appendChild(warn);

    return { container, pills, warn };
  }

  afterEach(() => {
    document.body.innerHTML = "";
    vi.clearAllMocks();
  });

  test("initializes with all elements and renders empty pills", () => {
    const { pills } = buildSelectDOM();

    initResourceSelect("associatedResources", "res-pills", "res-warn");

    expect(pills.innerHTML).toBe("");
  });

  test("renders pills for checked checkboxes", () => {
    const { container, pills } = buildSelectDOM();

    const cb1 = document.createElement("input");
    cb1.type = "checkbox";
    cb1.value = "id-1";
    cb1.checked = true;
    const label1 = document.createElement("label");
    label1.textContent = "Resource One";
    container.appendChild(cb1);
    container.appendChild(label1);

    initResourceSelect("associatedResources", "res-pills", "res-warn");

    expect(pills.querySelectorAll("span").length).toBeGreaterThan(0);
  });

  test("shows warning when more than max resources selected", () => {
    const { container, warn } = buildSelectDOM();

    // Add 12 checked checkboxes (> max of 10)
    for (let i = 0; i < 12; i++) {
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = `id-${i}`;
      cb.checked = true;
      const label = document.createElement("label");
      label.textContent = `Resource ${i}`;
      container.appendChild(cb);
      container.appendChild(label);
    }

    initResourceSelect("associatedResources", "res-pills", "res-warn");

    expect(warn.textContent).toContain("12 resources");
  });

  test("renders +N more pill when more than 3 resources selected", () => {
    const { container, pills } = buildSelectDOM();

    for (let i = 0; i < 5; i++) {
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = `id-${i}`;
      cb.checked = true;
      const label = document.createElement("label");
      label.textContent = `Resource ${i}`;
      container.appendChild(cb);
      container.appendChild(label);
    }

    initResourceSelect("associatedResources", "res-pills", "res-warn");

    const spans = pills.querySelectorAll("span");
    const morePill = Array.from(spans).find((s) => s.textContent.includes("+"));
    expect(morePill).not.toBeUndefined();
    expect(morePill.textContent).toContain("+2 more");
  });

  test("attaches change listener for checkbox toggling", () => {
    const { container, pills } = buildSelectDOM();

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = "id-1";
    cb.checked = false;
    const label = document.createElement("label");
    label.textContent = "Resource One";
    container.appendChild(cb);
    container.appendChild(label);

    initResourceSelect("associatedResources", "res-pills", "res-warn");

    cb.checked = true;
    cb.dispatchEvent(new Event("change", { bubbles: true }));

    const spans = pills.querySelectorAll("span");
    expect(spans.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// initResourceSelect - Select All respects search filter
// ---------------------------------------------------------------------------
describe("initResourceSelect - Select All respects search filter", () => {
  test("passes search query to /admin/resources/ids when search input has value", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const container = document.createElement("div");
    container.id = "associatedResources";
    document.body.appendChild(container);

    const pillsBox = document.createElement("div");
    pillsBox.id = "res-pills-sa";
    document.body.appendChild(pillsBox);
    const warnBox = document.createElement("div");
    warnBox.id = "res-warn-sa";
    document.body.appendChild(warnBox);

    const selectBtn = document.createElement("button");
    selectBtn.id = "selectAllResourcesBtn";
    document.body.appendChild(selectBtn);

    const scrollTrigger = document.createElement("div");
    scrollTrigger.id = "resources-scroll-trigger-1";
    document.body.appendChild(scrollTrigger);

    const searchInput = document.createElement("input");
    searchInput.id = "searchResources";
    searchInput.value = "  file  ";
    document.body.appendChild(searchInput);

    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({ resource_ids: ["res-file-1"], count: 1 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    initResourceSelect(
      "associatedResources",
      "res-pills-sa",
      "res-warn-sa",
      6,
      "selectAllResourcesBtn"
    );

    const btn = document.getElementById("selectAllResourcesBtn");
    await btn.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchSpy).toHaveBeenCalled();
    const fetchUrl = fetchSpy.mock.calls[0][0];
    expect(fetchUrl).toContain("/admin/resources/ids");
    expect(fetchUrl).toContain("q=file");

    consoleSpy.mockRestore();
    warnSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  test("uses searchEditResources input in edit-server mode", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const container = document.createElement("div");
    container.id = "edit-server-resources";
    document.body.appendChild(container);

    const pillsBox = document.createElement("div");
    pillsBox.id = "res-pills-edit";
    document.body.appendChild(pillsBox);
    const warnBox = document.createElement("div");
    warnBox.id = "res-warn-edit";
    document.body.appendChild(warnBox);

    const selectBtn = document.createElement("button");
    selectBtn.id = "selectAllEditResourcesBtn";
    document.body.appendChild(selectBtn);

    const scrollTrigger = document.createElement("div");
    scrollTrigger.id = "resources-scroll-trigger-1";
    document.body.appendChild(scrollTrigger);

    const searchInput = document.createElement("input");
    searchInput.id = "searchEditResources";
    searchInput.value = "config";
    document.body.appendChild(searchInput);

    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({ resource_ids: ["res-config-1"], count: 1 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    initResourceSelect(
      "edit-server-resources",
      "res-pills-edit",
      "res-warn-edit",
      6,
      "selectAllEditResourcesBtn"
    );

    const btn = document.getElementById("selectAllEditResourcesBtn");
    await btn.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchSpy).toHaveBeenCalled();
    const fetchUrl = fetchSpy.mock.calls[0][0];
    expect(fetchUrl).toContain("q=config");

    consoleSpy.mockRestore();
    warnSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});
