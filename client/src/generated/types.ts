export interface ResourceRead {
  id: string;
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
  uriTemplate?: string;
  visibility: "public" | "private" | "team";
  teamId?: string;
  createdAt: string;
  updatedAt: string;
  enabled: boolean;
  gatewayId?: string;
}

export interface GatewayRead {
  id: string;
  name: string;
  slug: string;
}

export interface CursorPaginatedGatewaysResponse {
  items: GatewayRead[];
  nextCursor?: string;
}

export interface BodyCreateResourceResourcesPost {
  [key: string]: any;
}

export enum ResourceReadVisibility {
  Public = "public",
  Private = "private",
  Team = "team"
}

export interface ResourceCreate {
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

export interface ResourceUpdate {
  name?: string;
  description?: string;
  mimeType?: string;
  content?: string;
  tags?: string[];
  enabled?: boolean;
}
