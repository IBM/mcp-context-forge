export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

/**
 * Formats an ISO 8601 datetime string for display by stripping milliseconds and timezone marker.
 * @param value - ISO 8601 datetime string (e.g., "2024-01-15T10:30:45.123Z")
 * @param emptyLabel - Label to display when value is null/undefined (default: "Not available")
 * @returns Formatted datetime string (e.g., "2024-01-15T10:30:45") or empty label
 */
export function formatDateTime(value?: string | null, emptyLabel = "Not available"): string {
  if (!value) return emptyLabel;
  // Strip milliseconds and trailing timezone marker to match ISO display style
  return value.replace(/\.\d+Z?$/, "");
}

// Time divisions ordered smallest unit first, used to pick the coarsest unit
// that still renders a value below the next threshold (e.g. 90s -> "2 minutes
// ago", not "90 seconds").
const RELATIVE_DIVISIONS: { amount: number; unit: Intl.RelativeTimeFormatUnit }[] = [
  { amount: 60, unit: "second" },
  { amount: 60, unit: "minute" },
  { amount: 24, unit: "hour" },
  { amount: 7, unit: "day" },
  { amount: 4.34524, unit: "week" },
  { amount: 12, unit: "month" },
  { amount: Number.POSITIVE_INFINITY, unit: "year" },
];

// Intl.RelativeTimeFormat is comparatively expensive to construct, so cache one
// instance per locale.
const relativeFormatters = new Map<string, Intl.RelativeTimeFormat>();

function relativeFormatter(locale: string): Intl.RelativeTimeFormat {
  let formatter = relativeFormatters.get(locale);
  if (!formatter) {
    formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
    relativeFormatters.set(locale, formatter);
  }
  return formatter;
}

// Backend timestamps are UTC but are sometimes serialized without a zone
// designator (e.g. "2026-08-04T21:00:00"). Per the ECMAScript spec, a *zoneless*
// datetime is parsed as LOCAL time, which skews relative output by the viewer's
// UTC offset (a Pacific viewer sees a UTC "now" as "in 7 hours"). Append "Z" so
// a zoneless datetime is interpreted as UTC. Values that already carry "Z" or a
// numeric offset, and date-only strings (already UTC per spec), are left alone.
function assumeUtcIfZoneless(value: string): string {
  const isDateTime = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(value);
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value);
  return isDateTime && !hasZone ? `${value.replace(" ", "T")}Z` : value;
}

/**
 * Formats an ISO 8601 timestamp as a locale-aware relative time (e.g. "5 minutes
 * ago", "just now", "yesterday"). Shared util: the MCP roster (#5842), activity
 * feed (#5531), and System "Refreshed Xs ago" all render relative times.
 *
 * A zoneless datetime is treated as UTC (see `assumeUtcIfZoneless`) so relative
 * output does not drift with the viewer's timezone.
 *
 * Returns `null` for missing or unparseable input so callers can decide their
 * own fallback rather than showing a bogus "in 56 years".
 *
 * @param value - ISO 8601 datetime string, or null/undefined
 * @param options.now - Reference epoch millis (defaults to Date.now(); injectable for tests)
 * @param options.locale - BCP-47 locale for the formatter (defaults to "en")
 */
export function formatLastSeen(
  value?: string | null,
  options: { now?: number; locale?: string } = {},
): string | null {
  if (!value) return null;
  const then = Date.parse(assumeUtcIfZoneless(value));
  if (Number.isNaN(then)) return null;

  const { now = Date.now(), locale = "en" } = options;
  // Negative while in the past, which is what RelativeTimeFormat expects ("ago").
  let delta = (then - now) / 1000;

  for (const division of RELATIVE_DIVISIONS) {
    if (Math.abs(delta) < division.amount) {
      return relativeFormatter(locale).format(Math.round(delta), division.unit);
    }
    delta /= division.amount;
  }
  return null;
}
