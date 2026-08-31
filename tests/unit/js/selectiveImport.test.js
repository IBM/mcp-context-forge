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
  displayImportPreview,
} from "../../../mcpgateway/admin_ui/selectiveImport.js";
import { showNotification } from "../../../mcpgateway/admin_ui/utils.js";
import {
  showImportProgress,
  displayImportResults,
  refreshCurrentTabData,
} from "../../../mcpgateway/admin_ui/fileTransfer.js";

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
  vi.clearAllMocks();
});

// Helper to build the DOM structure displayImportPreview requires:
// #import-drop-zone must have a parent that has a parent (importSection).
function setupDropZone() {
  const importSection = document.createElement("div");
  const parent = document.createElement("div");
  const dropZone = document.createElement("div");
  dropZone.id = "import-drop-zone";
  parent.appendChild(dropZone);
  importSection.appendChild(parent);
  document.body.appendChild(importSection);
  return importSection;
}

// Minimal valid preview object used across displayImportPreview tests.
function makePreview(overrides = {}) {
  return {
    summary: { total_items: 3, by_type: { tools: 2, prompts: 1 } },
    bundles: {},
    items: {},
    conflicts: {},
    ...overrides,
  };
}

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

  test("dry_run=true shows 'Import preview completed' notification", async () => {
    vi.spyOn(console, "log").mockImplementation(() => {});
    window.Admin = { currentImportData: { tools: [] } };

    const { item1 } = addCheckboxes();
    item1.checked = true;

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ dry_run: true }),
    });

    await handleSelectiveImport(true);

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("preview completed"),
      "success"
    );
  });

  test("calls refreshCurrentTabData on successful real import", async () => {
    vi.spyOn(console, "log").mockImplementation(() => {});
    window.Admin = { currentImportData: { tools: [] } };

    const { item1 } = addCheckboxes();
    item1.checked = true;

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ imported: 1 }),
    });

    await handleSelectiveImport(false);

    expect(refreshCurrentTabData).toHaveBeenCalled();
    expect(displayImportResults).toHaveBeenCalled();
  });

  test("shows error notification when server returns non-ok response", async () => {
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
    window.Admin = { currentImportData: { tools: [] } };

    const { item1 } = addCheckboxes();
    item1.checked = true;

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      statusText: "Bad Request",
      json: () => Promise.resolve({ detail: "Invalid import format" }),
    });

    await handleSelectiveImport(false);

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Invalid import format"),
      "error"
    );
    expect(showImportProgress).toHaveBeenLastCalledWith(false);
  });

  test("shows error notification on network failure", async () => {
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
    window.Admin = { currentImportData: { tools: [] } };

    const { item1 } = addCheckboxes();
    item1.checked = true;

    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Network down"));

    await handleSelectiveImport(false);

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("Network down"),
      "error"
    );
    expect(showImportProgress).toHaveBeenLastCalledWith(false);
  });

  test("uses ROOT_PATH prefix in fetch URL", async () => {
    vi.spyOn(console, "log").mockImplementation(() => {});
    window.Admin = { currentImportData: { tools: [] } };
    window.ROOT_PATH = "/myprefix";

    const { item1 } = addCheckboxes();
    item1.checked = true;

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });

    await handleSelectiveImport(false);

    expect(fetchSpy).toHaveBeenCalledWith(
      "/myprefix/admin/import/configuration",
      expect.anything()
    );
  });

  test("collects gateway selections and includes them in request body", async () => {
    vi.spyOn(console, "log").mockImplementation(() => {});
    window.Admin = { currentImportData: { gateways: [] } };

    const { gw1 } = addCheckboxes();
    gw1.checked = true;

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });

    await handleSelectiveImport(false);

    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(body.selectedEntities.gateways).toContain("gw1");
  });

  test("reads conflict strategy and rekey secret from DOM elements", async () => {
    vi.spyOn(console, "log").mockImplementation(() => {});
    window.Admin = { currentImportData: { tools: [] } };

    document.body.innerHTML += `
      <select id="import-conflict-strategy"><option value="skip" selected>Skip</option></select>
      <input id="import-rekey-secret" value="mysecret" />
    `;

    const { item1 } = addCheckboxes();
    item1.checked = true;

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });

    await handleSelectiveImport(false);

    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(body.conflict_strategy).toBe("skip");
    expect(body.rekey_secret).toBe("mysecret");
  });
});

