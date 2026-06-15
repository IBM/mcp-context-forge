import { describe, it, expect } from "vitest";
import { extractApiErrorDetail } from "./errors";

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
