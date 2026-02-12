/**
 * Unit tests for admin.js formatting functions.
 */

import { describe, test, expect, beforeAll, afterAll } from "vitest";
import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";

let win;

beforeAll(() => {
  win = loadAdminJs();
});

afterAll(() => {
  cleanupAdminJs();
});

// ---------------------------------------------------------------------------
// formatValue
// ---------------------------------------------------------------------------
describe("formatValue", () => {
  const f = () => win.formatValue;

  test('returns "N/A" for null', () => {
    expect(f()(null, "any")).toBe("N/A");
  });

  test('returns "N/A" for undefined', () => {
    expect(f()(undefined, "any")).toBe("N/A");
  });

  test('returns "N/A" for "N/A" string', () => {
    expect(f()("N/A", "any")).toBe("N/A");
  });

  test("formats avgResponseTime with 3 decimal places and ms suffix", () => {
    expect(f()(1.23456, "avgResponseTime")).toBe("1.235 ms");
  });

  test("formats avgResponseTime zero", () => {
    expect(f()(0, "avgResponseTime")).toBe("0.000 ms");
  });

  test('returns "N/A" for non-numeric avgResponseTime', () => {
    expect(f()("not-a-number", "avgResponseTime")).toBe("N/A");
  });

  test("formats successRate with % suffix", () => {
    expect(f()(95, "successRate")).toBe("95%");
  });

  test("formats errorRate with % suffix", () => {
    expect(f()(5, "errorRate")).toBe("5%");
  });

  test('returns "N/A" for NaN number', () => {
    expect(f()(NaN, "other")).toBe("N/A");
  });

  test("returns string representation for normal values", () => {
    expect(f()(42, "totalExecutions")).toBe("42");
  });

  test('returns "N/A" for empty string', () => {
    expect(f()("", "any")).toBe("N/A");
  });

  test('returns "N/A" for whitespace-only string', () => {
    expect(f()("   ", "any")).toBe("N/A");
  });

  test("returns string for non-empty string values", () => {
    expect(f()("hello", "any")).toBe("hello");
  });
});

// ---------------------------------------------------------------------------
// formatNumber
// ---------------------------------------------------------------------------
describe("formatNumber", () => {
  const f = () => win.formatNumber;

  test("formats integer with locale separators", () => {
    const result = f()(1000);
    // Locale-dependent, but should contain the digits
    expect(result).toContain("1");
    expect(result).toContain("000");
  });

  test("formats zero", () => {
    expect(f()(0)).toBe("0");
  });

  test("formats negative number", () => {
    const result = f()(-1234);
    expect(result).toContain("1");
    expect(result).toContain("234");
  });
});

// ---------------------------------------------------------------------------
// formatLastUsed
// ---------------------------------------------------------------------------
describe("formatLastUsed", () => {
  const f = () => win.formatLastUsed;

  test('returns "Never" for null', () => {
    expect(f()(null)).toBe("Never");
  });

  test('returns "Never" for undefined', () => {
    expect(f()(undefined)).toBe("Never");
  });

  test('returns "Never" for empty string', () => {
    expect(f()("")).toBe("Never");
  });

  // NOTE: formatLastUsed uses Date.now() inside JSDOM's sandbox, so
  // vi.useFakeTimers() does NOT affect it. We use real-time-relative
  // timestamps instead.

  test('returns "Just now" for timestamp < 60 seconds ago', () => {
    const thirtySecsAgo = Date.now() - 30 * 1000;
    expect(f()(thirtySecsAgo)).toBe("Just now");
  });

  test('returns "X min ago" for timestamp < 60 minutes ago', () => {
    const tenMinsAgo = Date.now() - 10 * 60 * 1000;
    expect(f()(tenMinsAgo)).toBe("10 min ago");
  });

  test("handles epoch seconds (< 1e12)", () => {
    const epochSecs = Math.floor(Date.now() / 1000) - 30;
    expect(f()(epochSecs)).toBe("Just now");
  });

  test("handles epoch string", () => {
    const epochStr = String(Date.now() - 5000);
    expect(f()(epochStr)).toBe("Just now");
  });

  test("handles ISO string with Z suffix", () => {
    const recentIso = new Date(Date.now() - 10 * 1000).toISOString();
    expect(f()(recentIso)).toBe("Just now");
  });

  test("handles ISO string without Z suffix (appends Z)", () => {
    // Remove trailing Z to test the auto-append behavior
    const recentIso = new Date(Date.now() - 10 * 1000)
      .toISOString()
      .replace("Z", "");
    expect(f()(recentIso)).toBe("Just now");
  });

  test('returns "Never" for invalid date string', () => {
    expect(f()("not-a-date")).toBe("Never");
  });

  test("returns formatted date for old timestamps", () => {
    const result = f()("2025-01-01T00:00:00Z");
    // Should contain date components (locale-dependent)
    expect(result).toContain("2025");
    expect(result).toContain("Jan");
  });
});

