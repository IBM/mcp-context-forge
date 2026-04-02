/**
 * Unit tests for filters.js module
 * Tests: filterServerTable, filterToolsTable, filterResourcesTable, filterPromptsTable,
 *        filterA2AAgentsTable, filterGatewaysTable, toggleViewPublic
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import {
  filterServerTable,
  filterToolsTable,
  filterResourcesTable,
  filterPromptsTable,
  filterA2AAgentsTable,
  filterGatewaysTable,
  toggleViewPublic,
} from "../../../mcpgateway/admin_ui/filters.js";

// Mock dependencies
vi.mock("../../../mcpgateway/admin_ui/gateways.js", () => ({
  getSelectedGatewayIds: vi.fn(() => []),
}));

vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));

describe("filterServerTable", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <table id="servers-table">
        <tbody id="servers-table-body">
          <tr data-testid="server-item">
            <td>Actions</td>
            <td>Icon</td>
            <td>1</td>
            <td>uuid-1</td>
            <td>Test Server</td>
            <td>A test server</td>
            <td>tool1, tool2</td>
            <td>res1</td>
            <td>prompt1</td>
            <td>tag1</td>
            <td>owner@example.com</td>
            <td>team-1</td>
            <td>public</td>
          </tr>
          <tr data-testid="server-item">
            <td>Actions</td>
            <td>Icon</td>
            <td>2</td>
            <td>uuid-2</td>
            <td>Another Server</td>
            <td>Different description</td>
            <td>tool3</td>
            <td>res2</td>
            <td>prompt2</td>
            <td>tag2</td>
            <td>user@example.com</td>
            <td>team-2</td>
            <td>private</td>
          </tr>
          <tr data-testid="server-item">
            <td>Actions</td>
            <td>Icon</td>
            <td>3</td>
            <td>uuid-3</td>
            <td>Third Server</td>
            <td>Another test server</td>
            <td>tool1</td>
            <td>res3</td>
            <td>prompt3</td>
            <td>tag1, tag3</td>
            <td>admin@example.com</td>
            <td>team-1</td>
            <td>public</td>
          </tr>
        </tbody>
      </table>
    `;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("shows all rows when search is empty", () => {
    filterServerTable("");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    rows.forEach((row) => {
      expect(row.style.display).toBe("");
    });
  });

  test("filters rows by server name", () => {
    filterServerTable("Test Server");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe(""); // Matches because description contains "test server"
  });

  test("filters rows by description", () => {
    filterServerTable("Different description");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters rows by tag", () => {
    filterServerTable("tag2");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("search is case insensitive", () => {
    filterServerTable("TEST SERVER");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe(""); // Matches "Another test server" in description
  });

  test("handles missing table gracefully", () => {
    document.body.innerHTML = "";
    const consoleSpy = vi.spyOn(console, "warn");
    filterServerTable("test");
    expect(consoleSpy).toHaveBeenCalledWith("Server table not found");
    consoleSpy.mockRestore();
  });

  test("filters by owner email", () => {
    filterServerTable("owner@example.com");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by team", () => {
    filterServerTable("team-2");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by visibility", () => {
    filterServerTable("private");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("shows multiple matching rows", () => {
    filterServerTable("test server");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("filters by UUID", () => {
    filterServerTable("uuid-2");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by tools", () => {
    filterServerTable("tool1");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("filters by resources", () => {
    filterServerTable("res2");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by prompts", () => {
    filterServerTable("prompt3");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("handles search with leading/trailing whitespace", () => {
    filterServerTable("  Test Server  ");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
  });

  test("handles partial matches", () => {
    filterServerTable("Serv");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("");
  });

  test("handles no matches", () => {
    filterServerTable("nonexistent");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    rows.forEach((row) => {
      expect(row.style.display).toBe("none");
    });
  });

  test("uses fallback selector with data-testid", () => {
    document.body.innerHTML = `
      <table>
        <tbody data-testid="server-list">
          <tr data-testid="server-item">
            <td>Actions</td>
            <td>Icon</td>
            <td>1</td>
            <td>uuid-1</td>
            <td>Test Server</td>
            <td>Description</td>
            <td>tools</td>
            <td>res</td>
            <td>prompt</td>
            <td>tag</td>
            <td>owner@test.com</td>
            <td>team-1</td>
            <td>public</td>
          </tr>
        </tbody>
      </table>
    `;

    filterServerTable("Test Server");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("");
  });

  test("handles error during filtering", () => {
    document.body.innerHTML = `
      <table id="servers-table">
        <tbody id="servers-table-body">
          <tr data-testid="server-item">
            <td>Actions</td>
          </tr>
        </tbody>
      </table>
    `;

    const consoleSpy = vi.spyOn(console, "error");
    expect(() => filterServerTable("test")).not.toThrow();
    consoleSpy.mockRestore();
  });

  test("filters by multiple tags", () => {
    filterServerTable("tag1");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("handles special characters in search", () => {
    document.body.innerHTML = `
      <table id="servers-table">
        <tbody id="servers-table-body">
          <tr data-testid="server-item">
            <td>Actions</td>
            <td>Icon</td>
            <td>1</td>
            <td>uuid-1</td>
            <td>Server (Test)</td>
            <td>Description</td>
            <td>tools</td>
            <td>res</td>
            <td>prompt</td>
            <td>tag</td>
            <td>owner@test.com</td>
            <td>team-1</td>
            <td>public</td>
          </tr>
        </tbody>
      </table>
    `;

    filterServerTable("(Test)");
    const rows = document.querySelectorAll('tr[data-testid="server-item"]');
    expect(rows[0].style.display).toBe("");
  });
});

describe("filterToolsTable", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <table id="tools-table">
        <tbody id="tools-table-body">
          <tr>
            <td>Actions</td>
            <td>1</td>
            <td>tool-id-1</td>
            <td>gateway-1</td>
            <td>read_file</td>
            <td>GET</td>
            <td>Reads a file</td>
            <td>annotation1</td>
            <td>filesystem</td>
            <td>owner@test.com</td>
            <td>team-1</td>
            <td>Active</td>
          </tr>
          <tr>
            <td>Actions</td>
            <td>2</td>
            <td>tool-id-2</td>
            <td>gateway-2</td>
            <td>write_file</td>
            <td>POST</td>
            <td>Writes a file</td>
            <td>annotation2</td>
            <td>filesystem</td>
            <td>user@test.com</td>
            <td>team-2</td>
            <td>Inactive</td>
          </tr>
          <tr>
            <td>Actions</td>
            <td>3</td>
            <td>tool-id-3</td>
            <td>gateway-1</td>
            <td>list_files</td>
            <td>GET</td>
            <td>Lists files in directory</td>
            <td>annotation3</td>
            <td>filesystem, directory</td>
            <td>admin@test.com</td>
            <td>team-1</td>
            <td>Active</td>
          </tr>
        </tbody>
      </table>
    `;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("shows all rows when search is empty", () => {
    filterToolsTable("");
    const rows = document.querySelectorAll("#tools-table-body tr");
    rows.forEach((row) => {
      expect(row.style.display).toBe("");
    });
  });

  test("filters by tool name", () => {
    filterToolsTable("read_file");
    const rows = document.querySelectorAll("#tools-table-body tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by description", () => {
    filterToolsTable("Writes a file");
    const rows = document.querySelectorAll("#tools-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by tag", () => {
    filterToolsTable("filesystem");
    const rows = document.querySelectorAll("#tools-table-body tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("");
  });

  test("filters by status", () => {
    filterToolsTable("Inactive");
    const rows = document.querySelectorAll("#tools-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("handles missing table gracefully", () => {
    document.body.innerHTML = "";
    const consoleSpy = vi.spyOn(console, "warn");
    filterToolsTable("test");
    expect(consoleSpy).toHaveBeenCalledWith("Tools table body not found");
    consoleSpy.mockRestore();
  });

  test("filters by source gateway", () => {
    filterToolsTable("gateway-2");
    const rows = document.querySelectorAll("#tools-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by request type", () => {
    filterToolsTable("POST");
    const rows = document.querySelectorAll("#tools-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by annotation", () => {
    filterToolsTable("annotation3");
    const rows = document.querySelectorAll("#tools-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("filters by owner", () => {
    filterToolsTable("admin@test.com");
    const rows = document.querySelectorAll("#tools-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("filters by team", () => {
    filterToolsTable("team-2");
    const rows = document.querySelectorAll("#tools-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("shows multiple matching rows", () => {
    filterToolsTable("team-1");
    const rows = document.querySelectorAll("#tools-table-body tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("case insensitive search", () => {
    filterToolsTable("READ_FILE");
    const rows = document.querySelectorAll("#tools-table-body tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
  });

  test("handles whitespace in search", () => {
    filterToolsTable("  write_file  ");
    const rows = document.querySelectorAll("#tools-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
  });

  test("filters by multiple tags", () => {
    filterToolsTable("directory");
    const rows = document.querySelectorAll("#tools-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("handles partial matches", () => {
    filterToolsTable("file");
    const rows = document.querySelectorAll("#tools-table-body tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("");
  });

  test("handles no matches", () => {
    filterToolsTable("nonexistent");
    const rows = document.querySelectorAll("#tools-table-body tr");
    rows.forEach((row) => {
      expect(row.style.display).toBe("none");
    });
  });

  test("handles error during filtering", () => {
    document.body.innerHTML = `
      <table id="tools-table">
        <tbody id="tools-table-body">
          <tr><td>Actions</td></tr>
        </tbody>
      </table>
    `;

    const consoleSpy = vi.spyOn(console, "error");
    expect(() => filterToolsTable("test")).not.toThrow();
    consoleSpy.mockRestore();
  });
});

describe("filterResourcesTable", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <table id="resources-table">
        <tbody id="resources-table-body">
          <tr>
            <td>Actions</td>
            <td>gateway-1</td>
            <td>file://test.txt</td>
            <td>A test file</td>
            <td>files</td>
            <td>owner@test.com</td>
            <td>team-1</td>
            <td>Active</td>
          </tr>
          <tr>
            <td>Actions</td>
            <td>gateway-2</td>
            <td>http://api.example.com</td>
            <td>API endpoint</td>
            <td>api</td>
            <td>user@test.com</td>
            <td>team-2</td>
            <td>Inactive</td>
          </tr>
          <tr>
            <td>Actions</td>
            <td>gateway-1</td>
            <td>file://data.json</td>
            <td>JSON data file</td>
            <td>files, data</td>
            <td>admin@test.com</td>
            <td>team-1</td>
            <td>Active</td>
          </tr>
        </tbody>
      </table>
    `;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("shows all rows when search is empty", () => {
    filterResourcesTable("");
    const rows = document.querySelectorAll("#resources-table-body tr");
    rows.forEach((row) => {
      expect(row.style.display).toBe("");
    });
  });

  test("filters by resource name", () => {
    filterResourcesTable("file://test.txt");
    const rows = document.querySelectorAll("#resources-table-body tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by description", () => {
    filterResourcesTable("API endpoint");
    const rows = document.querySelectorAll("#resources-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("handles missing table gracefully", () => {
    document.body.innerHTML = "";
    const consoleSpy = vi.spyOn(console, "warn");
    filterResourcesTable("test");
    expect(consoleSpy).toHaveBeenCalledWith("Resources table body not found");
    consoleSpy.mockRestore();
  });

  test("filters by source gateway", () => {
    filterResourcesTable("gateway-2");
    const rows = document.querySelectorAll("#resources-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by tags", () => {
    filterResourcesTable("api");
    const rows = document.querySelectorAll("#resources-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by owner", () => {
    filterResourcesTable("admin@test.com");
    const rows = document.querySelectorAll("#resources-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("filters by team", () => {
    filterResourcesTable("team-2");
    const rows = document.querySelectorAll("#resources-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by status", () => {
    filterResourcesTable("Inactive");
    const rows = document.querySelectorAll("#resources-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("shows multiple matching rows", () => {
    filterResourcesTable("file://");
    const rows = document.querySelectorAll("#resources-table-body tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("case insensitive search", () => {
    filterResourcesTable("API ENDPOINT");
    const rows = document.querySelectorAll("#resources-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
  });

  test("handles whitespace in search", () => {
    filterResourcesTable("  test.txt  ");
    const rows = document.querySelectorAll("#resources-table-body tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
  });

  test("filters by multiple tags", () => {
    filterResourcesTable("data");
    const rows = document.querySelectorAll("#resources-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("handles partial matches", () => {
    filterResourcesTable("file");
    const rows = document.querySelectorAll("#resources-table-body tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("handles no matches", () => {
    filterResourcesTable("nonexistent");
    const rows = document.querySelectorAll("#resources-table-body tr");
    rows.forEach((row) => {
      expect(row.style.display).toBe("none");
    });
  });

  test("handles error during filtering", () => {
    document.body.innerHTML = `
      <table id="resources-table">
        <tbody id="resources-table-body">
          <tr><td>Actions</td></tr>
        </tbody>
      </table>
    `;

    const consoleSpy = vi.spyOn(console, "error");
    expect(() => filterResourcesTable("test")).not.toThrow();
    consoleSpy.mockRestore();
  });

  test("filters by protocol", () => {
    filterResourcesTable("http://");
    const rows = document.querySelectorAll("#resources-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });
});

describe("filterPromptsTable", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <table id="prompts-table">
        <tbody id="prompts-table-body">
          <tr>
            <td>Actions</td>
            <td>1</td>
            <td>gateway-1</td>
            <td>code_review</td>
            <td>Reviews code</td>
            <td>code</td>
            <td>owner@test.com</td>
            <td>team-1</td>
            <td>Active</td>
          </tr>
          <tr>
            <td>Actions</td>
            <td>2</td>
            <td>gateway-2</td>
            <td>summarize</td>
            <td>Summarizes text</td>
            <td>text</td>
            <td>user@test.com</td>
            <td>team-2</td>
            <td>Inactive</td>
          </tr>
          <tr>
            <td>Actions</td>
            <td>3</td>
            <td>gateway-1</td>
            <td>translate</td>
            <td>Translates text between languages</td>
            <td>text, translation</td>
            <td>admin@test.com</td>
            <td>team-1</td>
            <td>Active</td>
          </tr>
        </tbody>
      </table>
    `;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("shows all rows when search is empty", () => {
    filterPromptsTable("");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    rows.forEach((row) => {
      expect(row.style.display).toBe("");
    });
  });

  test("filters by prompt name", () => {
    filterPromptsTable("code_review");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by description", () => {
    filterPromptsTable("Summarizes text");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("handles missing table gracefully", () => {
    document.body.innerHTML = "";
    const consoleSpy = vi.spyOn(console, "warn");
    filterPromptsTable("test");
    expect(consoleSpy).toHaveBeenCalledWith("Prompts table body not found");
    consoleSpy.mockRestore();
  });

  test("filters by gateway name", () => {
    filterPromptsTable("gateway-2");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by tags", () => {
    filterPromptsTable("translation");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("filters by owner", () => {
    filterPromptsTable("admin@test.com");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("filters by team", () => {
    filterPromptsTable("team-2");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by status", () => {
    filterPromptsTable("Inactive");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("shows multiple matching rows", () => {
    filterPromptsTable("text");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("");
  });

  test("case insensitive search", () => {
    filterPromptsTable("CODE_REVIEW");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
  });

  test("handles whitespace in search", () => {
    filterPromptsTable("  summarize  ");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
  });

  test("filters by multiple tags", () => {
    filterPromptsTable("code");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("none");
  });

  test("handles partial matches", () => {
    filterPromptsTable("trans");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("handles no matches", () => {
    filterPromptsTable("nonexistent");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    rows.forEach((row) => {
      expect(row.style.display).toBe("none");
    });
  });

  test("handles error during filtering", () => {
    document.body.innerHTML = `
      <table id="prompts-table">
        <tbody id="prompts-table-body">
          <tr><td>Actions</td></tr>
        </tbody>
      </table>
    `;

    const consoleSpy = vi.spyOn(console, "error");
    expect(() => filterPromptsTable("test")).not.toThrow();
    consoleSpy.mockRestore();
  });

  test("filters by S.No. column is excluded", () => {
    filterPromptsTable("1");
    const rows = document.querySelectorAll("#prompts-table-body tr");
    // S.No. is in column 1, which should be excluded from search
    // So searching for "1" should match gateway-1 instead
    expect(rows[0].style.display).toBe("");
  });
});

describe("filterA2AAgentsTable", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <table id="agents-table">
        <tbody>
          <tr>
            <td>Actions</td>
            <td>1</td>
            <td>agent-id-1</td>
            <td>Agent One</td>
            <td>First agent</td>
            <td>http://localhost:8001</td>
            <td>a2a</td>
            <td>A2A</td>
            <td>Active</td>
            <td>Reachable</td>
            <td>owner@test.com</td>
            <td>team-1</td>
            <td>public</td>
          </tr>
          <tr>
            <td>Actions</td>
            <td>2</td>
            <td>agent-id-2</td>
            <td>Agent Two</td>
            <td>Second agent</td>
            <td>http://localhost:8002</td>
            <td>mcp</td>
            <td>MCP</td>
            <td>Inactive</td>
            <td>Unreachable</td>
            <td>user@test.com</td>
            <td>team-2</td>
            <td>private</td>
          </tr>
          <tr>
            <td>Actions</td>
            <td>3</td>
            <td>agent-id-3</td>
            <td>Agent Three</td>
            <td>Third agent</td>
            <td>http://localhost:8003</td>
            <td>a2a, mcp</td>
            <td>A2A</td>
            <td>Active</td>
            <td>Reachable</td>
            <td>admin@test.com</td>
            <td>team-1</td>
            <td>public</td>
          </tr>
        </tbody>
      </table>
    `;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("shows all rows when search is empty", () => {
    filterA2AAgentsTable("");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    rows.forEach((row) => {
      expect(row.style.display).toBe("");
    });
  });

  test("filters by agent name", () => {
    filterA2AAgentsTable("Agent One");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by endpoint", () => {
    filterA2AAgentsTable("8002");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by type", () => {
    // Search "MCP" — appears in type column of row 1, and in tags of row 2
    filterA2AAgentsTable("MCP");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe(""); // Matches "mcp" in tags column
  });

  test("handles missing table gracefully", () => {
    document.body.innerHTML = "";
    const consoleSpy = vi.spyOn(console, "warn");
    filterA2AAgentsTable("test");
    expect(consoleSpy).toHaveBeenCalledWith("A2A Agents table body not found");
    consoleSpy.mockRestore();
  });

  test("uses fallback selector for a2a-agents-panel", () => {
    document.body.innerHTML = `
      <div id="a2a-agents-panel">
        <table>
          <tbody>
            <tr>
              <td>Actions</td>
              <td>1</td>
              <td>agent-id-1</td>
              <td>Test Agent</td>
              <td>Description</td>
              <td>http://localhost:8000</td>
              <td>tag</td>
              <td>A2A</td>
              <td>Active</td>
              <td>Reachable</td>
              <td>owner@test.com</td>
              <td>team-1</td>
              <td>public</td>
            </tr>
          </tbody>
        </table>
      </div>
    `;

    filterA2AAgentsTable("Test Agent");
    const rows = document.querySelectorAll("#a2a-agents-panel tbody tr");
    expect(rows[0].style.display).toBe("");
  });

  test("filters by description", () => {
    filterA2AAgentsTable("Second agent");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by tags", () => {
    filterA2AAgentsTable("a2a");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("filters by status", () => {
    filterA2AAgentsTable("Inactive");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by health status", () => {
    filterA2AAgentsTable("Unreachable");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by owner", () => {
    filterA2AAgentsTable("admin@test.com");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("filters by team", () => {
    filterA2AAgentsTable("team-2");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("filters by visibility", () => {
    filterA2AAgentsTable("private");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("none");
  });

  test("shows multiple matching rows", () => {
    filterA2AAgentsTable("Agent");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("");
  });

  test("case insensitive search", () => {
    filterA2AAgentsTable("AGENT ONE");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
  });

  test("handles whitespace in search", () => {
    filterA2AAgentsTable("  Agent Two  ");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
  });

  test("filters by agent ID", () => {
    filterA2AAgentsTable("agent-id-3");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("none");
    expect(rows[2].style.display).toBe("");
  });

  test("filters by partial endpoint", () => {
    filterA2AAgentsTable("localhost");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("");
  });

  test("handles no matches", () => {
    filterA2AAgentsTable("nonexistent");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    rows.forEach((row) => {
      expect(row.style.display).toBe("none");
    });
  });

  test("handles error during filtering", () => {
    document.body.innerHTML = `
      <table id="agents-table">
        <tbody>
          <tr><td>Actions</td></tr>
        </tbody>
      </table>
    `;

    const consoleSpy = vi.spyOn(console, "error");
    expect(() => filterA2AAgentsTable("test")).not.toThrow();
    consoleSpy.mockRestore();
  });

  test("filters by multiple tags", () => {
    filterA2AAgentsTable("mcp");
    const rows = document.querySelectorAll("#agents-table tbody tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).toBe("");
    expect(rows[2].style.display).toBe("");
  });
});

describe("filterGatewaysTable", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="gateways-panel">
        <table>
          <thead>
            <tr>
              <th>Actions</th>
              <th>S.No.</th>
              <th>Name</th>
              <th>URL</th>
              <th>Tags</th>
              <th>Status</th>
              <th>Last Seen</th>
              <th>Owner</th>
              <th>Team</th>
              <th>Visibility</th>
            </tr>
          </thead>
          <tbody>
            <tr data-enabled="true">
              <td>Actions</td>
              <td>1</td>
              <td>Gateway One</td>
              <td>http://localhost:9000</td>
              <td>mcp</td>
              <td>Active</td>
              <td>2024-01-01</td>
              <td>owner@test.com</td>
              <td>team-1</td>
              <td>public</td>
            </tr>
            <tr data-enabled="false">
              <td>Actions</td>
              <td>2</td>
              <td>Gateway Two</td>
              <td>http://localhost:9001</td>
              <td>a2a</td>
              <td>Inactive</td>
              <td>2024-01-02</td>
              <td>user@test.com</td>
              <td>team-2</td>
              <td>private</td>
            </tr>
          </tbody>
        </table>
      </div>
      <input type="checkbox" id="show-inactive-gateways" />
    `;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("shows all enabled rows when search is empty", () => {
    const checkbox = document.getElementById("show-inactive-gateways");
    checkbox.checked = false;

    filterGatewaysTable("");

    const rows = document.querySelectorAll("#gateways-panel tbody tr");
    expect(rows[0].style.display).not.toBe("none");
    expect(rows[1].style.display).toBe("none");
  });

  test("shows all rows when show inactive is checked", () => {
    const checkbox = document.getElementById("show-inactive-gateways");
    checkbox.checked = true;

    filterGatewaysTable("");

    const rows = document.querySelectorAll("#gateways-panel tbody tr");
    expect(rows[0].style.display).not.toBe("none");
    expect(rows[1].style.display).not.toBe("none");
  });

  test("filters by gateway name", () => {
    const checkbox = document.getElementById("show-inactive-gateways");
    checkbox.checked = true;

    filterGatewaysTable("Gateway One");

    const rows = document.querySelectorAll("#gateways-panel tbody tr");
    expect(rows[0].style.display).not.toBe("none");
    expect(rows[1].style.display).toBe("none");
  });

  test("filters by URL", () => {
    const checkbox = document.getElementById("show-inactive-gateways");
    checkbox.checked = true;

    filterGatewaysTable("9001");

    const rows = document.querySelectorAll("#gateways-panel tbody tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).not.toBe("none");
  });

  test("filters by tag", () => {
    const checkbox = document.getElementById("show-inactive-gateways");
    checkbox.checked = true;

    filterGatewaysTable("a2a");

    const rows = document.querySelectorAll("#gateways-panel tbody tr");
    expect(rows[0].style.display).toBe("none");
    expect(rows[1].style.display).not.toBe("none");
  });

  test("handles missing table gracefully", () => {
    document.body.innerHTML = "";
    expect(() => filterGatewaysTable("test")).not.toThrow();
  });

  test("finds table in visible panel", () => {
    document.body.innerHTML = `
      <div class="tab-panel">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>URL</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr data-enabled="true">
              <td>Actions</td>
              <td>1</td>
              <td>Test Gateway</td>
              <td>http://localhost:9000</td>
              <td>tag</td>
              <td>Active</td>
              <td>2024-01-01</td>
              <td>owner@test.com</td>
              <td>team-1</td>
              <td>public</td>
            </tr>
          </tbody>
        </table>
      </div>
    `;

    filterGatewaysTable("Test Gateway");
    const rows = document.querySelectorAll(".tab-panel tbody tr");
    expect(rows[0].style.display).not.toBe("none");
  });
});

describe("toggleViewPublic", () => {
  beforeEach(() => {
    window.htmx = {
      process: vi.fn(),
      trigger: vi.fn(),
    };

    document.body.innerHTML = `
      <input type="checkbox" id="view-public-checkbox" />
      <div id="container-1" hx-get="/api/items?team_id=team-1"></div>
      <div id="container-2" hx-get="/api/other?team_id=team-1"></div>
    `;
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete window.htmx;
  });

  test("adds include_public param when checkbox is checked", () => {
    toggleViewPublic("view-public-checkbox", ["container-1", "container-2"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = true;
    checkbox.onchange();

    const container1 = document.getElementById("container-1");
    const container2 = document.getElementById("container-2");

    expect(container1.getAttribute("hx-get")).toContain("include_public=true");
    expect(container2.getAttribute("hx-get")).toContain("include_public=true");
  });

  test("removes include_public param when checkbox is unchecked", () => {
    toggleViewPublic("view-public-checkbox", ["container-1", "container-2"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = false;
    checkbox.onchange();

    const container1 = document.getElementById("container-1");
    const container2 = document.getElementById("container-2");

    expect(container1.getAttribute("hx-get")).not.toContain("include_public=true");
    expect(container2.getAttribute("hx-get")).not.toContain("include_public=true");
  });

  test("preserves team_id in URL", () => {
    toggleViewPublic("view-public-checkbox", ["container-1"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = true;
    checkbox.onchange();

    const container = document.getElementById("container-1");
    expect(container.getAttribute("hx-get")).toContain("team_id=team-1");
  });

  test("calls htmx.process and htmx.trigger", () => {
    toggleViewPublic("view-public-checkbox", ["container-1"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = true;
    checkbox.onchange();

    expect(window.htmx.process).toHaveBeenCalled();
    expect(window.htmx.trigger).toHaveBeenCalled();
  });

  test("handles missing checkbox gracefully", () => {
    expect(() => {
      toggleViewPublic("nonexistent", ["container-1"], "team-1");
    }).not.toThrow();
  });

  test("handles missing team_id gracefully", () => {
    expect(() => {
      toggleViewPublic("view-public-checkbox", ["container-1"], null);
    }).not.toThrow();

    // Verify checkbox onchange is not set when teamId is null
    const checkbox = document.getElementById("view-public-checkbox");
    expect(checkbox.onchange).toBeNull();
  });

  test("handles missing containers gracefully", () => {
    toggleViewPublic("view-public-checkbox", ["nonexistent"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = true;

    expect(() => checkbox.onchange()).not.toThrow();
  });

  test("preserves gateway_id param when present", async () => {
    const { getSelectedGatewayIds } = await import("../../../mcpgateway/admin_ui/gateways.js");
    getSelectedGatewayIds.mockReturnValue(["gw-1", "gw-2"]);

    toggleViewPublic("view-public-checkbox", ["container-1"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = true;
    checkbox.onchange();

    const container = document.getElementById("container-1");
    expect(container.getAttribute("hx-get")).toContain("gateway_id=gw-1%2Cgw-2");
  });

  test("handles empty container list", () => {
    expect(() => {
      toggleViewPublic("view-public-checkbox", [], "team-1");
    }).not.toThrow();
  });

  test("handles undefined container list", () => {
    expect(() => {
      toggleViewPublic("view-public-checkbox", undefined, "team-1");
    }).not.toThrow();
  });

  test("handles multiple toggles correctly", () => {
    toggleViewPublic("view-public-checkbox", ["container-1"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    const container = document.getElementById("container-1");

    // First toggle: check
    checkbox.checked = true;
    checkbox.onchange();
    expect(container.getAttribute("hx-get")).toContain("include_public=true");

    // Second toggle: uncheck
    checkbox.checked = false;
    checkbox.onchange();
    expect(container.getAttribute("hx-get")).not.toContain("include_public=true");

    // Third toggle: check again
    checkbox.checked = true;
    checkbox.onchange();
    expect(container.getAttribute("hx-get")).toContain("include_public=true");
  });

  test("preserves existing query parameters", () => {
    document.body.innerHTML = `
      <input type="checkbox" id="view-public-checkbox" />
      <div id="container-1" hx-get="/api/items?team_id=team-1&page=2&limit=50"></div>
    `;

    toggleViewPublic("view-public-checkbox", ["container-1"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = true;
    checkbox.onchange();

    const container = document.getElementById("container-1");
    const url = container.getAttribute("hx-get");
    expect(url).toContain("team_id=team-1");
    expect(url).toContain("page=2");
    expect(url).toContain("limit=50");
    expect(url).toContain("include_public=true");
  });

  test("handles URL without query parameters", () => {
    document.body.innerHTML = `
      <input type="checkbox" id="view-public-checkbox" />
      <div id="container-1" hx-get="/api/items"></div>
    `;

    toggleViewPublic("view-public-checkbox", ["container-1"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = true;
    checkbox.onchange();

    const container = document.getElementById("container-1");
    expect(container.getAttribute("hx-get")).toContain("team_id=team-1");
    expect(container.getAttribute("hx-get")).toContain("include_public=true");
  });

  test("handles container without hx-get attribute", () => {
    document.body.innerHTML = `
      <input type="checkbox" id="view-public-checkbox" />
      <div id="container-1"></div>
    `;

    toggleViewPublic("view-public-checkbox", ["container-1"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = true;

    expect(() => checkbox.onchange()).not.toThrow();
  });

  test("calls htmx.trigger with correct element", () => {
    toggleViewPublic("view-public-checkbox", ["container-1"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    const container = document.getElementById("container-1");
    checkbox.checked = true;
    checkbox.onchange();

    expect(window.htmx.trigger).toHaveBeenCalledWith(container, "load");
  });

  test("processes each container individually", () => {
    toggleViewPublic("view-public-checkbox", ["container-1", "container-2"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = true;
    checkbox.onchange();

    expect(window.htmx.process).toHaveBeenCalledTimes(2);
    expect(window.htmx.trigger).toHaveBeenCalledTimes(2);
  });

  test("handles empty gateway_id list", async () => {
    const { getSelectedGatewayIds } = await import("../../../mcpgateway/admin_ui/gateways.js");
    getSelectedGatewayIds.mockReturnValue([]);

    toggleViewPublic("view-public-checkbox", ["container-1"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = true;
    checkbox.onchange();

    const container = document.getElementById("container-1");
    expect(container.getAttribute("hx-get")).not.toContain("gateway_id=");
  });

  test("handles single gateway_id", async () => {
    const { getSelectedGatewayIds } = await import("../../../mcpgateway/admin_ui/gateways.js");
    getSelectedGatewayIds.mockReturnValue(["gw-1"]);

    toggleViewPublic("view-public-checkbox", ["container-1"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = true;
    checkbox.onchange();

    const container = document.getElementById("container-1");
    expect(container.getAttribute("hx-get")).toContain("gateway_id=gw-1");
  });

  test("handles special characters in team_id", () => {
    document.body.innerHTML = `
      <input type="checkbox" id="view-public-checkbox" />
      <div id="container-1" hx-get="/api/items?team_id=team-1%40special"></div>
    `;

    toggleViewPublic("view-public-checkbox", ["container-1"], "team-1@special");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = true;
    checkbox.onchange();

    const container = document.getElementById("container-1");
    expect(container.getAttribute("hx-get")).toContain("team_id=team-1%40special");
  });

  test("handles missing htmx gracefully", () => {
    delete window.htmx;

    toggleViewPublic("view-public-checkbox", ["container-1"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = true;

    // The code will throw when htmx is missing since it calls window.htmx.process()
    // This test verifies the current behavior - if we want graceful handling,
    // the source code would need to check if window.htmx exists first
    expect(() => checkbox.onchange()).toThrow();
  });

  test("removes include_public from URL with multiple params", () => {
    document.body.innerHTML = `
      <input type="checkbox" id="view-public-checkbox" />
      <div id="container-1" hx-get="/api/items?team_id=team-1&include_public=true&page=1"></div>
    `;

    toggleViewPublic("view-public-checkbox", ["container-1"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = false;
    checkbox.onchange();

    const container = document.getElementById("container-1");
    const url = container.getAttribute("hx-get");
    expect(url).not.toContain("include_public=true");
    expect(url).toContain("team_id=team-1");
    expect(url).toContain("page=1");
  });

  test("handles error during URL manipulation", () => {
    document.body.innerHTML = `
      <input type="checkbox" id="view-public-checkbox" />
      <div id="container-1" hx-get="invalid-url"></div>
    `;

    const consoleSpy = vi.spyOn(console, "error");
    toggleViewPublic("view-public-checkbox", ["container-1"], "team-1");

    const checkbox = document.getElementById("view-public-checkbox");
    checkbox.checked = true;

    expect(() => checkbox.onchange()).not.toThrow();
    consoleSpy.mockRestore();
  });
});
