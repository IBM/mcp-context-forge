import { api } from "@/api/client";
import type { CreateServerDetails } from "@/components/gateways/types";
import type { VirtualServer } from "@/types/server";

export interface CreateVirtualServerPayload {
  server: {
    name: string;
    description?: string;
    icon: string;
    tags: string[];
    associated_tools: string[];
    associated_resources: string[];
    associated_prompts: string[];
    associated_a2a_agents: string[];
    team_id: string | null;
    owner_email?: string;
    visibility: CreateServerDetails["visibility"];
    oauth_enabled: boolean;
    oauth_config?: Record<string, unknown>;
  };
  team_id: string | null;
  visibility: CreateServerDetails["visibility"];
}

export function buildCreateVirtualServerPayload(
  details: CreateServerDetails,
): CreateVirtualServerPayload {
  return {
    server: {
      name: details.name,
      description: details.description || undefined,
      icon: "",
      tags: details.tags ?? [],
      associated_tools: [],
      associated_resources: [],
      associated_prompts: [],
      associated_a2a_agents: [],
      team_id: null,
      visibility: details.visibility,
      oauth_enabled: details.oauthEnabled,
      oauth_config: details.oauthEnabled ? {} : undefined,
    },
    team_id: null,
    visibility: details.visibility,
  };
}

export function createVirtualServer(details: CreateServerDetails): Promise<VirtualServer> {
  return api.post<VirtualServer>("/servers", buildCreateVirtualServerPayload(details));
}
