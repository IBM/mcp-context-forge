/**
 * Unit tests for formFieldHandlers.js module
 * Tests: generateSchema, updateSchemaPreview, createParameterForm,
 *        handleAddPassthrough, searchTeamSelector, selectTeamFromSelector
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

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

import {
  generateSchema,
  updateSchemaPreview,
  createParameterForm,
} from "../../../mcpgateway/admin_ui/formFieldHandlers.js";
import { AppState } from "../../../mcpgateway/admin_ui/appState.js";

beforeEach(() => {
  AppState.parameterCount = 0;
});

afterEach(() => {
  document.body.innerHTML = "";
  AppState.parameterCount = 0;
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

    // Parameter 1
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

    // Parameter 2
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
    expect(schema.properties.query).toEqual({
      type: "string",
      description: "Search query",
    });
    expect(schema.properties.limit).toEqual({
      type: "number",
      description: "Result limit",
    });
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

    delete window.schemaEditor;
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
});
