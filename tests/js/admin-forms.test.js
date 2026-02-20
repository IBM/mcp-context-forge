/**
 * Unit tests for admin.js form generation and schema functions.
 */

import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  test,
  vi,
} from "vitest";
import { createDOMEnvironment } from "./helpers/dom-env.js";
import {
  generateSchema,
  updateRequestTypeOptions,
  updateEditToolRequestTypes,
} from "../../mcpgateway/admin_ui/formFieldHandlers.js";
import { cleanUpUrlParamsForTab } from "../../mcpgateway/admin_ui/tabs.js";
import { AppState } from "../../mcpgateway/admin_ui/appState.js";
import * as securityModule from "../../mcpgateway/admin_ui/security.js";

let env;
let doc;
let window;

beforeAll(() => {
  env = createDOMEnvironment();
  doc = env.document;
  window = env.window;
  global.document = doc;
  global.window = window;
});

afterAll(() => {
  env.cleanup();
  delete global.document;
  delete global.window;
});

beforeEach(() => {
  doc.body.textContent = "";
});

// ---------------------------------------------------------------------------
// generateSchema
// ---------------------------------------------------------------------------
describe("generateSchema", () => {
  function setupParams(params) {
    // Mock AppState.getParameterCount()
    vi.spyOn(AppState, "getParameterCount").mockReturnValue(params.length);

    params.forEach((p, i) => {
      const idx = i + 1;
      const nameInput = doc.createElement("input");
      nameInput.name = `param_name_${idx}`;
      nameInput.value = p.name;
      doc.body.appendChild(nameInput);

      const typeSelect = doc.createElement("select");
      typeSelect.name = `param_type_${idx}`;
      const opt = doc.createElement("option");
      opt.value = p.type || "string";
      opt.selected = true;
      typeSelect.appendChild(opt);
      doc.body.appendChild(typeSelect);

      const descInput = doc.createElement("input");
      descInput.name = `param_description_${idx}`;
      descInput.value = p.description || "";
      doc.body.appendChild(descInput);

      const reqCheckbox = doc.createElement("input");
      reqCheckbox.type = "checkbox";
      reqCheckbox.name = `param_required_${idx}`;
      reqCheckbox.checked = p.required || false;
      doc.body.appendChild(reqCheckbox);
    });
  }

  test("generates JSON schema from form parameters", () => {
    setupParams([
      {
        name: "query",
        type: "string",
        description: "Search query",
        required: true,
      },
      {
        name: "limit",
        type: "integer",
        description: "Max results",
        required: false,
      },
    ]);
    const result = JSON.parse(generateSchema());
    expect(result.title).toBe("CustomInputSchema");
    expect(result.type).toBe("object");
    expect(result.properties.query).toEqual({
      type: "string",
      description: "Search query",
    });
    expect(result.properties.limit).toEqual({
      type: "integer",
      description: "Max results",
    });
    expect(result.required).toContain("query");
    expect(result.required).not.toContain("limit");
  });

  test("returns empty schema when no parameters", () => {
    setupParams([]);
    const result = JSON.parse(generateSchema());
    expect(result.properties).toEqual({});
    expect(result.required).toEqual([]);
  });

  test("skips parameters with empty names", () => {
    setupParams([
      { name: "", type: "string", description: "empty name" },
      { name: "valid", type: "string", description: "valid param" },
    ]);
    const result = JSON.parse(generateSchema());
    expect(result.properties.valid).toBeDefined();
    expect(Object.keys(result.properties)).toHaveLength(1);
  });

  test("returns valid JSON string", () => {
    setupParams([{ name: "test", type: "string" }]);
    const result = generateSchema();
    expect(() => JSON.parse(result)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// updateRequestTypeOptions
// ---------------------------------------------------------------------------
describe("updateRequestTypeOptions", () => {
  function setupRequestTypeDOM(integrationType) {
    const requestTypeSelect = doc.createElement("select");
    requestTypeSelect.id = "requestType";
    doc.body.appendChild(requestTypeSelect);

    const integrationTypeSelect = doc.createElement("select");
    integrationTypeSelect.id = "integrationType";
    const opt = doc.createElement("option");
    opt.value = integrationType;
    opt.selected = true;
    integrationTypeSelect.appendChild(opt);
    doc.body.appendChild(integrationTypeSelect);

    return requestTypeSelect;
  }

  test("populates options for REST integration", () => {
    const select = setupRequestTypeDOM("REST");
    updateRequestTypeOptions();
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toContain("GET");
    expect(options).toContain("POST");
    expect(options).toContain("PUT");
    expect(options).toContain("PATCH");
    expect(options).toContain("DELETE");
  });

  test("clears options for MCP integration", () => {
    const select = setupRequestTypeDOM("MCP");
    updateRequestTypeOptions();
    expect(select.options.length).toBe(0);
  });

  test("sets preselected value", () => {
    const select = setupRequestTypeDOM("REST");
    updateRequestTypeOptions("PUT");
    expect(select.value).toBe("PUT");
  });

  test("ignores invalid preselected value", () => {
    const select = setupRequestTypeDOM("REST");
    updateRequestTypeOptions("INVALID");
    // Should still have options but value won't be INVALID
    expect(select.options.length).toBeGreaterThan(0);
  });

  test("does not throw when elements missing", () => {
    expect(() => updateRequestTypeOptions()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// updateEditToolRequestTypes
// ---------------------------------------------------------------------------
describe("updateEditToolRequestTypes", () => {
  function setupEditToolDOM(integrationType) {
    const typeSelect = doc.createElement("select");
    typeSelect.id = "edit-tool-type";
    const opt = doc.createElement("option");
    opt.value = integrationType;
    opt.selected = true;
    typeSelect.appendChild(opt);
    doc.body.appendChild(typeSelect);

    const requestTypeSelect = doc.createElement("select");
    requestTypeSelect.id = "edit-tool-request-type";
    doc.body.appendChild(requestTypeSelect);

    return { typeSelect, requestTypeSelect };
  }

  test("populates options for REST type", () => {
    const { requestTypeSelect } = setupEditToolDOM("REST");
    updateEditToolRequestTypes();
    const options = Array.from(requestTypeSelect.options).map((o) => o.value);
    expect(options).toContain("GET");
    expect(options).toContain("POST");
    expect(requestTypeSelect.disabled).toBe(false);
  });

  test("clears and disables for MCP type", () => {
    const { requestTypeSelect } = setupEditToolDOM("MCP");
    updateEditToolRequestTypes();
    expect(requestTypeSelect.options.length).toBe(0);
    expect(requestTypeSelect.disabled).toBe(true);
  });

  test("sets selected method when provided", () => {
    const { requestTypeSelect } = setupEditToolDOM("REST");
    updateEditToolRequestTypes("DELETE");
    expect(requestTypeSelect.value).toBe("DELETE");
  });

  test("does not set invalid method", () => {
    const { requestTypeSelect } = setupEditToolDOM("REST");
    updateEditToolRequestTypes("INVALID");
    // Value should be first option (GET) since INVALID is not in list
    expect(requestTypeSelect.value).toBe("GET");
  });

  test("does not throw when elements missing", () => {
    expect(() => updateEditToolRequestTypes()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// cleanUpUrlParamsForTab
// ---------------------------------------------------------------------------
describe("cleanUpUrlParamsForTab", () => {
  beforeEach(() => {
    // Mock safeReplaceState globally
    vi.spyOn(securityModule, "safeReplaceState").mockImplementation(() => {});
    // Reset window.location to clean state
    window.history.replaceState({}, "", window.location.pathname);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("preserves only params for the target tab's tables", () => {
    // Set up a panel with pagination controls
    const panel = doc.createElement("div");
    panel.id = "tools-panel";
    const ctrl = doc.createElement("div");
    ctrl.id = "tools-pagination-controls";
    panel.appendChild(ctrl);
    doc.body.appendChild(panel);

    // Set window.location to have mixed params
    const url = new window.URL(window.location.href);
    url.searchParams.set("tools_page", "2");
    url.searchParams.set("servers_page", "3");
    url.searchParams.set("team_id", "team-123");
    window.history.replaceState({}, "", url.toString());

    cleanUpUrlParamsForTab("tools");

    // Check the call to safeReplaceState
    expect(securityModule.safeReplaceState).toHaveBeenCalled();
    const callArgs = securityModule.safeReplaceState.mock.calls[0];
    const capturedUrl = callArgs[2];

    expect(capturedUrl).toContain("tools_page=2");
    expect(capturedUrl).toContain("team_id=team-123");
    expect(capturedUrl).not.toContain("servers_page");
  });

  test("preserves team_id as global param", () => {
    const panel = doc.createElement("div");
    panel.id = "overview-panel";
    doc.body.appendChild(panel);

    const url = new window.URL(window.location.href);
    url.searchParams.set("team_id", "my-team");
    window.history.replaceState({}, "", url.toString());

    cleanUpUrlParamsForTab("overview");

    const callArgs = securityModule.safeReplaceState.mock.calls[0];
    const capturedUrl = callArgs[2];
    expect(capturedUrl).toContain("team_id=my-team");
  });

  test("removes all non-matching params", () => {
    const panel = doc.createElement("div");
    panel.id = "gateways-panel";
    const ctrl = doc.createElement("div");
    ctrl.id = "gateways-pagination-controls";
    panel.appendChild(ctrl);
    doc.body.appendChild(panel);

    const url = new window.URL(window.location.href);
    url.searchParams.set("tools_page", "1");
    url.searchParams.set("resources_page", "2");
    window.history.replaceState({}, "", url.toString());

    cleanUpUrlParamsForTab("gateways");

    const callArgs = securityModule.safeReplaceState.mock.calls[0];
    const capturedUrl = callArgs[2];
    expect(capturedUrl).not.toContain("tools_page");
    expect(capturedUrl).not.toContain("resources_page");
  });
});
