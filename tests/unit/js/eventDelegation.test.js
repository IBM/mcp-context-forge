/**
 * @vitest-environment jsdom
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { initializeEventDelegation, resetEventDelegation } from "../../../mcpgateway/admin_ui/eventDelegation.js";

describe("eventDelegation", () => {
  let container;
  let mockAdminFunction;

  beforeEach(() => {
    // Create a container for our test elements
    container = document.createElement("div");
    document.body.appendChild(container);

    // Mock window.Admin namespace
    mockAdminFunction = vi.fn();
    window.Admin = {
      testFunction: mockAdminFunction,
      showTab: vi.fn(),
      searchTeamSelector: vi.fn(),
      handleToggleSubmit: vi.fn(),
      nested: {
        function: vi.fn(),
      },
    };

    // Reset and initialize event delegation for each test
    resetEventDelegation();
    initializeEventDelegation();
  });

  afterEach(() => {
    // Clean up
    document.body.removeChild(container);
    delete window.Admin;
  });

  describe("click events", () => {
    it("handles simple click with no arguments", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action-click", "testFunction");
      container.appendChild(button);

      button.click();

      expect(mockAdminFunction).toHaveBeenCalledTimes(1);
    });

    it("handles click with single argument", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action-click", "testFunction");
      button.setAttribute("data-arg0", '"test-value"');
      container.appendChild(button);

      button.click();

      expect(mockAdminFunction).toHaveBeenCalledWith("test-value", expect.any(MouseEvent));
    });

    it("handles click with multiple arguments", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action-click", "testFunction");
      button.setAttribute("data-arg0", '"first"');
      button.setAttribute("data-arg1", '"second"');
      button.setAttribute("data-arg2", "123");
      container.appendChild(button);

      button.click();

      expect(mockAdminFunction).toHaveBeenCalledWith("first", "second", 123, expect.any(MouseEvent));
    });

    it("handles click with JSON argument", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action-click", "testFunction");
      button.setAttribute("data-arg0", '{"key":"value"}');
      container.appendChild(button);

      button.click();

      expect(mockAdminFunction).toHaveBeenCalledWith({ key: "value" }, expect.any(MouseEvent));
    });

    it("handles click with 'this' reference", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action-click", "testFunction");
      button.setAttribute("data-arg0", "this");
      container.appendChild(button);

      button.click();

      expect(mockAdminFunction).toHaveBeenCalledWith(button, expect.any(MouseEvent));
    });

    it("handles click with 'this.value' reference", () => {
      const input = document.createElement("input");
      input.value = "test-value";
      input.setAttribute("data-action-click", "testFunction");
      input.setAttribute("data-arg0", "this.value");
      container.appendChild(input);

      input.click();

      expect(mockAdminFunction).toHaveBeenCalledWith("test-value", expect.any(MouseEvent));
    });

    it("handles nested function paths", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action-click", "nested.function");
      container.appendChild(button);

      button.click();

      expect(window.Admin.nested.function).toHaveBeenCalledTimes(1);
    });

    it("prevents default for buttons", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action-click", "testFunction");
      container.appendChild(button);

      const event = new MouseEvent("click", { bubbles: true, cancelable: true });
      const preventDefaultSpy = vi.spyOn(event, "preventDefault");
      button.dispatchEvent(event);

      expect(preventDefaultSpy).toHaveBeenCalled();
    });

    it("does not prevent default when data-prevent-default is false", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action-click", "testFunction");
      button.setAttribute("data-prevent-default", "false");
      container.appendChild(button);

      const event = new MouseEvent("click", { bubbles: true, cancelable: true });
      const preventDefaultSpy = vi.spyOn(event, "preventDefault");
      button.dispatchEvent(event);

      expect(preventDefaultSpy).not.toHaveBeenCalled();
    });

    it("works with event bubbling (clicks on child element)", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action-click", "testFunction");
      const span = document.createElement("span");
      span.textContent = "Click me";
      button.appendChild(span);
      container.appendChild(button);

      span.click();

      expect(mockAdminFunction).toHaveBeenCalledTimes(1);
    });

    it("stops propagation when data-stop-propagation is true", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action-click", "testFunction");
      button.setAttribute("data-stop-propagation", "true");
      container.appendChild(button);

      const event = new MouseEvent("click", { bubbles: true, cancelable: true });
      const stopPropagationSpy = vi.spyOn(event, "stopPropagation");
      button.dispatchEvent(event);

      expect(stopPropagationSpy).toHaveBeenCalled();
    });
  });

  describe("input events", () => {
    it("handles input event with automatic value passing", () => {
      const input = document.createElement("input");
      input.setAttribute("data-action-input", "searchTeamSelector");
      container.appendChild(input);

      input.value = "test search";
      input.dispatchEvent(new Event("input", { bubbles: true }));

      expect(window.Admin.searchTeamSelector).toHaveBeenCalledWith("test search", expect.any(Event));
    });

    it("handles input event with explicit argument", () => {
      const input = document.createElement("input");
      input.setAttribute("data-action-input", "testFunction");
      input.setAttribute("data-arg0", '"explicit-value"');
      container.appendChild(input);

      input.value = "ignored";
      input.dispatchEvent(new Event("input", { bubbles: true }));

      expect(mockAdminFunction).toHaveBeenCalledWith("explicit-value", expect.any(Event));
    });
  });

  describe("change events", () => {
    it("handles change event on text input with automatic value", () => {
      const input = document.createElement("input");
      input.type = "text";
      input.setAttribute("data-action-change", "testFunction");
      container.appendChild(input);

      input.value = "changed value";
      input.dispatchEvent(new Event("change", { bubbles: true }));

      expect(mockAdminFunction).toHaveBeenCalledWith("changed value", expect.any(Event));
    });

    it("handles change event on checkbox with automatic checked state", () => {
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.setAttribute("data-action-change", "testFunction");
      container.appendChild(checkbox);

      checkbox.checked = true;
      checkbox.dispatchEvent(new Event("change", { bubbles: true }));

      expect(mockAdminFunction).toHaveBeenCalledWith(true, expect.any(Event));
    });

    it("handles change event on select element", () => {
      const select = document.createElement("select");
      select.setAttribute("data-action-change", "testFunction");
      const option = document.createElement("option");
      option.value = "option1";
      select.appendChild(option);
      container.appendChild(select);

      select.value = "option1";
      select.dispatchEvent(new Event("change", { bubbles: true }));

      expect(mockAdminFunction).toHaveBeenCalledWith("option1", expect.any(Event));
    });
  });

  describe("submit events", () => {
    it("handles form submit and prevents default", () => {
      const form = document.createElement("form");
      form.setAttribute("data-action-submit", "handleToggleSubmit");
      form.setAttribute("data-arg0", '"tools"');
      container.appendChild(form);

      const event = new Event("submit", { bubbles: true, cancelable: true });
      const preventDefaultSpy = vi.spyOn(event, "preventDefault");
      form.dispatchEvent(event);

      expect(window.Admin.handleToggleSubmit).toHaveBeenCalledWith(expect.any(Event), "tools");
      expect(preventDefaultSpy).toHaveBeenCalled();
    });

    it("prevents submit when function returns false", () => {
      window.Admin.handleToggleSubmit.mockReturnValue(false);

      const form = document.createElement("form");
      form.setAttribute("data-action-submit", "handleToggleSubmit");
      container.appendChild(form);

      const event = new Event("submit", { bubbles: true, cancelable: true });
      const preventDefaultSpy = vi.spyOn(event, "preventDefault");
      form.dispatchEvent(event);

      expect(preventDefaultSpy).toHaveBeenCalled();
    });

    it("does not prevent default when data-prevent-default is false", () => {
      const form = document.createElement("form");
      form.setAttribute("data-action-submit", "testFunction");
      form.setAttribute("data-prevent-default", "false");
      container.appendChild(form);

      const event = new Event("submit", { bubbles: true, cancelable: true });
      const preventDefaultSpy = vi.spyOn(event, "preventDefault");
      form.dispatchEvent(event);

      expect(preventDefaultSpy).not.toHaveBeenCalled();
    });
  });

  describe("keydown events", () => {
    it("handles keydown event", () => {
      const input = document.createElement("input");
      input.setAttribute("data-action-keydown", "testFunction");
      input.setAttribute("data-arg0", '"Enter"');
      container.appendChild(input);

      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));

      expect(mockAdminFunction).toHaveBeenCalledWith("Enter", expect.any(KeyboardEvent));
    });
  });

  describe("focus events", () => {
    it("handles focus event", () => {
      const input = document.createElement("input");
      input.setAttribute("data-action-focus", "testFunction");
      container.appendChild(input);

      input.dispatchEvent(new FocusEvent("focus", { bubbles: true }));

      expect(mockAdminFunction).toHaveBeenCalledTimes(1);
    });
  });

  describe("blur events", () => {
    it("handles blur event", () => {
      const input = document.createElement("input");
      input.setAttribute("data-action-blur", "testFunction");
      container.appendChild(input);

      input.dispatchEvent(new FocusEvent("blur", { bubbles: true }));

      expect(mockAdminFunction).toHaveBeenCalledTimes(1);
    });
  });

  describe("error handling", () => {
    it("logs error when function does not exist", () => {
      const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

      const button = document.createElement("button");
      button.setAttribute("data-action-click", "nonExistentFunction");
      container.appendChild(button);

      button.click();

      // When a function doesn't exist, it's undefined, which triggers "is not a function" error
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining("Action is not a function: nonExistentFunction")
      );

      consoleErrorSpy.mockRestore();
    });

    it("logs error when action is not a function", () => {
      window.Admin.notAFunction = "string value";
      const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

      const button = document.createElement("button");
      button.setAttribute("data-action-click", "notAFunction");
      container.appendChild(button);

      button.click();

      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining("Action is not a function: notAFunction")
      );

      consoleErrorSpy.mockRestore();
    });

    it("handles invalid JSON in data attributes gracefully", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action-click", "testFunction");
      button.setAttribute("data-arg0", "{invalid json}");
      container.appendChild(button);

      button.click();

      // Should pass the string as-is when JSON parsing fails
      expect(mockAdminFunction).toHaveBeenCalledWith("{invalid json}", expect.any(MouseEvent));
    });
  });

  describe("edge cases", () => {
    it("does nothing when no data-action attribute is present", () => {
      const button = document.createElement("button");
      container.appendChild(button);

      button.click();

      expect(mockAdminFunction).not.toHaveBeenCalled();
    });

    it("handles empty data-action attribute", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action-click", "");
      container.appendChild(button);

      button.click();

      expect(mockAdminFunction).not.toHaveBeenCalled();
    });

    it("handles multiple data-arg attributes in correct order", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action-click", "testFunction");
      button.setAttribute("data-arg0", '"first"');
      button.setAttribute("data-arg1", '"second"');
      button.setAttribute("data-arg2", '"third"');
      button.setAttribute("data-arg3", '"fourth"');
      container.appendChild(button);

      button.click();

      expect(mockAdminFunction).toHaveBeenCalledWith(
        "first",
        "second",
        "third",
        "fourth",
        expect.any(MouseEvent)
      );
    });

    it("handles this.dataset references", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action-click", "testFunction");
      button.setAttribute("data-arg0", "this.dataset");
      button.setAttribute("data-custom-value", "test123");
      container.appendChild(button);

      button.click();

      expect(mockAdminFunction).toHaveBeenCalledWith(
        expect.objectContaining({ customValue: "test123" }),
        expect.any(MouseEvent)
      );
    });
  });

  describe("confirmAction", () => {
    it("prevents default when user cancels confirm", () => {
      vi.spyOn(window, "confirm").mockReturnValue(false);
      const event = new Event("submit", { bubbles: true, cancelable: true });
      const preventDefaultSpy = vi.spyOn(event, "preventDefault");

      window.Admin.confirmAction(event, "Are you sure?");

      expect(preventDefaultSpy).toHaveBeenCalled();
    });

    it("does not prevent default when user confirms", () => {
      vi.spyOn(window, "confirm").mockReturnValue(true);
      const event = new Event("submit", { bubbles: true, cancelable: true });
      const preventDefaultSpy = vi.spyOn(event, "preventDefault");

      const result = window.Admin.confirmAction(event, "Are you sure?");

      expect(preventDefaultSpy).not.toHaveBeenCalled();
      expect(result).toBe(true);
    });
  });

  describe("initialization", () => {
    it("is idempotent - does not duplicate listeners", () => {
      window.Admin.idempotentTest = vi.fn();

      const button = document.createElement("button");
      button.setAttribute("data-action-click", "idempotentTest");
      container.appendChild(button);

      button.click();
      expect(window.Admin.idempotentTest).toHaveBeenCalledTimes(1);

      // Re-initialize should be a no-op
      initializeEventDelegation();

      button.click();
      expect(window.Admin.idempotentTest).toHaveBeenCalledTimes(2);

      delete window.Admin.idempotentTest;
    });

    it("attaches confirmAction to window.Admin", () => {
      expect(window.Admin.confirmAction).toBeDefined();
      expect(typeof window.Admin.confirmAction).toBe("function");
    });
  });
});
