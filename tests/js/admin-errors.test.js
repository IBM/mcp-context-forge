/**
 * Unit tests for admin.js error handling functions.
 */

import { describe, test, expect } from "vitest";
import { handleFetchError } from "../../mcpgateway/admin_ui/utils.js";

// ---------------------------------------------------------------------------
// handleFetchError
// ---------------------------------------------------------------------------
describe("handleFetchError", () => {
  test("returns timeout message for AbortError", () => {
    const error = new Error("The operation was aborted");
    error.name = "AbortError";
    const result = handleFetchError(error, "fetch data");
    expect(result).toContain("timed out");
    expect(result).toContain("fetch data");
  });

  test("returns server error message for HTTP errors", () => {
    const error = new Error("HTTP 500 Internal Server Error");
    const result = handleFetchError(error, "save settings");
    expect(result).toContain("Server error");
    expect(result).toContain("save settings");
    expect(result).toContain("HTTP 500");
  });

  test("returns network error message for NetworkError", () => {
    const error = new Error("NetworkError when attempting to fetch");
    const result = handleFetchError(error, "load data");
    expect(result).toContain("Network error");
    expect(result).toContain("load data");
  });

  test("returns network error message for Failed to fetch", () => {
    const error = new Error("Failed to fetch");
    const result = handleFetchError(error, "connect");
    expect(result).toContain("Network error");
    expect(result).toContain("connect");
  });

  test("returns generic error for unknown errors", () => {
    const error = new Error("Something unexpected");
    const result = handleFetchError(error, "process");
    expect(result).toContain("Failed to process");
    expect(result).toContain("Something unexpected");
  });

  test("uses default operation name", () => {
    const error = new Error("Something unexpected");
    const result = handleFetchError(error);
    expect(result).toContain("operation");
  });

  test("handles AbortError with default operation", () => {
    const error = new Error("aborted");
    error.name = "AbortError";
    const result = handleFetchError(error);
    expect(result).toContain("timed out");
    expect(result).toContain("operation");
  });
});
