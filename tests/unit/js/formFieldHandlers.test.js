/**
 * Unit tests for formFieldHandlers.js module
 * Tests: generateSchema, updateSchemaPreview, createParameterForm,
 *        handleAddParameter, updateRequestTypeOptions, updateEditToolRequestTypes,
 *        handleAddPassthrough, searchTeamSelector, performTeamSelectorSearch,
 *        selectTeamFromSelector
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import {
  generateSchema,
  updateSchemaPreview,
  createParameterForm,
  handleAddParameter,
  updateRequestTypeOptions,
  updateEditToolRequestTypes,
  handleAddPassthrough,
  searchTeamSelector,
  performTeamSelectorSearch,
  selectTeamFromSelector,
} from "../../../mcpgateway/admin_ui/formFieldHandlers.js";
import { AppState } from "../../../mcpgateway/admin_ui/appState.js";

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  validateInputName: vi.fn((name) => {
    if (!name || typeof name !== "string" || name.trim() === "") {
      return { valid: false, error: "parameter is required" };
    }
    return { valid: true, value: name.trim() };
  }),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));

beforeEach(() => {
  AppState.parameterCount = 0;
  vi.useFakeTimers();
});

afterEach(() => {
  document.body.innerHTML = "";
  AppState.parameterCount = 0;
  vi.restoreAllMocks();
  vi.useRealTimers();
  delete window.schemaEditor;
  delete window.htmx;
  delete window.updateTeamContext;
  delete window.ROOT_PATH;
});

// ---------------------------------------------------------------------------
// generateSchema
// ---------------------------------------------------------------------------
describe("generateSchema", () => {
  test("returns empty schema when no parameters exist", () => {
    AppState.parameterCount = 0;
    const schema = JSON.parse(generateSchema());
    expect(schema.type).toBe("object");
    expect(schema.properties).toEqual({});
    expect(schema.required).toEqual([]);
  });

  test("generates schema from parameter form fields", () => {
    AppState.parameterCount = 2;

    const name1 = document.createElement("input");
    name1.name = "param_name_1";
    name1.value = "query";
    document.body.appendChild(name1);

    const type1 = document.createElement("select");
    type1.name = "param_type_1";
    const opt1 = document.createElement("option");
    opt1.value = "string";
    opt1.textContent = "string";
    type1.appendChild(opt1);
    type1.value = "string";
    document.body.appendChild(type1);

    const desc1 = document.createElement("textarea");
    desc1.name = "param_description_1";
    desc1.value = "Search query";
    document.body.appendChild(desc1);

    const req1 = document.createElement("input");
    req1.type = "checkbox";
    req1.name = "param_required_1";
    req1.checked = true;
    document.body.appendChild(req1);

    const name2 = document.createElement("input");
    name2.name = "param_name_2";
    name2.value = "limit";
    document.body.appendChild(name2);

    const type2 = document.createElement("select");
    type2.name = "param_type_2";
    const opt2 = document.createElement("option");
    opt2.value = "number";
    opt2.textContent = "number";
    type2.appendChild(opt2);
    type2.value = "number";
    document.body.appendChild(type2);

    const desc2 = document.createElement("textarea");
    desc2.name = "param_description_2";
    desc2.value = "Result limit";
    document.body.appendChild(desc2);

    const req2 = document.createElement("input");
    req2.type = "checkbox";
    req2.name = "param_required_2";
    req2.checked = false;
    document.body.appendChild(req2);

    const schema = JSON.parse(generateSchema());
    expect(schema.properties.query).toEqual({ type: "string", description: "Search query" });
    expect(schema.properties.limit).toEqual({ type: "number", description: "Result limit" });
    expect(schema.required).toEqual(["query"]);
  });

  test("skips parameters with empty names", () => {
    AppState.parameterCount = 1;

    const name = document.createElement("input");
    name.name = "param_name_1";
    name.value = "";
    document.body.appendChild(name);

    const schema = JSON.parse(generateSchema());
    expect(schema.properties).toEqual({});
  });

  test("skips parameters with invalid names", async () => {
    const { validateInputName } = await import("../../../mcpgateway/admin_ui/security.js");
    validateInputName.mockReturnValueOnce({ valid: false, error: "invalid" });

    AppState.parameterCount = 1;
    const name = document.createElement("input");
    name.name = "param_name_1";
    name.value = "<script>";
    document.body.appendChild(name);

    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const schema = JSON.parse(generateSchema());
    expect(schema.properties).toEqual({});
    warnSpy.mockRestore();
  });

  test("uses 'string' as default type when typeField is absent", () => {
    AppState.parameterCount = 1;

    const name = document.createElement("input");
    name.name = "param_name_1";
    name.value = "myparam";
    document.body.appendChild(name);
    // No type field added — should default to "string"

    const schema = JSON.parse(generateSchema());
    expect(schema.properties.myparam.type).toBe("string");
  });

  test("uses empty string for description when descField is absent", () => {
    AppState.parameterCount = 1;

    const name = document.createElement("input");
    name.name = "param_name_1";
    name.value = "myparam";
    document.body.appendChild(name);
    // No desc field

    const schema = JSON.parse(generateSchema());
    expect(schema.properties.myparam.description).toBe("");
  });

  test("handles errors thrown during parameter processing", () => {
    AppState.parameterCount = 1;

    // Make document.querySelector throw for this parameter
    const origQuerySelector = document.querySelector.bind(document);
    const spy = vi.spyOn(document, "querySelector").mockImplementationOnce(() => {
      throw new Error("DOM error");
    });

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const schema = JSON.parse(generateSchema());
    expect(schema.properties).toEqual({});
    errorSpy.mockRestore();
    spy.mockRestore();
  });

  test("schema title and structure are correct", () => {
    AppState.parameterCount = 0;
    const schema = JSON.parse(generateSchema());
    expect(schema.title).toBe("CustomInputSchema");
    expect(schema.type).toBe("object");
  });
});

// ---------------------------------------------------------------------------
// updateSchemaPreview
// ---------------------------------------------------------------------------
describe("updateSchemaPreview", () => {
  test("does nothing when no radio button is checked", () => {
    expect(() => updateSchemaPreview()).not.toThrow();
  });

  test("calls schemaEditor.setValue when mode is json", () => {
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "schema_input_mode";
    radio.value = "json";
    radio.checked = true;
    document.body.appendChild(radio);

    window.schemaEditor = { setValue: vi.fn() };
    AppState.parameterCount = 0;

    updateSchemaPreview();
    expect(window.schemaEditor.setValue).toHaveBeenCalled();
  });

  test("does not call setValue when mode is not json", () => {
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "schema_input_mode";
    radio.value = "form";
    radio.checked = true;
    document.body.appendChild(radio);

    window.schemaEditor = { setValue: vi.fn() };
    updateSchemaPreview();
    expect(window.schemaEditor.setValue).not.toHaveBeenCalled();
  });

  test("does not throw when schemaEditor.setValue is not a function", () => {
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "schema_input_mode";
    radio.value = "json";
    radio.checked = true;
    document.body.appendChild(radio);

    window.schemaEditor = { setValue: "not-a-function" };
    expect(() => updateSchemaPreview()).not.toThrow();
  });

  test("does not throw when schemaEditor is absent", () => {
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "schema_input_mode";
    radio.value = "json";
    radio.checked = true;
    document.body.appendChild(radio);

    delete window.schemaEditor;
    expect(() => updateSchemaPreview()).not.toThrow();
  });

  test("catches errors and logs them", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    // Force an error by making document.querySelector throw
    const spy = vi.spyOn(document, "querySelector").mockImplementationOnce(() => {
      throw new Error("forced");
    });
    expect(() => updateSchemaPreview()).not.toThrow();
    errorSpy.mockRestore();
    spy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// createParameterForm
// ---------------------------------------------------------------------------
describe("createParameterForm", () => {
  test("creates a parameter form container with correct structure", () => {
    const form = createParameterForm(1);
    expect(form).toBeInstanceOf(HTMLElement);
    expect(form.querySelector('input[name="param_name_1"]')).not.toBeNull();
    expect(form.querySelector('select[name="param_type_1"]')).not.toBeNull();
    expect(form.querySelector('textarea[name="param_description_1"]')).not.toBeNull();
    expect(form.querySelector('input[name="param_required_1"]')).not.toBeNull();
  });

  test("includes delete button", () => {
    const form = createParameterForm(1);
    const deleteBtn = form.querySelector(".delete-param");
    expect(deleteBtn).not.toBeNull();
    expect(deleteBtn.textContent).toBe("×");
  });

  test("includes all type options", () => {
    const form = createParameterForm(1);
    const options = form.querySelectorAll('select[name="param_type_1"] option');
    const values = Array.from(options).map((o) => o.value);
    expect(values).toContain("string");
    expect(values).toContain("number");
    expect(values).toContain("boolean");
    expect(values).toContain("object");
    expect(values).toContain("array");
  });

  test("uses parameterCount in field names", () => {
    const form = createParameterForm(5);
    expect(form.querySelector('input[name="param_name_5"]')).not.toBeNull();
    expect(form.querySelector('select[name="param_type_5"]')).not.toBeNull();
  });

  test("required checkbox is checked by default", () => {
    const form = createParameterForm(1);
    const checkbox = form.querySelector('input[name="param_required_1"]');
    expect(checkbox.checked).toBe(true);
  });

  test("name input blur handler sets custom validity for invalid name", async () => {
    const { validateInputName } = await import("../../../mcpgateway/admin_ui/security.js");
    validateInputName.mockReturnValueOnce({ valid: false, error: "bad name" });

    const form = createParameterForm(1);
    const nameInput = form.querySelector('input[name="param_name_1"]');
    nameInput.value = "bad!name";

    const setCustomValiditySpy = vi.spyOn(nameInput, "setCustomValidity");
    const reportValiditySpy = vi.spyOn(nameInput, "reportValidity").mockImplementation(() => {});

    nameInput.dispatchEvent(new Event("blur"));

    expect(setCustomValiditySpy).toHaveBeenCalledWith("bad name");
    expect(reportValiditySpy).toHaveBeenCalled();
  });

  test("name input blur handler clears validity and cleans value for valid name", async () => {
    const { validateInputName } = await import("../../../mcpgateway/admin_ui/security.js");
    validateInputName.mockReturnValueOnce({ valid: true, value: "clean_name" });

    const form = createParameterForm(1);
    const nameInput = form.querySelector('input[name="param_name_1"]');
    nameInput.value = "  clean_name  ";

    const setCustomValiditySpy = vi.spyOn(nameInput, "setCustomValidity");

    nameInput.dispatchEvent(new Event("blur"));

    expect(setCustomValiditySpy).toHaveBeenCalledWith("");
    expect(nameInput.value).toBe("clean_name");
  });

  test("parameter title text matches parameterCount", () => {
    const form = createParameterForm(3);
    const title = form.querySelector("span");
    expect(title.textContent).toBe("Parameter 3");
  });
});

// ---------------------------------------------------------------------------
// handleAddParameter
// ---------------------------------------------------------------------------
describe("handleAddParameter", () => {
  test("adds a parameter div to the container", () => {
    const container = document.createElement("div");
    container.id = "parameters-container";
    document.body.appendChild(container);

    AppState.parameterCount = 0;
    handleAddParameter();

    expect(container.children.length).toBe(1);
    expect(AppState.parameterCount).toBe(1);
  });

  test("rollbacks parameterCount when container is not found", () => {
    // No container in DOM
    AppState.parameterCount = 0;
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    handleAddParameter();

    expect(AppState.parameterCount).toBe(0);
    errorSpy.mockRestore();
  });

  test("clicking delete button removes param div and decrements count", () => {
    const container = document.createElement("div");
    container.id = "parameters-container";
    document.body.appendChild(container);

    AppState.parameterCount = 0;
    handleAddParameter();

    expect(container.children.length).toBe(1);
    expect(AppState.parameterCount).toBe(1);

    const deleteBtn = container.querySelector(".delete-param");
    expect(deleteBtn).not.toBeNull();
    deleteBtn.click();

    expect(container.children.length).toBe(0);
    expect(AppState.parameterCount).toBe(0);
  });

  test("multiple parameters can be added", () => {
    const container = document.createElement("div");
    container.id = "parameters-container";
    document.body.appendChild(container);

    AppState.parameterCount = 0;
    handleAddParameter();
    handleAddParameter();
    handleAddParameter();

    expect(container.children.length).toBe(3);
    expect(AppState.parameterCount).toBe(3);
  });

  test("catches errors thrown during delete click handler", () => {
    const container = document.createElement("div");
    container.id = "parameters-container";
    document.body.appendChild(container);

    AppState.parameterCount = 0;
    handleAddParameter();

    const paramDiv = container.firstElementChild;
    const removespy = vi.spyOn(paramDiv, "remove").mockImplementationOnce(() => {
      throw new Error("remove failed");
    });

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const deleteBtn = container.querySelector(".delete-param");
    deleteBtn.click();

    expect(errorSpy).toHaveBeenCalledWith("Error removing parameter:", expect.any(Error));
    errorSpy.mockRestore();
    removespy.mockRestore();
  });

  test("rollbacks parameterCount when DOM creation throws", () => {
    const container = document.createElement("div");
    container.id = "parameters-container";
    document.body.appendChild(container);

    AppState.parameterCount = 0;
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    // Make appendChild throw
    const origAppendChild = container.appendChild.bind(container);
    vi.spyOn(container, "appendChild").mockImplementationOnce(() => {
      throw new Error("append failed");
    });

    handleAddParameter();

    expect(AppState.parameterCount).toBe(0);
    errorSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// updateRequestTypeOptions
// ---------------------------------------------------------------------------
describe("updateRequestTypeOptions", () => {
  function setupIntegrationElements(integrationType) {
    const requestTypeSelect = document.createElement("select");
    requestTypeSelect.id = "requestType";
    document.body.appendChild(requestTypeSelect);

    const integrationTypeSelect = document.createElement("select");
    integrationTypeSelect.id = "integrationType";
    const opt = document.createElement("option");
    opt.value = integrationType;
    integrationTypeSelect.appendChild(opt);
    integrationTypeSelect.value = integrationType;
    document.body.appendChild(integrationTypeSelect);

    return { requestTypeSelect, integrationTypeSelect };
  }

  test("does nothing when requestType element is missing", () => {
    // Only integrationType present
    const integrationTypeSelect = document.createElement("select");
    integrationTypeSelect.id = "integrationType";
    document.body.appendChild(integrationTypeSelect);

    expect(() => updateRequestTypeOptions()).not.toThrow();
  });

  test("does nothing when integrationType element is missing", () => {
    const requestTypeSelect = document.createElement("select");
    requestTypeSelect.id = "requestType";
    document.body.appendChild(requestTypeSelect);

    expect(() => updateRequestTypeOptions()).not.toThrow();
  });

  test("populates REST methods for REST integration", () => {
    const { requestTypeSelect } = setupIntegrationElements("REST");

    updateRequestTypeOptions();

    const options = Array.from(requestTypeSelect.options).map((o) => o.value);
    expect(options).toEqual(["GET", "POST", "PUT", "PATCH", "DELETE"]);
  });

  test("clears options for MCP integration", () => {
    const { requestTypeSelect } = setupIntegrationElements("MCP");

    updateRequestTypeOptions();

    expect(requestTypeSelect.options.length).toBe(0);
  });

  test("sets preselected value when it is in the options list", () => {
    const { requestTypeSelect } = setupIntegrationElements("REST");

    updateRequestTypeOptions("POST");

    expect(requestTypeSelect.value).toBe("POST");
  });

  test("ignores preselected value when not in the options list", () => {
    const { requestTypeSelect } = setupIntegrationElements("REST");

    updateRequestTypeOptions("INVALID");

    // Should not throw and value remains whatever jsdom sets
    expect(() => updateRequestTypeOptions("INVALID")).not.toThrow();
  });

  test("uses empty options for unknown integration type", () => {
    const { requestTypeSelect } = setupIntegrationElements("UNKNOWN");

    updateRequestTypeOptions();

    expect(requestTypeSelect.options.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// updateEditToolRequestTypes
// ---------------------------------------------------------------------------
describe("updateEditToolRequestTypes", () => {
  function setupEditToolElements(toolType) {
    const editToolTypeSelect = document.createElement("select");
    editToolTypeSelect.id = "edit-tool-type";
    const opt = document.createElement("option");
    opt.value = toolType;
    editToolTypeSelect.appendChild(opt);
    editToolTypeSelect.value = toolType;
    document.body.appendChild(editToolTypeSelect);

    const editToolRequestTypeSelect = document.createElement("select");
    editToolRequestTypeSelect.id = "edit-tool-request-type";
    document.body.appendChild(editToolRequestTypeSelect);

    return { editToolTypeSelect, editToolRequestTypeSelect };
  }

  test("does nothing when edit-tool-type element is missing", () => {
    const editToolRequestTypeSelect = document.createElement("select");
    editToolRequestTypeSelect.id = "edit-tool-request-type";
    document.body.appendChild(editToolRequestTypeSelect);

    expect(() => updateEditToolRequestTypes()).not.toThrow();
  });

  test("does nothing when edit-tool-request-type element is missing", () => {
    const editToolTypeSelect = document.createElement("select");
    editToolTypeSelect.id = "edit-tool-type";
    document.body.appendChild(editToolTypeSelect);

    expect(() => updateEditToolRequestTypes()).not.toThrow();
  });

  test("disables and clears request type select for MCP", () => {
    const { editToolRequestTypeSelect } = setupEditToolElements("MCP");

    updateEditToolRequestTypes();

    expect(editToolRequestTypeSelect.disabled).toBe(true);
    expect(editToolRequestTypeSelect.options.length).toBe(0);
    expect(editToolRequestTypeSelect.value).toBe("");
  });

  test("enables and populates request type select for REST", () => {
    const { editToolRequestTypeSelect } = setupEditToolElements("REST");

    updateEditToolRequestTypes();

    expect(editToolRequestTypeSelect.disabled).toBe(false);
    const options = Array.from(editToolRequestTypeSelect.options).map((o) => o.value);
    expect(options).toEqual(["GET", "POST", "PUT", "PATCH", "DELETE"]);
  });

  test("sets selectedMethod when it is in the options", () => {
    const { editToolRequestTypeSelect } = setupEditToolElements("REST");

    updateEditToolRequestTypes("PUT");

    expect(editToolRequestTypeSelect.value).toBe("PUT");
  });

  test("does not set selectedMethod when not in options", () => {
    const { editToolRequestTypeSelect } = setupEditToolElements("REST");

    updateEditToolRequestTypes("CONNECT");

    // Value is not set to CONNECT since it's not in the list
    const options = Array.from(editToolRequestTypeSelect.options).map((o) => o.value);
    expect(options).not.toContain("CONNECT");
  });

  test("stores prevValue as dataset attribute on first call", () => {
    const { editToolTypeSelect } = setupEditToolElements("REST");

    updateEditToolRequestTypes();

    expect(editToolTypeSelect.dataset.prevValue).toBe("REST");
  });

  test("does not overwrite prevValue if already set", () => {
    const { editToolTypeSelect } = setupEditToolElements("REST");
    editToolTypeSelect.dataset.prevValue = "MCP"; // already set

    updateEditToolRequestTypes();

    expect(editToolTypeSelect.dataset.prevValue).toBe("MCP");
  });
});

// ---------------------------------------------------------------------------
// handleAddPassthrough
// ---------------------------------------------------------------------------
describe("handleAddPassthrough", () => {
  function addPassthroughContainer(displayStyle = "") {
    const container = document.createElement("div");
    container.id = "passthrough-container";
    container.style.display = displayStyle;
    document.body.appendChild(container);
    return container;
  }

  test("logs error when passthrough-container is not found", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    handleAddPassthrough();
    expect(errorSpy).toHaveBeenCalledWith("Passthrough container not found");
    errorSpy.mockRestore();
  });

  test("shows container when display is empty", () => {
    const container = addPassthroughContainer("");
    handleAddPassthrough();
    expect(container.style.display).toBe("block");
  });

  test("shows container when display is none", () => {
    const container = addPassthroughContainer("none");
    handleAddPassthrough();
    expect(container.style.display).toBe("block");
  });

  test("hides container when display is block", () => {
    const container = addPassthroughContainer("block");
    handleAddPassthrough();
    expect(container.style.display).toBe("none");
  });

  test("adds query-mapping-field on first show", () => {
    addPassthroughContainer("");
    handleAddPassthrough();
    expect(document.getElementById("query-mapping-field")).not.toBeNull();
  });

  test("adds header-mapping-field on first show", () => {
    addPassthroughContainer("");
    handleAddPassthrough();
    expect(document.getElementById("header-mapping-field")).not.toBeNull();
  });

  test("adds timeout-ms-field on first show", () => {
    addPassthroughContainer("");
    handleAddPassthrough();
    expect(document.getElementById("timeout-ms-field")).not.toBeNull();
  });

  test("adds expose-passthrough-field on first show", () => {
    addPassthroughContainer("");
    handleAddPassthrough();
    expect(document.getElementById("expose-passthrough-field")).not.toBeNull();
  });

  test("adds allowlist-field on first show", () => {
    addPassthroughContainer("");
    handleAddPassthrough();
    expect(document.getElementById("allowlist-field")).not.toBeNull();
  });

  test("adds plugin-chain-pre-field on first show", () => {
    addPassthroughContainer("");
    handleAddPassthrough();
    expect(document.getElementById("plugin-chain-pre-field")).not.toBeNull();
  });

  test("adds plugin-chain-post-field on first show", () => {
    addPassthroughContainer("");
    handleAddPassthrough();
    expect(document.getElementById("plugin-chain-post-field")).not.toBeNull();
  });

  test("does not duplicate fields on second show", () => {
    addPassthroughContainer("");
    handleAddPassthrough(); // show + add fields

    // Reset to hidden so second call shows again
    const container = document.getElementById("passthrough-container");
    container.style.display = "none";
    handleAddPassthrough(); // show again, should not add duplicate fields

    expect(document.querySelectorAll("#query-mapping-field").length).toBe(1);
    expect(document.querySelectorAll("#header-mapping-field").length).toBe(1);
    expect(document.querySelectorAll("#timeout-ms-field").length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// searchTeamSelector (debounce)
// ---------------------------------------------------------------------------
describe("searchTeamSelector", () => {
  test("debounces and calls performTeamSelectorSearch after 300ms", () => {
    // We set up the container so performTeamSelectorSearch doesn't error
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve("<div>teams</div>"),
    });

    searchTeamSelector("test");
    // Not called immediately
    expect(container.innerHTML).toBe("");

    vi.advanceTimersByTime(300);
    // After 300ms, loading indicator is set
    expect(container.innerHTML).toContain("Loading");
  });

  test("cancels previous debounce when called multiple times", () => {
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve("<div>teams</div>"),
    });

    searchTeamSelector("a");
    searchTeamSelector("ab");
    searchTeamSelector("abc");

    vi.advanceTimersByTime(300);
    // fetch should only be called once (for the last "abc")
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// performTeamSelectorSearch
// ---------------------------------------------------------------------------
describe("performTeamSelectorSearch", () => {
  test("logs error when team-selector-items container is missing", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    performTeamSelectorSearch("test");
    expect(errorSpy).toHaveBeenCalledWith("team-selector-items container not found");
    errorSpy.mockRestore();
  });

  test("shows loading indicator immediately", () => {
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve("<div>teams</div>"),
    });

    performTeamSelectorSearch("test");
    expect(container.innerHTML).toContain("Loading");
  });

  test("builds URL without q param when searchTerm is empty", async () => {
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve("<div>teams</div>"),
    });

    performTeamSelectorSearch("");
    await vi.runAllTimersAsync();

    const url = fetch.mock.calls[0][0];
    expect(url).not.toContain("q=");
    expect(url).toContain("render=selector");
  });

  test("builds URL with q param when searchTerm is provided", async () => {
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve("<div>teams</div>"),
    });

    performTeamSelectorSearch("myteam");
    await vi.runAllTimersAsync();

    const url = fetch.mock.calls[0][0];
    expect(url).toContain("q=myteam");
  });

  test("uses ROOT_PATH when set", async () => {
    window.ROOT_PATH = "/custom-root";
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve("<div>teams</div>"),
    });

    performTeamSelectorSearch("");
    await vi.runAllTimersAsync();

    const url = fetch.mock.calls[0][0];
    expect(url).toContain("/custom-root/admin/teams/partial");
  });

  test("sets innerHTML with fetched HTML on success", async () => {
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve("<div>team-list</div>"),
    });

    performTeamSelectorSearch("test");
    await vi.runAllTimersAsync();

    expect(container.innerHTML).toBe("<div>team-list</div>");
    expect(container.dataset.loaded).toBe("true");
  });

  test("processes htmx on the container when htmx is available", async () => {
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve("<div>teams</div>"),
    });

    window.htmx = { process: vi.fn() };
    performTeamSelectorSearch("");
    await vi.runAllTimersAsync();

    expect(window.htmx.process).toHaveBeenCalledWith(container);
  });

  test("shows error message on HTTP error", async () => {
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500 });

    performTeamSelectorSearch("test");
    await vi.runAllTimersAsync();

    expect(container.innerHTML).toContain("Failed to load teams");
    expect(container.dataset.loaded).toBeUndefined();
  });

  test("shows error message on network failure", async () => {
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockRejectedValue(new Error("Network error"));

    performTeamSelectorSearch("test");
    await vi.runAllTimersAsync();

    expect(container.innerHTML).toContain("Failed to load teams");
  });

  test("does not throw when retry button is missing from error UI", async () => {
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockRejectedValue(new Error("err"));

    // Mock querySelector so retry button lookup returns null
    const origQuerySelector = container.querySelector.bind(container);
    vi.spyOn(container, "querySelector").mockImplementation((selector) => {
      if (selector === '[data-action="retry-team-search"]') return null;
      return origQuerySelector(selector);
    });

    performTeamSelectorSearch("test");
    await vi.runAllTimersAsync();

    expect(container.innerHTML).toContain("Failed to load teams");
  });

  test("retry button calls searchTeamSelector on click", async () => {
    const container = document.createElement("div");
    container.id = "team-selector-items";
    document.body.appendChild(container);

    global.fetch = vi.fn().mockRejectedValue(new Error("err"));

    performTeamSelectorSearch("test");
    await vi.runAllTimersAsync();

    // Click the retry button — it resets dataset.loaded and calls searchTeamSelector
    const retryBtn = container.querySelector('[data-action="retry-team-search"]');
    expect(retryBtn).not.toBeNull();

    // Set up fetch to succeed on retry
    fetch.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("<div>retried</div>"),
    });

    retryBtn.click();
    vi.advanceTimersByTime(300);
    await vi.runAllTimersAsync();

    expect(container.innerHTML).toContain("retried");
  });
});

// ---------------------------------------------------------------------------
// selectTeamFromSelector
// ---------------------------------------------------------------------------
describe("selectTeamFromSelector", () => {
  function makeButton({ teamId = "t1", teamName = "My Team", isPersonal = "false" } = {}) {
    const btn = document.createElement("button");
    btn.dataset.teamId = teamId;
    btn.dataset.teamName = teamName;
    btn.dataset.teamIsPersonal = isPersonal;
    return btn;
  }

  test("updates Alpine.js state when __x is present", () => {
    const container = document.createElement("div");
    container.setAttribute("x-data", "");
    const alpineData = { selectedTeam: null, selectedTeamName: null, open: true };
    container.__x = { $data: alpineData };

    const btn = makeButton({ teamId: "t2", teamName: "Squad", isPersonal: "false" });
    container.appendChild(btn);
    document.body.appendChild(container);

    selectTeamFromSelector(btn);

    expect(alpineData.selectedTeam).toBe("t2");
    expect(alpineData.selectedTeamName).toBe("🏢 Squad");
    expect(alpineData.open).toBe(false);
  });

  test("sets personal team name with 👤 prefix", () => {
    const container = document.createElement("div");
    container.setAttribute("x-data", "");
    const alpineData = { selectedTeam: null, selectedTeamName: null, open: true };
    container.__x = { $data: alpineData };

    const btn = makeButton({ teamId: "personal1", teamName: "John", isPersonal: "true" });
    container.appendChild(btn);
    document.body.appendChild(container);

    selectTeamFromSelector(btn);

    expect(alpineData.selectedTeamName).toBe("👤 John");
  });

  test("does not throw when no Alpine.js __x present", () => {
    const container = document.createElement("div");
    container.setAttribute("x-data", "");
    // No __x

    const btn = makeButton();
    container.appendChild(btn);
    document.body.appendChild(container);

    expect(() => selectTeamFromSelector(btn)).not.toThrow();
  });

  test("does not throw when button has no parent x-data container", () => {
    const btn = makeButton();
    document.body.appendChild(btn);

    expect(() => selectTeamFromSelector(btn)).not.toThrow();
  });

  test("clears search input when present", () => {
    const searchInput = document.createElement("input");
    searchInput.id = "team-selector-search";
    searchInput.value = "some query";
    document.body.appendChild(searchInput);

    const btn = makeButton();
    document.body.appendChild(btn);

    selectTeamFromSelector(btn);

    expect(searchInput.value).toBe("");
  });

  test("resets loaded flag on items container", () => {
    const itemsContainer = document.createElement("div");
    itemsContainer.id = "team-selector-items";
    itemsContainer.dataset.loaded = "true";
    document.body.appendChild(itemsContainer);

    const btn = makeButton();
    document.body.appendChild(btn);

    selectTeamFromSelector(btn);

    expect(itemsContainer.dataset.loaded).toBeUndefined();
  });

  test("calls window.updateTeamContext with teamId", () => {
    window.updateTeamContext = vi.fn();
    const btn = makeButton({ teamId: "team-42" });
    document.body.appendChild(btn);

    selectTeamFromSelector(btn);

    expect(window.updateTeamContext).toHaveBeenCalledWith("team-42");
  });

  test("does not throw when window.updateTeamContext is not defined", () => {
    delete window.updateTeamContext;
    const btn = makeButton();
    document.body.appendChild(btn);

    expect(() => selectTeamFromSelector(btn)).not.toThrow();
  });
});
