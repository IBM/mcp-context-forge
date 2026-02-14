/**
 * Unit tests for tags.js module
 * Tests: extractAvailableTags, updateAvailableTags, filterEntitiesByTags,
 *        addTagToFilter, updateFilterEmptyState, clearTagFilter, initializeTagFiltering
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));

import {
  extractAvailableTags,
  updateAvailableTags,
  filterEntitiesByTags,
  addTagToFilter,
  updateFilterEmptyState,
  clearTagFilter,
  initializeTagFiltering,
} from "../../../mcpgateway/admin_ui/tags.js";

// Helper to build a minimal table with tags column
function buildTable(entityType, rows) {
  const panel = document.createElement("div");
  panel.id = `${entityType}-panel`;

  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  ["Name", "Tags"].forEach((h) => {
    const th = document.createElement("th");
    th.textContent = h;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  rows.forEach(({ name, tags }) => {
    const tr = document.createElement("tr");
    const nameTd = document.createElement("td");
    nameTd.textContent = name;
    tr.appendChild(nameTd);

    const tagsTd = document.createElement("td");
    tags.forEach((tag) => {
      const span = document.createElement("span");
      span.className =
        "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full";
      span.textContent = tag;
      tagsTd.appendChild(span);
    });
    tr.appendChild(tagsTd);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  panel.appendChild(table);
  document.body.appendChild(panel);
  return panel;
}

afterEach(() => {
  document.body.innerHTML = "";
});

// ---------------------------------------------------------------------------
// extractAvailableTags
// ---------------------------------------------------------------------------
describe("extractAvailableTags", () => {
  test("extracts unique sorted tags from table rows", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    buildTable("tools", [
      { name: "Tool A", tags: ["auth", "api"] },
      { name: "Tool B", tags: ["api", "grpc"] },
    ]);
    const tags = extractAvailableTags("tools");
    expect(tags).toEqual(["api", "auth", "grpc"]);
    consoleSpy.mockRestore();
  });

  test("returns empty array when no rows exist", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    buildTable("tools", []);
    const tags = extractAvailableTags("tools");
    expect(tags).toEqual([]);
    consoleSpy.mockRestore();
  });

  test("returns empty array when panel does not exist", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const tags = extractAvailableTags("nonexistent");
    expect(tags).toEqual([]);
    consoleSpy.mockRestore();
  });

  test("filters out 'No tags', 'None', 'N/A'", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    buildTable("tools", [
      { name: "Tool A", tags: ["No tags"] },
      { name: "Tool B", tags: ["valid-tag"] },
    ]);
    const tags = extractAvailableTags("tools");
    expect(tags).toEqual(["valid-tag"]);
    consoleSpy.mockRestore();
  });

  test("filters out single-character tags", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    buildTable("tools", [{ name: "Tool A", tags: ["x", "ab"] }]);
    const tags = extractAvailableTags("tools");
    expect(tags).toEqual(["ab"]);
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// updateAvailableTags
// ---------------------------------------------------------------------------
describe("updateAvailableTags", () => {
  test("populates container with tag buttons", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    buildTable("tools", [{ name: "Tool A", tags: ["alpha", "beta"] }]);

    const container = document.createElement("div");
    container.id = "tools-available-tags";
    document.body.appendChild(container);

    updateAvailableTags("tools");
    const buttons = container.querySelectorAll("button");
    expect(buttons.length).toBe(2);
    expect(buttons[0].textContent).toBe("alpha");
    expect(buttons[1].textContent).toBe("beta");
    consoleSpy.mockRestore();
  });

  test("shows 'No tags found' when no tags available", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    buildTable("tools", []);

    const container = document.createElement("div");
    container.id = "tools-available-tags";
    document.body.appendChild(container);

    updateAvailableTags("tools");
    expect(container.innerHTML).toContain("No tags found");
    consoleSpy.mockRestore();
  });

  test("does nothing when container is missing", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    buildTable("tools", []);
    expect(() => updateAvailableTags("tools")).not.toThrow();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// filterEntitiesByTags
// ---------------------------------------------------------------------------
describe("filterEntitiesByTags", () => {
  test("shows all rows when filter is empty", () => {
    buildTable("tools", [
      { name: "A", tags: ["tag1"] },
      { name: "B", tags: ["tag2"] },
    ]);
    filterEntitiesByTags("tools", "");
    const rows = document.querySelectorAll("#tools-panel tbody tr");
    rows.forEach((row) => expect(row.style.display).toBe(""));
  });

  test.skip("hides rows that don't match filter tag (jsdom lacks CSS comment support in selectors)", () => {
    buildTable("tools", [
      { name: "A", tags: ["alpha"] },
      { name: "B", tags: ["beta"] },
    ]);
    filterEntitiesByTags("tools", "alpha");
    const rows = document.querySelectorAll("#tools-panel tbody tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
  });

  test.skip("supports multiple comma-separated tags (jsdom lacks CSS comment support in selectors)", () => {
    buildTable("tools", [
      { name: "A", tags: ["alpha"] },
      { name: "B", tags: ["beta"] },
      { name: "C", tags: ["gamma"] },
    ]);
    filterEntitiesByTags("tools", "alpha, beta");
    const rows = document.querySelectorAll("#tools-panel tbody tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });
});

// ---------------------------------------------------------------------------
// addTagToFilter
// ---------------------------------------------------------------------------
describe("addTagToFilter", () => {
  test.skip("appends tag to filter input value (jsdom lacks CSS comment support in selectors)", () => {
    buildTable("tools", [
      { name: "A", tags: ["alpha"] },
      { name: "B", tags: ["beta"] },
    ]);

    const input = document.createElement("input");
    input.id = "tools-tag-filter";
    input.value = "";
    document.body.appendChild(input);

    addTagToFilter("tools", "alpha");
    expect(input.value).toBe("alpha");
  });

  test("does not duplicate existing tags", () => {
    buildTable("tools", [{ name: "A", tags: ["alpha"] }]);

    const input = document.createElement("input");
    input.id = "tools-tag-filter";
    input.value = "alpha";
    document.body.appendChild(input);

    addTagToFilter("tools", "alpha");
    expect(input.value).toBe("alpha");
  });

  test("does nothing when input is missing", () => {
    expect(() => addTagToFilter("tools", "alpha")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// updateFilterEmptyState
// ---------------------------------------------------------------------------
describe("updateFilterEmptyState", () => {
  test("shows empty message when no visible items and filtering", () => {
    const panel = document.createElement("div");
    panel.id = "tools-panel";
    const container = document.createElement("div");
    container.classList.add("overflow-x-auto");
    panel.appendChild(container);
    document.body.appendChild(panel);

    updateFilterEmptyState("tools", 0, true);
    const msg = container.querySelector(".tag-filter-empty-message");
    expect(msg).not.toBeNull();
    expect(msg.style.display).toBe("block");
  });

  test("hides empty message when items are visible", () => {
    const panel = document.createElement("div");
    panel.id = "tools-panel";
    const container = document.createElement("div");
    container.classList.add("overflow-x-auto");
    const msg = document.createElement("div");
    msg.className = "tag-filter-empty-message";
    container.appendChild(msg);
    panel.appendChild(container);
    document.body.appendChild(panel);

    updateFilterEmptyState("tools", 5, true);
    expect(msg.style.display).toBe("none");
  });

  test("does nothing when container is missing", () => {
    expect(() => updateFilterEmptyState("tools", 0, true)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// clearTagFilter
// ---------------------------------------------------------------------------
describe("clearTagFilter", () => {
  test("clears input and shows all rows", () => {
    buildTable("tools", [
      { name: "A", tags: ["alpha"] },
      { name: "B", tags: ["beta"] },
    ]);

    const input = document.createElement("input");
    input.id = "tools-tag-filter";
    input.value = "alpha";
    document.body.appendChild(input);

    clearTagFilter("tools");
    expect(input.value).toBe("");
    const rows = document.querySelectorAll("#tools-panel tbody tr");
    rows.forEach((row) => expect(row.style.display).toBe(""));
  });

  test("does nothing when input is missing", () => {
    expect(() => clearTagFilter("tools")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// initializeTagFiltering
// ---------------------------------------------------------------------------
describe("initializeTagFiltering", () => {
  test("does not throw even with no panels present", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(() => initializeTagFiltering()).not.toThrow();
    consoleSpy.mockRestore();
  });
});
