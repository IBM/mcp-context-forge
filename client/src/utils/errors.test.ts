import { describe, it, expect, vi, beforeEach } from "vitest";
import { sanitizeError, withErrorHandling, extractApiErrorDetail } from "./errors";

describe("sanitizeError", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  it("returns network error message for network errors", () => {
    expect(sanitizeError(new Error("network failure"))).toBe(
      "Network error. Please check your connection and try again.",
    );
  });

  it("returns network error message for timeout errors", () => {
    expect(sanitizeError(new Error("timeout occurred"))).toBe(
      "Network error. Please check your connection and try again.",
    );
  });

  it("returns network error message for fetch errors", () => {
    expect(sanitizeError(new Error("fetch failed"))).toBe(
      "Network error. Please check your connection and try again.",
    );
  });

  it("returns auth error for 401", () => {
    expect(sanitizeError(new Error("401 error"))).toBe(
      "Authentication required. Please log in again.",
    );
  });

  it("returns auth error for unauthorized", () => {
    expect(sanitizeError(new Error("unauthorized access"))).toBe(
      "Authentication required. Please log in again.",
    );
  });

  it("returns permission error for 403", () => {
    expect(sanitizeError(new Error("403 forbidden"))).toBe(
      "You don't have permission to perform this action.",
    );
  });

  it("returns permission error for forbidden", () => {
    expect(sanitizeError(new Error("forbidden resource"))).toBe(
      "You don't have permission to perform this action.",
    );
  });

  it("returns not found error for 404", () => {
    expect(sanitizeError(new Error("404 error"))).toBe("The requested resource was not found.");
  });

  it("returns not found error for not found message", () => {
    expect(sanitizeError(new Error("resource not found"))).toBe(
      "The requested resource was not found.",
    );
  });

  it("returns server error for 500", () => {
    expect(sanitizeError(new Error("500 internal server error"))).toBe(
      "Server error. Please try again later.",
    );
  });

  it("returns server error for 502", () => {
    expect(sanitizeError(new Error("502 bad gateway"))).toBe(
      "Server error. Please try again later.",
    );
  });

  it("returns server error for 503", () => {
    expect(sanitizeError(new Error("503 service unavailable"))).toBe(
      "Server error. Please try again later.",
    );
  });

  it("returns generic message for unmatched Error", () => {
    expect(sanitizeError(new Error("some random error"))).toBe(
      "An error occurred. Please try again.",
    );
  });

  it("returns unexpected error for non-Error objects", () => {
    expect(sanitizeError("string error")).toBe("An unexpected error occurred.");
    expect(sanitizeError(null)).toBe("An unexpected error occurred.");
    expect(sanitizeError(undefined)).toBe("An unexpected error occurred.");
    expect(sanitizeError(42)).toBe("An unexpected error occurred.");
  });
});

describe("withErrorHandling", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  it("returns result on success", async () => {
    const result = await withErrorHandling(() => Promise.resolve("ok"), "test");
    expect(result).toBe("ok");
  });

  it("returns null on error", async () => {
    const result = await withErrorHandling(
      () => Promise.reject(new Error("network error")),
      "test operation",
    );
    expect(result).toBeNull();
  });

  it("logs error message on failure", async () => {
    const consoleSpy = vi.spyOn(console, "error");
    await withErrorHandling(() => Promise.reject(new Error("fetch error")), "my operation failed");
    expect(consoleSpy).toHaveBeenCalledWith("my operation failed", expect.any(String));
  });

  it("handles non-Error throws", async () => {
    const result = await withErrorHandling(() => Promise.reject("plain string error"), "test");
    expect(result).toBeNull();
  });
});

describe("extractApiErrorDetail", () => {
  it("returns null for null", () => {
    expect(extractApiErrorDetail(null)).toBeNull();
  });

  it("returns null for undefined", () => {
    expect(extractApiErrorDetail(undefined)).toBeNull();
  });

  it("returns null for a string", () => {
    expect(extractApiErrorDetail("error")).toBeNull();
  });

  it("returns null for a number", () => {
    expect(extractApiErrorDetail(42)).toBeNull();
  });

  it("returns null when body has no detail field", () => {
    expect(extractApiErrorDetail({ message: "Something went wrong" })).toBeNull();
  });

  it("returns null when detail is null", () => {
    expect(extractApiErrorDetail({ detail: null })).toBeNull();
  });

  it("returns null when detail is an empty string", () => {
    expect(extractApiErrorDetail({ detail: "" })).toBeNull();
  });

  it("returns string detail", () => {
    expect(extractApiErrorDetail({ detail: "Tool not found" })).toBe("Tool not found");
  });

  it("returns first msg from a FastAPI validation error array", () => {
    expect(
      extractApiErrorDetail({
        detail: [{ msg: "field required" }, { msg: "invalid value" }],
      }),
    ).toBe("field required");
  });

  it("returns null when detail is an empty array", () => {
    expect(extractApiErrorDetail({ detail: [] })).toBeNull();
  });

  it("returns null when the array item has no msg property", () => {
    expect(extractApiErrorDetail({ detail: [{ loc: ["body", "name"] }] })).toBeNull();
  });
});
