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

vi.mock("../../../mcpgateway/admin_ui/gateway.js", () => ({
  getSelectedGatewayIds: vi.fn(() => []),
}));
vi.mock("../../../mcpgateway/admin_ui/modals.js", () => ({
  openModal: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  validateInputName: vi.fn((s) => ({ valid: true, value: s })),
}));
vi.mock("../../../mcpgateway/admin_ui/utils", () => ({
  decodeHtml: vi.fn((s) => s || ""),
  fetchWithTimeout: vi.fn(),
  getCurrentTeamId: vi.fn(() => null),
  handleFetchError: vi.fn((e) => e.message),
  isInactiveChecked: vi.fn(() => false),
  parseUriTemplate: vi.fn((uri) => []),
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
});
