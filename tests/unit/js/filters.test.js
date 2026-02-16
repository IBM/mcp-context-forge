/**
 * Unit tests for filters.js module
 * Tests: clearSearch (the only untested function)
 * (filterServerTable, filterToolsTable, filterResourcesTable, filterPromptsTable,
 *  filterA2AAgentsTable, filterGatewaysTable are already tested in tests/js/)
 */

import { describe, test, expect, vi, afterEach } from "vitest";

import { clearSearch } from "../../../mcpgateway/admin_ui/filters.js";

vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));

afterEach(() => {
  document.body.innerHTML = "";
});

// Helper: build a simple table with searchable rows
function buildSearchableTable(entityType, tbodyId, rows) {
  const panel = document.createElement("div");
  panel.id = `${entityType}-panel`;

  const input = document.createElement("input");
  input.id = `${entityType}-search-input`;
  input.value = "previous search";
  panel.appendChild(input);

  const table = document.createElement("table");
  const tbody = document.createElement("tbody");
  tbody.id = tbodyId;

  rows.forEach((text) => {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.textContent = text;
    tr.appendChild(td);
    tbody.appendChild(tr);
  });

  table.appendChild(tbody);
  panel.appendChild(table);
  document.body.appendChild(panel);
  return input;
}

// ---------------------------------------------------------------------------
// clearSearch
// ---------------------------------------------------------------------------
describe("clearSearch", () => {
  test("clears catalog search input", () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const input = buildSearchableTable("catalog", "servers-table-body", ["Server A"]);
    clearSearch("catalog");
    expect(input.value).toBe("");
    consoleSpy.mockRestore();
  });

  test("clears tools search input", () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const input = buildSearchableTable("tools", "tools-table-body", ["Tool A"]);
    clearSearch("tools");
    expect(input.value).toBe("");
    consoleSpy.mockRestore();
  });

  test("clears resources search input", () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const input = buildSearchableTable("resources", "resources-table-body", ["Res A"]);
    clearSearch("resources");
    expect(input.value).toBe("");
    consoleSpy.mockRestore();
  });

  test("clears prompts search input", () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const input = buildSearchableTable("prompts", "prompts-table-body", ["Prompt A"]);
    clearSearch("prompts");
    expect(input.value).toBe("");
    consoleSpy.mockRestore();
  });

  test("clears a2a-agents search input", () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const input = buildSearchableTable("a2a-agents", "agents-table-body", ["Agent A"]);
    clearSearch("a2a-agents");
    expect(input.value).toBe("");
    consoleSpy.mockRestore();
  });

  test("clears gateways search input", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const input = buildSearchableTable("gateways", "gateways-table-body", ["GW A"]);
    clearSearch("gateways");
    expect(input.value).toBe("");
    consoleSpy.mockRestore();
  });

  test("does not throw for unknown entity type", () => {
    expect(() => clearSearch("unknown")).not.toThrow();
  });

  test("does not throw when input elements are missing", () => {
    expect(() => clearSearch("catalog")).not.toThrow();
  });
});
