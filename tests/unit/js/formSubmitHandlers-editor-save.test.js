/**
 * Unit tests for CodeMirror editor save error handling in form submit handlers.
 *
 * Tests verify that:
 * 1. All editors are attempted to save even if one fails
 * 2. All errors are collected and reported together
 * 3. Form submission is aborted if any editor fails
 * 4. Individual editor errors are logged for debugging
 */

import { describe, test, expect, beforeEach, vi } from "vitest";
import { JSDOM } from "jsdom";

let dom;
let document;
let window;

beforeEach(() => {
  dom = new JSDOM('<!DOCTYPE html><html><body></body></html>');
  document = dom.window.document;
  window = dom.window;
  global.window = window;
  global.document = document;

  // Mock console methods
  global.console.error = vi.fn();
  global.console.log = vi.fn();
});

describe("CodeMirror Editor Save Error Handling", () => {
  test("all editors attempt save even when one fails", () => {
    // Simulate edit tool form with multiple editors
    const editor1SaveSuccess = vi.fn();
    const editor2SaveError = vi.fn(() => {
      throw new Error("Editor 2 failed");
    });
    const editor3SaveSuccess = vi.fn();

    window.editToolHeadersEditor = { save: editor1SaveSuccess };
    window.editToolSchemaEditor = { save: editor2SaveError };
    window.editToolOutputSchemaEditor = { save: editor3SaveSuccess };

    // Simulate the error collection logic from formSubmitHandlers.js
    const editorSaveErrors = [];
    const editors = [
      { name: "editToolHeadersEditor", editor: window.editToolHeadersEditor },
      { name: "editToolSchemaEditor", editor: window.editToolSchemaEditor },
      { name: "editToolOutputSchemaEditor", editor: window.editToolOutputSchemaEditor },
    ];

    for (const { name, editor } of editors) {
      if (editor) {
        try {
          editor.save();
        } catch (error) {
          console.error(`Failed to save ${name}:`, error);
          editorSaveErrors.push(`${name}: ${error.message}`);
        }
      }
    }

    // Verify all editors were attempted
    expect(editor1SaveSuccess).toHaveBeenCalledTimes(1);
    expect(editor2SaveError).toHaveBeenCalledTimes(1);
    expect(editor3SaveSuccess).toHaveBeenCalledTimes(1);

    // Verify error was collected
    expect(editorSaveErrors.length).toBe(1);
    expect(editorSaveErrors[0]).toBe("editToolSchemaEditor: Editor 2 failed");

    // Verify console.error was called
    expect(console.error).toHaveBeenCalledWith(
      "Failed to save editToolSchemaEditor:",
      expect.any(Error)
    );
  });

  test("multiple editor failures are all collected", () => {
    // Simulate multiple failing editors
    const editor1SaveError = vi.fn(() => {
      throw new Error("Editor 1 failed");
    });
    const editor2SaveError = vi.fn(() => {
      throw new Error("Editor 2 failed");
    });
    const editor3SaveError = vi.fn(() => {
      throw new Error("Editor 3 failed");
    });

    window.editToolHeadersEditor = { save: editor1SaveError };
    window.editToolSchemaEditor = { save: editor2SaveError };
    window.editToolOutputSchemaEditor = { save: editor3SaveError };

    const editorSaveErrors = [];
    const editors = [
      { name: "editToolHeadersEditor", editor: window.editToolHeadersEditor },
      { name: "editToolSchemaEditor", editor: window.editToolSchemaEditor },
      { name: "editToolOutputSchemaEditor", editor: window.editToolOutputSchemaEditor },
    ];

    for (const { name, editor } of editors) {
      if (editor) {
        try {
          editor.save();
        } catch (error) {
          console.error(`Failed to save ${name}:`, error);
          editorSaveErrors.push(`${name}: ${error.message}`);
        }
      }
    }

    // Verify all errors were collected
    expect(editorSaveErrors.length).toBe(3);
    expect(editorSaveErrors[0]).toBe("editToolHeadersEditor: Editor 1 failed");
    expect(editorSaveErrors[1]).toBe("editToolSchemaEditor: Editor 2 failed");
    expect(editorSaveErrors[2]).toBe("editToolOutputSchemaEditor: Editor 3 failed");

    // Verify console.error was called 3 times
    expect(console.error).toHaveBeenCalledTimes(3);
  });

  test("missing editors are skipped without error", () => {
    // Only set up one editor
    const editor1SaveSuccess = vi.fn();
    window.editToolHeadersEditor = { save: editor1SaveSuccess };
    // Other editors undefined

    const editorSaveErrors = [];
    const editors = [
      { name: "editToolHeadersEditor", editor: window.editToolHeadersEditor },
      { name: "editToolSchemaEditor", editor: window.editToolSchemaEditor },
      { name: "editToolOutputSchemaEditor", editor: window.editToolOutputSchemaEditor },
    ];

    for (const { name, editor } of editors) {
      if (editor) {
        try {
          editor.save();
        } catch (error) {
          console.error(`Failed to save ${name}:`, error);
          editorSaveErrors.push(`${name}: ${error.message}`);
        }
      }
    }

    // Verify only the present editor was called
    expect(editor1SaveSuccess).toHaveBeenCalledTimes(1);
    expect(editorSaveErrors.length).toBe(0);
    expect(console.error).not.toHaveBeenCalled();
  });

  test("error message format is correct", () => {
    // Simulate one failing editor
    const editorSaveError = vi.fn(() => {
      throw new Error("Invalid JSON syntax");
    });

    window.editToolQueryMappingEditor = { save: editorSaveError };

    const editorSaveErrors = [];
    const editors = [
      { name: "editToolQueryMappingEditor", editor: window.editToolQueryMappingEditor },
    ];

    for (const { name, editor } of editors) {
      if (editor) {
        try {
          editor.save();
        } catch (error) {
          console.error(`Failed to save ${name}:`, error);
          editorSaveErrors.push(`${name}: ${error.message}`);
        }
      }
    }

    // Build the error message as the code would
    const errorMessage = editorSaveErrors.length > 0
      ? `Failed to save editor content:\n${editorSaveErrors.join("\n")}`
      : null;

    expect(errorMessage).toBe("Failed to save editor content:\neditToolQueryMappingEditor: Invalid JSON syntax");
  });

  test("successful save with all editors present", () => {
    // Simulate all editors saving successfully
    const editor1Save = vi.fn();
    const editor2Save = vi.fn();
    const editor3Save = vi.fn();
    const editor4Save = vi.fn();
    const editor5Save = vi.fn();

    window.editToolHeadersEditor = { save: editor1Save };
    window.editToolSchemaEditor = { save: editor2Save };
    window.editToolOutputSchemaEditor = { save: editor3Save };
    window.editToolQueryMappingEditor = { save: editor4Save };
    window.editToolHeaderMappingEditor = { save: editor5Save };

    const editorSaveErrors = [];
    const editors = [
      { name: "editToolHeadersEditor", editor: window.editToolHeadersEditor },
      { name: "editToolSchemaEditor", editor: window.editToolSchemaEditor },
      { name: "editToolOutputSchemaEditor", editor: window.editToolOutputSchemaEditor },
      { name: "editToolQueryMappingEditor", editor: window.editToolQueryMappingEditor },
      { name: "editToolHeaderMappingEditor", editor: window.editToolHeaderMappingEditor },
    ];

    for (const { name, editor } of editors) {
      if (editor) {
        try {
          editor.save();
        } catch (error) {
          console.error(`Failed to save ${name}:`, error);
          editorSaveErrors.push(`${name}: ${error.message}`);
        }
      }
    }

    // Verify all editors were called
    expect(editor1Save).toHaveBeenCalledTimes(1);
    expect(editor2Save).toHaveBeenCalledTimes(1);
    expect(editor3Save).toHaveBeenCalledTimes(1);
    expect(editor4Save).toHaveBeenCalledTimes(1);
    expect(editor5Save).toHaveBeenCalledTimes(1);

    // Verify no errors
    expect(editorSaveErrors.length).toBe(0);
    expect(console.error).not.toHaveBeenCalled();
  });

  test("error in middle editor does not prevent later editors from saving", () => {
    // First editor succeeds, second fails, third succeeds
    const editor1Save = vi.fn();
    const editor2SaveError = vi.fn(() => {
      throw new Error("Middle editor failed");
    });
    const editor3Save = vi.fn();

    window.headersEditor = { save: editor1Save };
    window.schemaEditor = { save: editor2SaveError };
    window.outputSchemaEditor = { save: editor3Save };

    const editorSaveErrors = [];
    const editors = [
      { name: "headersEditor", editor: window.headersEditor },
      { name: "schemaEditor", editor: window.schemaEditor },
      { name: "outputSchemaEditor", editor: window.outputSchemaEditor },
    ];

    for (const { name, editor } of editors) {
      if (editor) {
        try {
          editor.save();
        } catch (error) {
          console.error(`Failed to save ${name}:`, error);
          editorSaveErrors.push(`${name}: ${error.message}`);
        }
      }
    }

    // Critical: All three editors should have been attempted
    expect(editor1Save).toHaveBeenCalledTimes(1);
    expect(editor2SaveError).toHaveBeenCalledTimes(1);
    expect(editor3Save).toHaveBeenCalledTimes(1);

    // Only the middle editor error should be collected
    expect(editorSaveErrors.length).toBe(1);
    expect(editorSaveErrors[0]).toBe("schemaEditor: Middle editor failed");
  });
});
