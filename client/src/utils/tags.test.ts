import { describe, it, expect } from "vitest";
import { MAX_TAGS, getTagLabels } from "./tags";

describe("getTagLabels", () => {
  it("passes through plain string tags", () => {
    expect(getTagLabels(["a", "b"])).toEqual(["a", "b"]);
  });

  it("extracts the label from object tags", () => {
    expect(getTagLabels([{ label: "auth" }, "api"])).toEqual(["auth", "api"]);
  });

  it("returns an empty array for no tags", () => {
    expect(getTagLabels([])).toEqual([]);
  });
});

describe("MAX_TAGS", () => {
  it("is a positive shared limit", () => {
    expect(MAX_TAGS).toBeGreaterThan(0);
  });
});
