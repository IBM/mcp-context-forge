/**
 * Recent Activity types
 *
 * Mirrors the planned GET /api/logs/activity response shape — the backend
 * mappers `_audit_to_activity` and `_security_to_activity` are the source of
 * truth for `status` and `description`. The UI MUST NOT re-derive these from
 * other fields.
 */

export type ActivityStatus = "success" | "error" | "warning" | "info";

export type ActivitySource = "audit" | "security";

export interface ActivityItem {
  /** Composite id, e.g. "audit:42" or "security:17". */
  id: string;
  /** ISO 8601 timestamp. */
  timestamp: string;
  source: ActivitySource;
  /** Server-rendered headline (e.g. "MCP server registered"). */
  title: string;
  /** Server-rendered one-line summary shown beneath the title. */
  description: string;
  status: ActivityStatus;
  resource_type: string;
  resource_name: string;
  actor: string;
  correlation_id: string;
}

export interface ActivityListResponse {
  items: ActivityItem[];
}
