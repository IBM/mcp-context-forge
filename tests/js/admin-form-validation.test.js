/**
 * Unit tests for setupFormValidation() name-field selection logic.
 *
 * Verifies that only technical name inputs receive blur validation,
 * and that displayName / hidden name fields are correctly excluded.
 */

import {
    describe,
    test,
    expect,
    beforeAll,
    beforeEach,
    afterAll,
} from "vitest";
import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";

let win;
let doc;

beforeAll(() => {
    win = loadAdminJs();
    win.MAX_NAME_LENGTH = 200;
    doc = win.document;
});

afterAll(() => {
    cleanupAdminJs();
});

beforeEach(() => {
    doc.body.textContent = "";
});

/**
 * Build a minimal form with the given input elements,
 * call setupFormValidation(), and return the form.
 */
function buildForm(inputs) {
    const form = doc.createElement("form");
    inputs.forEach(({ name, type, value, id }) => {
        const wrapper = doc.createElement("div");
        const input = doc.createElement("input");
        input.name = name;
        if (type) input.type = type;
        if (value !== undefined) input.value = value;
        if (id) input.id = id;
        wrapper.appendChild(input);
        form.appendChild(wrapper);
    });
    doc.body.appendChild(form);
    win.setupFormValidation();
    return form;
}

/** Dispatch a blur event on the given element. */
function blur(el) {
    el.dispatchEvent(new win.Event("blur"));
}

// ---------------------------------------------------------------------------
// setupFormValidation — name field selection
// ---------------------------------------------------------------------------
describe("setupFormValidation name-field selection", () => {
    test("validates visible input[name='name']", () => {
        const form = buildForm([{ name: "name", type: "text", value: "" }]);
        const input = form.querySelector('input[name="name"]');
        blur(input);
        // Empty name triggers validation error
        expect(input.validity.customError).toBe(true);
    });

    test("validates input[name='customName']", () => {
        const form = buildForm([
            { name: "customName", type: "text", value: "" },
        ]);
        const input = form.querySelector('input[name="customName"]');
        blur(input);
        expect(input.validity.customError).toBe(true);
    });

    test("does NOT validate input[name='displayName']", () => {
        const form = buildForm([
            { name: "displayName", type: "text", value: "" },
        ]);
        const input = form.querySelector('input[name="displayName"]');
        blur(input);
        // displayName is excluded — no custom validity set
        expect(input.validity.customError).toBe(false);
    });

    test("does NOT validate input[name='display_name']", () => {
        const form = buildForm([
            { name: "display_name", type: "text", value: "" },
        ]);
        const input = form.querySelector('input[name="display_name"]');
        blur(input);
        expect(input.validity.customError).toBe(false);
    });

    test("does NOT validate hidden input[name='name']", () => {
        const form = buildForm([{ name: "name", type: "hidden", value: "" }]);
        const input = form.querySelector('input[name="name"]');
        blur(input);
        expect(input.validity.customError).toBe(false);
    });

    test("validates valid name and clears error styling", () => {
        const form = buildForm([
            {
                name: "name",
                type: "text",
                value: "my-tool",
                id: "tool-name",
            },
        ]);
        const input = form.querySelector('input[name="name"]');
        blur(input);
        expect(input.validity.customError).toBe(false);
        expect(input.classList.contains("border-red-500")).toBe(false);
    });

    test("shows error styling on invalid name", () => {
        const form = buildForm([{ name: "name", type: "text", value: "" }]);
        const input = form.querySelector('input[name="name"]');
        blur(input);
        expect(input.classList.contains("border-red-500")).toBe(true);
    });

    test("form with both name and displayName only validates name", () => {
        const form = buildForm([
            { name: "name", type: "text", value: "" },
            { name: "displayName", type: "text", value: "" },
        ]);
        const nameInput = form.querySelector('input[name="name"]');
        const displayInput = form.querySelector('input[name="displayName"]');

        blur(nameInput);
        blur(displayInput);

        // Only the technical name field gets validation
        expect(nameInput.validity.customError).toBe(true);
        expect(displayInput.validity.customError).toBe(false);
    });

    test("edit form: hidden name excluded, customName validated", () => {
        const form = buildForm([
            { name: "name", type: "hidden", value: "original-name" },
            { name: "customName", type: "text", value: "" },
            { name: "displayName", type: "text", value: "" },
        ]);
        const hiddenName = form.querySelector('input[name="name"]');
        const customName = form.querySelector('input[name="customName"]');
        const displayName = form.querySelector('input[name="displayName"]');

        blur(hiddenName);
        blur(customName);
        blur(displayName);

        expect(hiddenName.validity.customError).toBe(false);
        expect(customName.validity.customError).toBe(true);
        expect(displayName.validity.customError).toBe(false);
    });
});
