/**
 * Resource types for the Admin UI
 */

export interface Resource {
  id: string;
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
  gatewayId?: string;
  uriTemplate?: string;
  size: number;
  createdAt: string;
  updatedAt: string;
  enabled: boolean;
  metrics?: Record<string, unknown>;
  tags: string[];

  // Audit fields
  createdBy?: string;
  createdFromIp?: string;
  createdVia?: string;
  createdUserAgent?: string;
  modifiedBy?: string;
  modifiedFromIp?: string;
  modifiedVia?: string;
  modifiedUserAgent?: string;

  // Import/federation metadata
  importBatchId?: string;
  federationSource?: string;
  version: number;

  // Ownership/visibility
  teamId?: string;
  team?: string;
  ownerEmail?: string;
  visibility: "public" | "private" | "team";

  // Optional display metadata
  title?: string;
  annotations?: Record<string, unknown>;
  _meta?: Record<string, unknown>;

  content?: string | null;

  // UI-specific optional fields
  textContent?: string;
  binaryContent?: string; // Base64 encoded
  gatewaySlug?: string;
  serverIds?: string[];
}

export interface ResourceGroup {
  gatewaySlug: string;
  gatewayId?: string;
  resources: Resource[];
  isActive: boolean; // At least one resource is enabled
}

export interface ResourceCreateRequest {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
  uriTemplate?: string;
  content: string;
  tags?: string[];
  visibility?: "public" | "private" | "team";
  teamId?: string;
}

export interface ResourceUpdateRequest {
  name?: string;
  description?: string;
  mimeType?: string;
  content?: string;
  tags?: string[];
  enabled?: boolean;
}
