import { api } from "@/api/client";
import type { Team, TeamMember, AddTeamMemberRequest, UpdateTeamMemberRequest } from "@/types/team";

interface CreateTeamPayload {
  name: string;
  description?: string;
  visibility: "private" | "public";
  max_members?: number;
}

interface UpdateTeamPayload {
  name?: string;
  description?: string;
  visibility?: "private" | "public";
  max_members?: number;
}

export function createTeam(payload: CreateTeamPayload): Promise<Team> {
  return api.post<Team>("/teams", payload);
}

export function updateTeam(id: string, payload: UpdateTeamPayload): Promise<Team> {
  return api.put<Team>(`/teams/${encodeURIComponent(id)}`, payload);
}

export function deleteTeam(id: string): Promise<void> {
  return api.delete<void>(`/teams/${encodeURIComponent(id)}`);
}

export function listTeamMembers(teamId: string): Promise<TeamMember[]> {
  // Default (no include_pagination) returns every team member as a bare array,
  // with no cursor metadata.
  return api.get<TeamMember[]>(`/teams/${encodeURIComponent(teamId)}/members`);
}

export function addTeamMember(teamId: string, data: AddTeamMemberRequest): Promise<void> {
  return api.post<void>(`/teams/${encodeURIComponent(teamId)}/members`, data);
}

export function updateTeamMember(
  teamId: string,
  userEmail: string,
  data: UpdateTeamMemberRequest,
): Promise<void> {
  return api.put<void>(
    `/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userEmail)}`,
    data,
  );
}

export function removeTeamMember(teamId: string, userEmail: string): Promise<void> {
  return api.delete<void>(
    `/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userEmail)}`,
  );
}
