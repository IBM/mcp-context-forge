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
