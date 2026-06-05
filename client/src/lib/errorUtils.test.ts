import { describe, it, expect } from "vitest";
import { parseApiError } from "./errorUtils";

describe("parseApiError", () => {
  it("returns fallback when error is null", () => {
    expect(parseApiError(null, "fallback")).toBe("fallback");
  });

  it("returns fallback when error is a string", () => {
    expect(parseApiError("oops", "fallback")).toBe("fallback");
  });

  it("returns fallback when error has no body", () => {
    expect(parseApiError({}, "fallback")).toBe("fallback");
  });

  it("returns body.message for simple message format", () => {
    const error = { body: { message: "Something went wrong" } };
    expect(parseApiError(error, "fallback")).toBe("Something went wrong");
  });

  it("returns body.detail when it is a plain string", () => {
    const error = { body: { detail: "Gateway not found" } };
    expect(parseApiError(error, "fallback")).toBe("Gateway not found");
  });

  it("returns body.detail.message when detail is an object with a message property", () => {
    const error = {
      body: { detail: { message: "A server with this name already exists", success: false } },
    };
    expect(parseApiError(error, "fallback")).toBe("A server with this name already exists");
  });

  it("returns fallback when detail is an object without a message property", () => {
    const error = { body: { detail: { success: false } } };
    expect(parseApiError(error, "fallback")).toBe("fallback");
  });

  it("returns joined validation messages when detail is an array", () => {
    const error = {
      body: {
        detail: [
          { loc: ["body", "name"], msg: "field required" },
          { loc: ["body", "url"], msg: "invalid URL" },
        ],
      },
    };
    expect(parseApiError(error, "fallback")).toBe("name: field required; url: invalid URL");
  });

  it("omits field prefix when loc has only one element", () => {
    const error = {
      body: {
        detail: [{ loc: ["name"], msg: "field required" }],
      },
    };
    expect(parseApiError(error, "fallback")).toBe("field required");
  });

  it("uses 'Invalid value' when validation error has no msg", () => {
    const error = {
      body: {
        detail: [{ loc: ["body", "url"] }],
      },
    };
    expect(parseApiError(error, "fallback")).toBe("url: Invalid value");
  });

  it("prefers body.message over body.detail string", () => {
    const error = { body: { message: "simple message", detail: "detail string" } };
    expect(parseApiError(error, "fallback")).toBe("simple message");
  });

  it("returns fallback when detail is an empty array", () => {
    const error = { body: { detail: [] } };
    expect(parseApiError(error, "fallback")).toBe("fallback");
  });
});
