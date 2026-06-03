import { describe, expect, it } from "vitest";
import { formatBucketTick } from "./formatBucket";

describe("formatBucketTick", () => {
  it("returns HH:mm for hour and day windows", () => {
    // Use UTC ISO so the assertion is independent of the test machine TZ —
    // we only care that the output is two `:`-separated digits, not the exact value.
    const hour = formatBucketTick("2026-01-01T12:34:00Z", "hour");
    const day = formatBucketTick("2026-01-01T12:34:00Z", "day");
    expect(hour).toMatch(/^\d{1,2}:\d{2}/);
    expect(day).toMatch(/^\d{1,2}:\d{2}/);
  });

  it("returns Month Day for week window", () => {
    const result = formatBucketTick("2026-01-15T00:00:00Z", "week");
    // Locale-dependent ("Jan 14"/"Jan 15"); just check it's letters + a number.
    expect(result).toMatch(/[A-Za-z]+\s+\d+/);
  });

  it("returns the raw input when timestamp is unparseable", () => {
    expect(formatBucketTick("not-a-date", "day")).toBe("not-a-date");
  });
});
