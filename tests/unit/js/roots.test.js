/**
 * Unit tests for roots.js module
 * Tests: viewRoot, editRoot, exportRoot
 */

import { describe, test, expect, vi, afterEach } from "vitest";

import { viewRoot, editRoot, exportRoot } from "../../../mcpgateway/admin_ui/roots.js";
import { fetchWithTimeout } from "../../../mcpgateway/admin_ui/utils.js";

vi.mock("../../../mcpgateway/admin_ui/modals.js", () => ({
  openModal: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  validateInputName: vi.fn((s) => ({ valid: true, value: s })),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  fetchWithTimeout: vi.fn(),
  isInactiveChecked: vi.fn(() => false),
  handleFetchError: vi.fn((e) => e.message),
  showErrorMessage: vi.fn(),
}));

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// viewRoot
// ---------------------------------------------------------------------------
describe("viewRoot", () => {
  test("fetches and displays root details", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const details = document.createElement("div");
    details.id = "root-details";
    document.body.appendChild(details);

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          uri: "file:///test",
          name: "Test Root",
          description: "A test root",
        }),
    });

    await viewRoot("file:///test");
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("file")
    );
    consoleSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Network error"));

    await viewRoot("file:///test");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("handles non-ok response", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: () => Promise.resolve({ detail: "Not found" }),
    });

    await viewRoot("missing");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// editRoot
// ---------------------------------------------------------------------------
describe("editRoot", () => {
  test("fetches root data for editing", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          uri: "file:///test",
          name: "Test Root",
          description: "desc",
        }),
    });

    const nameInput = document.createElement("input");
    nameInput.id = "edit-root-name";
    document.body.appendChild(nameInput);

    const uriInput = document.createElement("input");
    uriInput.id = "edit-root-uri";
    document.body.appendChild(uriInput);

    await editRoot("file:///test");
    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("file")
    );
    consoleSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Failed"));

    await editRoot("file:///test");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// exportRoot
// ---------------------------------------------------------------------------
describe("exportRoot", () => {
  test("fetches root and triggers download via blob", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const mockBlob = new Blob(["{}"], { type: "application/json" });
    fetchWithTimeout.mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(mockBlob),
      headers: {
        get: vi.fn(() => null),
      },
    });

    // Mock URL.createObjectURL and revokeObjectURL
    const mockUrl = "blob:http://localhost/fake";
    window.URL.createObjectURL = vi.fn(() => mockUrl);
    window.URL.revokeObjectURL = vi.fn();

    await exportRoot("file:///test");
    expect(fetchWithTimeout).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("handles error gracefully", async () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    fetchWithTimeout.mockRejectedValue(new Error("Failed"));

    await exportRoot("file:///test");
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});
