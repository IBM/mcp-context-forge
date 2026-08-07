/**
 * Permissions API service.
 *
 * Wraps `GET /rbac/my/permissions`, which returns the caller's effective
 * permission set (team-scoped, already narrowed by token scoping). This is the
 * durable, real backend authority the UI uses to gate what it renders/fetches;
 * it is NOT the security boundary (endpoints enforce RBAC server-side).
 */

import { api } from "./client";

export const permissionsApi = {
  /**
   * List the current user's effective permissions.
   *
   * @param params.teamId Optional team context; omit for the "all teams" view.
   */
  listMine: (params?: { teamId?: string; signal?: AbortSignal }): Promise<string[]> => {
    const query = params?.teamId ? `?team_id=${encodeURIComponent(params.teamId)}` : "";
    return api.get<string[]>(`/rbac/my/permissions${query}`, undefined, params?.signal);
  },
};
