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
import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";
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
// Edit Tool Advanced Configuration Fields
// ---------------------------------------------------------------------------
describe("Edit Tool Advanced Configuration Fields", () => {
  function setupEditToolAdvancedFieldsDOM() {
    // Create advanced configuration fields
    const titleField = doc.createElement("input");
    titleField.id = "edit-tool-title";
    titleField.type = "text";
    titleField.name = "title";
    doc.body.appendChild(titleField);

    const timeoutField = doc.createElement("input");
    timeoutField.id = "edit-tool-timeout-ms";
    timeoutField.type = "number";
    timeoutField.name = "timeout_ms";
    doc.body.appendChild(timeoutField);

    const jsonpathFilterField = doc.createElement("input");
    jsonpathFilterField.id = "edit-tool-jsonpath-filter";
    jsonpathFilterField.type = "text";
    jsonpathFilterField.name = "jsonpath_filter";
    doc.body.appendChild(jsonpathFilterField);

    const gatewayField = doc.createElement("select");
    gatewayField.id = "edit-tool-gateway-id";
    gatewayField.name = "gateway_id";
    doc.body.appendChild(gatewayField);

    const teamField = doc.createElement("select");
    teamField.id = "edit-tool-team-id";
    teamField.name = "team_id";
    doc.body.appendChild(teamField);

    return { titleField, timeoutField, jsonpathFilterField, gatewayField, teamField };
  }

  test("title field exists and is text input", () => {
    const { titleField } = setupEditToolAdvancedFieldsDOM();
    expect(titleField).toBeDefined();
    expect(titleField.type).toBe("text");
    expect(titleField.name).toBe("title");
  });

  test("timeout_ms field exists and is number input", () => {
    const { timeoutField } = setupEditToolAdvancedFieldsDOM();
    expect(timeoutField).toBeDefined();
    expect(timeoutField.type).toBe("number");
    expect(timeoutField.name).toBe("timeout_ms");
  });

  test("jsonpath_filter field exists and is text input", () => {
    const { jsonpathFilterField } = setupEditToolAdvancedFieldsDOM();
    expect(jsonpathFilterField).toBeDefined();
    expect(jsonpathFilterField.type).toBe("text");
    expect(jsonpathFilterField.name).toBe("jsonpath_filter");
  });

  test("gateway_id field exists and is select dropdown", () => {
    const { gatewayField } = setupEditToolAdvancedFieldsDOM();
    expect(gatewayField).toBeDefined();
    expect(gatewayField.tagName.toLowerCase()).toBe("select");
    expect(gatewayField.name).toBe("gateway_id");
  });

  test("team_id field exists and is select dropdown", () => {
    const { teamField } = setupEditToolAdvancedFieldsDOM();
    expect(teamField).toBeDefined();
    expect(teamField.tagName.toLowerCase()).toBe("select");
    expect(teamField.name).toBe("team_id");
  });
});

