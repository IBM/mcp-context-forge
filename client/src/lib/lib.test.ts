import { describe, it, expect } from "vitest";
import { cn } from "./utils";
import { VALIDATION, PAGINATION } from "./constants";

// ─────────────────────────────────────────────
// cn() utility tests
// ─────────────────────────────────────────────
describe("cn utility", () => {
  it("merges two class names", () => {
    expect(cn("foo", "bar")).toBe("foo bar");
  });

  it("handles conditional classes (falsy values omitted)", () => {
    expect(cn("foo", false && "bar", "baz")).toBe("foo baz");
  });

  it("handles undefined/null inputs gracefully", () => {
    expect(cn("foo", undefined, null as unknown as string)).toBe("foo");
  });

  it("merges Tailwind conflict classes (last wins)", () => {
    // tailwind-merge: p-2 overrides p-4
    const result = cn("p-4", "p-2");
    expect(result).toBe("p-2");
  });

  it("handles array of classes", () => {
    const result = cn(["foo", "bar"]);
    expect(result).toContain("foo");
    expect(result).toContain("bar");
  });

  it("returns empty string for no args", () => {
    expect(cn()).toBe("");
  });

  it("handles object syntax (clsx style)", () => {
    const result = cn({ "text-red-500": true, "text-blue-500": false });
    expect(result).toContain("text-red-500");
    expect(result).not.toContain("text-blue-500");
  });

  it("merges complex multi-class string", () => {
    const result = cn("flex items-center", "justify-between gap-4");
    expect(result).toContain("flex");
    expect(result).toContain("items-center");
    expect(result).toContain("justify-between");
    expect(result).toContain("gap-4");
  });
});

// ─────────────────────────────────────────────
// Constants tests
// ─────────────────────────────────────────────
describe("VALIDATION constants", () => {
  it("MAX_EMAIL_LENGTH is 255", () => {
    expect(VALIDATION.MAX_EMAIL_LENGTH).toBe(255);
  });

  it("MAX_PASSWORD_LENGTH is 1000", () => {
    expect(VALIDATION.MAX_PASSWORD_LENGTH).toBe(1000);
  });

  it("MIN_PASSWORD_LENGTH is 8", () => {
    expect(VALIDATION.MIN_PASSWORD_LENGTH).toBe(8);
  });

  it("MAX_NAME_LENGTH is 255", () => {
    expect(VALIDATION.MAX_NAME_LENGTH).toBe(255);
  });
});

describe("PAGINATION constants", () => {
  it("DEFAULT_LIMIT is 25", () => {
    expect(PAGINATION.DEFAULT_LIMIT).toBe(25);
  });

  it("MIN_LIMIT is 1", () => {
    expect(PAGINATION.MIN_LIMIT).toBe(1);
  });

  it("MAX_LIMIT is 100", () => {
    expect(PAGINATION.MAX_LIMIT).toBe(100);
  });
});
