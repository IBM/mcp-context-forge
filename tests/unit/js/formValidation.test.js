/**
 * Unit tests for formValidation.js module
 * Tests: setupFormValidation
 */

import { describe, test, expect, vi, afterEach } from "vitest";

import { setupFormValidation } from "../../../mcpgateway/admin_ui/formValidation.js";
import { validateInputName, validateUrl } from "../../../mcpgateway/admin_ui/security.js";

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  validateInputName: vi.fn((value, label) => {
    if (!value || value.trim() === "") {
      return { valid: false, error: `${label || "Name"} is required` };
    }
    if (value.includes("<script>")) {
      return { valid: false, error: "Invalid characters" };
    }
    return { valid: true, value: value.trim() };
  }),
  validateUrl: vi.fn((value, label) => {
    if (!value || value.trim() === "") {
      return { valid: false, error: `${label || "URL"} is required` };
    }
    if (!value.startsWith("http")) {
      return { valid: false, error: "Invalid URL format" };
    }
    return { valid: true, value: value.trim() };
  }),
}));

afterEach(() => {
  document.body.innerHTML = "";
  vi.clearAllMocks();
});

describe("setupFormValidation", () => {
  test("attaches blur listeners to name fields", () => {
    document.body.innerHTML = `
      <form>
        <div>
          <label for="test-name">Name</label>
          <input id="test-name" name="name" value="" />
          <p data-error-message-for="name" class="invisible"></p>
        </div>
      </form>
    `;

    setupFormValidation();

    const nameField = document.getElementById("test-name");
    nameField.value = "ValidName";
    nameField.dispatchEvent(new Event("blur"));

    // label is undefined in jsdom since innerText is not supported
    expect(validateInputName).toHaveBeenCalledWith("ValidName", undefined);
  });

  test("shows error on invalid name field", () => {
    document.body.innerHTML = `
      <form>
        <div>
          <label for="test-name">Name</label>
          <input id="test-name" name="name" value="" />
          <p data-error-message-for="name" class="invisible"></p>
        </div>
      </form>
    `;

    setupFormValidation();

    const nameField = document.getElementById("test-name");
    nameField.value = "<script>alert(1)</script>";
    nameField.dispatchEvent(new Event("blur"));

    expect(nameField.classList.contains("border-red-500")).toBe(true);
    const errorMsg = document.querySelector('[data-error-message-for="name"]');
    expect(errorMsg.classList.contains("invisible")).toBe(false);
  });

  test("clears error on valid name field", () => {
    document.body.innerHTML = `
      <form>
        <div>
          <label for="test-name">Name</label>
          <input id="test-name" name="name" value="" class="border-red-500" />
          <p data-error-message-for="name">Old error</p>
        </div>
      </form>
    `;

    setupFormValidation();

    const nameField = document.getElementById("test-name");
    nameField.value = "GoodName";
    nameField.dispatchEvent(new Event("blur"));

    expect(nameField.classList.contains("border-red-500")).toBe(false);
    const errorMsg = document.querySelector('[data-error-message-for="name"]');
    expect(errorMsg.classList.contains("invisible")).toBe(true);
  });

  test("attaches blur listeners to URL fields", () => {
    document.body.innerHTML = `
      <form>
        <div>
          <label for="test-url">URL</label>
          <input id="test-url" name="url" value="" required />
          <p data-error-message-for="url" class="invisible"></p>
        </div>
      </form>
    `;

    setupFormValidation();

    const urlField = document.getElementById("test-url");
    urlField.value = "http://example.com";
    urlField.dispatchEvent(new Event("blur"));

    expect(validateUrl).toHaveBeenCalledWith("http://example.com", undefined);
  });

  test("shows error on invalid URL field", () => {
    document.body.innerHTML = `
      <form>
        <div>
          <label for="test-url">URL</label>
          <input id="test-url" name="url" value="" required />
          <p data-error-message-for="url" class="invisible"></p>
        </div>
      </form>
    `;

    setupFormValidation();

    const urlField = document.getElementById("test-url");
    urlField.value = "not-a-url";
    urlField.dispatchEvent(new Event("blur"));

    expect(urlField.classList.contains("border-red-500")).toBe(true);
  });

  test("skips empty optional URL fields", () => {
    document.body.innerHTML = `
      <form>
        <div>
          <label for="test-url">URL</label>
          <input id="test-url" name="url" value="" />
          <p data-error-message-for="url" class="invisible"></p>
        </div>
      </form>
    `;

    setupFormValidation();

    const urlField = document.getElementById("test-url");
    urlField.value = "";
    urlField.dispatchEvent(new Event("blur"));

    // should not add error classes for empty optional fields
    expect(urlField.classList.contains("border-red-500")).toBe(false);
    expect(validateUrl).not.toHaveBeenCalled();
  });

  test("validates multiple forms on the page", () => {
    document.body.innerHTML = `
      <form>
        <input name="gateway-name" value="" />
      </form>
      <form>
        <input name="tool-name" value="" />
      </form>
    `;

    setupFormValidation();

    const inputs = document.querySelectorAll("input");
    inputs.forEach((input) => {
      input.value = "test";
      input.dispatchEvent(new Event("blur"));
    });

    expect(validateInputName).toHaveBeenCalledTimes(2);
  });
});
