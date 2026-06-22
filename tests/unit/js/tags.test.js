/**
 * Unit tests for tags.js module
 * Tests: extractAvailableTags, updateAvailableTags, filterEntitiesByTags,
 *        addTagToFilter, updateFilterEmptyState, clearTagFilter, initializeTagFiltering
 */

import { describe, test, expect, vi, afterEach } from "vitest";

import {
  extractAvailableTags,
  updateAvailableTags,
  filterEntitiesByTags,
  addTagToFilter,
  updateFilterEmptyState,
  clearTagFilter,
  initializeTagFiltering,
} from "../../../mcpgateway/admin_ui/tags.js";

vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));
vi.mock("../../../mcpgateway/admin_ui/search.js", () => ({
  getPanelSearchConfig: vi.fn(() => null),
  loadSearchablePanel: vi.fn(),
  queueSearchablePanelReload: vi.fn(),
}));

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
      span.setAttribute("data-tag", tag);
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

  test("respects configured max tag length from GATEWAY_CONFIG", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    // Set a higher limit
    window.GATEWAY_CONFIG = { validationMaxTagLength: 150, validationMinTagLength: 2 };

    const longTag = "a".repeat(120); // 120 characters - within the 150 limit
    const tooLongTag = "b".repeat(160); // 160 characters - exceeds the 150 limit

    buildTable("tools", [
      { name: "Tool A", tags: ["short", longTag, tooLongTag] }
    ]);

    const tags = extractAvailableTags("tools");
    expect(tags).toContain("short");
    expect(tags).toContain(longTag); // Should include 120-char tag
    expect(tags).not.toContain(tooLongTag); // Should exclude 160-char tag

    // Cleanup
    delete window.GATEWAY_CONFIG;
    consoleSpy.mockRestore();
  });

  test("falls back to default 50-char limit when GATEWAY_CONFIG is missing", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    // Ensure GATEWAY_CONFIG is not set
    delete window.GATEWAY_CONFIG;

    const tag51 = "a".repeat(51); // 51 characters - exceeds default 50 limit
    const tag50 = "b".repeat(50); // 50 characters - at default limit

    buildTable("tools", [
      { name: "Tool A", tags: ["short", tag50, tag51] }
    ]);

    const tags = extractAvailableTags("tools");
    expect(tags).toContain("short");
    expect(tags).toContain(tag50); // Should include 50-char tag
    expect(tags).not.toContain(tag51); // Should exclude 51-char tag (default limit)

    consoleSpy.mockRestore();
  });

  test("respects configured min tag length from GATEWAY_CONFIG", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    // Set a higher minimum
    window.GATEWAY_CONFIG = { validationMaxTagLength: 100, validationMinTagLength: 5 };

    buildTable("tools", [
      { name: "Tool A", tags: ["ab", "abcd", "abcde", "abcdef"] }
    ]);

    const tags = extractAvailableTags("tools");
    expect(tags).not.toContain("ab"); // 2 chars - below min of 5
    expect(tags).not.toContain("abcd"); // 4 chars - below min of 5
    expect(tags).toContain("abcde"); // 5 chars - at min
    expect(tags).toContain("abcdef"); // 6 chars - above min

    // Cleanup
    delete window.GATEWAY_CONFIG;
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
