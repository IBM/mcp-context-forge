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

export interface UpdateVirtualServerPayload {
  name: string;
  description: string;
  tags: string[];
  associated_tools?: string[];
  associated_resources?: string[];
  associated_prompts?: string[];
  team_id?: string;
  visibility: CreateServerDetails["visibility"];
  oauth_enabled: boolean;
}

export function buildCreateVirtualServerPayload(
  details: CreateServerDetails,
): CreateVirtualServerPayload {
  const teamId = details.visibility === "team" && details.teamId ? details.teamId : null;

  return {
    server: {
      name: details.name,
      description: details.description || undefined,
      icon: "",
      tags: details.tags ?? [],
      associated_tools: details.associatedTools ?? [],
      associated_resources: details.associatedResources ?? [],
      associated_prompts: details.associatedPrompts ?? [],
      associated_a2a_agents: [],
      team_id: teamId,
      visibility: details.visibility,
      oauth_enabled: details.oauthEnabled,
      oauth_config: details.oauthEnabled ? {} : undefined,
    },
    team_id: teamId,
    visibility: details.visibility,
  };
}

export function createVirtualServer(details: CreateServerDetails): Promise<VirtualServer> {
  return api.post<VirtualServer>("/servers", buildCreateVirtualServerPayload(details));
}

export function deleteVirtualServer(id: string): Promise<void> {
  return api.delete<void>(`/servers/${encodeURIComponent(id)}`);
}

export function buildUpdateVirtualServerPayload(
  details: CreateServerDetails,
): UpdateVirtualServerPayload {
  const payload: UpdateVirtualServerPayload = {
    name: details.name,
    description: details.description ?? "",
    tags: details.tags ?? [],
    visibility: details.visibility,
    oauth_enabled: details.oauthEnabled,
  };

  if (details.associatedTools !== undefined) {
    payload.associated_tools = details.associatedTools;
  }
  if (details.associatedResources !== undefined) {
    payload.associated_resources = details.associatedResources;
  }
  if (details.associatedPrompts !== undefined) {
    payload.associated_prompts = details.associatedPrompts;
  }
  if (details.visibility === "team" && details.teamId) {
    payload.team_id = details.teamId;
  }

  return payload;
}

export function updateVirtualServer(
  serverId: string,
  details: CreateServerDetails,
): Promise<VirtualServer> {
  return api.put<VirtualServer>(
    `/servers/${encodeURIComponent(serverId)}`,
    buildUpdateVirtualServerPayload(details),
  );
}