// ---------------------------------------------------------------------------
// formatFileSize
// ---------------------------------------------------------------------------
describe("formatFileSize", () => {
  const f = () => win.formatFileSize;

  test('returns "0 Bytes" for zero', () => {
    expect(f()(0)).toBe("0 Bytes");
  });

  test("formats bytes", () => {
    expect(f()(500)).toBe("500 Bytes");
  });

  test("formats kilobytes", () => {
    expect(f()(1024)).toBe("1 KB");
  });

  test("formats megabytes", () => {
    expect(f()(1048576)).toBe("1 MB");
  });

  test("formats gigabytes", () => {
    expect(f()(1073741824)).toBe("1 GB");
  });

  test("formats fractional kilobytes", () => {
    const result = f()(1536); // 1.5 KB
    expect(result).toBe("1.5 KB");
  });

  test("rounds to 2 decimal places", () => {
    const result = f()(1234567); // ~1.18 MB
    expect(result).toMatch(/^\d+\.?\d{0,2} MB$/);
  });
});

// ---------------------------------------------------------------------------
// formatTimestamp
// ---------------------------------------------------------------------------
describe("formatTimestamp", () => {
  const f = () => win.formatTimestamp;

  test("formats ISO timestamp to en-US locale string", () => {
    const result = f()("2025-06-15T14:30:45Z");
    // Should contain month, day, time components
    expect(result).toContain("Jun");
    expect(result).toContain("15");
  });

  test("formats epoch milliseconds", () => {
    const result = f()(1718458245000);
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// formatDate
// ---------------------------------------------------------------------------
describe("formatDate", () => {
  const f = () => win.formatDate;

  test("formats ISO date string", () => {
    const result = f()("2025-06-15T00:00:00Z");
    expect(result).toContain("Jun");
    expect(result).toContain("15");
    expect(result).toContain("2025");
  });

  test("formats date-only string", () => {
    const result = f()("2025-01-01");
    expect(result).toContain("Jan");
    expect(result).toContain("2025");
  });

  test("returns 'Invalid Date' for unparseable string (V8 behavior)", () => {
    // In V8/JSDOM, new Date("not-a-date").toLocaleDateString() returns
    // "Invalid Date" rather than throwing, so the catch branch is not hit.
    const result = f()("not-a-date");
    expect(result).toBe("Invalid Date");
  });
});

// ---------------------------------------------------------------------------
// truncateText
// ---------------------------------------------------------------------------
describe("truncateText", () => {
  const f = () => win.truncateText;

  test("returns empty string for null", () => {
    expect(f()(null, 10)).toBe("");
  });

  test("returns empty string for undefined", () => {
    expect(f()(undefined, 10)).toBe("");
  });

  test("returns empty string for empty input", () => {
    expect(f()("", 10)).toBe("");
  });

  test("returns text unchanged when shorter than maxLength", () => {
    expect(f()("hello", 10)).toBe("hello");
  });

  test("returns text unchanged when exactly maxLength", () => {
    expect(f()("hello", 5)).toBe("hello");
  });

  test("truncates and adds ellipsis when exceeding maxLength", () => {
    expect(f()("hello world", 5)).toBe("hello...");
  });

  test("truncates to 0 length", () => {
    expect(f()("hello", 0)).toBe("...");
  });
});
