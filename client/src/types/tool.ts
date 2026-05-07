export interface Tool {
  id: string;
  name: string;
  originalName: string;
  description?: string;
  originalDescription?: string;
  title?: string;
  gatewayId?: string;
  gatewaySlug: string;
  customName: string;
  customNameSlug: string;
  enabled: boolean;
  reachable: boolean;
  executionCount?: number;
  tags: Array<Record<string, string>>;
  integrationType: string;
  requestType: string;
  createdAt: string;
  updatedAt: string;
}

export interface ToolGroup {
  gatewaySlug: string;
  gatewayId?: string;
  tools: Tool[];
  isActive: boolean;
}
