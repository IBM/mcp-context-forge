import { describe, it, expect } from "vitest";
import { formatBytes, formatLastSeen } from "./format";

describe("formatBytes", () => {
  it("formats 0 bytes correctly", () => {
    expect(formatBytes(0)).toBe("0 Bytes");
  });

  it("formats bytes correctly", () => {
    expect(formatBytes(500)).toBe("500 Bytes");
  });

  it("formats kilobytes correctly", () => {
    expect(formatBytes(1024)).toBe("1 KB");
    expect(formatBytes(1536)).toBe("1.5 KB");
  });

  it("formats megabytes correctly", () => {
    expect(formatBytes(1048576)).toBe("1 MB");
    expect(formatBytes(1572864)).toBe("1.5 MB");
  });

  it("formats gigabytes correctly", () => {
    expect(formatBytes(1073741824)).toBe("1 GB");
  });
});

describe("formatLastSeen", () => {
  // Fixed reference point so the relative output is deterministic.
  const now = Date.parse("2026-01-15T12:00:00Z");

  it("returns null for missing input", () => {
    expect(formatLastSeen(undefined, { now })).toBeNull();
    expect(formatLastSeen(null, { now })).toBeNull();
  });

  it("returns null for unparseable input", () => {
    expect(formatLastSeen("not-a-date", { now })).toBeNull();
  });

  it("formats a recent past time in seconds", () => {
    const value = new Date(now - 30_000).toISOString();
    expect(formatLastSeen(value, { now, locale: "en" })).toBe("30 seconds ago");
  });

  it("promotes to the coarsest unit below the next threshold", () => {
    // 100s reads in minutes ("2 minutes ago"), never "100 seconds ago".
    const value = new Date(now - 100_000).toISOString();
    expect(formatLastSeen(value, { now, locale: "en" })).toBe("2 minutes ago");
  });

  it("formats hours and days ago", () => {
    expect(formatLastSeen(new Date(now - 3 * 3_600_000).toISOString(), { now, locale: "en" })).toBe(
      "3 hours ago",
    );
    expect(
      formatLastSeen(new Date(now - 2 * 86_400_000).toISOString(), { now, locale: "en" }),
    ).toBe("2 days ago");
  });

  it("is locale-aware", () => {
    const value = new Date(now - 5 * 60_000).toISOString();
    const formatted = formatLastSeen(value, { now, locale: "es" });
    // Spanish output, not the English form. The exact inflection ("minutos" vs
    // "min") varies by ICU version, so match loosely rather than the full string.
    expect(formatted).toMatch(/hace\s+5\s+min/);
    expect(formatted).not.toMatch(/ago/);
  });

  it("treats a zoneless datetime as UTC, not local time", () => {
    // "11:00:00" with no zone is one hour before the 12:00Z reference. Without
    // the UTC assumption this would drift with the runner's timezone (e.g. a
    // Pacific runner would read it as "in 7 hours").
    expect(formatLastSeen("2026-01-15T11:00:00", { now, locale: "en" })).toBe("1 hour ago");
  });

  it("respects an explicit zone or offset when present", () => {
    expect(formatLastSeen("2026-01-15T12:00:00Z", { now, locale: "en" })).toBe("now");
    expect(formatLastSeen("2026-01-15T13:00:00+01:00", { now, locale: "en" })).toBe("now");
  });
});