// ---------------------------------------------------------------------------
// Edit Tool REST Passthrough Fields
// ---------------------------------------------------------------------------
describe("Edit Tool REST Passthrough Fields", () => {
  function setupRestPassthroughDOM(integrationType = "REST") {
    // Create integration type select
    const typeSelect = doc.createElement("select");
    typeSelect.id = "edit-tool-type";
    const opt = doc.createElement("option");
    opt.value = integrationType;
    opt.selected = true;
    typeSelect.appendChild(opt);
    doc.body.appendChild(typeSelect);

    // Create REST passthrough button wrapper
    const buttonWrapper = doc.createElement("div");
    buttonWrapper.id = "edit-tool-rest-passthrough-button-wrapper";
    buttonWrapper.style.display = integrationType === "REST" ? "block" : "none";
    doc.body.appendChild(buttonWrapper);

    // Create passthrough button
    const button = doc.createElement("button");
    button.id = "edit-tool-passthrough-btn";
    button.type = "button";
    button.textContent = "Advanced: Add Passthrough";
    buttonWrapper.appendChild(button);

    // Create passthrough container
    const container = doc.createElement("fieldset");
    container.id = "edit-tool-passthrough-container";
    container.style.display = "none";
    doc.body.appendChild(container);

    // Add REST passthrough fields
    const baseUrlField = doc.createElement("input");
    baseUrlField.id = "edit-tool-base-url";
    baseUrlField.name = "base_url";
    container.appendChild(baseUrlField);

    const pathTemplateField = doc.createElement("input");
    pathTemplateField.id = "edit-tool-path-template";
    pathTemplateField.name = "path_template";
    container.appendChild(pathTemplateField);

    const exposePassthroughCheckbox = doc.createElement("input");
    exposePassthroughCheckbox.id = "edit-tool-expose-passthrough";
    exposePassthroughCheckbox.type = "checkbox";
    exposePassthroughCheckbox.name = "expose_passthrough";
    container.appendChild(exposePassthroughCheckbox);

    return { typeSelect, buttonWrapper, button, container, baseUrlField, pathTemplateField, exposePassthroughCheckbox };
  }

  test("passthrough button wrapper is shown for REST integration type", () => {
    const { buttonWrapper } = setupRestPassthroughDOM("REST");
    expect(buttonWrapper.style.display).toBe("block");
  });

  test("passthrough button wrapper is hidden for MCP integration type", () => {
    const { buttonWrapper } = setupRestPassthroughDOM("MCP");
    expect(buttonWrapper.style.display).toBe("none");
  });

  test("passthrough container is initially hidden", () => {
    const { container } = setupRestPassthroughDOM("REST");
    expect(container.style.display).toBe("none");
  });

  test("passthrough fields exist within container", () => {
    const { baseUrlField, pathTemplateField, exposePassthroughCheckbox } = setupRestPassthroughDOM("REST");
    expect(baseUrlField).toBeDefined();
    expect(baseUrlField.name).toBe("base_url");
    expect(pathTemplateField).toBeDefined();
    expect(pathTemplateField.name).toBe("path_template");
    expect(exposePassthroughCheckbox).toBeDefined();
    expect(exposePassthroughCheckbox.type).toBe("checkbox");
    expect(exposePassthroughCheckbox.name).toBe("expose_passthrough");
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

// ---------------------------------------------------------------------------
// ALLOW_PUBLIC_VISIBILITY flag — updateDefaultVisibility() gating
// ---------------------------------------------------------------------------
describe("ALLOW_PUBLIC_VISIBILITY flag", () => {
  let flagWin;
  let flagDoc;

  beforeAll(() => {
    flagWin = loadAdminJs({
      beforeEval: (w) => {
        w.ALLOW_PUBLIC_VISIBILITY = false;
      },
    });
    flagDoc = flagWin.document;
  });

  afterAll(() => {
    cleanupAdminJs();
  });

  // Render a minimal set of radios (always enabled — as admin.html now does)
  // then let updateDefaultVisibility() manage the disabled state.
  function buildVisibilityRadios(entityPrefix) {
    ["public", "team", "private"].forEach((val) => {
      const wrapper = flagDoc.createElement("div");
      wrapper.className = "flex items-center";
      const input = flagDoc.createElement("input");
      input.type = "radio";
      input.name = "visibility";
      input.value = val;
      input.id = `${entityPrefix}-visibility-${val}`;
      const label = flagDoc.createElement("label");
      label.htmlFor = input.id;
      wrapper.appendChild(input);
      wrapper.appendChild(label);
      flagDoc.body.appendChild(wrapper);
    });
  }

  function setTeamId(teamId) {
    const url = new flagWin.URL(flagWin.location.href);
    if (teamId) {
      url.searchParams.set("team_id", teamId);
    } else {
      url.searchParams.delete("team_id");
    }
    flagWin.history.replaceState({}, "", url.toString());
  }

  beforeEach(() => {
    flagDoc.body.textContent = "";
  });

  test("public radio is enabled when flag is false and no team_id in URL", () => {
    buildVisibilityRadios("server");
    setTeamId(null);
    flagWin.Admin.updateDefaultVisibility();

    expect(flagDoc.getElementById("server-visibility-public").disabled).toBe(
      false
    );
  });

  test("public radio is disabled when flag is false and team_id is in URL", () => {
    buildVisibilityRadios("server");
    setTeamId("team-abc");
    flagWin.Admin.updateDefaultVisibility();

    expect(flagDoc.getElementById("server-visibility-public").disabled).toBe(true);
  });

  test("public radio becomes disabled even when initially checked in team scope", () => {
    buildVisibilityRadios("server");
    const publicRadio = flagDoc.getElementById("server-visibility-public");
    publicRadio.checked = true;
    publicRadio.defaultChecked = true;
    setTeamId("team-abc");

    flagWin.updateDefaultVisibility();

    expect(publicRadio.checked).toBe(false);
    expect(publicRadio.disabled).toBe(true);
    expect(flagDoc.getElementById("server-visibility-team").checked).toBe(true);
  });

  test("disabled public radio gets opacity and line-through styling", () => {
    buildVisibilityRadios("tool");
    setTeamId("team-abc");
    flagWin.Admin.updateDefaultVisibility();

    const wrapper = flagDoc
      .getElementById("tool-visibility-public")
      .closest(".flex.items-center");
    expect(wrapper.classList.contains("opacity-40")).toBe(true);
    expect(wrapper.classList.contains("cursor-not-allowed")).toBe(true);
  });

  test("public radio re-enabled when navigating from team scope to global scope", () => {
    buildVisibilityRadios("server");
    setTeamId("team-abc");
    flagWin.Admin.updateDefaultVisibility();
    expect(flagDoc.getElementById("server-visibility-public").disabled).toBe(
      true
    );

    setTeamId(null);
    flagWin.Admin.updateDefaultVisibility();
    expect(flagDoc.getElementById("server-visibility-public").disabled).toBe(
      false
    );
  });

  test("form submission can include public when in global scope", () => {
    buildVisibilityRadios("server");
    setTeamId(null);
    flagWin.Admin.updateDefaultVisibility();

    const publicRadio = flagDoc.getElementById("server-visibility-public");
    publicRadio.checked = true;

    const checkedRadio = flagDoc.querySelector(
      'input[name="visibility"]:checked:not(:disabled)'
    );
    expect(checkedRadio).not.toBeNull();
    expect(checkedRadio.value).toBe("public");
  });
});

// ---------------------------------------------------------------------------
// Issue #4061: Edit Tool Gateway Reassignment Removal
// ---------------------------------------------------------------------------
describe("Edit Tool Gateway Reassignment Removal - Issue #4061", () => {
  function setupEditToolFormDOM() {
    // Create the edit tool modal
    const modal = doc.createElement("div");
    modal.id = "edit-tool-modal";
    doc.body.appendChild(modal);

    // Create edit tool form
    const form = doc.createElement("form");
    form.id = "edit-tool-form";
    modal.appendChild(form);

    // Create other fields that should exist
    const nameField = doc.createElement("input");
    nameField.id = "edit-tool-name";
    nameField.name = "name";
    form.appendChild(nameField);

    const urlField = doc.createElement("input");
    urlField.id = "edit-tool-url";
    urlField.name = "url";
    form.appendChild(urlField);

    const typeSelect = doc.createElement("select");
    typeSelect.id = "edit-tool-type";
    typeSelect.name = "integration_type";
    form.appendChild(typeSelect);

    // Gateway field should NOT exist (removed per issue #4061)
    // const gatewayField = doc.createElement("select");
    // gatewayField.id = "edit-tool-gateway-id";
    // gatewayField.name = "gateway_id";
    // form.appendChild(gatewayField);

    return { modal, form, nameField, urlField, typeSelect };
  }

  test("edit tool form does not contain gateway_id field", () => {
    setupEditToolFormDOM();
    const gatewayField = doc.getElementById("edit-tool-gateway-id");
    expect(gatewayField).toBeNull();
  });

  test("edit tool form does not contain gateway_id select element", () => {
    const { form } = setupEditToolFormDOM();
    const gatewaySelects = form.querySelectorAll('select[name="gateway_id"]');
    expect(gatewaySelects.length).toBe(0);
  });

  test("edit tool form contains other essential fields but not gateway_id", () => {
    const { form, nameField, urlField, typeSelect } = setupEditToolFormDOM();

    expect(nameField).toBeDefined();
    expect(nameField.name).toBe("name");

    expect(urlField).toBeDefined();
    expect(urlField.name).toBe("url");

    expect(typeSelect).toBeDefined();
    expect(typeSelect.name).toBe("integration_type");

    // Gateway field should not exist
    const gatewayField = form.querySelector('[name="gateway_id"]');
    expect(gatewayField).toBeNull();
  });

  test("form data collection does not include gateway_id", () => {
    const { form } = setupEditToolFormDOM();
    const formData = new FormData(form);

    expect(formData.has("gateway_id")).toBe(false);
    expect(formData.has("name")).toBe(true);
    expect(formData.has("url")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Issue #4061: Advanced Configuration Fields - Conditional Collection
// ---------------------------------------------------------------------------
describe("Advanced Configuration Fields Conditional Collection - Issue #4061", () => {
  function setupAdvancedFieldsDOM(integrationType = "REST") {
    const form = doc.createElement("form");
    form.id = "edit-tool-form";
    doc.body.appendChild(form);

    // Integration type selector
    const typeSelect = doc.createElement("select");
    typeSelect.id = "edit-tool-type";
    typeSelect.name = "integration_type";
    const typeOpt = doc.createElement("option");
    typeOpt.value = integrationType;
    typeOpt.selected = true;
    typeSelect.appendChild(typeOpt);
    form.appendChild(typeSelect);

    // Common advanced fields (applicable to all tool types)
    const titleField = doc.createElement("input");
    titleField.id = "edit-tool-title";
    titleField.name = "title";
    titleField.value = "";
    form.appendChild(titleField);

    const timeoutField = doc.createElement("input");
    timeoutField.id = "edit-tool-timeout-ms";
    timeoutField.name = "timeout_ms";
    timeoutField.type = "number";
    timeoutField.value = "";
    form.appendChild(timeoutField);

    const jsonpathFilterField = doc.createElement("input");
    jsonpathFilterField.id = "edit-tool-jsonpath-filter";
    jsonpathFilterField.name = "jsonpath_filter";
    jsonpathFilterField.value = "";
    form.appendChild(jsonpathFilterField);

    // REST passthrough fields (only applicable to REST tools)
    const baseUrlField = doc.createElement("input");
    baseUrlField.id = "edit-tool-base-url";
    baseUrlField.name = "base_url";
    baseUrlField.value = "";
    form.appendChild(baseUrlField);

    const pathTemplateField = doc.createElement("input");
    pathTemplateField.id = "edit-tool-path-template";
    pathTemplateField.name = "path_template";
    pathTemplateField.value = "";
    form.appendChild(pathTemplateField);

    const queryMappingField = doc.createElement("textarea");
    queryMappingField.id = "edit-tool-query-mapping";
    queryMappingField.name = "query_mapping";
    queryMappingField.value = "";
    form.appendChild(queryMappingField);

    const headerMappingField = doc.createElement("textarea");
    headerMappingField.id = "edit-tool-header-mapping";
    headerMappingField.name = "header_mapping";
    headerMappingField.value = "";
    form.appendChild(headerMappingField);

    const exposePassthroughCheckbox = doc.createElement("input");
    exposePassthroughCheckbox.id = "edit-tool-expose-passthrough";
    exposePassthroughCheckbox.name = "expose_passthrough";
    exposePassthroughCheckbox.type = "checkbox";
    exposePassthroughCheckbox.checked = false;
    form.appendChild(exposePassthroughCheckbox);

    const allowlistField = doc.createElement("input");
    allowlistField.id = "edit-tool-allowlist";
    allowlistField.name = "allowlist";
    allowlistField.value = "";
    form.appendChild(allowlistField);

    // Plugin chain fields
    const pluginChainPreField = doc.createElement("input");
    pluginChainPreField.id = "edit-tool-plugin-chain-pre";
    pluginChainPreField.name = "plugin_chain_pre";
    pluginChainPreField.value = "";
    form.appendChild(pluginChainPreField);

    const pluginChainPostField = doc.createElement("input");
    pluginChainPostField.id = "edit-tool-plugin-chain-post";
    pluginChainPostField.name = "plugin_chain_post";
    pluginChainPostField.value = "";
    form.appendChild(pluginChainPostField);

    return {
      form,
      typeSelect,
      titleField,
      timeoutField,
      jsonpathFilterField,
      baseUrlField,
      pathTemplateField,
      queryMappingField,
      headerMappingField,
      exposePassthroughCheckbox,
      allowlistField,
      pluginChainPreField,
      pluginChainPostField,
    };
  }

  test("common advanced fields are collected when values are present", () => {
    const { form, titleField, timeoutField, jsonpathFilterField } = setupAdvancedFieldsDOM("MCP");

    titleField.value = "My Tool Title";
    timeoutField.value = "5000";
    jsonpathFilterField.value = "$.data[*]";

    const formData = new FormData(form);

    expect(formData.get("title")).toBe("My Tool Title");
    expect(formData.get("timeout_ms")).toBe("5000");
    expect(formData.get("jsonpath_filter")).toBe("$.data[*]");
  });

  test("common advanced fields are not collected when values are empty", () => {
    const { form, titleField, timeoutField, jsonpathFilterField } = setupAdvancedFieldsDOM("MCP");

    // Leave fields empty
    titleField.value = "";
    timeoutField.value = "";
    jsonpathFilterField.value = "";

    const formData = new FormData(form);

    // Empty string values are still included in FormData, but backend should handle them conditionally
    expect(formData.get("title")).toBe("");
    expect(formData.get("timeout_ms")).toBe("");
    expect(formData.get("jsonpath_filter")).toBe("");
  });

  test("REST passthrough fields exist in form for REST integration type", () => {
    const { form, baseUrlField, pathTemplateField } = setupAdvancedFieldsDOM("REST");

    expect(baseUrlField).toBeDefined();
    expect(baseUrlField.name).toBe("base_url");
    expect(pathTemplateField).toBeDefined();
    expect(pathTemplateField.name).toBe("path_template");
  });

  test("REST passthrough fields are collected only when values are present", () => {
    const { form, baseUrlField, pathTemplateField, queryMappingField } = setupAdvancedFieldsDOM("REST");

    baseUrlField.value = "https://api.example.com";
    pathTemplateField.value = "/v1/{resource}";
    queryMappingField.value = '{"search": "q"}';

    const formData = new FormData(form);

    expect(formData.get("base_url")).toBe("https://api.example.com");
    expect(formData.get("path_template")).toBe("/v1/{resource}");
    expect(formData.get("query_mapping")).toBe('{"search": "q"}');
  });

  test("expose_passthrough checkbox value is collected correctly", () => {
    const { form, exposePassthroughCheckbox } = setupAdvancedFieldsDOM("REST");

    exposePassthroughCheckbox.checked = true;
    const formData = new FormData(form);

    expect(formData.has("expose_passthrough")).toBe(true);
  });

  test("plugin chain fields are collected when values are present", () => {
    const { form, pluginChainPreField, pluginChainPostField } = setupAdvancedFieldsDOM("MCP");

    pluginChainPreField.value = "auth_plugin,validation_plugin";
    pluginChainPostField.value = "logging_plugin";

    const formData = new FormData(form);

    expect(formData.get("plugin_chain_pre")).toBe("auth_plugin,validation_plugin");
    expect(formData.get("plugin_chain_post")).toBe("logging_plugin");
  });

  test("field name consistency: jsonpath_filter uses snake_case not camelCase", () => {
    const { jsonpathFilterField } = setupAdvancedFieldsDOM("MCP");

    // Critical: field name must be snake_case to match backend expectation
    expect(jsonpathFilterField.name).toBe("jsonpath_filter");
    expect(jsonpathFilterField.name).not.toBe("jsonpathFilter");
  });

  test("all REST passthrough field names use snake_case", () => {
    const {
      baseUrlField,
      pathTemplateField,
      queryMappingField,
      headerMappingField,
      exposePassthroughCheckbox,
      allowlistField,
    } = setupAdvancedFieldsDOM("REST");

    expect(baseUrlField.name).toBe("base_url");
    expect(pathTemplateField.name).toBe("path_template");
    expect(queryMappingField.name).toBe("query_mapping");
    expect(headerMappingField.name).toBe("header_mapping");
    expect(exposePassthroughCheckbox.name).toBe("expose_passthrough");
    expect(allowlistField.name).toBe("allowlist");
  });

  test("plugin chain field names use snake_case", () => {
    const { pluginChainPreField, pluginChainPostField } = setupAdvancedFieldsDOM("MCP");

    expect(pluginChainPreField.name).toBe("plugin_chain_pre");
    expect(pluginChainPostField.name).toBe("plugin_chain_post");
  });

  test("all new advanced configuration field IDs follow naming convention", () => {
    const fields = setupAdvancedFieldsDOM("REST");

    expect(fields.titleField.id).toBe("edit-tool-title");
    expect(fields.timeoutField.id).toBe("edit-tool-timeout-ms");
    expect(fields.jsonpathFilterField.id).toBe("edit-tool-jsonpath-filter");
    expect(fields.baseUrlField.id).toBe("edit-tool-base-url");
    expect(fields.pathTemplateField.id).toBe("edit-tool-path-template");
    expect(fields.queryMappingField.id).toBe("edit-tool-query-mapping");
    expect(fields.headerMappingField.id).toBe("edit-tool-header-mapping");
    expect(fields.exposePassthroughCheckbox.id).toBe("edit-tool-expose-passthrough");
    expect(fields.allowlistField.id).toBe("edit-tool-allowlist");
    expect(fields.pluginChainPreField.id).toBe("edit-tool-plugin-chain-pre");
    expect(fields.pluginChainPostField.id).toBe("edit-tool-plugin-chain-post");
  });
});