// ---------------------------------------------------------------------------
// displayImportPreview
// ---------------------------------------------------------------------------
describe("displayImportPreview", () => {
  test("creates preview container and appends it to importSection", () => {
    setupDropZone();
    displayImportPreview(makePreview());
    expect(document.getElementById("import-preview-container")).not.toBeNull();
  });

  test("reuses existing preview container instead of creating a new one", () => {
    setupDropZone();
    const existing = document.createElement("div");
    existing.id = "import-preview-container";
    document.body.appendChild(existing);

    displayImportPreview(makePreview());

    expect(document.querySelectorAll("#import-preview-container").length).toBe(1);
  });

  test("renders total_items count in summary", () => {
    setupDropZone();
    displayImportPreview(makePreview({ summary: { total_items: 7, by_type: { tools: 7 } } }));
    expect(document.getElementById("import-preview-container").textContent).toContain("7");
  });

  test("renders by_type breakdown in summary", () => {
    setupDropZone();
    displayImportPreview(makePreview({ summary: { total_items: 3, by_type: { tools: 2, prompts: 1 } } }));
    const text = document.getElementById("import-preview-container").textContent;
    expect(text).toContain("tools: 2");
    expect(text).toContain("prompts: 1");
  });

  test("renders gateway bundles section when bundles are present", () => {
    setupDropZone();
    const preview = makePreview({
      bundles: {
        "my-gateway": {
          gateway: { name: "My Gateway", description: "A gateway" },
          total_items: 2,
          items: { tools: [{ id: "t1" }], prompts: [{ id: "p1" }] },
        },
      },
    });
    displayImportPreview(preview);
    const container = document.getElementById("import-preview-container");
    expect(container.textContent).toContain("My Gateway");
    expect(container.querySelector(".gateway-checkbox")).not.toBeNull();
  });

  test("renders gateway with empty description as 'No description'", () => {
    setupDropZone();
    const preview = makePreview({
      bundles: {
        "gw-no-desc": {
          gateway: { name: "GW", description: null },
          total_items: 0,
          items: {},
        },
      },
    });
    displayImportPreview(preview);
    expect(document.getElementById("import-preview-container").textContent).toContain("No description");
  });

  test("renders custom items section for entities with is_custom=true", () => {
    setupDropZone();
    const preview = makePreview({
      items: {
        tools: [
          { id: "t1", name: "My Tool", description: "desc", is_custom: true, conflicts_with: null },
        ],
      },
    });
    displayImportPreview(preview);
    const container = document.getElementById("import-preview-container");
    expect(container.textContent).toContain("My Tool");
    expect(container.querySelector(".item-checkbox")).not.toBeNull();
  });

  test("does not render custom items section for entities with no custom items", () => {
    setupDropZone();
    const preview = makePreview({
      items: {
        tools: [
          { id: "t1", name: "Auto Tool", description: "", is_custom: false, conflicts_with: null },
        ],
      },
    });
    displayImportPreview(preview);
    expect(document.querySelector(".item-checkbox")).toBeNull();
  });

  test("renders conflict warning badge on conflicting items", () => {
    setupDropZone();
    const preview = makePreview({
      items: {
        tools: [
          { id: "t1", name: "Conflicting Tool", description: "", is_custom: true, conflicts_with: "existing-tool" },
        ],
      },
    });
    displayImportPreview(preview);
    expect(document.getElementById("import-preview-container").textContent).toContain("Conflict");
  });

  test("renders conflicts warning banner when conflicts object is non-empty", () => {
    setupDropZone();
    const preview = makePreview({ conflicts: { tools: ["existing-tool"] } });
    displayImportPreview(preview);
    expect(document.getElementById("import-preview-container").textContent).toContain("Naming conflicts detected");
  });

  test("does not render conflict banner when conflicts is empty", () => {
    setupDropZone();
    displayImportPreview(makePreview({ conflicts: {} }));
    expect(document.getElementById("import-preview-container").textContent).not.toContain("Naming conflicts detected");
  });

  test("Select All button checks all checkboxes when clicked", () => {
    setupDropZone();
    const preview = makePreview({
      bundles: {
        gw: { gateway: { name: "GW", description: "" }, total_items: 1, items: { tools: [] } },
      },
      items: {
        tools: [{ id: "t1", name: "T", description: "", is_custom: true, conflicts_with: null }],
      },
    });
    displayImportPreview(preview);
    document.querySelector('[data-action="select-all"]').click();
    const allChecked = [...document.querySelectorAll(".gateway-checkbox, .item-checkbox")].every(
      (cb) => cb.checked
    );
    expect(allChecked).toBe(true);
  });

  test("Select None button unchecks all checkboxes when clicked", () => {
    setupDropZone();
    const preview = makePreview({
      items: {
        tools: [{ id: "t1", name: "T", description: "", is_custom: true, conflicts_with: null }],
      },
    });
    displayImportPreview(preview);
    // Check first, then click Select None
    document.querySelectorAll(".item-checkbox").forEach((cb) => { cb.checked = true; });
    document.querySelector('[data-action="select-none"]').click();
    const anyChecked = [...document.querySelectorAll(".item-checkbox")].some((cb) => cb.checked);
    expect(anyChecked).toBe(false);
  });

  test("Custom Items Only button unchecks gateways and checks items", () => {
    setupDropZone();
    const preview = makePreview({
      bundles: {
        gw: { gateway: { name: "GW", description: "" }, total_items: 1, items: { tools: [] } },
      },
      items: {
        tools: [{ id: "t1", name: "T", description: "", is_custom: true, conflicts_with: null }],
      },
    });
    displayImportPreview(preview);
    document.querySelectorAll(".gateway-checkbox").forEach((cb) => { cb.checked = true; });
    document.querySelector('[data-action="select-custom"]').click();
    expect(document.querySelector(".gateway-checkbox").checked).toBe(false);
    expect(document.querySelector(".item-checkbox").checked).toBe(true);
  });

  test("Reset Selection button removes the preview container", () => {
    setupDropZone();
    displayImportPreview(makePreview());
    document.querySelector('[data-action="reset-selection"]').click();
    expect(document.getElementById("import-preview-container")).toBeNull();
  });

  test("Preview Selected button triggers dry-run import", async () => {
    vi.spyOn(console, "log").mockImplementation(() => {});
    setupDropZone();
    window.Admin = { currentImportData: {} };

    displayImportPreview(makePreview());

    // Click Preview Selected with no checkboxes checked — should hit the
    // "no items selected" warning path (confirming the handler was wired up).
    document.querySelector('[data-action="preview-selected"]').click();
    await Promise.resolve();

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("select at least one item"),
      "warning"
    );
  });

  test("Import Selected button triggers real import", async () => {
    vi.spyOn(console, "log").mockImplementation(() => {});
    setupDropZone();
    window.Admin = { currentImportData: {} };

    displayImportPreview(makePreview());

    document.querySelector('[data-action="import-selected"]').click();
    await Promise.resolve();

    expect(showNotification).toHaveBeenCalledWith(
      expect.stringContaining("select at least one item"),
      "warning"
    );
  });

  test("checkbox change event triggers updateSelectionCount", () => {
    setupDropZone();
    const preview = makePreview({
      items: {
        tools: [{ id: "t1", name: "T", description: "", is_custom: true, conflicts_with: null }],
      },
    });

    displayImportPreview(preview);

    // Use the #selection-count rendered inside the preview container itself.
    const count = document.getElementById("selection-count");
    const checkbox = document.querySelector(".item-checkbox");
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event("change"));

    expect(count.textContent).toContain("1 items selected");
  });

  test("initialises selection count to 0 on render", () => {
    setupDropZone();
    displayImportPreview(makePreview());

    // The count element is rendered inside the preview container by the template.
    const count = document.getElementById("selection-count");
    expect(count.textContent).toContain("0 items selected");
  });
});
