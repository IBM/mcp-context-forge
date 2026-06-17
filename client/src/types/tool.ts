export interface Tool {
  id: string;
  name: string;
  originalName: string;
  description?: string;
  originalDescription?: string;
  title?: string;
  displayName?: string;
  gatewayId?: string;
  gatewaySlug: string;
  customName: string;
  customNameSlug: string;
  enabled: boolean;
  reachable: boolean;
  executionCount?: number;
  tags: Array<{ id: string; label: string } | string>;
  integrationType: string;
  requestType: string;
  url?: string | null;
  inputSchema?: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
  version?: number;
  visibility?: string;
  team?: string;
  teamId?: string;
  ownerEmail?: string;
  auth?: {
    authType?: string;
    username?: string;
    password?: string;
    token?: string;
    authHeaderKey?: string;
    authHeaderValue?: string;
    authHeaders?: Array<{ key: string; value: string }>;
  };
  createdAt: string;
  updatedAt: string;
  createdBy?: string;
  createdVia?: string;
  createdFromIp?: string | null;
  createdUserAgent?: string | null;
  modifiedBy?: string | null;
  modifiedFromIp?: string | null;
  modifiedVia?: string | null;
  modifiedUserAgent?: string | null;
}

export interface ToolGroup {
  gatewaySlug: string;
  gatewayId?: string;
  tools: Tool[];
  isActive: boolean;
}
