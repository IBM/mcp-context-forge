/**
 * Resource types for the Admin UI
 */

export interface Resource {
  id: string;
  uri: string;
  name: string;
  description?: string;
  title?: string;
  mimeType?: string;
  size?: number;
  uriTemplate?: string;
  createdAt: string;
  updatedAt: string;
  enabled: boolean;
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

  // Content
  textContent?: string;
  binaryContent?: string; // Base64 encoded

  // Relationships
  gatewayId?: string;
  gatewaySlug?: string;
  serverIds?: string[];
}

export interface ResourceGroup {
  gatewaySlug: string;
  gatewayId?: string;
  resources: Resource[];
  isActive: boolean; // At least one resource is enabled
}

export interface ResourcesResponse {
  data: Resource[];
  pagination: {
    page: number;
    perPage: number;
    total: number;
    totalPages: number;
  };
  links?: {
    first?: string;
    prev?: string;
    next?: string;
    last?: string;
  };
}

export interface ResourceCreateRequest {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
  uriTemplate?: string;
  content: string;
  tags?: string[];
  visibility?: "public" | "private";
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
