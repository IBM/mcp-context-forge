/**
 * Unit tests for admin.js table filtering functions.
 */

import {
  describe,
  test,
  expect,
  beforeAll,
  beforeEach,
  afterAll,
} from "vitest";
import { createDOMEnvironment } from "./helpers/dom-env.js";
import {
  filterServerTable,
  filterToolsTable,
  filterResourcesTable,
  filterPromptsTable,
  filterA2AAgentsTable,
  filterGatewaysTable,
} from "../../mcpgateway/admin_ui/filters.js";
import {
  filterEntitiesByTags,
  addTagToFilter,
  clearTagFilter,
} from "../../mcpgateway/admin_ui/tags.js";

let env;
let doc;

beforeAll(() => {
  env = createDOMEnvironment();
  doc = env.document;
  global.document = doc;
});

afterAll(() => {
  env.cleanup();
  delete global.document;
});

beforeEach(() => {
  doc.body.textContent = "";
});

// ---------------------------------------------------------------------------
// filterServerTable
// ---------------------------------------------------------------------------
describe("filterServerTable", () => {
  function buildServerTable(rows) {
    const table = doc.createElement("table");
    const tbody = doc.createElement("tbody");
    tbody.id = "servers-table-body";
    rows.forEach((cells) => {
      const tr = doc.createElement("tr");
      tr.setAttribute("data-testid", "server-item");
      cells.forEach((text) => {
        const td = doc.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    doc.body.appendChild(table);
    return tbody;
  }

  test("shows matching rows and hides non-matching", () => {
    // Columns: Actions(0), Icon(1), S.No.(2), UUID(3), Name(4), ...
    const tbody = buildServerTable([
      ["act", "ico", "1", "uuid-1", "Alpha Server", "desc alpha"],
      ["act", "ico", "2", "uuid-2", "Beta Server", "desc beta"],
    ]);
    filterServerTable("alpha");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
  });

  test("empty search shows all rows", () => {
    const tbody = buildServerTable([
      ["act", "ico", "1", "uuid-1", "Alpha", "desc"],
      ["act", "ico", "2", "uuid-2", "Beta", "desc"],
    ]);
    filterServerTable("");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("");
  });

  test("case-insensitive search", () => {
    const tbody = buildServerTable([
      ["act", "ico", "1", "uuid-1", "MyServer", "test"],
    ]);
    filterServerTable("MYSERVER");
    expect(tbody.querySelector("tr").style.display).toBe("");
  });

  test("no table does not throw", () => {
    expect(() => filterServerTable("anything")).not.toThrow();
  });

  test("falls back to data-testid selector", () => {
    // Build without #servers-table-body id
    const table = doc.createElement("table");
    const tbody = doc.createElement("tbody");
    tbody.setAttribute("data-testid", "server-list");
    const tr = doc.createElement("tr");
    tr.setAttribute("data-testid", "server-item");
    ["act", "ico", "1", "uuid", "Fallback Server", "desc"].forEach((t) => {
      const td = doc.createElement("td");
      td.textContent = t;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
    table.appendChild(tbody);
    doc.body.appendChild(table);

    filterServerTable("fallback");
    expect(tr.style.display).toBe("");
  });
});

// ---------------------------------------------------------------------------
// filterToolsTable
// ---------------------------------------------------------------------------
describe("filterToolsTable", () => {
  function buildToolsTable(rows) {
    const table = doc.createElement("table");
    const tbody = doc.createElement("tbody");
    tbody.id = "tools-table-body";
    rows.forEach((cells) => {
      const tr = doc.createElement("tr");
      cells.forEach((text) => {
        const td = doc.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    doc.body.appendChild(table);
    return tbody;
  }

  test("shows matching rows and hides non-matching", () => {
    // Columns: Actions(0), S.No.(1), Source(2), Name(3), ...
    const tbody = buildToolsTable([
      [
        "act",
        "1",
        "REST",
        "get-users",
        "GET",
        "Gets users",
        "",
        "",
        "",
        "",
        "Active",
      ],
      [
        "act",
        "2",
        "MCP",
        "list-files",
        "POST",
        "Lists files",
        "",
        "",
        "",
        "",
        "Active",
      ],
    ]);
    filterToolsTable("get-users");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
  });

  test("empty search shows all rows", () => {
    const tbody = buildToolsTable([
      ["act", "1", "REST", "tool-a", "GET", "desc", "", "", "", "", "Active"],
      ["act", "2", "MCP", "tool-b", "POST", "desc", "", "", "", "", "Active"],
    ]);
    filterToolsTable("");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("");
  });

  test("no table does not throw", () => {
    expect(() => filterToolsTable("anything")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// filterResourcesTable
// ---------------------------------------------------------------------------
describe("filterResourcesTable", () => {
  function buildResourcesTable(rows) {
    const table = doc.createElement("table");
    const tbody = doc.createElement("tbody");
    tbody.id = "resources-table-body";
    rows.forEach((cells) => {
      const tr = doc.createElement("tr");
      cells.forEach((text) => {
        const td = doc.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    doc.body.appendChild(table);
    return tbody;
  }

  test("shows matching rows and hides non-matching", () => {
    // Columns: Actions(0), Source(1), Name(2), ...
    const tbody = buildResourcesTable([
      [
        "act",
        "gateway-1",
        "config-file",
        "Configuration file",
        "prod",
        "admin",
        "team-a",
        "Active",
      ],
      [
        "act",
        "gateway-2",
        "log-file",
        "Log file",
        "staging",
        "dev",
        "team-b",
        "Active",
      ],
    ]);
    filterResourcesTable("config");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
  });

  test("empty search shows all rows", () => {
    const tbody = buildResourcesTable([
      ["act", "gw", "res-a", "desc", "", "", "", ""],
      ["act", "gw", "res-b", "desc", "", "", "", ""],
    ]);
    filterResourcesTable("");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("");
  });

  test("no table does not throw", () => {
    expect(() => filterResourcesTable("anything")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// filterPromptsTable
// ---------------------------------------------------------------------------
describe("filterPromptsTable", () => {
  function buildPromptsTable(rows) {
    const table = doc.createElement("table");
    const tbody = doc.createElement("tbody");
    tbody.id = "prompts-table-body";
    rows.forEach((cells) => {
      const tr = doc.createElement("tr");
      cells.forEach((text) => {
        const td = doc.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    doc.body.appendChild(table);
    return tbody;
  }

  test("shows matching rows and hides non-matching", () => {
    // Columns: Actions(0), S.No.(1), GatewayName(2), Name(3), ...
    const tbody = buildPromptsTable([
      [
        "act",
        "1",
        "gw-1",
        "greeting-prompt",
        "A greeting",
        "tag-a",
        "owner",
        "team",
        "Active",
      ],
      [
        "act",
        "2",
        "gw-2",
        "farewell-prompt",
        "A farewell",
        "tag-b",
        "owner",
        "team",
        "Active",
      ],
    ]);
    filterPromptsTable("greeting");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
  });

  test("empty search shows all rows", () => {
    const tbody = buildPromptsTable([
      ["act", "1", "gw", "p-a", "desc", "", "", "", ""],
      ["act", "2", "gw", "p-b", "desc", "", "", "", ""],
    ]);
    filterPromptsTable("");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("");
  });

  test("no table does not throw", () => {
    expect(() => filterPromptsTable("anything")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// filterA2AAgentsTable
// ---------------------------------------------------------------------------
describe("filterA2AAgentsTable", () => {
  function buildAgentsTable(rows, { usePanel = false } = {}) {
    const wrapper = doc.createElement("div");
    wrapper.id = usePanel ? "a2a-agents-panel" : "agents-table";
    const table = doc.createElement("table");
    const tbody = doc.createElement("tbody");
    rows.forEach((cells) => {
      const tr = doc.createElement("tr");
      cells.forEach((text) => {
        const td = doc.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrapper.appendChild(table);
    doc.body.appendChild(wrapper);
    return tbody;
  }

  test("shows matching rows via #agents-table", () => {
    // Columns: Actions(0), ID(1), Name(2), ...
    const tbody = buildAgentsTable([
      [
        "act",
        "id-1",
        "Weather Agent",
        "Gets weather",
        "http://a",
        "tag",
        "type",
        "Active",
        "OK",
        "owner",
        "team",
        "public",
      ],
      [
        "act",
        "id-2",
        "Search Agent",
        "Does search",
        "http://b",
        "tag",
        "type",
        "Active",
        "OK",
        "owner",
        "team",
        "public",
      ],
    ]);
    filterA2AAgentsTable("weather");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("none");
  });

  test("falls back to #a2a-agents-panel", () => {
    const tbody = buildAgentsTable(
      [
        [
          "act",
          "id-1",
          "Fallback Agent",
          "desc",
          "http://c",
          "",
          "",
          "",
          "",
          "",
          "",
          "",
        ],
      ],
      { usePanel: true }
    );
    filterA2AAgentsTable("fallback");
    expect(tbody.querySelector("tr").style.display).toBe("");
  });

  test("empty search shows all rows", () => {
    const tbody = buildAgentsTable([
      ["act", "id-1", "Agent A", "desc", "", "", "", "", "", "", "", ""],
      ["act", "id-2", "Agent B", "desc", "", "", "", "", "", "", "", ""],
    ]);
    filterA2AAgentsTable("");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("");
  });

  test("no table does not throw", () => {
    expect(() => filterA2AAgentsTable("anything")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// filterGatewaysTable
// ---------------------------------------------------------------------------
describe("filterGatewaysTable", () => {
  function buildGatewaysTable(rows, { enabledValues = [] } = {}) {
    const panel = doc.createElement("div");
    panel.id = "gateways-panel";
    const table = doc.createElement("table");
    const thead = doc.createElement("thead");
    const headerRow = doc.createElement("tr");
    [
      "actions",
      "s.no.",
      "name",
      "url",
      "tags",
      "status",
      "lastseen",
      "owner",
      "team",
      "visibility",
    ].forEach((h) => {
      const th = doc.createElement("th");
      th.textContent = h;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);
    const tbody = doc.createElement("tbody");
    rows.forEach((cells, i) => {
      const tr = doc.createElement("tr");
      if (enabledValues[i] !== undefined) {
        tr.setAttribute("data-enabled", enabledValues[i]);
      }
      cells.forEach((text) => {
        const td = doc.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    panel.appendChild(table);
    doc.body.appendChild(panel);
    return tbody;
  }

  test("shows matching rows and hides non-matching (strategy 1: gateways-panel)", () => {
    const tbody = buildGatewaysTable([
      [
        "act",
        "1",
        "Server Alpha",
        "http://alpha.com",
        "prod",
        "Active",
        "now",
        "admin",
        "team-a",
        "public",
      ],
      [
        "act",
        "2",
        "Server Beta",
        "http://beta.com",
        "staging",
        "Active",
        "now",
        "admin",
        "team-b",
        "public",
      ],
    ]);
    filterGatewaysTable("alpha");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).not.toBe("none");
    expect(rows[1].style.display).toBe("none");
  });

  test("empty search shows all rows", () => {
    const tbody = buildGatewaysTable([
      ["act", "1", "Server A", "http://a.com", "", "Active", "", "", "", ""],
      ["act", "2", "Server B", "http://b.com", "", "Active", "", "", "", ""],
    ]);
    filterGatewaysTable("");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).not.toBe("none");
    expect(rows[1].style.display).not.toBe("none");
  });

  test("integrates inactive filter — hides disabled rows when checkbox unchecked", () => {
    // Create the inactive checkbox
    const cb = doc.createElement("input");
    cb.type = "checkbox";
    cb.id = "show-inactive-gateways";
    cb.checked = false;
    doc.body.appendChild(cb);

    const tbody = buildGatewaysTable(
      [
        [
          "act",
          "1",
          "Enabled GW",
          "http://a.com",
          "",
          "Active",
          "",
          "",
          "",
          "",
        ],
        [
          "act",
          "2",
          "Disabled GW",
          "http://b.com",
          "",
          "Inactive",
          "",
          "",
          "",
          "",
        ],
      ],
      { enabledValues: ["true", "false"] }
    );
    filterGatewaysTable("");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).not.toBe("none");
    expect(rows[1].style.display).toBe("none");
  });

  test("no table does not throw", () => {
    expect(() => filterGatewaysTable("anything")).not.toThrow();
  });

  test("strategy 3: finds table by header matching", () => {
    // Build a table without gateways-panel, with matching headers
    const table = doc.createElement("table");
    const thead = doc.createElement("thead");
    const headerRow = doc.createElement("tr");
    [
      "actions",
      "s.no.",
      "name",
      "url",
      "tags",
      "status",
      "lastseen",
      "owner",
      "team",
      "visibility",
    ].forEach((h) => {
      const th = doc.createElement("th");
      th.textContent = h;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = doc.createElement("tbody");
    const tr = doc.createElement("tr");
    tr.setAttribute("data-enabled", "true");
    [
      "act",
      "1",
      "Found Server",
      "http://found.com",
      "",
      "Active",
      "",
      "",
      "",
      "",
    ].forEach((text) => {
      const td = doc.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
    table.appendChild(tbody);
    doc.body.appendChild(table);

    filterGatewaysTable("found");
    expect(tr.style.display).not.toBe("none");
  });
});

// ---------------------------------------------------------------------------
// addTagToFilter
// ---------------------------------------------------------------------------
describe("addTagToFilter", () => {
  test("adds tag to empty filter input", () => {
    const input = doc.createElement("input");
    input.id = "tools-tag-filter";
    input.value = "";
    doc.body.appendChild(input);

    // Need the panel with tbody for filterEntitiesByTags to work
    const panel = doc.createElement("div");
    panel.id = "tools-panel";
    const table = doc.createElement("table");
    const tbody = doc.createElement("tbody");
    table.appendChild(tbody);
    panel.appendChild(table);
    doc.body.appendChild(panel);

    addTagToFilter("tools", "production");
    expect(input.value).toBe("production");
  });

  test("appends tag to existing tags", () => {
    const input = doc.createElement("input");
    input.id = "tools-tag-filter";
    input.value = "staging";
    doc.body.appendChild(input);

    const panel = doc.createElement("div");
    panel.id = "tools-panel";
    const table = doc.createElement("table");
    table.appendChild(doc.createElement("tbody"));
    panel.appendChild(table);
    doc.body.appendChild(panel);

    addTagToFilter("tools", "production");
    expect(input.value).toContain("staging");
    expect(input.value).toContain("production");
  });

  test("does not add duplicate tag", () => {
    const input = doc.createElement("input");
    input.id = "tools-tag-filter";
    input.value = "production";
    doc.body.appendChild(input);

    const panel = doc.createElement("div");
    panel.id = "tools-panel";
    const table = doc.createElement("table");
    table.appendChild(doc.createElement("tbody"));
    panel.appendChild(table);
    doc.body.appendChild(panel);

    addTagToFilter("tools", "production");
    // Should still just be "production" (not duplicated)
    const tags = input.value
      .split(",")
      .map((t) => t.trim())
      .filter((t) => t);
    expect(tags.filter((t) => t === "production")).toHaveLength(1);
  });

  test("no filter input does not throw", () => {
    expect(() => addTagToFilter("nonexistent", "tag")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// filterEntitiesByTags
// ---------------------------------------------------------------------------
describe("filterEntitiesByTags", () => {
  function buildTaggedTable(entityType, rows) {
    const panel = doc.createElement("div");
    panel.id = `${entityType}-panel`;
    const table = doc.createElement("table");
    const tbody = doc.createElement("tbody");
    rows.forEach(({ text, tags }) => {
      const tr = doc.createElement("tr");
      const td = doc.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
      // Add tag spans
      const tagTd = doc.createElement("td");
      tags.forEach((tag) => {
        const span = doc.createElement("span");
        span.className =
          "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full";
        span.textContent = tag;
        tagTd.appendChild(span);
      });
      tr.appendChild(tagTd);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    panel.appendChild(table);
    doc.body.appendChild(panel);
    return tbody;
  }

  // NOTE: Tests with non-empty filter tags are skipped because
  // filterEntitiesByTags uses CSS comments (/* ... */) in its
  // querySelectorAll selector, which JSDOM's nwsapi cannot parse.

  test("empty filter shows all rows", () => {
    const tbody = buildTaggedTable("tools", [
      { text: "Tool A", tags: ["production"] },
      { text: "Tool B", tags: ["staging"] },
    ]);
    filterEntitiesByTags("tools", "");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).toBe("");
    expect(rows[1].style.display).toBe("");
  });

  test("whitespace-only filter shows all rows", () => {
    const tbody = buildTaggedTable("tools", [
      { text: "Tool A", tags: ["production"] },
    ]);
    filterEntitiesByTags("tools", "  ,  , ");
    const rows = tbody.querySelectorAll("tr");
    expect(rows[0].style.display).toBe("");
  });

  test("no matching panel does not throw", () => {
    expect(() => filterEntitiesByTags("nonexistent", "tag")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// clearTagFilter
// ---------------------------------------------------------------------------
describe("clearTagFilter", () => {
  test("clears filter input and shows all rows", () => {
    const input = doc.createElement("input");
    input.id = "tools-tag-filter";
    input.value = "production";
    doc.body.appendChild(input);

    // Build a panel with rows to verify they become visible
    const panel = doc.createElement("div");
    panel.id = "tools-panel";
    const table = doc.createElement("table");
    const tbody = doc.createElement("tbody");
    const tr = doc.createElement("tr");
    tr.style.display = "none";
    const td = doc.createElement("td");
    td.textContent = "Tool";
    tr.appendChild(td);
    tbody.appendChild(tr);
    table.appendChild(tbody);
    panel.appendChild(table);
    doc.body.appendChild(panel);

    clearTagFilter("tools");
    expect(input.value).toBe("");
    expect(tr.style.display).toBe("");
  });

  test("no filter input does not throw", () => {
    expect(() => clearTagFilter("nonexistent")).not.toThrow();
  });
});
