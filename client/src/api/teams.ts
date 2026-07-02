import { api } from "@/api/client";
import type { Team } from "@/types/team";

interface CreateTeamPayload {
  name: string;
  description?: string;
  visibility: "private" | "public";
  max_members?: number;
}

export interface TeamMemberPayload {
  email: string;
  role: "owner" | "member";
}

export function createTeam(payload: CreateTeamPayload): Promise<Team> {
  return api.post<Team>("/teams", payload);
}

export function addTeamMember(teamId: string, member: TeamMemberPayload): Promise<void> {
  return api.post<void>(`/teams/${encodeURIComponent(teamId)}/members`, member);
}

export function deleteTeam(id: string): Promise<void> {
  return api.delete<void>(`/teams/${encodeURIComponent(id)}`);
}
