export type Visibility = "private" | "team" | "public";

/**
 * Base server interface with common fields
 */
export interface BaseServer {
  id: string;
  name: string;
  description?: string;
  enabled: boolean;
  visibility: Visibility;
  team_id?: string;
  team?: string;
  owner_email?: string;
}

/**
 * MCP Server types
 *
 * Note: Backend uses "Gateway" terminology and endpoints (/gateways),
 * but frontend displays these as "MCP Servers" to users.
 */
export interface MCPServerCapabilities {
  prompts?: Record<string, unknown>;
  resources?: Record<string, unknown>;
  tools?: Record<string, unknown>;
  completions?: Record<string, unknown>;
}

export interface MCPServer extends BaseServer {
  url: string;
  transport: "SSE" | "STREAMABLEHTTP";
  reachable: boolean;
  capabilities?: MCPServerCapabilities;
  last_seen?: string;
  lastSeen?: string;
  tool_count: number;
  toolCount?: number;
  created_at: string;
  createdAt?: string;
  updated_at: string;
  updatedAt?: string;
  slug?: string;
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

export interface VirtualServerTag {
  id?: string;
  label?: string;
  name?: string;
  value?: string;
  [key: string]: unknown;
}

/**
 * Virtual Server types
 *
 * Represents virtual servers from the /servers endpoint
 */
export interface VirtualServer extends Omit<BaseServer, "team_id" | "owner_email"> {
  description: string;
  icon: string;
  createdAt: string;
  updatedAt: string;
  associatedTools?: string[];
  associatedToolIds?: string[];
  associatedResources?: string[];
  associatedPrompts?: string[];
  associatedA2aAgents?: string[];
  metrics: Record<string, unknown> | null;
  tags?: Array<string | VirtualServerTag>;
  createdBy: string;
  createdFromIp: string;
  createdVia: string;
  createdUserAgent: string;
  modifiedBy: string | null;
  modifiedFromIp: string | null;
  modifiedVia: string | null;
  modifiedUserAgent: string | null;
  importBatchId: string | null;
  federationSource: string | null;
  version: number;
  teamId: string;
  team: string;
  ownerEmail: string;
  oauthEnabled: boolean;
  oauthConfig: Record<string, unknown> | null;
}

export interface VirtualServersResponse {
  servers?: VirtualServer[];
  nextCursor?: string | null;
}
