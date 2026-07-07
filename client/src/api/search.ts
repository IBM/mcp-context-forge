import { api } from "./client";

export type SearchEntityType =
  "servers" | "gateways" | "tools" | "resources" | "prompts" | "agents" | "teams" | "users";

export interface GlobalSearchItem {
  id?: string;
  name?: string;
  display_name?: string;
  displayName?: string;
  original_name?: string;
  originalName?: string;
  full_name?: string;
  email?: string;
  slug?: string;
  description?: string | null;
  url?: string | null;
  endpoint_url?: string | null;
  uri?: string;
  entity_type?: SearchEntityType;
  [key: string]: unknown;
}

export interface GlobalSearchGroup {
  entity_type: SearchEntityType;
  count: number;
  items: GlobalSearchItem[];
}

export interface GlobalSearchResponse {
  query: string;
  entity_types: SearchEntityType[];
  limit_per_type: number;
  results: Partial<Record<SearchEntityType, GlobalSearchItem[]>>;
  groups: GlobalSearchGroup[];
  items: GlobalSearchItem[];
  count: number;
}

export interface GlobalSearchParams {
  query: string;
  entityTypes: SearchEntityType[];
  limitPerType?: number;
  teamId?: string | null;
  signal?: AbortSignal;
}

export function searchAdminEntities({
  query,
  entityTypes,
  limitPerType = 8,
  teamId,
  signal,
}: GlobalSearchParams): Promise<GlobalSearchResponse> {
  const params = new URLSearchParams();
  params.set("q", query.trim());
  params.set("limit_per_type", limitPerType.toString());
  params.set("entity_types", entityTypes.join(","));

  if (teamId) {
    params.set("team_id", teamId);
  }

  return api.get<GlobalSearchResponse>(`/admin/search?${params.toString()}`, undefined, signal);
}
