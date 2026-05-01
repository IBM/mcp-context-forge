/**
 * MCP Server types
 *
 * Note: Backend uses "Gateway" terminology and endpoints (/gateways),
 * but frontend displays these as "MCP Servers" to users.
 */

export interface MCPServer {
  id: string;
  name: string;
  url: string;
  description?: string;
  transport: "SSE" | "STREAMABLEHTTP";
  enabled: boolean;
  reachable: boolean;
  last_seen?: string;
  tool_count: number;
  created_at: string;
  updated_at: string;
  team_id?: string;
  team?: string;
  owner_email?: string;
  visibility: "private" | "team" | "public";
}

export interface PaginationMeta {
  page: number;
  per_page: number;
  total: number;
  total_pages: number;
}

export interface PaginationLinks {
  first?: string;
  prev?: string;
  next?: string;
  last?: string;
}

export interface ServersResponse {
  gateways: MCPServer[];
  nextCursor?: string | null;
}

export type ServerStatus = "draft" | "active" | "offline" | "warning";
