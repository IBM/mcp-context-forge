/**
 * Unit tests for selectiveImport.js module
 * Tests: updateSelectionCount, selectAllItems, selectNoneItems, selectOnlyCustom,
 *        resetImportSelection, displayImportPreview, handleSelectiveImport
 */

import { describe, test, expect, vi, afterEach } from "vitest";

import {
  updateSelectionCount,
  selectAllItems,
  selectNoneItems,
  selectOnlyCustom,
  resetImportSelection,
  handleSelectiveImport,
} from "../../../mcpgateway/admin_ui/selectiveImport.js";
import { showNotification } from "../../../mcpgateway/admin_ui/utils.js";
import { showImportProgress } from "../../../mcpgateway/admin_ui/fileTransfer.js";

vi.mock("../../../mcpgateway/admin_ui/fileTransfer.js", () => ({
  displayImportResults: vi.fn(),
  refreshCurrentTabData: vi.fn(),
  showImportProgress: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  getAuthToken: vi.fn().mockResolvedValue("test-token"),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showNotification: vi.fn(),
}));

// Helper to add checkboxes
function addCheckboxes() {
  const gw1 = document.createElement("input");
  gw1.type = "checkbox";
  gw1.className = "gateway-checkbox";
  gw1.dataset.gateway = "gw1";
  document.body.appendChild(gw1);

  const gw2 = document.createElement("input");
  gw2.type = "checkbox";
  gw2.className = "gateway-checkbox";
  gw2.dataset.gateway = "gw2";
  document.body.appendChild(gw2);

  const item1 = document.createElement("input");
  item1.type = "checkbox";
  item1.className = "item-checkbox";
  item1.dataset.type = "tools";
  item1.dataset.id = "tool-1";
  document.body.appendChild(item1);

  const item2 = document.createElement("input");
  item2.type = "checkbox";
  item2.className = "item-checkbox";
  item2.dataset.type = "prompts";
  item2.dataset.id = "prompt-1";
  document.body.appendChild(item2);

  return { gw1, gw2, item1, item2 };
}

afterEach(() => {
  document.body.innerHTML = "";
  delete window.Admin;
  delete window.ROOT_PATH;
});

// ---------------------------------------------------------------------------
// updateSelectionCount
// ---------------------------------------------------------------------------
describe("updateSelectionCount", () => {
  test("updates count element with selection summary", () => {
    const { gw1, item1 } = addCheckboxes();
    gw1.checked = true;
    item1.checked = true;

    const count = document.createElement("span");
    count.id = "selection-count";
    document.body.appendChild(count);

    updateSelectionCount();
    expect(count.textContent).toContain("2 items selected");
    expect(count.textContent).toContain("1 gateways");
    expect(count.textContent).toContain("1 individual items");
  });

  test("shows 0 when nothing selected", () => {
    addCheckboxes();
    const count = document.createElement("span");
    count.id = "selection-count";
    document.body.appendChild(count);

    updateSelectionCount();
    expect(count.textContent).toContain("0 items selected");
  });

  test("does not throw when count element is missing", () => {
    expect(() => updateSelectionCount()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// selectAllItems
// ---------------------------------------------------------------------------
describe("selectAllItems", () => {
  test("checks all gateway and item checkboxes", () => {
    const { gw1, gw2, item1, item2 } = addCheckboxes();
    selectAllItems();
    expect(gw1.checked).toBe(true);
    expect(gw2.checked).toBe(true);
    expect(item1.checked).toBe(true);
    expect(item2.checked).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// selectNoneItems
// ---------------------------------------------------------------------------
describe("selectNoneItems", () => {
  test("unchecks all checkboxes", () => {
    const { gw1, gw2, item1, item2 } = addCheckboxes();
    gw1.checked = true;
    item1.checked = true;

    selectNoneItems();
    expect(gw1.checked).toBe(false);
    expect(gw2.checked).toBe(false);
    expect(item1.checked).toBe(false);
    expect(item2.checked).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// selectOnlyCustom
// ---------------------------------------------------------------------------
describe("selectOnlyCustom", () => {
  test("unchecks gateways and checks only item checkboxes", () => {
    const { gw1, gw2, item1, item2 } = addCheckboxes();
    gw1.checked = true;
    gw2.checked = true;

    selectOnlyCustom();
    expect(gw1.checked).toBe(false);
    expect(gw2.checked).toBe(false);
    expect(item1.checked).toBe(true);
    expect(item2.checked).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// resetImportSelection
// ---------------------------------------------------------------------------
describe("resetImportSelection", () => {
  test("removes the preview container", () => {
    const container = document.createElement("div");
    container.id = "import-preview-container";
    document.body.appendChild(container);

    resetImportSelection();
    expect(document.getElementById("import-preview-container")).toBeNull();
  });

  test("does nothing when container does not exist", () => {
    expect(() => resetImportSelection()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// handleSelectiveImport
// ---------------------------------------------------------------------------
describe("handleSelectiveImport", () => {
  test("shows error when no import data is set", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    window.Admin = {};
    await handleSelectiveImport();
    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("select an import file"),
      "error"
    );
    consoleSpy.mockRestore();
  });

  test("shows warning when no items are selected", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    window.Admin = { currentImportData: { some: "data" } };
    await handleSelectiveImport();
    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("select at least one item"),
      "warning"
    );
    expect(showImportProgress).toHaveBeenCalledWith(false);
    consoleSpy.mockRestore();
  });

  test("sends import request when items are selected", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    window.Admin = { currentImportData: { tools: [] } };
    window.ROOT_PATH = "";

    const { item1 } = addCheckboxes();
    item1.checked = true;

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ imported: 1 }),
    });

    await handleSelectiveImport(false);

    expect(fetchSpy).toHaveBeenCalledWith(
      "/admin/import/configuration",
      expect.objectContaining({ method: "POST" })
    );

    fetchSpy.mockRestore();
    consoleSpy.mockRestore();
  });
});
