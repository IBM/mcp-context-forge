/**
 * Formats a date string as YYYY-MM-DDTHH:mm:ss in local time.
 * Returns `fallback` when the value is absent or unparseable.
 */
export function formatLocalDateTime(value: string | null | undefined, fallback: string): string {
  if (!value) return fallback;
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return fallback;
    const pad = (n: number) => n.toString().padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  } catch {
    return fallback;
  }
}
