/**
 * Fixture data for the Recent Activity widget.
 *
 * Used by the MSW handler in tests and (when VITE_USE_MOCK_ACTIVITY=true)
 * by the dev server before the backend ships /api/logs/activity.
 *
 * Timestamps are spread across the last few hours so the relative-time
 * formatter has something interesting to render.
 */

import type { ActivityItem } from "@/types/activity";

export const RECENT_ACTIVITY_FIXTURE: ActivityItem[] = [
  {
    id: "audit:1001",
    timestamp: "2026-06-08T17:53:24Z",
    source: "audit",
    title: "MCP server registered",
    description:
      "A new MCP server github-tools was registered by alice@acme.io. 14 tools were discovered and indexed.",
    status: "success",
    resource_type: "mcp_server",
    resource_name: "github-tools",
    actor: "alice@acme.io",
    correlation_id: "a1b2c3d4",
  },
  {
    id: "audit:1002",
    timestamp: "2026-06-08T16:12:21Z",
    source: "audit",
    title: "Virtual server published",
    description:
      "Virtual server payments-aggregator is now live with 6 federated tools from 3 upstream MCP servers.",
    status: "info",
    resource_type: "virtual_server",
    resource_name: "payments-aggregator",
    actor: "alice@acme.io",
    correlation_id: "b2c3d4e5",
  },
  {
    id: "security:2001",
    timestamp: "2026-06-08T16:03:20Z",
    source: "security",
    title: "Rate limit threshold reached",
    description:
      "Tool stripe.create_charge hit 80% of its per-minute rate limit (240/300). Consider raising the limit or adding a retry plugin.",
    status: "warning",
    resource_type: "tool",
    resource_name: "stripe.create_charge",
    actor: "system",
    correlation_id: "c3d4e5f6",
  },
  {
    id: "security:2002",
    timestamp: "2026-06-08T15:42:14Z",
    source: "security",
    title: "Authentication failed",
    description:
      "5 failed login attempts for bob@acme.io from 198.51.100.42 in the last 10 minutes. Account temporarily locked.",
    status: "error",
    resource_type: "user",
    resource_name: "bob@acme.io",
    actor: "bob@acme.io",
    correlation_id: "d4e5f6a7",
  },
  {
    id: "audit:1003",
    timestamp: "2026-06-07T12:55:07Z",
    source: "audit",
    title: "Plugin enabled",
    description:
      "Plugin pii-redactor v1.4.2 was enabled on virtual server customer-support by carol@acme.io.",
    status: "success",
    resource_type: "plugin",
    resource_name: "pii-redactor",
    actor: "carol@acme.io",
    correlation_id: "e5f6a7b8",
  },
  {
    id: "audit:1004",
    timestamp: "2026-06-07T11:57:14Z",
    source: "audit",
    title: "Team membership updated",
    description: "Member was added to team platform-infra with role developer.",
    status: "info",
    resource_type: "team",
    resource_name: "platform-infra",
    actor: "alice@acme.io",
    correlation_id: "f6a7b8c9",
  },
  {
    id: "security:2003",
    timestamp: "2026-06-06T13:58:16Z",
    source: "security",
    title: "MCP server degraded",
    description:
      "Health checks for jira-tools have failed 3 times in the last 5 minutes. Last successful response: 7m ago.",
    status: "warning",
    resource_type: "mcp_server",
    resource_name: "jira-tools",
    actor: "system",
    correlation_id: "a7b8c9d0",
  },
  {
    id: "security:2004",
    timestamp: "2026-06-06T13:51:27Z",
    source: "security",
    title: "Tool invocation failed",
    description:
      "Tool postgres.query returned connection refused for correlation f3a91b…. Affected caller: eve@acme.io.",
    status: "error",
    resource_type: "tool",
    resource_name: "postgres.query",
    actor: "eve@acme.io",
    correlation_id: "b8c9d0e1",
  },
  {
    id: "audit:1005",
    timestamp: "2026-06-05T18:59:22Z",
    source: "audit",
    title: "JWT secret rotated",
    description:
      "JWT_SECRET_KEY was rotated by platform-admin. All existing sessions remain valid until their original expiry.",
    status: "success",
    resource_type: "secret",
    resource_name: "JWT_SECRET_KEY",
    actor: "frank@acme.io",
    correlation_id: "c9d0e1f2",
  },
  {
    id: "audit:1006",
    timestamp: "2026-06-05T18:59:20Z",
    source: "audit",
    title: "A2A agent connected",
    description:
      "A2A agent research-orchestrator at agents.acme.io registered 3 skills and passed handshake verification.",
    status: "info",
    resource_type: "a2a_agent",
    resource_name: "research-orchestrator",
    actor: "system",
    correlation_id: "d0e1f2a3",
  },
];
