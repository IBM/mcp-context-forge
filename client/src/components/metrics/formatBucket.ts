import type { TimeWindow } from "@/hooks/useMetrics";

/**
 * Format a bucket timestamp for axis-tick display.
 *
 * Hour/day windows use HH:mm so multiple ticks fit on a narrow card.
 * Week windows use MMM dd because hour granularity would be noise at that zoom.
 * Returns the raw input if it can't be parsed, so a broken bucket from the
 * backend doesn't crash the chart.
 */
export function formatBucketTick(timestamp: string, window: TimeWindow): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;

  if (window === "week") {
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}
